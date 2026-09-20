# Cloud-Native Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automate Chinese translation and dish image generation directly inside GitHub Actions using Cloudflare Workers AI free tier, removing all manual local execution while maintaining zero cost and local backwards compatibility.

**Architecture:** A lightweight REST client (`bsdm/cloudflare.py`) interfaces with Cloudflare Workers AI for both LLaMA/Qwen translation and SDXL-Lightning 4-step image generation. A web image search fallback (`bsdm/web_image.py`) provides insurance against filtered or failed generations. The nightly GitHub Actions workflow (`refresh.yml`) orchestrates scrape -> translate -> image generation (paced at 8 dishes/run) -> git commit -> publish, natively queuing unrendered items in git.

**Tech Stack:** Python 3.11+, `requests`, `PIL` (Pillow), GitHub Actions (`refresh.yml`), Cloudflare Workers AI REST API, Pytest with network mocking.

## Global Constraints

- **No Network in Tests**: All pytest tests must run offline with mocked network calls in accordance with `tests/conftest.py:block_network`.
- **Zero Cost Forever**: Use only Cloudflare Workers AI Free Tier (10,000 daily neurons) and GitHub Actions.
- **Fail-Safe Publishing**: Errors in translation or image generation must never prevent `refresh.yml` from committing menu updates and publishing the static site.
- **Image Dimensions & Format**: All dish images must be saved as 16:9 WebP at 1024x576 in `data/images/<dish_id>.webp`.
- **Backward Compatibility**: Local execution flags (`--claude-bin`, `--url` for ComfyUI) must continue to function normally.

---

### Task 1: Cloudflare REST Client Module (`bsdm/cloudflare.py`) & Tests

**Files:**
- Create: `bsdm/cloudflare.py`
- Test: `tests/test_cloudflare.py`

**Interfaces:**
- Produces:
  - `class CloudflareClient`:
    - `__init__(account_id: str | None = None, api_token: str | None = None, timeout: int = 60)`
    - `is_configured() -> bool`
    - `translate(items: list[str], section: str, system_prompt: str, rules: str, model: str = "@cf/meta/llama-3.3-70b-instruct") -> dict[str, str]`
    - `generate_image(prompt: str, negative_prompt: str = "", num_steps: int = 4, model: str = "@cf/bytedance/stable-diffusion-xl-lightning") -> bytes`
    - Exceptions: `CloudflareError`, `CloudflareQuotaError`

- [ ] **Step 1: Write failing unit tests for CloudflareClient**

Create `tests/test_cloudflare.py`:
```python
import io
import json
import pytest
from unittest.mock import patch, MagicMock
from PIL import Image

from bsdm.cloudflare import CloudflareClient, CloudflareError, CloudflareQuotaError


def test_is_configured():
    client = CloudflareClient(account_id="acc123", api_token="tok456")
    assert client.is_configured() is True

    unconfigured = CloudflareClient(account_id="", api_token="")
    assert unconfigured.is_configured() is False


@patch("requests.Session.post")
def test_translate_success(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "success": True,
        "result": {
            "response": json.dumps({"Chicken Thigh": "鸡腿", "Tofu": "豆腐"})
        }
    }
    mock_post.return_value = mock_resp

    client = CloudflareClient(account_id="acc123", api_token="tok456")
    res = client.translate(["Chicken Thigh", "Tofu"], section="dishes", system_prompt="Sys", rules="Rules")
    assert res == {"Chicken Thigh": "鸡腿", "Tofu": "豆腐"}


@patch("requests.Session.post")
def test_translate_quota_exceeded(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 429
    mock_resp.text = "Daily quota exceeded"
    mock_post.return_value = mock_resp

    client = CloudflareClient(account_id="acc123", api_token="tok456")
    with pytest.raises(CloudflareQuotaError):
        client.translate(["Chicken"], section="dishes", system_prompt="Sys", rules="Rules")


@patch("requests.Session.post")
def test_generate_image_binary_success(mock_post):
    # Create a small valid PNG in memory
    buf = io.BytesIO()
    Image.new("RGB", (64, 36), color="red").save(buf, format="PNG")
    png_bytes = buf.getvalue()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Type": "image/png"}
    mock_resp.content = png_bytes
    mock_post.return_value = mock_resp

    client = CloudflareClient(account_id="acc123", api_token="tok456")
    img_data = client.generate_image("A bowl of ramen")
    assert img_data == png_bytes
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cloudflare.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'bsdm.cloudflare'`

