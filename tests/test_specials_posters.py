"""The geometry reader, held against every poster in the archive.

Text order in the PDF is meaningless -- one entry's two lines are not adjacent
in it, and a note drawn on top of a row reads as part of that row -- so the
reader groups text by which coloured bar contains it. The only honest test of
that is the real editions, which is what data/specials/ already is.

Five editions spanning a year are documented as parsing; whichever ones are
committed are the ones checked here, so adding a poster to the archive extends
this test by itself.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest

from bsdm import specials as specialslib

pytestmark = pytest.mark.golden


def posters(repo):
    return sorted(specialslib.archive_dir(repo).glob("*/*/*.pdf"))


@pytest.fixture(scope="module")
def parsed(request):
    """Every archived poster, read once for the whole module."""
    repo = request.path.parent.parent
    out = {}
    for path in posters(repo):
        out[path.name] = specialslib.parse(path.read_bytes())
    assert out, "no posters in data/specials/ -- run `make specials`"
    return out


def test_the_archive_is_not_empty(repo):
    assert posters(repo), "data/specials/ is the only copy of a poster that will ever exist"


def test_every_edition_still_parses(parsed):
    """A reshaped poster is the failure this is watching for. Five editions
    spanning a year all parse; check a new one with --dry-run before assuming
    a change is a bug."""
    assert len(parsed) >= 3
    for name, calendar in parsed.items():
        assert calendar["entries"], name


def test_every_edition_is_a_dated_fortnight(parsed):
    for name, calendar in parsed.items():
        first = dt.date.fromisoformat(calendar["from"])
        last = dt.date.fromisoformat(calendar["to"])
        assert 0 < (last - first).days <= 20, name
        assert calendar["meal"] in ("Breakfast", "Brunch", "Lunch", "Dinner"), name


def test_no_special_ever_runs_on_a_weekend(parsed):
    """Which is the whole reason bars can be told from the grid: every
    background stripe spans the full width, and no special has ever run on a
    Saturday. A weekend date here means furniture was read as a bar."""
    for name, calendar in parsed.items():
        for entry in calendar["entries"]:
            for key in ("from", "to"):
                day = dt.date.fromisoformat(entry[key])
                assert day.weekday() <= 4, f"{name}: {entry['text'][:40]} on a {day:%A}"


def test_every_entry_falls_inside_the_fortnight(parsed):
    for name, calendar in parsed.items():
        for entry in calendar["entries"]:
            assert calendar["from"] <= entry["from"] <= entry["to"] <= calendar["to"], name


def test_every_hall_label_resolves(parsed, repo):
    """config/halls.json's `aliases` is ground truth for this one job:
    matching the names the poster uses. An unplaced label is a special that
    silently never reaches the board."""
    config = json.loads((repo / "config" / "halls.json").read_text())
    table = specialslib.alias_table(config)
    for name, calendar in parsed.items():
        entries = specialslib.attach_halls(json.loads(json.dumps(calendar["entries"])), table)
        unplaced = sorted({e["label"] for e in entries if e["label"] and not e["halls"]})
        assert unplaced == [], f"{name}: add an alias in config/halls.json"


class TestSeptember2026:
    """One edition read line by line, because a count is not a reading."""

    @pytest.fixture
    def calendar(self, parsed):
        return next(c for n, c in parsed.items() if "Sept14-25" in n)

    def test_the_title_gives_the_meal_and_the_fortnight(self, calendar):
        assert calendar["meal"] == "Dinner"
        assert (calendar["from"], calendar["to"]) == ("2026-09-14", "2026-09-25")

    def test_a_bar_drawn_over_a_row_does_not_shorten_the_one_beneath(self, calendar):
        """Stern runs the whole week; the other halls reopened on the Tuesday
        and the poster says so in a block drawn over the top."""
        stern = next(e for e in calendar["entries"] if e["label"] == "Stern"
                     and e["from"] == "2026-09-14")
        assert stern["text"] == "Stern: Esquite fries" and stern["to"] == "2026-09-18"
        afdc = next(e for e in calendar["entries"] if e["label"] == "AFDC"
                    and e["from"].startswith("2026-09-1"))
        assert afdc["from"] == "2026-09-15"

    def test_an_entrys_two_lines_are_joined(self, calendar):
        """They are not adjacent in the PDF's text order. The bar is what says
        they belong together."""
        afdc = next(e for e in calendar["entries"] if e["label"] == "AFDC"
                    and e["from"] == "2026-09-15")
        assert afdc["text"].startswith("AFDC: Chicken Tikka Masala")
        assert "Steamed Basmati Rice" in afdc["text"]


class TestNovember2025:
    """The awkward one: a Thanksgiving band drawn across the middle of a week,
    a hall that announces it has no special, and R&DE's own typo."""

    @pytest.fixture
    def calendar(self, parsed):
        return next(c for n, c in parsed.items() if "Nov17-28" in n)

    def test_a_note_drawn_on_top_of_a_row_is_its_own_entry(self, calendar):
        """Smallest bar wins. Read by text order it would be glued onto
        whichever special it interrupts."""
        note = next(e for e in calendar["entries"]
                    if e["text"].startswith("Traditional Thanksgiving"))
        assert note["label"] is None
        assert note["from"] == note["to"] == "2025-11-20"

    def test_a_row_the_note_interrupts_is_split_in_two(self, calendar):
        runs = sorted((e["from"], e["to"]) for e in calendar["entries"]
                      if e["label"] == "Stern" and "Causa" in e["text"])
        assert runs == [("2025-11-17", "2025-11-19"), ("2025-11-21", "2025-11-21")], \
            "one dish, two bars, because Thursday belongs to the band drawn over it"

    def test_a_hall_announcing_no_special_is_still_recorded(self, calendar):
        """Kept, because it is what the poster says -- and filtered out again
        on the way to the board."""
        assert any("No Dinner Special" in e["text"] for e in calendar["entries"])

    def test_the_typo_r_and_de_keeps_remaking(self, calendar, repo):
        config = json.loads((repo / "config" / "halls.json").read_text())
        table = specialslib.alias_table(config)
        assert any(e["label"] == "WIlbur" for e in calendar["entries"])
        assert specialslib.resolve_halls("WIlbur", table) == ["wilbur"]


def test_a_note_is_recorded_once_however_many_rows_it_crosses(parsed):
    for name, calendar in parsed.items():
        keys = [(e["text"], e["from"], e["to"]) for e in calendar["entries"]]
        assert len(keys) == len(set(keys)), name
