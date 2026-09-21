"""Dish identity, protein classification, and prompting.

Classification is the one place in the project where being wrong is expensive
and silent at the same time: it decides the meat-first order, the badge on the
card, and what the negative prompt steers out of the picture. A vegetable dish
read as beef comes back plated with steak, and nothing reports it.
"""

from __future__ import annotations

import pytest

from bsdm import dishes as dishlib


def d(name, ingredients="", tags=()):
    return {"name": name, "ingredients": ingredients, "tags": list(tags)}


class TestIdentity:
    def test_normalize_folds_case_and_punctuation(self):
        assert dishlib.normalize("Chef's  Choice -- Soup!") == "chef s choice soup"

    def test_normalize_folds_smart_quotes(self):
        """The menu app emits both, sometimes for the same dish in the same
        week. Two spellings of one name would mean two ids and two pictures."""
        assert dishlib.normalize("Chef’s Choice") == dishlib.normalize("Chef's Choice")
        assert dishlib.normalize("Mac — Cheese") == dishlib.normalize("Mac - Cheese")

    def test_dish_id_is_short_stable_hex(self):
        assert dishlib.dish_id("Tofu Scramble") == dishlib.dish_id("tofu   scramble")
        assert len(dishlib.dish_id("Tofu Scramble")) == 12
        int(dishlib.dish_id("Tofu Scramble"), 16)

    def test_different_dishes_get_different_ids(self):
        assert dishlib.dish_id("Beef Stew") != dishlib.dish_id("Bean Stew")


class TestPlaceholder:
    @pytest.mark.parametrize("ingredients", ["", "   ", "chef's choice", "Chef’s Choice soup",
                                             "See attendant", "ask the chef"])
    def test_a_station_name_instead_of_a_recipe(self, ingredients):
        assert dishlib.is_placeholder(d("Soup of the Day", ingredients))

    def test_a_real_recipe_is_not(self):
        assert not dishlib.is_placeholder(d("Tomato Soup", "tomato, cream, basil"))


class TestClassify:
    def test_the_halls_own_icons_are_authoritative(self):
        """A vegetarian dish named "Chick'n Tenders" is not poultry, and the
        hall's own label is better evidence than anything in the name."""
        assert dishlib.classify(d("Chick'n Tenders", "soy protein", ["vegetarian"])) == "vegetarian"
        assert dishlib.classify(d("Beef-Style Seitan", "wheat gluten", ["vegan"])) == "vegan"

    def test_naming_an_animal_outranks_naming_a_dish_form(self):
        assert dishlib.classify(d("Turkey Burger")) == "poultry"
        assert dishlib.classify(d("Greek Chicken Gyro Meat")) == "poultry"

    def test_the_head_protein_is_named_first(self):
        assert dishlib.classify(d("Chicken and Shrimp Jambalaya")) == "poultry"
        assert dishlib.classify(d("Shrimp and Chicken Jambalaya")) == "seafood"

    def test_a_secondary_keyword_still_lands(self):
        assert dishlib.classify(d("Bulgogi")) == "beef"
        assert dishlib.classify(d("Chorizo Hash")) == "pork"
        assert dishlib.classify(d("Spam Musubi Bowl")) == "pork"
        assert dishlib.is_meat(d("Spam Musubi Bowl"))

    def test_the_name_outranks_the_ingredients(self):
        assert dishlib.classify(d("Chicken Curry", "coconut milk, beef stock")) == "poultry"

    def test_nested_sub_recipes_describe_the_sauce_not_the_dish(self):
        """The anchovies inside "caesar dressing (...)" are in the dressing.
        Only the outer list says what is on the plate."""
        salad = d("Caesar Salad", "romaine, caesar dressing (mayonnaise, anchovy, garlic)")
        assert dishlib.classify(salad) == "other"

    def test_a_flavouring_base_is_not_a_protein(self):
        assert dishlib.classify(d("Rice Pilaf", "rice, chicken soup base, onion")) == "other"
        assert dishlib.classify(d("Gravy", "flour, beef stock")) == "other"

    def test_a_condiment_named_after_an_animal_it_does_not_contain(self):
        """"vegetarian oyster sauce" and "A-1 steak sauce" both name a protein
        they have none of. This was wired into classify() only, once, and
        vegetable dishes came back plated with steak."""
        stir_fry = d("Vegetable Stir Fry", "broccoli, vegetarian oyster sauce, A-1 steak sauce")
        assert dishlib.classify(stir_fry) == "other"

    def test_a_counter_is_read_from_its_name_alone(self):
        """A salad bar that stocks grilled chicken is not a chicken dish -- its
        "ingredients" are a list of toppings on offer, not a recipe."""
        assert dishlib.classify(d("Salad Bar", "grilled chicken, lettuce, tomato")) == "other"

    def test_a_station_container_reads_as_station_not_meat(self):
        """Burger Bar is a station container, not a single beef dish."""
        assert dishlib.classify(d("Burger Bar")) == "station"
        assert dishlib.is_station_container(d("Burger Bar"))
        assert not dishlib.is_meat(d("Burger Bar"))

    def test_unknown_is_unknown_rather_than_guessed(self):
        assert dishlib.classify(d("Craveable Grains", "farro, herbs")) == "other"

    @pytest.mark.parametrize("category,name", [
        ("seafood", "Baked Cod"), ("pork", "Carnitas Tacos"), ("beef", "Brisket"),
        ("lamb", "Lamb Tagine"), ("poultry", "Roast Duck"),
    ])
    def test_every_protein_bucket_is_reachable(self, category, name):
        assert dishlib.classify(d(name)) == category
        assert dishlib.is_meat(d(name))

    def test_is_meat_is_false_for_the_rest(self):
        assert not dishlib.is_meat(d("Steamed Broccoli", "broccoli"))
        assert not dishlib.is_meat(d("Mystery Grain Bowl"))

    def test_classify_reads_objects_as_well_as_dicts(self):
        """catalog entries are dicts; bsdm.scrape.Dish is a dataclass. Both go
        through classify() on different paths."""
        from bsdm.scrape import Dish
        assert dishlib.classify(Dish(name="Roast Chicken")) == "poultry"


