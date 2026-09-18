"""The specials calendar: finding it, filing it, and reading it back out.

The poster is the one input with no second chance -- the hours page links a
fortnight at a time, so an edition nobody fetched while it was up is gone,
which is worse than the menus, which at least have a rolling week. Everything
here is built around that: archive first, parse second, and never raise.
"""

from __future__ import annotations

import datetime as dt

import pytest

from bsdm import specials as specialslib


@pytest.fixture
def halls(project):
    project.add_hall("arrillaga", short="Arrillaga", name="Arrillaga Family Dining Commons",
                     aliases=["AFDC"])
    project.add_hall("wilbur", short="Wilbur", name="Wilbur Dining")
    project.add_hall("florencemoore", short="FloMo", name="Florence Moore Dining",
                     aliases=["Florence Moore"])
    return project


class TestLabels:
    def test_every_name_a_hall_answers_to(self, halls):
        table = specialslib.alias_table(halls.config)
        for label in ("arrillaga", "Arrillaga", "AFDC", "afdc",
                      "Arrillaga Family Dining Commons"):
            assert specialslib.resolve_halls(label, table) == ["arrillaga"]

    def test_matching_ignores_case_and_punctuation(self, halls):
        """Which is why only genuinely different words belong in `aliases`."""
        table = specialslib.alias_table(halls.config)
        assert specialslib.resolve_halls("Florence-Moore", table) == ["florencemoore"]
        assert specialslib.resolve_halls("FLO MO", table) == ["florencemoore"]

    @pytest.mark.parametrize("label", ["Stern & Wilbur", "Stern/Wilbur", "Stern, Wilbur",
                                       "Stern and Wilbur", "Stern | Wilbur"])
    def test_a_list_of_halls_is_split_however_it_is_written(self, halls, label):
        halls.add_hall("stern")
        table = specialslib.alias_table(halls.config)
        assert specialslib.resolve_halls(label, table) == ["stern", "wilbur"]

    def test_all_or_nothing(self, halls):
        """"Traditional Thanksgiving Dinner at all Dining Halls" must stay a
        campus-wide note rather than be filed under whichever word matched."""
        table = specialslib.alias_table(halls.config)
        assert specialslib.resolve_halls("Traditional Thanksgiving Dinner at all "
                                         "Dining Halls", table) == []
        assert specialslib.resolve_halls("Wilbur & The Moon", table) == []

    def test_a_hall_named_twice_is_listed_once(self, halls):
        table = specialslib.alias_table(halls.config)
        assert specialslib.resolve_halls("Wilbur & Wilbur", table) == ["wilbur"]

    def test_an_empty_label_names_nothing(self, halls):
        assert specialslib.resolve_halls("   ", specialslib.alias_table(halls.config)) == []


class TestFindLink:
    def page(self, *links):
        return "<html><body>" + "".join(
            f'<a href="{href}">{text}</a>' for href, text in links) + "</body></html>"

    def test_finds_the_poster_by_the_words_in_it(self):
        html = self.page(("/files/Dining%20Hall%20Specials%20Calendar_Sept14-25.pdf", "Specials"))
        assert specialslib.find_link(html).endswith("Calendar_Sept14-25.pdf")

    def test_a_link_that_says_calendar_too_wins_outright(self):
        """R&DE also publishes special-diet guidance, which says "special"
        without being the poster."""
        html = self.page(("/files/special-diets.pdf", "Special Diets"),
                         ("/files/specials-calendar.pdf", "Dining Hall Specials Calendar"))
        assert specialslib.find_link(html).endswith("specials-calendar.pdf")

    def test_relative_links_are_resolved_against_the_page(self):
        got = specialslib.find_link(self.page(("/sites/x/specials.pdf", "Specials")))
        assert got.startswith("https://rde.stanford.edu/")

    def test_a_query_string_does_not_hide_the_extension(self):
        html = self.page(("/files/specials.pdf?t=17263", "Specials Calendar"))
        assert specialslib.find_link(html) is not None

    def test_only_pdfs(self):
        assert specialslib.find_link(self.page(("/specials-calendar.html", "Specials"))) is None

    def test_nothing_linked_is_not_an_error(self):
        assert specialslib.find_link(self.page(("/menus.pdf", "Menus"))) is None


