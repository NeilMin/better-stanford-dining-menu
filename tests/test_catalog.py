"""The dish catalog: an index of every dish ever seen, not of this week's board.

It accumulates rather than re-derives. One run reads a bounded window, so
everything outside that window survives only through `previous` -- and the
pictures in data/images/ are keyed to it, so a dish that drops out of the index
for a fortnight comes back a stranger owing an hour of GPU time.
"""

from __future__ import annotations

from bsdm import catalog as cataloglib
from bsdm import dishes as dishlib

from conftest import dish


def build(project, days=None, *, stations=None, previous=None, specials=()):
    from bsdm import menus as menuslib
    for day, halls in (days or {}).items():
        project.write_menu(day, halls)
    return cataloglib.build(menuslib.history(project.root), stations or {},
                            previous, specials)


def entry_for(catalog, name):
    return catalog[dishlib.dish_id(name)]


class TestBuild:
    def test_keys_on_the_normalized_name(self, project):
        catalog = build(project, {"2026-09-17": {"wilbur": {"Dinner": [dish("Roast Chicken")]}}})
        assert list(catalog) == [dishlib.dish_id("roast   chicken")]

    def test_carries_what_the_menu_said(self, project):
        catalog = build(project, {"2026-09-17": {"wilbur": {"Dinner": [
            dish("Roast Chicken", "chicken thigh, rosemary", tags=["halal"], order=2)]}}})
        got = entry_for(catalog, "Roast Chicken")
        assert got["name"] == "Roast Chicken"
        assert got["ingredients"] == "chicken thigh, rosemary"
        assert got["tags"] == ["halal"]
        assert got["category"] == "poultry"
        assert got["first_seen"] == got["last_seen"] == "2026-09-17"
        assert got["min_order"] == 2

    def test_one_dish_across_days_keeps_both_ends_of_its_run(self, project):
        catalog = build(project, {
            "2026-09-17": {"wilbur": {"Dinner": [dish("Roast Chicken", order=3)]}},
            "2026-09-19": {"stern": {"Dinner": [dish("Roast Chicken", order=1)]}},
        })
        got = entry_for(catalog, "Roast Chicken")
        assert (got["first_seen"], got["last_seen"]) == ("2026-09-17", "2026-09-19")
        assert got["min_order"] == 1


class TestNeedsImage:
    def test_a_standing_counter_gets_no_picture(self, project):
        """It renders as a dense list with no image slot at all. Building the
        catalog before the station table exists queues ~14 of these."""
        catalog = build(project,
                        {"2026-09-17": {"wilbur": {"Dinner": [dish("Burger Bar", "beef")]}}},
                        stations={"halls": {"wilbur": {"Dinner": {"stations": {"Burger Bar": 1.0}}}}})
        got = entry_for(catalog, "Burger Bar")
        assert got["station_only"] and not got["needs_image"]
        assert got["prompt"] is None and got["negative"] is None

    def test_a_counter_one_hall_serves_as_a_dish_does(self, project):
        """station_only, not station: Branner lists the same name as a dish."""
        catalog = build(project, {"2026-09-17": {
            "wilbur": {"Dinner": [dish("Panini Station", "bread")]},
            "branner": {"Dinner": [dish("Panini Station", "bread")]},
        }}, stations={"halls": {"wilbur": {"Dinner": {"stations": {"Panini Station": 1.0}}}}})
        got = entry_for(catalog, "Panini Station")
        assert not got["station_only"] and got["needs_image"]

    def test_a_placeholder_is_deliberately_not_illustrated(self, project):
        """Inventing a specific bowl of soup for an entry that changes daily
        would be worse than showing nothing."""
        catalog = build(project, {"2026-09-17": {"wilbur": {"Dinner": [
            dish("Soup of the Day", "chef's choice")]}}})
        got = entry_for(catalog, "Soup of the Day")
        assert got["placeholder"] and not got["needs_image"] and got["prompt"] is None

    def test_an_ordinary_dish_gets_a_prompt_and_a_negative(self, project):
        catalog = build(project, {"2026-09-17": {"wilbur": {"Dinner": [
            dish("Roast Chicken", "chicken thigh")]}}})
        got = entry_for(catalog, "Roast Chicken")
        assert got["needs_image"]
        assert got["prompt"].startswith("Roast Chicken")
        assert "a dining hall dish" not in got["prompt"]
        assert "sliced steak" in got["negative"], "the other four proteins are steered out"


