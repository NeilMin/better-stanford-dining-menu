"""A dish's visual brief: what the picture has to show, written once by a model.

SDXL knows a picture of "bulgogi" and has no idea what "Beef & Lamb Gyro Meat"
or "Miso Black Cod" look like on a plate. For two weeks that knowledge came from
a person looking at a wrong picture and writing a regex -- the per-dish branches
in dishes._hero_protein_phrase() and dishes.negative_prompt() are what that
looks like after thirty dishes. A brief moves the knowledge to a language model:

    dish    the name a cookbook would use ("Magnolia Boil" is a seafood boil)
    look    the visible food, as comma-separated nouns and adjectives for CLIP
    vessel  plate or bowl
    avoid   what the image model tends to add wrongly -- the negative prompt,
            because CLIP cannot read "no pita" and draws the pita
    checks  yes/no questions about the finished photo that tell the right dish
            from the likely mistakes, answered later by bsdm/judge.py

The photo style is not the model's to choose: dishes.photo_style() is appended
to every prompt, so the board still reads as one set.

Briefs live in data/briefs.json, their own file with one writer, rather than in
the catalog: catalog.build() re-derives dishes.json on every scrape and CI runs
it, and a field it does not know about is a field it drops. Writing merges into
the file on disk, the same discipline as record_image(), so a long run can be
interrupted and a hand-corrected brief is never overwritten by accident.

A revision changes `dish`, `look`, `vessel` and `avoid` only. The checks are the
definition of a right picture, and a model asked to get past its own failed
check will happily decide the check was the problem. The one exception is a
check no picture could answer -- the judge said "unclear" every time -- which
may be reworded, keeping its expected answer: "is the meat pork?" cannot be
settled by a photo of curry, and would otherwise hold the dish on its
placeholder for good.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from bsdm import dishes as dishlib
from bsdm.llm import LLMError, parse_json

# Bumped whenever the instructions below change enough that briefs written
# under the old ones should be rewritten.
BRIEF_REV = 5

SYSTEM = (
    "You are a food stylist who writes briefs for a text-to-image model (Stable Diffusion XL, "
    "which reads a comma-separated description through CLIP). You know what dishes look like "
    "as a US university dining hall serves them. Reply with a single JSON object and nothing else."
)

_FORMAT = """Reply with this JSON object:
{
  "dish": "the most widely known name for this dish, as a cookbook would title it",
  "look": "what the camera sees, see rules",
  "vessel": "plate" or "bowl",
  "avoid": ["short noun phrases", "..."],
  "checks": [{"q": "a yes/no question about the photo", "yes": true}, ...]
}

dish -- Not the menu's marketing name: "Magnolia Boil" is "Cajun seafood boil", "Craveable Grains" is whatever grain dish the ingredients describe.

look -- The food only, 20 to 50 words, comma-separated concrete nouns and adjectives: the main component first, then the visible sides of it -- cut, shape, colour, texture, sauce, garnish. One portion, the way a diner pictures the dish from its name: a hot dog is in a bun and a burger has one, even where the menu lists the bun as a separate item. Only what is visible: no seasonings you cannot see, no oil, no cooking steps, no praise. Never write a negation ("no meat", "without bread"): the image model cannot read it and draws the word -- that belongs in avoid.

vessel -- "bowl" for soup, stew, curry, rice, grains, noodles in broth, anything loose or saucy; "plate" otherwise.

avoid -- 3 to 10 things the image model is likely to put in this picture wrongly: the wrong protein, the wrong form of the dish (a tortilla wrap for fajitas, pita for gyro meat, skewers for meat that is not skewered), raw versions of cooked things, side dishes and platters, garnishes that could be mistaken for the food. For a vegetarian or vegan dish always include meat, chicken, beef, pork, fish and shrimp.

checks -- 2 to 4 yes/no questions about the finished photo that decide whether it shows the right dish at all. A check fails the picture, so each one must be something that, answered wrongly, would make a diner say "that is not what I ordered": the wrong main ingredient or protein, the wrong form of the dish (ground instead of sliced, a soup instead of a dry dish, a wrap instead of loose fillings), raw instead of cooked, a different dish entirely (tofu where the fish should be). Never check garnishes, herbs, seeds, the exact colour of a sauce, minor vegetables, or whether a bun, bread, rice or a side comes with it -- an image model varies those and the picture is still the dish. Each question asks about one thing. At most one question may expect yes: the main component, named plainly and as a photo shows it ("Is the main item a fillet of white fish?", not "Is it bone-in short rib with peppers and onions?"; "meat chunks in red curry sauce", not "pork", since a photo cannot tell pork from beef in a sauce). Every other question is a likely mistake whose answer should be no ("Is the meat ground like mince?"). Ask only about big things visible at a glance, never "Is it seasoned with oregano?". Lighting, the plate, other dishes in the picture and text are checked separately."""

_EXAMPLES = """Three briefs that fixed real mistakes. The first pictures of these showed ground meat on a flatbread, a block of tofu in sauce, and a luau platter.

