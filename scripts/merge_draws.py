#!/usr/bin/env python3
"""Fold the pictures several CI machines drew back into one catalog.

.github/workflows/draw.yml splits the night's queue across free runners
(gen_images.py --shard), each drawing on its own copy of data/. None of them may
push -- they would race each other and the twice-daily scrape -- so each hands
its data/ back as an artifact, and this applies what each one changed to the
catalog as it is *now*, which a scrape may have rewritten since they started.

What a machine changed is measured against the commit it started from: the
image fields of the dishes it drew (catalog.IMAGE_FIELDS, the picture itself,
and the fields record_image() drops), the briefs it wrote, and the picture files
of the dishes whose picture changed. Everything else in its copy is ignored, so
a catalog that was current six hours ago cannot undo tonight's scrape. A dish
the catalog no longer has is skipped rather than resurrected.

    uv run python scripts/merge_draws.py --base SHA shards/shard-1 shards/shard-2 ...
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bsdm.catalog import IMAGE_FIELDS  # noqa: E402

# The picture, what catalog.build() carries over, and what record_image() drops.
FIELDS = ("image", *IMAGE_FIELDS, "vlm_score", "vlm_reason")
_MISSING = object()


def _at(base: str, path: str, root: Path) -> dict:
    done = subprocess.run(["git", "show", f"{base}:{path}"], cwd=root, capture_output=True, check=False)
    return json.loads(done.stdout) if done.returncode == 0 else {}


def _write(path: Path, data: dict) -> None:
    # The same form record_image() and brief.record() write, so a merge is a small diff.
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True) + "\n")


def merge(root: Path, base: str, shards: list[Path]) -> dict:
    """Apply each shard's changes onto root's data/. Returns counts for the log."""
    base_dishes = _at(base, "data/dishes.json", root)
    base_briefs = _at(base, "data/briefs.json", root)
    dishes_path, briefs_path = root / "data" / "dishes.json", root / "data" / "briefs.json"
    dishes = json.loads(dishes_path.read_text())
    briefs = json.loads(briefs_path.read_text()) if briefs_path.exists() else {}
    counts = {"pictures": 0, "records": 0, "briefs": 0, "gone": 0}

    for shard in shards:
        drawn = json.loads((shard / "data" / "dishes.json").read_text())
        for did, entry in drawn.items():
            before = base_dishes.get(did, {})
            changed = [k for k in FIELDS if entry.get(k, _MISSING) != before.get(k, _MISSING)]
            if not changed:
                continue
            if did not in dishes:
                counts["gone"] += 1
                continue
            for key in changed:
                if key in entry:
                    dishes[did][key] = entry[key]
                else:
                    dishes[did].pop(key, None)
            counts["records"] += 1
            picture = shard / "data" / "images" / f"{did}.webp"
            if "generated_at" in changed and entry.get("image") and picture.exists():
                shutil.copyfile(picture, root / "data" / "images" / f"{did}.webp")
                counts["pictures"] += 1

        shard_briefs = shard / "data" / "briefs.json"
        for did, brief in (json.loads(shard_briefs.read_text()) if shard_briefs.exists() else {}).items():
            if brief != base_briefs.get(did):
                briefs[did] = brief
                counts["briefs"] += 1

    _write(dishes_path, dishes)
    _write(briefs_path, briefs)
    return counts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True, help="the commit the shards started from")
    ap.add_argument("shards", nargs="*", type=Path, help="each shard's artifact directory")
    args = ap.parse_args(argv)
    shards = [s for s in args.shards if (s / "data" / "dishes.json").exists()]
    if not shards:
        print("No shard came back with a catalog; nothing to merge.")
        return 0
    counts = merge(ROOT, args.base, shards)
    print(f"From {len(shards)} machines: {counts['pictures']} pictures, {counts['records']} dishes "
          f"updated, {counts['briefs']} briefs" + (f", {counts['gone']} dishes no longer on the "
                                                   "menu skipped" if counts["gone"] else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