- [ ] **Step 3: Implement `bsdm/cloudflare.py`**

Create `bsdm/cloudflare.py`:
```python
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import requests

log = logging.getLogger(__name__)

CF_BASE_URL = "https://api.cloudflare.com/client/v4/accounts"
DEFAULT_TRANSLATION_MODEL = "@cf/meta/llama-3.3-70b-instruct"
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

    def translate(self, items: list[str], section: str, system_prompt: str, rules: str,
                  model: str = DEFAULT_TRANSLATION_MODEL) -> dict[str, str]:
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
            "max_tokens": 2048,
        }
        resp = self._run(model, payload)
        data = resp.json()
        raw_text = ""
        if isinstance(data, dict):
            raw_text = data.get("result", {}).get("response", "")
        if not raw_text:
            raise CloudflareError("Empty response from Cloudflare translation")

        match = re.search(r"\{.*\}", raw_text, re.S)
        if match:
            raw_text = match.group(0)

        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise CloudflareError(f"Malformed translation JSON: {exc} | raw text: {raw_text[:200]}") from exc

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

    def generate_image(self, prompt: str, negative_prompt: str = "", num_steps: int = 4,
                       model: str = DEFAULT_IMAGE_MODEL) -> bytes:
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
                import base64
                return base64.b64decode(data["result"]["image"])
        except Exception:
            pass

        return resp.content
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cloudflare.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit Task 1**

```bash
git add bsdm/cloudflare.py tests/test_cloudflare.py
git commit -m "feat(cf): add Cloudflare Workers AI client and unit tests"
```

---

### Task 2: Web Image Search Fallback (`bsdm/web_image.py`) & Tests

**Files:**
- Create: `bsdm/web_image.py`
- Test: `tests/test_web_image.py`

**Interfaces:**
- Produces:
  - `def search_food_image(dish_name: str, timeout: int = 15) -> bytes | None`
  - Searches DuckDuckGo image search for `{dish_name} food`, downloads candidate, validates it is a readable image, and returns raw image bytes.

- [ ] **Step 1: Write failing unit tests for `bsdm/web_image.py`**

Create `tests/test_web_image.py`:
```python
import io
import pytest
from unittest.mock import patch, MagicMock
from PIL import Image

from bsdm.web_image import search_food_image


@patch("requests.Session.get")
def test_search_food_image_success(mock_get):
    # Mock DuckDuckGo token & search response
    buf = io.BytesIO()
    Image.new("RGB", (200, 150), color="blue").save(buf, format="JPEG")
    fake_img = buf.getvalue()

    # Call 1: vqd token lookup; Call 2: search json; Call 3: image download
    r1 = MagicMock(status_code=200, text='vqd="4-12345"')
    r2 = MagicMock(status_code=200)
    r2.json.return_value = {"results": [{"image": "https://example.com/dish.jpg"}]}
    r3 = MagicMock(status_code=200, content=fake_img, headers={"Content-Type": "image/jpeg"})

    mock_get.side_effect = [r1, r2, r3]

    result = search_food_image("Chicken Teriyaki")
    assert result == fake_img


@patch("requests.Session.get")
def test_search_food_image_no_results(mock_get):
    r1 = MagicMock(status_code=200, text='vqd="4-12345"')
    r2 = MagicMock(status_code=200)
    r2.json.return_value = {"results": []}

    mock_get.side_effect = [r1, r2]

    result = search_food_image("Super Rare Unheard Dish")
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_web_image.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'bsdm.web_image'`

- [ ] **Step 3: Implement `bsdm/web_image.py`**

Create `bsdm/web_image.py`:
```python
from __future__ import annotations

import io
import logging
import re
import urllib.parse
from typing import Any

import requests
from PIL import Image

log = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)"


