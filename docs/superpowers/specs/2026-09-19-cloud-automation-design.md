# Cloud-Native Automation Design: $0 Maintenance-Free Translation & Image Pipeline

**Date:** 2026-09-19  
**Status:** Approved by User  
**Target:** Long-term, zero-cost, fully autonomous translation and dish image generation via GitHub Actions and Cloudflare Workers AI.

---

## 1. Context & Motivation

Better Stanford Dining Menu (BSDM) scrapes Stanford dining menus twice daily via GitHub Actions (`.github/workflows/refresh.yml`) and publishes a static web dashboard via GitHub Pages (`.github/workflows/pages.yml`).

While scraping and static site generation run autonomously in CI, two critical steps currently require manual intervention on a local machine:
1. **Translation**: `scripts/translate.py` requires running `claude -p` locally using the Claude Code CLI.
2. **Dish Image Generation**: `scripts/gen_images.py` requires a local Apple Silicon GPU running ComfyUI on `127.0.0.1:8189` with RealVisXL (SDXL).

Once the maintainer graduates or steps away, this manual cycle cannot continue. The goal is to make the entire pipeline **100% self-sufficient in the cloud forever at $0 cost**, requiring zero manual triggering while preserving local development compatibility.

---

## 2. Architectural Decisions & Constraints

### 2.1 Unified Cloud Provider: Cloudflare Workers AI (Free Tier)
- **Zero Cost**: Cloudflare grants **10,000 Neurons per day** for free, resetting daily at 00:00 UTC.
- **Single Vendor / Single Credential**: A single Cloudflare account and API token (`CF_ACCOUNT_ID`, `CF_API_TOKEN`) handles both translation (LLM) and image generation (SDXL-Lightning).
- **Long-term Stability**: Enterprise-grade infrastructure with predictable REST APIs that will not arbitrarily disappear or inject watermarks.

### 2.2 Workload & Quota Budget
- **Stanford Dining Characteristics**:
  - Existing catalog has 392 dishes and 1,048 terms already translated and rendered.
  - On 90%+ of days during the school year, new dishes = 0.
  - During quarterly rotations or special events, 15–30 new dishes may appear in a batch.
- **Neuron Consumption**:
  - **Text Translation** (`@cf/meta/llama-3.3-70b-instruct` or `@cf/qwen/qwen2.5-7b-instruct`): ~100–200 Neurons per run (1–2% of daily quota).
  - **Image Generation** (`@cf/bytedance/stable-diffusion-xl-lightning`): ~500–700 Neurons per image (~12–15 images/day within free tier).
- **Pacing & Queue Behavior**:
  - Image generation in CI enforces a batch limit (`--limit 8`).
  - Items are prioritised by `bsdm/pending.py:rank` (meat mains P0 -> vegetarian mains P1 -> sides P2).
  - If a large menu turnover introduces 24 new dishes: Day 1 renders 8, Day 2 renders 8, Day 3 renders 8. All new dishes are cleared within 3 days without exceeding the daily 10,000 Neurons quota.
  - State is persisted natively in git (`data/dishes.json` and `data/zh.json`). Unfinished items remain in the queue and resume automatically on the next scheduled run.

### 2.3 Fail-Safe & Degradation Rules
- If Cloudflare credentials are missing: log a clean notice and skip cloud generation without failing the workflow.
- If Cloudflare hits a rate limit (HTTP 429) or prompt filter during image generation:
  - Save whatever images were generated up to that point.
  - Trigger a secondary fallback: search-based image download (e.g., DuckDuckGo food image query) cropped to 16:9 WebP.
  - If both fail, keep the dish with `image: null` (displaying the placeholder card icon) and let the queue retry next time.
- **Never Fail Scrape Publishing**: Failures in translation or image generation MUST NOT block `refresh.yml` from committing menu updates or publishing today's meals to GitHub Pages.

---

## 3. Detailed Component Specifications

### 3.1 New Module: `bsdm/cloudflare.py`
A lightweight, dependency-free (standard library + `requests`) client for Cloudflare Workers AI REST API:
- `class CloudflareClient`:
  - `__init__(account_id: str | None = None, api_token: str | None = None, timeout: int = 60)`:
    Defaults to reading `CF_ACCOUNT_ID` and `CF_API_TOKEN` from environment variables.
  - `is_configured() -> bool`: Returns `True` if credentials are non-empty.
  - `translate(items: list[str], section: str, system_prompt: str, rules: str, model: str = "@cf/meta/llama-3.3-70b-instruct") -> dict[str, str]`:
    Sends a chat completion request formatted with system prompt and JSON schema instructions. Parses and validates the returned JSON object.
  - `generate_image(prompt: str, negative_prompt: str = "", num_steps: int = 4, model: str = "@cf/bytedance/stable-diffusion-xl-lightning") -> bytes`:
    Sends a text-to-image request. Handles raw binary image stream (`image/png` or `image/jpeg`) or JSON response, returning raw image bytes.

