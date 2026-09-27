# GEMINI.md

This file provides guidance and domain context for Gemini / Antigravity when working with code in this repository.
It complements `README.md` (project goals and design choices) and `AGENTS.md`, which has the
full invariants and the reasons for them.

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
                                                   │
          gen_images.py (brief, draw, judge) ─────►  data/briefs.json + data/images/<dishId>.webp
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
make catalog       # Re-derive data/dishes.json from stored menus, then rebuild site
make images        # Draw dishes missing pictures (local ComfyUI on :8189 + claude CLI for briefs and judging)
make images-todo   # Check pending dishes waiting for image generation
make logos         # Crop hall logos from R&DE campus map -> data/logos/
make logos-check   # Verify whether R&DE map coordinates have moved
make specials      # Fetch and parse dinner specials PDF calendar
make translate     # Fill in data/zh.json (claude CLI, else Gemma with GEMINI_API_KEY; CI runs it nightly)
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
uv run python scripts/gen_images.py --max-priority 0    # Meat only
uv run python scripts/gen_images.py --only bulgogi --force --seed 12345
uv run python scripts/gen_images.py --no-judge --only x  # Draw once, unjudged (you will look yourself)
uv run python scripts/eval_judge.py --sample 20          # Score the judge on pictures a person already ruled on
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

### Image Generation: Brief, Draw, Judge
- **Port 8189**: ComfyUI runs on port `8189`, **not** `8188` (8188 belongs to an unrelated project).
- **Brief**: `bsdm/brief.py` asks a language model (`bsdm/llm.py`: the `claude` CLI on the laptop, the free Gemini API with `GEMINI_API_KEY` in CI) once per dish for what the picture must show: a cookbook name, a CLIP-friendly `look`, `plate`/`bowl`, an `avoid` list (the negative prompt) and 2-4 yes/no `checks`. Stored in `data/briefs.json`, which only `gen_images.py` writes. `BRIEF_REV` bumps rewrite briefs.
- **Judge**: `bsdm/judge.py` asks the brief's checks plus shared ones (recognisable? a spread of several dishes? text or hands?) blind, and compares the answers itself. Checks are about *which dish* (protein, form, raw vs cooked), never garnish. "unclear" fails a defining feature and passes a mistake.
- **Never Keep a Failure**: failed pictures are redrawn (`--attempts`), then the brief is revised from the failures (`--revisions`; `checks` never change). A picture is written only after it passes; otherwise the dish keeps its placeholder and a `rejected` record. New image fields must be listed in `catalog.IMAGE_FIELDS` or the next scrape drops them.
- **Evaluate Before Trusting**: `scripts/eval_judge.py` replays pictures a person rejected (the version before each fix commit) against the accepted replacement.
- **Prompt Rev**: Bump `bsdm/dishes.py:PROMPT_REV` whenever prompt generation rules change, allowing `--redraw-stale` to selectively refresh older images.
- **SDXL Prompting Rules**: Positive prompts **cannot** use phrases like "no meat" (CLIP lacks negation and interprets this as a prompt about meat). Protein exclusions are strictly placed in `bsdm/dishes.py:negative_prompt()`.
- **Flavoring Exclusion**: `_FLAVORING_RE` in `bsdm/dishes.py` prevents condiments like "chicken soup base" or "A-1 steak sauce" from turning vegetable dishes into meat classifications or drawing meat on the plate.
- **Everything Free**: CI draws with the laptop's RealVisXL on free GitHub runners' CPUs, the queue split across up to six machines (`draw.yml`, `--shard`), writes briefs eight dishes to a call with a chain of Gemini Flash models then Gemma (Flash's free tier is 20 requests/day per model), and judges and translates with Gemma 4 26B -- all on the free `GEMINI_API_KEY`. The laptop uses ComfyUI RealVisXL and the `claude` CLI. RealVisXL on a free GitHub runner was measured at 29-31 min/picture and ruled out. Nothing paid, ever; a backend that disappears must degrade to the placeholder icon.

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
