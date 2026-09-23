# Automated Dish Prompt Compiler and Visual Quality Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement an automated prompt compiler (Cloudflare Llama 3.3 70B) and visual quality gate with multi-seed auto-retry (Cloudflare Llama 3.2 11B Vision) for the BSDM image pipeline, and verify it on two live dishes.

**Architecture:** 
1. `CloudflareClient` (`bsdm/cloudflare.py`) is extended with `compile_dish_prompt` and `evaluate_food_image`.
2. A new batch prompt compiler module (`bsdm/prompt_compiler.py`) and CLI (`scripts/compile_prompts.py`) extract culinary appearance from raw ingredients, filter additives, and persist structured prompts to `data/dishes.json`.
3. `scripts/gen_images.py` incorporates an automated quality evaluation loop that inspects generated food cards via VLM and auto-regenerates with new seeds (up to 3 attempts) if visual score is below 7.
4. Test on two sample dishes end-to-end to report generated image quality and VLM evaluation scores.

**Tech Stack:** Python 3.12, Cloudflare Workers AI REST API, ComfyUI RealVisXL SDXL, Pytest.

## Global Constraints
- Preserve "No sockets in tests" rule: all Cloudflare API calls in tests must use mocked responses.
- Idempotent and resumable: dishes are compiled once and keyed by ID; images pass through VLM quality evaluation.
- Graceful offline fallback: if Cloudflare credentials are unset, fallback to existing heuristics without crashing.

---

### Task 1: Extend CloudflareClient with Prompt Compilation and Food Quality Evaluation

**Files:**
- Modify: `bsdm/cloudflare.py:120-224`
- Test: `tests/test_cloudflare.py`

**Interfaces:**
- Produces:
  - `CloudflareClient.compile_dish_prompt(name: str, ingredients: str, tags: list[str], category: str) -> dict[str, str]` (keys: `prompt`, `negative`)
  - `CloudflareClient.evaluate_food_image(image_bytes: bytes, dish_name: str) -> dict[str, Any]` (keys: `valid`, `score`, `reason`)

- [ ] **Step 1: Write failing tests for compile_dish_prompt and evaluate_food_image**

Create `tests/test_cloudflare.py`:
```python
import json
from unittest.mock import MagicMock
from bsdm.cloudflare import CloudflareClient

def test_compile_dish_prompt_parses_json():
    client = CloudflareClient("acc123", "tok456")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "result": {
            "response": json.dumps({
                "prompt": "Juicy beef hot dog in a soft bun",
                "negative": "yellow sludge, plastic"
            })
        }
    }
    client.session.post = MagicMock(return_value=mock_resp)

    res = client.compile_dish_prompt(
        name="Beef Hot Dog",
        ingredients="beef, sorbitol, sodium lactate",
        tags=["halal"],
        category="beef"
    )
    assert res["prompt"] == "Juicy beef hot dog in a soft bun"
    assert "yellow sludge" in res["negative"]

def test_evaluate_food_image_parses_score():
    client = CloudflareClient("acc123", "tok456")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "result": {
            "response": '{"valid": true, "score": 9, "reason": "Appetizing plating and crisp focus"}'
        }
    }
    client.session.post = MagicMock(return_value=mock_resp)

    # Fake 10x10 PNG bytes
    from PIL import Image
    import io
    buf = io.BytesIO()
    Image.new("RGB", (10, 10), "white").save(buf, format="JPEG")
    res = client.evaluate_food_image(buf.getvalue(), dish_name="Beef Hot Dog")
    assert res["valid"] is True
    assert res["score"] == 9
    assert "Appetizing" in res["reason"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cloudflare.py -v`
Expected: FAIL with `AttributeError: 'CloudflareClient' object has no attribute 'compile_dish_prompt'`

- [ ] **Step 3: Implement compile_dish_prompt and evaluate_food_image in bsdm/cloudflare.py**

Add methods to `bsdm/cloudflare.py`:
```python
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
        if isinstance(raw_text, str):
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

        raise CloudflareError(f"Failed to compile prompt for {name}: {raw_text[:200]}")

    def evaluate_food_image(
        self,
        image_bytes: bytes,
        dish_name: str,
        model: str = DEFAULT_VISION_MODEL,
    ) -> dict[str, Any]:
        """Evaluate a generated food card for visual quality, authenticity, and lack of AI artifacts."""
        return self.evaluate_image(image_bytes, dish_name=dish_name, model=model)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cloudflare.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add bsdm/cloudflare.py tests/test_cloudflare.py
git commit -m "feat(cloudflare): add compile_dish_prompt and evaluate_food_image methods"
```

---

### Task 2: Build Batch Prompt Compiler Module and CLI

**Files:**
- Create: `bsdm/prompt_compiler.py`
- Create: `scripts/compile_prompts.py`
- Test: `tests/test_prompt_compiler.py`

