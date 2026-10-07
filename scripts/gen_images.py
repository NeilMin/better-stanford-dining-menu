#!/usr/bin/env python3
"""Render the dish images that data/dishes.json is still missing.

Each dish goes through the loop a person used to run by hand, one wrong picture
at a time:

  1. a brief (bsdm/brief.py) says what the picture has to show -- written once
     by a language model and kept in data/briefs.json
  2. draw it: local ComfyUI (RealVisXL), or Cloudflare Workers AI
  3. the judge (bsdm/judge.py) asks the brief's checks of the picture
  4. if every attempt fails, the failures go back to the brief, which is
     revised, and the dish is drawn again

A picture that never passes is never written. The board shows its placeholder
icon instead, which is less wrong than a wrong picture -- the same reason
build() refuses to publish last week's menus. --no-judge draws without asking,
for when you are going to look at the result yourself.

Images are keyed on the dish name, so this is resumable and idempotent: a dish
is drawn once and then reused across every hall and every week it appears in.
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

from bsdm import brief as brieflib  # noqa: E402
from bsdm import dishes as dishlib  # noqa: E402
from bsdm import judge  # noqa: E402
from bsdm.catalog import is_stale  # noqa: E402
from bsdm.cloudflare import KLEIN_MODEL, CloudflareClient, CloudflareError, CloudflareQuotaError  # noqa: E402
from bsdm.comfy import DEFAULT_URL, MODELS, ComfyClient, ComfyError, to_webp  # noqa: E402
from bsdm.llm import LLMError, Unavailable  # noqa: E402
from bsdm.llm import pick as pick_llm  # noqa: E402
from bsdm.pending import rank  # noqa: E402
from bsdm.queue import load_queue  # noqa: E402


IMAGES = ROOT / "data" / "images"
CATALOG = ROOT / "data" / "dishes.json"
CARD_RATIO = 16 / 9

# Fields of an earlier gate that a new picture makes meaningless.
_STALE_FIELDS = ("vlm_score", "vlm_reason", "rejected")

# Runs a dish may fail under one version of the brief instructions before it is
# left alone. A dish nothing passes for would otherwise take its four drawings
# out of the free runners' night every night, for ever; a new BRIEF_REV, or
# --retry-rejected, gives it another go.
MAX_TRIES = 3


def given_up(entry: dict) -> bool:
    rejected = entry.get("rejected") or {}
    return rejected.get("tries", 0) >= MAX_TRIES and rejected.get("brief_rev") == brieflib.BRIEF_REV


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


def record_image(dish_id: str, fields: dict, drop: tuple[str, ...] = ()) -> None:
    """Merge one dish's image fields into the catalog on disk."""
    catalog = json.loads(CATALOG.read_text())
    entry = catalog.setdefault(dish_id, {})
    for key in drop:
        entry.pop(key, None)
    entry.update(fields)
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
    client: CloudflareClient, prompt: str, negative: str,
    seed: int | None = None, model: str = KLEIN_MODEL,
) -> tuple[Image.Image, float]:
    """Generate an image via Cloudflare Workers AI."""
    started = time.monotonic()
    raw_bytes = client.generate_image(prompt, negative_prompt=negative, model=model, seed=seed)
    raw_img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
    card_img = crop_and_resize_to_card(raw_img)
    secs = time.monotonic() - started
    return card_img, secs


class Stop(Exception):
    """Something no later dish will get past tonight: quota, a missing server."""


