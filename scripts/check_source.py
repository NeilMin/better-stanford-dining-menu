#!/usr/bin/env python3
"""Fail if R&DE is offering something config/halls.json cannot account for.

Run at the end of the nightly job, after the menus have been committed and the
site published, because the finding is not a reason to lose a night's data --
it is a reason for somebody to open config/halls.json. Exiting non-zero is the
point: a red run sends mail, and a warning in a green log does not.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bsdm import source as sourcelib  # noqa: E402


def main() -> int:
    snapshot = sourcelib.load(ROOT)
    if not snapshot:
        # Nothing has looked yet. In CI this runs after the scrape, so this is a
        # local checkout, not a finding.
        print(f"No {sourcelib.path(ROOT).name} yet -- run scripts/update.py first.")
        return 0

    config = json.loads((ROOT / "config" / "halls.json").read_text())
    found = sourcelib.drift(ROOT, config)
    if not found:
        print(f"Source unchanged: {len(snapshot['halls'])} halls offered, "
              f"all accounted for in config/halls.json.")
        return 0

    print(f"!! R&DE has moved and {len(found)} thing(s) need a person:\n")
    for item in found:
        print(f"- {item}\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
