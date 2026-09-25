# Image Quality and Pipeline Resilience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish systematic guardrails against hallucinated, raw, or misclassified dish photos by implementing culinary domain heuristics, strictly enforcing VLM quality gating on web-search fallbacks, setting local RealVisXL as standard, and adding an automated image audit tool.

**Architecture:**
- Domain Heuristics Layer in `bsdm/dishes.py`: Expand semantic parsing for grains (cooked/fluffy/steamed in bowls, raw exclusions), curries (rich golden turmeric gravy, clear water exclusions), plant-based proteins (crispy pan-seared edges, tuber confusion exclusions), grilled fruits/vegan dishes (meat exclusions), and non-edible dried spices (bay leaves, star anise, cinnamon sticks).
- Web-Search Quality Gate Enforcement in `bsdm/web_image.py` & `scripts/gen_images.py`: Enforce strict VLM validation (`min_score >= 7`) on web search results, ban un-gated fallback image adoption, and default pipeline to local ComfyUI RealVisXL.
- Image Quality Auditor in `scripts/audit_images.py`: Scan dish catalog and images for culinary integrity, flagging unverified web searches, missing domain safeguards, or corrupt files.

**Tech Stack:** Python 3.11+, Pytest, Pillow, Cloudflare Workers AI (Llama 3.2 Vision), ComfyUI (RealVisXL).

## Global Constraints

- Clock is Pacific (`America/Los_Angeles`).
- Autouse fixture in `tests/conftest.py` blocks `socket.connect`; all tests must be mock-based and offline.
- Existing image aspect ratio is 16:9 (`1024x576`) WebP.
- Preserve all existing tests and passing test suite (`uv run pytest` must stay green).

---

### Task 1: Add Culinary Domain Heuristics for Grains, Curries, Tofu, and Grilled Fruits

**Files:**
- Modify: `bsdm/dishes.py:20-220`
- Test: `tests/test_dishes.py`

**Interfaces:**
- `bsdm.dishes.prompt(entry: dict) -> str`: Generates positive photography prompt.
- `bsdm.dishes.negative_prompt(entry: dict) -> str`: Generates negative exclusion tokens.
- `bsdm.dishes._hero_protein_phrase(entry: dict) -> str`: Builds hero phrase based on dish category, name, and ingredients.
- `bsdm.dishes._INVISIBLE_RE`: Regex of ingredients hidden from visible prompt.

- [ ] **Step 1: Write failing unit tests for domain heuristics**

Add tests in `tests/test_dishes.py`:
- `test_grain_heuristics_cooked_and_negative_raw()`: Checks that rice/grain dishes have cooked descriptors and raw grain negative exclusions.
- `test_curry_heuristics_turmeric_gravy_and_negative_clear()`: Checks that curry dishes have rich golden gravy and exclude clear water/broth.
- `test_tofu_heuristics_crispy_edges_and_potato_exclusion()`: Checks that tofu with sweet potatoes excludes potato chunks.
- `test_grilled_fruit_heuristics_exclude_meat()`: Checks that grilled pineapple or vegan dishes exclude meat, steak, pork, barbecue meat.
- `test_invisible_spices_excluded_from_hero()`: Checks that star anise, cinnamon stick, and cardamom pods are filtered out.

```python
def test_grain_heuristics_cooked_and_negative_raw():
    entry = {"name": "Jasmine Rice", "category": "vegan", "ingredients": "jasmine rice, water"}
    p = dishes.prompt(entry)
    neg = dishes.negative_prompt(entry)
    assert "steamed fluffy cooked" in p
    assert "raw rice" in neg
    assert "uncooked rice" in neg
    assert "dry rice grains" in neg

def test_curry_heuristics_turmeric_gravy_and_negative_clear():
    entry = {"name": "Vegetable Curry", "category": "vegan", "ingredients": "carrots, peas, curry powder"}
    p = dishes.prompt(entry)
    neg = dishes.negative_prompt(entry)
    assert "thick golden-yellow turmeric curry gravy" in p
    assert "clear water" in neg
    assert "watery soup" in neg

def test_tofu_heuristics_crispy_edges_and_potato_exclusion():
    entry = {"name": "Teriyaki Tofu", "category": "vegan", "ingredients": "tofu, sweet potatoes, teriyaki sauce"}
    p = dishes.prompt(entry)
    neg = dishes.negative_prompt(entry)
    assert "crispy golden pan-seared" in p
    assert "sweet potato" in neg or "potato" in neg

def test_grilled_fruit_heuristics_exclude_meat():
    entry = {"name": "Grilled Peaches", "category": "vegan", "ingredients": "peaches, brown sugar"}
    neg = dishes.negative_prompt(entry)
    assert "meat" in neg
    assert "steak" in neg
    assert "pork" in neg

def test_invisible_spices_excluded_from_hero():
    entry = {"name": "Spiced Lentils", "category": "vegan", "ingredients": "lentils, star anise, cinnamon stick, bay leaf, cardamom pod"}
    p = dishes.prompt(entry)
    assert "star anise" not in p
    assert "cinnamon stick" not in p
    assert "cardamom pod" not in p
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_dishes.py -k "heuristics or invisible_spices"`
Expected: FAIL (missing phrases and exclusions).

