#!/usr/bin/env python3
"""Render data/ into the deployable site/ directory."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bsdm.build import build  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(ROOT / "site"))
    args = ap.parse_args()

    stats = build(ROOT, Path(args.out))
    print(
        f"Built {args.out}: {stats['days']} days, {stats['halls']} halls, "
        f"{stats['rows']} rows over {stats['dishes']} dishes, "
        f"{stats['images']} images, {stats['logos']} logos, "
        f"{stats['zh_dishes']} Chinese names and "
        f"{stats['zh_terms']} Chinese terms, index.html {stats['html_kb']:.0f} KB"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