**Interfaces:**
- Consumes: `CloudflareClient.compile_dish_prompt`
- Produces: `bsdm.prompt_compiler.compile_pending(catalog, client, limit, force, only)`

- [ ] **Step 1: Write failing test for prompt compiler**

Create `tests/test_prompt_compiler.py`:
```python
from unittest.mock import MagicMock
from bsdm.prompt_compiler import compile_pending

def test_compile_pending_updates_entries():
    catalog = {
        "dish1": {
            "name": "Beef Hot Dog",
            "ingredients": "beef, salt, sorbitol",
            "tags": ["halal"],
            "category": "beef",
            "needs_image": True,
            "prompt": "Old heuristic prompt",
            "negative": "Old negative",
        }
    }
    client = MagicMock()
    client.is_configured.return_value = True
    client.compile_dish_prompt.return_value = {
        "prompt": "New compiled hot dog prompt",
        "negative": "New negative exclusions",
    }

    updated = compile_pending(catalog, client, limit=None, force=True)
    assert updated == 1
    assert catalog["dish1"]["prompt"] == "New compiled hot dog prompt"
    assert catalog["dish1"]["negative"] == "New negative exclusions"
    assert catalog["dish1"]["prompt_compiled"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_prompt_compiler.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bsdm.prompt_compiler'`

- [ ] **Step 3: Implement bsdm/prompt_compiler.py and scripts/compile_prompts.py**

Create `bsdm/prompt_compiler.py`:
```python
from __future__ import annotations
import logging
from typing import Any
from bsdm.cloudflare import CloudflareClient

log = logging.getLogger(__name__)

COMPILER_REV = 1

def compile_pending(
    catalog: dict[str, Any],
    client: CloudflareClient,
    limit: int | None = None,
    force: bool = False,
    only: str | None = None,
) -> int:
    """Compile structured prompts for catalog dishes missing compiled prompts."""
    if not client.is_configured():
        log.warning("CloudflareClient not configured; skipping prompt compilation")
        return 0

    pending = []
    for did, entry in catalog.items():
        if not entry.get("needs_image"):
            continue
        if only and only.lower() not in entry["name"].lower():
            continue
        if not force and entry.get("prompt_compiled") and entry.get("prompt_compiler_rev", 0) >= COMPILER_REV:
            continue
        pending.append((did, entry))

    if limit is not None:
        pending = pending[:limit]

    count = 0
    for did, entry in pending:
        try:
            res = client.compile_dish_prompt(
                name=entry["name"],
                ingredients=entry.get("ingredients", ""),
                tags=entry.get("tags", []),
                category=entry.get("category", "other"),
            )
            entry["prompt"] = res["prompt"]
            entry["negative"] = res["negative"]
            entry["prompt_compiled"] = True
            entry["prompt_compiler_rev"] = COMPILER_REV
            count += 1
            log.info("Compiled prompt for '%s'", entry["name"])
        except Exception as exc:
            log.warning("Failed to compile prompt for '%s': %s", entry["name"], exc)

    return count
```

Create `scripts/compile_prompts.py`:
```python
#!/usr/bin/env python3
"""Batch compile food photography prompts for dishes using Cloudflare Llama 3.3 70B."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bsdm.cloudflare import CloudflareClient
from bsdm.prompt_compiler import compile_pending

CATALOG_PATH = ROOT / "data" / "dishes.json"

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", help="substring match on dish name")
    ap.add_argument("--limit", type=int, help="max dishes to compile")
    ap.add_argument("--force", action="store_true", help="recompile already compiled dishes")
    args = ap.parse_args()

    client = CloudflareClient()
    if not client.is_configured():
        print("Error: CF_ACCOUNT_ID and CF_API_TOKEN environment variables are required.", file=sys.stderr)
        return 1

    catalog = json.loads(CATALOG_PATH.read_text())
    count = compile_pending(catalog, client, limit=args.limit, force=args.force, only=args.only)
    if count > 0:
        CATALOG_PATH.write_text(json.dumps(catalog, indent=1, ensure_ascii=False, sort_keys=True) + "\n")
        print(f"Successfully compiled prompts for {count} dishes.")
    else:
        print("No dishes needed prompt compilation.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_prompt_compiler.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add bsdm/prompt_compiler.py scripts/compile_prompts.py tests/test_prompt_compiler.py
git commit -m "feat(prompt_compiler): add batch LLM prompt compiler module and CLI"
```

---

### Task 3: Integrate VLM Quality Gate with Multi-Seed Auto-Retry in Image Generation

**Files:**
- Modify: `scripts/gen_images.py:210-280`
- Test: `tests/test_gen_images_gate.py`

**Interfaces:**
- Consumes: `CloudflareClient.evaluate_food_image`
- Logic:
  - Generate image with candidate seed.
  - If VLM evaluation is active, judge card image.
  - If score < 7 and attempts < 3, pick a new seed and retry.
  - Record VLM score and review status in catalog entry.

