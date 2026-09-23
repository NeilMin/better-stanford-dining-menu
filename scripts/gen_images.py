#!/usr/bin/env python3
"""Render the dish images that data/dishes.json is still missing.

Multi-tier hybrid image pipeline:
  Tier 1: Web food photography search (Wikipedia / Pexels) gated by Cloudflare
          Llama 3.2 Vision judge for authenticity and cooked state.
  Tier 2: Cloudflare Workers AI FLUX.1-schnell with protein-hardened prompting.
  Local Master Mode: ComfyUI RealVisXL on port 8189 (overwrites anytime locally).

Images are keyed on the dish name, so this is resumable and idempotent:
a dish is drawn once and then reused across every hall and every week it appears in.
"""

from __future__ import annotations

import argparse
import io
import json
import random
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
CARD_RATIO = 16 / 9


def seed_for(dish_id: str, entry: dict | None = None) -> int:
    """A stable seed per dish, so a regenerated image looks like the old one."""
    stored = (entry or {}).get("seed")
    if stored is not None:
        return int(stored)
    try:
        return int(dish_id[:8], 16)
    except ValueError:
        import hashlib
        return int(hashlib.sha256(dish_id.encode()).hexdigest()[:8], 16)


def is_current(path: Path) -> bool:
    """Whether an existing image still matches the shape the cards display."""
    try:
        with Image.open(path) as im:
            return abs(im.width / im.height - CARD_RATIO) < 0.02
    except OSError:
        return False


def record_image(dish_id: str, fields: dict) -> None:
    """Merge one dish's image fields into the catalog on disk."""
    catalog = json.loads(CATALOG.read_text())
    catalog.setdefault(dish_id, {}).update(fields)
    CATALOG.write_text(json.dumps(catalog, indent=1, ensure_ascii=False, sort_keys=True) + "\n")


def crop_and_resize_to_card(img: Image.Image) -> Image.Image:
    """Crop and resize an image to 16:9 1024x576 for the card grid."""
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
    return img


def generate_with_cloudflare(
    client: CloudflareClient, prompt: str, negative: str
) -> tuple[Image.Image, float]:
    """Generate an image via Cloudflare Workers AI."""
    started = time.monotonic()
    raw_bytes = client.generate_image(prompt, negative_prompt=negative)
    raw_img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
    card_img = crop_and_resize_to_card(raw_img)
    secs = time.monotonic() - started
    return card_img, secs


def generate_with_search(
    dish_name: str, client: CloudflareClient | None = None, min_score: int = 7
) -> tuple[Image.Image | None, float]:
    """Search web food photography and crop to card if approved by VLM quality gate."""
    started = time.monotonic()
    data = web_image.search_food_image(dish_name, client=client, min_score=min_score)
    secs = time.monotonic() - started
    if not data:
        return None, secs
    try:
        raw_img = Image.open(io.BytesIO(data)).convert("RGB")
        return crop_and_resize_to_card(raw_img), secs
    except Exception:
        return None, secs


