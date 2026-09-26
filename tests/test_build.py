"""Assembling the payload the page is rendered from.

Two failures live here that look alike and are not: a day where nobody is
serving is a closure and publishes, while an empty live/ means the scrape did
not run and the answer is to fix the scrape. Reaching backwards for data to
publish turns a broken scraper into a site quietly serving last week's dinner
-- and replaces a good deploy with it.
"""

from __future__ import annotations

import json
import re
from datetime import date

import pytest

from bsdm import build as buildlib
from bsdm.dishes import dish_id

from conftest import dish


@pytest.fixture
def site(project):
    """A hall, a day, and a dish: the smallest thing that publishes."""
    project.set_today("2026-09-17")
    project.add_hall("wilbur")
    project.write_catalog({})
    project.write_menu("2026-09-17", {"wilbur": {"Dinner": [dish("Roast Chicken", "chicken")]}})
    return project


class TestScheduleFor:
    def hall(self, *schedules):
        return {"schedules": list(schedules)}

    def test_the_schedule_covering_that_day(self):
        hall = self.hall({"from": "2026-09-16", "days": [0, 1, 2, 3, 4],
                          "meals": {"Dinner": ["17:00", "20:00"]}})
        assert buildlib.schedule_for(hall, date(2026, 9, 17)) == {"Dinner": ["17:00", "20:00"]}

    def test_a_schedule_that_has_not_started_yet(self):
        hall = self.hall({"from": "2026-09-20", "days": [0, 1, 2, 3, 4], "meals": {"D": []}})
        assert buildlib.schedule_for(hall, date(2026, 9, 17)) == {}

    def test_a_schedule_that_has_ended(self):
        hall = self.hall({"from": "2026-09-01", "to": "2026-09-15",
                          "days": [0, 1, 2, 3, 4], "meals": {"D": []}})
        assert buildlib.schedule_for(hall, date(2026, 9, 17)) == {}

    def test_a_day_of_the_week_it_does_not_run(self):
        """Thursday is 3. A weekday table says nothing about the weekend."""
        hall = self.hall({"from": "2026-09-01", "days": [5, 6], "meals": {"D": []}})
        assert buildlib.schedule_for(hall, date(2026, 9, 17)) == {}

    def test_the_first_matching_schedule_wins(self):
        """Orientation-week exceptions are listed above the term's own hours."""
        hall = self.hall(
            {"from": "2026-09-15", "to": "2026-09-17", "days": [0, 1, 2, 3, 4],
             "meals": {"Dinner": ["17:00", "20:00"]}},
            {"from": "2026-09-01", "days": [0, 1, 2, 3, 4],
             "meals": {"Dinner": ["17:30", "19:30"]}},
        )
        assert buildlib.schedule_for(hall, date(2026, 9, 17))["Dinner"] == ["17:00", "20:00"]

    def test_a_hall_with_no_schedules_at_all(self):
        assert buildlib.schedule_for({}, date(2026, 9, 17)) == {}


class TestWindow:
    def test_only_the_live_window_publishes(self, site):
        site.archive_menu("2026-09-16", {"wilbur": {"Dinner": [dish("Yesterday")]}})
        payload = buildlib.build_payload(site.root)
        assert payload["window"] == ["2026-09-17"]

    def test_a_live_day_that_has_since_passed_is_filtered_out(self, site):
        """live/ is swept by the scrape, so a build the next morning on an
        unscraped checkout would otherwise publish yesterday as today."""
        site.write_menu("2026-09-16", {"wilbur": {"Dinner": [dish("Yesterday")]}})
        assert buildlib.build_payload(site.root)["window"] == ["2026-09-17"]

    def test_no_live_day_refuses_to_build(self, project):
        """Never reach backwards for data to publish: a broken scraper must
        not quietly replace a good site with last week's dinner."""
        project.set_today("2026-09-17")
        project.add_hall("wilbur")
        project.write_catalog({})
        project.write_menu("2026-09-15", {"wilbur": {"Dinner": [dish("Old")]}})

        with pytest.raises(SystemExit) as exc:
            buildlib.build_payload(project.root)
        assert "make update" in str(exc.value)

    def test_a_day_where_nobody_is_serving_publishes(self, project):
        """Over a break the board should say the halls are shut -- which is a
        different thing from having no day at all."""
        project.set_today("2026-09-17")
        project.add_hall("wilbur")
        project.write_catalog({})
        project.write_menu("2026-09-17", {})

        payload = buildlib.build_payload(project.root)
        assert payload["window"] == ["2026-09-17"]
        assert payload["halls"] == [] and payload["menus"]["2026-09-17"] == {}


