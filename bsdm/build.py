"""Assemble the static site from the scraped data.

Output is a self-contained index.html, one more per hall in <hallId>/, plus the
img/ and logo/ directories they share, so it works equally well opened from
disk and served from GitHub Pages.
"""

from __future__ import annotations

import html as html_lib
import json
import shutil
from datetime import date, datetime
from pathlib import Path

from bsdm import logos as logolib
from bsdm import menus as menuslib
from bsdm import specials as specialslib
from bsdm import zh as zhlib
from bsdm.menus import TZ

# The domain the site is served from. Written into the artifact as CNAME on
# every build; see the note where it is written.
DOMAIN = "stanford-dining.neilmin.com"


def schedule_for(hall: dict, day: date) -> dict:
    """The meal -> [open, close] table this hall runs on `day`."""
    iso = day.isoformat()
    weekday = day.weekday()
    for sched in hall.get("schedules", []):
        if sched["from"] > iso:
            continue
        if sched.get("to") and sched["to"] < iso:
            continue
        if weekday in sched.get("days", []):
            return sched.get("meals", {})
    return {}


def build_payload(root: Path) -> dict:
    config = json.loads((root / "config" / "halls.json").read_text())
    catalog = json.loads((root / "data" / "dishes.json").read_text())
    images_dir = root / "data" / "images"

    logo_index = logolib.index(root)
    logo_dir = logolib.out_dir(root)

    zh_table = zhlib.load(root)
    # Only the terms the published menus actually use are shipped. The table
    # keeps every term ever seen, which over a term's worth of menus is a good
    # deal more than any one week puts on the board.
    zh_terms: dict[str, str] = {}
    zh_specials: dict[str, str] = {}

    stations_path = root / "data" / "stations.json"
    station_table = json.loads(stations_path.read_text()) if stations_path.exists() else {}

    # Only the live window is read. The filter still stands after it, because
    # live/ is swept by the scrape and a build run the next morning on an
    # unscraped checkout would otherwise publish yesterday as today.
    days = [json.loads(p.read_text()) for p in menuslib.live(root)]
    today = menuslib.today().isoformat()
    days = [d for d in days if d["date"] >= today]

    # A day the halls serve nothing is a day with no dishes in it, and it
    # publishes: over a break the board should say the halls are shut. Having
    # no day at all is a different thing -- the scrape did not run, or did not
    # finish -- and the answer to that is to fix the scrape, not to reach back
    # for the last week that worked and publish it as though it were this one.
    # This used to fall back to the newest seven days on file, which turned a
    # broken scraper into a site quietly serving last week's dinner.
    if not days:
        raise SystemExit(
            f"No menus for {today} or later in {menuslib.live_dir(root)}.\n"
            "Nothing was scraped, so there is nothing to publish: run "
            "`make update`. Refusing to build rather than replace a good site "
            "with an empty one."
        )
    window = [d["date"] for d in days]

    halls_by_id = {h["id"]: h for h in config["halls"]}

    # A dish's ingredients, tags and allergens differ between halls for a handful
    # of dishes -- Branner serves allergen-free versions of the same recipes -- so
    # each distinct combination is stored as a variant and menu entries reference
    # "<dishId>.<variantIndex>".
    dishes: dict[str, dict] = {}
    variant_index: dict[str, dict[tuple, int]] = {}

    def variant_ref(dish_id: str, d: dict) -> str:
        key = (d["ingredients"], tuple(d["tags"]),
               tuple(d["allergens"]), tuple(d["trace_allergens"]))
        table = variant_index.setdefault(dish_id, {})
        if key not in table:
            table[key] = len(table)
            entry = catalog.get(dish_id, {})
            record = dishes.setdefault(dish_id, {
                "name": d["name"],
                "category": entry.get("category", "other"),
                "icon": entry.get("icon", "plate"),
                "placeholder": entry.get("placeholder", False),
                "image": entry.get("image") if entry.get("image")
                         and (images_dir / entry["image"]).exists() else None,
                "v": [],
            })
            # An untranslated dish keeps its English name in Chinese mode --
            # translation runs locally and lands a commit later, exactly as
            # images do.
            if name_zh := zhlib.get(zh_table, "dishes", dish_id):
                record["zh"] = name_zh
            record["v"].append({
                "ing": d["ingredients"],
                "tags": d["tags"],
                "alg": d["allergens"],
                "trace": d["trace_allergens"],
            })
            for term in zhlib.terms_in(d["ingredients"]):
                if term_zh := zhlib.get(zh_table, "terms", term):
                    zh_terms[term] = term_zh
        return f"{dish_id}.{table[key]}"

    from bsdm.dishes import dish_id as make_id
    from bsdm.stations import split as split_service, group_service_stations

    # Specials come off a PDF poster, on their own dates. They are dishes like
    # any other -- drawn, counted, filtered -- that lead their hall's list. Only
    # a day the menus show that hall serving the calendar's meal gets one: the
    # poster's bars run Monday to Friday whether or not a hall reopened on the
    # Tuesday.
    poster = specialslib.for_window(root, window)

    menus: dict[str, dict] = {}
    hours: dict[str, dict] = {}
    notices: dict[str, dict] = {}

    for day in days:
        iso = day["date"]
        as_date = date.fromisoformat(iso)
        on_poster = poster.get(iso, {"meal": None, "halls": {}, "notes": []})
        # Each service is split into the dishes cooked that day and the counters
        # that are there every day, so the board can lead with what changed.
        menus[iso] = {}
        for hall_id, meals in day["halls"].items():
            per_meal = {}
            for meal, served in meals.items():
                grouped = group_service_stations(served)
                daily, standing = split_service(station_table, hall_id, meal, grouped)
                specials = []
                if meal == on_poster["meal"] and daily:
                    listed = {make_id(d["name"]): d for d in served}
                    for text in on_poster["halls"].get(hall_id, []):
                        sid = make_id(text)
                        # A special the menu lists as well keeps the menu's
                        # ingredients and allergens; the poster has neither.
                        specials.append(variant_ref(sid, listed.get(sid) or {
                            "name": text, "ingredients": "", "tags": [],
                            "allergens": [], "trace_allergens": [],
                        }))
                        # The poster's wording is what zh.json translates;
                        # a menu dish of the same name keeps its own.
                        record = dishes[sid]
                        if "zh" not in record and (
                                text_zh := zhlib.get(zh_table, "specials", text)):
                            record["zh"] = text_zh
                # Shown once, as the special, even where the menu lists it too.
                led = {make_id(text) for text in on_poster["halls"].get(hall_id, [])} \
                    if specials else set()

                def to_ref(item: dict) -> str | dict:
                    if item.get("is_group"):
                        s_dish = item["station"]
                        sid = make_id(s_dish["name"])
                        s_ref = variant_ref(sid, s_dish)
                        item_refs = [variant_ref(make_id(c["name"]), c) for c in item.get("items", [])]
                        return {
                            "station": s_ref,
                            "items": item_refs,
                        }
                    return variant_ref(make_id(item["name"]), item)

                def item_id(item: dict) -> str:
                    name = item["station"]["name"] if item.get("is_group") else item["name"]
                    return make_id(name)

                per_meal[meal] = {
                    "specials": specials,
                    "daily": [to_ref(d) for d in daily if item_id(d) not in led],
                    "stations": [to_ref(d) for d in standing if item_id(d) not in led],
                }
            menus[iso][hall_id] = per_meal
        hours[iso] = {
            h["id"]: schedule_for(h, as_date)
            for h in config["halls"] if h["active"] and schedule_for(h, as_date)
        }
        # What the calendar says to the whole campus at once stays a notice.
        if on_poster["notes"]:
            notices[iso] = {"meal": on_poster["meal"], "notes": on_poster["notes"]}
            for text in on_poster["notes"]:
                if text_zh := zhlib.get(zh_table, "specials", text):
                    zh_specials[text] = text_zh

    def hall_public(h: dict) -> dict:
        out = {
            "id": h["id"], "short": h["short"], "name": h["name"],
            "concept": h["concept"], "address": h["address"], "accent": h["accent"],
        }
        if concept_zh := zhlib.get(zh_table, "halls", h["id"]):
            out["concept_zh"] = concept_zh
        # A hall with no logo cut yet falls back to its name alone, the same way
        # a dish with no picture falls back to an icon.
        entry = logo_index.get(h["id"])
        if entry and (logo_dir / entry["file"]).exists():
            out["logo"] = entry
        return out

    now = datetime.now(TZ)
    return {
        "generated_at": now.strftime("%b %-d, %Y at %-I:%M %p %Z"),
        "generated_at_zh": now.strftime("%Y年%-m月%-d日 %H:%M"),
        "stations_computed_from": station_table.get("days_analyzed", 0),
        "window": window,
        "halls": [
            hall_public(h)
            for h in config["halls"]
            if h["active"] and any(h["id"] in menus[d] for d in window)
        ],
        "defaults": config["defaults"],
        "dishes": dishes,
        "zh_terms": zh_terms,
        "zh_specials": zh_specials,
        "menus": menus,
        "hours": hours,
        "notices": notices,
    }