def generate_with_search_fallback(dish_name: str) -> tuple[Image.Image | None, float]:
    """Search DuckDuckGo / web as an un-gated fallback when generation fails."""
    return generate_with_search(dish_name, client=None, min_score=0)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--backend", choices=["auto", "cloudflare", "comfyui", "search"], default="auto",
                    help="generation backend: auto, cloudflare, comfyui, or search (default: auto)")
    ap.add_argument("--search-first", action=argparse.BooleanOptionalAction, default=True,
                    help="try web food search + VLM judge before AI generation (default: True)")
    ap.add_argument("--search-fallback", action=argparse.BooleanOptionalAction, default=True,
                    help="fall back to web image search if generation fails (default: True)")
    ap.add_argument("--only-search", action="store_true",
                    help="only search web food photography (skip AI generation)")
    ap.add_argument("--only-ai", action="store_true",
                    help="only use AI generation (skip web search)")
    ap.add_argument("--vlm-gate", action=argparse.BooleanOptionalAction, default=True,
                    help="evaluate generated image with VLM when Cloudflare is configured (default: True)")
    ap.add_argument("--max-vlm-retries", type=int, default=3,
                    help="maximum generation attempts with new seeds if VLM score < 7 (default: 3)")
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
    elif args.backend == "search":
        backend = "search"
    else:  # auto
        if comfy_client.available():
            comfy_client.validate(args.model)
            backend = "comfyui"
        elif cf_client.is_configured():
            backend = "cloudflare"
        else:
            backend = "search"

    if backend == "cloudflare":
        print(f"Processing {len(pending)} dishes via Cloudflare Workers AI + Web Search (Hybrid Tier)")
    elif backend == "comfyui":
        print(f"Drawing {len(pending)} dishes with {args.model} via {args.url}")
    else:
        print(f"Searching web images for {len(pending)} dishes")

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
        vlm_score = None
        vlm_reason = None

        # Tier 1: Web Food Search with VLM Quality Gate
        if not args.only_ai and (backend in ("cloudflare", "search")) and args.search_first:
            try:
                vlm_client = cf_client if cf_client.is_configured() else None
                search_img, search_secs = generate_with_search(dish_name, client=vlm_client, min_score=7)
                if search_img is not None:
                    image = search_img
                    secs = search_secs
                    used_model = "web-search"
            except Exception as exc:
                print(f"  [{i}/{len(pending)}] Web food search error for {dish_name}: {exc}", file=sys.stderr)

        # Tier 2: AI Generation
        if image is None and not args.only_search:
            max_attempts = max(1, args.max_vlm_retries) if (args.vlm_gate and cf_client.is_configured()) else 1
            best_candidate = None  # (image, seed, score, reason, secs, model)
            total_secs = 0.0

            for attempt in range(1, max_attempts + 1):
                attempt_img = None
                attempt_secs = 0.0
                attempt_model = None

                if backend == "cloudflare":
                    try:
                        attempt_img, attempt_secs = generate_with_cloudflare(cf_client, prompt, negative)
                        attempt_model = "cf-flux"
                    except CloudflareQuotaError as exc:
                        print(f"  [{i}/{len(pending)}] Cloudflare quota exceeded: {exc}", file=sys.stderr)
                        quota_exceeded = True
                        break
                    except (CloudflareError, OSError, Exception) as exc:
                        print(f"  [{i}/{len(pending)}] Cloudflare generation failed for {dish_name}: {exc}", file=sys.stderr)
                elif backend == "comfyui":
                    try:
                        raw_img, attempt_secs = comfy_client.generate(
                            args.model, prompt, negative, seed, steps=args.steps,
                        )
                        attempt_img = crop_and_resize_to_card(raw_img)
                        attempt_model = args.model
                    except (ComfyError, OSError, Exception) as exc:
                        print(f"  [{i}/{len(pending)}] ComfyUI generation failed for {dish_name}: {exc}", file=sys.stderr)

                total_secs += attempt_secs

                if attempt_img is None:
                    continue

                if args.vlm_gate and cf_client.is_configured():
                    thumb_bytes = to_webp(attempt_img)
                    try:
                        eval_res = cf_client.evaluate_food_image(thumb_bytes, dish_name=dish_name)
                    except Exception as exc:
                        print(f"  [{i}/{len(pending)}] VLM evaluation error for {dish_name}: {exc}", file=sys.stderr)
                        eval_res = {"valid": False, "score": 0, "reason": f"Evaluation error: {exc}"}

                    if isinstance(eval_res, dict):
                        valid = bool(eval_res.get("valid", False))
                        raw_score = eval_res.get("score", 0)
                        try:
                            score = int(raw_score)
                        except (TypeError, ValueError):
                            score = 0
                        reason = str(eval_res.get("reason", ""))
                    else:
                        valid = True
                        score = 10
                        reason = ""

                    if best_candidate is None or score > best_candidate[2]:
                        best_candidate = (attempt_img, seed, score, reason, total_secs, attempt_model)

                    if valid and score >= 7:
                        print(f"    [VLM Pass] Score {score}/10: {reason}")
                        image = attempt_img
                        secs = total_secs
                        used_model = attempt_model
                        vlm_score = score
                        vlm_reason = reason
                        break
                    else:
                        print(f"    [VLM Retry {attempt}/{max_attempts}] Score {score}/10: {reason}")
                        if attempt < max_attempts:
                            seed = random.randint(1, 2**31 - 1)
                            image = None
                else:
                    image = attempt_img
                    secs = total_secs
                    used_model = attempt_model
                    break

            if image is None and best_candidate is not None:
                image, seed, vlm_score, vlm_reason, secs, used_model = best_candidate

        # Tier 3: Emergency Fallback
        if image is None and args.search_fallback and not args.only_ai:
            print(f"  [{i}/{len(pending)}] Attempting fallback search for {dish_name}...", flush=True)
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
            record_fields = {
                "image": f"{did}.webp",
                "model": used_model,
                "seed": seed,
                "prompt_rev": dishlib.PROMPT_REV,
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            if vlm_score is not None:
                record_fields["vlm_score"] = vlm_score
            if vlm_reason is not None:
                record_fields["vlm_reason"] = vlm_reason
            record_image(did, record_fields)

            if backend == "comfyui" and args.free_every and i % args.free_every == 0 and i < len(pending):
                comfy_client.free()

            elapsed = time.monotonic() - started
            eta = (elapsed / i) * (len(pending) - i)
            print(f"  [{i}/{len(pending)}] P{entry.get('priority', 2)} {secs:5.1f}s  "
                  f"{dish_name[:42]:42.42s} [{used_model}] eta {eta / 60:.0f}m", flush=True)

        if quota_exceeded:
            break

    print(f"\nProcessed {done}, failed {failed}, in {(time.monotonic() - started) / 60:.1f} min")
    if quota_exceeded:
        print("Stopped early due to Cloudflare quota limit; completed images saved.", file=sys.stderr)
        return 0
    return 1 if failed and not done else 0


if __name__ == "__main__":
    raise SystemExit(main())