class TestArchiveName:
    def test_filed_under_the_fortnight_it_covers(self):
        got = specialslib._archive_name(
            "https://x/Dining%20Hall%20Specials%20Calendar_Sept14-25.pdf",
            {"from": "2026-09-14"})
        assert got == "2026/09/2026-09-14_Dining-Hall-Specials-Calendar-Sept14-25.pdf"

    def test_a_cache_buster_is_not_part_of_the_name(self):
        got = specialslib._archive_name("https://x/specials.pdf?t=17263", {"from": "2026-09-14"})
        assert got == "2026/09/2026-09-14_specials.pdf"

    def test_an_unreadable_edition_goes_in_undated(self):
        """It has no dates to file it under, and it is still the only copy that
        will ever exist."""
        assert specialslib._archive_name("https://x/specials.pdf", None) == \
            "undated/undated_specials.pdf"


class TestAttachHalls:
    def test_a_hall_label_narrows_the_text_to_the_dish(self, halls):
        """The column already says which hall it is."""
        entries = [{"label": "Wilbur", "text": "Wilbur: Garlic Noodles", "dish": "Garlic Noodles"}]
        got = specialslib.attach_halls(entries, specialslib.alias_table(halls.config))
        assert got[0]["halls"] == ["wilbur"] and got[0]["text"] == "Garlic Noodles"
        assert "dish" not in got[0]

    def test_a_sentence_that_happens_to_contain_a_colon_keeps_all_of_it(self, halls):
        entries = [{"label": "Reminder", "text": "Reminder: closed Friday", "dish": "closed Friday"}]
        got = specialslib.attach_halls(entries, specialslib.alias_table(halls.config))
        assert got[0]["halls"] == [] and got[0]["text"] == "Reminder: closed Friday"

    def test_an_entry_with_no_colon_at_all(self, halls):
        entries = [{"label": None, "text": "Thanksgiving Day Dinner", "dish": None}]
        got = specialslib.attach_halls(entries, specialslib.alias_table(halls.config))
        assert got[0]["halls"] == [] and got[0]["text"] == "Thanksgiving Day Dinner"


def calendar(*entries, meal="Dinner"):
    return {"url": "https://x/p.pdf", "meal": meal, "from": entries[0]["from"],
            "to": entries[-1]["to"], "entries": list(entries)}


def entry(text, first, last, halls=()):
    return {"text": text, "from": first, "to": last, "halls": list(halls), "label": None}


