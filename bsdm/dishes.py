"""Dish identity, protein classification, and image prompting.

Dishes repeat heavily across halls and across weeks ("Seasonal Steamed
Vegetables" shows up at nearly every hall), so everything expensive -- above all
image generation -- is keyed on a normalized name rather than on the day it was
served.
"""

from __future__ import annotations

import hashlib
import re

# Entries whose "ingredients" are a placeholder rather than a recipe. Drawing a
# specific bowl of soup for "Soup of the Day" would invent a meal that isn't
# being served, so these get a category icon instead of a generated image.
_PLACEHOLDER_RE = re.compile(r"^\s*(chef'?s choice|see |ask )", re.I)

# Build-your-own counters. Their "ingredients" are a list of toppings on offer,
# so reading a protein out of them is misleading -- a salad bar that stocks
# grilled chicken is not a chicken dish. These are classified from the name only,
# which still lets "Burger Bar" read as beef.
_COUNTER_RE = re.compile(r"\b(bar|station|counter)\s*(\([^)]*\))?\s*$", re.I)

_SMART_QUOTES = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-"})

# Protein keywords in two tiers. Naming an animal ("turkey") outranks naming a
# dish form that merely implies one ("burger"), so "Turkey Burger" is poultry and
# "Greek Chicken Gyro Meat" is poultry rather than lamb.
_PRIMARY: dict[str, list[str]] = {
    "seafood": [
        "fish", "cod", "salmon", "tuna", "tilapia", "halibut", "snapper", "trout",
        "mahi", "pollock", "swai", "catfish", "sardine", "shrimp", "prawn", "crab",
        "lobster", "clam", "mussel", "oyster", "scallop", "squid", "calamari",
        "octopus", "seafood", "surimi",
    ],
    "pork": [
        "pork", "bacon", "ham", "prosciutto", "pancetta", "capicola", "guanciale",
    ],
    "beef": [
        "beef", "steak", "brisket", "veal", "oxtail", "tri-tip", "short rib",
        "ribeye", "sirloin", "chuck roast",
    ],
    "lamb": ["lamb", "mutton", "goat"],
    "poultry": ["chicken", "turkey", "duck", "poultry", "cornish hen", "quail"],
}

_SECONDARY: dict[str, list[str]] = {
    "beef": [
        "burger", "hamburger", "cheeseburger", "meatball", "meatloaf", "bolognese",
        "barbacoa", "carne asada", "ropa vieja", "nikujaga", "bulgogi", "pastrami",
        "corned beef", "patty melt", "philly cheesesteak",
    ],
    "pork": [
        "chorizo", "carnitas", "pepperoni", "salami", "andouille", "kielbasa",
        "al pastor", "sausage", "bratwurst", "carnita",
    ],
    "lamb": ["gyro", "merguez", "shawarma"],
    "seafood": ["ceviche", "po'boy", "poboy", "gumbo", "chowder"],
    "poultry": ["schnitzel"],
}

# Bases, sauces and seasonings that flavour a dish without making it a meat dish.
# "chicken soup base" in a rice pilaf must not mark it as poultry.
_FLAVORING_RE = re.compile(
    r"\b("
    r"(chicken|beef|pork|veal|fish|ham|lobster|clam|shrimp)\s+"
    r"(soup\s+)?(base|stock|broth|bouillon|consomm[e\u00e9]|essence|powder|fat|flavor(ing)?)"
    r"|anchov(y|ies)|fish sauce|oyster sauce|shrimp paste|bonito|dashi"
    r"|worcestershire|lard|gelatin|rennet|natural flavor(ing)?s?"
    r")\b",
    re.I,
)

_CATEGORY_LABEL = {
    "seafood": "Seafood",
    "pork": "Pork",
    "beef": "Beef",
    "lamb": "Lamb",
    "poultry": "Poultry",
    "vegan": "Vegan",
    "vegetarian": "Vegetarian",
    "other": "Other",
}

# Icons for dishes we deliberately don't illustrate.
_STATION_ICON = [
    (re.compile(r"\bsoup\b", re.I), "soup"),
    (re.compile(r"\b(burger|grill)\b", re.I), "grill"),
    (re.compile(r"\b(panini|sandwich|deli)\b", re.I), "sandwich"),
    (re.compile(r"\b(salad|greens|performance bar)\b", re.I), "salad"),
    (re.compile(r"\b(bread|bakery|pastry)\b", re.I), "bread"),
    (re.compile(r"\b(pizza)\b", re.I), "pizza"),
    (re.compile(r"\b(dessert|cake|cookie|ice cream)\b", re.I), "dessert"),
    (re.compile(r"\b(pasta|noodle)\b", re.I), "pasta"),
]


