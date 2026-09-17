#!/usr/bin/env python3
"""Cut the hall logos out of the R&DE dining halls map into data/logos/.

The crop boxes live in config/logos.json and are pixel coordinates into one
specific version of the map, so this refuses to run against a map it does not
recognise rather than quietly writing eight rectangles of street.

    make logos                                   # cut them
    uv run python scripts/fetch_logos.py --check # has the map changed?
    uv run python scripts/fetch_logos.py --contact-sheet /tmp/logos.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from bsdm import logos as logolib  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="report whether the live map still matches config/logos.json")
    ap.add_argument("--force", action="store_true",
                    help="cut anyway when the map has changed (boxes are probably wrong)")
    ap.add_argument("--contact-sheet", metavar="PATH",
                    help="also write every cut logo stacked into one image, to eyeball")
    ap.add_argument("--map", metavar="PATH",
                    help="cut from a local copy instead of fetching")
    args = ap.parse_args()

    config = logolib.load(ROOT)
    blob = Path(args.map).read_bytes() if args.map else logolib.fetch(config)
    state = logolib.check(config, blob)

    if args.check:
        print(f"source  {config['_source']}")
        print(f"stored  {config['sha256']}  {config['map_size'][0]}x{config['map_size'][1]}")
        print(f"live    {state['sha256']}  {state['size'][0]}x{state['size'][1]}")
        print("unchanged." if state["matches"] else
              "!! the map has been redrawn -- re-read the boxes in config/logos.json")
        return 0 if state["matches"] else 1

    if not state["matches"]:
        print("!! the map has been redrawn since config/logos.json was written.", file=sys.stderr)
        print(f"   stored {config['sha256'][:16]} / live {state['sha256'][:16]}", file=sys.stderr)
        print("   The boxes are pixel coordinates into the old map, so cutting now would\n"
              "   most likely write eight rectangles of street. Re-read the boxes (open\n"
              "   the map, find each callout) and update config/logos.json, or pass\n"
              "   --force if you have already checked that nothing moved.", file=sys.stderr)
        if not args.force:
            return 1

    cuts = logolib.cut(config, blob)
    index = logolib.write(ROOT, cuts)
    for hall_id in sorted(index):
        image = cuts[hall_id][0]
        box = config["boxes"][hall_id]
        print(f"  {hall_id:16s} {box[2] - box[0]:3d}x{box[3] - box[1]:3d} source"
              f"  ->  {image.width:3d}x{image.height:3d}"
              f"  ({index[hall_id]['w']}x{index[hall_id]['h']} on the page)")
    print(f"{len(index)} logos -> {logolib.out_dir(ROOT).relative_to(ROOT)}/")

    if args.contact_sheet:
        pad = 8
        width = max(image.width for image, _, _ in cuts.values()) + pad * 2
        height = sum(image.height + pad for image, _, _ in cuts.values()) + pad
        sheet = Image.new("RGB", (width, height), "white")
        y = pad
        for hall_id in sorted(cuts):
            image = cuts[hall_id][0]
            sheet.paste(image, ((width - image.width) // 2, y))
            y += image.height + pad
        sheet.save(args.contact_sheet)
        print(f"contact sheet -> {args.contact_sheet}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