# ---------- one page per hall ----------
#
# The board is one page, and a search for "arrillaga menu" has nothing on it to
# land on: the menu is drawn by app.js, and the official app is a form with no
# URL per hall. So every active hall also gets /<id>/, the same app opened on
# that hall alone, with its own title and canonical, the week's menu written
# into the HTML for a crawler that runs no script, and the hall described in
# JSON-LD. The page tells app.js which hall it is and how far down it sits
# (`page` in the data block), because the pictures are relative paths.

MEAL_ORDER = ("Breakfast", "Brunch", "Lunch", "Dinner")


def _json_script(value) -> str:
    # Split the closing tag so a stray "</script>" inside the data can't end the block early.
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def _clock(hhmm: str) -> str:
    """11:00 -> 11am, as app.js's fmtTime writes it in English."""
    h, m = (int(x) for x in hhmm.split(":"))
    suffix = "am" if h < 12 or h == 24 else "pm"
    hour = h % 12 or 12
    return f"{hour}:{m:02d}{suffix}" if m else f"{hour}{suffix}"


def _dish_name(payload: dict, ref: str) -> str:
    return payload["dishes"][ref.rsplit(".", 1)[0]]["name"]


def _served(payload: dict, iso: str, hall_id: str) -> list[tuple[str, dict]]:
    meals = payload["menus"].get(iso, {}).get(hall_id, {})
    return [(m, meals[m]) for m in MEAL_ORDER if m in meals] + \
        [(m, svc) for m, svc in meals.items() if m not in MEAL_ORDER]


