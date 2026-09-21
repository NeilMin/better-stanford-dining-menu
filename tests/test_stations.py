"""Telling standing counters apart from the day's rotating menu.

Nothing in R&DE's markup distinguishes them, so it is derived from how often a
name recurs at that hall. It has to be right before the catalog is built:
station membership decides `needs_image`, and a counter misread as a dish
queues an hour of GPU time for something the page renders as a line of text.
"""

from __future__ import annotations

from bsdm import menus as menuslib
from bsdm import stations as stationlib

from conftest import dish


def menus_for(project, days, halls):
    """`days` services per hall, each serving `halls[hall]` -- a list of dishes."""
    paths = []
    for i in range(days):
        day = f"2026-09-{i + 1:02d}"
        paths.append(project.archive_menu(day, {
            hall: {"Dinner": served(i)} for hall, served in halls.items()
        }))
    return paths


class TestAnalyze:
    def test_a_name_on_every_service_is_standing(self, project):
        paths = menus_for(project, 7, {"wilbur": lambda i: [
            dish("Burger Bar", "beef patty"), dish(f"Special {i}", "rice"),
        ]})
        table = stationlib.analyze(paths)
        assert stationlib.station_names(table, "wilbur", "Dinner") == {"Burger Bar"}

    def test_the_split_is_per_hall_not_global(self, project):
        """Only four of eight halls run a Burger Bar, and Branner runs its own
        allergen-free counters under their own names."""
        paths = menus_for(project, 7, {
            "wilbur": lambda i: [dish("Burger Bar", "beef patty")],
            "branner": lambda i: [dish("Burger Bar", "beef patty") if i == 0
                                  else dish(f"Roast {i}", "chicken")],
        })
        table = stationlib.analyze(paths)
        assert stationlib.station_names(table, "wilbur", "Dinner") == {"Burger Bar"}
        assert stationlib.station_names(table, "branner", "Dinner") == set()

    def test_the_split_is_per_meal_too(self, project):
        for i in range(7):
            project.archive_menu(f"2026-09-{i + 1:02d}", {"wilbur": {
                "Breakfast": [dish("Omelette Bar", "eggs")],
                "Dinner": [dish(f"Roast {i}", "chicken")],
            }})
        table = stationlib.analyze(menuslib.history(project.root))
        assert stationlib.station_names(table, "wilbur", "Breakfast") == {"Omelette Bar"}
        assert stationlib.station_names(table, "wilbur", "Dinner") == set()

    def test_station_established_in_one_meal_is_standing_in_another_meal_at_the_same_hall(self, project):
        """A station established at lunch (e.g. Panini Station at Lakeside) remains
        a standing counter when it appears occasionally at dinner, rather than
        floating as a daily rotating dish card."""
        paths = []
        for i in range(10):
            paths.append(project.archive_menu(f"2026-09-{i + 1:02d}", {"lakeside": {
                "Lunch": [dish("Panini Station", "bread, cheese")],
                "Dinner": ([dish("Panini Station", "bread, cheese")] if i < 2 else []) + [dish(f"Roast {i}", "chicken")],
            }}))
        table = stationlib.analyze(paths)
        assert "Panini Station" in stationlib.station_names(table, "lakeside", "Lunch")
        assert "Panini Station" in stationlib.station_names(table, "lakeside", "Dinner")

    def test_the_threshold_is_a_share_of_that_halls_services(self, project):
        """0.6, and the split is almost perfectly bimodal in practice: a
        standing counter is on 7 of 7, the day's menu on exactly 1."""
        # 6 of 10 is exactly the threshold; 5 of 10 is below it.
        paths = menus_for(project, 10, {"wilbur": lambda i: (
            [dish("Six Of Ten", "rice")] if i < 6 else []
        ) + ([dish("Five Of Ten", "rice")] if i < 5 else []) + [dish(f"Day {i}", "rice")]})
        names = stationlib.station_names(stationlib.analyze(paths), "wilbur", "Dinner")
        assert "Six Of Ten" in names
        assert "Five Of Ten" not in names

    def test_records_how_much_was_observed(self, project):
        paths = menus_for(project, 5, {"wilbur": lambda i: [dish("Soup", "chef's choice")]})
        table = stationlib.analyze(paths)
        assert table["halls"]["wilbur"]["Dinner"]["services_observed"] == 5
        assert table["days_analyzed"] == 5
        assert table["threshold"] == stationlib.THRESHOLD