- [ ] **Step 3: Implement domain heuristics in `bsdm/dishes.py`**

In `bsdm/dishes.py`:
1. Expand `_INVISIBLE_RE`:
   ```python
   _INVISIBLE_RE = re.compile(
       r"\b(?:canola|olive|vegetable|soybean|sunflower|sesame|cooking)\s+oil\b|"
       r"\boil\s+blend\b|\bextra\s+virgin\b|\bcooking\s+spray\b|"
       r"\bsalt\b|\bblack\s+pepper\b|\bwhite\s+pepper\b|\bkosher\s+salt\b|\bsea\s+salt\b|"
       r"\bwater\b|\bice\b|\bcornstarch\b|\bflour\b|\bbaking\s+(?:powder|soda)\b|"
       r"\bsoy\s+lecithin\b|\bxanthan\s+gum\b|\byeast\b|\bextract\b|"
       r"\bpotassium\s+sorbate\b|\bsodium\s+benzoate\b|\bcitric\s+acid\b|"
       r"\bflavoring\b|\bnatural\s+flavor\b|\bmonosodium\s+glutamate\b|\bmsg\b|"
       r"\bbay\s+(?:leaves?|leaf)\b|\bstar\s+anise\b|\bcinnamon\s+sticks?\b|"
       r"\bwhole\s+cloves?\b|\bcardamom\s+pods?\b|\blemongrass\s+stalks?\b",
       re.IGNORECASE,
   )
   ```
2. In `_hero_protein_phrase`:
   - Detect rice/grains:
     ```python
     if re.search(r"\b(rice|basmati|jasmine|pilaf|quinoa|polenta|couscous|risotto)\b", name, re.I):
         return "steamed fluffy cooked rice grains, glistening and tender, served warm in a ceramic bowl"
     ```
   - Detect curry:
     ```python
     if re.search(r"\b(curry|curried|tikka|masala|korma|vindaloo)\b", name, re.I):
         return "thoroughly simmered in rich thick golden-yellow turmeric curry gravy coating all vegetables and ingredients"
     ```
   - Detect tofu/plant protein:
     ```python
     if re.search(r"\b(tofu|tempeh|seitan|plant-based)\b", name, re.I):
         return "crispy golden pan-seared firm tofu cubes with tender curd interior"
     ```
