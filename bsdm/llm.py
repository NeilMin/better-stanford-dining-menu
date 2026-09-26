"""The language model that writes a dish's brief and checks its picture.

Both jobs go through one call, `ask(prompt, images)`, so the backend is a choice
made once rather than a branch in every caller. The only backend so far is the
Claude Code CLI in headless mode, the same engine scripts/translate.py uses: it
costs nothing beyond a subscription already in use and needs no API key. It
takes images through `--input-format stream-json`, one turn, no tools.

The failure that matters is `Unavailable`: a usage limit or a missing binary is
not something retrying the next dish will fix, so the caller stops asking for
the night instead of burning through the queue on errors. Anything else is an
`LLMError` for that one call.
"""

from __future__ import annotations

import base64
import io
import json
import re
import shutil
import subprocess
import tempfile
from typing import Sequence

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


def default() -> ClaudeCLI:
    return ClaudeCLI()
