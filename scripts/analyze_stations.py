#!/usr/bin/env python3
"""Recompute data/stations.json from the accumulated menu history."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bsdm.stations import analyze  # noqa: E402


def main() -> int:
    table = analyze(ROOT / "data" / "menus")
    out = ROOT / "data" / "stations.json"
    out.write_text(json.dumps(table, indent=1, ensure_ascii=False, sort_keys=True) + "\n")

    total = sum(len(m["stations"]) for h in table["halls"].values() for m in h.values())
    print(f"{table['days_analyzed']} days analyzed; {total} standing stations across "
          f"{len(table['halls'])} halls")
    for hall in sorted(table["halls"]):
        parts = [f"{meal} {len(v['stations'])}" for meal, v in sorted(table["halls"][hall].items())]
        print(f"  {hall:15s} {', '.join(parts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
