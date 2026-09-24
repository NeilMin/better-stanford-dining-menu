#!/usr/bin/env python3
"""Fill in the Chinese translations data/zh.json is still missing.

The engine is the Claude Code CLI in headless mode (`claude -p`), so translating
costs nothing beyond the subscription already in use and needs no API key. Like
image generation this runs locally and its output is committed: CI scrapes and
publishes, it never translates. A dish that has not been through here yet simply
shows its English name in Chinese mode.

Work is keyed on the dish name and on the ingredient term, so this is resumable
and idempotent -- a term is translated once and then reused by every dish that
lists it.

    make translate                                   # everything missing
    uv run python scripts/translate.py --dry-run     # what would be sent
    uv run python scripts/translate.py --only tofu --force   # redo a few dishes
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bsdm import zh as zhlib  # noqa: E402
from bsdm.cloudflare import CloudflareClient, CloudflareError, CloudflareQuotaError  # noqa: E402

SYSTEM = (
    "You translate the menus of a US university dining hall into Simplified "
    "Chinese, for Chinese students reading the menu before they decide where to "
    "eat. You reply with one JSON object and nothing else: no prose, no "
    "explanation, no markdown fence."
)

RULES = {
    "dishes": """These are dish names from a dining hall menu board.
- Translate as a dish name a Chinese diner would recognise, normally cooking method plus main ingredient: "Teriyaki Chicken Thigh" -> 照烧鸡腿.
- Keep them short. These are menu names, not descriptions, and they are read in a narrow column.
- Keep a cuisine or a place when the name turns on it: "Jamaican Jerk Chicken" -> 牙买加烟熏辣鸡.
- Keep brand names, chef names and Stanford dining hall names in English, inside Chinese parentheses where the English name trails the dish: "Panini Station (Branner)" -> 帕尼尼窗口（Branner）.
- A name that is a serving station rather than a dish stays one: "Allergen Friendly Pizza Station" -> 无过敏原披萨窗口.
- "Plant-Forward" or "Plant Powered" means plant-based: translate as "植物基" or "植物肉", NEVER literally as "植物向前" (e.g. "Plant-Forward Tenders" -> 植物基鸡柳).""",

    "terms": """These are ingredient-label terms, the kind printed on a packet.
- Use the everyday word, the one on a supermarket label or in a home kitchen: 面粉, 番茄, 高汤.
- "Plant-forward" means plant-based: translate as "植物基", NEVER literally as "植物向前" (e.g. "plant-forward chicken strips" -> 植物基鸡肉条).
- For additives and processing aids use the standard Chinese additive name, and put the English after it in parentheses when the Chinese alone would not be recognised: "BHT" -> BHT（二丁基羟基甲苯）.
- Keep letter codes and brand names as they are: "A-1 steak sauce", "FD&C yellow no.5".
- One translation per term, no alternatives, no pinyin, no explanation.
- A term that is a whole sentence is translated as a sentence.""",

    "halls": """These are one-line descriptions of a Stanford dining hall's concept, shown under the hall's name on the page.
- Keep the restaurant concept name and any chef's name in English: "Star Ginger, inspired by Chef Mai Pham" -> Star Ginger，灵感源自主厨 Mai Pham.
- Write it the way a Chinese restaurant would describe itself, not word for word. Drop "our", and use the idiomatic shape: "Home of our Kosher Kitchen" -> 犹太洁食（Kosher）厨房之家, not 我们的洁食厨房所在地.
- A dining hall is 食堂, not 餐厅.""",

    "specials": """These are limited-time dinner specials off a dining hall's fortnightly calendar. Unlike a menu name, a special is often a short list of what comes with it.