3. In `negative_prompt`:
   - Grains:
     ```python
     if re.search(r"\b(rice|basmati|jasmine|grain|quinoa|pilaf)\b", name, re.I):
         neg.extend(["raw rice", "uncooked rice", "dry rice grains", "raw grains", "sack of rice", "paddy", "field"])
     ```
   - Curry:
     ```python
     if re.search(r"\b(curry|curried|tikka|masala|korma)\b", name, re.I):
         neg.extend(["clear water", "clear broth", "watery soup", "plain boiled vegetables", "dry un-sauced vegetables"])
     ```
   - Tofu with tuber ingredients:
     ```python
     if re.search(r"\b(tofu|tempeh)\b", name, re.I) and re.search(r"\b(sweet potato|potato|yam)\b", ingredients, re.I):
         neg.extend(["potato", "potatoes", "sweet potato", "starchy chunks", "potato cubes", "french fries", "cheese cubes"])
     ```
   - Grilled fruits or vegan dishes:
     ```python
     if (re.search(r"\b(grilled|roasted|charred|bbq)\b", name, re.I) and
         (entry.get("category") in ("vegan", "vegetarian") or re.search(r"\b(pineapple|peach|apple|watermelon|fruit)\b", name, re.I))):
         neg.extend(["meat", "pork", "steak", "beef", "poultry", "chicken", "ribs", "bacon", "ham", "sausage", "barbecue meat", "meat cuts"])
     ```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_dishes.py -k "heuristics or invisible_spices"`
Expected: PASS.

- [ ] **Step 5: Run full test suite and commit**

Run: `uv run pytest`
Expected: 514+ passed.
Commit:
```bash
git add bsdm/dishes.py tests/test_dishes.py
git commit -m "feat(dishes): add culinary domain heuristics for grains, curries, tofu, and grilled fruits"
```

---

### Task 2: Strictly Enforce VLM Verification on Web-Search and Deprecate Blind Fallbacks

**Files:**
- Modify: `bsdm/web_image.py:320-405`
- Modify: `scripts/gen_images.py:120-340`
- Test: `tests/test_web_image.py`
- Test: `tests/test_gen_images.py`

**Interfaces:**
- `bsdm.web_image.search_food_image(dish_name: str, client: CloudflareClient | None = None, min_score: int = 7, require_vlm: bool = True, timeout: int = 15) -> bytes | None`
- In `scripts/gen_images.py`: `--search-first` defaults to `False`; `--search-fallback` requires VLM (`require_vlm=True`, `min_score=7`); un-gated acceptance is strictly removed.

- [ ] **Step 1: Write failing tests for require_vlm enforcement**

In `tests/test_web_image.py`:
- `test_search_food_image_without_client_and_require_vlm_returns_none()`: When `require_vlm=True` and `client=None`, returns `None` instead of raw candidate bytes.
- `test_search_food_image_with_require_vlm_false_returns_candidate()`: When `require_vlm=False`, returns candidate bytes (for backward compatibility where explicitly requested).

```python
@patch("bsdm.web_image.search_bing")
@patch("requests.Session.get")
def test_search_food_image_without_client_and_require_vlm_returns_none(mock_get, mock_bing):
    fake_img = _make_fake_image(width=800, height=600)
    mock_bing.return_value = [("https://example.com/bing_dish.jpg", 800, 600)]
    mock_get.return_value = MagicMock(status_code=200, content=fake_img)

    result = search_food_image("Basmati Rice", client=None, require_vlm=True)
    assert result is None
```

In `tests/test_gen_images.py`:
- Test that fallback search without VLM does not assign `model: "web-search"` to dishes without VLM approval.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_web_image.py -k "require_vlm"`
Expected: FAIL.

- [ ] **Step 3: Implement require_vlm enforcement in `bsdm/web_image.py` & `scripts/gen_images.py`**

In `bsdm/web_image.py`:
```python
def search_food_image(
    dish_name: str,
    client: CloudflareClient | None = None,
    min_score: int = 7,
    require_vlm: bool = True,
    timeout: int = 15,
) -> bytes | None:
    ...
    for img_url, w, h in candidates:
        ...
        if client is not None and client.is_configured():
            eval_fn = getattr(client, "evaluate_food_image", client.evaluate_image)
            eval_res = eval_fn(r.content, dish_name)
            score = eval_res.get("score", 0)
            valid = eval_res.get("valid", False)
            reason = eval_res.get("reason", "")
            if valid and score >= min_score:
                log.info("VLM accepted candidate for '%s': score=%d (%s)", dish_name, score, reason)
                return r.content
            else:
                log.info("VLM rejected candidate for '%s': valid=%s, score=%d (%s)", dish_name, valid, score, reason)
                continue
        elif require_vlm:
            # Without configured VLM to inspect image contents, reject candidate to prevent unvetted errors
            log.warning("Skipping unverified candidate for '%s' because VLM evaluation is required", dish_name)
            continue
        else:
            return r.content
    return None
```

In `scripts/gen_images.py`:
1. Change `--search-first` default:
   ```python
   ap.add_argument("--search-first", action=argparse.BooleanOptionalAction, default=False,
                   help="try web food search + VLM judge before AI generation (default: False)")
   ```
2. In `generate_with_search`:
   ```python
   def generate_with_search(
       dish_name: str, client: CloudflareClient | None = None, min_score: int = 7, require_vlm: bool = True
   ) -> tuple[Image.Image | None, float]:
       started = time.monotonic()
       data = web_image.search_food_image(dish_name, client=client, min_score=min_score, require_vlm=require_vlm)
       secs = time.monotonic() - started
       if not data:
           return None, secs
       try:
           raw_img = Image.open(io.BytesIO(data)).convert("RGB")
           return crop_and_resize_to_card(raw_img), secs
       except Exception:
           return None, secs
   ```
