# GEMINI.md

This file provides guidance and domain context for Gemini / Antigravity when working with code in this repository.
It complements `README.md` (project goals and design choices) and `CLAUDE.md`.

---

## 1. Project Overview & Architecture

**Better Stanford Dining Menu (BSDM)** solves the core dining question at Stanford: *"Of the dining halls I'd walk to, which one has the better dinner tonight?"*

R&DE's official menu app only shows one hall, one meal, and one day at a time. BSDM scrapes all dining halls for a rolling 7-day window and publishes a static, responsive web dashboard comparing halls side-by-side, illustrated with locally-generated AI dish photos, protein classifications, live hours, dinner specials parsed from PDF posters, and full bilingual (EN/ZH) support.

### Pipeline Dependency Graph

```
data/menus/live/ + archive/YYYY/MM/
                   ──stations.analyze()──►  data/stations.json
                                                   │
                   ──────catalog.build()───────────►  data/dishes.json
                                                   │        ▲
          compile_prompts.py ──────────────────────┘        │
                                                   │
          gen_images.py (VLM quality gate) ───────►  data/images/<dishId>.webp
                                                   │
          fetch_logos.py ─────────────────────────►  data/logos/<hallId>.webp + index.json
                                                   │
          specials.update() ──────────────────────►  data/specials/*.pdf + data/specials.json
                                                   │
          translate.py ───────────────────────────►  data/zh.json
                                                   │
                          build.build() ───────────►  site/ (index.html, logo/, CNAME)
```

---

## 2. Commands & Workflow

```sh
uv sync
make test          # Full test suite: no network, no GPU, ~2s
make update        # Scrape rolling 7-day window -> data/menus/, data/stations.json, data/dishes.json, data/specials/
make prompts       # Compile structured food photography prompts via Cloudflare LLM
make catalog       # Re-derive data/dishes.json from stored menus, then rebuild site
make images        # Generate images for dishes missing pictures (requires local ComfyUI on :8189)
make images-todo   # Check pending dishes waiting for image generation
make logos         # Crop hall logos from R&DE campus map -> data/logos/
make logos-check   # Verify whether R&DE map coordinates have moved
make specials      # Fetch and parse dinner specials PDF calendar
make translate     # Fill in data/zh.json (requires claude CLI; run locally)
make site          # Render static site/ from data/
make serve         # Preview at http://127.0.0.1:8777
make verify        # Live fetch and diff against stored data to detect scraper faults
make hours-diff    # Diff R&DE hours text against data/hours_snapshot.json
make hours-accept  # Update hours snapshot baseline
make source-check  # Verify if R&DE added/removed halls in dropdown
```

### Targeted Test / Script Invocations

```sh
uv run pytest tests/test_catalog.py -k min_order
uv run pytest -m "not golden"                           # Skip tests reading committed data/
uv run pytest -m "not node"                             # Skip tests invoking node for web/app.js
uv run python scripts/verify.py --day 2026-09-18 --meal Dinner --halls arrillaga,wilbur
uv run python scripts/compile_prompts.py --only bulgogi --force
uv run python scripts/gen_images.py --max-priority 0    # Meat only
uv run python scripts/gen_images.py --only bulgogi --force --seed 12345
uv run python scripts/gen_images.py --no-vlm-gate       # Skip VLM evaluation
uv run python scripts/translate.py --dry-run
uv run python scripts/fetch_specials.py --show
```

---

## 3. Critical Invariants & Rules (DO NOT BREAK)

### Scraper & Source Integrity
- **Sequential Requests Only**: R&DE's app is ASP.NET WebForms. `__VIEWSTATE` and `__EVENTVALIDATION` rotate on each request. Requests **cannot** be parallelized.
- **Clock is Pacific (`America/Los_Angeles`)**: Scheduled cron runs twice daily (08:30 UTC = 01:30 PT, and 21:30 UTC = 14:30 PT). `bsdm/menus.py:today()` defines the serving date.
- **Self-Healing Scraper Retries**: If an expected service returns empty dishes (due to transient ASP.NET session desync / empty postback), `scripts/update.py` immediately retries once with a fresh `MenuScraper` instance and adopts the new healthy session upon recovery.
- **Archive is Append-Only**: Days `< today` are moved from `data/menus/live/` to `data/menus/archive/YYYY/MM/` by `bsdm/menus.py:archive_past()`. Past days are never re-scraped or overwritten.
- **A New Dining Hall Causes a Red CI Run**: `bsdm/source.py` tracks halls in the dropdown. If R&DE adds a hall not in `config/halls.json`, `scripts/check_source.py` fails the CI run *after* data is committed and published. This alerts the maintainer immediately without losing data.
- **Never Publish Stale Menus**: If `data/menus/live/` has no days `>= today`, `bsdm/build.py` raises `SystemExit` instead of falling back to old menus.

