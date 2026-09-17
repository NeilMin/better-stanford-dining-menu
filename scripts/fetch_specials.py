#!/usr/bin/env python3
"""Follow the specials calendar link on the R&DE hours page into data/.

Runs as part of `make update`; this is the way to run it on its own, and the way
to check a poster by hand when R&DE reshapes one.

    make specials                                          # fetch and fold in
    uv run python scripts/fetch_specials.py --show         # what is on file
    uv run python scripts/fetch_specials.py --dry-run FILE # parse a PDF, print it
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bsdm import specials as specialslib  # noqa: E402


def load_config() -> dict:
    return json.loads((ROOT / "config" / "halls.json").read_text())


def show_entries(record: dict, table: dict[str, str]) -> None:
    for entry in record.get("entries", []):
        where = ",".join(entry.get("halls") or []) or (
            f"[{entry['label']}?]" if entry.get("label") else "(all halls)")
        span = entry["from"] if entry["from"] == entry["to"] else f"{entry['from']}..{entry['to']}"
        print(f"  {span}  {where:22s} {entry['text']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", metavar="PDF",
                    help="parse a local PDF and print it, touching nothing")
    ap.add_argument("--show", action="store_true", help="print what data/specials.json holds")
    ap.add_argument("--force", action="store_true", help="re-parse even if the PDF is unchanged")
    args = ap.parse_args()

    config = load_config()
    table = specialslib.alias_table(config)

    if args.dry_run:
        parsed = specialslib.parse(Path(args.dry_run).read_bytes())
        specialslib.attach_halls(parsed["entries"], table)
        print(f"{parsed['title']}  ({parsed['meal']}, {parsed['from']}..{parsed['to']})")
        show_entries(parsed, table)
        return 0

    if args.show:
        store = specialslib.load(ROOT)
        for record in store.get("calendars", []):
            head = record.get("title") or record["file"]
            print(f"\n{head}   {record.get('from', '?')}..{record.get('to', '?')}"
                  f"   {record['file']}")
            if record.get("error"):
                print(f"  !! unreadable: {record['error']}")
            show_entries(record, table)
        return 0

    result = specialslib.update(ROOT, config, force=args.force)
    if not result["url"]:
        print("No specials calendar linked from the hours page.")
        return 0
    print(f"{result['status']}: {result['url']}")
    if result["status"] == "unreadable":
        print(f"  archived as {result['file']}, but could not be read: {result['error']}",
              file=sys.stderr)
        return 1
    if result["status"] != "unchanged":
        print(f"  {result['title']}  ({result['from']}..{result['to']})")
        print(f"  {result['entries']} entries, {result['placed']} tied to a hall"
              f"  ->  data/specials/{result['file']}")
        if result["unplaced_labels"]:
            print(f"  !! labels that match no hall: {', '.join(result['unplaced_labels'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
