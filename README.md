# Stanford Dining, Side by Side

The official [R&DE dining hall menu](https://rdeapps.stanford.edu/dininghallmenu/) shows you
one hall, on one day, for one meal, and makes you re-pick all three from dropdowns to see
anything else. That is the wrong shape for the only question that actually matters at 6pm:
**of the two or three halls I'd walk to, which one has the better dinner tonight?**

This scrapes all of it and puts the halls next to each other, with a picture of every dish.

<!-- screenshot -->

## What it does

- **Side-by-side columns.** Pick any halls; each becomes a column you compare at a glance.
  Switch meal or day and all the columns move together.
- **A picture of every dish.** Menu names like "Craveable Grains" or "Magnolia Boil" tell you
  nothing. Every dish gets an image generated locally from its name *and its ingredient list*,
  so the picture reflects the actual recipe.
- **Meat first.** Dishes are classified by protein and sorted meat-first by default, with the
  protein called out on the card.
- **"Only here" badges.** A dish on offer at exactly one of the halls you selected is the
  reason to walk to that one. Every hall has a burger bar; that is not a tiebreaker.
- **The hall's own logo on its column.** Eight halls, eight marks you already know from the
  signs — quicker to pick out than eight names in the same typeface.
- **Tonight's special, first.** R&DE publishes limited-time specials in a PDF poster that the menu
  app knows nothing about. It is scraped, read, and shown as the first dish of the hall it belongs
  to — highlighted, with its own picture drawn from the name, since the poster gives nothing else.
- **Real hours.** Each column shows that hall's hours for the selected meal and whether it is
  open right now.
- **Allergens as served.** A few dishes differ by hall — Branner runs allergen-free versions of
  the same recipes — so each column shows the allergens for *that* hall's version.
- **A Chinese mode.** One switch in the masthead. Dish names come up in Chinese *with* the
  English kept underneath — the sign at the counter still says "Magnolia Boil" — while
  ingredients, allergens and the interface itself are in Chinese outright.

## Quick start

```sh
uv sync
make test        # the suite: no network, no GPU
make update      # scrape the rolling 7-day window into data/menus/, and the specials poster
make logos       # cut the hall logos out of the R&DE map (once; they rarely change)
make images      # draw the dishes still missing pictures (needs local ComfyUI)
make translate   # fill in the Chinese still missing (needs the claude CLI)
make serve       # preview at http://127.0.0.1:8777
```

`make update`, `make logos` and `make site` need only network access. `make images` needs a GPU and
`make translate` needs the Claude Code CLI, which is why both are separate steps.

## How it fits together

```
R&DE menu app  ─┐                          ┌─►  data/menus/live/YYYY-MM-DD.json   (what ships)
                ├── scripts/update.py ─────┼─►  data/menus/archive/YYYY/MM/…     (what has passed)
R&DE hours page ┘  (and the specials PDF   ├─►  data/dishes.json                 (catalog + images)
                    it links to)           └─►  data/specials/YYYY/MM/*.pdf + data/specials.json
                    it links to)                                │
R&DE halls map ─── scripts/fetch_logos.py ──►  data/logos/<hallId>.webp
                                                                │
local ComfyUI  ─── scripts/gen_images.py ───►  data/images/<dishId>.webp
                                                                │
claude CLI     ─── scripts/translate.py ────►  data/zh.json     │
                                                                │
                   scripts/build_site.py ───────────────────────►  site/index.html
                                                                   site/img/ + site/logo/
```

**Live and archive.** R&DE offers today..today+6 and nothing behind it, so a day not scraped
while it was up is gone and `data/menus/` is the only copy of it that will ever exist. But the
board shows only what the source still covers. Those two jobs are separated on disk rather than
in memory: `live/` is the window the site publishes, `archive/YYYY/MM/` is everything that has
passed, and `bsdm/menus.py` owns both the split and the definition of "today" that draws it —
Pacific, because that is the day the halls are serving and because the nightly job runs at 23:20
California time, where a UTC reading would archive a day still being served. Each job then asks
for the window it wants: the board takes `live()`, classification takes a bounded `recent()`, and
only an explicit replay walks `history()`. The archive is append-only — the scrape window starts
at today, so a day that has passed is never rewritten.

**Scraping.** The menu app is ASP.NET WebForms, so a query is a POST carrying `__VIEWSTATE` and
`__EVENTVALIDATION` harvested from the previous response, not a URL. Tokens rotate per response,
so requests are sequential. A full pass is ~180 requests and takes about three minutes.

**Dish identity.** Everything expensive is keyed on the normalized dish name. A week of menus is
~2,600 dish rows but only ~270 distinct dishes, because "Seasonal Steamed Vegetables" is served
almost everywhere. Images are drawn once and reused across every hall and week the dish appears
in, so the steady-state cost is the handful of genuinely new dishes each day.

**Hours are transcribed, not parsed.** `config/halls.json` is hand-written ground truth from the
[Dining Locations & Hours](https://rde.stanford.edu/dining-hospitality/dining-locations-hours)
page. That page is prose — orientation-week exceptions and a "Fall Hours Begin Friday" line
sitting above a weekday table — and a parser for it would be guesswork that rots silently.
Instead `scripts/update.py` fingerprints the page and warns when it changes:

```sh
make hours-diff      # see what moved
# ...edit config/halls.json to match...
make hours-accept    # record the new baseline
```

**Tests.** `make test` runs the suite: no network, no GPU, a couple of seconds. It is organised
around the invariants rather than the modules -- what a bounded window may carry over, what the
station split decides about pictures, which day counts as today -- because that is where the
regressions have been. Two parts of it are worth knowing about: the tests marked `golden` build
the site out of the checkout's own `data/`, which is the only thing that checks five
separately-written directories still fit together, and the ones marked `node` run functions
straight out of `web/app.js`, because the Chinese ingredient list is reassembled by a tokenizer
that has to match `bsdm/zh.py` exactly. The suite runs in CI before the site is built.

```sh
make test
uv run pytest tests/test_catalog.py -k min_order
uv run pytest -m "not golden"
```

**Verifying the scrape.** Most halls run a shared cycle menu, so identical menus across
halls are normal rather than a bug — and that makes a scraper fault hard to spot, because a
broken location dropdown produces the same symptom. `make verify` re-fetches live and diffs
against what is stored:

```sh
make verify
uv run python scripts/verify.py --day 2026-09-16 --meal Lunch --halls arrillaga,wilbur
```

Measured over one week of real data (145 hall-services), the discriminating power looks like
this: **breakfast is one campus-wide menu, identical at every hall, every day.** Lunch and
dinner return 5–7 distinct menus across 8 halls. Branner is unique in all 8 of its services;
Arrillaga and Ricker match some other hall in 20 of 21. So dinner is where choosing actually
matters — which is why it is the default meal.

**Chinese is translated once per term, not once per dish.** A week of menus is ~2,600 dish rows
whose ingredient lists contain only ~870 distinct terms — "salt" accounts for 247 of them — so
the vocabulary is translated once into `data/zh.json` and the page reassembles each list from it
in the browser. Wording then cannot drift between two dishes that list the same thing, and a new
day costs a handful of names plus whichever terms have genuinely never been seen before.
Ingredient lists are lists, not prose, which is the whole reason this works; dish names are not,
so those are translated whole.

The engine is the Claude Code CLI in headless mode, so translating costs nothing beyond a
subscription already in use and needs no API key:

```sh
make translate                                        # everything missing
uv run python scripts/translate.py --dry-run          # what would be sent
uv run python scripts/translate.py --only tofu --force  # redo a few dishes
```

Like images this runs locally and its output is committed — CI scrapes and publishes but never
translates — so a brand-new dish shows its English name in Chinese mode until the next local run
lands. Hall names stay in English throughout: "Arrillaga" is what the building says and what
anyone you ask will call it.

**Specials are a poster, not an API.** Every fortnight R&DE replaces a PDF calendar of dinner
specials — the sort of thing that is the entire reason to walk to one hall over another — and
links it from the hours page under a filename nobody could predict (`Dining Hall Specials
Calendar_Sept14-25.pdf`, `Dining_Hall_Specials_Calendar_Aug3-14_0.pdf`, `...Calendar_H Frame
Nov17-28.pdf`). So the link is scraped rather than guessed, and every edition is archived in
`data/specials/`: the page only ever points at the current one.

Reading it is geometry rather than text order. Each special is a coloured bar drawn across the
days it runs, with `Hall: dish` on top of it, so the bar's width is the date range and its height
is what groups the lines of one entry. Text goes to the *smallest* bar containing it, which is
what stops a note drawn over a row — a Thanksgiving band, a "reopens Tuesday" block — from being
read as part of the special underneath. Bars are told apart from the grid by the weekend: the
background stripes run the full width, and no special has ever run on a Saturday.

```sh
make specials                                                   # fetch and fold in
uv run python scripts/fetch_specials.py --show                  # what is on file
uv run python scripts/fetch_specials.py --dry-run data/specials/2026-09-14_*.pdf
```

The poster's bars span Monday to Friday even where a hall reopens on the Tuesday, so a special is
only ever shown on a day the scraped menus say that hall is actually serving that meal — and only
under the meal the calendar is for, which so far has always been dinner. There it leads the hall's
column as a dish card of its own.

**The hall logos come out of a map.** R&DE publishes no logo files: not on the site, not in its
sitemap, not in the Wayback index of its file tree. The one place all eight appear is the callout
boxes on the [dining halls
map](https://rde.stanford.edu/dining-hospitality/dining-locations-hours), so that is where they
are cut from — `config/logos.json` holds a hand-verified pixel box per hall, alongside the digest
of the exact image they were read off, because a redrawn map moves all eight at once:

```sh
make logos                                                    # cut them
make logos-check                                              # has the map moved?
uv run python scripts/fetch_logos.py --contact-sheet /tmp/logos.png
```

That map is 1920px wide and a logo is 30–130px tall inside it, which is the whole budget: the
files are written at 2× the box the page gives them and the header is sized to what the source
can carry, not the other way round. The callouts are slightly translucent, so a crop also carries
a wash of whatever the logo was standing on; that is flattened to white on the way through, on a
threshold strict enough to spare Arrillaga's cream roof panel.

**Image generation** talks to a local [ComfyUI](https://github.com/comfyanonymous/ComfyUI) over
HTTP; it never starts or stops the server, and it renders through `PreviewImage` so a bulk run
leaves nothing behind in a ComfyUI install shared with other projects.

```sh
cd ~/Projects/.shared/comfyui && ./.venv/bin/python main.py --listen 127.0.0.1 --port 8189
make images
```

Defaults to **RealVisXL V5.0** at 1344×768 / 20 steps, measured at ~56s per image on an M-series
Mac. Flux.1-schnell is wired up as `--model flux`, measured on the same machine and dishes at
**107–154s** — roughly 3× slower for a trade rather than a win: it follows an ingredient list more
literally (it drew the egg that really is in Magnolia Boil) but composes busier, tighter shots,
while RealVisXL returns cleaner plated photographs. For a library that has to be redrawn as menus
rotate, 3× the wall time did not buy 3× the usefulness. Food-specific LoRAs were considered and
rejected: the SDXL ones on Civitai are either a dark/neon studio style or unrelated, and the good
Flux ones target Flux.1-dev rather than schnell.

Seeds are derived from the dish id, so regenerating a dish reproduces its picture. An image whose
aspect ratio no longer matches the card is redrawn automatically, so changing the card shape
refreshes the library rather than leaving the browser to centre-crop older pictures.

**Priority.** Not every dish is worth a picture. Standing stations render as a dense list with no
image slot, and placeholder entries are deliberately not illustrated, so both are skipped
entirely. The rest are drawn meat first, then other main courses, then sides:

```sh
make images                                  # everything, in priority order
uv run python scripts/gen_images.py --max-priority 0   # meat only
uv run python scripts/gen_images.py --max-priority 1   # meat and other mains
```

A dish counts as a main if R&DE lists it in the first two menu positions, which beats guessing
from the name — that is what keeps "Plant-Forward Loco Moco & Gravy" out of the sides bucket.

Dishes whose "ingredients" are a placeholder (`chef's choice soup of the day`) are deliberately
**not** illustrated. Inventing a specific bowl of soup for an entry that changes daily would be
worse than showing nothing, so those get a category icon instead.

## Deploying

Live at **[stanford-dining.neilmin.com](https://stanford-dining.neilmin.com)**.

`site/` is pure build output and is not committed; `data/` is. GitHub Actions re-scrapes and
redeploys daily, so menus stay current with your laptop closed. Images are the exception —
they need a local GPU, so you generate them locally and commit them, and the site shows a
labelled placeholder for any dish whose picture has not landed yet.

Which means the nightly job has to be able to ask for something it cannot do itself. It keeps
one standing issue, *Dishes waiting for a picture*: the body is the current backlog, rewritten
every night, and it comments — mentioning you, so the mail arrives whatever the repo is watched
at — only on a night that turned up dishes nobody has drawn. Editing the body sends nothing,
deliberately: twenty new dishes a night is the normal state of a rotating menu, and a nightly
ping would be read exactly as often as a warning in a green log. The same list, locally:

```sh
make images-todo
```

Two workflows: `refresh.yml` runs on the cron, scrapes, commits `data/`, and then *calls*
`pages.yml`; `pages.yml` builds and deploys, on any push or when called. The call is not
decoration — a push made with `GITHUB_TOKEN` deliberately does not fire `on: push`, so a
refresh that relied on its own commit would scrape every night and publish none of it.

Set the repository variable `ENABLE_PAGES` to `false` to stop publishing; unset means publish.
The daily scrape runs either way.

## Caveats

- **Images are generated, not photographed.** They show what a dish typically looks like. They
  are not pictures of the food being served.
- **Allergen text is reproduced from R&DE** and is subject to change without notice. If you have
  an allergy, confirm at the hall.
- **The Chinese is machine-translated**, dish by dish and term by term, and nobody has read all
  of it. The English is kept on screen next to every dish name partly for that reason. Fixing a
  bad one is a hand edit in `data/zh.json`; `make translate` never overwrites what is already
  there.
- The source app only exposes a rolling 7-day window, so history exists only for days already
  scraped. The specials poster is worse: the hours page links one fortnight at a time, so an
  edition nobody fetched while it was up is gone. `data/specials/` is the archive.
- **The hall logos are Stanford's**, cut from R&DE's own map and shown to identify the hall they
  belong to. They are not licensed for any other use; see Stanford's
  [trademark policy](https://adminguide.stanford.edu/chapters/guiding-policies-and-principles/conflict-interest/ownership-and-use-stanford-trademarks).
- EVGR appears in the app's dropdown but returns no menu and is absent from the hours page; it is
  marked inactive.

## Licence

MIT. Menu content belongs to Stanford R&DE.
