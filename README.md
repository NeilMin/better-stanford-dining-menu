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
- **Real hours.** Each column shows that hall's hours for the selected meal and whether it is
  open right now.
- **Allergens as served.** A few dishes differ by hall — Branner runs allergen-free versions of
  the same recipes — so each column shows the allergens for *that* hall's version.

## Quick start

```sh
uv sync
make update      # scrape the rolling 7-day window into data/menus/
make images      # draw the dishes still missing pictures (needs local ComfyUI)
make serve       # preview at http://127.0.0.1:8777
```

`make update` and `make site` need only network access. `make images` is the one step that
needs a GPU, which is why it is separate.

## How it fits together

```
R&DE menu app  ──scripts/update.py──►  data/menus/YYYY-MM-DD.json   (one file per day)
                                       data/dishes.json             (dish catalog + image index)
                                              │
local ComfyUI  ──scripts/gen_images.py────────┤  data/images/<dishId>.webp
                                              │
                 scripts/build_site.py  ──────►  site/index.html + site/img/
```

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
- The source app only exposes a rolling 7-day window, so history exists only for days already
  scraped.
- EVGR appears in the app's dropdown but returns no menu and is absent from the hours page; it is
  marked inactive.

## Licence

MIT. Menu content belongs to Stanford R&DE.