Beef & Lamb Gyro Meat (beef, lamb, onion):
{"dish": "Greek gyro meat", "look": "a pile of thin shaved slices of seasoned beef and lamb, browned crisp edges, juicy dark meat strips, sprinkle of chopped parsley", "vessel": "plate", "avoid": ["pita bread", "flatbread", "wrap", "ground meat", "meatballs", "skewers", "french fries"], "checks": [{"q": "Is the meat in thin shaved slices or strips?", "yes": true}, {"q": "Is the meat ground or crumbled like mince?", "yes": false}, {"q": "Is the meat wrapped in a pita or flatbread?", "yes": false}]}

Miso Black Cod (black cod, white miso paste, mirin, sugar, green onions):
{"dish": "miso-glazed black cod", "look": "a thick fillet of sablefish, glossy caramelized dark-amber miso glaze on top, flaky snow-white flesh, crisp dark skin, a few thin slices of scallion", "vessel": "plate", "avoid": ["salmon", "pink fish", "tofu", "green beans", "soup", "noodles", "rice"], "checks": [{"q": "Is the main item a fillet of white-fleshed fish?", "yes": true}, {"q": "Is the fish pink or orange like salmon?", "yes": false}, {"q": "Does the main item look like a block of tofu?", "yes": false}]}

Hawaiian Garlic Rice (rice, garlic, butter, green onions):
{"dish": "garlic fried rice", "look": "fluffy cooked white rice grains tossed with crispy golden fried garlic bits, flecks of chopped green onion, glistening with butter", "vessel": "bowl", "avoid": ["meat", "pork", "chicken", "fish", "platter", "side dishes", "raw rice", "flowers"], "checks": [{"q": "Is the main food cooked rice?", "yes": true}, {"q": "Are there pieces of meat or fish with the rice?", "yes": false}, {"q": "Does the rice look raw or dry and uncooked?", "yes": false}]}"""


class BriefError(LLMError):
    pass


def path(root: Path) -> Path:
    return root / "data" / "briefs.json"


def load(root: Path) -> dict:
    p = path(root)
    return json.loads(p.read_text()) if p.exists() else {}


def record(root: Path, dish_id: str, brief: dict) -> None:
    """Merge one brief into the file on disk; never hold the whole file across a run."""
    p = path(root)
    briefs = json.loads(p.read_text()) if p.exists() else {}
    briefs[dish_id] = brief
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(briefs, indent=1, ensure_ascii=False, sort_keys=True) + "\n")


def is_current(brief: dict | None) -> bool:
    return bool(brief) and brief.get("rev", 0) >= BRIEF_REV


def _describe(entry: dict) -> str:
    """The dish as the menu gives it, which is all the brief writer gets to see."""
    name = entry["name"]
    ingredients = dishlib._key_ingredients(entry.get("ingredients", ""), limit=14, dish_name=name)
    tags = entry.get("tags") or []
    label = "vegan" if "vegan" in tags else "vegetarian" if "vegetarian" in tags else "none"
    lines = [f"Dish: {name}"]
    if ingredients:
        lines.append(f"Menu ingredients, top level, in menu order: {', '.join(ingredients)}")
    elif entry.get("special"):
        lines.append("A special from the dining hall's poster: there is no ingredient list, only the name.")
    lines.append(f"Dietary label from the hall: {label}")
    category = entry.get("category") or dishlib.classify(entry)
    if category in ("seafood", "pork", "beef", "lamb", "poultry"):
        lines.append(f"Main protein: {category}")
    return "\n".join(lines)


def write_request(entry: dict) -> str:
    return (
        "Write the brief for one dish from a Stanford dining hall menu. The picture shows this "
        "one dish on its own; the photo style is added for you, so describe only the food.\n\n"
        f"{_describe(entry)}\n\n{_FORMAT}\n\n{_EXAMPLES}"
    )


def unanswerable(brief: dict, verdicts: list[dict]) -> list[str]:
    """The brief's checks the judge failed only ever by saying "unclear".

    A check answered the wrong way is a wrong picture. One no picture could
    answer -- "is the meat in this curry pork?" -- is a question a photo cannot
    settle, and left as it is it keeps the dish on its placeholder for good.
    """
    got: dict[str, set] = {}
    for verdict in verdicts:
        for f in verdict.get("failed", []):
            got.setdefault(f["q"], set()).add(f["got"])
    return [c["q"] for c in brief["checks"] if got.get(c["q"]) == {"unclear"}]


def revise_request(entry: dict, brief: dict, verdicts: list[dict]) -> str:
    seen = []
    for n, verdict in enumerate(verdicts, 1):
        failed = "; ".join(
            f'"{f["q"]}" should be {f["expected"]}, was {f["got"]}' for f in verdict.get("failed", [])
        )
        seen.append(f"- picture {n}: {verdict.get('seen', '?')} -- failed: {failed or 'nothing recorded'}")
    current = {k: brief[k] for k in ("dish", "look", "vessel", "avoid", "checks")}
    unclear = unanswerable(brief, verdicts)
    reword = (
        "These checks could not be answered from any picture -- the inspector said unclear: "
        + "; ".join(f'"{q}"' for q in unclear)
        + ". Reword each so a photo can answer it while testing the same thing, and give them as "
        '"rephrased": {"old question": "new question"}. Their expected answers stay as they are.\n\n'
    ) if unclear else ""
    return (
        "Pictures drawn from this brief failed inspection. Revise the brief so the next picture "
        "gets it right.\n\n"
        f"{_describe(entry)}\n\nCurrent brief:\n{json.dumps(current, ensure_ascii=False)}\n\n"
        "What the inspector saw:\n" + "\n".join(seen) + "\n\n"
        "Steer the image model: name the missed feature earlier and more concretely in look, and "
        "put what appeared wrongly into avoid. The checks stay as they are -- they define a right "
        "picture.\n\n" + reword + _FORMAT
    )


def parse(text: str) -> dict:
    """Validate a model's answer into a brief, or raise BriefError."""
    raw = parse_json(text)
    dish = str(raw.get("dish") or "").strip()
    look = str(raw.get("look") or "").strip().rstrip(".")
    vessel = raw.get("vessel")
    avoid = [str(a).strip() for a in raw.get("avoid") or [] if str(a).strip()]
    checks = []
    for c in raw.get("checks") or []:
        if isinstance(c, dict) and str(c.get("q") or "").strip() and isinstance(c.get("yes"), bool):
            checks.append({"q": str(c["q"]).strip(), "yes": c["yes"]})
    if not dish or not look:
        raise BriefError("brief without dish or look")
    if vessel not in ("plate", "bowl"):
        raise BriefError(f"vessel {vessel!r}")
    if not 1 <= len(checks) <= 6:
        raise BriefError(f"{len(checks)} checks")
    return {"dish": dish, "look": look, "vessel": vessel, "avoid": avoid[:12], "checks": checks}


