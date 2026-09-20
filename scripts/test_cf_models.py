#!/usr/bin/env python3
"""Compare Cloudflare Workers AI image models locally side-by-side.

Usage:
    # Set credentials via environment or in a local .env file:
    CF_ACCOUNT_ID="xxx" CF_API_TOKEN="xxx" uv run python scripts/test_cf_models.py --dish "Bibimbap Bowl"

    # Or specify models to test:
    uv run python scripts/test_cf_models.py --dish "Pork Bulgogi" --models flux sdxl-base
"""

from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bsdm import dishes as dishlib  # noqa: E402
from bsdm.cloudflare import CloudflareClient, CloudflareError  # noqa: E402
from bsdm.comfy import to_webp  # noqa: E402

# Try loading .env if exists
env_file = ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))

MODEL_ALIASES = {
    "flux": "@cf/black-forest-labs/flux-1-schnell",
    "sdxl-base": "@cf/stabilityai/stable-diffusion-xl-base-1.0",
    "sdxl-lightning": "@cf/bytedance/stable-diffusion-xl-lightning",
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dish", default="Bibimbap Bowl", help="dish name to test (default: Bibimbap Bowl)")
    ap.add_argument("--models", nargs="+", default=["flux", "sdxl-base"],
                    choices=list(MODEL_ALIASES.keys()) + list(MODEL_ALIASES.values()),
                    help="models to evaluate")
    ap.add_argument("--no-open", action="store_true", help="do not auto-open Preview on macOS")
    args = ap.parse_args()

    client = CloudflareClient()
    if not client.is_configured():
        print(
            "Error: Cloudflare credentials not found.\n"
            "Please provide CF_ACCOUNT_ID and CF_API_TOKEN via environment variables or a local .env file.",
            file=sys.stderr,
        )
        return 1

    catalog = json.loads((ROOT / "data" / "dishes.json").read_text())
    entry = next((d for d in catalog.values() if d["name"].lower() == args.dish.lower()), None)
    if not entry:
        print(f"Dish '{args.dish}' not found in catalog; generating prompt dynamically...")
        prompt = f"professional food photography of {args.dish}, appetizing, studio lighting, 4k"
        negative = "cartoon, anime, 3d render, plastic, blurry, watermark"
    else:
        prompt = entry["prompt"]
        negative = entry.get("negative") or dishlib.negative_prompt(entry)

    out_dir = ROOT / "test_output"
    out_dir.mkdir(exist_ok=True)

    print(f"\nEvaluating models for dish: {args.dish}")
    print(f"Prompt: {prompt[:90]}...\n")

    produced_files: list[Path] = []
    for model_key in args.models:
        model_id = MODEL_ALIASES.get(model_key, model_key)
        short_name = model_key.split("/")[-1]
        print(f"Testing {short_name} ({model_id})...", end=" ", flush=True)

        started = time.monotonic()
        try:
            raw_bytes = client.generate_image(prompt=prompt, negative_prompt=negative, model=model_id)
            img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
            webp_bytes = to_webp(img)
            elapsed = time.monotonic() - started

            out_path = out_dir / f"{short_name}_{args.dish.replace(' ', '_').lower()}.webp"
            out_path.write_bytes(webp_bytes)
            produced_files.append(out_path)
            print(f"DONE in {elapsed:.1f}s -> {out_path.name}")
        except CloudflareError as exc:
            print(f"FAILED: {exc}")
        except Exception as exc:
            print(f"ERROR: {exc}")

    if produced_files and not args.no_open and sys.platform == "darwin":
        subprocess.run(["open", "-a", "Preview"] + [str(p) for p in produced_files])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