class TestDishesAndVariants:
    def test_a_menu_entry_references_a_dish_and_a_variant(self, site):
        payload = buildlib.build_payload(site.root)
        ref = payload["menus"]["2026-09-17"]["wilbur"]["Dinner"]["daily"][0]
        assert ref == f"{dish_id('Roast Chicken')}.0"
        assert payload["dishes"][dish_id("Roast Chicken")]["v"][0]["ing"] == "chicken"

    def test_a_dish_served_differently_at_two_halls_keeps_both(self, project):
        """Branner runs allergen-free versions of the same recipes, so each
        column has to show the allergens for that hall's version."""
        project.set_today("2026-09-17")
        project.add_hall("wilbur")
        project.add_hall("branner")
        project.write_catalog({})
        project.write_menu("2026-09-17", {
            "wilbur": {"Dinner": [dish("Pasta", "pasta, cream", allergens=["MILK"])]},
            "branner": {"Dinner": [dish("Pasta", "pasta", allergens=[])]},
        })
        payload = buildlib.build_payload(project.root)
        did = dish_id("Pasta")
        assert len(payload["dishes"][did]["v"]) == 2
        assert payload["menus"]["2026-09-17"]["wilbur"]["Dinner"]["daily"] == [f"{did}.0"]
        assert payload["menus"]["2026-09-17"]["branner"]["Dinner"]["daily"] == [f"{did}.1"]

    def test_the_same_dish_served_the_same_way_is_one_variant(self, project):
        project.set_today("2026-09-17")
        project.add_hall("wilbur")
        project.add_hall("stern")
        project.write_catalog({})
        served = [dish("Rice", "rice")]
        project.write_menu("2026-09-17", {"wilbur": {"Dinner": served},
                                          "stern": {"Dinner": served}})
        assert len(buildlib.build_payload(project.root)["dishes"][dish_id("Rice")]["v"]) == 1

    def test_the_catalogs_classification_travels_with_the_dish(self, site):
        site.write_catalog({dish_id("Roast Chicken"): {
            "name": "Roast Chicken", "category": "poultry", "icon": "plate",
            "placeholder": False, "image": None}})
        record = buildlib.build_payload(site.root)["dishes"][dish_id("Roast Chicken")]
        assert record["category"] == "poultry"

    def test_a_dish_the_catalog_has_never_seen_still_renders(self, site):
        """The catalog is rebuilt after the scrape; a build in between must not
        drop a dish off the board."""
        record = buildlib.build_payload(site.root)["dishes"][dish_id("Roast Chicken")]
        assert record["category"] == "other" and record["icon"] == "plate"

    def test_a_picture_is_only_shipped_if_the_file_is_there(self, site):
        """CI has no GPU: images are drawn locally and arrive as a commit, so
        the catalog can name one the checkout does not have yet."""
        did = dish_id("Roast Chicken")
        site.write_catalog({did: {"name": "Roast Chicken", "image": f"{did}.webp"}})
        assert buildlib.build_payload(site.root)["dishes"][did]["image"] is None

        site.write_image(f"{did}.webp")
        assert buildlib.build_payload(site.root)["dishes"][did]["image"] == f"{did}.webp"


class TestStations:
    def test_standing_counters_are_split_off_the_daily_menu(self, site):
        site.write_menu("2026-09-17", {"wilbur": {"Dinner": [
            dish("Roast Chicken", "chicken"), dish("Panini Station", "bread, cheese")]}})
        site.write_stations(wilbur={"Dinner": ["Panini Station"]})
        svc = buildlib.build_payload(site.root)["menus"]["2026-09-17"]["wilbur"]["Dinner"]
        assert svc["daily"] == [f"{dish_id('Roast Chicken')}.0"]
        assert svc["stations"] == [f"{dish_id('Panini Station')}.0"]

    def test_station_container_groups_items_in_payload(self, site):
        site.write_menu("2026-09-17", {"wilbur": {"Dinner": [
            dish("Roast Chicken", "chicken"),
            dish("Burger Bar", ""),
            dish("Grilled Chicken", "chicken"),
            dish("Grilled Vegan/Vegetarian", "tofu"),
        ]}})
        site.write_stations(wilbur={"Dinner": ["Burger Bar", "Grilled Chicken", "Grilled Vegan/Vegetarian"]})
        svc = buildlib.build_payload(site.root)["menus"]["2026-09-17"]["wilbur"]["Dinner"]
        assert svc["daily"] == [f"{dish_id('Roast Chicken')}.0"]
        assert svc["stations"] == [{
            "station": f"{dish_id('Burger Bar')}.0",
            "items": [f"{dish_id('Grilled Chicken')}.0", f"{dish_id('Grilled Vegan/Vegetarian')}.0"],
        }]

    def test_how_much_history_the_table_was_built_on_is_published(self, site):
        site.write_stations(wilbur={"Dinner": []})
        assert buildlib.build_payload(site.root)["stations_computed_from"] == 7