def _stamp(brief: dict, entry: dict, llm) -> dict:
    return {
        **brief,
        "name": entry["name"],
        "rev": BRIEF_REV,
        "model": llm.name,
        "written_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def write(entry: dict, llm) -> dict:
    brief = parse(llm.ask(write_request(entry), system=SYSTEM))
    return {**_stamp(brief, entry, llm), "revisions": 0}


def revise(entry: dict, brief: dict, verdicts: list[dict], llm) -> dict:
    """A new look and avoid list; the same checks, except unanswerable ones reworded.

    Whatever checks the model sends back are ignored. Only a check that was
    never answered with anything but "unclear" may take new wording, and it
    keeps its expected answer -- what it tests is not the model's to change.
    """
    text = llm.ask(revise_request(entry, brief, verdicts), system=SYSTEM)
    new = parse(text)
    rephrased = parse_json(text).get("rephrased")
    rephrased = rephrased if isinstance(rephrased, dict) else {}
    unclear = set(unanswerable(brief, verdicts))
    new["checks"] = [
        {**c, "q": str(rephrased[c["q"]]).strip()}
        if c["q"] in unclear and str(rephrased.get(c["q"]) or "").strip() else c
        for c in brief["checks"]
    ]
    return {**_stamp(new, entry, llm), "revisions": brief.get("revisions", 0) + 1}


def compose(entry: dict, brief: dict) -> tuple[str, str]:
    """The positive and negative prompt a brief draws with.

    The protein exclusions are still derived from the hall's own labels rather
    than trusted to the model: a vegetarian dish must never be drawn with meat,
    whatever the brief forgot to say.
    """
    positive = f"{brief['dish']}, {brief['look']}, {dishlib.photo_style(brief['vessel'] == 'bowl')}"
    negative, seen = [], set()
    for term in [*brief.get("avoid", []), *dishlib.protein_exclusions(entry), dishlib.NEGATIVE_PROMPT]:
        if term.lower() not in seen:
            seen.add(term.lower())
            negative.append(term)
    return positive, ", ".join(negative)