class TestColdStart:
    """Below four observed services the ratio is meaningless -- on day one
    everything has been served on 1 of 1 -- so name shape is used instead."""

    def test_a_counter_says_so_in_its_name(self, project):
        """"bar", "station" and "counter", plus the openings R&DE writes its
        standing entries with ("Soup ...", "Assorted ...", "Grilled ...")."""
        paths = menus_for(project, 2, {"wilbur": lambda i: [
            dish("Panini Station", "assorted breads"),
            dish("Roast Salmon", "salmon, lemon"),
        ]})
        names = stationlib.station_names(stationlib.analyze(paths), "wilbur", "Dinner")
        assert "Panini Station" in names
        assert "Roast Salmon" not in names

    def test_a_placeholder_ingredient_list_is_a_counter(self, project):
        paths = menus_for(project, 2, {"wilbur": lambda i: [
            dish("Soup of the Day", "chef's choice"),
            dish("Wild Rice Pilaf", "wild rice, stock, celery"),
        ]})
        names = stationlib.station_names(stationlib.analyze(paths), "wilbur", "Dinner")
        assert "Soup of the Day" in names
        assert "Wild Rice Pilaf" not in names

    def test_an_empty_ingredient_list_is_a_counter(self, project):
        paths = menus_for(project, 1, {"wilbur": lambda i: [dish("Deli", "")]})
        assert "Deli" in stationlib.station_names(stationlib.analyze(paths), "wilbur", "Dinner")

    def test_the_ratio_takes_over_once_there_is_enough_to_go_on(self, project):
        """Four services is the switch: a dish named like a counter that turns
        out to appear once is the day's menu after all."""
        paths = menus_for(project, 4, {"wilbur": lambda i: (
            [dish("Grilled Vegetable Plate", "zucchini")] if i == 0 else [dish(f"Day {i}", "rice")]
        )})
        names = stationlib.station_names(stationlib.analyze(paths), "wilbur", "Dinner")
        assert "Grilled Vegetable Plate" not in names


class TestSplit:
    def test_partitions_one_service_in_menu_order(self, project):
        table = {"halls": {"wilbur": {"Dinner": {"stations": {"Burger Bar": 1.0}}}}}
        served = [dish("Roast Chicken"), dish("Burger Bar"), dish("Rice Pilaf")]
        daily, standing = stationlib.split(table, "wilbur", "Dinner", served)
        assert [d["name"] for d in daily] == ["Roast Chicken", "Rice Pilaf"]
        assert [d["name"] for d in standing] == ["Burger Bar"]

    def test_an_unanalysed_hall_is_all_menu(self, project):
        """Better a counter shown as a card than a dish silently dropped: a new
        hall has no table yet, and the board still has to render."""
        served = [dish("Burger Bar"), dish("Roast Chicken")]
        daily, standing = stationlib.split({}, "newhall", "Dinner", served)
        assert len(daily) == 2 and standing == []

    def test_station_names_is_empty_for_anything_unknown(self):
        assert stationlib.station_names({}, "wilbur", "Dinner") == set()
        assert stationlib.station_names({"halls": {}}, "wilbur", "Lunch") == set()


class TestGroupServiceStations:
    def test_burger_bar_groups_grill_proteins(self):
        served = [
            dish("Hot Honey BBQ Chicken", "chicken, honey"),
            dish("Burger Bar", ""),
            dish("Grilled Chicken", "chicken, oil"),
            dish("Grilled Vegan/Vegetarian", "tofu, veggies"),
            dish("Handmade Pizza", "dough, cheese"),
        ]
        grouped = stationlib.group_service_stations(served)
        assert len(grouped) == 3
        assert grouped[0]["name"] == "Hot Honey BBQ Chicken"
        assert grouped[1]["is_group"] is True
        assert grouped[1]["station"]["name"] == "Burger Bar"
        assert [c["name"] for c in grouped[1]["items"]] == ["Grilled Chicken", "Grilled Vegan/Vegetarian"]
        assert grouped[2]["name"] == "Handmade Pizza"

    def test_taco_bar_groups_taco_components(self):
        served = [
            dish("Breakfast Taco Bar", ""),
            dish("Sautéed Chorizo Sausage", "chorizo"),
            dish("Tater Tots", "potato"),
            dish("Tasty Tofu Scramble", "tofu"),
            dish("Buttermilk Pancakes", "flour, milk"),
        ]
        grouped = stationlib.group_service_stations(served)
        assert len(grouped) == 2
        assert grouped[0]["is_group"] is True
        assert grouped[0]["station"]["name"] == "Breakfast Taco Bar"
        assert [c["name"] for c in grouped[0]["items"]] == [
            "Sautéed Chorizo Sausage", "Tater Tots", "Tasty Tofu Scramble"
        ]
        assert grouped[1]["name"] == "Buttermilk Pancakes"

    def test_standalone_dishes_remain_unmodified(self):
        served = [dish("Pasta", "wheat"), dish("Salad", "lettuce")]
        grouped = stationlib.group_service_stations(served)
        assert [d["name"] for d in grouped] == ["Pasta", "Salad"]
