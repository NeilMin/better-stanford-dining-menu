# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

`README.md` explains what the project is and why the design choices were made. Read it first.
This file covers the invariants that are easy to break and only visible across several files.

## Commands

```sh
uv sync
make update        # scrape the rolling 7-day window -> data/menus/, data/stations.json, data/dishes.json
                   #   and follow the specials link on the hours page -> data/specials/
make catalog       # re-derive data/dishes.json from stored menus, then rebuild the site
make images        # draw dishes still missing pictures (needs local ComfyUI on :8189)
make logos         # cut the hall logos out of the R&DE map -> data/logos/
make specials      # fetch the specials calendar on its own
make translate     # fill in data/zh.json (needs the claude CLI; never runs in CI)
make site          # render site/ from data/
make serve         # build, then preview at http://127.0.0.1:8777
make verify        # re-fetch today's dinner live and diff it against what is stored
make hours-diff    # show how the R&DE hours page moved; hours-accept records the new baseline
make logos-check   # has R&DE redrawn the map the logo crop boxes point into?
```

There is no test suite. `make verify` is the correctness check that matters: it re-fetches from
the live source and diffs against `data/`. Narrow it while iterating:

```sh
uv run python scripts/verify.py --day 2026-09-16 --meal Lunch --halls arrillaga,wilbur
uv run python scripts/verify.py --fresh-session     # new session per hall, isolates dropdown faults
uv run python scripts/gen_images.py --only bulgogi --force   # redraw one dish
uv run python scripts/gen_images.py --max-priority 0         # meat only
uv run python scripts/gen_images.py --redraw-stale           # images drawn under older prompt rules
uv run python scripts/translate.py --section dishes --batch 30   # retry names after a dropped batch
uv run python scripts/fetch_specials.py --show                   # every calendar on file
uv run python scripts/fetch_specials.py --dry-run FILE.pdf       # parse a poster, print nothing
uv run python scripts/fetch_logos.py --contact-sheet /tmp/l.png  # eyeball all eight crops
```

## Pipeline order

```
data/menus/*.json  ──stations.analyze()──►  data/stations.json
                                                   │
                   ──────catalog.build()───────────►  data/dishes.json
                                                   │
          gen_images.py ──────────────────────────►  data/images/<dishId>.webp
                                                   │
          fetch_logos.py ─────────────────────────►  data/logos/<hallId>.webp + index.json
                                                   │
          specials.update() ──────────────────────►  data/specials/*.pdf + data/specials.json
                                                   │
          translate.py ───────────────────────────►  data/zh.json
                                                   │
                          build.build() ───────────►  site/
```

Only the first two are ordered with respect to each other. Logos, specials and translations are
independent inputs that the build folds in if they are there and leaves out if they are not.

**Stations must be analysed before the catalog is built.** Station membership decides
`needs_image`, because standing counters render as a dense list with no image slot. Building the
catalog first silently queues pictures for ~14 dishes that will never show one.

`scripts/update.py` and `scripts/rebuild_catalog.py` must both go through `bsdm/catalog.py`.
They drifted once — `update.py` kept an inline copy that overwrote `priority`, `needs_image`,
`station_only` and `min_order` on every scrape.

## Things that will bite you

**`bsdm/zh.py` and `web/app.js` tokenize ingredient strings twice, on purpose.** Python decides
which terms to send for translation; the browser splits the same string again to reassemble the
list in Chinese. Same separators (`,()[]`), same key (whitespace collapsed, lowercased). Change
one and the other goes on asking for terms that were never translated — which shows up as a
stray English word mid-sentence, not as an error. The split is deliberately structure-free:
some R&DE strings open a parenthesis they never close.

**`translate.py` merges per batch and never overwrites.** Same discipline as `record_image()`,
for the same reason: a first run is a couple of dozen model calls over several minutes and has
to survive a Ctrl-C, and a hand-corrected translation must not be undone by the next run. Use
`--force` to redo one deliberately. A dropped batch is normal — it just stays missing and the
next run picks it up.

**`data/zh.json` is generated but committed, and CI never writes it.** Translating needs the
`claude` CLI, so it happens on a laptop and arrives as a commit, exactly like images. New dishes
show their English name in Chinese mode until then; `scripts/update.py` prints how many are
waiting.

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
is prose. `make hours-diff` / `make hours-accept` manage the baseline when it changes. Its
`aliases` field is separate ground truth for one job only: matching the names the specials poster
uses ("AFDC", "Casper", and "Wibur", which is a typo R&DE keeps re-making). Matching already
ignores case and punctuation, so only genuinely different words belong there.

**`config/logos.json` is pixel coordinates into one specific JPEG**, which is why its sha256 sits
next to them. R&DE publishes no per-hall logo files anywhere — the callouts on the dining halls
map are the only place all eight exist — so the boxes are read off that map by hand. A redraw
moves all eight at once and would turn the crops into eight rectangles of street, so
`scripts/fetch_logos.py` refuses to cut against a digest it does not recognise. `--force` is
there for when you have checked; `--contact-sheet` is how you check.