class TestForWindow:
    WINDOW = ["2026-09-17", "2026-09-18", "2026-09-19"]

    def test_a_run_is_expanded_to_the_days_inside_the_window(self, project):
        project.write_specials(calendar(entry("Esquite Fries", "2026-09-14", "2026-09-18",
                                              ["stern"])))
        got = specialslib.for_window(project.root, self.WINDOW)
        assert sorted(got) == ["2026-09-17", "2026-09-18"]
        assert got["2026-09-17"]["halls"] == {"stern": ["Esquite Fries"]}
        assert got["2026-09-17"]["meal"] == "Dinner"

    def test_an_entry_no_hall_claims_is_a_campus_wide_note(self, project):
        project.write_specials(calendar(entry("Thanksgiving Day Dinner",
                                              "2026-09-18", "2026-09-18")))
        got = specialslib.for_window(project.root, self.WINDOW)
        assert got["2026-09-18"]["notes"] == ["Thanksgiving Day Dinner"]
        assert got["2026-09-18"]["halls"] == {}

    def test_a_hall_announcing_it_has_none_is_not_put_on_the_board(self, project):
        """A hall with no special and a hall saying it has none look the same
        to someone deciding where to eat."""
        project.write_specials(calendar(
            entry("No Dinner Special this week", "2026-09-17", "2026-09-18", ["arrillaga"])))
        assert specialslib.for_window(project.root, self.WINDOW) == {}

    def test_every_calendar_on_file_is_consulted(self, project):
        """A window can straddle two fortnights, and the archive keeps the ones
        that have rolled off the page."""
        project.write_specials(
            calendar(entry("Old Special", "2026-09-15", "2026-09-17", ["stern"])),
            calendar(entry("New Special", "2026-09-18", "2026-09-25", ["stern"])),
        )
        got = specialslib.for_window(project.root, self.WINDOW)
        assert got["2026-09-17"]["halls"]["stern"] == ["Old Special"]
        assert got["2026-09-18"]["halls"]["stern"] == ["New Special"]

    def test_the_same_text_twice_is_listed_once(self, project):
        project.write_specials(
            calendar(entry("Garlic Noodles", "2026-09-17", "2026-09-17", ["wilbur"])),
            calendar(entry("Garlic Noodles", "2026-09-17", "2026-09-18", ["wilbur"])),
        )
        got = specialslib.for_window(project.root, self.WINDOW)
        assert got["2026-09-17"]["halls"]["wilbur"] == ["Garlic Noodles"]

    def test_an_empty_window_asks_for_nothing(self, project):
        project.write_specials(calendar(entry("X", "2026-09-17", "2026-09-17", ["stern"])))
        assert specialslib.for_window(project.root, []) == {}

    def test_no_calendar_on_file_is_not_an_error(self, project):
        assert specialslib.for_window(project.root, self.WINDOW) == {}


class TestDishes:
    def test_only_the_ones_a_hall_serves(self, project):
        """Notes are announcements, not food."""
        project.write_specials(calendar(
            entry("Esquite Fries", "2026-09-14", "2026-09-18", ["stern"]),
            entry("Traditional Thanksgiving Dinner", "2026-09-20", "2026-09-20"),
        ))
        assert [d["text"] for d in specialslib.dishes(project.root)] == ["Esquite Fries"]

    def test_a_dish_that_runs_twice_keeps_the_whole_span(self, project):
        project.write_specials(
            calendar(entry("Garlic Noodles", "2025-11-17", "2025-11-19", ["wilbur"])),
            calendar(entry("Garlic Noodles", "2025-11-21", "2025-11-21", ["wilbur"])),
        )
        got = specialslib.dishes(project.root)
        assert got == [{"text": "Garlic Noodles", "from": "2025-11-17", "to": "2025-11-21"}]

    def test_a_hall_announcing_no_special_is_not_a_dish(self, project):
        project.write_specials(calendar(
            entry("No Dinner Special this week", "2026-09-17", "2026-09-18", ["arrillaga"])))
        assert specialslib.dishes(project.root) == []


class TestTexts:
    def test_every_distinct_special_and_note(self, project):
        project.write_specials(calendar(
            entry("Esquite Fries", "2026-09-14", "2026-09-18", ["stern"]),
            entry("Thanksgiving Day Dinner", "2026-09-20", "2026-09-20"),
            entry("Esquite Fries", "2026-09-21", "2026-09-25", ["stern"]),
            entry("No Dinner Special this week", "2026-09-21", "2026-09-25", ["arrillaga"]),
        ))
        assert specialslib.texts(project.root) == ["Esquite Fries", "Thanksgiving Day Dinner"]


