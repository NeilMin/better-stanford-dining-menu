"""Scrape the R&DE dining hall menu app.

The app (https://rdeapps.stanford.edu/dininghallmenu/) is ASP.NET WebForms: the
three dropdowns drive a postback rather than a URL, so every query is a POST
carrying __VIEWSTATE / __EVENTVALIDATION harvested from the previous response.
Those tokens rotate on each response, so requests must be sequential.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field, asdict
from datetime import date, datetime

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

BASE_URL = "https://rdeapps.stanford.edu/dininghallmenu/"
MEALS = ("Breakfast", "Lunch", "Brunch", "Dinner")

# The dietary icons the app renders next to a dish, keyed by image basename.
ICON_TAGS = {
    "GF": "gluten-free",
    "V": "vegetarian",
    "VGN": "vegan",
    "H": "halal",
    "K": "kosher",
    "M": "mindful",
}


@dataclass
class Dish:
    name: str
    recipe_id: str = ""  # R&DE's own menu-item id, stable per hall
    description: str = ""
    ingredients: str = ""
    allergens: list[str] = field(default_factory=list)
    trace_allergens: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    order: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Service:
    """One hall's menu for one meal on one day."""

    hall: str  # menu_key
    day: str  # ISO date
    meal: str
    dishes: list[Dish] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "hall": self.hall,
            "day": self.day,
            "meal": self.meal,
            "dishes": [d.to_dict() for d in self.dishes],
        }


class MenuScraper:
    def __init__(self, delay: float = 0.4, timeout: int = 30):
        self.delay = delay
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["User-Agent"] = (
            "better-stanford-dining-menu/0.1 (personal menu viewer; "
            "https://github.com/NeilMin/better-stanford-dining-menu)"
        )
        self._state: dict[str, str] = {}
        self._last_html = ""

    # -- form plumbing -------------------------------------------------

    def _absorb(self, html: str) -> None:
        """Pull the rotating ASP.NET hidden fields out of a response."""
        self._last_html = html
        self._state = {
            m.group(1): m.group(2)
            for m in re.finditer(
                r'<input type="hidden" name="(__[A-Z]+)"[^>]*value="([^"]*)"', html
            )
        }

    def prime(self) -> None:
        r = self.session.get(BASE_URL, timeout=self.timeout)
        r.raise_for_status()
        self._absorb(r.text)

    def available_days(self) -> list[date]:
        """The rolling window the app offers, oldest first (today .. today+6)."""
        if not self._last_html:
            self.prime()
        soup = BeautifulSoup(self._last_html, "html.parser")
        sel = soup.find("select", id="MainContent_lstDay")
        days = []
        for opt in sel.find_all("option"):
            val = (opt.get("value") or "").strip()
            if val:
                days.append(datetime.strptime(val, "%m/%d/%Y").date())
        return sorted(days)

    def available_halls(self) -> list[str]:
        if not self._last_html:
            self.prime()
        soup = BeautifulSoup(self._last_html, "html.parser")
        sel = soup.find("select", id="MainContent_lstLocations")
        return [
            (o.get("value") or "").strip()
            for o in sel.find_all("option")
            if (o.get("value") or "").strip()
        ]

    # -- querying ------------------------------------------------------

    def fetch(self, hall: str, day: date, meal: str) -> Service:
        if not self._state:
            self.prime()
        payload = dict(self._state)
        payload.update(
            {
                "__EVENTTARGET": "GetMenulstMealType",
                "__EVENTARGUMENT": "",
                "ctl00$MainContent$lstLocations": hall,
                "ctl00$MainContent$lstDay": f"{day.month}/{day.day}/{day.year}",
                "ctl00$MainContent$lstMealType": meal,
            }
        )
        r = self.session.post(BASE_URL, data=payload, timeout=self.timeout)
        r.raise_for_status()
        self._absorb(r.text)
        time.sleep(self.delay)
        return Service(hall, day.isoformat(), meal, parse_dishes(r.text))


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _split_allergens(text: str) -> list[str]:
    """'MILK, WHEAT' -> ['MILK', 'WHEAT']."""
    return [a for a in (p.strip() for p in _clean(text).split(",")) if a]


def parse_dishes(html: str) -> list[Dish]:
    """Extract dishes from a menu response.

    A dish is one `li.clsMenuItem`; an empty list means the hall does not serve
    that meal that day (Casper and Branner never serve breakfast, and the
    'Brunch' option is vestigial -- weekend service is filed under 'Lunch').
    """
    soup = BeautifulSoup(html, "html.parser")
    dishes: list[Dish] = []

    for i, li in enumerate(soup.select("li.clsMenuItem")):
        name_el = li.select_one(".clsLabel_Name")
        if not name_el:
            continue
        name = _clean(name_el.get_text())
        if not name:
            continue

        dish = Dish(name=name, order=i)

        # R&DE tags each row with its own menu-item id. Two halls can run a
        # station of the same name with different ids, which is how "Panini
        # Station" at Arrillaga and at Branner are told apart.
        if fb := li.select_one("[id^='idFeedback_']"):
            dish.recipe_id = fb["id"].removeprefix("idFeedback_")

        if el := li.select_one(".clsLabel_Description"):
            dish.description = _clean(el.get_text())

        if el := li.select_one(".clsLabel_Ingredients"):
            # Drop the bold "Ingredients:" prefix span, keep the list.
            if label := el.select_one(".clsSectionName"):
                label.extract()
            dish.ingredients = _clean(el.get_text())

        if el := li.select_one(".clsLabel_Allergens"):
            if label := el.select_one(".clsSectionNameAllegens"):
                label.extract()
            dish.allergens = _split_allergens(el.get_text())

        if el := li.select_one(".clsLabel_TraceAllergens"):
            if label := el.select_one(".clsSectionNameAllegens"):
                label.extract()
            dish.trace_allergens = _split_allergens(el.get_text())

        # Icons look like images/icons/GF2.png -- strip the trailing variant digit.
        seen = []
        for img in li.select("img[src*='images/icons/']"):
            code = re.sub(r"\d+$", "", img["src"].rsplit("/", 1)[-1].rsplit(".", 1)[0])
            tag = ICON_TAGS.get(code.upper())
            if tag and tag not in seen:
                seen.append(tag)
        dish.tags = seen

        dishes.append(dish)

    return dishes
