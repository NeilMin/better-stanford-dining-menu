# Automated Dish Prompt Compiler and Visual Quality Gate Design

**Author**: Antigravity & NeilMin  
**Date**: 2026-09-23  
**Status**: Approved (Transitioning to Implementation Plan)

---

## 1. Background & Problem Statement

In the Better Stanford Dining Menu (BSDM) pipeline, dish illustrations have traditionally relied on hand-crafted heuristic regexes in `bsdm/dishes.py` (e.g. `_INVISIBLE_RE`, `_FLAVORING_RE`, and `_hero_protein_phrase`). 

This heuristic approach fails to scale across thousands of rotating Stanford dishes:
1. **Unseen Dishes Degrade to Generic Textures**: Dishes lacking specific keyword rules fall back to generic protein phrases (`tender cooked beef, succulent meat texture, rich caramelized sear`), stripping away culinary context (e.g. producing meat slabs instead of hot dogs in buns).
2. **Chemical Leaks into Diffusion Prompts**: Raw dining hall ingredient strings contain food additives, stabilizers, and hydrolysates (`hydrolyzed corn protein`, `sorbitol`, `sodium phosphates`), causing CLIP text encoders to hallucinate bizarre yellow corn paste, plastic slices, or rubbery textures.
3. **No Quality Feedback Loop**: Image generation in `scripts/gen_images.py` accepts images on the first seed with zero automated visual verification, requiring tedious human inspection and manual regex tuning.

---

## 2. Goals & Invariants

- **Systematic Prompt Compilation**: Replace brittle regex heuristics with Cloudflare Llama 3.3 70B to compile rich, realistic food photography prompts and targeted negative prompts.
- **Batch Pre-compilation (Idempotent & Incremental)**: Prompt compilation runs offline during catalog updates (`scripts/compile_prompts.py`) and commits the resulting prompts to `data/dishes.json`. Image generation runtime has zero LLM latency overhead.
- **Closed-Loop Visual Quality Gate**: After generating an image via ComfyUI (or Cloudflare), evaluate the output using Cloudflare Llama 3.2 11B Vision. If AI smearing, plastic textures, or culinary inaccuracies occur (score < 7), automatically re-roll with a new seed (up to 3 attempts).
- **Graceful Fallbacks**: If Cloudflare credentials are unset or the network is offline, the pipeline safely falls back to standard heuristic prompts and bypasses VLM gating without blocking builds.
- **Testing Invariant**: Respect the project's "No sockets in tests" rule (`tests/conftest.py`) by mocking all Cloudflare network calls.

---

## 3. Architecture & Data Flow

```
[Dining Hall Scraper / Menu Update]
                   │
                   ▼
  data/menus/live/ + config/halls.json
                   │
                   ▼
       [1. Upstream Prompt Compiler]
         scripts/compile_prompts.py
         ├── Scans data/dishes.json for dishes missing compiled prompts
         ├── Sends batch requests to Cloudflare Llama 3.3 70B
         │     Input: name, tags, raw ingredients
         │     Output: clean presentation, positive prompt, negative exclusions
         └── Writes compiled prompts into data/dishes.json
                   │
                   ▼
       [2. Image Generation & VLM Quality Gate]
         scripts/gen_images.py
         ├── Iterates pending dishes using compiled prompts
         ├── Generates candidate card image (ComfyUI RealVisXL / Cloudflare FLUX)
         ├── [Downstream VLM Evaluator: Cloudflare Llama 3.2 11B Vision]
         │     ├── Inspects thumbnail for AI smudging, plastic texture, realism
         │     ├── Score ≥ 7: ACCEPT -> write data/images/<dishId>.webp
         │     └── Score < 7: REJECT -> re-seed and retry (up to 3 attempts)
         └── Exhausted Retries -> Fallback to Web Search or mark for review
                   │
                   ▼
       [3. Static Site Publisher]
         scripts/build_site.py ──► site/index.html
```

---

## 4. Detailed Component Design

### 4.1 Cloudflare Client Extensions (`bsdm/cloudflare.py`)

Extend `CloudflareClient` with two dedicated methods:

