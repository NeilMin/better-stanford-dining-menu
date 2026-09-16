#!/usr/bin/env python3
"""Re-derive data/dishes.json from the stored menus, without re-scraping."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bsdm.catalog import build, summarize  # noqa: E402


def main() -> int:
    path = ROOT / "data" / "dishes.json"
    previous = json.loads(path.read_text()) if path.exists() else {}
    stations_path = ROOT / "data" / "stations.json"
    table = json.loads(stations_path.read_text()) if stations_path.exists() else {}

    catalog = build(ROOT / "data" / "menus", table, previous)
    path.write_text(json.dumps(catalog, indent=1, ensure_ascii=False, sort_keys=True) + "\n")

    moved = sum(1 for k, v in catalog.items()
                if k in previous and previous[k].get("category") != v["category"])
    print(summarize(catalog))
    if moved:
        print(f"{moved} reclassified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
