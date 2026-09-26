"""The language model that writes a dish's brief and checks its picture.

Both jobs go through one call, `ask(prompt, images)`, so the backend is a choice
made once rather than a branch in every caller. There are two, and both cost
nothing:

    ClaudeCLI  the Claude Code CLI in headless mode, the engine scripts/translate.py
               uses -- a subscription already in use, no API key. On the laptop.
    Gemini     the Gemini API's free tier, with a free Google AI Studio key in
               GEMINI_API_KEY. In CI, where there is no claude CLI.

The failure that matters is `Unavailable`: a usage limit, a missing binary or
key is not something retrying the next dish will fix, so the caller stops asking
for the night instead of burning through the queue on errors. Anything else is
an `LLMError` for that one call.
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Sequence

import requests
from PIL import Image


class LLMError(RuntimeError):
    pass


class Unavailable(LLMError):
    """The backend cannot answer tonight: not installed, not logged in, out of quota."""


# Phrases the CLI uses when the subscription has run dry. Matched loosely: the
# wording has changed between releases, the meaning has not.
_LIMIT_RE = re.compile(
    r"usage limit|rate limit|session limit|limit reached|hit your .*limit|quota|credit balance"
    r"|not logged in|/login", re.I)

# What a judge needs to tell beef from chicken. Bigger costs tokens and says
# nothing more; the cards themselves are shown at 640px.
_IMAGE_EDGE = 768


def jpeg(data: bytes, edge: int = _IMAGE_EDGE) -> bytes:
    """Re-encode an image as a JPEG no larger than `edge` on its long side."""
    with Image.open(io.BytesIO(data)) as im:
        im = im.convert("RGB")
        im.thumbnail((edge, edge))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def parse_json(text: str) -> dict:
    """The JSON object in a model's answer, tolerating a stray fence or preamble."""
    if match := re.search(r"\{.*\}", text, re.S):
        text = match.group(0)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError(f"unparseable answer: {exc}: {text[:200]!r}")
    if not isinstance(value, dict):
        raise LLMError("answer was not a JSON object")
    return value


class ClaudeCLI:
    """`claude -p` with images passed inline as base64 content blocks."""

    def __init__(self, model: str = "sonnet", bin: str = "claude", timeout: int = 180):
        self.model = model
        self.bin = bin
        self.timeout = timeout

    @property
    def name(self) -> str:
        return f"claude-{self.model}"

    def available(self) -> bool:
        return shutil.which(self.bin) is not None

    def ask(self, prompt: str, images: Sequence[bytes] = (), system: str = "") -> str:
        if not self.available():
            raise Unavailable(f"{self.bin} not found")
        content = [
            {"type": "image",
             "source": {"type": "base64", "media_type": "image/jpeg",
                        "data": base64.b64encode(jpeg(img)).decode()}}
            for img in images
        ]
        content.append({"type": "text", "text": prompt})
        message = {"type": "user", "message": {"role": "user", "content": content}}

        cmd = [self.bin, "-p", "--model", self.model,
               "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
               "--strict-mcp-config", "--restricted", "--no-session-persistence"]
        if system:
            cmd += ["--system-prompt", system]
        try:
            # Outside the repo, like translate.py: none of the project's
            # context is wanted, and loading it would be paid for on every call.
            done = subprocess.run(
                cmd, input=json.dumps(message) + "\n", capture_output=True, text=True,
                timeout=self.timeout, cwd=tempfile.gettempdir(), check=False,
            )
        except subprocess.TimeoutExpired:
            raise LLMError(f"no answer in {self.timeout}s")

        result = None
        for line in done.stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "result":
                result = event
        if result is None:
            detail = (done.stderr or done.stdout).strip()[:300] or "claude failed"
            raise (Unavailable if _LIMIT_RE.search(detail) else LLMError)(detail)
        text = str(result.get("result") or "")
        if result.get("is_error"):
            raise (Unavailable if _LIMIT_RE.search(text) else LLMError)(text[:300] or "claude error")
        return text


GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# Gemma, not Gemini Flash: Flash's free tier is 20 requests a day per model,
# and a night of new dishes needs a hundred. Gemma 4 26B (a mixture of experts,
# answers in seconds) judged the eval set as well as Claude Sonnet did. It is a
# version, not an alias -- if Google retires it the calls fail as Unavailable and
# nothing unchecked is published; set GEMINI_MODEL to its successor.
DEFAULT_GEMINI_MODEL = "gemma-4-26b-a4b-it"