- Keep the structure of the original: a list stays a list, separated by Chinese enumeration commas.
- Translate as food, not as prose: "Jerk Pork Belly, Rasta Pasta, Ripe Fried Plantains" -> 牙买加香辣烤五花肉、牙买加奶油辣味意面（Rasta Pasta）、煎熟大蕉.
- Use the name a Chinese menu already uses for a foreign dish (玛莎拉咖喱鸡, 叉烧越南法棍) rather than transliterating it or translating its words literally. "Jerk" is a Jamaican spice rub, not smoking; "ginger beer" is a soft drink, 姜汁汽水.
- Keep a dish's own proper name in English inside Chinese parentheses when the Chinese alone would not identify it: "Poul Nan Sos" -> 海地炖鸡（Poul Nan Sos）.
- Keep announcements as announcements: "Closed for Winter Break" -> 寒假期间关闭.""",
}

BATCH = {"dishes": 40, "terms": 40, "halls": 20, "specials": 25}


class TranslateError(RuntimeError):
    pass


def ask(items: list[str], section: str, args) -> dict[str, str]:
    """One model call: a list of English strings in, a JSON object out."""
    prompt = (
        f"{RULES[section]}\n\n"
        "Reply with a JSON object mapping every input string below, copied "
        "exactly as given, to its Simplified Chinese translation.\n\n"
        + json.dumps(items, ensure_ascii=False, indent=0)
    )
    cmd = [args.claude_bin, "-p", "--model", args.model,
           "--system-prompt", SYSTEM, "--strict-mcp-config", "--restricted"]
    try:
        # Run outside the repo: the translator wants none of the project's
        # context, and loading it would be paid for on every batch.
        done = subprocess.run(
            cmd + [prompt], capture_output=True, text=True,
            timeout=args.timeout, cwd=tempfile.gettempdir(),
        )
    except subprocess.TimeoutExpired:
        raise TranslateError(f"no answer in {args.timeout}s")
    if done.returncode != 0:
        raise TranslateError((done.stderr or done.stdout).strip()[:200] or "claude failed")

    text = done.stdout.strip()
    # Belt and braces: the system prompt forbids a fence, but a stray one must
    # not throw away a whole batch.
    if match := re.search(r"\{.*\}", text, re.S):
        text = match.group(0)
    try:
        answer = json.loads(text)
    except json.JSONDecodeError as exc:
        raise TranslateError(f"unparseable answer: {exc}")
    if not isinstance(answer, dict):
        raise TranslateError("answer was not an object")

    # Match loosely on the way back. The model occasionally normalises the
    # whitespace or the case of a key; the term it translated is still the term
    # that was asked about.
    by_norm = {zhlib.norm(k): v for k, v in answer.items() if isinstance(v, str)}
    out = {}
    for item in items:
        value = answer.get(item) or by_norm.get(zhlib.norm(item))
        if isinstance(value, str) and value.strip():
            out[item] = value.strip()
    return out


def ask_cloudflare(items: list[str], section: str, client: CloudflareClient) -> dict[str, str]:
    """One model call via Cloudflare Workers AI."""
    return client.translate(items, section, SYSTEM, RULES[section])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", choices=["auto", "cloudflare", "claude"], default="auto",
                    help="translation backend: cloudflare, claude, or auto (default: auto)")
    ap.add_argument("--model", default="sonnet", help="model alias passed to claude (default sonnet)")
    ap.add_argument("--claude-bin", default="claude", help="path to the Claude Code CLI")
    ap.add_argument("--section", choices=sorted(zhlib.SECTIONS), action="append",
                    help="limit to dish names, ingredient terms, hall concepts or specials")
    ap.add_argument("--only", help="substring match on the English source")
    ap.add_argument("--force", action="store_true", help="retranslate what is already done")
    ap.add_argument("--limit", type=int, help="stop after N items per section")
    ap.add_argument("--batch", type=int, help="items per model call")
    ap.add_argument("--jobs", type=int, default=3, help="model calls in flight at once")
    ap.add_argument("--timeout", type=int, default=240, help="seconds to wait for one call")
    ap.add_argument("--dry-run", action="store_true", help="print what would be sent and stop")
    args = ap.parse_args(argv)

    cf_client = CloudflareClient()
    if args.backend == "cloudflare":
        if not cf_client.is_configured():
            print("Error: Cloudflare backend requested but CF_ACCOUNT_ID and CF_API_TOKEN are not set.",
                  file=sys.stderr)
            return 1
        use_cf = True
    elif args.backend == "auto":
        use_cf = cf_client.is_configured()
    else:
        use_cf = False

    table = zhlib.load(ROOT)
    want = zhlib.wanted(ROOT)
    sections = args.section or ["dishes", "terms", "halls", "specials"]

    todo: dict[str, dict[str, str]] = {}
    for section in sections:
        items = {
            key: english for key, english in want[section].items()
            if (args.force or not zhlib.get(table, section, key))
            and (not args.only or args.only.lower() in english.lower())
        }
        if args.limit:
            items = dict(list(items.items())[: args.limit])
        if items:
            todo[section] = items

    if not todo:
        print(zhlib.summarize(ROOT))
        print("Nothing to translate.")
        return 0

    if args.dry_run:
        backend_name = "Cloudflare Workers AI" if use_cf else f"claude ({args.model})"
        for section, items in todo.items():
            size = args.batch or BATCH[section]
            print(f"{section}: {len(items)} items in {-(-len(items) // size)} calls to {backend_name}")
            for english in list(items.values())[:8]:
                print(f"  {english}")
            if len(items) > 8:
                print(f"  ... and {len(items) - 8} more")
        return 0

    started = time.monotonic()
    done_count = failed = 0
    quota_exceeded = False

    for section, items in todo.items():
        size = args.batch or BATCH[section]
        # Key by the English string, which is what the model sees and answers
        # with; several dish ids can share a name, so map back to all of them.
        by_english: dict[str, list[str]] = {}
        for key, english in items.items():
            by_english.setdefault(english, []).append(key)
        english_list = list(by_english)
        batches = [english_list[i: i + size] for i in range(0, len(english_list), size)]
        backend_name = "Cloudflare Workers AI" if use_cf else f"claude ({args.model})"
        print(f"{section}: {len(items)} missing, {len(batches)} calls to {backend_name}")

        with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
            if use_cf:
                futures = {pool.submit(ask_cloudflare, batch, section, cf_client): batch for batch in batches}
            else:
                futures = {pool.submit(ask, batch, section, args): batch for batch in batches}

            for n, future in enumerate(as_completed(futures), 1):
                batch = futures[future]
                try:
                    answer = future.result()
                except CloudflareQuotaError as exc:
                    print(f"  [{n}/{len(batches)}] Cloudflare quota exceeded: {exc}",
                          file=sys.stderr)
                    for f in futures:
                        f.cancel()
                    quota_exceeded = True
                    break
                except (TranslateError, CloudflareError) as exc:
                    failed += 1
                    print(f"  [{n}/{len(batches)}] FAILED ({len(batch)} items): {exc}",
                          file=sys.stderr)
                    continue

                pairs = {
                    key: (english, answer[english])
                    for english in answer for key in by_english[english]
                }
                # Written per batch, not at the end: a long first run must
                # survive a Ctrl-C with everything it has already translated.
                zhlib.merge(ROOT, section, pairs)
                done_count += len(pairs)
                dropped = len(batch) - len(answer)
                note = f", {dropped} not answered" if dropped else ""
                print(f"  [{n}/{len(batches)}] {len(answer)} translated{note}"
                      f"   e.g. {next(iter(answer.items()), ('', ''))[1][:24]}", flush=True)

        if quota_exceeded:
            print("Stopping translation due to quota limit.", file=sys.stderr)
            break

    print(f"\nTranslated {done_count} items in {(time.monotonic() - started) / 60:.1f} min")
    print(zhlib.summarize(ROOT))
    if quota_exceeded:
        return 0
    return 1 if failed and not done_count else 0


if __name__ == "__main__":
    raise SystemExit(main())