3. Update `generate_with_search_fallback`:
   ```python
   def generate_with_search_fallback(dish_name: str, client: CloudflareClient | None = None) -> tuple[Image.Image | None, float]:
       """Search web only if VLM can verify candidate."""
       return generate_with_search(dish_name, client=client, min_score=7, require_vlm=True)
   ```

- [ ] **Step 4: Update affected tests in `tests/test_web_image.py` and `tests/test_gen_images.py`**

Ensure tests calling `search_food_image` pass `require_vlm=False` when testing legacy fallback paths or pass mock `client` when testing VLM gating.

- [ ] **Step 5: Run tests and verify they pass**

Run: `uv run pytest tests/test_web_image.py tests/test_gen_images.py`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add bsdm/web_image.py scripts/gen_images.py tests/test_web_image.py tests/test_gen_images.py
git commit -m "feat(pipeline): enforce strict VLM gate on web images and disable blind fallbacks"
```

---

### Task 3: Build Automated Dish Image Integrity Auditor (`scripts/audit_images.py`)

**Files:**
- Create: `scripts/audit_images.py`
- Create: `tests/test_audit_images.py`
- Modify: `Makefile`

**Interfaces:**
- `scripts/audit_images.py`: CLI tool scanning `data/dishes.json` and `data/images/`.
  Flags:
  - `--strict`: Exit code 1 on any warning/error.
  - `--fix`: Clear unverified or anomalous image references in `data/dishes.json` so they are cleanly re-queued for generation.
  - `--dish-id`: Audit a specific dish ID.

- [ ] **Step 1: Write test for image auditor**

Create `tests/test_audit_images.py`:
- Test that auditor flags:
  1. A dish with `model: "web-search"` but no `vlm_score` or `vlm_score < 7`.
  2. A rice dish whose prompt lacks cooked indicators or negative lacks raw grain exclusions.
  3. A curry dish whose prompt lacks curry gravy.
  4. An image file that is missing or not 1024x576.
- Test that `--fix` clears `entry["image"] = None` and `entry["needs_image"] = True` for flagged items.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_audit_images.py`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `scripts/audit_images.py`**

In `scripts/audit_images.py`:
- Load `data/dishes.json`.
- For each dish with an image:
  - Check file existence in `data/images/{image}`.
  - Verify aspect ratio / dimensions (1024x576) and format (WebP).
  - Verify model provenance: if `model == "web-search"`, check `vlm_score >= 7`. Flag if missing or unvetted.
  - Check prompt domain heuristic conformity:
    * Rice dishes: must contain cooked indicators and raw negative exclusions.
    * Curry dishes: must contain curry sauce indicators.
    * Grilled vegan/fruit dishes: must contain meat exclusions in negative prompt.
- Provide summary output with issue counts.
- If `--fix` is passed, reset `image`, `generated_at`, `model` for invalid dishes and mark `needs_image: true`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_audit_images.py`
Expected: PASS.

- [ ] **Step 5: Add `make audit-images` to `Makefile`**

In `Makefile`:
```makefile
audit-images:
	uv run python scripts/audit_images.py
```

- [ ] **Step 6: Commit**

```bash
git add scripts/audit_images.py tests/test_audit_images.py Makefile
git commit -m "feat(audit): add automated dish image and prompt heuristic auditor"
```

---

### Task 4: Run Auditor Against Current Catalog and Verify Full Pipeline

**Files:**
- Run: `scripts/audit_images.py`
- Modify: `data/dishes.json` (if any stale unverified web-search dishes are flagged and fixed)
- Test: All unit and golden tests (`uv run pytest`)

- [ ] **Step 1: Run audit tool on current repository**

Run: `uv run python scripts/audit_images.py`
Inspect output for any existing legacy dishes with unverified web searches or heuristic flaws.

- [ ] **Step 2: Run full test suite**

Run: `uv run pytest`
Expected: All 514+ tests pass.

- [ ] **Step 3: Run site build**

Run: `uv run python scripts/build_site.py` (or `make site`)
Expected: Site builds cleanly without errors.

- [ ] **Step 4: Commit and push**

Commit any catalog cleanups or rule refinements.