class TestPriority:
    def meal(self, project, *dishes, previous=None, specials=()):
        return build(project, {"2026-09-17": {"wilbur": {"Dinner": list(dishes)}}},
                     previous=previous, specials=specials)

    def test_meat_leads(self, project):
        catalog = self.meal(project, dish("Braised Short Rib", "beef short rib", order=6))
        assert entry_for(catalog, "Braised Short Rib")["priority"] == 0

    def test_menu_position_beats_a_guess_from_the_name(self, project):
        """R&DE lists the day's entrees first, which is better evidence than
        the word "rice" in "Plant-Forward Loco Moco & Gravy"."""
        catalog = self.meal(project, dish("Plant-Forward Loco Moco & Gravy", "rice, gravy", order=1))
        assert entry_for(catalog, "Plant-Forward Loco Moco & Gravy")["priority"] == 1

    def test_a_side_by_name_is_a_side(self, project):
        catalog = self.meal(project, dish("Steamed Rice", "rice", order=2))
        assert entry_for(catalog, "Steamed Rice")["priority"] == 2

    def test_a_side_by_position_is_a_side(self, project):
        catalog = self.meal(project, dish("Chana Masala", "chickpeas", order=7))
        assert entry_for(catalog, "Chana Masala")["priority"] == 2

    def test_anything_else_is_a_main(self, project):
        catalog = self.meal(project, dish("Chana Masala", "chickpeas", order=3))
        assert entry_for(catalog, "Chana Masala")["priority"] == 1

    def test_minor_matches_on_whole_words(self, project):
        """"jackfruit" contains "fruit", and a pulled jackfruit sandwich is an
        entree, not a fruit cup."""
        assert cataloglib._is_minor("Fruit Cup")
        assert not cataloglib._is_minor("Pulled Jackfruit Sandwich")


class TestAccumulation:
    def test_a_dish_outside_the_window_is_carried_over_whole(self, project):
        """The window is bounded; the index is not. A dish off the menu for a
        fortnight must not take its picture out of the index with it."""
        old_id = dishlib.dish_id("Winter Squash Soup")
        previous = {old_id: {"name": "Winter Squash Soup", "image": f"{old_id}.webp",
                             "station_only": True, "needs_image": False, "priority": 2,
                             "placeholder": False, "min_order": 3, "first_seen": "2026-01-02"}}
        catalog = build(project, {"2026-09-17": {"wilbur": {"Dinner": [dish("Roast Chicken")]}}},
                        previous=previous)
        assert catalog[old_id] == previous[old_id]

    def test_a_carried_dish_does_not_go_through_the_rules_again(self, project):
        """With no sighting this run there is nothing to recompute from, and
        station_only would flip to False and queue a picture for a counter."""
        old_id = dishlib.dish_id("Burger Bar")
        previous = {old_id: {"name": "Burger Bar", "station_only": True,
                             "needs_image": False, "image": None}}
        catalog = build(project, {"2026-09-17": {"wilbur": {"Dinner": [dish("Roast Chicken")]}}},
                        previous=previous)
        assert catalog[old_id]["station_only"] and not catalog[old_id]["needs_image"]

    def test_min_order_is_merged_above_the_rules(self, project):
        """It is the menu position that decides priority, so taking the minimum
        over only this window demotes a dish that led the menu in March."""
        did = dishlib.dish_id("Mushroom Wellington")
        previous = {did: {"name": "Mushroom Wellington", "min_order": 0, "image": None}}
        catalog = build(project, {"2026-09-17": {"wilbur": {"Dinner": [
            dish("Mushroom Wellington", "mushroom, pastry", order=6)]}}}, previous=previous)
        got = catalog[did]
        assert got["min_order"] == 0
        assert got["priority"] == 1, "demoted to a side by a week of being listed late"

    def test_first_seen_reaches_back_past_the_window(self, project):
        did = dishlib.dish_id("Roast Chicken")
        previous = {did: {"name": "Roast Chicken", "first_seen": "2025-03-04", "image": None}}
        catalog = build(project, {"2026-09-17": {"wilbur": {"Dinner": [dish("Roast Chicken")]}}},
                        previous=previous)
        assert catalog[did]["first_seen"] == "2025-03-04"

    def test_image_fields_already_earned_are_kept(self, project):
        """Retuning classification is free; redrawing the library is not."""
        did = dishlib.dish_id("Roast Chicken")
        previous = {did: {"name": "Roast Chicken", "image": f"{did}.webp", "seed": 12345,
                          "model": "sdxl", "prompt_rev": 1,
                          "generated_at": "2026-02-01T00:00:00+00:00"}}
        catalog = build(project, {"2026-09-17": {"wilbur": {"Dinner": [dish("Roast Chicken")]}}},
                        previous=previous)
        got = catalog[did]
        assert got["image"] == f"{did}.webp"
        assert (got["seed"], got["model"], got["prompt_rev"]) == (12345, "sdxl", 1)
        assert got["generated_at"] == "2026-02-01T00:00:00+00:00"

    def test_a_dish_with_no_picture_yet_stays_without_one(self, project):
        catalog = build(project, {"2026-09-17": {"wilbur": {"Dinner": [dish("Roast Chicken")]}}},
                        previous={dishlib.dish_id("Roast Chicken"): {"name": "Roast Chicken"}})
        assert entry_for(catalog, "Roast Chicken")["image"] is None

    def test_compiled_prompt_is_carried_over(self, project):
        d_raw = dish("Beef Hot Dog", "beef, sorbitol", order=0)
        did = dishlib.dish_id(d_raw["name"])
        previous = {
            did: {
                "name": "Beef Hot Dog",
                "ingredients": "beef, sorbitol",
                "first_seen": "2026-09-10",
                "min_order": 0,
                "prompt": "Custom compiled prompt",
                "negative": "Custom compiled negative",
                "prompt_compiled": True,
                "prompt_compiler_rev": 1,
            }
        }
        catalog = build(project, {"2026-09-17": {"wilbur": {"Dinner": [d_raw]}}}, previous=previous)
        got = entry_for(catalog, "Beef Hot Dog")
        assert got["prompt"] == "Custom compiled prompt"
        assert got["negative"] == "Custom compiled negative"
        assert got["prompt_compiled"] is True
        assert got["prompt_compiler_rev"] == 1