### 3.2 Web Search Fallback: `bsdm/web_image.py`
A zero-credential fallback fetcher for edge-case dishes:
- Queries DuckDuckGo / open image search for `"{dish_name} food high quality"` without needing API keys.
- Validates image dimensions, downloads the top candidate, and converts via `PIL.Image`.
- Crops to 16:9 aspect ratio and encodes to WebP via `to_webp()`.

### 3.3 Modified Script: `scripts/translate.py`
- Add `--backend` flag with choices `['auto', 'cloudflare', 'claude']` (default `'auto'`).
- In `'auto'` mode:
  - If `CF_API_TOKEN` and `CF_ACCOUNT_ID` are present, use Cloudflare Workers AI.
  - Else, fall back to local `claude` CLI.
- Ensure error handling: if a batch fails or times out, log error, save progress with `zhlib.merge()`, and exit cleanly.

### 3.4 Modified Script: `scripts/gen_images.py`
- Add `--backend` flag with choices `['auto', 'cloudflare', 'comfyui']` (default `'auto'`).
- In `'auto'` mode:
  - If `CF_API_TOKEN` and `CF_ACCOUNT_ID` are present, use Cloudflare.
  - Else if ComfyUI is listening at `DEFAULT_URL`, use ComfyUI.
- Add `--search-fallback` flag (default `True`): if AI generation fails or is filtered, attempt `bsdm/web_image.py`.
- Enforce default batch limit `--limit 8` when running in cloud/CI mode.
- Record `model: "cf-sdxl-lightning"` or `"web-search"` in `data/dishes.json`.

### 3.5 Updated Workflow: `.github/workflows/refresh.yml`
Update the `refresh` job steps:
1. `Scrape the menu window`: `uv run python scripts/update.py`
2. `Translate missing menu items`:
   - Runs `uv run python scripts/translate.py`
   - Env: `CF_ACCOUNT_ID: ${{ secrets.CF_ACCOUNT_ID }}`, `CF_API_TOKEN: ${{ secrets.CF_API_TOKEN }}`
   - Continues on error (`continue-on-error: true`) so translation never blocks menu publishing.
3. `Generate pending dish images`:
   - Runs `uv run python scripts/gen_images.py --limit 8`
   - Env: `CF_ACCOUNT_ID: ${{ secrets.CF_ACCOUNT_ID }}`, `CF_API_TOKEN: ${{ secrets.CF_API_TOKEN }}`
   - Continues on error (`continue-on-error: true`).
4. `Commit refreshed menus, translations, and images`:
   - Stages `data/` (`git add data/`).
   - If diff exists: commits with message `"data: refresh menus and assets for YYYY-MM-DD"`, pushes to `main`.
5. `Check what the source is offering`: `uv run python scripts/check_source.py`
6. `File the dishes still waiting for a picture`: `uv run python scripts/notify_images.py`
   (Will report only if the backlog exceeds the daily limit or persistently fails).

---

## 4. Testing & Invariant Protection

- **No Network In Pytest**: All tests in `tests/` MUST respect the BSDM invariant (`tests/conftest.py:block_network`).
- **New Unit Tests**:
  - `tests/test_cloudflare.py`: Mock Cloudflare Workers AI responses (both translation JSON and image byte outputs). Test quota 429 handling and JSON parsing robustness.
  - `tests/test_web_image.py`: Mock HTTP search responses and verify 16:9 cropping & WebP output.
- **CI / Local Backward Compatibility**:
  - Running `make update` or `make translate` locally without Cloudflare credentials continues to use existing tooling.

---

## 5. Deployment & Secrets Setup Guide

Once the code changes are merged:
1. User logs into [Cloudflare Dashboard](https://dash.cloudflare.com/) (free tier).
2. Copies **Account ID** from the right sidebar.
3. Navigates to **My Profile > API Tokens > Create Token**, selects **Use template: Workers AI**, and generates the token.
4. Adds the following repository secrets under GitHub `Settings > Secrets and variables > Actions`:
   - `CF_ACCOUNT_ID`: Cloudflare Account ID string.
   - `CF_API_TOKEN`: Generated Workers AI API token string.