def _setting(name: str) -> str:
    """An environment variable, or failing that the same line in the repo's .env."""
    if value := os.getenv(name, "").strip():
        return value
    env = Path(__file__).resolve().parent.parent / ".env"
    if "PYTEST_CURRENT_TEST" not in os.environ and env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == name:
                return value.strip().strip("'\"")
    return ""


def _retry_after(body: dict) -> float | None:
    """The wait a 429 asks for, in seconds, if it names one."""
    for detail in (body.get("error") or {}).get("details") or []:
        if str(detail.get("@type", "")).endswith("RetryInfo"):
            match = re.match(r"([\d.]+)s", str(detail.get("retryDelay", "")))
            if match:
                return float(match.group(1))
    return None


class Gemini:
    """The Gemini API's free tier.

    Free within per-model rate limits; the price is that Google may use what is
    sent to improve its products, which for pictures of dining hall food is no
    price at all. A per-minute limit is waited out, as the 429 asks; one that
    will not clear within a minute is the daily quota, and that is Unavailable.
    An overloaded model (503) is retried with backoff, then also Unavailable.
    The key travels in a header, never in the URL, so it cannot end up in a log.
    """

    def __init__(self, model: str | None = None, key: str | None = None, timeout: int = 120,
                 session: requests.Session | None = None, retries: int = 3):
        self.model = model or _setting("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL
        self.key = key if key is not None else _setting("GEMINI_API_KEY")
        self.timeout = timeout
        self.session = session or requests.Session()
        self.retries = retries

    @property
    def name(self) -> str:
        return self.model

    def available(self) -> bool:
        return bool(self.key)

    def ask(self, prompt: str, images: Sequence[bytes] = (), system: str = "") -> str:
        if not self.key:
            raise Unavailable("GEMINI_API_KEY is not set")
        parts = [{"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(jpeg(img)).decode()}}
                 for img in images]
        parts.append({"text": prompt})
        config = {"temperature": 0, "maxOutputTokens": 2048}
        # JSON mode sends Gemma into a loop that only ends when the server hangs
        # up at 60s; asked plainly it answers in seconds, and parse_json() takes
        # the fence off. Gemini proper handles JSON mode fine.
        if not self.model.startswith("gemma"):
            config["responseMimeType"] = "application/json"
        body = {"contents": [{"role": "user", "parts": parts}], "generationConfig": config}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}

        for attempt in range(self.retries + 1):
            try:
                r = self.session.post(GEMINI_URL.format(model=self.model), json=body, timeout=self.timeout,
                                      headers={"x-goog-api-key": self.key})
            except requests.RequestException as exc:
                # A dropped connection is as passing as an overload.
                if attempt < self.retries:
                    time.sleep(10 * 3 ** attempt)
                    continue
                raise LLMError(f"Gemini request failed: {exc}")
            if r.status_code == 429:
                try:
                    wait = _retry_after(r.json())
                except ValueError:
                    wait = None
                if wait is not None and wait <= 60 and attempt < self.retries:
                    time.sleep(wait + 1)
                    continue
                raise Unavailable(f"Gemini quota: {r.text[:300]}")
            if r.status_code in (500, 502, 503, 504):
                # "Experiencing high demand" -- usually gone in a minute. If it is
                # not, nothing tonight will fare better, which is Unavailable.
                if attempt < self.retries:
                    time.sleep(10 * 3 ** attempt)
                    continue
                raise Unavailable(f"Gemini overloaded ({r.status_code}): {r.text[:200]}")
            if r.status_code in (401, 403):
                raise Unavailable(f"Gemini refused the key ({r.status_code}): {r.text[:200]}")
            if r.status_code != 200:
                raise LLMError(f"Gemini error {r.status_code}: {r.text[:300]}")
            break

        data = r.json()
        candidates = data.get("candidates") or []
        if not candidates:
            raise LLMError(f"Gemini gave no answer: {data.get('promptFeedback')}")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        if not text:
            raise LLMError(f"Gemini answer was empty ({candidates[0].get('finishReason')})")
        return text


def pick(which: str = "auto", claude_model: str = "sonnet"):
    """The backend to use: the claude CLI where it is installed, else Gemini.

    Returns one whether or not it is available; the caller asks, so it can say
    what is missing.
    """
    claude = ClaudeCLI(model=claude_model)
    if which == "claude":
        return claude
    if which == "gemini":
        return Gemini()
    if claude.available():
        return claude
    gemini = Gemini()
    return gemini if gemini.available() else claude
