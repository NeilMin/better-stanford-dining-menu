#!/usr/bin/env python3
"""Re-fetch live menus and diff them against what is stored in data/menus/.

The scraper drives an ASP.NET postback whose dropdowns are carried in rotating
hidden fields, so a sequencing fault would silently return the previous hall's
menu rather than erroring. Identical menus across halls are the symptom, so this
checks stored data against a fresh, independently-primed fetch.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bsdm.scrape import MenuScraper  # noqa: E402


def stored(day: str, hall: str, meal: str) -> list[str]:
    path = ROOT / "data" / "menus" / f"{day}.json"
    if not path.exists():
        return []
    payload = json.loads(path.read_text())
    return [d["name"] for d in payload["halls"].get(hall, {}).get(meal, [])]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--day", required=True, help="ISO date, e.g. 2026-09-16")
    ap.add_argument("--meal", default="Dinner")
    ap.add_argument("--halls", required=True,
                    help="comma-separated hall ids as used in config/halls.json")
    ap.add_argument("--fresh-session", action="store_true",
                    help="prime a brand-new session before each hall")
    args = ap.parse_args()

    config = json.loads((ROOT / "config" / "halls.json").read_text())
    by_id = {h["id"]: h for h in config["halls"]}
    day = date.fromisoformat(args.day)

    scraper = MenuScraper(delay=0.4)
    scraper.prime()

    live: dict[str, list[str]] = {}
    failures = 0

    for hall_id in [s.strip() for s in args.halls.split(",")]:
        hall = by_id[hall_id]
        if args.fresh_session:
            scraper = MenuScraper(delay=0.4)
            scraper.prime()
        svc = scraper.fetch(hall["menu_key"], day, args.meal)
        live[hall_id] = [d.name for d in svc.dishes]

        was = stored(args.day, hall_id, args.meal)
        match = was == live[hall_id]
        print(f"{hall_id:15s} live {len(live[hall_id]):2d} | stored {len(was):2d} | "
              f"{'MATCH' if match else 'DIFFERS'}")
        if not match:
            failures += 1
            only_live = [n for n in live[hall_id] if n not in was]
            only_stored = [n for n in was if n not in live[hall_id]]
            if only_live:
                print(f"    only live   : {', '.join(only_live[:6])}")
            if only_stored:
                print(f"    only stored : {', '.join(only_stored[:6])}")

    print("\n--- cross-hall comparison of the LIVE fetch ---")
    ids = list(live)
    dupes = 0
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if live[a] and live[a] == live[b]:
                print(f"  !! {a} and {b} returned byte-identical menus")
                dupes += 1
    if not dupes:
        print("  all halls returned distinct menus")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
