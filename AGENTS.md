# AGENTS.md

Guidance for AI coding agents working in this repository -- Claude Code reads this file directly;
Gemini / Antigravity also read `GEMINI.md`, a shorter digest of the same rules.

`README.md` explains what the project is and why the design choices were made. Read it first.
This file covers the invariants that are easy to break and only visible across several files.

## Codebase map

| Path | Purpose |
| :--- | :--- |
| `bsdm/` | Core Python package handling scraping, menus, stations, catalog, specials, logos, and static site build. |
| `bsdm/scrape.py` | ASP.NET WebForms scraper with session state (`__VIEWSTATE` / `__EVENTVALIDATION`). |
| `bsdm/menus.py` | `live/` vs `archive/` management, Pacific timezone definition (`today()`). |
| `bsdm/stations.py` | Standing station detection (recurrence analysis across rolling services). |
| `bsdm/catalog.py` | Dish index builder, priority assignment, carry-over from previous runs. |
| `bsdm/dishes.py` | Protein classification, prompt generation, CLIP negative prompt filtering. |
| `bsdm/brief.py` | Per-dish visual brief (what the picture must show, plus yes/no checks), written once by an LLM into `data/briefs.json`. |
| `bsdm/judge.py` | Asks a brief's checks of a drawn picture, blind; a picture is kept only if it passes. |
| `bsdm/llm.py` | The model behind briefs and judging: the `claude` CLI on the laptop, Gemini's free tier (`GEMINI_API_KEY`) where there is no CLI. |
| `bsdm/cloudflare.py` | Cloudflare Workers AI client (Llama 3.3 70B translation, Flux.1 Schnell images). |
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
| `.github/workflows/` | `refresh.yml` (scrape and translate, twice a day), `draw.yml` (after each scrape: draw and judge new dishes on several free runners at once), `pages.yml` (test, build, deploy to GitHub Pages). |

## Commands

```sh
uv sync
make test          # the suite: no network, no GPU, ~2s
make update        # scrape the rolling 7-day window -> data/menus/, data/stations.json, data/dishes.json
                   #   and follow the specials link on the hours page -> data/specials/
make catalog       # re-derive data/dishes.json from stored menus, then rebuild the site
make images        # draw dishes still missing pictures (local ComfyUI on :8189 + the claude CLI,
                   #   which writes each dish's brief and judges every picture)
make images-todo   # print the dishes still waiting for a picture (what the nightly job files)
make logos         # cut the hall logos out of the R&DE map -> data/logos/
make specials      # fetch the specials calendar on its own
make translate     # fill in data/zh.json (the claude CLI, else Gemma with GEMINI_API_KEY)
make site          # render site/ from data/
make serve         # build, then preview at http://127.0.0.1:8777
make verify        # re-fetch today's dinner live and diff it against what is stored
make hours-diff    # show how the R&DE hours page moved; hours-accept records the new baseline
make source-check  # is R&DE offering a hall config/halls.json has never heard of?
make logos-check   # has R&DE redrawn the map the logo crop boxes point into?
```

`make test` is the suite. It runs in `pages.yml` *before* the build, for the same reason
`build()` refuses to fall back to last week's menus: the site is published straight off `data/`,
and a deploy that replaces a good site with a wrong one is worse than a deploy that does not
happen. The scrape commits `data/` either way, so a red suite costs the tick and nothing else.

`make verify` is the other half and the suite cannot replace it: it re-fetches from the live
source and diffs against `data/`. Narrow either while iterating:

