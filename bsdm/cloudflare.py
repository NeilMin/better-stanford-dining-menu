"""Cloudflare Workers AI REST client for translation and image generation.

Provides a unified interface to Cloudflare's Workers AI endpoints, allowing
automated translation via Llama 3.3 and image generation via SDXL Lightning
without requiring local GPU or paid subscriptions.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
from pathlib import Path
import re
from typing import Any

import requests

log = logging.getLogger(__name__)

CF_BASE_URL = "https://api.cloudflare.com/client/v4/accounts"
DEFAULT_TRANSLATION_MODEL = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
DEFAULT_IMAGE_MODEL = "@cf/black-forest-labs/flux-1-schnell"
DEFAULT_VISION_MODEL = "@cf/meta/llama-3.2-11b-vision-instruct"


def _load_dotenv(env_path: Path | str | None = None) -> None:
    """Load CF credentials from a .env file if not present in os.environ."""
    if os.getenv("CF_ACCOUNT_ID") and os.getenv("CF_API_TOKEN"):
        return
    candidates = [Path(env_path)] if env_path else [
        Path.cwd() / ".env",
        Path(__file__).resolve().parent.parent / ".env",
    ]
    for p in candidates:
        if p and p.is_file():
            try:
                for line in p.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip().strip("'\""))
            except Exception as exc:
                log.debug("Failed reading %s: %s", p, exc)
            if os.getenv("CF_ACCOUNT_ID") and os.getenv("CF_API_TOKEN"):
                break


_load_dotenv()


class CloudflareError(RuntimeError):
    pass


class CloudflareQuotaError(CloudflareError):
    pass


class CloudflareClient:
    def __init__(self, account_id: str | None = None, api_token: str | None = None, timeout: int = 60):
        if account_id is None or api_token is None:
            if not (os.getenv("CF_ACCOUNT_ID") and os.getenv("CF_API_TOKEN")):
                _load_dotenv()
        self.account_id = (account_id if account_id is not None else os.getenv("CF_ACCOUNT_ID") or "").strip().strip('"').strip("'")
        self.api_token = (api_token if api_token is not None else os.getenv("CF_API_TOKEN") or "").strip().strip('"').strip("'")
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
        if "flux" in model:
            payload: dict[str, Any] = {"prompt": prompt}
            if num_steps:
                payload["steps"] = min(max(num_steps, 1), 8)
        elif "stable-diffusion-xl-base" in model:
            payload: dict[str, Any] = {"prompt": prompt, "num_steps": min(num_steps or 20, 20)}
        else:
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

    def evaluate_image(
        self,
        image_bytes: bytes,
        dish_name: str,
        model: str = DEFAULT_VISION_MODEL,
    ) -> dict[str, Any]:
        """Evaluate a food image candidate for realism, cleanliness, and readiness."""
        try:
            from PIL import Image
            im = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            im.thumbnail((512, 512))
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=85)
            thumb_bytes = buf.getvalue()
        except Exception as exc:
            log.warning("Failed to prepare thumbnail for vision eval: %s", exc)
            return {"valid": False, "score": 0, "reason": "Invalid image bytes"}

        prompt = (
            f"You are a culinary magazine photo editor. Evaluate whether this image is suitable for a professional culinary publication for the dish '{dish_name}'.\n"
            "Strict Rejection Rules (MUST set valid=false and score < 5 if any apply):\n"
            "1. Domestic/lifestyle snapshot: amateur home-cooking photo, home kitchen counters, dirty stovetops, cooking pots/pans, messy tableware, plastic takeout containers, or half-eaten food.\n"
            "2. Poor lighting & photography: harsh direct flash, dim yellow incandescent lighting, blurry/grainy focus, or unappetizing color cast.\n"
            "3. Uncooked / preparation: raw meat, raw dough, unfinished cooking steps, or cutting board prep.\n"
            "4. Clutter & overlays: visible people/hands, brand logos, watermarks, text, menus, or utensil clutter.\n\n"
            "Acceptance Criteria (score 8-10):\n"
            "- Beautiful commercial restaurant or studio plating.\n"
            "- Crisp, sharp focus with appetizing food styling and balanced natural or soft diffused lighting.\n"
            "- Clean background with no distracting mess.\n"
            "- Accurately represents '{dish_name}'.\n\n"
            'Reply ONLY with a raw JSON object with keys: "valid" (boolean), "score" (integer 1-10), "reason" (short string).'
        )
        payload = {
            "prompt": prompt,
            "image": list(thumb_bytes),
            "max_tokens": 128,
        }
        try:
            resp = self._run(model, payload)
            data = resp.json()
            raw_text = data.get("result", {}).get("response", "") if isinstance(data, dict) else ""
            if isinstance(raw_text, dict):
                res = raw_text
            elif isinstance(raw_text, str):
                match = re.search(r"\{.*\}", raw_text, re.S)
                if match:
                    clean_json = (
                        match.group(0)
                        .replace("'", '"')
                        .replace("True", "true")
                        .replace("False", "false")
                    )
                    res = json.loads(clean_json)
                else:
                    res = {}
            else:
                res = {}

            if isinstance(res, dict) and "valid" in res:
                return {
                    "valid": bool(res.get("valid", False)),
                    "score": int(res.get("score", 0)),
                    "reason": str(res.get("reason", "")),
                }
        except Exception as exc:
            log.warning("Vision evaluation failed for '%s': %s", dish_name, exc)

        return {"valid": False, "score": 0, "reason": "Evaluation failed"}

    def compile_dish_prompt(
        self,
        name: str,
        ingredients: str,
        tags: list[str] | None = None,
        category: str = "other",
        model: str = DEFAULT_TRANSLATION_MODEL,
    ) -> dict[str, str]:
        tags_str = ", ".join(tags or [])
        system = (
            "You are an expert commercial food photography director and culinary stylist. "
            "Your task is to take a dining hall dish name, category, and raw ingredient list, "
            "and create a clean, appetizing image generation prompt and targeted negative prompt.\n\n"
            "Rules:\n"
            "1. CULINARY ACCURACY: Understand what the dish looks like when served (e.g. Hot Dog is in a bun; Fajitas are sliced seared meat strips with bell peppers and onions; Lasagna has visible pasta sheets and cheese).\n"
            "2. STRIP CHEMICALS & LIQUIDS: Completely remove food additives, stabilizers, chemical preservatives (sorbitol, sodium lactate, sodium phosphates, hydrolyzed corn protein, gums, starch powders, acids, oils, cooking spray).\n"
            "3. PHOTOGRAPHY STYLE: Food photography, plated on a simple white ceramic plate (or bowl for soup/stew), overhead three-quarter view, centered composition, generous empty margin around plate, soft natural window light, shallow depth of field, clean neutral background, sharp focus, high detail.\n"
            "4. TARGETED NEGATIVE: Exclude dish-specific pitfalls (e.g. for Hot Dog: corn, yellow sludge, cheese sauce, ridges, tire tread; for Fajitas: burrito, wrap, taco, noodles, soup; for vegan dishes: meat, chicken, beef, pork, seafood).\n"
            "5. OUTPUT FORMAT: Respond ONLY with a valid JSON object with keys 'prompt' and 'negative'. Do not include markdown codeblocks or explanatory prose."
        )
        user_prompt = (
            f"Dish: {name}\n"
            f"Category: {category}\n"
            f"Tags: {tags_str}\n"
            f"Raw Ingredients: {ingredients}\n"
        )
        payload = {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": 512,
        }
        resp = self._run(model, payload)
        data = resp.json()
        raw_text = data.get("result", {}).get("response", "") if isinstance(data, dict) else ""
        if isinstance(raw_text, dict):
            parsed = raw_text
            if "prompt" in parsed:
                return {
                    "prompt": str(parsed.get("prompt", "")).strip(),
                    "negative": str(parsed.get("negative", "")).strip(),
                }
        elif isinstance(raw_text, str):
            match = re.search(r"\{.*\}", raw_text, re.S)
            if match:
                raw_text = match.group(0)
            try:
                parsed = json.loads(raw_text)
                if isinstance(parsed, dict) and "prompt" in parsed:
                    return {
                        "prompt": str(parsed.get("prompt", "")).strip(),
                        "negative": str(parsed.get("negative", "")).strip(),
                    }
            except Exception as exc:
                log.warning("Failed to parse compile_dish_prompt JSON: %s", exc)

        raise CloudflareError(f"Failed to compile prompt for {name}: {str(raw_text)[:200]}")

    def evaluate_food_image(
        self,
        image_bytes: bytes,
        dish_name: str,
        model: str = DEFAULT_VISION_MODEL,
    ) -> dict[str, Any]:
        """Evaluate a generated food card for visual quality, authenticity, and lack of AI artifacts."""
        return self.evaluate_image(image_bytes, dish_name=dish_name, model=model)

