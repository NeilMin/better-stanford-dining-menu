"""The steps in the order the nightly job runs them, and the data it has left.

Two kinds of test here. The first walks a synthetic week through scrape ->
stations -> catalog -> build, because several of the rules only exist at the
joins: what a stage is handed decides what the next one does, and getting the
order wrong is silent. The second builds the site out of the checkout's own
data/, which is the only test that can tell you the committed artefacts still
fit together.
"""

from __future__ import annotations

import json

import pytest

from bsdm import build as buildlib
from bsdm import catalog as cataloglib
from bsdm import menus as menuslib
from bsdm import stations as stationlib
from bsdm.dishes import dish_id

from conftest import dish, load_script


class TestOrder:
    """`scripts/update.py` analyses stations, then builds the catalog. The other
    way round is not an error -- it just quietly queues pictures for counters."""

    @pytest.fixture
    def week(self, project):
        project.set_today("2026-09-17")
        project.add_hall("wilbur")
        for i in range(7):
            project.archive_menu(f"2026-09-{10 + i:02d}", {"wilbur": {"Dinner": [
                dish("Pasta Marinara", "pasta, tomato sauce", order=0),
                dish(f"Braised Short Rib {i}", "beef short rib", order=1),
            ]}})
        return project

    def test_stations_are_analysed_before_the_catalog_is_built(self, week):
        paths = menuslib.recent(week.root)
        table = stationlib.analyze(paths)
        catalog = cataloglib.build(paths, table)
        assert not catalog[dish_id("Pasta Marinara")]["needs_image"]

    def test_building_the_catalog_first_queues_a_picture_for_a_counter(self, week):
        """The failure this ordering prevents, spelled out: an empty table is
        exactly what update.py would hand it on the wrong order."""
        catalog = cataloglib.build(menuslib.recent(week.root), {})
        assert catalog[dish_id("Pasta Marinara")]["needs_image"], (
            "if this ever stops being true the ordering rule can be relaxed")

    def test_the_catalog_is_rebuilt_after_the_specials_are_fetched(self, week):
        """A poster fetched tonight has to be in the catalog tonight, or its
        pictures are not queued until tomorrow."""
        table = stationlib.analyze(menuslib.recent(week.root))
        catalog = cataloglib.build(menuslib.recent(week.root), table, None,
                                   [{"text": "Jerk Pork Belly", "from": "2026-09-15",
                                     "to": "2026-09-19"}])
        assert catalog[dish_id("Jerk Pork Belly")]["needs_image"]


def test_both_entry_points_go_through_one_catalog_builder():
    """update.py kept an inline copy once, and it overwrote priority,
    needs_image, station_only and min_order on every scrape."""
    update = load_script("update")
    rebuild = load_script("rebuild_catalog")
    assert update.build_catalog is cataloglib.build
    assert rebuild.build is cataloglib.build


class TestSyntheticWeek:
    """A week from scraped rows to the payload the page is rendered from."""

    @pytest.fixture
    def built(self, project):
        project.set_today("2026-09-17")
        project.add_hall("wilbur")
        project.add_hall("branner")

        # The counter is on every service; the day's dish and the side are not,
        # which is the recurrence the station split reads.
        served = lambda i: [
            dish("Burger Bar", "beef patty, bun", order=0),
            dish(f"Roast Chicken {i}", "chicken thigh, rosemary", order=1),
        ]
        for i in range(7):
            project.archive_menu(f"2026-09-{10 + i:02d}", {"wilbur": {"Dinner": served(i)}})
        project.write_menu("2026-09-17", {
            "wilbur": {"Dinner": served(7) + [dish("Steamed Rice", "rice", order=5)]},
            # Branner runs the allergen-free version of the same recipe.
            "branner": {"Dinner": [dish("Steamed Rice", "rice", order=5, allergens=[])]},
        })
        project.write_specials({"url": "https://x/p.pdf", "meal": "Dinner",
                                "from": "2026-09-15", "to": "2026-09-19", "entries": [
                                    {"label": "Wilbur", "text": "Jerk Pork Belly",
                                     "halls": ["wilbur"], "from": "2026-09-17",
                                     "to": "2026-09-17"}]})

        paths = menuslib.recent(project.root)
        table = stationlib.analyze(paths)
        project.write_stations(table)
        from bsdm import specials as specialslib
        catalog = cataloglib.build(paths, table, None, specialslib.dishes(project.root))
        project.write_catalog(catalog)
        return project, catalog, buildlib.build_payload(project.root)

    def test_the_counter_is_a_station_not_a_card(self, built):
        _, catalog, payload = built
        svc = payload["menus"]["2026-09-17"]["wilbur"]["Dinner"]
        assert svc["stations"] == [{
            "station": f"{dish_id('Burger Bar')}.0",
            "items": [],
        }]
        assert not catalog[dish_id("Burger Bar")]["needs_image"]

    def test_the_special_leads_and_is_drawn(self, built):
        _, catalog, payload = built
        svc = payload["menus"]["2026-09-17"]["wilbur"]["Dinner"]
        assert svc["specials"] == [f"{dish_id('Jerk Pork Belly')}.0"]
        assert catalog[dish_id("Jerk Pork Belly")]["priority"] == 0

    def test_the_meat_dish_is_drawn_before_the_side(self, built):
        _, catalog, _ = built
        assert catalog[dish_id("Roast Chicken 7")]["priority"] == 0
        assert catalog[dish_id("Steamed Rice")]["priority"] == 2

    def test_every_reference_on_the_board_resolves(self, built):
        _, _, payload = built
        check_refs(payload)