class TestSpecials:
    def poster(self, project, meal="Dinner", halls=("wilbur",), text="Jerk Pork Belly",
               first="2026-09-17", last="2026-09-17"):
        project.write_specials({"url": "https://x/p.pdf", "meal": meal,
                                "from": first, "to": last, "entries": [
                                    {"label": "Wilbur", "text": text, "halls": list(halls),
                                     "from": first, "to": last}]})
        return project

    def test_a_special_leads_its_halls_column(self, site):
        self.poster(site)
        svc = buildlib.build_payload(site.root)["menus"]["2026-09-17"]["wilbur"]["Dinner"]
        assert svc["specials"] == [f"{dish_id('Jerk Pork Belly')}.0"]

    def test_only_on_a_day_the_menus_show_that_hall_serving(self, site):
        """The poster's bars run Monday to Friday even in a week where seven
        halls reopen on the Tuesday. The menu wins."""
        self.poster(site, first="2026-09-16", last="2026-09-18")
        site.write_menu("2026-09-18", {})           # nobody serving
        payload = buildlib.build_payload(site.root)
        assert payload["menus"]["2026-09-17"]["wilbur"]["Dinner"]["specials"]
        assert payload["menus"]["2026-09-18"] == {}

    def test_filed_under_the_calendars_own_meal(self, site):
        """So the page needs no meal guard of its own."""
        site.write_menu("2026-09-17", {"wilbur": {
            "Lunch": [dish("Sandwich", "bread")],
            "Dinner": [dish("Roast Chicken", "chicken")]}})
        self.poster(site, meal="Dinner")
        day = buildlib.build_payload(site.root)["menus"]["2026-09-17"]["wilbur"]
        assert day["Lunch"]["specials"] == [] and day["Dinner"]["specials"]

    def test_a_special_the_menu_also_lists_is_shown_once(self, site):
        site.write_menu("2026-09-17", {"wilbur": {"Dinner": [
            dish("Esquite Fries", "corn, cotija"), dish("Roast Chicken", "chicken")]}})
        self.poster(site, text="Esquite Fries")
        svc = buildlib.build_payload(site.root)["menus"]["2026-09-17"]["wilbur"]["Dinner"]
        assert svc["specials"] == [f"{dish_id('Esquite Fries')}.0"]
        assert f"{dish_id('Esquite Fries')}.0" not in svc["daily"]
        assert svc["daily"] == [f"{dish_id('Roast Chicken')}.0"]

    def test_and_keeps_the_menus_ingredients(self, site):
        """The poster has neither ingredients nor allergens."""
        site.write_menu("2026-09-17", {"wilbur": {"Dinner": [
            dish("Esquite Fries", "corn, cotija", allergens=["MILK"])]}})
        self.poster(site, text="Esquite Fries")
        payload = buildlib.build_payload(site.root)
        variant = payload["dishes"][dish_id("Esquite Fries")]["v"][0]
        assert variant["ing"] == "corn, cotija" and variant["alg"] == ["MILK"]

    def test_a_special_only_the_poster_knows_about_has_no_ingredients(self, site):
        self.poster(site)
        variant = buildlib.build_payload(site.root)["dishes"][dish_id("Jerk Pork Belly")]["v"][0]
        assert variant == {"ing": "", "tags": [], "alg": [], "trace": []}

    def test_a_campus_wide_note_stays_a_notice(self, site):
        """A hall's special is a card; what the calendar says to everyone at
        once is not."""
        site.write_specials({"url": "https://x/p.pdf", "meal": "Dinner",
                             "from": "2026-09-17", "to": "2026-09-17", "entries": [
                                 {"label": None, "text": "Thanksgiving Day Dinner",
                                  "halls": [], "from": "2026-09-17", "to": "2026-09-17"}]})
        payload = buildlib.build_payload(site.root)
        assert payload["notices"]["2026-09-17"] == {
            "meal": "Dinner", "notes": ["Thanksgiving Day Dinner"]}
        assert payload["menus"]["2026-09-17"]["wilbur"]["Dinner"]["specials"] == []

    def test_a_hall_with_nothing_cooked_that_day_gets_no_special(self, site):
        """`daily` empty means the hall is not really serving, whatever the
        poster's bar reaches across."""
        site.write_menu("2026-09-17", {"wilbur": {"Dinner": [dish("Burger Bar", "beef")]}})
        site.write_stations(wilbur={"Dinner": ["Burger Bar"]})
        self.poster(site)
        svc = buildlib.build_payload(site.root)["menus"]["2026-09-17"]["wilbur"]["Dinner"]
        assert svc["specials"] == []


