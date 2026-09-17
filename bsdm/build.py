"""Assemble the static site from the scraped data.

Output is a single self-contained index.html plus an img/ directory, so it works
equally well opened from disk and served from GitHub Pages.
"""

from __future__ import annotations

import json
import shutil
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from bsdm import zh as zhlib

TZ = ZoneInfo("America/Los_Angeles")

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

    zh_table = zhlib.load(root)
    # Only the terms the published menus actually use are shipped. The table
    # keeps every term ever seen, which over a term's worth of menus is a good
    # deal more than any one week puts on the board.
    zh_terms: dict[str, str] = {}

    stations_path = root / "data" / "stations.json"
    station_table = json.loads(stations_path.read_text()) if stations_path.exists() else {}

    menu_files = sorted((root / "data" / "menus").glob("*.json"))
    days = [json.loads(p.read_text()) for p in menu_files]
    # Only publish the days the source site still covers.
    today = datetime.now(TZ).date().isoformat()
    days = [d for d in days if d["date"] >= today] or days[-7:]
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
    from bsdm.stations import split as split_service

    menus: dict[str, dict] = {}
    hours: dict[str, dict] = {}

    for day in days:
        iso = day["date"]
        as_date = date.fromisoformat(iso)
        # Each service is split into the dishes cooked that day and the counters
        # that are there every day, so the board can lead with what changed.
        menus[iso] = {}
        for hall_id, meals in day["halls"].items():
            per_meal = {}
            for meal, served in meals.items():
                daily, standing = split_service(station_table, hall_id, meal, served)
                per_meal[meal] = {
                    "daily": [variant_ref(make_id(d["name"]), d) for d in daily],
                    "stations": [variant_ref(make_id(d["name"]), d) for d in standing],
                }
            menus[iso][hall_id] = per_meal
        hours[iso] = {
            h["id"]: schedule_for(h, as_date)
            for h in config["halls"] if h["active"] and schedule_for(h, as_date)
        }

    def hall_public(h: dict) -> dict:
        out = {
            "id": h["id"], "short": h["short"], "name": h["name"],
            "concept": h["concept"], "address": h["address"], "accent": h["accent"],
        }
        if concept_zh := zhlib.get(zh_table, "halls", h["id"]):
            out["concept_zh"] = concept_zh
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
        "menus": menus,
        "hours": hours,
    }


def build(root: Path, out: Path) -> dict:
    payload = build_payload(root)
    web = root / "web"

    html = (web / "index.html").read_text()
    html = html.replace("/*CSS*/", (web / "app.css").read_text())
    html = html.replace("/*JS*/", (web / "app.js").read_text())
    # Split the closing tag so a stray "</script>" inside the data can't end the block early.
    html = html.replace(
        "/*DATA*/",
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"),
    )

    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(html)
    (out / ".nojekyll").write_text("")
    # Pages reads the custom domain out of the published artifact, so shipping
    # CNAME here sets it on every deploy. Keeping it in the build rather than in
    # the repo root also means the domain cannot drift from what is served.
    (out / "CNAME").write_text(DOMAIN + "\n")

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

    total = sum(len(svc["daily"]) + len(svc["stations"])
                for day in payload["menus"].values()
                for meals in day.values() for svc in meals.values())
    return {
        "days": len(payload["window"]),
        "halls": len(payload["halls"]),
        "dishes": len(payload["dishes"]),
        "rows": total,
        "images": len(used),
        "zh_dishes": sum(1 for d in payload["dishes"].values() if d.get("zh")),
        "zh_terms": len(payload["zh_terms"]),
        "html_kb": (out / "index.html").stat().st_size / 1024,
    }