class TestSpecials:
    def test_a_special_is_a_dish_drawn_from_its_name_alone(self, project):
        """The poster gives a name and nothing else, but this is the dish
        people walk across campus for."""
        catalog = build(project, {"2026-09-17": {"wilbur": {"Dinner": [dish("Rice")]}}},
                        specials=[{"text": "Jerk Pork Belly", "from": "2026-09-15",
                                   "to": "2026-09-19"}])
        got = entry_for(catalog, "Jerk Pork Belly")
        assert got["special"] and got["needs_image"] and got["priority"] == 0
        assert got["prompt"].startswith("Jerk Pork Belly")
        assert "a dining hall dish" not in got["prompt"]

    def test_an_empty_ingredient_list_is_not_read_as_changes_daily(self, project):
        """is_placeholder() would say so, and skip the picture. It does not:
        the poster names one dish on fixed dates."""
        catalog = build(project, {"2026-09-17": {"wilbur": {"Dinner": [dish("Rice")]}}},
                        specials=[{"text": "Esquite Fries", "from": "2026-09-15",
                                   "to": "2026-09-19"}])
        got = entry_for(catalog, "Esquite Fries")
        assert got["placeholder"] is False and got["needs_image"]

    def test_a_special_the_menu_also_lists_keeps_the_menus_ingredients(self, project):
        catalog = build(project, {"2026-09-17": {"wilbur": {"Dinner": [
            dish("Esquite Fries", "corn, cotija, lime", order=5)]}}},
            specials=[{"text": "Esquite Fries", "from": "2026-09-15", "to": "2026-09-19"}])
        got = entry_for(catalog, "Esquite Fries")
        assert got["ingredients"] == "corn, cotija, lime"
        assert got["special"] and got["priority"] == 0, "a special leads whatever its position"

    def test_a_special_is_dated_by_its_run(self, project):
        catalog = build(project, {"2026-09-17": {"wilbur": {"Dinner": [dish("Rice")]}}},
                        specials=[{"text": "Jerk Pork Belly", "from": "2026-09-15",
                                   "to": "2026-09-19"}])
        got = entry_for(catalog, "Jerk Pork Belly")
        assert (got["first_seen"], got["last_seen"]) == ("2026-09-15", "2026-09-19")


class TestStale:
    def test_an_image_drawn_under_older_rules(self):
        assert cataloglib.is_stale({"image": "x.webp", "prompt_rev": dishlib.PROMPT_REV - 1})

    def test_an_image_drawn_under_the_current_rules_is_not(self):
        assert not cataloglib.is_stale({"image": "x.webp", "prompt_rev": dishlib.PROMPT_REV})

    def test_no_image_is_not_stale(self):
        assert not cataloglib.is_stale({"image": None, "prompt_rev": 1})

    def test_an_image_from_before_the_field_existed_is_stale(self):
        assert cataloglib.is_stale({"image": "x.webp"}) == (dishlib.PROMPT_REV > 1)


def test_summarize_counts_what_is_outstanding(project):
    catalog = build(project, {"2026-09-17": {"wilbur": {"Dinner": [
        dish("Braised Short Rib", "beef short rib", order=0),
        dish("Soup of the Day", "chef's choice", order=1),
    ]}}})
    line = cataloglib.summarize(catalog)
    assert "2 dishes" in line and "1 want images" in line and "1 placeholders skipped" in line