def _names(payload: dict, refs: list) -> list[str]:
    """Dish names in board order. A station group is its station's name."""
    return [_dish_name(payload, r["station"] if isinstance(r, dict) else r) for r in refs]


def prerender(payload: dict, hall: dict) -> str:
    """The hall's week as plain HTML, for whoever reads the page without
    running app.js. render() removes it on the first draw, so a reader with
    scripts sees the board and never this."""
    esc = html_lib.escape
    hid = hall["id"]
    parts = [f'<section class="prerender" id="prerender">',
             f"<h2>{esc(hall['name'])} menu</h2>"]
    about = ". ".join(x for x in (hall.get("concept"), hall.get("address")) if x)
    if about:
        parts.append(f"<p>{esc(about)}.</p>")
    for iso in payload["window"]:
        day = date.fromisoformat(iso)
        parts.append(f"<h3>{day.strftime('%A, %B')} {day.day}</h3>")
        served = _served(payload, iso, hid)
        if not served:
            parts.append("<p>Closed.</p>")
            continue
        for meal, svc in served:
            span = payload["hours"].get(iso, {}).get(hid, {}).get(meal)
            when = f" · {_clock(span[0])}–{_clock(span[1])}" if span else ""
            parts.append(f"<h4>{esc(meal)}{when}</h4>")
            items = [f"<li>Special: {esc(n)}</li>" for n in _names(payload, svc["specials"])]
            items += [f"<li>{esc(n)}</li>" for n in _names(payload, svc["daily"])]
            if items:
                parts.append("<ul>" + "".join(items) + "</ul>")
            if svc["stations"]:
                parts.append("<p>Every day: " +
                             esc(", ".join(_names(payload, svc["stations"]))) + ".</p>")
    parts.append("</section>")
    return "\n".join(parts)


def _address(text: str) -> dict:
    """'489 Arguello Mall, Stanford, CA 94305' as a schema.org PostalAddress.
    config/halls.json writes every address that way; one that is not is kept
    whole rather than guessed at."""
    out = {"@type": "PostalAddress", "addressCountry": "US"}
    parts = [p.strip() for p in text.split(",")]
    if len(parts) == 3 and len(region := parts[2].split()) == 2:
        out.update(streetAddress=parts[0], addressLocality=parts[1],
                   addressRegion=region[0], postalCode=region[1])
    else:
        out["streetAddress"] = text
    return out