```sh
uv run pytest tests/test_catalog.py -k min_order
uv run pytest -m "not golden"                    # skip the tests that read committed data/
uv run pytest -m "not node"                      # skip the ones that shell out to node
uv run python scripts/verify.py --day 2026-09-16 --meal Lunch --halls arrillaga,wilbur
uv run python scripts/verify.py --fresh-session     # new session per hall, isolates dropdown faults
uv run python scripts/gen_images.py --only bulgogi --force   # redraw one dish
uv run python scripts/gen_images.py --only bulgogi --force --rewrite-briefs  # ...from a fresh brief
uv run python scripts/gen_images.py --max-priority 0         # meat only
uv run python scripts/gen_images.py --redraw-stale           # images drawn under older prompt rules
uv run python scripts/gen_images.py --no-judge --only x      # draw once, unjudged: you will look yourself
uv run python scripts/eval_judge.py --sample 20              # score the judge on pictures already ruled on
uv run python scripts/notify_images.py --dry-run             # the backlog issue, printed not filed
uv run python scripts/translate.py --section dishes --batch 30   # retry names after a dropped batch
uv run python scripts/fetch_specials.py --show                   # every calendar on file
uv run python scripts/fetch_specials.py --dry-run FILE.pdf       # parse a poster, print nothing
uv run python scripts/fetch_logos.py --contact-sheet /tmp/l.png  # eyeball all eight crops
```

## Pipeline order

```
data/menus/live/ + archive/YYYY/MM/
                   ──stations.analyze()──►  data/stations.json
                                                   │
                   ──────catalog.build()───────────►  data/dishes.json
                                                   │
          gen_images.py ──brief, draw, judge──────►  data/briefs.json + data/images/<dishId>.webp
                                                   │
          fetch_logos.py ─────────────────────────►  data/logos/<hallId>.webp + index.json
                                                   │
          specials.update() ──────────────────────►  data/specials/*.pdf + data/specials.json
                                                   │
          translate.py ───────────────────────────►  data/zh.json
                                                   │
                          build.build() ───────────►  site/
```

Logos and translations are independent inputs that the build folds in if they are there and
leaves out if they are not. Specials are not independent of the catalog: **a special is a dish**, so
`catalog.build()` takes `specials.dishes()` and queues a picture for each, drawn from the name alone
and at priority 0. That is why `scripts/update.py` rebuilds the catalog *after* fetching the poster.

**Stations must be analysed before the catalog is built.** Station membership decides
`needs_image`, because standing counters render as a dense list with no image slot. Building the
catalog first silently queues pictures for ~14 dishes that will never show one.

`scripts/update.py` and `scripts/rebuild_catalog.py` must both go through `bsdm/catalog.py`.
They drifted once — `update.py` kept an inline copy that overwrote `priority`, `needs_image`,
`station_only` and `min_order` on every scrape.

## Things that will bite you

**A hall R&DE adds is not something the scrape can act on, so the nightly run goes red instead.**
`scripts/update.py` iterates `config/halls.json` and used never to ask the dropdown what else was
there, which made a new hall completely invisible: no error, CI green, and seven days later its
menus are gone for good. It cannot be automated — a hall needs a `menu_key`, a schedule, aliases,
an address and a logo crop box, and the dropdown carries one of those — so `bsdm/source.py` records
what the source offered and `scripts/check_source.py` fails the job at the very end, after the
menus are committed and `publish` is on its way. That ordering is the whole design: the finding
must not cost a night's data, and a warning in a green log is the silence we already had. Which is
also why `publish` carries `if: ${{ !cancelled() }}` — a red run means somebody edits config, not
that today's menus are withheld. Measure *unknown* against every hall in config and *missing*
against the active ones only: EVGR sits in the dropdown while config has it inactive, and a
dropdown entry is not a hall serving food.

**`bsdm/menus.py` owns which days a job reads, and the only definition of "today".** `live()` is
what the board publishes, `recent()` is the bounded window classification is judged over,
`history()` is every menu ever stored and belongs to explicit replays — `rebuild_catalog.py
--replay-archive` and the translation table, which has to keep offering a term it saw once and
never got an answer for. Do not glob `data/menus` directly; the layout is `live/` plus
`archive/YYYY/MM/` and the predicate that splits them has to stay in one place. `TZ` used to be
declared three times over; `today()` is Pacific because the nightly job runs at 06:20 UTC, which
is 23:20 the previous day in California, and a UTC reading would archive a day still being served
and leave the board short of it.

