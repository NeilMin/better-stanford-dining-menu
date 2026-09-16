#!/usr/bin/env python3
"""Re-derive data/dishes.json from the stored menus, without re-scraping.

Classification and prompt wording get tuned often; this replays every dish we
have already seen through the current rules and preserves the image each dish
has already been given.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bsdm import dishes as dishlib  # noqa: E402


def main() -> int:
    catalog_path = ROOT / "data" / "dishes.json"
    previous = json.loads(catalog_path.read_text()) if catalog_path.exists() else {}
    catalog: dict[str, dict] = {}

    for path in sorted((ROOT / "data" / "menus").glob("*.json")):
        day = json.loads(path.read_text())
        for meals in day["halls"].values():
            for served in meals.values():
                for d in served:
                    did = dishlib.dish_id(d["name"])
                    entry = catalog.setdefault(
                        did, {"first_seen": day["date"], "image": None}
                    )
                    entry.update({
                        "name": d["name"],
                        "ingredients": d["ingredients"],
                        "tags": d["tags"],
                        "category": dishlib.classify(d),
                        "placeholder": dishlib.is_placeholder(d),
                        "icon": dishlib.station_icon(d),
                        "last_seen": day["date"],
                    })
                    if old := previous.get(did):
                        entry["first_seen"] = min(entry["first_seen"], old.get("first_seen", day["date"]))
                        entry["image"] = old.get("image")
                        for key in ("generated_at", "model", "seed"):
                            if key in old:
                                entry[key] = old[key]
                    entry["prompt"] = None if entry["placeholder"] else dishlib.image_prompt(d)

    catalog_path.write_text(json.dumps(catalog, indent=1, ensure_ascii=False, sort_keys=True) + "\n")

    moved = sum(
        1 for k, v in catalog.items()
        if k in previous and previous[k].get("category") != v["category"]
    )
    print(f"{len(catalog)} dishes, {sum(1 for v in catalog.values() if v['placeholder'])} placeholders, "
          f"{moved} reclassified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
