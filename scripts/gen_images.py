#!/usr/bin/env python3
"""Render the dish images that data/dishes.json is still missing.

Supports Cloudflare Workers AI, local ComfyUI, and DuckDuckGo web search
fallback. Images are keyed on the dish name, so this is resumable and
idempotent: a dish is drawn once and then reused across every hall and every
week it appears in.
"""

from __future__ import annotations

import argparse
import io
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
from bsdm.cloudflare import CloudflareClient, CloudflareError, CloudflareQuotaError  # noqa: E402
from bsdm.comfy import DEFAULT_URL, MODELS, ComfyClient, ComfyError, to_webp  # noqa: E402
from bsdm.pending import rank  # noqa: E402
from bsdm import web_image  # noqa: E402

IMAGES = ROOT / "data" / "images"
CATALOG = ROOT / "data" / "dishes.json"


def seed_for(dish_id: str, entry: dict | None = None) -> int:
    """A stable seed per dish, so a regenerated image looks like the old one.

    The catalog's own seed wins where it carries one, which is what makes a
    hand-picked seed stick. Deriving it from the id every time is what drew the
    picture being replaced, so a --force redraw would faithfully reproduce the
    bad one, and --redraw-stale would quietly undo the fix a prompt bump later.
    """
    stored = (entry or {}).get("seed")
    if stored is not None:
        return int(stored)
    try:
        return int(dish_id[:8], 16)
    except ValueError:
        import hashlib
        return int(hashlib.sha256(dish_id.encode()).hexdigest()[:8], 16)


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


def generate_with_cloudflare(
    client: CloudflareClient, prompt: str, negative: str
) -> tuple[Image.Image, float]:
    """Generate an image via Cloudflare Workers AI."""
    started = time.monotonic()
    raw_bytes = client.generate_image(prompt, negative_prompt=negative)
    img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
    secs = time.monotonic() - started
    return img, secs