def normalize(name: str) -> str:
    """Fold a dish name to its cache key form."""
    n = name.translate(_SMART_QUOTES).lower()
    n = re.sub(r"[^a-z0-9]+", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def dish_id(name: str) -> str:
    return hashlib.sha1(normalize(name).encode()).hexdigest()[:12]


def is_placeholder(dish) -> bool:
    """True when the menu gives a station name instead of an actual recipe."""
    ing = _get(dish)("ingredients", "") or ""
    return not ing.strip() or bool(_PLACEHOLDER_RE.match(ing))


def _get(dish):
    if isinstance(dish, dict):
        return lambda k, d=None: dish.get(k, d)
    return lambda k, d=None: getattr(dish, k, d)


def _tags(dish) -> list[str]:
    return _get(dish)("tags", []) or []


def _top_level_ingredients(ingredients: str) -> str:
    """Ingredients with nested parentheticals and flavouring bases removed.

    The menu nests sub-recipes several levels deep, so the anchovies inside
    "caesar dressing (mayonnaise, ..., anchovy, ...)" describe the dressing, not
    the salad. Only the outer list says what the dish actually is.
    """
    out, depth = [], 0
    for ch in ingredients or "":
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(ch)
    return _FLAVORING_RE.sub(" ", "".join(out))


def _earliest_match(haystack: str, tier: dict[str, list[str]]) -> str | None:
    """Category of the keyword appearing earliest in `haystack`, if any.

    Earliest wins so "Chicken and Shrimp Jambalaya" reads as poultry: the head
    protein is normally named first.
    """
    best_pos, best_cat = None, None
    for category, keywords in tier.items():
        for kw in keywords:
            m = re.search(rf"\b{re.escape(kw)}", haystack)
            if m and (best_pos is None or m.start() < best_pos):
                best_pos, best_cat = m.start(), category
    return best_cat


def classify(dish) -> str:
    """Bucket a dish for the meat-first highlighting.

    The hall's own vegan/vegetarian icons are authoritative and are checked
    first, so a vegetarian dish named "Chick'n Tenders" is never read as meat.
    Beyond that, the four passes run from most to least reliable evidence.
    """
    tags = _tags(dish)
    if "vegan" in tags:
        return "vegan"
    if "vegetarian" in tags:
        return "vegetarian"

    get = _get(dish)
    name = (get("name", "") or "").translate(_SMART_QUOTES).lower()
    ing = _top_level_ingredients((get("ingredients", "") or "").translate(_SMART_QUOTES).lower())

    passes = [(name, _PRIMARY), (ing, _PRIMARY), (name, _SECONDARY), (ing, _SECONDARY)]
    if _COUNTER_RE.search(name):
        passes = [(name, _PRIMARY), (name, _SECONDARY)]

    for haystack, tier in passes:
        if category := _earliest_match(haystack, tier):
            return category
    return "other"


def is_meat(dish) -> bool:
    return classify(dish) in {"seafood", "pork", "beef", "lamb", "poultry"}


def category_label(category: str) -> str:
    return _CATEGORY_LABEL.get(category, "Other")


def station_icon(dish) -> str:
    name = _get(dish)("name", "") or ""
    for pattern, icon in _STATION_ICON:
        if pattern.search(name):
            return icon
    return "plate"


def _key_ingredients(ingredients: str, limit: int = 12) -> list[str]:
    """Pull the leading, top-level ingredients out of the menu's ingredient blob.

    The source text nests parentheticals several levels deep ("cheese sauce
    (cheddar cheese (milk, cultures), ...)"); only the outer items describe what
    the dish looks like, so nested detail is dropped.
    """
    # Some entries put an exclusion notice in the ingredients field -- Casper's
    # no-allium counters list every allium they leave out. Read naively that
    # becomes "made with onion, shallots, leeks", which is exactly backwards, so
    # any ** -delimited segment that opens with a negation is dropped.
    segments = re.split(r"\*\*+", ingredients or "")
    text = " ".join(
        seg for seg in segments
        if not re.match(r"\s*(no|not|contains no|free of|without)\b", seg, re.I)
    )
    out, depth, buf = [], 0, []
    for ch in text:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            out.append("".join(buf))
            buf = []
            continue
        if depth == 0:
            buf.append(ch)
    out.append("".join(buf))

    skipped = re.compile(
        r"^(salt|pepper|black pepper|water|sugar|spices?|seasoning|oil|canola|"
        r"olive oil|canola/olive oil blend|vegetable oil|natural flavors?|"
        r"citric acid|xanthan gum|preservatives?)$",
        re.I,
    )
    seen, clean = set(), []
    for item in out:
        item = re.sub(r"\s+", " ", item).strip(" .;:-")
        if not item or len(item) > 40 or skipped.match(item):
            continue
        low = item.lower()
        if low in seen:
            continue
        seen.add(low)
        clean.append(item)
        if len(clean) >= limit:
            break
    return clean


def image_prompt(dish) -> str:
    """Build the positive prompt for one dish."""
    get = _get(dish)
    name = get("name", "")
    key = _key_ingredients(get("ingredients", ""), limit=8)
    tags = _tags(dish)

    parts = [f"{name}, a dining hall dish"]
    if key:
        parts.append("made with " + ", ".join(key))
    if "vegan" in tags:
        parts.append("plant-based, no meat, no dairy")
    elif "vegetarian" in tags:
        parts.append("vegetarian, no meat")

    parts.append(
        "appetizing food photography, plated on a simple white ceramic plate, "
        "overhead three-quarter view, soft natural window light, shallow depth "
        "of field, clean neutral background, sharp focus, high detail"
    )
    return ", ".join(parts)


NEGATIVE_PROMPT = (
    "text, words, letters, watermark, signature, logo, menu, label, "
    "hands, people, person, fingers, cutlery clutter, messy, blurry, "
    "lowres, deformed, distorted, oversaturated, cartoon, illustration, "
    "3d render, plastic, fake looking, duplicate plates"
)