def search_food_image(dish_name: str, timeout: int = 15) -> bytes | None:
    """Search DuckDuckGo Images without API key, download top valid food photo."""
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    query = f"{dish_name} food dish recipe"
    # Step 1: obtain DuckDuckGo vqd token
    token_url = f"https://duckduckgo.com/?{urllib.parse.urlencode({'q': query})}"
    try:
        r = session.get(token_url, timeout=timeout)
        r.raise_for_status()
    except requests.RequestException as exc:
        log.warning("DuckDuckGo token lookup failed for '%s': %s", dish_name, exc)
        return None

    match = re.search(r'vqd=([0-9-_]+)', r.text) or re.search(r'vqd="([^"]+)"', r.text)
    if not match:
        log.warning("Could not extract vqd token for '%s'", dish_name)
        return None
    vqd = match.group(1)

    # Step 2: query images endpoint
    search_url = (
        f"https://duckduckgo.com/i.js?l=us-en&o=json&q={urllib.parse.quote(query)}"
        f"&vqd={vqd}&f=,,,&p=1"
    )
    try:
        r = session.get(search_url, timeout=timeout)
        r.raise_for_status()
        data = r.json()
    except (requests.RequestException, ValueError) as exc:
        log.warning("DuckDuckGo image search request failed for '%s': %s", dish_name, exc)
        return None

    results = data.get("results", [])
    if not results:
        return None

    # Step 3: attempt downloading top candidate
    for item in results[:3]:
        img_url = item.get("image")
        if not img_url:
            continue
        try:
            img_r = session.get(img_url, timeout=timeout)
            if img_r.status_code == 200 and len(img_r.content) > 2048:
                # Validate that PIL can parse it as an image
                with Image.open(io.BytesIO(img_r.content)) as im:
                    im.verify()
                return img_r.content
        except Exception:
            continue

    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_web_image.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit Task 2**

```bash
git add bsdm/web_image.py tests/test_web_image.py
git commit -m "feat(image): add DuckDuckGo web image fallback fetcher"
```

---

### Task 3: Update `scripts/translate.py` for Cloudflare Backend

**Files:**
- Modify: `scripts/translate.py`
- Test: `tests/test_translate.py`

**Interfaces:**
- Consumes: `bsdm.cloudflare.CloudflareClient`
- Produces: CLI `--backend [auto|cloudflare|claude]` in `scripts/translate.py`

- [ ] **Step 1: Write test for `scripts/translate.py` with Cloudflare backend**

Create `tests/test_translate.py`:
```python
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from scripts.translate import ask_cloudflare


def test_ask_cloudflare_translates():
    mock_client = MagicMock()
    mock_client.translate.return_value = {"Fried Rice": "炒饭"}
    
    res = ask_cloudflare(["Fried Rice"], "dishes", mock_client)
    assert res == {"Fried Rice": "炒饭"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_translate.py`
Expected: FAIL with `ImportError: cannot import name 'ask_cloudflare' from 'scripts.translate'`

- [ ] **Step 3: Update `scripts/translate.py`**

In `scripts/translate.py`:
- Add import: `from bsdm.cloudflare import CloudflareClient, CloudflareError, CloudflareQuotaError`
- Implement `ask_cloudflare(items: list[str], section: str, client: CloudflareClient) -> dict[str, str]`
- Update `main()` argument parser to add `--backend` (choices: `["auto", "cloudflare", "claude"]`, default: `"auto"`).
- In `main()`:
  - If backend is `"cloudflare"` or (`"auto"` and `CloudflareClient().is_configured()`):
    Use Cloudflare workers AI client.
  - Else: use existing Claude CLI `ask()` function.
  - Catch `CloudflareQuotaError` and break out of loop gracefully after persisting already completed batches.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_translate.py -v`
Expected: PASS

- [ ] **Step 5: Test dry-run of `scripts/translate.py`**

Run: `uv run python scripts/translate.py --dry-run`
Expected: Outputs translation status (e.g. "Nothing to translate") without crashing.

- [ ] **Step 6: Commit Task 3**

```bash
git add scripts/translate.py tests/test_translate.py
git commit -m "feat(translate): support Cloudflare Workers AI translation backend"
```

---

### Task 4: Update `scripts/gen_images.py` for Cloudflare & Search Fallback

**Files:**
- Modify: `scripts/gen_images.py`
- Test: `tests/test_gen_images.py`

**Interfaces:**
- Consumes:
  - `bsdm.cloudflare.CloudflareClient`
  - `bsdm.web_image.search_food_image`
- Produces:
  - CLI `--backend [auto|cloudflare|comfyui]`
  - CLI `--search-fallback` (default True)
  - Paced batch limit support and metadata recording

- [ ] **Step 1: Write test for `scripts/gen_images.py` image generation via Cloudflare**

Create `tests/test_gen_images.py`:
```python
import io
import pytest
from unittest.mock import patch, MagicMock
from PIL import Image

from bsdm.cloudflare import CloudflareClient
from scripts.gen_images import generate_with_cloudflare, generate_with_search_fallback