def structured_data(payload: dict, hall: dict) -> dict:
    """The hall as schema.org FoodEstablishment: where it is, when it is open
    on each day of the window, and what it serves at each meal."""
    hid = hall["id"]
    data = {
        "@context": "https://schema.org",
        "@type": "FoodEstablishment",
        "name": hall["name"],
        "url": f"https://{DOMAIN}/{hid}/",
    }
    if hall.get("address"):
        data["address"] = _address(hall["address"])
    if hall.get("logo"):
        data["image"] = f"https://{DOMAIN}/logo/{hall['logo']['file']}"
    opening, sections = [], []
    for iso in payload["window"]:
        day = date.fromisoformat(iso)
        for meal, span in payload["hours"].get(iso, {}).get(hid, {}).items():
            opening.append({
                "@type": "OpeningHoursSpecification",
                "dayOfWeek": f"https://schema.org/{day.strftime('%A')}",
                # schema.org times stop at 23:59; the stored table can say 24:00.
                "opens": span[0], "closes": "23:59" if span[1] == "24:00" else span[1],
                "validFrom": iso, "validThrough": iso,
            })
        for meal, svc in _served(payload, iso, hid):
            names = _names(payload, svc["specials"]) + _names(payload, svc["daily"])
            if names:
                sections.append({
                    "@type": "MenuSection",
                    "name": f"{day.strftime('%A, %B')} {day.day} · {meal}",
                    "hasMenuItem": [{"@type": "MenuItem", "name": n} for n in names],
                })
    if opening:
        data["openingHoursSpecification"] = opening
    if sections:
        data["hasMenu"] = {"@type": "Menu", "name": f"{hall['name']} menu",
                           "hasMenuSection": sections}
    return data


def _swap(html: str, old: str, new: str) -> str:
    """Replace one exact string in the template, and refuse if it has moved:
    a hall page that quietly kept the home page's canonical would be filed as
    a duplicate of it, which is the one thing these pages must not be."""
    if html.count(old) != 1:
        raise SystemExit(f"web/index.html: expected exactly one {old!r}")
    return html.replace(old, new)


HOME_TITLE = "Stanford Dining, Side by Side"
HOME_DESCRIPTION = "Compare today's menus across Stanford dining halls, with a picture of every dish."


def page_html(template: str, payload: dict, halls: list[dict], hall: dict | None) -> str:
    """One page of the site: the home board when `hall` is None, else that
    hall's page one directory down."""
    esc = html_lib.escape
    root = "../" if hall else ""
    links = " · ".join(f'<a href="{root}{h["id"]}/">{esc(h["name"])}</a>' for h in halls)
    html = template.replace("<!--HALLS-->", links)
    home = f"https://{DOMAIN}/"
    if hall is None:
        ld = {"@context": "https://schema.org", "@type": "WebSite",
              "name": HOME_TITLE, "url": home}
        html = html.replace("<!--PRERENDER-->", "")
    else:
        url = f"{home}{hall['id']}/"
        title = f"{hall['name']} Menu Today · {HOME_TITLE}"
        where = f" at {hall['address']}" if hall.get("address") else ""
        description = (f"What {hall['name']}{where} is serving today and this week: "
                       "every meal, with hours, allergens and a picture of every dish.")
        for old, new in [
            (f"<title>{HOME_TITLE}</title>", f"<title>{esc(title)}</title>"),
            (f'<meta name="description" content="{HOME_DESCRIPTION}">',
             f'<meta name="description" content="{esc(description)}">'),
            (f'<meta property="og:title" content="{HOME_TITLE}">',
             f'<meta property="og:title" content="{esc(title)}">'),
            (f'<meta property="og:description" content="{HOME_DESCRIPTION}">',
             f'<meta property="og:description" content="{esc(description)}">'),
            (f'<meta property="og:url" content="{home}">', f'<meta property="og:url" content="{url}">'),
            (f'<link rel="canonical" href="{home}">', f'<link rel="canonical" href="{url}">'),
        ]:
            html = _swap(html, old, new)
        ld = structured_data(payload, hall)
        html = html.replace("<!--PRERENDER-->", prerender(payload, hall))
    html = _swap(html, "</head>",
                 f'<script type="application/ld+json">{_json_script(ld)}</script>\n</head>')
    page = {"hall": hall["id"] if hall else None, "root": root}
    return html.replace("/*DATA*/", _json_script({**payload, "page": page}))


