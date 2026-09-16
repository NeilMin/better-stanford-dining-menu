#!/usr/bin/env python3
"""Render the dish images that data/dishes.json is still missing.

Needs a local ComfyUI, so this is the one step that cannot run in CI. Images are
keyed on the dish name, so this is resumable and idempotent: a dish is drawn once
and then reused across every hall and every week it appears in.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from bsdm import dishes as dishlib  # noqa: E402
from bsdm.catalog import is_stale  # noqa: E402
from bsdm.comfy import DEFAULT_URL, MODELS, ComfyClient, ComfyError, to_webp  # noqa: E402

IMAGES = ROOT / "data" / "images"
CATALOG = ROOT / "data" / "dishes.json"


def seed_for(dish_id: str) -> int:
    """A stable seed per dish, so a regenerated image looks like the old one."""
    return int(dish_id[:8], 16)


CARD_RATIO = 16 / 9


def is_current(path: Path) -> bool:
    """Whether an existing image still matches the shape the cards display.

    Changing the card's aspect ratio should redraw the library rather than let
    the browser centre-crop away half of every older picture.
    """
    try:
        with Image.open(path) as im:
            return abs(im.width / im.height - CARD_RATIO) < 0.02
    except OSError:
        return False


def record_image(dish_id: str, fields: dict) -> None:
    """Merge one dish's image fields into the catalog on disk.

    A full backfill runs for hours, so the catalog is re-read and rewritten per
    dish rather than held in memory: rebuild_catalog.py may well reclassify
    dishes while this is still running, and a wholesale write would silently
    revert that work.
    """
    catalog = json.loads(CATALOG.read_text())
    catalog.setdefault(dish_id, {}).update(fields)
    CATALOG.write_text(json.dumps(catalog, indent=1, ensure_ascii=False, sort_keys=True) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default=DEFAULT_URL, help="ComfyUI base URL")
    ap.add_argument("--model", default="sdxl", choices=sorted(MODELS))
    ap.add_argument("--limit", type=int, help="stop after N images")
    ap.add_argument("--only", help="substring match on the dish name")
    ap.add_argument("--force", action="store_true", help="redraw dishes that already have images")
    ap.add_argument("--redraw-stale", action="store_true",
                    help="also redraw images drawn before the current prompt rules")
    ap.add_argument("--max-priority", type=int, default=2, choices=(0, 1, 2),
                    help="0 meat only, 1 adds other mains, 2 adds sides (default)")
    ap.add_argument("--steps", type=int, help="override step count")
    ap.add_argument("--free-every", type=int, default=20, metavar="N",
                    help="release ComfyUI's cached models every N images (0 disables)")
    args = ap.parse_args()

    catalog = json.loads(CATALOG.read_text())
    client = ComfyClient(args.url)

    if not client.available():
        print(
            f"No ComfyUI at {args.url}.\n"
            f"Start the shared install with:\n"
            f"  cd ~/Projects/.shared/comfyui && "
            f"./.venv/bin/python main.py --listen 127.0.0.1 --port 8189",
            file=sys.stderr,
        )
        return 2
    client.validate(args.model)

    IMAGES.mkdir(parents=True, exist_ok=True)
    # Meat first, then other mains, then sides; within a tier, whatever R&DE
    # lists earliest on the menu.
    def rank(kv):
        e = kv[1]
        return (e.get("priority", 2), e.get("min_order", 999), e["name"])

    pending = []
    for did, entry in sorted(catalog.items(), key=rank):
        if not entry.get("needs_image") or not entry.get("prompt"):
            continue
        if entry.get("priority", 2) > args.max_priority:
            continue
        if args.only and args.only.lower() not in entry["name"].lower():
            continue
        path = IMAGES / f"{did}.webp"
        if (path.exists() and entry.get("image") and not args.force
                and is_current(path) and not (args.redraw_stale and is_stale(entry))):
            continue
        pending.append((did, entry))

    if args.limit:
        pending = pending[: args.limit]
    if not pending:
        print("Nothing to draw -- every illustratable dish already has an image.")
        return 0

    print(f"Drawing {len(pending)} dishes with {args.model} via {args.url}")
    started = time.monotonic()
    done = failed = 0

    for i, (did, entry) in enumerate(pending, 1):
        seed = seed_for(did)
        try:
            image, secs = client.generate(
                args.model, entry["prompt"],
                entry.get("negative") or dishlib.negative_prompt(entry),
                seed, steps=args.steps,
            )
        except (ComfyError, OSError) as exc:
            failed += 1
            print(f"  [{i}/{len(pending)}] FAILED {entry['name']}: {exc}", file=sys.stderr)
            continue

        (IMAGES / f"{did}.webp").write_bytes(to_webp(image))
        done += 1
        # Persisted per image: a multi-hour backfill must survive a Ctrl-C.
        record_image(did, {
            "image": f"{did}.webp",
            "model": args.model,
            "seed": seed,
            "prompt_rev": dishlib.PROMPT_REV,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })

        if args.free_every and i % args.free_every == 0 and i < len(pending):
            client.free()

        elapsed = time.monotonic() - started
        eta = (elapsed / i) * (len(pending) - i)
        print(f"  [{i}/{len(pending)}] P{entry.get('priority', 2)} {secs:5.1f}s  "
              f"{entry['name'][:42]:42.42s} eta {eta / 60:.0f}m", flush=True)

    print(f"\nDrew {done}, failed {failed}, in {(time.monotonic() - started) / 60:.1f} min")
    return 1 if failed and not done else 0


if __name__ == "__main__":
    raise SystemExit(main())