def write_briefs_only(pending: list[tuple[str, dict]], args) -> int:
    """Write the queue's briefs and draw nothing: the `plan` job's work in draw.yml.

    Briefs are batched eight to a call to stay inside Flash's free allowance, and
    a batch only pays off over the whole queue. With one machine per dish or two,
    a machine's own share is too small to batch, so the briefs are written once
    here and handed to every machine. A dish whose brief fails is left for the
    machine that draws it, which asks again on its own.
    """
    llm = pick_llm(args.llm, args.llm_model, role="brief")
    if not llm.available():
        print("No GEMINI_API_KEY (environment or .env): no briefs written.", file=sys.stderr)
        return 0
    briefs = brieflib.load(ROOT)
    todo = [(d, e) for d, e in pending
            if args.rewrite_briefs or not brieflib.is_current(briefs.get(d))]
    wrote = 0
    try:
        for at in range(0, len(todo), args.brief_batch):
            batch = todo[at:at + args.brief_batch]
            try:
                written = brieflib.write_many([e for _, e in batch], llm) if len(batch) > 1 else [None]
            except Unavailable:
                raise
            except LLMError as exc:
                print(f"batch of {len(batch)} briefs failed, writing them one by one: {exc}", file=sys.stderr)
                written = [None] * len(batch)
            for (did, entry), brief in zip(batch, written):
                try:
                    brief = brief or brieflib.write(entry, llm)
                except Unavailable:
                    raise
                except LLMError as exc:
                    print(f"no brief for {entry['name']}: {exc}", file=sys.stderr)
                    continue
                brieflib.record(ROOT, did, brief)
                wrote += 1
    except Unavailable as exc:
        print(f"Out of briefs for tonight: {exc}", file=sys.stderr)
    print(f"Wrote {wrote} of {len(todo)} briefs.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", choices=["auto", "comfyui", "cloudflare"], default="auto",
                    help="auto uses ComfyUI when it is up, else Cloudflare (default: auto)")
    ap.add_argument("--url", default=DEFAULT_URL, help="ComfyUI base URL")
    ap.add_argument("--model", default="sdxl", choices=sorted(MODELS))
    ap.add_argument("--cf-model", default=KLEIN_MODEL,
                    help=f"Workers AI model for --backend cloudflare (default {KLEIN_MODEL})")
    ap.add_argument("--llm", choices=["auto", "claude", "gemini"], default="auto",
                    help="who writes briefs (and judges, unless --judge-llm says otherwise): the "
                         "Gemini API's free tier with GEMINI_API_KEY -- Flash models in turn for "
                         "briefs, Gemma for judging. auto is gemini; the claude CLI only when "
                         "named (default: auto)")
    ap.add_argument("--judge-llm", choices=["auto", "claude", "gemini"],
                    help="who judges pictures, if not the same as --llm")
    ap.add_argument("--llm-model", default="sonnet",
                    help="claude model alias, when the claude CLI is used (default sonnet)")
    ap.add_argument("--judge", action=argparse.BooleanOptionalAction, default=True,
                    help="only keep pictures that pass the brief's checks (default: on). "
                         "--no-judge draws once and keeps it, for when you will look yourself")
    ap.add_argument("--attempts", type=int, default=2, metavar="N",
                    help="pictures drawn per version of the brief (default 2)")
    ap.add_argument("--revisions", type=int, default=1, metavar="N",
                    help="times the brief is revised after its pictures all fail (default 1)")
    ap.add_argument("--rewrite-briefs", action="store_true", help="write the briefs afresh")
    ap.add_argument("--brief-batch", type=int, default=8, metavar="N",
                    help="dishes whose briefs one call writes (default 8)")
    ap.add_argument("--limit", type=int, help="stop after N dishes")
    ap.add_argument("--only", help="substring match on the dish name, or =exact name")
    ap.add_argument("--force", action="store_true", help="redraw dishes that already have images")
    ap.add_argument("--from-queue", nargs="?", const=str(ROOT / "data" / "redraw_queue.json"),
                    help="Read dishes to redraw from redraw_queue.json and force regeneration")
    ap.add_argument("--retry-rejected", action="store_true",
                    help=f"also try dishes that failed {MAX_TRIES} runs running under the current brief rules")
    ap.add_argument("--redraw-stale", action="store_true",
                    help="also redraw images drawn before the current prompt rules")
    ap.add_argument("--audit", action="store_true",
                    help="judge the pictures no judge has seen; redraw only those that fail, "
                         "and replace one only with a picture that passes")
    ap.add_argument("--max-priority", type=int, default=2, choices=(0, 1, 2),
                    help="0 meat only, 1 adds other mains, 2 adds sides (default)")
    ap.add_argument("--steps", type=int, help="override step count")
    ap.add_argument("--seed", type=int,
                    help="draw the first attempt with this seed rather than the dish's own")
    ap.add_argument("--free-every", type=int, default=20, metavar="N",
                    help="release ComfyUI's cached models every N images (0 disables)")
    ap.add_argument("--max-wait", type=float, default=600, metavar="SECONDS",
                    help="how long one ComfyUI picture may take (default 600; a CPU needs more)")
    ap.add_argument("--shard", metavar="K/N",
                    help="draw every Nth pending dish starting at the Kth, so N machines split "
                         "the queue between them (see .github/workflows/draw.yml)")
    ap.add_argument("--minutes", type=float, metavar="M",
                    help="start no new dish after M minutes, so a CI job ends before it is killed")
    ap.add_argument("--briefs-only", action="store_true",
                    help="write the briefs for the queue and draw nothing (needs no ComfyUI)")
    ap.add_argument("--count", action="store_true",
                    help="print how many dishes would be drawn, and draw nothing")
    args = ap.parse_args(argv)
    # A run is hours of one line per dish, read as it goes -- in a log file or a
    # CI step, where stdout is otherwise block-buffered and lands out of order
    # with the warnings on stderr.
    sys.stdout.reconfigure(line_buffering=True)
    if args.audit and not args.judge:
        ap.error("--audit needs the judge")

    queue_ids: set[str] | None = None
    if args.from_queue:
        q_path = Path(args.from_queue)
        queue_items = load_queue(q_path)
        if not queue_items:
            print(f"Redraw queue at {q_path} is empty. Nothing to redraw.")
            return 0
        queue_ids = {item["id"] for item in queue_items if "id" in item}
        args.force = True

    catalog = json.loads(CATALOG.read_text())
    IMAGES.mkdir(parents=True, exist_ok=True)
    pending = []
    for did, entry in sorted(catalog.items(), key=rank):
        if not entry.get("needs_image") or not entry.get("prompt"):
            continue
        if queue_ids is not None and did not in queue_ids:
            continue
        if entry.get("priority", 2) > args.max_priority:
            continue
        if args.only:
            target = args.only.strip()
            if target.startswith("="):
                if entry["name"].strip().lower() != target[1:].strip().lower():
                    continue
            elif target.lower() != did.lower() and target.lower() not in entry["name"].lower():
                continue
        path = IMAGES / f"{did}.webp"
        unjudged = args.audit and path.exists() and entry.get("image") and "judge" not in entry
        if (path.exists() and entry.get("image") and not args.force and not unjudged
                and is_current(path) and not (args.redraw_stale and is_stale(entry))):
            continue
        if given_up(entry) and not (args.force or args.retry_rejected):
            continue
        pending.append((did, entry))
    del catalog  # record_image() re-reads; a long run must not write back a stale copy

    if args.shard:
        # Dealt round-robin, so every machine gets its share of the meat, which
        # is drawn first, rather than one machine getting all of it.
        k, n = (int(x) for x in args.shard.split("/"))
        if not 1 <= k <= n:
            ap.error("--shard is K/N with 1 <= K <= N")
        pending = pending[k - 1::n]
    if args.limit is not None:
        pending = pending[: args.limit]
    if args.count:
        print(len(pending))
        return 0
    if not pending:
        print("Nothing to draw -- every illustratable dish already has an image.")
        return 0

    if args.briefs_only:
        return write_briefs_only(pending, args)

    comfy = ComfyClient(args.url, max_wait=args.max_wait)
    cf = CloudflareClient()
    backend = args.backend
    if backend == "auto":
        backend = "comfyui" if comfy.available() else "cloudflare" if cf.is_configured() else None
    if backend == "comfyui":
        if not comfy.available():
            print(f"No ComfyUI at {args.url}.\n"
                  f"Start the shared install with:\n"
                  f"  cd ~/Projects/.shared/comfyui && "
                  f"./.venv/bin/python main.py --listen 127.0.0.1 --port 8189", file=sys.stderr)
            return 2
        comfy.validate(args.model)
    elif backend == "cloudflare":
        if not cf.is_configured():
            print("Cloudflare backend needs CF_ACCOUNT_ID and CF_API_TOKEN.", file=sys.stderr)
            return 2
    else:
        print("Nothing to draw with: no ComfyUI and no Cloudflare credentials.", file=sys.stderr)
        return 2
    model_name = args.model if backend == "comfyui" else (
        "cf-klein" if "klein" in args.cf_model else "cf-" + args.cf_model.rsplit("/", 1)[-1])

    llm = pick_llm(args.llm, args.llm_model, role="brief")
    judge_llm = pick_llm(args.judge_llm or args.llm, args.llm_model, role="judge")
    if args.judge and not judge_llm.available():
        llm = judge_llm  # report the judge as the thing missing
    if not llm.available():
        if args.judge:
            # Without a judge nothing drawn tonight could be kept, so drawing
            # would spend the GPU on pictures destined for the bin.
            print("Nothing to write briefs and judge pictures -- no GEMINI_API_KEY (environment or "
                  ".env) and no --llm claude; nothing drawn. (--no-judge draws with the rule-based prompts.)",
                  file=sys.stderr)
            return 2
        llm = None

    def draw(positive: str, negative: str, seed: int) -> tuple[Image.Image, float]:
        if backend == "comfyui":
            try:
                raw, secs = comfy.generate(args.model, positive, negative, seed, steps=args.steps)
            except ComfyError as exc:
                if not comfy.available():
                    raise Stop(f"ComfyUI went away: {exc}")
                raise
            return crop_and_resize_to_card(raw), secs
        try:
            return generate_with_cloudflare(cf, positive, negative, seed=seed, model=args.cf_model)
        except CloudflareQuotaError as exc:
            raise Stop(f"Cloudflare quota: {exc}")

    print(f"Drawing {len(pending)} dishes with {model_name}"
          + (f", briefs by {llm.name}, judged by {judge_llm.name}" if args.judge else ", unjudged"))
    started = time.monotonic()
    done = rejected = passed = 0
    drawn = 0
    briefs = brieflib.load(ROOT)
    fresh: set[str] = set()  # written this run, so --rewrite-briefs writes each once
    brief_failed: set[str] = set()  # sent to the back of the queue once; see below

    def needs_brief(did: str) -> bool:
        return bool(llm) and did not in fresh and (
            args.rewrite_briefs or not brieflib.is_current(briefs.get(did)))

    def keep_brief(did: str, brief: dict) -> None:
        brieflib.record(ROOT, did, brief)
        briefs[did] = brief
        fresh.add(did)

    try:
        for i, (did, entry) in enumerate(pending, 1):
            tag = f"  [{i}/{len(pending)}] P{entry.get('priority', 2)} {entry['name'][:42]:42.42s}"
            if args.minutes and time.monotonic() - started > args.minutes * 60:
                print(f"\nOut of time after {args.minutes:g} min; {len(pending) - i + 1} dishes "
                      "left for the next run.")
                break

            # One call writes this dish's brief and the next few that need one.
            batch = [(d, e) for d, e in pending[i - 1:] if needs_brief(d)][:args.brief_batch]
            if len(batch) > 1 and batch[0][0] == did:
                try:
                    written = brieflib.write_many([e for _, e in batch], llm)
                except Unavailable:
                    raise
                except LLMError as exc:
                    print(f"{tag} batch of briefs failed, writing them one by one: {exc}", file=sys.stderr)
                    written = []
                for (d, _), b in zip(batch, written):
                    if b:
                        keep_brief(d, b)
            if needs_brief(did):
                try:
                    keep_brief(did, brieflib.write(entry, llm))
                except Unavailable:
                    raise
                except LLMError as exc:
                    # A timeout is the API having a bad minute, not a verdict on
                    # the dish, and a meat dish skipped here waited for the next
                    # scrape, ten hours on. Once, to the back of the queue: the
                    # dishes drawn in between are the backoff, and `for` over a
                    # list picks up what is appended while it runs.
                    again = did not in brief_failed
                    brief_failed.add(did)
                    if again:
                        pending.append((did, entry))
                    print(f"{tag} no brief: {exc}"
                          + (" -- will try again at the end" if again else ""), file=sys.stderr)
                    continue
            brief = briefs.get(did)

            if args.seed is not None:
                base_seed = args.seed
            elif queue_ids is not None and did in queue_ids:
                stored = entry.get("seed")
                base_seed = ((int(stored) + 7919 * 7 + 1) % 2**32) if stored is not None else seed_for(did, entry)
            else:
                base_seed = seed_for(did, entry)
            kept = None
            verdicts: list[dict] = []
            secs = 0.0

            # A picture drawn before there was a judge is asked first. Most pass,
            # and redrawing a picture that is right would only trade it for another.
            existing = IMAGES / f"{did}.webp"
            if args.audit and entry.get("image") and existing.exists() and "judge" not in entry:
                try:
                    verdict = judge.inspect(existing.read_bytes(), brief, judge_llm)
                except Unavailable:
                    raise
                except LLMError as exc:
                    print(f"{tag} judge failed on the existing picture: {exc}", file=sys.stderr)
                    continue
                if verdict["pass"]:
                    passed += 1
                    record_image(did, {"judge": {k: verdict[k] for k in ("judge", "seen", "at")},
                                       "brief_rev": brief["rev"]}, drop=_STALE_FIELDS)
                    print(f"{tag} existing picture passes", flush=True)
                    continue
                verdicts.append(verdict)
                why = "; ".join(f"{f['q']} {f['got']}" for f in verdict["failed"])
                print(f"{tag} existing picture fails: {verdict['seen'][:60]} -- {why[:120]}")
            for version in range(args.revisions + 1 if args.judge else 1):
                if version:
                    try:
                        brief = brieflib.revise(entry, brief, verdicts[-args.attempts:], llm)
                    except Unavailable:
                        raise
                    except LLMError as exc:
                        print(f"{tag} revision failed: {exc}", file=sys.stderr)
                        break
                    keep_brief(did, brief)
                if brief:
                    positive, negative = brieflib.compose(entry, brief, close=backend == "cloudflare")
                else:
                    positive = entry["prompt"]
                    negative = entry.get("negative") or dishlib.negative_prompt(entry)

                for attempt in range(args.attempts if args.judge else 1):
                    # Deterministic, so a rerun of the same brief redraws the same pictures.
                    seed = (base_seed + 7919 * (version * args.attempts + attempt)) % 2**32
                    try:
                        image, s = draw(positive, negative, seed)
                    except (ComfyError, CloudflareError, OSError) as exc:
                        print(f"{tag} draw failed: {exc}", file=sys.stderr)
                        continue
                    secs += s
                    drawn += 1
                    if backend == "comfyui" and args.free_every and drawn % args.free_every == 0:
                        comfy.free()
                    if not args.judge:
                        kept = (image, seed, None)
                        break
                    try:
                        verdict = judge.inspect(to_webp(image), brief, judge_llm)
                    except Unavailable:
                        raise
                    except LLMError as exc:
                        # An unjudged picture is an unkept picture.
                        print(f"{tag} judge failed: {exc}", file=sys.stderr)
                        continue
                    verdicts.append(verdict)
                    if verdict["pass"]:
                        kept = (image, seed, verdict)
                        break
                    why = "; ".join(f"{f['q']} {f['got']}" for f in verdict["failed"])
                    print(f"{tag} rejected: {verdict['seen'][:60]} -- {why[:120]}")
                if kept:
                    break

            if kept is None:
                rejected += 1
                last = verdicts[-1] if verdicts else {}
                record_image(did, {"rejected": {
                    "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "brief_rev": brief.get("rev") if brief else None,
                    "tries": (entry.get("rejected") or {}).get("tries", 0) + 1,
                    "pictures": len(verdicts),
                    "seen": last.get("seen"),
                    "failed": [f["q"] for f in last.get("failed", [])],
                }})
                print(f"{tag} NOT DRAWN -- no picture passed", file=sys.stderr)
                continue

            image, seed, verdict = kept
            (IMAGES / f"{did}.webp").write_bytes(to_webp(image))
            done += 1
            fields = {
                "image": f"{did}.webp",
                "model": model_name,
                "seed": seed,
                "prompt_rev": dishlib.PROMPT_REV,
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            if brief:
                fields["brief_rev"] = brief["rev"]
            if verdict:
                fields["judge"] = {k: verdict[k] for k in ("judge", "seen", "at")}
            record_image(did, fields, drop=_STALE_FIELDS + (() if verdict else ("judge",)))
            elapsed = time.monotonic() - started
            eta = (elapsed / i) * (len(pending) - i)
            print(f"{tag} {secs:5.1f}s [{model_name}] kept after {len(verdicts) or 1} "
                  f"eta {eta / 60:.0f}m", flush=True)
    except (Stop, Unavailable) as exc:
        print(f"\nStopped: {exc}", file=sys.stderr)

    print(f"\nKept {done}, not drawn {rejected}"
          + (f", existing pictures passed {passed}" if args.audit else "")
          + f", in {(time.monotonic() - started) / 60:.1f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
