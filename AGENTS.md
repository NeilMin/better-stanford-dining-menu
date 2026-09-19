# AGENTS.md

This file provides high-level guidance for autonomous AI agents and coding assistants (Gemini, Antigravity, Claude Code, Cursor, Codex) working on the Better Stanford Dining Menu (BSDM) repository.

---

## 1. Quick Orientation & Codebase Map

| Path | Purpose |
| :--- | :--- |
| `bsdm/` | Core Python package handling scraping, menus, stations, catalog, specials, logos, and static site build. |
| `bsdm/scrape.py` | ASP.NET WebForms scraper with session state (`__VIEWSTATE` / `__EVENTVALIDATION`). |
| `bsdm/menus.py` | `live/` vs `archive/` management, Pacific timezone definition (`today()`). |
| `bsdm/stations.py` | Standing station detection (recurrence analysis across rolling services). |
| `bsdm/catalog.py` | Dish index builder, priority assignment, carry-over from previous runs. |
| `bsdm/dishes.py` | Protein classification, prompt generation, CLIP negative prompt filtering. |
| `bsdm/specials.py` | Canva PDF geometric parser via PyMuPDF for dinner specials. |
| `bsdm/logos.py` | Cropping hall logos from the campus map JPEG using `config/logos.json`. |
| `bsdm/hours.py` | Fingerprinting and diffing the R&DE Dining Locations & Hours page. |
| `bsdm/source.py` | Monitors R&DE dropdown for new/removed halls; triggers red CI notification. |
| `bsdm/zh.py` | Bilingual translation tokenization and translation table (`data/zh.json`) management. |
| `bsdm/comfy.py` | ComfyUI HTTP client (SDXL / Flux on port `8189`). |
| `bsdm/build.py` | Static site compiler: inlines CSS, JS, and payload JSON into `site/index.html`. |
| `scripts/` | Executable CLI tools invoked by `Makefile` and GitHub Actions workflows. |
| `config/` | Ground-truth metadata (`halls.json`, `logos.json`). |
| `data/` | Scraped menus (`live/`, `archive/`), `dishes.json`, `stations.json`, `zh.json`, images, and logos. |
| `web/` | Web template (`index.html`), vanilla JS application (`app.js`), and responsive styles (`app.css`). |
| `tests/` | Pytest test suite, mock fixtures (`conftest.py`), and JS bridge tests (`test_web_js.py`). |
| `.github/workflows/` | CI/CD workflows: `refresh.yml` (nightly scraper & issue filer), `pages.yml` (deploy to GitHub Pages). |

---

## 2. Essential Commands

```sh
# Setup & Testing
uv sync
make test           # Unit & golden tests (<2s, no network, no GPU)

# Scrape & Build
make update         # Scrape 7-day window, update stations, specials, catalog
make site           # Compile site/
make serve          # Preview at http://127.0.0.1:8777

# Verification & Sanity Checks
make verify         # Live diff today's dinner across all halls against stored data
make hours-diff     # Check if R&DE hours text changed
make source-check   # Check if R&DE dropdown lists unconfigured halls
make logos-check    # Check if map JPEG sha256 changed
```

---

## 3. Mandatory Agent Invariants

1. **Do Not Parallelize Scraper Calls**: ASP.NET WebForms tokens rotate per response; requests must remain sequential.
2. **Never Publish Stale Menus**: If no days in `data/menus/live/` are `>= today` (Pacific time), `bsdm/build.py` must abort with an error rather than falling back.
3. **Keep Tokenizers in Sync**: Any change to ingredient tokenization in `bsdm/zh.py` must be mirrored identically in `web/app.js:splitIngredients()`.
4. **ComfyUI Port**: Always target port `8189` for local image generation.
5. **No Sockets in Tests**: Tests in `tests/` run in sandbox without network; `socket.connect` is intercepted by `tests/conftest.py`.
6. **Detailed Guidance**: Refer to `GEMINI.md` (for Gemini/Antigravity) and `CLAUDE.md` (for Claude Code) for in-depth design rationales and gotchas.
