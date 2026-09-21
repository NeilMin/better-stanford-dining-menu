"""Tell standing stations apart from the day's rotating menu.

R&DE's menu app returns one flat list per service, mixing the dishes cooked that
day with the counters that are there every day -- Burger Bar, Panini Station,
Soup of the Day. Nothing in the markup distinguishes them, so it is derived from
how often a name recurs at that hall: over a week, stations appear on 7 days out
of 7 and the day's menu appears on exactly 1. The split is almost perfectly
bimodal, with very little in between.

Station sets are per hall, not global: only four of eight halls run a Burger Bar,
and Branner runs its own allergen-free counters under their own names.
"""

from __future__ import annotations

import collections
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable

from bsdm import dishes as dishlib
from bsdm.menus import TZ

# A name recurring on at least this share of a hall's services is standing.
THRESHOLD = 0.6
# Below this many observed services the ratio is meaningless -- on day one
# everything would look permanent -- so name shape is used instead.
MIN_SERVICES = 4

# Cold-start fallback: counters usually say so in their name, and their
# "ingredients" are a placeholder rather than a recipe.
_NAME_RE = re.compile(
    r"\b(bar|station|counter)\b|^(soup|composed salad|assorted |grilled )", re.I
)


def analyze(menu_paths: Iterable[Path]) -> dict:
    """Build the per-(hall, meal) station table over the menus handed in.

    The caller picks the window -- menus.recent() nightly -- because a standing
    counter is a claim about what a hall is doing lately, not about everything
    it ever did.
    """
    appearances: collections.Counter = collections.Counter()
    services: collections.Counter = collections.Counter()
    samples: dict[tuple[str, str, str], dict] = {}

    files = sorted(menu_paths)
    for path in files:
        day = json.loads(path.read_text())
        for hall, meals in day["halls"].items():
            for meal, served in meals.items():
                services[(hall, meal)] += 1
                for dish in served:
                    key = (hall, meal, dish["name"])
                    appearances[key] += 1
                    samples.setdefault(key, dish)

    halls: dict[str, dict] = {}
    for (hall, meal, name), count in sorted(appearances.items()):
        observed = services[(hall, meal)]
        ratio = count / observed
        if observed >= MIN_SERVICES:
            standing = ratio >= THRESHOLD
        else:
            dish = samples[(hall, meal, name)]
            standing = bool(_NAME_RE.search(name)) or dishlib.is_placeholder(dish)

        entry = halls.setdefault(hall, {}).setdefault(
            meal, {"services_observed": observed, "stations": {}}
        )
        if standing:
            entry["stations"][name] = round(ratio, 3)

    return {
        "computed_at": datetime.now(TZ).isoformat(timespec="seconds"),
        "days_analyzed": len(files),
        "threshold": THRESHOLD,
        "min_services": MIN_SERVICES,
        "halls": halls,
    }


def station_names(table: dict, hall: str, meal: str) -> set[str]:
    return set(table.get("halls", {}).get(hall, {}).get(meal, {}).get("stations", {}))


_GRILL_SUB_RE = re.compile(
    r"^(grilled\b|black bean burger|impossible burger|turkey burger|panko crusted.*grill|halal all-beef hot dog)",
    re.I,
)
_TACO_SUB_RE = re.compile(
    r"^(saut[eé]ed chorizo|tasty tofu scramble|tater tots)",
    re.I,
)


def _sub_pattern_for(name: str) -> re.Pattern | None:
    if re.search(r"\b(burger bar|hot dog bar|chili bar|grill)\b", name, re.I):
        return _GRILL_SUB_RE
    if re.search(r"\b(taco bar)\b", name, re.I):
        return _TACO_SUB_RE
    return None


def group_service_stations(served: list[dict]) -> list[dict]:
    """Group station containers (e.g. Burger Bar) with their immediate sub-items.

    Returns a new list where station containers are represented as:
      {"is_group": True, "station": dish, "items": [sub_dish, ...]}
    and their sub-items are removed from the top-level list.
    """
    out: list[dict] = []
    i = 0
    while i < len(served):
        d = served[i]
        name = d.get("name", "")
        if dishlib.is_station_container(d):
            pat = _sub_pattern_for(name)
            items = []
            j = i + 1
            if pat:
                while j < len(served) and pat.search(served[j].get("name", "")):
                    items.append(served[j])
                    j += 1
            out.append({"is_group": True, "station": d, "items": items})
            i = j
        else:
            out.append(d)
            i += 1
    return out


def split(table: dict, hall: str, meal: str, served: list[dict]) -> tuple[list, list]:
    """Partition one service's items into (daily menu, standing stations)."""
    stations = station_names(table, hall, meal)
    daily = []
    standing = []
    for d in served:
        name = d["station"]["name"] if d.get("is_group") else d["name"]
        if name in stations:
            standing.append(d)
        else:
            daily.append(d)
    return daily, standing
