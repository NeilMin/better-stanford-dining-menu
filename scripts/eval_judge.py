#!/usr/bin/env python3
"""Measure the judge against pictures a person already ruled on.

Every commit below redrew specific dishes because somebody looked at the picture
and said it was wrong. The version before the commit is therefore a known
reject, and the version on disk now is what was accepted in its place. A judge
worth trusting fails the first and passes the second -- and this can be checked
without anyone looking at a picture again.

    uv run python scripts/eval_judge.py                 # rejects vs accepted
    uv run python scripts/eval_judge.py --sample 20     # plus 20 unreviewed current pictures
    uv run python scripts/eval_judge.py --only gyro     # one dish, verbose

Briefs are written through bsdm/brief.py and recorded in data/briefs.json, the
same ones gen_images.py will draw from; pass --rewrite to write them afresh.
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bsdm import brief as brieflib  # noqa: E402
from bsdm import judge  # noqa: E402
from bsdm.llm import LLMError, pick  # noqa: E402

# Commits that redrew named dishes after their pictures were rejected by eye.
# Library-wide redraws (a prompt-rule bump, a model change) are left out: those
# replaced pictures nobody had ruled on.
REJECTIONS = [
    "22c9746",  # Saffron Rice, Spam Musubi Bowl
    "ccc1083",  # Spicy Green Beans, Hawaiian Teriyaki Short Ribs, Crispy Korean-Style Tempeh
    "37ece25",  # Spam Musubi Bowl, again
    "1e15978",  # seven key dishes: tenders, eggplant, vindaloo, bourguignon, ...
    "b3947aa",  # Vegetable Lasagna
    "0859547",  # Mushroom Etouffee, Lemon Herbed Zucchini
    "2609eb6",  # Chicken Fajitas, Beef Hot Dog
    "4f05036",  # eight dishes: garlic rice, basmati, pineapple, curried vegetables, ...
    "7d14316",  # Beef & Lamb Gyro Meat
    "5baf9d6",  # Miso Black Cod
    "dd2a06a",  # Coconut Red Curry with Sweet Potato, Cilantro Lime Salmon
]


def git_blob(rev: str, path: str) -> bytes:
    return subprocess.run(["git", "show", f"{rev}:{path}"], cwd=ROOT, capture_output=True,
                          check=True).stdout


def rejected_pictures() -> list[tuple[str, str, bytes]]:
    """(commit, dish id, picture bytes) for every picture a rejection commit replaced."""
    out = []
    for commit in REJECTIONS:
        diff = subprocess.run(["git", "diff", "--name-status", f"{commit}^", commit, "--", "data/images"],
                              cwd=ROOT, capture_output=True, text=True, check=True).stdout
        for line in diff.splitlines():
            status, path = line.split("\t")
            if status == "M":
                out.append((commit, Path(path).stem, git_blob(f"{commit}^", path)))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--llm", choices=["auto", "claude", "gemini"], default="auto",
                    help="the claude CLI where installed, else Gemini (default: auto)")
    ap.add_argument("--judge-llm", choices=["auto", "claude", "gemini"],
                    help="who judges, if not the same as --llm (which then only writes briefs)")
    ap.add_argument("--model", default="sonnet", help="claude model alias (default sonnet)")
    ap.add_argument("--sample", type=int, default=0, help="also judge N unreviewed current pictures")
    ap.add_argument("--only", help="substring of the dish name")
    ap.add_argument("--rewrite", action="store_true", help="write the briefs afresh")
    ap.add_argument("--brief-root", type=Path, default=ROOT,
                    help="project root whose data/briefs.json to read and write -- point it at a "
                         "scratch directory to try another brief writer without touching the real one")
    ap.add_argument("--brief-batch", type=int, default=1, metavar="N",
                    help="write briefs N dishes to a call, as gen_images.py does (default 1)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", type=Path, help="write every verdict here as JSON")
    args = ap.parse_args(argv)

    llm = pick(args.llm, args.model, role="brief")
    judge_llm = pick(args.judge_llm or args.llm, args.model, role="judge")
    catalog = json.loads((ROOT / "data" / "dishes.json").read_text())
    briefs = brieflib.load(args.brief_root)
    lock = threading.Lock()

    cases = []  # (kind, dish id, label, picture)
    rejects = rejected_pictures()
    reviewed = {did for _, did, _ in rejects}
    for commit, did, blob in rejects:
        cases.append(("reject", did, commit, blob))
    for did in sorted(reviewed):
        cases.append(("accept", did, "HEAD", (ROOT / "data" / "images" / f"{did}.webp").read_bytes()))
    if args.sample:
        pool = sorted(did for did, e in catalog.items()
                      if e.get("image") and did not in reviewed and (ROOT / "data" / "images" / e["image"]).exists())
        for did in random.Random(7).sample(pool, min(args.sample, len(pool))):
            cases.append(("sample", did, "HEAD", (ROOT / "data" / "images" / f"{did}.webp").read_bytes()))
    if args.only:
        cases = [c for c in cases if args.only.lower() in catalog[c[1]]["name"].lower()]

    def brief_for(did: str) -> dict:
        existing = briefs.get(did)
        if existing and brieflib.is_current(existing) and (not args.rewrite or did in batched):
            return existing
        b = brieflib.write(catalog[did], llm)
        with lock:  # record() re-reads and rewrites the file
            briefs[did] = b
            brieflib.record(args.brief_root, did, b)
        return b

    # Briefs first, one per dish, so no two cases race to write the same one.
    dish_ids = sorted({c[1] for c in cases})
    batched: set[str] = set()
    if args.brief_batch > 1:
        todo = [d for d in dish_ids if args.rewrite or not brieflib.is_current(briefs.get(d))]
        chunks = [todo[n:n + args.brief_batch] for n in range(0, len(todo), args.brief_batch)]

        def write_chunk(chunk):
            written = brieflib.write_many([catalog[d] for d in chunk], llm)
            with lock:
                for d, b in zip(chunk, written):
                    if b:
                        briefs[d] = b
                        batched.add(d)
                        brieflib.record(args.brief_root, d, b)
            return sum(1 for b in written if b)

        with ThreadPoolExecutor(args.workers) as ex:
            for chunk, result in zip(chunks, ex.map(lambda c: _try(write_chunk, c), chunks)):
                if isinstance(result, Exception):
                    print(f"  batch of {len(chunk)} briefs failed: {result}", file=sys.stderr)
                elif result < len(chunk):
                    print(f"  batch left {len(chunk) - result} of {len(chunk)} unusable", file=sys.stderr)
        # What a batch left out is written alone below, as gen_images.py does.
    with ThreadPoolExecutor(args.workers) as ex:
        for did, result in zip(dish_ids, ex.map(lambda d: _try(brief_for, d), dish_ids)):
            if isinstance(result, Exception):
                print(f"  brief failed for {catalog[did]['name']}: {result}", file=sys.stderr)

    def run(case):
        _kind, did, _label, blob = case
        b = briefs.get(did)
        if not b:
            return case, None
        return case, _try(judge.inspect, blob, b, judge_llm)

    results = []
    with ThreadPoolExecutor(args.workers) as ex:
        for (kind, did, label, _), verdict in ex.map(run, cases):
            name = catalog[did]["name"]
            if verdict is None or isinstance(verdict, Exception):
                print(f"{kind:7s} {'ERROR':5s} {name[:34]:34s} {verdict}")
                results.append({"kind": kind, "id": did, "name": name, "rev": label, "error": str(verdict)})
                continue
            ok = verdict["pass"] if kind != "reject" else not verdict["pass"]
            mark = "ok" if ok else "MISS"
            why = "; ".join(f"{f['q']} -> {f['got']}" for f in verdict["failed"])
            print(f"{kind:7s} {mark:5s} {name[:34]:34s} {'PASS' if verdict['pass'] else 'FAIL'}  "
                  f"{verdict['seen'][:70]}" + (f"\n{'':48s}{why}" if why else ""))
            results.append({"kind": kind, "id": did, "name": name, "rev": label, **verdict})

    print()
    for kind, want in (("reject", False), ("accept", True), ("sample", True)):
        rows = [r for r in results if r["kind"] == kind and "error" not in r]
        if rows:
            right = sum(1 for r in rows if r["pass"] == want)
            verb = "failed (as they should)" if kind == "reject" else "passed"
            print(f"{kind:7s} {right}/{len(rows)} {verb}")
    errors = sum(1 for r in results if "error" in r)
    if errors:
        print(f"{errors} errors")
    if args.out:
        args.out.write_text(json.dumps(results, indent=1, ensure_ascii=False))
    return 0


def _try(fn, *a):
    try:
        return fn(*a)
    except (LLMError, OSError, subprocess.SubprocessError) as exc:
        return exc


if __name__ == "__main__":
    raise SystemExit(main())
