# Late Night Dining & Shake Smart Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Late Night dining support with Shake Smart Shakes menu item and dynamic late-night hall logo switching for Arrillaga and Lakeside.

**Architecture:** Crop and register logos and dish images from R&DE's Shake Smart banner; extend `config/halls.json` and `bsdm/build.py` to generate `"Late Night"` meal data and late night logos; update `web/app.js` to render the Late Night tab, switch logos dynamically, and handle midnight-crossing hours.

**Tech Stack:** Python 3.12/3.14 (PIL, pytest), Vanilla JavaScript (DOM el(), Node.js test harness), static HTML/CSS.

## Global Constraints
- Only residential dining commons are tracked (Arrillaga and Lakeside; The Axe & Palm is excluded).
- Logo format: WebP at 2x resolution, registered in `data/logos/index.json`.
- Dish format: WebP 16:9 (`1024x576`), registered in `data/dishes.json` under `bcda517df9b6`.
- Full bilingual English/Chinese support in `data/zh.json` and `web/app.js`.

---

### Task 1: Asset Extraction and Registration

**Files:**
- Create: `scripts/extract_late_night_assets.py` (one-off script to generate WebP assets from `data/shake_smart_banner.jpg`)
- Modify: `data/logos/index.json`
- Modify: `data/dishes.json`
- Modify: `data/zh.json`
- Output: `data/logos/arrillaga_late_night.webp`, `data/logos/lakeside_late_night.webp`, `data/images/bcda517df9b6.webp`

- [ ] **Step 1: Write and run asset extraction script**
Crop `arrillaga_late_night.webp`, `lakeside_late_night.webp`, and `bcda517df9b6.webp` from `data/shake_smart_banner.jpg`.
- [ ] **Step 2: Register logos in `data/logos/index.json`**
Add entries for `arrillaga_late_night` and `lakeside_late_night`.
- [ ] **Step 3: Register dish and translations**
Add `bcda517df9b6` to `data/dishes.json` and add Chinese translations to `data/zh.json`.
- [ ] **Step 4: Commit assets**
`git add data/ && git commit -m "data(assets): add late night logos and Shake Smart dish image"`

---

### Task 2: Backend Build and Payload Generation

**Files:**
- Modify: `config/halls.json`
- Modify: `bsdm/build.py`
- Test: `tests/test_build.py`

- [ ] **Step 1: Write failing test in `tests/test_build.py`**
Test that `build_payload()` produces `"Late Night"` in `hours` and `menus` for Arrillaga and Lakeside, and includes `late_night_logo` in `halls`.
- [ ] **Step 2: Update `config/halls.json`**
Set Lakeside `late_night.hours` to `["21:30", "02:00"]`.
- [ ] **Step 3: Implement `bsdm/build.py` changes**
Add `"Late Night"` to `MEALS` and `schedule_for()`; attach `late_night_logo` and populate `menus` with Shake Smart Shakes.
- [ ] **Step 4: Verify test passes**
Run: `uv run pytest tests/test_build.py -k late_night -v`
- [ ] **Step 5: Commit**
`git add config/halls.json bsdm/build.py tests/test_build.py && git commit -m "feat(build): add Late Night meal and late night logos to build payload"`

---

### Task 3: Frontend Application & Dynamic Logo Switching

**Files:**
- Modify: `web/app.js`
- Test: `tests/test_web_js.py`

- [ ] **Step 1: Write failing tests in `tests/test_web_js.py`**
Verify `serviceStatus` handles midnight-crossing spans (`21:00` to `02:00`), `MEALS` includes `Late Night`, and `MEAL_ZH["Late Night"] === "夜宵"`.
- [ ] **Step 2: Update `web/app.js`**
Add `"Late Night"` to `MEALS`, `MEAL_ZH`, update `hallLogo()` to switch logo when `state.meal === "Late Night"`, update `serviceStatus` for midnight crossing, and update `upcoming()` to pick `Late Night` between 20:00 and 02:00.
- [ ] **Step 3: Verify tests pass**
Run: `uv run pytest tests/test_web_js.py -v`
- [ ] **Step 4: Commit**
`git add web/app.js tests/test_web_js.py && git commit -m "feat(web): support Late Night tab and dynamic late-night logos"`

---

### Task 4: Full Site Build, Verification, and Local Server

**Files:**
- Generated: `site/`

- [ ] **Step 1: Run full test suite**
Run: `uv run pytest`
- [ ] **Step 2: Build site**
Run: `uv run python scripts/build_site.py`
- [ ] **Step 3: Start local preview server**
Run: `uv run python scripts/serve.py` in background (port 8777).
