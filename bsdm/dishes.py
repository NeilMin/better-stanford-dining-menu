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
        "al pastor", "sausage", "bratwurst", "carnita", "spam",
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
    # Condiments named after an animal they do not contain. Left in the prompt,
    # "A-1 steak sauce" in a vegetable stir-fry puts sliced steak on the plate.
    r"|(a-?1\s+)?steak sauce|chicken salt"
    r"|worcestershire|lard|gelatin|rennet|natural flavor(ing)?s?"
    r")\b",
    re.I,
)

# Seasonings, cooking media and thickeners. They belong in a recipe but not in a
# photograph, and every one of them crowds out an ingredient you could actually
# see -- the prompt keeps only the first eight.
_INVISIBLE_RE = re.compile(
    r"^\s*("
    r"(kosher |sea |table )?salt|(black |white |ground )?pepper(corn)?s?|sugar|water|ice"
    # Any oil, however the kitchen spells the blend ("canola/olive oil blend").
    r"|[\w/ ]*oils?( blend)?|cooking spray|butter spray"
    r"|corn ?starch|arrowroot|xanthan gum|flour|baking (powder|soda)|yeast|msg"
    r"|(white |red |rice |apple cider |balsamic )?vinegar|citric acid|lemon juice|lime juice|orange juice|pineapple juice"
    r"|spices?|seasoning( blend| mix)?|salt and pepper|garlic powder|onion powder"
    r"|preservatives?|emulsifiers?|food colou?ring|marinade|dredge|glaze|batter"
    r"|(soy|pea|wheat) protein( isolate)?|wheat gluten|gluten|vital wheat gluten"
    r"|(potato|tapioca|corn|modified food) starch|(yellow |white )?corn flour|rice flour|maltodextrin|dextrin"
    r"|tricalcium phosphate|leavening agent|paprika extract colou?r|extract colou?r"
    r"|disodium dihydrogen pyrophosphate|sodium bicarbonate|dextrose|cream of tartar|guar gum"
    r"|(sodium|calcium|potassium|disodium|monocalcium|aluminum)\s+[\w\s]+"
    r"|sorbitol|sorbic acid|lactic acid|ascorbic acid|fumaric acid|propionic acid|benzoic acid"
    r"|hydrolyzed\s+[\w\s]*protein"
    r"|[\w\s]*gum arabic|[\w\s]*cellulose gum|[\w\s]*gellan gum|[\w\s]*konjac gum|locust bean gum"
    r"|(soy|sunflower)?\s*lecithin|l-cysteine(\s+hydrochloride)?"
    r"|(spice|rosemary|carrot)\s+extract(ive)?s?|natural flavorings?"
    r")\s*$",
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
    "station": "Station",
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

_STATION_CONTAINER_RE = re.compile(
    r"\b(burger bar|hot dog bar|breakfast taco bar|taco bar|baked potato bar|chili bar)\b"
    r"|allergy friendly burger bar",
    re.I,
)


def is_station_container(dish) -> bool:
    """True when an item is a station/assembly counter container (e.g. Burger Bar)
    rather than a finished, standalone recipe.
    """
    get = _get(dish)
    name = (get("name", "") or "").translate(_SMART_QUOTES).strip()
    ing = (get("ingredients", "") or "").translate(_SMART_QUOTES).strip()
    if not name:
        return False
    if _STATION_CONTAINER_RE.search(name):
        return True
    if not ing and re.search(r"\b(bar|station)\b", name, re.I):
        return True
    return False


def normalize(name: str) -> str:
    """Fold a dish name to its cache key form."""
    n = name.translate(_SMART_QUOTES).lower()
    n = re.sub(r"[^a-z0-9]+", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def dish_id(name: str) -> str:
    return hashlib.sha1(normalize(name).encode()).hexdigest()[:12]


def is_placeholder(dish) -> bool:
    """True when the menu gives a station name instead of an actual recipe."""
    if is_station_container(dish):
        return True
    # Folded first, like every other read of source text in this module: R&DE
    # writes both apostrophes, and "Chef’s Choice" left unfolded reads as a
    # recipe and earns the soup of the day a picture of one specific soup.
    ing = (_get(dish)("ingredients", "") or "").translate(_SMART_QUOTES)
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
    if is_station_container(dish):
        return "station"

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


def _key_ingredients(ingredients: str, limit: int = 12, dish_name: str = "") -> list[str]:
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

    out, buf, depth = [], [], 0
    for ch in text:
        if ch in "([{":
            depth += 1
            continue
        if ch in ")]}":
            depth = max(0, depth - 1)
            continue
        if depth:
            continue
        if ch == ",":
            out.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    out.append("".join(buf))

    is_saffron_dish = bool(re.search(r"\bsaffron\b", dish_name, re.I))
    seen, clean = set(), []
    for item in out:
        item = re.sub(r"\s+", " ", item).strip(" .;:-")
        item = re.sub(r"^(marinade|dredge|glaze|batter)\s+", "", item, flags=re.I)
        if not item or len(item) > 40 or _INVISIBLE_RE.match(item):
            continue
        # The same rule that stops "oyster sauce" from marking a dish as seafood
        # has to stop it reaching the prompt, or the picture grows an oyster.
        if _FLAVORING_RE.search(item):
            continue
        low = item.lower()
        if is_saffron_dish and low in ("dill", "peas", "green peas"):
            continue
        if low == "saffron":
            item = "red saffron threads"
            low = item.lower()
        if low in seen:
            continue
        seen.add(low)
        clean.append(item)
        if len(clean) >= limit:
            break
    return clean


def is_bowl(dish) -> bool:
    """True when the dish is served in a bowl rather than plated flat."""
    name = _get(dish)("name", "")
    return bool(re.search(r"\b(bowls?|soups?|chowders?|ramen|pho|bisque|etouffee|étouffée)\b", name, re.I))


def _hero_protein_phrase(dish) -> str | None:
    name = (_get(dish)("name", "") or "").lower()
    if "tempeh" in name:
        return "crispy bite-sized golden-brown glazed tempeh cubes, sticky spicy-sweet red gochujang glaze, toasted sesame seeds and chopped scallions"
    if "tender" in name or "tenders" in name:
        if any(w in name for w in ("plant", "vegan", "vegetarian", "forward")):
            return (
                "crispy golden-brown breaded plant-based tenders with crunchy panko coating, "
                "tender flaky interior, served with dipping sauce on the side"
            )
        return (
            "crispy golden-brown fried buttermilk chicken tenders with rustic irregular craggy coating, "
            "crunchy textured exterior and tender juicy white meat interior, served with dipping sauce on the side"
        )
    if "thai basil eggplant" in name or ("eggplant" in name and "basil" in name):
        return (
            "stir-fried tender purple Chinese eggplant slices with vibrant glossy skin, "
            "savory garlic Thai basil sauce, fresh green basil leaves, and sliced red bell peppers"
        )
    if "bourguignon" in name and ("mushroom" in name or "wild mushroom" in name):
        return "rich braised wild mushrooms, cremini and shiitake in a glossy deep red wine sauce with pearl onions, carrots, and fresh thyme"
    if "etouffee" in name or "étouffée" in name:
        if "mushroom" in name:
            return (
                "rich savory Louisiana mushroom etouffee with tender sautéed sliced cremini mushrooms "
                "in a thick glossy golden-brown roux sauce, garnished with finely chopped fresh parsley"
            )
    if "zucchini" in name and ("lemon" in name or "herb" in name):
        return (
            "tender sautéed green zucchini medallions with golden-brown caramelized sear, "
            "tender cooked courgette squash with pale tender center and dark green skin, "
            "tossed with minced garlic and aromatic fresh thyme and oregano herbs, glistening extra virgin olive oil, "
            "a fresh yellow lemon wedge resting on the side"
        )
    if "lemon herb rice" in name:
        return (
            "fluffy aromatic yellow basmati rice tinted golden with turmeric, "
            "speckled with finely chopped fresh green dill, mint, and parsley, glistening with olive oil and lemon zest"
        )
    if "tabouli" in name or "tabbouleh" in name:
        return (
            "vibrant fresh Mediterranean tabouli salad loaded with finely chopped fresh parsley and mint, "
            "tossed with tender bulgur wheat, diced red tomatoes, and cucumbers in lemon olive oil dressing"
        )
    if "pickled red onion" in name:
        return (
            "vibrant magenta-pink thinly sliced pickled red onion ribbons, glistening in spiced vinegar pickling brine"
        )
    if "butternut squash soup" in name:
        return (
            "rich velvety smooth creamy golden-orange butternut squash soup, "
            "garnished with a delicate swirl of cream and fresh herbs"
        )
    if "tex-mex salad" in name:
        return (
            "crisp colorful chopped Tex-Mex salad with fresh romaine lettuce, black beans, "
            "sweet golden corn kernels, diced red bell peppers, cherry tomatoes, and fresh cilantro"
        )
    if "lasagna" in name and any(w in name for w in ("vegetable", "veggie", "spinach", "mushroom")):
        return (
            "layers of tender pasta sheets filled with creamy ricotta, melted mozzarella, "
            "vibrant sautéed spinach, mushrooms, zucchini, rich marinara sauce, and golden bubbling cheese crust"
        )
    if "fajita" in name or "fajitas" in name:
        if any(w in name for w in ("chicken", "poultry")):
            return (
                "tender seasoned grilled chicken breast strips with appetizing charred grill marks, "
                "tossed with sautéed sliced red and green bell peppers and caramelized onions"
            )
        if any(w in name for w in ("beef", "steak", "carne")):
            return (
                "tender seasoned grilled beef steak strips with caramelized edges, "
                "tossed with sautéed sliced red and green bell peppers and caramelized onions"
            )
        return (
            "tender seasoned grilled meat strips with appetizing charred edges, "
            "tossed with sautéed sliced red and green bell peppers and caramelized onions"
        )
    if ("hot dog" in name or "hotdog" in name or "frankfurter" in name) and "bun" not in name:
        return (
            "a classic juicy all-beef hot dog nestled in a soft warm bakery bun, "
            "with a neat swirl of yellow mustard"
        )

    category = classify(dish)
    if category not in ("pork", "beef", "poultry", "seafood", "lamb"):
        return None
    if category == "pork":
        if "vindaloo" in name:
            return "tender simmered pork chunks in rich spicy and tangy red vindaloo curry sauce with tender potatoes"
        if "bulgogi" in name:
            return "tender stir-fried thinly sliced pork in sweet savory marinade with scallions"
        if "carnitas" in name or "al pastor" in name:
            return "tender shredded seasoned pork with crispy edges"
        if "bacon" in name:
            return "crispy browned bacon strips"
        if "spam" in name:
            if "musubi" in name:
                return (
                    "pan-fried caramelized Spam luncheon meat slices with crispy browned edges and sweet soy glaze, "
                    "a sunny-side-up fried egg with golden yolk, over fluffy steamed white rice, "
                    "garnished with furikake seasoning, toasted sesame seeds, and fresh sliced green scallions"
                )
            return "crispy caramelized pan-fried Spam slices with sweet savory glaze and browned edges"
        return "tender cooked pork cuts, succulent meat texture, browned edges"
    if category == "beef":
        if "bourguignon" in name:
            return "tender braised beef chunks in rich glossy red wine sauce with pearl onions, sautéed mushrooms, and fresh herbs"
        if "bulgogi" in name:
            return "tender stir-fried thinly sliced beef in sweet savory marinade with onions and scallions"
        if "short rib" in name or "rib" in name:
            return "tender grilled bone-in kalbi beef short ribs with caramelized teriyaki glaze"
        if "steak" in name:
            return "juicy sliced seared steak with rich caramelized crust"
        if "burger" in name:
            return "juicy grilled beef patty with melted cheese"
        return "tender cooked beef, succulent meat texture, rich caramelized sear"
    if category == "poultry":
        if "tandoori" in name:
            return "roasted tandoori chicken with vibrant red-orange spice crust, charred edges, and aromatic herbs"
        if "roast" in name or "grilled" in name:
            return "juicy grilled or roasted chicken, golden skin, tender meat texture"
        if "crispy" in name or "fried" in name:
            return "crispy golden fried chicken, crunchy coating"
        if "tikka" in name or "curry" in name:
            return "tender chicken pieces in rich fragrant spiced sauce"
        return "tender cooked chicken, succulent poultry texture"
    if category == "seafood":
        return "delicate flaky fish fillet or fresh seafood, glistening glaze"
    if category == "lamb":
        return "tender seasoned lamb, fragrant spices, succulent meat texture"
    return None


def image_prompt(dish) -> str:
    """Build the positive prompt for one dish."""
    get = _get(dish)
    name = get("name", "")
    key = _key_ingredients(get("ingredients", ""), limit=8, dish_name=name)
    tags = _tags(dish)

    parts = [name]
    if hero := _hero_protein_phrase(dish):
        parts.append(hero)
    if key:
        parts.append("made with " + ", ".join(key))
    if "vegan" in tags:
        parts.append("plant-based, no meat, no dairy")
    elif "vegetarian" in tags:
        parts.append("vegetarian, no meat")
    if re.search(r"\bmusubi\b", name, re.I):
        parts.append("a pair of two chopsticks resting beside the bowl")

    vessel = "served in a simple white ceramic bowl" if is_bowl(dish) else "plated on a simple white ceramic plate"
    parts.append(
        f"appetizing food photography, {vessel}, "
        "overhead three-quarter view, centered composition with generous empty margin around the plate, "
        "soft natural window light, shallow depth of field, clean neutral background, sharp focus, high detail"
    )
    return ", ".join(parts)


NEGATIVE_PROMPT = (
    "text, words, letters, watermark, signature, logo, menu, label, "
    "hands, people, person, fingers, cutlery clutter, extra chopsticks, "
    "three chopsticks, duplicate spoons, extra spoons, deformed spoons, messy, blurry, "
    "lowres, deformed, distorted, oversaturated, cartoon, illustration, "
    "3d render, plastic, fake looking, duplicate plates, multiple dishes, table spread, feast"
)

# What each protein looks like on a plate, phrased for the negative prompt.
_PROTEIN_NEGATIVE = {
    "seafood": "fish fillet, shrimp, prawns, shellfish, crawfish, crayfish, crab, lobster",
    "pork": "pork, bacon, ham, pork belly",
    "beef": "beef, sliced steak, ground beef",
    "lamb": "lamb, mutton",
    "poultry": "chicken, chicken breast, turkey",
}


def negative_prompt(dish) -> str:
    """The negative prompt for one dish, naming the proteins it must not show.

    SDXL conditions on CLIP, which has no way to represent "no meat" -- a positive
    prompt saying so is read as a prompt about meat. Steering a protein out of a
    picture only works from the negative side, so the dish's own classification
    is turned into the list of things to exclude: everything, for a dish the hall
    labels vegetarian, and the other four proteins for a dish that has one, which
    is what stops grilled chicken from being plated as steak.
    """
    category = classify(dish)
    name = _get(dish)("name", "")
    if category in ("vegan", "vegetarian") or (
        category == "other" and re.search(r"\b(vegetable|veggie|plant-based)\b", name, re.I)
    ):
        exclude = list(_PROTEIN_NEGATIVE.values()) + ["meat"]
    elif category in _PROTEIN_NEGATIVE:
        exclude = [v for k, v in _PROTEIN_NEGATIVE.items() if k != category]
    else:
        # "other" is genuinely unknown -- a dish with no icon and no protein
        # keyword may still arrive with meat in it, so nothing is excluded.
        exclude = []

    name = _get(dish)("name", "")
    if re.search(r"\bsaffron\b", name, re.I):
        exclude.extend(["dill", "peas", "green peas", "star anise"])
    if re.search(r"\bzucchini\b", name, re.I) and re.search(r"\blemon\b", name, re.I):
        exclude.extend([
            "sliced lemons", "lemon slices", "lemon wheels", "citrus slices", "lime slices",
            "citrus pulp", "sliced limes", "cucumbers", "pickles", "yogurt", "tzatziki",
            "sour cream", "dip", "sauce bowl", "white cream",
        ])
    if re.search(r"\brice\b", name, re.I) and re.search(r"\blemon\b", name, re.I):
        exclude.extend(["sliced lemons", "lemon wheels", "citrus slices", "whole lemons"])
    if re.search(r"\bhot\s*dogs?\b", name, re.I) and "bun" not in name.lower():
        exclude.extend(["ridges", "tire tread", "sliced meat", "shredded meat", "deformed sausage", "second sausage", "double sausage", "split casing", "corn", "corn kernels", "yellow sludge", "cheese sauce", "mayonnaise"])
    if re.search(r"\bfajitas?\b", name, re.I):
        exclude.extend(["burrito", "tortilla wrap", "taco", "noodles", "pasta", "soup"])

    if not exclude:
        return NEGATIVE_PROMPT
    return ", ".join(exclude) + ", " + NEGATIVE_PROMPT


# Bumped whenever the prompt rules change, so already-drawn images can be told
# apart from ones drawn under the current rules and redrawn in priority order.
PROMPT_REV = 6
