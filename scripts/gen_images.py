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

from bsdm.comfy import DEFAULT_URL, MODELS, ComfyClient, ComfyError, to_webp  # noqa: E402
from bsdm.dishes import NEGATIVE_PROMPT  # noqa: E402

IMAGES = ROOT / "data" / "images"
CATALOG = ROOT / "data" / "dishes.json"


def seed_for(dish_id: str) -> int:
    """A stable seed per dish, so a regenerated image looks like the old one."""
    return int(dish_id[:8], 16)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default=DEFAULT_URL, help="ComfyUI base URL")
    ap.add_argument("--model", default="sdxl", choices=sorted(MODELS))
    ap.add_argument("--limit", type=int, help="stop after N images")
    ap.add_argument("--only", help="substring match on the dish name")
    ap.add_argument("--force", action="store_true", help="redraw dishes that already have images")
    ap.add_argument("--size", type=int, help="override generation resolution")
    ap.add_argument("--steps", type=int, help="override step count")
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
    pending = []
    for did, entry in sorted(catalog.items(), key=lambda kv: kv[1]["name"]):
        if entry["placeholder"] or not entry.get("prompt"):
            continue
        if args.only and args.only.lower() not in entry["name"].lower():
            continue
        on_disk = (IMAGES / f"{did}.webp").exists()
        if on_disk and entry.get("image") and not args.force:
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
                args.model, entry["prompt"], NEGATIVE_PROMPT, seed,
                size=args.size, steps=args.steps,
            )
        except (ComfyError, OSError) as exc:
            failed += 1
            print(f"  [{i}/{len(pending)}] FAILED {entry['name']}: {exc}", file=sys.stderr)
            continue

        (IMAGES / f"{did}.webp").write_bytes(to_webp(image))
        entry.update({
            "image": f"{did}.webp",
            "model": args.model,
            "seed": seed,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        done += 1
        # Persist after every image: a 2-hour backfill must survive a Ctrl-C.
        CATALOG.write_text(json.dumps(catalog, indent=1, ensure_ascii=False, sort_keys=True) + "\n")

        elapsed = time.monotonic() - started
        eta = (elapsed / i) * (len(pending) - i)
        print(f"  [{i}/{len(pending)}] {secs:5.1f}s  {entry['name'][:44]:44.44s} "
              f"eta {eta / 60:.0f}m", flush=True)

    print(f"\nDrew {done}, failed {failed}, in {(time.monotonic() - started) / 60:.1f} min")
    return 1 if failed and not done else 0


if __name__ == "__main__":
    raise SystemExit(main())
