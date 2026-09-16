# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

`README.md` explains what the project is and why the design choices were made. Read it first.
This file covers the invariants that are easy to break and only visible across several files.

## Commands

```sh
uv sync
make update        # scrape the rolling 7-day window -> data/menus/, data/stations.json, data/dishes.json
make catalog       # re-derive data/dishes.json from stored menus, then rebuild the site
make images        # draw dishes still missing pictures (needs local ComfyUI on :8189)
make site          # render site/ from data/
make serve         # build, then preview at http://127.0.0.1:8777
make verify        # re-fetch today's dinner live and diff it against what is stored
make hours-diff    # show how the R&DE hours page moved; hours-accept records the new baseline
```

There is no test suite. `make verify` is the correctness check that matters: it re-fetches from
the live source and diffs against `data/`. Narrow it while iterating:

```sh
uv run python scripts/verify.py --day 2026-09-16 --meal Lunch --halls arrillaga,wilbur
uv run python scripts/verify.py --fresh-session     # new session per hall, isolates dropdown faults
uv run python scripts/gen_images.py --only bulgogi --force   # redraw one dish
uv run python scripts/gen_images.py --max-priority 0         # meat only
uv run python scripts/gen_images.py --redraw-stale           # images drawn under older prompt rules
```

## Pipeline order

```
data/menus/*.json  ──stations.analyze()──►  data/stations.json
                                                   │
                   ──────catalog.build()───────────►  data/dishes.json
                                                   │
          gen_images.py ──────────────────────────►  data/images/<dishId>.webp
                                                   │
                          build.build() ───────────►  site/
```

**Stations must be analysed before the catalog is built.** Station membership decides
`needs_image`, because standing counters render as a dense list with no image slot. Building the
catalog first silently queues pictures for ~14 dishes that will never show one.

`scripts/update.py` and `scripts/rebuild_catalog.py` must both go through `bsdm/catalog.py`.
They drifted once — `update.py` kept an inline copy that overwrote `priority`, `needs_image`,
`station_only` and `min_order` on every scrape.

## Things that will bite you

**`gen_images.py` must never hold the catalog in memory.** A full backfill runs for hours.
`record_image()` re-reads `data/dishes.json` and merges only the image fields, because a
wholesale rewrite silently reverts any reclassification done while it was running.

**Bump `dishes.PROMPT_REV` whenever prompt rules change.** It is what tells images drawn under
older rules apart from current ones, so `--redraw-stale` can work through them meat-first
instead of forcing a full redraw of the library.

**`_FLAVORING_RE` is shared by `classify()` and `_key_ingredients()` on purpose.** A condiment
that names an animal it does not contain ("A-1 steak sauce", "vegetarian oyster sauce") must be
invisible to both. It was wired only into `classify()` once, and vegetable dishes came back
plated with steak.

**A positive prompt cannot say "no meat".** SDXL conditions on CLIP, which has no negation, so
"vegetarian, no meat" reads as a prompt *about* meat. Proteins are steered out from the negative
side only — `dishes.negative_prompt()` derives the exclusions per dish.

**ComfyUI runs on port 8189, not 8188.** 8188 belongs to another project and has no models
loaded, so probing it makes the shared install look broken. Nothing in this repo may start or
stop the server; it is shared. Long runs should pass `--free-every N` — Metal allocations do not
appear in RSS, so a leak looks like nothing until the OS kills the process.

**Identical menus across halls are normal.** Most halls run a shared cycle menu and breakfast is
one campus-wide menu. A broken location dropdown produces the same symptom, which is the entire
reason `scripts/verify.py` exists. Treat cross-hall duplicates as a prompt to verify against the
live source, never as a finding on their own.

**The scraper is sequential by necessity.** `__VIEWSTATE` / `__EVENTVALIDATION` rotate per
response, so requests cannot be parallelised.

**`config/halls.json` is hand-transcribed ground truth**, not parsed output. The R&DE hours page
is prose. `make hours-diff` / `make hours-accept` manage the baseline when it changes.

## Frontend

`web/index.html` is a template with `/*CSS*/`, `/*JS*/` and `/*DATA*/` markers; `bsdm/build.py`
inlines all three into one self-contained `site/index.html`. `</` is escaped as `<\/` inside the
JSON block so a dish name cannot close the script tag early.

- **Bump `STORE` in `web/app.js`** (currently `bsdm.prefs.v3`) whenever the persisted state shape
  changes. Stale localStorage once looked exactly like a scraper bug, because the MCP browser
  shares the user's Chrome profile.
- **`.board` sets `overflow-x: auto`, which makes `overflow-y` compute to `auto`.** That makes it
  the scroll container for `position: sticky`, which is why the column headers are deliberately
  not sticky. Re-adding sticky needs a different containment strategy, not just the property.
- **`<img width/height>` defeats `aspect-ratio`** unless `height: auto` is also set. The
  attributes are load-bearing for layout reservation, so keep both.

## Deployment

Live at **https://stanford-dining.neilmin.com** (Porkbun CNAME → `neilmin.github.io`, Pages
source: GitHub Actions).

- `refresh.yml` — cron only. Scrapes, commits `data/`, then **calls** `pages.yml`. It calls
  rather than relies on its own push, because a push made with `GITHUB_TOKEN` does not fire
  `on: push`.
- `pages.yml` — builds and deploys, on push or when called. It checks out `main` **by name**: a
  called workflow otherwise checks out the commit that started the run, which predates the
  refresh commit.
- `ENABLE_PAGES="false"` is the kill switch; unset means publish.
- `bsdm/build.py` writes `CNAME` into the artifact. It cannot *set* the custom domain on an
  Actions-sourced site — that is a one-time setting — but it stops a deploy without it from
  clearing the setting.

`site/` is build output and is not committed. `data/` is, including images: CI has no GPU, so
images are generated locally, committed, and pushed. New dishes appear with a placeholder icon
until that happens.