def test_generate_with_cloudflare_returns_image():
    buf = io.BytesIO()
    Image.new("RGB", (100, 100), color="green").save(buf, format="PNG")
    png_bytes = buf.getvalue()

    client = MagicMock(spec=CloudflareClient)
    client.generate_image.return_value = png_bytes

    img, secs = generate_with_cloudflare(client, "Ramen prompt", "neg prompt")
    assert isinstance(img, Image.Image)
    assert secs >= 0


@patch("bsdm.web_image.search_food_image")
def test_generate_with_search_fallback_returns_image(mock_search):
    buf = io.BytesIO()
    Image.new("RGB", (100, 100), color="yellow").save(buf, format="JPEG")
    mock_search.return_value = buf.getvalue()

    img, secs = generate_with_search_fallback("Curry")
    assert isinstance(img, Image.Image)
    assert secs >= 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_gen_images.py`
Expected: FAIL with `ImportError: cannot import name 'generate_with_cloudflare' from 'scripts.gen_images'`

- [ ] **Step 3: Modify `scripts/gen_images.py`**

In `scripts/gen_images.py`:
- Add imports:
  ```python
  from bsdm.cloudflare import CloudflareClient, CloudflareError, CloudflareQuotaError
  from bsdm.web_image import search_food_image
  ```
- Implement `generate_with_cloudflare(client: CloudflareClient, prompt: str, negative: str) -> tuple[Image.Image, float]`
- Implement `generate_with_search_fallback(dish_name: str) -> tuple[Image.Image | None, float]`
- In `main()`:
  - Add argument `--backend` (choices: `["auto", "cloudflare", "comfyui"]`, default: `"auto"`).
  - Add argument `--search-fallback`, default `True`.
  - In `'auto'` mode: if `CloudflareClient().is_configured()`, use Cloudflare; else fall back to ComfyUI if available.
  - When rendering each pending dish:
    1. Try chosen backend.
    2. If Cloudflare hits `CloudflareQuotaError`, log quota warning, save state, and stop loop cleanly (saving all completed images).
    3. If prompt is filtered or generation fails, and `--search-fallback` is enabled: attempt `generate_with_search_fallback()`.
    4. Save image with `to_webp()` to `data/images/{did}.webp` and record metadata in `data/dishes.json` (`model: "cf-sdxl-lightning"` or `"web-search"`).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_gen_images.py -v`
Expected: PASS

- [ ] **Step 5: Test dry-run of `scripts/gen_images.py`**

Run: `uv run python scripts/gen_images.py --limit 0`
Expected: Clean exit without errors.

- [ ] **Step 6: Commit Task 4**

```bash
git add scripts/gen_images.py tests/test_gen_images.py
git commit -m "feat(gen_images): support Cloudflare Workers AI and web search fallback"
```

---

### Task 5: Update GitHub Actions `.github/workflows/refresh.yml` & Verification

**Files:**
- Modify: `.github/workflows/refresh.yml`

- [ ] **Step 1: Update `.github/workflows/refresh.yml`**

Add translation and image generation steps into the `refresh` job before the commit step:
```yaml
      - name: Scrape the menu window
        run: uv run python scripts/update.py

      - name: Translate missing menu items
        continue-on-error: true
        env:
          CF_ACCOUNT_ID: ${{ secrets.CF_ACCOUNT_ID }}
          CF_API_TOKEN: ${{ secrets.CF_API_TOKEN }}
        run: uv run python scripts/translate.py

      - name: Generate pending dish images
        continue-on-error: true
        env:
          CF_ACCOUNT_ID: ${{ secrets.CF_ACCOUNT_ID }}
          CF_API_TOKEN: ${{ secrets.CF_API_TOKEN }}
        run: uv run python scripts/gen_images.py --limit 8

      - name: Commit refreshed menus and assets
        if: always()
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add data/
          if git diff --cached --quiet; then
            echo "No menu or asset changes."
          else
            git commit -m "data: refresh menus and assets for $(date -u +%Y-%m-%d)"
            git push
          fi
```

- [ ] **Step 2: Run full test suite**

Run: `uv run pytest`
Expected: Full test suite passes completely (<2s, 0 network socket errors).

- [ ] **Step 3: Commit Task 5**

```bash
git add .github/workflows/refresh.yml
git commit -m "ci(refresh): integrate cloud translation and image generation into daily workflow"
```
