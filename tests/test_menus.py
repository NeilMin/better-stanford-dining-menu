"""Which days a job reads, and the one definition of "today".

The split between live/ and archive/ decides what publishes, and `today()`
draws it. Both are cheap to get wrong in a way nothing else reports: a day
archived early is a day the board is short of, and a UTC reading does exactly
that every single night.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from bsdm import menus as menuslib


class TestToday:
    def test_is_pacific_not_utc(self, monkeypatch):
        """The nightly job runs at 06:20 UTC, which is still the previous day in
        California. Reading it as UTC would archive a day with forty minutes of
        dinner left to run."""
        class FixedDatetime:
            @staticmethod
            def now(tz):
                return datetime(2026, 9, 18, 6, 20, tzinfo=timezone.utc).astimezone(tz)

        monkeypatch.setattr(menuslib, "datetime", FixedDatetime)
        assert menuslib.today() == date(2026, 9, 17)

    def test_tz_is_the_halls_own(self):
        assert str(menuslib.TZ) == "America/Los_Angeles"


class TestLayout:
    def test_date_of_reads_the_stem(self, project):
        path = project.write_menu("2026-09-17", {})
        assert menuslib.date_of(path) == date(2026, 9, 17)

    def test_archive_path_is_nested_by_month(self, project):
        path = menuslib.archive_path(project.root, date(2026, 9, 17))
        assert path.relative_to(project.root).as_posix() == \
            "data/menus/archive/2026/09/2026-09-17.json"

    def test_live_path_is_flat(self, project):
        path = menuslib.live_path(project.root, date(2026, 9, 17))
        assert path.relative_to(project.root).as_posix() == "data/menus/live/2026-09-17.json"


class TestWindows:
    @pytest.fixture
    def stocked(self, project):
        project.set_today("2026-09-17")
        for day in ("2026-07-01", "2026-08-30", "2026-09-15", "2026-09-16"):
            project.archive_menu(day, {})
        for day in ("2026-09-17", "2026-09-18", "2026-09-19"):
            project.write_menu(day, {})
        return project

    def test_live_is_the_published_window_oldest_first(self, stocked):
        assert [p.stem for p in menuslib.live(stocked.root)] == \
            ["2026-09-17", "2026-09-18", "2026-09-19"]

    def test_archived_walks_every_month_oldest_first(self, stocked):
        assert [p.stem for p in menuslib.archived(stocked.root)] == \
            ["2026-07-01", "2026-08-30", "2026-09-15", "2026-09-16"]

    def test_history_is_everything_ever_stored(self, stocked):
        assert len(menuslib.history(stocked.root)) == 7
        # Archive first, so a replay walks the days in the order they happened.
        assert [p.stem for p in menuslib.history(stocked.root)][0] == "2026-07-01"

    def test_recent_is_bounded_but_always_keeps_live(self, stocked):
        """The window classification is judged over. Bounded so a nightly run
        costs the same in March as in September, and so a counter R&DE retires
        stops being called standing within a quarter."""
        got = [p.stem for p in menuslib.recent(stocked.root, days=3)]
        assert got == ["2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18", "2026-09-19"]

    def test_recent_cutoff_is_inclusive(self, stocked):
        got = [p.stem for p in menuslib.recent(stocked.root, days=2)]
        assert "2026-09-15" in got, "today - 2 days is inside the window, not outside it"

    def test_recent_default_reaches_two_months_back(self, stocked):
        got = [p.stem for p in menuslib.recent(stocked.root)]
        assert "2026-07-01" not in got and "2026-08-30" in got

    def test_no_job_globs_the_directory_itself(self, stocked):
        """A day in archive/ must never reach a caller that asked for live().
        The two live one predicate apart and only bsdm/menus.py may spell it."""
        assert set(menuslib.live(stocked.root)).isdisjoint(menuslib.archived(stocked.root))


class TestArchivePast:
    def test_moves_only_days_that_have_gone_by(self, project):
        project.set_today("2026-09-17")
        project.write_menu("2026-09-15", {})
        project.write_menu("2026-09-17", {})
        project.write_menu("2026-09-18", {})

        moved = menuslib.archive_past(project.root)

        assert [p.stem for p in moved] == ["2026-09-15"]
        assert [p.stem for p in menuslib.live(project.root)] == ["2026-09-17", "2026-09-18"]
        assert moved[0].relative_to(project.root).as_posix() == \
            "data/menus/archive/2026/09/2026-09-15.json"

    def test_is_idempotent(self, project):
        project.set_today("2026-09-17")
        project.write_menu("2026-09-15", {})
        menuslib.archive_past(project.root)
        assert menuslib.archive_past(project.root) == []

    def test_keeps_the_day_intact(self, project):
        project.set_today("2026-09-17")
        project.write_menu("2026-09-16", {"wilbur": {"Dinner": []}})
        before = (project.root / "data/menus/live/2026-09-16.json").read_text()
        moved = menuslib.archive_past(project.root)
        assert moved[0].read_text() == before