### Catalog & Stations
- **Stations Before Catalog**: `bsdm/stations.py:analyze()` must run *before* `bsdm/catalog.py:build()`. Standing stations (recurrence ratio >= 0.6 over recent services) render as dense text lists without image slots. Inverting order queues unnecessary image generation.
- **Catalog Accumulates Sightings**: `catalog.build()` reads a bounded window (`menus.recent()`), preserving prior entries via `previous`. `min_order` is merged *before* priority calculation so a dish served as an entree in March is not demoted to a side later.
- **Specials are Priority-0 Dishes**: Specials parsed from the poster are added to `data/dishes.json` with `priority = 0`, `min_order = 0`, and `placeholder = False`.

### Image Generation, Prompt Compilation & VLM Quality Gate
- **Port 8189**: ComfyUI runs on port `8189`, **not** `8188` (8188 belongs to an unrelated project).
- **Upstream Prompt Compiler**: `scripts/compile_prompts.py` batches prompt compilation via Cloudflare Llama 3.3 70B (`bsdm.prompt_compiler.compile_pending()`), extracting dish composition, plated appearance, lighting, and negative prompts. Sets `prompt_compiled: true` and `prompt_compiler_rev: 1` in `data/dishes.json`. `bsdm/catalog.py:build()` carries forward existing compiled prompts across catalog updates.
- **Downstream VLM Quality Gate**: `scripts/gen_images.py` integrates a multi-seed generation loop with Cloudflare Llama 3.2 11B Vision (`--vlm-gate`, default True). Generated images are scored on dish fidelity and visual appeal; scores >= 7 pass. On failure, retries up to `--max-vlm-retries 3` with new random seeds before accepting the highest-scoring candidate. `vlm_score` and `vlm_reason` are saved to image metadata in `data/dishes.json`.
- **Graceful Cloudflare Degradation**: Both prompt compilation and VLM evaluation check `client.is_configured()`. If `CF_ACCOUNT_ID` or `CF_API_TOKEN` are absent, prompt compilation is safely skipped and `gen_images.py` falls back directly to rule-based heuristic prompts and un-gated generation.
- **Prompt Rev**: Bump `bsdm/dishes.py:PROMPT_REV` whenever prompt generation rules change, allowing `--redraw-stale` to selectively refresh older images.
- **SDXL Prompting Rules**: Positive prompts **cannot** use phrases like "no meat" (CLIP lacks negation and interprets this as a prompt about meat). Protein exclusions are strictly placed in `bsdm/dishes.py:negative_prompt()`.
- **Flavoring Exclusion**: `_FLAVORING_RE` in `bsdm/dishes.py` prevents condiments like "chicken soup base" or "A-1 steak sauce" from turning vegetable dishes into meat classifications or drawing meat on the plate.
- **Image Backlog Reporting**: CI cannot run ComfyUI. `scripts/notify_images.py` manages a standing GitHub issue (`Dishes waiting for a picture`), only commenting when newly discovered dishes need pictures.

### Specials Poster
- **Geometric Parsing via PyMuPDF**: Canva PDF text stream order is non-linear. `bsdm/specials.py` reads geometry: coloured rectangles define date ranges, text belongs to the smallest enclosing bounding box.
- **Menu Outranks Poster for Open State**: Specials span Mon–Fri even if a hall opens on Tuesday. `bsdm/build.py` only renders a special if the scraped menu confirms that hall is serving dinner that day.

### Bilingual / Translation (Chinese & English)
- **Tokenizer Parity**: `bsdm/zh.py:terms_in()` and `web/app.js:splitIngredients()` tokenize ingredient strings using the exact same separator regex (`([,()\[\]])`) and normalization. Any deviation produces untranslated English words in Chinese mode.
- **Incremental Merging**: `scripts/translate.py` merges batches into `data/zh.json` without overwriting existing manual edits.
- **UI Strings**: User-visible strings live in the `UI` dictionary in `web/app.js`, ensuring English and Chinese stay in sync.

### Testing Invariants
- **No Sockets in Tests**: Autouse fixture in `tests/conftest.py` blocks `socket.connect`. All network calls must be mocked or use pre-recorded fixtures.
- **Clock Pinning**: Tests use `project.set_today(...)`, which patches both `bsdm.menus.today` and `bsdm.source.today`.

---

## 4. Frontend & Layout Mechanics

- **Single Inlined HTML Artifact**: `web/index.html` contains `/*CSS*/`, `/*JS*/`, and `/*DATA*/` placeholders. `bsdm/build.py` generates the self-contained `site/index.html`.
- **CSS Grid & Subgrid**: `.board` defines row templates and each `.column` uses CSS `subgrid`. Standing counters use `grid-row: auto / -1` to fill unused rows without expanding dish card heights.
- **Pinned Headers (`.pinned`)**: `.board` has `overflow-x: auto`, which makes `overflow-y` compute to `auto` and breaks standard `position: sticky`. The sticky hall row is a `position: fixed` overlay synchronized via `syncPins()`.
- **Light/Dark Scheme**: Colors use CSS `light-dark()` pairs on `:root` in `web/app.css`, controlled by the `[data-theme]` attribute.
- **LocalStorage Storage Keys**: State is stored in `bsdm.prefs.v4`. Tour state is stored in `bsdm.tour.v1`. Dates are **never** persisted to localStorage.