class TestHallsAndHours:
    def test_an_inactive_hall_is_not_published(self, site):
        site.add_hall("evgr", active=False)
        site.write_menu("2026-09-17", {
            "wilbur": {"Dinner": [dish("Roast Chicken", "chicken")]},
            "evgr": {"Dinner": [dish("Roast Chicken", "chicken")]}})
        assert [h["id"] for h in buildlib.build_payload(site.root)["halls"]] == ["wilbur"]

    def test_a_hall_serving_nothing_all_window_is_not_a_column(self, site):
        site.add_hall("stern")
        assert [h["id"] for h in buildlib.build_payload(site.root)["halls"]] == ["wilbur"]

    def test_hours_come_from_the_transcribed_config(self, site):
        hours = buildlib.build_payload(site.root)["hours"]["2026-09-17"]
        assert hours["wilbur"]["Dinner"] == ["17:00", "20:00"]

    def test_a_logo_is_only_shipped_if_it_has_been_cut(self, site):
        """R&DE publishes the logos only inside one map image, so a new hall
        has none until someone reads its box off that map."""
        assert "logo" not in buildlib.build_payload(site.root)["halls"][0]

        (site.root / "data/logos/index.json").write_text(
            json.dumps({"wilbur": {"file": "wilbur.webp", "w": 40, "h": 20}}))
        (site.root / "data/logos/wilbur.webp").write_bytes(b"RIFF----WEBPVP8 ")
        assert buildlib.build_payload(site.root)["halls"][0]["logo"]["file"] == "wilbur.webp"


class TestChinese:
    def test_only_the_terms_this_weeks_menus_use_are_shipped(self, site):
        """The table keeps every term ever seen, which over a term's worth of
        menus is a good deal more than any one week puts on the board."""
        site.write_zh({"dishes": {}, "terms": {"chicken": "鸡肉",
                                               "tamarind": "罗望子"},
                       "halls": {}, "specials": {}})
        payload = buildlib.build_payload(site.root)
        assert payload["zh_terms"] == {"chicken": "鸡肉"}

    def test_an_untranslated_dish_keeps_its_english(self, site):
        assert "zh" not in buildlib.build_payload(site.root)["dishes"][dish_id("Roast Chicken")]

    def test_a_translated_dish_carries_its_chinese(self, site):
        site.write_zh({"dishes": {dish_id("Roast Chicken"): {"en": "Roast Chicken",
                                                            "zh": "烤鸡"}},
                       "terms": {}, "halls": {}, "specials": {}})
        record = buildlib.build_payload(site.root)["dishes"][dish_id("Roast Chicken")]
        assert record["zh"] == "烤鸡"

    def test_a_notice_is_translated_whole(self, site):
        site.write_specials({"url": "https://x/p.pdf", "meal": "Dinner",
                             "from": "2026-09-17", "to": "2026-09-17", "entries": [
                                 {"label": None, "text": "Thanksgiving Day Dinner",
                                  "halls": [], "from": "2026-09-17", "to": "2026-09-17"}]})
        site.write_zh({"dishes": {}, "terms": {}, "halls": {},
                       "specials": {"Thanksgiving Day Dinner": "感恩节晚餐"}})
        payload = buildlib.build_payload(site.root)
        assert payload["zh_specials"] == {"Thanksgiving Day Dinner": "感恩节晚餐"}


