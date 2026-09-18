"""What R&DE offered last night, and what about it needs a person.

A hall R&DE adds cannot be picked up automatically -- it needs a menu_key, a
schedule, aliases, an address and a crop box, and the dropdown carries one of
those -- so the scrape records what it saw and the nightly job ends by failing
on it. A warning in a green log is the silence we already had.
"""

from __future__ import annotations

from bsdm import source as sourcelib


def snapshot(project, halls, *, specials_url="https://x/p.pdf", window=("2026-09-17",)):
    return sourcelib.record(project.root, halls=list(halls), window=list(window),
                            specials_url=specials_url)


def covering_calendar(project, first="2026-09-14", last="2026-09-25"):
    project.write_specials({"url": "https://x/p.pdf", "meal": "Dinner",
                            "from": first, "to": last, "entries": []})


class TestRecord:
    def test_writes_down_what_the_source_offered(self, project):
        got = snapshot(project, ["Wilbur", "Arrillaga"], window=["2026-09-17", "2026-09-23"])
        assert got["halls"] == ["Arrillaga", "Wilbur"], "sorted, so a reorder is not a change"
        assert got["window"] == ["2026-09-17", "2026-09-23"]
        assert got["specials_url"] == "https://x/p.pdf"
        assert sourcelib.load(project.root) == got

    def test_an_empty_window_is_recorded_as_one(self, project):
        assert snapshot(project, ["Wilbur"], window=[])["window"] == []

    def test_nothing_has_looked_yet(self, project):
        assert sourcelib.load(project.root) == {}


class TestDrift:
    def test_a_normal_night_finds_nothing(self, project):
        project.set_today("2026-09-17")
        project.add_hall("wilbur", menu_key="Wilbur")
        snapshot(project, ["Wilbur"])
        assert sourcelib.drift(project.root, project.config) == []

    def test_no_snapshot_is_not_a_finding(self, project):
        """In CI this runs after the scrape, so an empty file is a local
        checkout, not a discovery."""
        project.add_hall("wilbur", menu_key="Wilbur")
        assert sourcelib.drift(project.root, project.config) == []

    def test_a_hall_config_has_never_heard_of(self, project):
        """No error, CI green, and seven days later its menus are gone for
        good -- which is the whole reason this exists."""
        project.set_today("2026-09-17")
        project.add_hall("wilbur", menu_key="Wilbur")
        snapshot(project, ["Wilbur", "Toyon"])
        found = sourcelib.drift(project.root, project.config)
        assert len(found) == 1 and "Toyon" in found[0]
        assert "menu_key" in found[0], "it says what a person has to write"

    def test_a_hall_config_switched_off_is_not_a_discovery(self, project):
        """EVGR sits in the dropdown while config has it inactive. Unknown is
        measured against every hall in config, active or not."""
        project.set_today("2026-09-17")
        project.add_hall("wilbur", menu_key="Wilbur")
        project.add_hall("evgr", menu_key="EVGR", active=False)
        snapshot(project, ["Wilbur", "EVGR"])
        assert sourcelib.drift(project.root, project.config) == []

    def test_a_hall_the_dropdown_no_longer_offers(self, project):
        """Missing is measured against the active halls only, for the same
        reason from the other side."""
        project.set_today("2026-09-17")
        project.add_hall("wilbur", menu_key="Wilbur")
        project.add_hall("stern", menu_key="Stern")
        snapshot(project, ["Wilbur"])
        found = sourcelib.drift(project.root, project.config)
        assert len(found) == 1 and "Stern" in found[0] and "active: false" in found[0]

    def test_an_inactive_hall_the_dropdown_dropped_too_is_silent(self, project):
        project.set_today("2026-09-17")
        project.add_hall("wilbur", menu_key="Wilbur")
        project.add_hall("evgr", menu_key="EVGR", active=False)
        snapshot(project, ["Wilbur"])
        assert sourcelib.drift(project.root, project.config) == []

    def test_a_poster_nobody_can_find(self, project):
        """Silent by nature: the hours page simply stops linking one, and an
        edition not saved while it is up is gone for good."""
        project.set_today("2026-09-17")
        project.add_hall("wilbur", menu_key="Wilbur")
        snapshot(project, ["Wilbur"], specials_url=None)
        found = sourcelib.drift(project.root, project.config)
        assert len(found) == 1 and "specials calendar" in found[0]

    def test_but_not_while_one_on_file_still_covers_today(self, project):
        """A fortnight with no specials at all is a normal thing for R&DE to
        publish, and the poster is only linked for its own fortnight."""
        project.set_today("2026-09-17")
        project.add_hall("wilbur", menu_key="Wilbur")
        covering_calendar(project)
        snapshot(project, ["Wilbur"], specials_url=None)
        assert sourcelib.drift(project.root, project.config) == []

    def test_a_calendar_that_has_run_out_does_not_cover_today(self, project):
        project.set_today("2026-09-17")
        project.add_hall("wilbur", menu_key="Wilbur")
        covering_calendar(project, "2026-08-03", "2026-08-14")
        snapshot(project, ["Wilbur"], specials_url=None)
        assert len(sourcelib.drift(project.root, project.config)) == 1

    def test_several_findings_are_all_reported(self, project):
        project.set_today("2026-09-17")
        project.add_hall("wilbur", menu_key="Wilbur")
        project.add_hall("stern", menu_key="Stern")
        snapshot(project, ["Wilbur", "Toyon"], specials_url=None)
        assert len(sourcelib.drift(project.root, project.config)) == 3