1. `compile_dish_prompt(dish: dict) -> dict[str, str]`
   - Model: `@cf/meta/llama-3.3-70b-instruct-fp8-fast`
   - Input: dish name, dining hall category, tags (vegan, halal, etc.), and raw ingredients.
   - System prompt instructions:
     - Act as a professional commercial food photography director.
     - Identify the authentic visual plating and physical appearance (e.g. Hot dog in toasted bun; Fajitas as sizzling charred strips with bell peppers and onions).
     - Strip all chemical preservatives, industrial additives, salts, and liquid media.
     - Generate an appetizing, highly detailed positive prompt.
     - Generate a targeted negative prompt excluding dish-specific pitfalls (e.g. yellow sludge, cheese sauce, burrito wraps).
   - Returns structured JSON: `{"prompt": "...", "negative": "..."}`.

2. `evaluate_food_image(image_bytes: bytes, dish_name: str, expected_description: str) -> dict[str, Any]`
   - Model: `@cf/meta/llama-3.2-11b-vision-instruct`
   - Evaluates rendered food photo with specific anti-AI artifact criteria:
     - No plastic or rubbery sheen, no AI smudging/painterly blur.
     - No unidentifiable yellow/green slime or weird topping pastes.
     - Plated cleanly on ceramic tableware without hands/utensil clutter.
   - Returns: `{"valid": bool, "score": int (1-10), "reason": str}`.

### 4.2 Batch Prompt Compiler (`scripts/compile_prompts.py` & `bsdm/prompt_compiler.py`)

- CLI tool to compile prompts for dishes needing them:
  ```sh
  uv run python scripts/compile_prompts.py [--only <dish>] [--force] [--limit <n>]
  ```
- Incremental tracking in `data/dishes.json`:
  ```json
  {
    "prompt": "...",
    "negative": "...",
    "prompt_compiled": true,
    "prompt_compiler_rev": 1
  }
  ```
- Dishes that are station containers or placeholders are skipped.
- Integrated into `make update` or runnable as an explicit Makefile target (`make prompts`).

### 4.3 Image Generation Closed Loop (`scripts/gen_images.py`)

Modify `scripts/gen_images.py` execution loop:
1. Load `entry["prompt"]` and `entry["negative"]`.
2. Generate image using current backend (ComfyUI or Cloudflare).
3. If `cf_client.is_configured()` and `--no-vlm-eval` is not set:
   - Call `cf_client.evaluate_food_image()`.
   - Log inspection score and reason: `[Judge: 8/10] Clean plating, realistic textures`.
   - If `score < 7`:
     - Log failure: `[Judge: 4/10] Rejected: plastic smearing on sausage casing`.
     - Pick a new seed: `seed = random.randint(1, 2**31 - 1)`
     - Retry generation up to `MAX_EVAL_ATTEMPTS = 3`.
4. Save accepted image to `data/images/<dishId>.webp` and record metadata in `data/dishes.json`.

---

## 5. Error Handling & Edge Cases

| Scenario | Behavior |
| :--- | :--- |
| Cloudflare API unavailable / Quota 429 | Compiler logs warning and preserves heuristic fallback prompt (`bsdm/dishes.py`); generation proceeds without failing. |
| VLM evaluation fails or times out | Accepts generation ifComfyUI rendered without error; logs warning instead of crashing. |
| Dish fails all 3 VLM attempts | Logs failure with reasons; triggers existing web search fallback or marks `needs_review: true`. |
| Offline / Sandbox Unit Tests | Network calls are intercepted by mocked fixtures in `tests/conftest.py`. |

---

## 6. Verification Plan

1. **Unit Tests (`tests/test_prompt_compiler.py` & `tests/test_vlm_gate.py`)**:
   - Verify prompt compiler formats system prompt and extracts clean JSON.
   - Verify VLM quality gate correctly parses judge scores, triggers retries on score < 7, and accepts score >= 7.
2. **Golden / Regression Tests**:
   - Verify existing test suite passes (`uv run pytest`).
   - Verify `scripts/build_site.py` compiles cleanly with the updated dishes schema.
3. **End-to-End Dry Run**:
   - Test `scripts/compile_prompts.py --only "Beef Hot Dog"` with Cloudflare client mock and live client.
   - Test `scripts/gen_images.py` with multi-seed retry logic.
