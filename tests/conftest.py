"""A throwaway project root, shaped exactly like the real one.

Every module under bsdm/ takes a `root: Path` and reads config/ and data/ out of
it, which is the whole reason this can be tested without mocking a filesystem:
a test builds a miniature project on tmp_path and hands it the same paths the
nightly job would. What a test writes into it is the fixture; what it asserts is
what the code derived from that.

Two things are faked rather than built, because both are clocks:

    project.set_today(...)   pins bsdm.menus.today(), which decides what is live
                             and what is archived, and therefore what publishes.
    _frozen_now              keeps generated_at stamps out of the assertions.

Menus are written through `write_menu` / `archive_menu` rather than by globbing,
for the same reason bsdm/menus.py exists: live/ and archive/YYYY/MM/ are one
predicate apart and no test should be the second place that predicate is spelled.
"""

from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# Enough of a schedule to be open every day, so a test that is not about hours
# does not have to think about them.
ALL_DAY = {
    "from": "2000-01-01",
    "days": [0, 1, 2, 3, 4, 5, 6],
    "meals": {
        "Breakfast": ["07:30", "10:00"],
        "Lunch": ["11:00", "14:00"],
        "Dinner": ["17:00", "20:00"],
    },
}


def dish(name: str, ingredients: str = "", *, tags=(), allergens=(),
         trace=(), order: int = 0, recipe_id: str = "") -> dict:
    """One dish row, in the shape bsdm/scrape.py writes into data/menus/."""
    return {
        "name": name,
        "recipe_id": recipe_id,
        "description": "",
        "ingredients": ingredients,
        "allergens": list(allergens),
        "trace_allergens": list(trace),
        "tags": list(tags),
        "order": order,
    }


class Project:
    """A project root under construction. Mutating methods return self."""

    def __init__(self, root: Path, monkeypatch: pytest.MonkeyPatch):
        self.root = root
        self._monkeypatch = monkeypatch
        self.halls: list[dict] = []
        self.defaults = {"selected": [], "highlight": "meat"}
        for sub in ("config", "data/menus/live", "data/images", "data/logos"):
            (root / sub).mkdir(parents=True, exist_ok=True)
        self.save_config()

    # -- config ---------------------------------------------------------

    def add_hall(self, hall_id: str, *, menu_key: str | None = None,
                 short: str | None = None, name: str | None = None,
                 aliases=(), active: bool = True, concept=None,
                 schedules=None, accent: str = "#cccccc",
                 address: str = "1 Campus Drive") -> "Project":
        self.halls.append({
            "id": hall_id,
            "menu_key": menu_key or hall_id.title(),
            "aliases": list(aliases),
            "name": name or f"{hall_id.title()} Dining Commons",
            "short": short or hall_id.title(),
            "address": address,
            "concept": concept,
            "active": active,
            "accent": accent,
            "schedules": [dict(ALL_DAY)] if schedules is None else schedules,
        })
        if active and len(self.defaults["selected"]) < 3:
            self.defaults["selected"].append(hall_id)
        return self.save_config()

    def save_config(self) -> "Project":
        (self.root / "config" / "halls.json").write_text(json.dumps(
            {"halls": self.halls, "defaults": self.defaults}, indent=1))
        return self

    @property
    def config(self) -> dict:
        return json.loads((self.root / "config" / "halls.json").read_text())

    # -- menus ----------------------------------------------------------

    def _menu_payload(self, day: str, halls: dict) -> str:
        return json.dumps({"date": day, "scraped_at": f"{day}T23:20:00-07:00",
                           "halls": halls}, indent=1) + "\n"

    def write_menu(self, day: str, halls: dict) -> Path:
        """A day in live/ -- what the board publishes."""
        path = self.root / "data" / "menus" / "live" / f"{day}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self._menu_payload(day, halls))
        return path

    def archive_menu(self, day: str, halls: dict) -> Path:
        """A day in archive/YYYY/MM/ -- what has passed."""
        path = self.root / "data" / "menus" / "archive" / day[:4] / day[5:7] / f"{day}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self._menu_payload(day, halls))
        return path

    # -- derived data ---------------------------------------------------

    def write_stations(self, table: dict | None = None, **by_hall) -> "Project":
        """Either a whole table, or stations(hall={meal: [names]}) shorthand."""
        if table is None:
            table = {"computed_at": "2026-09-17T23:20:00-07:00", "days_analyzed": 7,
                     "threshold": 0.6, "min_services": 4, "halls": {}}
            for hall, meals in by_hall.items():
                table["halls"][hall] = {
                    meal: {"services_observed": 7, "stations": {n: 1.0 for n in names}}
                    for meal, names in meals.items()
                }
        self._write_json("data/stations.json", table)
        return self

    def write_catalog(self, catalog: dict) -> "Project":
        self._write_json("data/dishes.json", catalog)
        return self

    def write_specials(self, *calendars: dict) -> "Project":
        self._write_json("data/specials.json", {"calendars": list(calendars)})
        return self

    def write_zh(self, table: dict) -> "Project":
        self._write_json("data/zh.json", table)
        return self

    def write_image(self, name: str) -> Path:
        """A file where a picture goes. build.py only checks that it exists."""
        path = self.root / "data" / "images" / name
        path.write_bytes(b"RIFF----WEBPVP8 ")
        return path

    def _write_json(self, rel: str, payload) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n")
        return path

    def with_web(self) -> "Project":
        """The real templates, for tests that render the page."""
        shutil.copytree(REPO / "web", self.root / "web")
        return self

    # -- the clock ------------------------------------------------------

    def set_today(self, day: str | date) -> "Project":
        """Pin the day the halls are serving.

        Patched in bsdm.source as well as bsdm.menus: source.py imports the name
        rather than the module, so patching one place would leave it reading the
        real calendar and make a specials-coverage test fail in the future.
        """
        from bsdm import menus as menuslib
        from bsdm import source as sourcelib

        value = day if isinstance(day, date) else date.fromisoformat(day)
        self._monkeypatch.setattr(menuslib, "today", lambda: value)
        self._monkeypatch.setattr(sourcelib, "today", lambda: value)
        return self


def load_script(name: str):
    """Import one of scripts/*.py by path.

    They are entry points rather than a package -- each puts the repo on
    sys.path itself -- so there is nothing importable to name. Their module
    globals (ROOT, CATALOG) are what a test patches to point them at tmp_path.
    """
    import importlib.util

    path = REPO / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"bsdm_scripts_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Project:
    return Project(tmp_path / "root", monkeypatch)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test may reach R&DE.

    Every fetch in this project has an injection point -- `html=` on the hours
    and specials paths, a session on the scraper, a blob on the logo cutter --
    and a test that quietly used the real one would be slow, flaky, and a
    request to somebody else's server on every run. Refusing at the socket is
    what keeps that honest.
    """
    import socket

    def refuse(*args, **kwargs):
        raise AssertionError(
            "a test opened a network connection. Pass the fixture in instead: "
            "html= on hours/specials, a fake session on MenuScraper, blob= on logos.")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture
def repo() -> Path:
    """The real checkout, for the golden tests that read committed artefacts."""
    return REPO