def build(root: Path, out: Path) -> dict:
    payload = build_payload(root)
    web = root / "web"
    config = json.loads((root / "config" / "halls.json").read_text())

    template = (web / "index.html").read_text()
    template = template.replace("/*CSS*/", (web / "app.css").read_text())
    template = template.replace("/*JS*/", (web / "app.js").read_text())

    # Every active hall gets its page, serving this week or not: over a break the
    # data carries no halls at all, and a page that vanished for three weeks
    # would be dropped from the index and have to be found again. A hall the
    # week does not serve reads "Closed" down its page instead.
    public = {h["id"]: h for h in payload["halls"]}
    halls = [public.get(h["id"], h) for h in config["halls"] if h["active"]]

    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(page_html(template, payload, halls, None))
    for hall in halls:
        (out / hall["id"]).mkdir(exist_ok=True)
        (out / hall["id"] / "index.html").write_text(page_html(template, payload, halls, hall))
    # A hall that has left config/halls.json takes its page with it.
    for stale in out.iterdir():
        if stale.is_dir() and (stale / "index.html").exists() \
                and stale.name not in {h["id"] for h in halls}:
            shutil.rmtree(stale)
    (out / ".nojekyll").write_text("")
    # Pages reads the custom domain out of the published artifact, so shipping
    # CNAME here sets it on every deploy. Keeping it in the build rather than in
    # the repo root also means the domain cannot drift from what is served.
    (out / "CNAME").write_text(DOMAIN + "\n")
    # robots.txt is read per host, so neilmin.com's does not speak for this one.
    # The sitemap is what points a crawler here at all; lastmod is the build's
    # own day, because the menu on the page is new every night.
    (out / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\n\nSitemap: https://{DOMAIN}/sitemap.xml\n")
    lastmod = menuslib.today().isoformat()
    (out / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join(f"  <url><loc>https://{DOMAIN}/{path}</loc><lastmod>{lastmod}</lastmod></url>\n"
                  for path in ["", *(f"{h['id']}/" for h in halls)])
        + "</urlset>\n")
    # The link-preview card, named by absolute URL in index.html's og:image.
    # Composed once by hand from the logos and a few dishes, not per build.
    shutil.copy2(web / "og.jpg", out / "og.jpg")

    logo_out = out / "logo"
    logo_out.mkdir(exist_ok=True)
    wanted_logos = {h["logo"]["file"] for h in payload["halls"] if h.get("logo")}
    for name in wanted_logos:
        src = logolib.out_dir(root) / name
        dst = logo_out / name
        if not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime:
            shutil.copy2(src, dst)
    for stale in logo_out.glob("*.webp"):
        if stale.name not in wanted_logos:
            stale.unlink()

    img_out = out / "img"
    img_out.mkdir(exist_ok=True)
    used = {d["image"] for d in payload["dishes"].values() if d["image"]}
    for name in used:
        src = root / "data" / "images" / name
        dst = img_out / name
        if not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime:
            shutil.copy2(src, dst)
    for stale in img_out.glob("*.webp"):
        if stale.name not in used:
            stale.unlink()

    total = sum(len(svc["specials"]) + len(svc["daily"]) + len(svc["stations"])
                for day in payload["menus"].values()
                for meals in day.values() for svc in meals.values())
    return {
        "days": len(payload["window"]),
        "halls": len(payload["halls"]),
        "dishes": len(payload["dishes"]),
        "rows": total,
        "images": len(used),
        "logos": len(wanted_logos),
        "specials": sum(len(svc["specials"]) for day in payload["menus"].values()
                        for meals in day.values() for svc in meals.values()),
        "zh_dishes": sum(1 for d in payload["dishes"].values() if d.get("zh")),
        "zh_terms": len(payload["zh_terms"]),
        "html_kb": (out / "index.html").stat().st_size / 1024,
        "hall_pages": len(halls),
    }