class TestRender:
    def test_the_page_is_one_self_contained_file(self, site, tmp_path):
        site.with_web()
        stats = buildlib.build(site.root, tmp_path / "site")
        html = (tmp_path / "site" / "index.html").read_text()

        assert "/*CSS*/" not in html and "/*JS*/" not in html and "/*DATA*/" not in html
        assert "<style" in html and "menu-data" in html
        assert stats["days"] == 1 and stats["halls"] == 1 and stats["rows"] == 1

    def test_a_dish_name_cannot_close_the_script_tag(self, site, tmp_path):
        """`</` is escaped inside the JSON block, so a dish called
        "</script><script>..." ends up as text rather than as markup."""
        site.write_menu("2026-09-17", {"wilbur": {"Dinner": [
            dish("</script><script>alert(1)</script>", "x")]}})
        site.with_web()
        buildlib.build(site.root, tmp_path / "site")
        html = (tmp_path / "site" / "index.html").read_text()
        assert "</script><script>alert(1)" not in html
        assert "<\\/script>" in html

    def test_the_data_block_is_valid_json(self, site, tmp_path):
        site.with_web()
        buildlib.build(site.root, tmp_path / "site")
        html = (tmp_path / "site" / "index.html").read_text()
        start = html.index('id="menu-data"')
        body = html[html.index(">", start) + 1: html.index("</script>", start)]
        payload = json.loads(body.replace("<\\/", "</"))
        assert payload["window"] == ["2026-09-17"]

    def test_the_custom_domain_is_written_on_every_build(self, site, tmp_path):
        """Pages reads it out of the published artifact. It cannot set the
        domain, but it stops a deploy without it from clearing the setting."""
        site.with_web()
        buildlib.build(site.root, tmp_path / "site")
        assert (tmp_path / "site" / "CNAME").read_text().strip() == buildlib.DOMAIN
        assert (tmp_path / "site" / ".nojekyll").exists()

    def test_the_link_preview_is_shipped_where_the_page_says_it_is(self, site, tmp_path):
        """A crawler reads og:image as an absolute URL, so the template spells
        the domain out. It has to be the one the build writes into CNAME, and the
        card has to be in the artifact at that path, or every shared link
        unfurls with a broken picture and nothing anywhere says so."""
        site.with_web()
        out = tmp_path / "site"
        buildlib.build(site.root, out)
        html = (out / "index.html").read_text()
        names = re.findall(r'<meta property="og:(?:image|url)" content="([^"]+)"', html)
        assert names == [f"https://{buildlib.DOMAIN}/", f"https://{buildlib.DOMAIN}/og.jpg"]
        assert (out / "og.jpg").read_bytes()[:2] == b"\xff\xd8", "a JPEG, as the name says"

    def test_crawlers_are_pointed_at_every_page_on_this_host(self, site, tmp_path):
        """robots.txt is per host, so the personal site's does not cover this
        one. The canonical, the sitemap and robots.txt all name the domain the
        build writes into CNAME, or Search Console files the page under a URL
        nothing serves."""
        site.with_web()
        out = tmp_path / "site"
        buildlib.build(site.root, out)
        home = f"https://{buildlib.DOMAIN}/"
        html = (out / "index.html").read_text()
        assert re.findall(r'<link rel="canonical" href="([^"]+)"', html) == [home]
        assert f"Sitemap: {home}sitemap.xml" in (out / "robots.txt").read_text()
        sitemap = (out / "sitemap.xml").read_text()
        assert re.findall(r"<loc>([^<]+)</loc>", sitemap) == [home, f"{home}wilbur/"]
        assert sitemap.count("<lastmod>2026-09-17</lastmod>") == 2

    def test_only_the_pictures_in_use_are_copied(self, site, tmp_path):
        did = dish_id("Roast Chicken")
        site.write_catalog({did: {"name": "Roast Chicken", "image": f"{did}.webp"}})
        site.write_image(f"{did}.webp")
        site.with_web()
        out = tmp_path / "site"
        buildlib.build(site.root, out)
        assert (out / "img" / f"{did}.webp").exists()

        # ...and one that falls off the menu is swept up rather than left to
        # accumulate in the artifact.
        (out / "img" / "stale.webp").write_bytes(b"x")
        buildlib.build(site.root, out)
        assert not (out / "img" / "stale.webp").exists()
        assert (out / "img" / f"{did}.webp").exists()


def _script_body(html: str, marker: str) -> dict:
    start = html.index(marker)
    body = html[html.index(">", start) + 1: html.index("</script>", start)]
    return json.loads(body.replace("<\\/", "</"))