class TestStationIcon:
    @pytest.mark.parametrize("name,icon", [
        ("Soup of the Day", "soup"), ("Burger Bar", "grill"), ("Panini Station", "sandwich"),
        ("Composed Salad", "salad"), ("Bakery Counter", "bread"), ("Pizza Station", "pizza"),
        ("Dessert Bar", "dessert"), ("Pasta Bar", "pasta"),
    ])
    def test_known_counters(self, name, icon):
        assert dishlib.station_icon(d(name)) == icon

    def test_anything_else_gets_a_plate(self):
        assert dishlib.station_icon(d("Chana Masala")) == "plate"


class TestKeyIngredients:
    def prompt_of(self, ingredients, name="Test Dish", tags=()):
        return dishlib.image_prompt(d(name, ingredients, tags))

    def test_leads_with_the_name(self):
        prompt = self.prompt_of("", "Tofu Scramble")
        assert prompt.startswith("Tofu Scramble")
        assert "a dining hall dish" not in prompt

    def test_keeps_the_visible_ingredients(self):
        assert "made with chicken breast, rice" in self.prompt_of("chicken breast, rice")

    @pytest.mark.parametrize("hidden", [
        "salt", "water", "canola/olive oil blend", "corn starch", "spices",
        "garlic powder", "citric acid", "cooking spray",
    ])
    def test_drops_what_a_photograph_cannot_show(self, hidden):
        assert hidden not in self.prompt_of(f"rice, {hidden}")

    def test_drops_nested_detail(self):
        got = self.prompt_of("cheese sauce (cheddar cheese (milk, cultures), cream)")
        assert "made with cheese sauce," in got and "cultures" not in got

    def test_drops_flavourings_for_the_same_reason_classify_does(self):
        """The rule that stops "oyster sauce" marking a dish as seafood has to
        stop it reaching the prompt too, or the picture grows an oyster."""
        got = self.prompt_of("broccoli, oyster sauce, A-1 steak sauce, chicken base")
        assert "oyster" not in got and "steak" not in got and "chicken base" not in got

    def test_drops_an_exclusion_notice(self):
        """Casper's no-allium counters list every allium they leave out. Read
        naively that becomes "made with onion, shallots", which is backwards."""
        got = self.prompt_of("**No onion, no garlic** tofu, rice, ginger")
        assert "made with tofu, rice, ginger" in got

    def test_deduplicates(self):
        assert self.prompt_of("rice, Rice, rice").count("rice") == 1

    def test_keeps_only_the_first_eight(self):
        many = ", ".join(f"item{i}" for i in range(20))
        assert "item7" in self.prompt_of(many) and "item8" not in self.prompt_of(many)

    def test_says_plant_based_for_a_vegan_dish(self):
        assert "plant-based, no meat, no dairy" in self.prompt_of("tofu", tags=["vegan"])

    def test_saffron_rice_emphasizes_threads_and_drops_obscuring_herbs(self):
        saffron_dish = d("Saffron Rice", "rice, onions, dill, saffron, canola/olive oil blend, salt", tags=["vegan"])
        prompt = dishlib.image_prompt(saffron_dish)
        assert "red saffron threads" in prompt
        assert "dill" not in prompt

    def test_pork_bulgogi_anchors_hero_protein(self):
        pork_bulgogi = d("Pork Bulgogi", "pork, mushroom, onion, kale")
        prompt = dishlib.image_prompt(pork_bulgogi)
        assert "tender stir-fried thinly sliced pork in sweet savory marinade with scallions" in prompt
        assert "centered composition with generous empty margin around the plate" in prompt

    def test_beef_bulgogi_anchors_hero_protein(self):
        beef_bulgogi = d("Beef Bulgogi", "beef, scallions, onion")
        prompt = dishlib.image_prompt(beef_bulgogi)
        assert "tender stir-fried thinly sliced beef in sweet savory marinade with onions and scallions" in prompt


