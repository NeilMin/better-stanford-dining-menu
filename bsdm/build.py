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

TZ = ZoneInfo("America/Los_Angeles")


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
            record["v"].append({
                "ing": d["ingredients"],
                "tags": d["tags"],
                "alg": d["allergens"],
                "trace": d["trace_allergens"],
            })
        return f"{dish_id}.{table[key]}"

    from bsdm.dishes import dish_id as make_id

    menus: dict[str, dict] = {}
    hours: dict[str, dict] = {}

    for day in days:
        iso = day["date"]
        as_date = date.fromisoformat(iso)
        menus[iso] = {
            hall_id: {
                meal: [variant_ref(make_id(d["name"]), d) for d in served]
                for meal, served in meals.items()
            }
            for hall_id, meals in day["halls"].items()
        }
        hours[iso] = {
            h["id"]: schedule_for(h, as_date)
            for h in config["halls"] if h["active"] and schedule_for(h, as_date)
        }

    return {
        "generated_at": datetime.now(TZ).strftime("%b %-d, %Y at %-I:%M %p %Z"),
        "window": window,
        "halls": [
            {
                "id": h["id"], "short": h["short"], "name": h["name"],
                "concept": h["concept"], "address": h["address"], "accent": h["accent"],
            }
            for h in config["halls"]
            if h["active"] and any(h["id"] in menus[d] for d in window)
        ],
        "defaults": config["defaults"],
        "dishes": dishes,
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

    total = sum(len(refs) for day in payload["menus"].values()
                for meals in day.values() for refs in meals.values())
    return {
        "days": len(payload["window"]),
        "halls": len(payload["halls"]),
        "dishes": len(payload["dishes"]),
        "rows": total,
        "images": len(used),
        "html_kb": (out / "index.html").stat().st_size / 1024,
    }