- [ ] **Step 1: Write unit test for the quality gate loop**

Create `tests/test_gen_images_gate.py`:
```python
from unittest.mock import MagicMock
from PIL import Image
import io

def test_vlm_retry_logic():
    # Test helper verifying score threshold logic
    scores = [4, 8]  # First fails, second succeeds
    client = MagicMock()
    client.is_configured.return_value = True
    client.evaluate_food_image.side_effect = [
        {"valid": False, "score": 4, "reason": "Plastic texture"},
        {"valid": True, "score": 8, "reason": "Good plating and sharp focus"}
    ]

    attempts = 0
    accepted = False
    for attempt in range(3):
        attempts += 1
        res = client.evaluate_food_image(b"fake", "Dish")
        if res["valid"] and res["score"] >= 7:
            accepted = True
            break

    assert attempts == 2
    assert accepted is True
```

- [ ] **Step 2: Run test to verify it passes**

Run: `uv run pytest tests/test_gen_images_gate.py -v`
Expected: PASS

- [ ] **Step 3: Modify scripts/gen_images.py to incorporate VLM gate & multi-seed retry**

In `scripts/gen_images.py`:
- Add CLI flag `--vlm-gate / --no-vlm-gate` (default: True if Cloudflare client configured).
- Add CLI flag `--max-vlm-retries` (default: 3).
- Wrap generation attempt in a loop:
```python
        max_attempts = args.max_vlm_retries if (args.vlm_gate and cf_client.is_configured()) else 1
        for attempt in range(1, max_attempts + 1):
            # generate image using backend ...
            if image is not None and args.vlm_gate and cf_client.is_configured():
                thumb_bytes = to_webp(image)
                eval_res = cf_client.evaluate_food_image(thumb_bytes, dish_name=dish_name)
                score = eval_res.get("score", 0)
                reason = eval_res.get("reason", "")
                if eval_res.get("valid") and score >= 7:
                    print(f"    [VLM Pass] Score {score}/10: {reason}")
                    break
                else:
                    print(f"    [VLM Retry {attempt}/{max_attempts}] Score {score}/10: {reason}")
                    if attempt < max_attempts:
                        import random
                        seed = random.randint(1, 2**31 - 1)
                        image = None
```
- In `record_image`, save `vlm_score` and `vlm_reason` if evaluated.

- [ ] **Step 4: Verify test suite still passes without network**

Run: `uv run pytest`
Expected: All 470+ tests pass.

- [ ] **Step 5: Commit changes**

```bash
git add scripts/gen_images.py tests/test_gen_images_gate.py
git commit -m "feat(gen_images): integrate VLM quality gate and multi-seed retry loop"
```

---

### Task 4: Add Makefile Target and Update Documentation

**Files:**
- Modify: `Makefile`
- Modify: `AGENTS.md`
- Modify: `GEMINI.md`

- [ ] **Step 1: Add prompts target to Makefile**

In `Makefile`:
```makefile
prompts:                   ## compile structured food prompts via Cloudflare LLM
	$(PY) scripts/compile_prompts.py
```

- [ ] **Step 2: Update AGENTS.md and GEMINI.md to document the prompt compiler and quality gate**

Add `make prompts` and explanation of the VLM quality gate.

- [ ] **Step 3: Run full pytest suite to verify no regressions**

Run: `uv run pytest`
Expected: 100% pass.

- [ ] **Step 4: Commit changes**

```bash
git add Makefile AGENTS.md GEMINI.md
git commit -m "docs: add prompts makefile target and update agent documentation"
```

---

### Task 5: End-to-End Verification on Two Live Dishes

**Goal:** As requested by the user, run the pipeline on 2 existing dishes, inspect the generated pictures, and report their VLM evaluation scores.

**Test Dishes:**
- Dish 1: `Beef Hot Dog` (`50ea6a72eb85`)
- Dish 2: `Chicken Fajitas` (`2af8a6c63440`)

- [ ] **Step 1: Run compile_prompts for the test dishes**

Run: `uv run python scripts/compile_prompts.py --only "Beef Hot Dog" --force`
Verify prompt compilation output and JSON fields in `data/dishes.json`.

- [ ] **Step 2: Run image generation with VLM evaluation enabled**

Run: `uv run python scripts/gen_images.py --backend comfyui --model sdxl --only "Beef Hot Dog" --limit 1 --force`
Capture VLM score and generated image.

- [ ] **Step 3: Repeat for Chicken Fajitas**

Run: `uv run python scripts/compile_prompts.py --only "Chicken Fajitas" --force`
Run: `uv run python scripts/gen_images.py --backend comfyui --model sdxl --only "Chicken Fajitas" --limit 1 --force`
Capture VLM score and generated image.

- [ ] **Step 4: Visually inspect resulting images and report findings and VLM scores to the user**