class TestUpdate:
    HTML = '<a href="https://rde.stanford.edu/f/specials-calendar.pdf">Specials Calendar</a>'

    @pytest.fixture
    def downloads(self, monkeypatch):
        def install(blob):
            monkeypatch.setattr(specialslib, "download", lambda url, timeout=60: blob)
        return install

    def test_an_unreadable_poster_is_still_archived(self, halls, downloads, monkeypatch):
        """The hours page only ever points at the current fortnight, so an
        edition we cannot read is still the only copy that will exist."""
        downloads(b"%PDF-1.4 but not really")
        result = specialslib.update(halls.root, halls.config, html=self.HTML)

        assert result["status"] == "unreadable" and result["error"]
        archived = specialslib.archive_dir(halls.root) / result["file"]
        assert archived.read_bytes() == b"%PDF-1.4 but not really"
        assert archived.parent.name == "undated"

    def test_an_unreadable_poster_does_not_raise(self, halls, downloads):
        """scripts/update.py logs it and carries on with the night's menus. A
        poster R&DE has reshaped must not cost us a night of them."""
        downloads(b"nonsense")
        specialslib.update(halls.root, halls.config, html=self.HTML)
        stored = specialslib.load(halls.root)["calendars"][0]
        assert "error" in stored and stored["file"].startswith("undated/")

    def test_a_readable_poster_is_folded_in(self, halls, downloads, monkeypatch):
        downloads(b"pdf bytes")
        monkeypatch.setattr(specialslib, "parse", lambda blob: {
            "title": "DINNER SPECIALS FOR SEPTEMBER 14 - 25, 2026", "meal": "Dinner",
            "from": "2026-09-14", "to": "2026-09-25",
            "entries": [{"label": "AFDC", "text": "AFDC: Jerk Pork Belly",
                         "dish": "Jerk Pork Belly", "from": "2026-09-15", "to": "2026-09-18"}],
        })
        result = specialslib.update(halls.root, halls.config, html=self.HTML)

        assert result["status"] == "new" and result["placed"] == 1
        assert result["unplaced_labels"] == []
        assert (specialslib.archive_dir(halls.root)
                / "2026/09/2026-09-14_specials-calendar.pdf").exists()
        stored = specialslib.load(halls.root)["calendars"][0]
        assert stored["entries"][0]["halls"] == ["arrillaga"]
        assert stored["entries"][0]["text"] == "Jerk Pork Belly"

    def test_a_label_matching_no_hall_is_reported_not_swallowed(self, halls, downloads,
                                                                monkeypatch):
        downloads(b"pdf bytes")
        monkeypatch.setattr(specialslib, "parse", lambda blob: {
            "title": "t", "meal": "Dinner", "from": "2026-09-14", "to": "2026-09-25",
            "entries": [{"label": "Toyon", "text": "Toyon: Something",
                         "dish": "Something", "from": "2026-09-15", "to": "2026-09-18"}],
        })
        result = specialslib.update(halls.root, halls.config, html=self.HTML)
        assert result["unplaced_labels"] == ["Toyon"]

    def test_the_same_bytes_twice_is_not_refetched_work(self, halls, downloads, monkeypatch):
        downloads(b"pdf bytes")
        monkeypatch.setattr(specialslib, "parse", lambda blob: {
            "title": "t", "meal": "Dinner", "from": "2026-09-14", "to": "2026-09-25",
            "entries": [],
        })
        specialslib.update(halls.root, halls.config, html=self.HTML)
        again = specialslib.update(halls.root, halls.config, html=self.HTML)
        assert again["status"] == "unchanged"
        assert len(specialslib.load(halls.root)["calendars"]) == 1

    def test_no_link_on_the_page_is_reported_not_raised(self, halls):
        result = specialslib.update(halls.root, halls.config, html="<html></html>")
        assert result == {"url": None, "status": "no link on the hours page"}

    def test_calendars_are_stored_in_date_order(self, halls, downloads, monkeypatch):
        for n, (url, start) in enumerate([("b.pdf", "2026-09-14"), ("a.pdf", "2026-08-03")]):
            downloads(f"pdf {n}".encode())
            monkeypatch.setattr(specialslib, "parse", lambda blob, s=start: {
                "title": "t", "meal": "Dinner", "from": s, "to": s, "entries": []})
            specialslib.update(halls.root, halls.config,
                               html=f'<a href="https://rde.stanford.edu/{url}">Specials</a>')
        stored = specialslib.load(halls.root)["calendars"]
        assert [c["from"] for c in stored] == ["2026-08-03", "2026-09-14"]