class TestHallPages:
    """Every active hall has /<id>/: the same app opened on that hall, filed
    under its own URL, with the week written out for a crawler that runs no
    script. The official menu has no URL per hall, which is the opening."""

    @pytest.fixture
    def out(self, site, tmp_path):
        # Branner is in config and serving nothing this week; EVGR is not active.
        site.add_hall("branner", name="Branner Dining",
                      address="655 Escondido Rd, Stanford, CA 94305")
        site.add_hall("evgr", active=False)
        site.write_menu("2026-09-17", {"wilbur": {"Dinner": [
            dish("Roast Chicken", "chicken"), dish("Mac & Cheese", "pasta")]}})
        site.with_web()
        out = tmp_path / "site"
        buildlib.build(site.root, out)
        return out

    def test_every_active_hall_is_filed_under_its_own_url(self, out):
        """Serving this week or not: a page that vanished over a break would
        be dropped from the index and have to be found again."""
        home = f"https://{buildlib.DOMAIN}/"
        for hid in ("wilbur", "branner"):
            html = (out / hid / "index.html").read_text()
            assert re.findall(r'<link rel="canonical" href="([^"]+)"', html) == [f"{home}{hid}/"]
            assert re.findall(r'<meta property="og:url" content="([^"]+)"', html) == [f"{home}{hid}/"]
        assert not (out / "evgr").exists()
        assert re.findall(r"<loc>([^<]+)</loc>", (out / "sitemap.xml").read_text()) == \
            [home, f"{home}wilbur/", f"{home}branner/"]

    def test_a_hall_page_is_titled_for_the_search_it_answers(self, out):
        html = (out / "branner" / "index.html").read_text()
        assert "<title>Branner Dining Menu Today · Stanford Dining, Side by Side</title>" in html
        assert '<meta name="description" content="What Branner Dining at 655 Escondido Rd' in html

    def test_the_week_is_in_the_html_and_escaped(self, out):
        html = (out / "wilbur" / "index.html").read_text()
        start = html.index('id="prerender"')
        section = html[start: html.index("</section>", start)]
        assert "<h3>Thursday, September 17</h3>" in section
        assert "<h4>Dinner · 5pm–8pm</h4>" in section
        assert "<li>Roast Chicken</li>" in section
        assert "<li>Mac &amp; Cheese</li>" in section
        assert "Closed." in (out / "branner" / "index.html").read_text()
        # The home board writes nothing out, and the marker is gone either way.
        home = (out / "index.html").read_text()
        assert 'id="prerender"' not in home and "<!--PRERENDER-->" not in home

    def test_structured_data_describes_the_hall(self, out):
        ld = _script_body((out / "wilbur" / "index.html").read_text(), 'type="application/ld+json"')
        assert ld["@type"] == "FoodEstablishment"
        assert ld["url"] == f"https://{buildlib.DOMAIN}/wilbur/"
        items = [i["name"] for s in ld["hasMenu"]["hasMenuSection"] for i in s["hasMenuItem"]]
        assert items == ["Roast Chicken", "Mac & Cheese"]
        assert {o["validFrom"] for o in ld["openingHoursSpecification"]} == {"2026-09-17"}
        branner = _script_body((out / "branner" / "index.html").read_text(),
                               'type="application/ld+json"')
        assert (branner["address"]["streetAddress"], branner["address"]["postalCode"]) == \
            ("655 Escondido Rd", "94305")
        home = _script_body((out / "index.html").read_text(), 'type="application/ld+json"')
        assert home["@type"] == "WebSite"

    def test_the_page_tells_app_js_which_hall_and_how_far_down(self, out):
        """The pictures are relative paths, so a page one directory down has
        to say so; app.js prefixes every img/ and logo/ with `root`."""
        home = _script_body((out / "index.html").read_text(), 'id="menu-data"')
        wilbur = _script_body((out / "wilbur" / "index.html").read_text(), 'id="menu-data"')
        assert home["page"] == {"hall": None, "root": ""}
        assert wilbur["page"] == {"hall": "wilbur", "root": "../"}

    def test_the_footer_links_land_on_pages_the_build_wrote(self, out):
        for page in (out / "index.html", out / "wilbur" / "index.html"):
            html = page.read_text()
            links = re.findall(r'<a href="([^"]+/)">', html[html.index('class="foot-halls"'):])
            assert len(links) == 2
            for href in links:
                assert (page.parent / href / "index.html").resolve().exists(), href

    def test_a_hall_that_leaves_config_takes_its_page_with_it(self, site, out):
        site.halls = [h for h in site.halls if h["id"] != "branner"]
        site.save_config()
        buildlib.build(site.root, out)
        assert not (out / "branner").exists()
        assert (out / "wilbur" / "index.html").exists() and (out / "img").is_dir()
