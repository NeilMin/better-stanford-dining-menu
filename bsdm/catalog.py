"""Derive the dish catalog -- the image index -- from the stored menus.

Kept separate from scraping so that retuning classification or prompt wording
never requires re-fetching, and so scraping and rebuilding cannot drift apart.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from bsdm import dishes as dishlib
from bsdm import stations as stationlib

# Sides and accompaniments. Worth a picture eventually, but not before the
# things people actually choose a dining hall for.
_MINOR = (
    "rice", "bread", "roll", "sauce", "gravy", "salsa", "dressing", "vinaigrette",
    "soup", "broth", "beans", "legumes", "grains", "potatoes", "fries", "slaw",
    "vegetables", "vegetable board", "salad", "edamame", "pickles", "butter",
    "syrup", "oatmeal", "yogurt", "fruit", "dessert", "cookie", "cake", "muffin",
)


_MINOR_RE = re.compile(r"\b(" + "|".join(_MINOR) + r")\b", re.I)


def _is_minor(name: str) -> bool:
    # Word boundaries matter: "jackfruit" contains "fruit", and a pulled
    # jackfruit sandwich is an entree, not a fruit cup.
    return bool(_MINOR_RE.search(name))


def build(menu_dir: Path, station_table: dict, previous: dict | None = None) -> dict:
    """Replay every stored menu through the current rules.

    Image fields already earned are carried over, so retuning is free.
    """
    previous = previous or {}
    catalog: dict[str, dict] = {}
    # A dish only needs a picture where it is shown as a card; standing stations
    # render as a dense list with no image slot at all.
    as_station: dict[str, int] = {}
    as_daily: dict[str, int] = {}

    for path in sorted(menu_dir.glob("*.json")):
        day = json.loads(path.read_text())
        for hall, meals in day["halls"].items():
            for meal, served in meals.items():
                station_names = stationlib.station_names(station_table, hall, meal)
                for d in served:
                    did = dishlib.dish_id(d["name"])
                    entry = catalog.setdefault(did, {
                        "first_seen": day["date"], "image": None, "min_order": 999,
                    })
                    entry.update({
                        "name": d["name"],
                        "ingredients": d["ingredients"],
                        "tags": d["tags"],
                        "category": dishlib.classify(d),
                        "placeholder": dishlib.is_placeholder(d),
                        "icon": dishlib.station_icon(d),
                        "last_seen": day["date"],
                    })
                    entry["min_order"] = min(entry["min_order"], d.get("order", 999))
                    if d["name"] in station_names:
                        as_station[did] = as_station.get(did, 0) + 1
                    else:
                        as_daily[did] = as_daily.get(did, 0) + 1

    for did, entry in catalog.items():
        entry["station_only"] = as_daily.get(did, 0) == 0 and as_station.get(did, 0) > 0
        entry["needs_image"] = not entry["placeholder"] and not entry["station_only"]
        entry["prompt"] = dishlib.image_prompt(entry) if entry["needs_image"] else None
        entry["negative"] = dishlib.negative_prompt(entry) if entry["needs_image"] else None

        # 0 is what you pick a hall for, 2 is a side. Menu position is the
        # signal: R&DE lists the day's entrees first.
        if dishlib.is_meat(entry):
            entry["priority"] = 0
        elif entry["min_order"] <= 1:
            # R&DE lists the day's entrees first, which outranks any guess made
            # from the name: "Plant-Forward Loco Moco & Gravy" is a main course.
            entry["priority"] = 1
        elif _is_minor(entry["name"]) or entry["min_order"] >= 4:
            entry["priority"] = 2
        else:
            entry["priority"] = 1

        if old := previous.get(did):
            entry["first_seen"] = min(entry["first_seen"], old.get("first_seen", entry["first_seen"]))
            entry["image"] = old.get("image")
            for key in ("generated_at", "model", "seed", "prompt_rev"):
                if key in old:
                    entry[key] = old[key]

    return catalog


def is_stale(entry: dict) -> bool:
    """An image drawn before the current prompt rules existed."""
    return bool(entry.get("image")) and entry.get("prompt_rev", 1) < dishlib.PROMPT_REV


def summarize(catalog: dict) -> str:
    need = [e for e in catalog.values() if e["needs_image"]]
    missing = [e for e in need if not e.get("image")]
    stale = [e for e in need if is_stale(e)]
    by_priority = {p: sum(1 for e in missing if e["priority"] == p) for p in (0, 1, 2)}
    return (
        f"{len(catalog)} dishes | {len(need)} want images "
        f"({sum(1 for e in catalog.values() if e['station_only'])} stations and "
        f"{sum(1 for e in catalog.values() if e['placeholder'])} placeholders skipped) | "
        f"{len(missing)} missing: {by_priority[0]} meat, {by_priority[1]} other mains, "
        f"{by_priority[2]} sides | {len(stale)} drawn under older prompt rules"
    )
