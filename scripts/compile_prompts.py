#!/usr/bin/env python3
"""Batch compile food photography prompts for dishes using Cloudflare Llama 3.3 70B."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bsdm.cloudflare import CloudflareClient  # noqa: E402
from bsdm.prompt_compiler import compile_pending  # noqa: E402

CATALOG_PATH = ROOT / "data" / "dishes.json"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", help="substring match on dish name")
    ap.add_argument("--limit", type=int, help="max dishes to compile")
    ap.add_argument("--force", action="store_true", help="recompile already compiled dishes")
    args = ap.parse_args()

    client = CloudflareClient()
    if not client.is_configured():
        print("Error: CF_ACCOUNT_ID and CF_API_TOKEN environment variables are required.", file=sys.stderr)
        return 1

    catalog = json.loads(CATALOG_PATH.read_text())
    count = compile_pending(catalog, client, limit=args.limit, force=args.force, only=args.only)
    if count > 0:
        CATALOG_PATH.write_text(json.dumps(catalog, indent=1, ensure_ascii=False, sort_keys=True) + "\n")
        print(f"Successfully compiled prompts for {count} dishes.")
    else:
        print("No dishes needed prompt compilation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