**Logo geometry is bounded by the source, not by the design.** The map is 1920px wide, so a hall's
logo is 30-130px tall inside it and nothing better exists. `render.height` in `config/logos.json`
is therefore *twice* the height the page gives them (`.col-logo`), and the header was sized around
that rather than the other way round. Normalising on height is also why Branner comes out smallest:
its roundel is taller than it is wide. Raising `height` past ~80 buys blur, not size.

**A special is not a row of its own.** The halls share one set of grid rows, so `column()` puts the
specials strip *inside* `.col-head`: a strip that only some columns had would push every card below
it in those columns out of line with the others. Same reason the empty `.col-logo` box is appended
even when a hall has no logo.

**The specials poster is read geometrically, and that is not fussiness.** Text order in the PDF is
meaningless -- one entry's two lines are not adjacent to each other in it, and a note drawn on top
of a row reads as part of that row. `bsdm/specials.py` groups text by which coloured bar contains
it, smallest bar winning, and maps the bar's x-extent to dates through the weekday header. Bars are
told from the grid by the weekend: every background stripe spans the full width, and no special has
ever run on a Saturday. Five editions spanning a year all parse; check a new one with
`scripts/fetch_specials.py --dry-run` before assuming a change is a bug.

**The poster and the menu disagree about who is open, and the menu wins.** Bars run Monday to
Friday even in a week where seven halls reopen on the Tuesday -- the poster says so in a separate
block drawn over the top. `bsdm/build.py` resolves it by only ever attaching a special to a day the
scraped menus show that hall serving that meal, and `web/app.js` only shows one when the selected
meal matches the calendar's. Do not try to derive it from the PDF's z-order.

**An unreadable poster is still archived.** The hours page links one fortnight at a time, so an
edition nobody fetched while it was up is gone for good -- worse than the menus, which at least
have a rolling week. `specials.update()` therefore writes the PDF to `data/specials/` before it
tries to parse it, records the error on the calendar entry, and returns rather than raising:
`scripts/update.py` logs it and carries on with the night's menus.

## Frontend

`web/index.html` is a template with `/*CSS*/`, `/*JS*/` and `/*DATA*/` markers; `bsdm/build.py`
inlines all three into one self-contained `site/index.html`. `</` is escaped as `<\/` inside the
JSON block so a dish name cannot close the script tag early.

- **Bump `STORE` in `web/app.js`** (currently `bsdm.prefs.v4`) whenever the persisted state shape
  changes. Stale localStorage once looked exactly like a scraper bug, because the MCP browser
  shares the user's Chrome profile.
- **`.board` sets `overflow-x: auto`, which makes `overflow-y` compute to `auto`.** That makes it
  the scroll container for `position: sticky`, which is why the column headers are deliberately
  not sticky. Re-adding sticky needs a different containment strategy, not just the property.
- **The halls share one set of grid rows, so a card's height is not its own.** `.board` declares
  the rows and every `.column` is a `subgrid` spanning them: row 1 is every hall's header, row N
  every hall's Nth card. Three places have to agree. `render()` sets `--rows` from the deepest
  column; `column()` gives the standing counters a `grid-row` ending at `-1`, so an expanded list
  of counters spends the rows a short column was not using instead of inflating a row of dish
  cards; and `dishCard()` appends the badge row and the card body *even when they are empty*,
  because the stylesheet reserves a badge row and an allergen line there. That reserve is what
  makes the cards equal in the first place — the subgrid only catches the leftovers, a name or an
  allergen list that runs long.
- **`<img width/height>` defeats `aspect-ratio`** unless `height: auto` is also set. The
  attributes are load-bearing for layout reservation, so keep both.
- **The logos are cut off a printed map, so each one arrives on its own patch of white paper.**
  Invisible on a light card; on a dark one it would read as a bright rectangle stuck to the
  header, so dark mode turns the accident into a deliberate plate — padded, rounded, and pulled
  back out with a negative margin so it does not move the name below it.
- **User-visible English lives in the `UI` table in `web/app.js`, not in the DOM calls.** Both
  languages are written side by side there so a new string cannot ship in one language only. The
  English in `web/index.html` is just what the page says before the script runs; `renderChrome()`
  rewrites all of it.
- **Chinese mode adds a dish name, it does not replace one.** The English line under it is what
  you match against the sign at the counter, so it is styled to stay readable and keeps the Latin
  face — a CJK font's Latin glyphs are conspicuously wider right under a Chinese name. Hall names
  stay English in both languages.

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
until that happens. `data/logos/` and `data/specials/` are committed for the same reason — the
logos because cutting them needs a hand-verified config, the posters because they are an archive
of something the source deletes. CI *does* fetch new posters, because `git add data/` picks them
up; it never re-cuts logos.