def check_refs(payload):
    """Every "<dishId>.<variantIndex>" on the board points at something."""
    for day, halls in payload["menus"].items():
        assert day in payload["window"]
        for hall_id, meals in halls.items():
            assert hall_id in {h["id"] for h in payload["halls"]}, f"{day} {hall_id}"
            for meal, service in meals.items():
                assert set(service) == {"specials", "daily", "stations"}
                refs = []
                for item in service["specials"] + service["daily"] + service["stations"]:
                    if isinstance(item, dict) and "station" in item:
                        refs.append(item["station"])
                        refs.extend(item.get("items", []))
                    else:
                        refs.append(item)
                for ref in refs:
                    did, _, index = ref.rpartition(".")
                    record = payload["dishes"].get(did)
                    assert record, f"{day} {hall_id} {meal}: {ref} is not a dish"
                    assert int(index) < len(record["v"]), f"{ref} has no such variant"


@pytest.fixture(scope="module")
def payload(request):
    """The real checkout's data, built as it stood the day it was scraped.

    Pinned to the window on disk rather than to the wall clock, so this keeps
    testing the committed data instead of expiring with it a week later.
    """
    import bsdm.menus as m
    import bsdm.source as s

    repo = request.path.parent.parent
    days = m.live(repo)
    if not days:
        pytest.skip("no live menus in this checkout -- run `make update`")
    first = m.date_of(days[0])
    patch = pytest.MonkeyPatch()
    patch.setattr(m, "today", lambda: first)
    patch.setattr(s, "today", lambda: first)
    try:
        yield buildlib.build_payload(repo)
    finally:
        patch.undo()


@pytest.fixture(scope="module")
def checkout_catalog(request):
    path = request.path.parent.parent / "data" / "dishes.json"
    if not path.exists():
        pytest.skip("no catalog in this checkout -- run `make update`")
    return json.loads(path.read_text())


@pytest.mark.golden
class TestTheCheckoutsOwnData:
    """data/ is committed, and the site is built straight off it. Nothing else
    checks that the pieces still fit: menus, catalog, images, logos, zh.json
    and the specials archive are written by five different jobs."""

    def test_it_builds(self, payload):
        assert payload["window"] and payload["halls"] and payload["dishes"]

    def test_every_reference_on_the_board_resolves(self, payload):
        check_refs(payload)

    def test_the_window_is_a_run_of_distinct_days_in_order(self, payload):
        assert payload["window"] == sorted(set(payload["window"]))

    def test_every_published_hall_serves_something_in_the_window(self, payload):
        for hall in payload["halls"]:
            assert any(hall["id"] in payload["menus"][day] for day in payload["window"]), \
                hall["id"]

    def test_every_picture_it_names_is_in_the_checkout(self, payload, repo):
        for did, record in payload["dishes"].items():
            if record["image"]:
                assert (repo / "data" / "images" / record["image"]).exists(), did

    def test_every_logo_it_names_is_in_the_checkout(self, payload, repo):
        for hall in payload["halls"]:
            if logo := hall.get("logo"):
                assert (repo / "data" / "logos" / logo["file"]).exists(), hall["id"]

    def test_every_shipped_term_is_keyed_the_way_the_page_looks_it_up(self, payload):
        from bsdm import zh as zhlib

        for term in payload["zh_terms"]:
            assert term == zhlib.norm(term)

    def test_the_hours_come_from_config_for_every_day(self, payload, repo):
        config = json.loads((repo / "config" / "halls.json").read_text())
        known = {h["id"] for h in config["halls"]}
        for day, halls in payload["hours"].items():
            assert day in payload["window"]
            assert set(halls) <= known

    def test_plant_forward_is_not_translated_literally(self, repo):
        zh_raw = (repo / "data" / "zh.json").read_text()
        assert "植物向前" not in zh_raw


@pytest.mark.golden
class TestTheCheckoutsCatalog:
    def test_every_entry_has_what_the_build_reads(self, checkout_catalog):
        for did, entry in checkout_catalog.items():
            assert {"name", "category", "priority", "placeholder"} <= set(entry), did

    def test_a_dish_that_wants_a_picture_has_a_prompt_to_draw_it_from(self, checkout_catalog):
        for did, entry in checkout_catalog.items():
            if entry.get("needs_image"):
                assert entry.get("prompt") and entry.get("negative"), did

    def test_nothing_is_both_a_standing_counter_and_a_card(self, checkout_catalog):
        for did, entry in checkout_catalog.items():
            assert not (entry.get("station_only") and entry.get("needs_image")), did

    def test_a_positive_prompt_never_asks_for_no_meat_by_itself(self, checkout_catalog):
        """CLIP has no negation: "no meat" in a positive prompt is a prompt
        about meat. It is only ever said alongside the hall's own vegan or
        vegetarian label, which is what the picture is really conditioned on."""
        for did, entry in checkout_catalog.items():
            if (prompt := entry.get("prompt")) and "no meat" in prompt:
                assert {"vegan", "vegetarian"} & set(entry.get("tags", [])), did

    def test_every_picture_on_disk_belongs_to_a_dish_id(self, repo):
        """Images are keyed on the dish id, so a stray name means a file that
        will never be shown and never be redrawn either."""
        for path in (repo / "data" / "images").glob("*.webp"):
            assert len(path.stem) == 12 and int(path.stem, 16) >= 0
