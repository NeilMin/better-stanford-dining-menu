"""Reading R&DE's menu app.

It is ASP.NET WebForms: the dropdowns drive a postback rather than a URL, so
every query is a POST carrying __VIEWSTATE / __EVENTVALIDATION harvested from
the previous response. A sequencing fault does not error -- it returns the
previous hall's menu, which is why scripts/verify.py exists.
"""

from __future__ import annotations

from datetime import date

import pytest

from bsdm import scrape as scrapelib


def menu_item(name, *, recipe_id="3849426", description="", ingredients=None,
              allergens=None, trace=None, icons=()):
    parts = [f'<span class="clsLabel_Name">{name}</span>',
             f'<a id="idFeedback_{recipe_id}" href="#">feedback</a>']
    if description:
        parts.append(f'<div class="clsLabel_Description">{description}</div>')
    if ingredients:
        parts.append('<div class="clsLabel_Ingredients">'
                     '<span class="clsSectionName">Ingredients:</span> '
                     f'{ingredients}</div>')
    if allergens:
        parts.append('<div class="clsLabel_Allergens">'
                     '<span class="clsSectionNameAllegens">Allergens:</span> '
                     f'{allergens}</div>')
    if trace:
        parts.append('<div class="clsLabel_TraceAllergens">'
                     '<span class="clsSectionNameAllegens">Trace:</span> '
                     f'{trace}</div>')
    for icon in icons:
        parts.append(f'<img src="images/icons/{icon}.png" alt="{icon}">')
    return '<li class="clsMenuItem">' + "".join(parts) + "</li>"


def page(*items, days=("9/17/2026", "9/18/2026"), halls=("Arrillaga", "Wilbur"),
         viewstate="VS1"):
    options = "".join(f'<option value="{d}">{d}</option>' for d in days)
    locations = "".join(f'<option value="{h}">{h}</option>' for h in halls)
    return f"""<html><body><form>
<input type="hidden" name="__VIEWSTATE" id="__VIEWSTATE" value="{viewstate}" />
<input type="hidden" name="__EVENTVALIDATION" id="__EVENTVALIDATION" value="EV1" />
<select name="ctl00$MainContent$lstDay" id="MainContent_lstDay">
  <option value="">-- pick --</option>{options}</select>
<select name="ctl00$MainContent$lstLocations" id="MainContent_lstLocations">
  <option value="">-- pick --</option>{locations}</select>
<ul>{"".join(items)}</ul>
</form></body></html>"""


class TestParseDishes:
    def test_one_li_is_one_dish(self):
        dishes = scrapelib.parse_dishes(page(menu_item("Roast Chicken"),
                                             menu_item("Steamed Rice")))
        assert [d.name for d in dishes] == ["Roast Chicken", "Steamed Rice"]

    def test_menu_position_is_recorded(self):
        """R&DE lists the day's entrees first, which is what decides priority
        and beats any guess made from the name."""
        dishes = scrapelib.parse_dishes(page(menu_item("A"), menu_item("B"), menu_item("C")))
        assert [d.order for d in dishes] == [0, 1, 2]

    def test_the_ingredients_label_is_not_an_ingredient(self):
        dishes = scrapelib.parse_dishes(page(menu_item("Pilaf", ingredients="rice, stock")))
        assert dishes[0].ingredients == "rice, stock"

    def test_allergens_are_split_into_a_list(self):
        dishes = scrapelib.parse_dishes(page(
            menu_item("Pasta", allergens="MILK, WHEAT", trace="SOY")))
        assert dishes[0].allergens == ["MILK", "WHEAT"]
        assert dishes[0].trace_allergens == ["SOY"]

    def test_a_dish_with_no_allergens_gets_an_empty_list(self):
        assert scrapelib.parse_dishes(page(menu_item("Rice")))[0].allergens == []

    def test_the_recipe_id_tells_two_halls_counters_apart(self):
        """"Panini Station" at Arrillaga and at Branner are different rows."""
        dishes = scrapelib.parse_dishes(page(menu_item("Panini Station", recipe_id="99")))
        assert dishes[0].recipe_id == "99"

    def test_the_dietary_icons_become_tags(self):
        dishes = scrapelib.parse_dishes(page(
            menu_item("Tofu", icons=["VGN2", "GF", "H"])))
        assert dishes[0].tags == ["vegan", "gluten-free", "halal"]

    def test_the_same_icon_twice_is_one_tag(self):
        """The app renders the icon beside the name and again in the detail."""
        dishes = scrapelib.parse_dishes(page(menu_item("Tofu", icons=["VGN", "VGN2"])))
        assert dishes[0].tags == ["vegan"]

    def test_an_icon_we_do_not_know_is_left_out(self):
        assert scrapelib.parse_dishes(page(menu_item("Tofu", icons=["XYZ"])))[0].tags == []

    def test_whitespace_is_collapsed(self):
        dishes = scrapelib.parse_dishes(page(menu_item("Roast \n   Chicken ")))
        assert dishes[0].name == "Roast Chicken"

    def test_a_row_with_no_name_is_not_a_dish(self):
        assert scrapelib.parse_dishes('<li class="clsMenuItem"><span>x</span></li>') == []
        assert scrapelib.parse_dishes(page(menu_item(" "))) == []

    def test_a_meal_a_hall_does_not_serve_is_an_empty_list(self):
        """Casper and Branner never serve breakfast, and "Brunch" is vestigial
        -- weekend service is filed under Lunch."""
        assert scrapelib.parse_dishes(page()) == []

    def test_a_dish_round_trips_to_the_dict_stored_on_disk(self):
        dish = scrapelib.parse_dishes(page(menu_item(
            "Pilaf", ingredients="rice", allergens="WHEAT", icons=["V"])))[0]
        assert dish.to_dict() == {
            "name": "Pilaf", "recipe_id": "3849426", "description": "",
            "ingredients": "rice", "allergens": ["WHEAT"], "trace_allergens": [],
            "tags": ["vegetarian"], "order": 0,
        }


