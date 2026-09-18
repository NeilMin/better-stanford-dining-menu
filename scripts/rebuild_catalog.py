#!/usr/bin/env python3
"""Re-derive data/dishes.json from the stored menus, without re-scraping."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bsdm import menus as menuslib  # noqa: E402
from bsdm import specials as specialslib  # noqa: E402
from bsdm.catalog import build, summarize  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    # The nightly run replays the recent window and carries everything older
    # through the previous catalog. This is how you replay the archive itself,
    # which is what you want after changing a classification rule.
    ap.add_argument("--replay-archive", action="store_true",
                    help="re-derive from every menu ever stored, not just the recent window")
    args = ap.parse_args()

    path = ROOT / "data" / "dishes.json"
    previous = json.loads(path.read_text()) if path.exists() else {}
    stations_path = ROOT / "data" / "stations.json"
    table = json.loads(stations_path.read_text()) if stations_path.exists() else {}

    window = menuslib.history(ROOT) if args.replay_archive else menuslib.recent(ROOT)
    catalog = build(window, table, previous, specialslib.dishes(ROOT))
    path.write_text(json.dumps(catalog, indent=1, ensure_ascii=False, sort_keys=True) + "\n")

    moved = sum(1 for k, v in catalog.items()
                if k in previous and previous[k].get("category") != v["category"])
    print(summarize(catalog))
    if moved:
        print(f"{moved} reclassified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