def generate_with_search_fallback(dish_name: str) -> tuple[Image.Image | None, float]:
    """Search DuckDuckGo Images as a fallback when AI generation fails."""
    started = time.monotonic()
    data = web_image.search_food_image(dish_name)
    secs = time.monotonic() - started
    if not data:
        return None, secs
    try:
        img = Image.open(io.BytesIO(data)).convert("RGB")
        w, h = img.size
        if abs(w / h - CARD_RATIO) > 0.01:
            if w / h > CARD_RATIO:  # too wide: trim the sides
                new_w = round(h * CARD_RATIO)
                left = (w - new_w) // 2
                img = img.crop((left, 0, left + new_w, h))
            else:  # too tall: trim top and bottom
                new_h = round(w / CARD_RATIO)
                top = (h - new_h) // 2
                img = img.crop((0, top, w, top + new_h))
        if img.size != (1024, 576):
            img = img.resize((1024, 576), Image.LANCZOS)
        return img, secs
    except Exception:
        return None, secs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--backend", choices=["auto", "cloudflare", "comfyui"], default="auto",
                    help="generation backend: auto, cloudflare, or comfyui (default: auto)")
    ap.add_argument("--search-fallback", action=argparse.BooleanOptionalAction, default=True,
                    help="fall back to web image search if generation fails (default: True)")
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
    ap.add_argument("--seed", type=int,
                    help="draw with this seed rather than the dish's own, and record it. "
                         "The only way to replace a picture the stable seed would otherwise "
                         "redraw identically -- use it with --only and --force")
    ap.add_argument("--free-every", type=int, default=20, metavar="N",
                    help="release ComfyUI's cached models every N images (0 disables)")
    args = ap.parse_args(argv)

    cf_client = CloudflareClient()
    comfy_client = ComfyClient(args.url)

    if args.backend == "cloudflare" and not cf_client.is_configured():
        print(
            "Error: Cloudflare backend requested but CF_ACCOUNT_ID and CF_API_TOKEN are not set.",
            file=sys.stderr,
        )
        return 1

    catalog = json.loads(CATALOG.read_text())
    IMAGES.mkdir(parents=True, exist_ok=True)
    # Meat first, then other mains, then sides; within a tier, whatever R&DE
    # lists earliest on the menu. Shared with bsdm/pending.py, which reports the
    # backlog to GitHub: a queue and a to-do list of the same queue that disagree
    # about the order would be read as one of them being wrong.
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

    if args.limit is not None:
        pending = pending[: args.limit]
    if not pending:
        print("Nothing to draw -- every illustratable dish already has an image.")
        return 0

    if args.backend == "cloudflare":
        backend = "cloudflare"
    elif args.backend == "comfyui":
        if not comfy_client.available():
            print(
                f"No ComfyUI at {args.url}.\n"
                f"Start the shared install with:\n"
                f"  cd ~/Projects/.shared/comfyui && "
                f"./.venv/bin/python main.py --listen 127.0.0.1 --port 8189",
                file=sys.stderr,
            )
            return 2
        comfy_client.validate(args.model)
        backend = "comfyui"
    else:  # auto
        if cf_client.is_configured():
            backend = "cloudflare"
        elif comfy_client.available():
            comfy_client.validate(args.model)
            backend = "comfyui"
        else:
            print(
                f"No image generation backend available.\n"
                f"Set CF_ACCOUNT_ID/CF_API_TOKEN for Cloudflare, or start ComfyUI at {args.url}.",
                file=sys.stderr,
            )
            return 2

    if backend == "cloudflare":
        print(f"Drawing {len(pending)} dishes via Cloudflare Workers AI")
    else:
        print(f"Drawing {len(pending)} dishes with {args.model} via {args.url}")

    started = time.monotonic()
    done = failed = 0
    quota_exceeded = False

    for i, (did, entry) in enumerate(pending, 1):
        seed = args.seed if args.seed is not None else seed_for(did, entry)
        prompt = entry["prompt"]
        negative = entry.get("negative") or dishlib.negative_prompt(entry)
        dish_name = entry["name"]
        image = None
        secs = 0.0
        used_model = None

        if backend == "cloudflare":
            try:
                image, secs = generate_with_cloudflare(cf_client, prompt, negative)
                used_model = "cf-sdxl-lightning"
            except CloudflareQuotaError as exc:
                print(f"  [{i}/{len(pending)}] Cloudflare quota exceeded: {exc}", file=sys.stderr)
                quota_exceeded = True
            except (CloudflareError, OSError, Exception) as exc:
                print(f"  [{i}/{len(pending)}] Cloudflare generation failed for {dish_name}: {exc}", file=sys.stderr)
        elif backend == "comfyui":
            try:
                image, secs = comfy_client.generate(
                    args.model, prompt, negative, seed, steps=args.steps,
                )
                used_model = args.model
            except (ComfyError, OSError, Exception) as exc:
                print(f"  [{i}/{len(pending)}] ComfyUI generation failed for {dish_name}: {exc}", file=sys.stderr)

        if image is None and args.search_fallback:
            print(f"  [{i}/{len(pending)}] Attempting search fallback for {dish_name}...", flush=True)
            fallback_img, fallback_secs = generate_with_search_fallback(dish_name)
            if fallback_img is not None:
                image = fallback_img
                secs = fallback_secs
                used_model = "web-search"

        if image is None:
            failed += 1
            print(f"  [{i}/{len(pending)}] FAILED {dish_name}", file=sys.stderr)
        else:
            (IMAGES / f"{did}.webp").write_bytes(to_webp(image))
            done += 1
            # Persisted per image: a multi-hour backfill must survive a Ctrl-C.
            record_image(did, {
                "image": f"{did}.webp",
                "model": used_model,
                "seed": seed,
                "prompt_rev": dishlib.PROMPT_REV,
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })

            if backend == "comfyui" and args.free_every and i % args.free_every == 0 and i < len(pending):
                comfy_client.free()

            elapsed = time.monotonic() - started
            eta = (elapsed / i) * (len(pending) - i)
            print(f"  [{i}/{len(pending)}] P{entry.get('priority', 2)} {secs:5.1f}s  "
                  f"{dish_name[:42]:42.42s} [{used_model}] eta {eta / 60:.0f}m", flush=True)

        if quota_exceeded:
            break

    print(f"\nDrew {done}, failed {failed}, in {(time.monotonic() - started) / 60:.1f} min")
    if quota_exceeded:
        print("Stopped early due to Cloudflare quota limit; completed images saved.", file=sys.stderr)
        return 0
    return 1 if failed and not done else 0


if __name__ == "__main__":
    raise SystemExit(main())