class TestVessel:
    def test_bowl_dishes_detected(self):
        assert dishlib.is_bowl(d("Spam Musubi Bowl"))
        assert dishlib.is_bowl(d("Grilled Teriyaki Chicken Protein Bowl"))
        assert dishlib.is_bowl(d("Tomato Basil Soup"))
        assert not dishlib.is_bowl(d("Steamed Broccoli"))
        assert not dishlib.is_bowl(d("Saffron Rice"))

    def test_prompt_uses_bowl_vessel(self):
        assert "served in a simple white ceramic bowl" in dishlib.image_prompt(d("Spam Musubi Bowl"))
        assert "a pair of two chopsticks" in dishlib.image_prompt(d("Spam Musubi Bowl"))
        assert "plated on a simple white ceramic plate" in dishlib.image_prompt(d("Saffron Rice"))


class TestNegativePrompt:
    def test_a_dish_never_excludes_its_own_protein(self):
        """SDXL conditions on CLIP, which has no negation, so the only way to
        steer a protein out is from the negative side -- and steering out the
        one the dish actually has would be a picture of the wrong dinner."""
        for category, words in dishlib._PROTEIN_NEGATIVE.items():
            got = dishlib.negative_prompt(d(f"{category} dish", tags=[]) | {"name": words.split(",")[0]})
            head = words.split(",")[0]
            assert head not in got.split(dishlib.NEGATIVE_PROMPT)[0], category

    def test_a_beef_dish_excludes_the_other_four(self):
        got = dishlib.negative_prompt(d("Beef Stew"))
        assert "chicken" in got and "pork" in got and "shrimp" in got and "mutton" in got

    def test_a_vegetarian_dish_excludes_everything(self):
        got = dishlib.negative_prompt(d("Garden Salad", tags=["vegetarian"]))
        assert "meat" in got
        for words in dishlib._PROTEIN_NEGATIVE.values():
            assert words.split(",")[0] in got

    def test_an_unknown_dish_excludes_nothing(self):
        """"other" is genuinely unknown -- it may still arrive with meat in it."""
        assert dishlib.negative_prompt(d("Craveable Grains")) == dishlib.NEGATIVE_PROMPT

    def test_the_base_prompt_is_always_there(self):
        for dish in (d("Beef Stew"), d("Salad", tags=["vegan"]), d("Mystery")):
            assert dishlib.NEGATIVE_PROMPT in dishlib.negative_prompt(dish)

    def test_saffron_excludes_interfering_garnishes(self):
        neg = dishlib.negative_prompt(d("Saffron Rice", tags=["vegan"]))
        assert "dill" in neg
        assert "peas" in neg
        assert "star anise" in neg

    def test_negative_prompt_excludes_extra_chopsticks(self):
        assert "three chopsticks" in dishlib.NEGATIVE_PROMPT
        assert "extra chopsticks" in dishlib.NEGATIVE_PROMPT


def test_prompt_rev_is_an_integer():
    """Bumped whenever the prompt rules change; --redraw-stale compares against
    it, so a string or a float would quietly stop selecting anything."""
    assert isinstance(dishlib.PROMPT_REV, int) and dishlib.PROMPT_REV >= 1