class TestDropdowns:
    @pytest.fixture
    def primed(self):
        scraper = scrapelib.MenuScraper(delay=0)
        scraper._absorb(page())
        return scraper

    def test_the_rolling_window_is_read_off_the_day_dropdown(self, primed):
        assert primed.available_days() == [date(2026, 9, 17), date(2026, 9, 18)]

    def test_the_window_comes_back_oldest_first(self):
        scraper = scrapelib.MenuScraper(delay=0)
        scraper._absorb(page(days=("9/19/2026", "9/17/2026")))
        assert scraper.available_days()[0] == date(2026, 9, 17)

    def test_what_the_location_dropdown_is_offering(self, primed):
        """Recorded every night, because a hall config has never heard of is
        invisible to the scrape itself."""
        assert primed.available_halls() == ["Arrillaga", "Wilbur"]

    def test_the_placeholder_option_is_not_a_hall(self, primed):
        assert "" not in primed.available_halls()

    def test_the_rotating_tokens_are_absorbed(self, primed):
        assert primed._state == {"__VIEWSTATE": "VS1", "__EVENTVALIDATION": "EV1"}


class TestFetch:
    class FakeSession:
        """Stands in for requests.Session, recording what was posted."""

        def __init__(self, responses):
            self.responses = list(responses)
            self.posts = []
            self.headers = {}

        def post(self, url, data, timeout):
            self.posts.append(data)
            return self.Response(self.responses.pop(0))

        class Response:
            def __init__(self, text):
                self.text = text

            def raise_for_status(self):
                pass

    def test_the_query_is_the_three_dropdowns_plus_the_tokens(self):
        """Not a URL. A hall, a day and a meal, carried in a postback."""
        scraper = scrapelib.MenuScraper(delay=0)
        scraper._absorb(page())
        scraper.session = self.FakeSession([page(menu_item("Roast Chicken"))])

        service = scraper.fetch("Wilbur", date(2026, 9, 17), "Dinner")

        posted = scraper.session.posts[0]
        assert posted["ctl00$MainContent$lstLocations"] == "Wilbur"
        assert posted["ctl00$MainContent$lstDay"] == "9/17/2026"
        assert posted["ctl00$MainContent$lstMealType"] == "Dinner"
        assert posted["__EVENTTARGET"] == "GetMenulstMealType"
        assert posted["__VIEWSTATE"] == "VS1"
        assert (service.hall, service.day, service.meal) == ("Wilbur", "2026-09-17", "Dinner")
        assert [d.name for d in service.dishes] == ["Roast Chicken"]

    def test_the_tokens_rotate_with_every_response(self):
        """Which is why the scrape is sequential: a request built from a stale
        token does not error, it answers with the previous hall's menu."""
        scraper = scrapelib.MenuScraper(delay=0)
        scraper._absorb(page(viewstate="VS1"))
        scraper.session = self.FakeSession([page(viewstate="VS2"), page(viewstate="VS3")])

        scraper.fetch("Wilbur", date(2026, 9, 17), "Dinner")
        scraper.fetch("Stern", date(2026, 9, 17), "Dinner")

        assert [p["__VIEWSTATE"] for p in scraper.session.posts] == ["VS1", "VS2"]

    def test_a_service_round_trips_to_the_dict_stored_on_disk(self):
        scraper = scrapelib.MenuScraper(delay=0)
        scraper._absorb(page())
        scraper.session = self.FakeSession([page(menu_item("Rice", ingredients="rice"))])
        payload = scraper.fetch("Wilbur", date(2026, 9, 17), "Dinner").to_dict()
        assert payload["hall"] == "Wilbur" and payload["day"] == "2026-09-17"
        assert payload["dishes"][0]["name"] == "Rice"
