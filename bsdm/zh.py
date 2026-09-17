"""The Chinese layer: dish names translated whole, ingredients term by term.

Ingredient text is deliberately not translated as prose. R&DE ingredient strings
are lists drawn from a small, heavily repeated vocabulary -- one full week is
~2,600 dish rows but only ~870 distinct terms, and "salt" alone accounts for 247
of them -- so the vocabulary is translated once and the list is reassembled per
dish in the browser. That keeps the wording identical between dishes, and makes
a new day's menu nearly free: a new dish costs one name plus whichever handful of
its terms have never been seen before.

`terms_in` and `norm` are mirrored in web/app.js, which reassembles the list on
the page. The two tokenizers must agree exactly: anything the page splits out but
this file never offered for translation falls back to English and shows up as a
stray English word mid-sentence.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# The separators an ingredient list is built from, kept in the split so the page
# can put the list back together with Chinese punctuation. Source text is not
# always balanced -- a few strings open a parenthesis and never close it, and one
# closes a bracket it never opened -- so the split is structure-free on purpose:
# every separator is translated where it stands rather than parsed into a tree.
_SPLIT = re.compile(r"([,()\[\]])")
_SEPARATORS = frozenset(",()[]")

# {section: whether entries keep their English alongside}. Terms are keyed by the
# English itself, so storing it again would be noise; dishes and halls are keyed
# by id, and the English is what makes the file reviewable by hand.
SECTIONS = {"dishes": True, "terms": False, "halls": True}


def norm(term: str) -> str:
    """The lookup key for one ingredient term. Mirrored in web/app.js."""
    return " ".join(term.split()).lower()


def terms_in(ingredients: str) -> list[str]:
    """Every translatable term in an ingredient string, in order."""
    out = []
    for piece in _SPLIT.split(ingredients or ""):
        if piece in _SEPARATORS:
            continue
        if key := norm(piece):
            out.append(key)
    return out


def path_for(root: Path) -> Path:
    return root / "data" / "zh.json"


def load(root: Path) -> dict:
    path = path_for(root)
    table = json.loads(path.read_text()) if path.exists() else {}
    for section in SECTIONS:
        table.setdefault(section, {})
    return table


def save(root: Path, table: dict) -> None:
    path_for(root).write_text(
        json.dumps(table, indent=1, ensure_ascii=False, sort_keys=True) + "\n"
    )


def get(table: dict, section: str, key: str) -> str | None:
    """The Chinese for one key, or None if it has not been translated."""
    entry = table.get(section, {}).get(key)
    if isinstance(entry, str):
        return entry or None
    return (entry or {}).get("zh") or None


def put(table: dict, section: str, key: str, english: str, chinese: str) -> None:
    table.setdefault(section, {})[key] = (
        {"en": english, "zh": chinese} if SECTIONS[section] else chinese
    )


def merge(root: Path, section: str, pairs: dict[str, tuple[str, str]]) -> None:
    """Merge one batch of translations into the table on disk.

    The table is re-read before every write rather than held in memory: a first
    run makes a couple of dozen model calls over several minutes and has to
    survive a Ctrl-C, and a wholesale write would drop anything another run --
    or a hand edit -- had added in the meantime.
    """
    table = load(root)
    for key, (english, chinese) in pairs.items():
        put(table, section, key, english, chinese)
    save(root, table)


def wanted(root: Path) -> dict[str, dict[str, str]]:
    """Everything the Chinese site needs, as {section: {key: English source}}.

    Terms are collected from the stored menus rather than from the catalog: the
    catalog keeps one ingredient string per dish, but the site publishes a
    variant per hall, and Branner's allergen-free recipes list different things.
    """
    catalog = json.loads((root / "data" / "dishes.json").read_text())
    names = {did: entry["name"] for did, entry in catalog.items()}

    terms: dict[str, str] = {}
    for path in sorted((root / "data" / "menus").glob("*.json")):
        day = json.loads(path.read_text())
        for meals in day["halls"].values():
            for served in meals.values():
                for dish in served:
                    for term in terms_in(dish.get("ingredients") or ""):
                        terms[term] = term

    config = json.loads((root / "config" / "halls.json").read_text())
    halls = {h["id"]: h["concept"] for h in config["halls"] if h.get("concept")}

    return {"dishes": names, "terms": terms, "halls": halls}


def missing(root: Path, table: dict | None = None) -> dict[str, dict[str, str]]:
    """The subset of `wanted` that has no translation yet."""
    table = load(root) if table is None else table
    return {
        section: {k: en for k, en in entries.items() if not get(table, section, k)}
        for section, entries in wanted(root).items()
    }


def summarize(root: Path) -> str:
    table = load(root)
    want = wanted(root)
    parts = []
    for section, label in (("dishes", "dish names"), ("terms", "ingredient terms"),
                           ("halls", "hall concepts")):
        total = len(want[section])
        have = sum(1 for k in want[section] if get(table, section, k))
        parts.append(f"{have}/{total} {label}")
    return "Chinese: " + " | ".join(parts)