**A build with no live day refuses to run; a build where nobody is serving publishes.** They look
alike and are not: a break is a day whose `halls` are empty and the board should say so, while an
empty `live/` means the scrape did not run and the answer is to fix the scrape. `build()` used to
fall back to the newest seven days on file, which turned a broken scraper into a site quietly
serving last week's dinner — and, worse, replaced a good deploy with it. Never reach backwards for
data to publish.

**`catalog.build()` accumulates, it does not re-derive.** It reads a window, not the whole
archive, so anything outside that window survives only through `previous` — the carry-over at the
bottom of `build()`. `min_order` is merged *above* the rules rather than below them because it is
the menu position that decides `priority`, and taking the minimum over only the window demotes a
dish that was listed first in March to a side. A dish dropped from the catalog would orphan the
picture in `data/images/` that is keyed to it and come back a stranger owing an hour of GPU time.

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

**`data/zh.json` is generated but committed, and both CI and the laptop write it.** The nightly
job translates what the scrape brought in with Gemma on the Gemini free tier, before it draws;
`make translate` on a laptop uses the `claude` CLI. A dish the night could not translate shows its
English name in Chinese mode until a later run does; `scripts/update.py` prints how many are
waiting. The step is `continue-on-error`, like drawing: a spent quota is tomorrow's work.

**The picture backlog must not become a red run.** `bsdm/source.py` owns red and it means a hall
needs a config entry *tonight* or its menus are lost; a dish without a picture is what a new dish
looks like until the nightly draw reaches it. `scripts/notify_images.py` can keep one standing
GitHub issue for the backlog (body rewritten nightly, the ids in an HTML comment so GitHub holds
the state), but it is not wired into `refresh.yml` any more: the owner asked not to be mailed, and
`make images-todo` prints the same list on demand.

**`bsdm/pending.py` asks what the board shows, not what the catalog claims.** A dish counts as
waiting when `needs_image` is set and there is no image file on disk — the same test
`bsdm/build.py` makes before it renders a thumb. Reading `entry["image"]` alone would go
quiet exactly when somebody drew the pictures and forgot to `git add data/images`.

**`gen_images.py` must never hold the catalog in memory.** A full backfill runs for hours.
`record_image()` re-reads `data/dishes.json` and merges only the image fields, because a
wholesale rewrite silently reverts any reclassification done while it was running.

**Bump `dishes.PROMPT_REV` whenever prompt rules change.** It is what tells images drawn under
older rules apart from current ones, so `--redraw-stale` can work through them meat-first
instead of forcing a full redraw of the library. `brief.BRIEF_REV` is the same for the brief
writer's instructions: a brief under an older rev is rewritten the next time its dish is drawn.

**A picture is kept only after it passes; never the best of the failures.** `gen_images.py`
writes an image only when `bsdm/judge.py` passes it, and a judge that cannot answer — an
unparseable reply, a spent subscription — keeps nothing. A dish nothing passes for keeps its
placeholder icon and gets a `rejected` record. The gate this replaced kept the highest-scoring
of three failures and, when Cloudflare's quota ran out mid-run, switched itself off and kept
whatever it had; a "Beef Souvlaki" it had itself scored 3/10 went up that way. A wrong picture
is worse than the icon, for the same reason `build()` will not publish last week's menus.

**Everything that draws, briefs or judges costs nothing, and has to stay that way.** The site is
meant to run unattended for years on free tiers; a backend that goes away must degrade to the
placeholder icon, never to an unchecked picture. What each job runs on, and why:

- *Drawing*: RealVisXL everywhere -- the local ComfyUI on the laptop, and in CI the same
  checkpoint on free GitHub runners' CPUs (`draw.yml`), at the laptop's 1344x768 and 12 steps
  instead of 20. A runner takes 17-19 minutes a picture at 15.3 GB of its 16, so the queue is
  dealt across up to six machines (`--shard K/N`), each stops starting dishes after four hours
  (`--minutes`), and `scripts/merge_draws.py` folds their copies of `data/` back into main as it
  is by then. The runners are for the few new dishes a scrape brings; a backlog (a new
  `BRIEF_REV`, a term's first week of menus) is the laptop's, at a minute and a half a picture --
  the owner's division, so hold `draw.yml`'s trigger while the laptop works one off. The owner compared sizes by eye: 1024x576 was clearly worse, 12 steps against 20
  was not. FLUX.2 [klein] on Cloudflare's free tier drew in CI for a day and was turned down as
  too plastic; `--backend cloudflare` and `photo_style(close=True)` are what is left of it. The
  CPU route had been ruled out once already on the time per picture alone, before anyone counted
  machines -- a public repository's runners are free, twenty at a time, six hours each.
- *Briefs* (the dish knowledge): the `claude` CLI on the laptop; in CI a `bsdm.llm.Chain` of
  Gemini Flash versions, then Gemma -- Flash's free tier is 20 requests a day *per model*, so they
  take turns. Gemma 4 26B alone wrote briefs that said souvlaki is not on skewers. Briefs are
  written eight dishes to a call (`--brief-batch`), which is what keeps a night inside Flash's
  allowance; it scored the same on the eval as one a call, for Claude and for Flash alike.
- *Judging*: the `claude` CLI on the laptop; in CI Gemma 4 26B on the Gemini API, which judged
  the eval set as well as Claude Sonnet did and has the free quota for a night. Gemma is asked
  without JSON mode (it loops until the server hangs up) and, for translation, with thinking at
  "minimal" (it otherwise thinks through its whole output cap).
- *Translation*: the `claude` CLI, else Gemma. Never Cloudflare while its neurons can draw.

`--llm` picks the brief writer (and the judge, unless `--judge-llm` says otherwise); `auto` takes
the CLI where it is installed. GitHub Models, the obvious free choice in 2025, was retired on
2026-07-30.

**The dish knowledge lives in the brief, not in `dishes.py`.** SDXL does not know what gyro meat
or miso black cod looks like, and for two weeks a person supplied it one regex at a time — the
per-dish branches in `_hero_protein_phrase()` and `negative_prompt()`. `bsdm/brief.py` asks a
language model once per dish for what the picture must show and records it in
`data/briefs.json`. Do not add new per-dish branches to `dishes.py`; they only feed the
rule-based prompt now, which draws only under `--no-judge` without the claude CLI. If a dish
keeps failing, read its brief first.

**A brief's checks are about which dish, never about garnish.** The judge fails a picture on
any check, so a check must be something that makes a diner say "that is not what I ordered":
the protein, the form (sliced vs ground, wrapped vs loose), raw vs cooked, a different dish.
Asked about sesame seeds and lemon wedges, the first version of the judge failed 19 of the 29
pictures a person had accepted. "unclear" fails a defining feature and passes a mistake, for the
same reason. A revision may change `look` and `avoid` but not what a check tests — a model asked
to get past its own failed check decides the check was wrong. The one exception is a check no
picture could answer ("unclear" every time, e.g. "is the meat in this curry pork?"): it may be
reworded, keeping its expected answer, or the dish would sit on its placeholder for good.

**`data/briefs.json` has one writer and is not the catalog.** `catalog.build()` re-derives
`dishes.json` on every scrape and keeps only the image fields named in `catalog.IMAGE_FIELDS`;
a new field `gen_images.py` records has to be added there or the next scrape drops it. That is
how the old gate's `vlm_score` went missing. Briefs are kept out of that churn altogether.

**Measure the judge before trusting a change to it.** `scripts/eval_judge.py` replays every
picture a person rejected by eye (the version before each fix commit) against the one they
accepted in its place, so a change to the judge or the brief instructions can be scored without
anyone looking at a picture again. The rejects are noisy — some of those commits also redrew
pictures nobody had complained about, and near-identical pairs show it — so read its misses
before chasing the number.

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

**A special is a card, not a banner.** It was once a strip in the column header, which hid the one
dish people walk across campus for. Now `bsdm/build.py` gives each service a `specials` list of
ordinary dish refs next to `daily`, and `column()` renders them first, whatever meat-first does to
the rest, as a `.card-special`. A dish the menu also lists is shown once, as the special, and keeps
the menu's ingredients. `catalog.build()` must set `placeholder: False` on them: an empty ingredient
list is what `is_placeholder()` reads as "changes daily", which would skip the picture.

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
scraped menus show that hall serving that meal -- filed under the calendar's meal, so the page
needs no meal guard of its own. Campus-wide notes stay `notices`, checked against the meal in
`web/app.js`. Do not try to derive it from the PDF's z-order.

**An unreadable poster is still archived.** The hours page links one fortnight at a time, so an
edition nobody fetched while it was up is gone for good -- worse than the menus, which at least
have a rolling week. `specials.update()` therefore writes the PDF to `data/specials/` before it
tries to parse it, records the error on the calendar entry, and returns rather than raising:
`scripts/update.py` logs it and carries on with the night's menus.

## Tests

The suite is organised around the invariants in this file rather than around the modules, because
that is where the regressions have been. Conventions worth keeping:

**Every module takes a `root`, so a test builds a miniature project instead of mocking a
filesystem.** `tests/conftest.py` has the `project` fixture: `add_hall`, `write_menu` /
`archive_menu`, `write_stations`, `write_catalog`, `write_specials`, `write_zh`. Menus go in
through those two methods and never by writing a path, for the same reason `bsdm/menus.py` exists
-- live/ and archive/ are one predicate apart and no test should be the second place it is spelled.

**The clock is pinned with `project.set_today(...)`, which patches two modules.** `bsdm/source.py`
imports the name rather than the module, so patching `bsdm.menus.today` alone leaves it reading the
real calendar -- which passes today and fails next year.

**No test may open a socket.** An autouse fixture refuses at `socket.connect`. Every fetch in the
project has an injection point (`html=` on hours and specials, a session on `MenuScraper`, a blob
on the logo cutter) and the guard is what keeps them used.

**`golden` marks the tests that read committed artefacts** -- the posters in `data/specials/`, the
menus, the catalog. They are the only check that five separately-written directories still fit
together, and they are pinned to the window on disk rather than the wall clock so they keep
testing the data instead of expiring with it. Adding a poster to the archive extends the parser's
test suite by itself.

**`node` marks the tests that run `web/app.js`.** It is one IIFE that reads the DOM on its first
line, so `tests/jsbridge.py` slices a declaration out of the file by name and evaluates it alone,
with what it closes over supplied as a prelude. Brittle on purpose: renaming a function there is a
failure with a message, not a silent skip. What it is guarding is the tokenizer pair above, which
has no other way to be checked at all.

## Frontend

`web/index.html` is a template with `/*CSS*/`, `/*JS*/` and `/*DATA*/` markers; `bsdm/build.py`
inlines all three into one self-contained `site/index.html`. `</` is escaped as `<\/` inside the
JSON block so a dish name cannot close the script tag early.

- **The page is used on a phone first.** About 70% of visitors come from a phone, so no change
  to the page is done until it has been looked at 360, 390 and 430 px wide, as well as on the
  laptop it was written on. A line that fits on the laptop is the usual casualty: the English
  name in the masthead fitted at 1710 px and lost "Side by Side" to an ellipsis at 390, which
  is why it is set in two lines. `scrollWidth > clientWidth` on an element finds a clipped line
  faster than a screenshot does.
- **Bump `STORE` in `web/app.js`** (currently `bsdm.prefs.v4`) whenever the persisted state shape
  changes. Stale localStorage once looked exactly like a scraper bug, because the MCP browser
  shares the user's Chrome profile.
- **The language of a first visit comes from the browser, not from a constant.** `fallback.lang`
  is `preferredLang()`: the first tag in `navigator.languages` whose primary subtag is one `UI`
  has a table for, English otherwise. It is a default, so a saved preference still wins on the
  way back in and the tour inherits it for free (it reads `t()` like everything else). Adding a
  third language is a new key in `UI` and nothing here.
- **The date is deliberately not persisted**; everything else in `state` is. `load()` and `save()`
  both strip it, so old saves that carry one still open on today.
- **A shared link is shown, not adopted.** The share button beside the headline sends
  `?d=&m=&h=` — the day, the meal and the halls, never a preference — and `readLink()` drops
  whatever the build does not publish. The halls and the meal are remembered, so a friend's
  link must not overwrite yours: they go into `borrowed`, `save()` writes `own` back for each,
  and a key leaves `borrowed` only when its own control is clicked (hall chip, meal chip,
  Reset). A new control that sets a borrowed key has to do the same. The query is cleared on
  arrival, which keeps the date unremembered through a reload or a bookmark.
- **Every active hall also has its own page, `/<hallId>/`,** written by `build.page_html()`
  from the same template: its own title, description, canonical and `og:url`, a
  `FoodEstablishment` JSON-LD block, and the week written out as plain HTML (`#prerender`) for
  crawlers that run no script — `render()` removes it on the first draw. It exists for search:
  the official menu has no URL per hall. Four things hold it together. The page is one
  directory down, so every `img/` and `logo/` path in `web/app.js` starts with `PAGE.root`;
  a new asset path that forgets it breaks only on the hall pages. The hall is *borrowed*
  exactly like a shared link's halls. `renderChrome()` keeps the hall's title rather than
  `docTitle`, because Google reads the title after the script has run. And `_swap()` refuses to
  build if a head tag it rewrites has changed in `index.html`: a hall page that kept the home
  page's canonical would be filed as a duplicate of it. Pages are made for every *active* hall
  in config, serving or not, so a break does not drop them from the index.
- **`web/og.jpg` is the link-preview card, composed once by hand** from the logos and a few
  dish pictures. The page is static, so every link unfurls with the same one; the line the
  button sends with the link is what says which view it is. `og:image` is an absolute URL on
  `build.DOMAIN`, and a test holds the two together.
- **The first-visit tour has its own key, `bsdm.tour.v1`,** set when the tour starts, so Reset and
  a `STORE` bump do not replay it. To see it again, delete that key. Its ring and tip are
  `position: fixed` overlays placed over the target, not styles on the target: on a phone each
  `.controls` row scrolls sideways and fades at the edge, which would clip a ring drawn inside it.
  A stop points at a static element from `index.html` (a `.group` wrapper or `#lang`), because
  `render()` replaces the chips inside it on every click.
- **Colours are declared once, as `light-dark()` pairs on `:root` in `web/app.css`.** The theme
  button only sets `data-theme`, which picks the `color-scheme` those pairs resolve against. A new
  colour is a new pair there, not a rule repeated under `[data-theme="dark"]` and the media query.
  The interface is greys plus cardinal; hall pastels are only a key (name underline, chip dot,
  the wash behind a special), and the colour on the page is meant to come from the photographs.
- **On a phone `.top` is `display: contents`.** That is what lets `.bar` (day and meal) stick to
  the page while the name row scrolls away: a sticky element only sticks inside its parent's
  box, and the wrapper is exactly as tall as the bar. On a desktop the whole `.top` is sticky.
- **`.board` sets `overflow-x: auto`, which makes `overflow-y` compute to `auto`.** That makes it
  the scroll container for `position: sticky`, so a sticky column header would anchor to the
  board rather than to the page and never stick at all. That is why the hall row that stays
  visible is `.pinned`, a `position: fixed` strip drawn over the board by `syncPins()` and laid
  on the columns' own measured rects — an overlay, like the tour's ring, so the board's layout
  and the subgrid rows are untouched by it. It carries only the name and the logo: the hours,
  the concept line and the counts are read once at the top and not again.
  The same scroller clips anything past the first and last column, so `.board` carries a
  negative margin and matching padding of `--bleed`: that is the room a special's panel reaches
  out into. Change one and the other.
- **`.board` is the only thing allowed to be wider than `--page`.** `<main>` spans the window and
  hands the cap back to `.notices`; the masthead, the title, the chips and the footer keep
  `--page` and do not move, whatever is selected — controls that shift under the cursor when you
  pick a hall are worse than a board you have to scroll, which is why `render()` writes `--cols`
  onto the board and nowhere near the root. `100%` inside `.board` therefore means the window less
  the gutters, which is what `<main>` spanning the window buys: the ceiling is deliberately not
  `100vw`, which counts the scrollbar and would push the whole page sideways.
- **Four column widths, and they answer different questions.** `--col-max` is what a column
  *asks* for when there is room, so `--want` (N of them) is how far the board grows on a wide
  screen. The other three are bounds, and two of them are derived from `--limit` rather than
  written down, so they are what N halls really measure on *this* screen rather than on an
  imaginary one:
  - `--col-cap`, the width **three** halls have side by side, is the most a column may ever be.
    `--full` (N of them) is what holds one or two halls to the size three of them have instead of
    blowing a single photograph up to the width of the page.
  - `--col-floor`, the width **five** halls have side by side, is the least it may ever be. A
    sixth hall is laid out after the fifth at that same width and the board scrolls, rather than
    every column giving up a few pixels to it. It is the min of the `minmax()`, so the tracks
    overflow `--width` and the scroller takes over, which is how `--col-min` behaved before it.
  - `--col-min` is the last word under both, for a window too narrow for the arithmetic to mean
    anything. It is the one number of the four that is a judgement rather than a derivation.

  `--width` clamps `--want` between `min(--limit, --full)` and the window, and `--want` is itself
  held under `--full`, so "never wider than three of them" holds outright and not just while
  `--col-max` happens to be the smaller number.
- **A board narrower than the page starts on the page's left edge; a wider one centres on the
  window.** `min()` over the two offsets picks between them with no branch, and they agree at
  three halls. Centring a short board instead would leave the title and the chips above it
  hanging off a left edge of their own, which reads as a bug — it was built that way once.
- **The columns are in chip order, not in click order.** The board reads `state.halls` straight
  through, so `hallOrder()` keeps that list sorted by `DATA.halls` — on the way in from storage
  and again on every toggle — and a hall picked last slots in where its chip sits rather than
  appearing on the right of the board. Filtering against `DATA.halls` is also what drops a stored
  id the build no longer publishes, which `render()` would otherwise crash on.
- **A dish card leads with its picture,** so the pictures in one row start level across the halls
  however many lines the names above them would have taken. `dishCard()` appends the thumb before
  the name block.
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
- **The type is Stanford's own: Source Serif 4 for names and headings, Source Sans 3 for
  everything else,** from Google Fonts, with platform fallbacks so the page still reads offline.
  In Chinese the serif roles take the CJK sans rather than a Song face, which is faint at these
  sizes; `html:lang(zh)` rules put the CJK stack first and hand the English-only lines back to
  the Latin face.

## Deployment

Live at **https://stanford-dining.neilmin.com** (Porkbun CNAME → `neilmin.github.io`, Pages
source: GitHub Actions).

- `draw.yml` — after each `refresh.yml` run, or by hand (the `dry_run` input hands the result
  back as an artifact instead of committing it). A `plan` job counts the queue, `draw` runs one job per
  machine, `collect` merges and pushes, retrying from the new main if a scrape landed first.
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

`site/` is build output and is not committed. `data/` is, including images: `draw.yml` draws
new dishes after each scrape with RealVisXL on free runners and commits what the judge passes;
the laptop draws with the same model, and `gen_images.py --audit` judges the pictures drawn
before there was a judge. A dish shows a placeholder icon until a picture of it passes. `data/logos/` and `data/specials/` are committed for the same reason — the
logos because cutting them needs a hand-verified config, the posters because they are an archive
of something the source deletes. CI *does* fetch new posters, because `git add data/` picks them
up; it never re-cuts logos.
