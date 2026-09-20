"""Cloudflare Workers AI REST client for translation and image generation.

Provides a unified interface to Cloudflare's Workers AI endpoints, allowing
automated translation via Llama 3.3 and image generation via SDXL Lightning
without requiring local GPU or paid subscriptions.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from typing import Any

import requests

log = logging.getLogger(__name__)

CF_BASE_URL = "https://api.cloudflare.com/client/v4/accounts"
DEFAULT_TRANSLATION_MODEL = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
DEFAULT_IMAGE_MODEL = "@cf/bytedance/stable-diffusion-xl-lightning"


class CloudflareError(RuntimeError):
    pass


class CloudflareQuotaError(CloudflareError):
    pass


class CloudflareClient:
    def __init__(self, account_id: str | None = None, api_token: str | None = None, timeout: int = 60):
        self.account_id = (account_id or os.getenv("CF_ACCOUNT_ID") or "").strip()
        self.api_token = (api_token or os.getenv("CF_API_TOKEN") or "").strip()
        self.timeout = timeout
        self.session = requests.Session()
        if self.api_token:
            self.session.headers.update({"Authorization": f"Bearer {self.api_token}"})

    def is_configured(self) -> bool:
        return bool(self.account_id and self.api_token)

    def _run(self, model: str, payload: dict[str, Any], raw_response: bool = False) -> requests.Response:
        if not self.is_configured():
            raise CloudflareError("Cloudflare account_id and api_token are required")
        url = f"{CF_BASE_URL}/{self.account_id}/ai/run/{model}"
        try:
            resp = self.session.post(url, json=payload, timeout=self.timeout)
        except requests.RequestException as exc:
            raise CloudflareError(f"Cloudflare request failed: {exc}") from exc

        if resp.status_code == 429:
            raise CloudflareQuotaError(f"Cloudflare quota exceeded (429): {resp.text[:300]}")
        if resp.status_code != 200:
            raise CloudflareError(f"Cloudflare error {resp.status_code}: {resp.text[:400]}")
        return resp

    def translate(
        self,
        items: list[str],
        section: str,
        system_prompt: str,
        rules: str,
        model: str = DEFAULT_TRANSLATION_MODEL,
    ) -> dict[str, str]:
        prompt = (
            f"{rules}\n\n"
            "Reply ONLY with a single JSON object mapping each input string below, exactly as given, "
            "to its Simplified Chinese translation. Do not wrap in markdown fences or include explanations.\n\n"
            + json.dumps(items, ensure_ascii=False, indent=0)
        )
        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 4096,
        }
        resp = self._run(model, payload)
        data = resp.json()
        raw_text = ""
        if isinstance(data, dict):
            raw_text = data.get("result", {}).get("response", "")
        if not raw_text:
            raise CloudflareError("Empty response from Cloudflare translation")

        if isinstance(raw_text, dict):
            parsed = raw_text
        elif isinstance(raw_text, str):
            match = re.search(r"\{.*\}", raw_text, re.S)
            if match:
                raw_text = match.group(0)

            try:
                parsed = json.loads(raw_text)
            except json.JSONDecodeError as exc:
                raise CloudflareError(f"Malformed translation JSON: {exc} | raw text: {raw_text[:200]}") from exc
        else:
            raise CloudflareError(f"Unexpected response type: {type(raw_text).__name__}")

        if not isinstance(parsed, dict):
            raise CloudflareError(f"Expected dict, got {type(parsed).__name__}")

        # Normalise matching
        out = {}
        by_norm = {k.strip().lower(): v for k, v in parsed.items() if isinstance(v, str)}
        for item in items:
            val = parsed.get(item) or by_norm.get(item.strip().lower())
            if isinstance(val, str) and val.strip():
                out[item] = val.strip()
        return out

    def generate_image(
        self,
        prompt: str,
        negative_prompt: str = "",
        num_steps: int = 4,
        model: str = DEFAULT_IMAGE_MODEL,
    ) -> bytes:
        payload: dict[str, Any] = {
            "prompt": prompt,
            "num_steps": num_steps,
            "width": 1024,
            "height": 576,
        }
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt

        resp = self._run(model, payload, raw_response=True)
        content_type = resp.headers.get("Content-Type", "")
        if "image" in content_type:
            return resp.content

        # Handle base64 JSON if returned
        try:
            data = resp.json()
            if isinstance(data, dict) and "result" in data and "image" in data["result"]:
                return base64.b64decode(data["result"]["image"])
        except Exception:
            pass

        return resp.content
