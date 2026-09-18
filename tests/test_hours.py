"""Fingerprinting the R&DE hours page.

The page is prose, so a parser for it would be guesswork that rots silently.
config/halls.json is transcribed by hand instead, and this watches for the day
the transcription goes stale.
"""

from __future__ import annotations

import json

from bsdm import hours as hourslib

PAGE = """<html><head><style>.x{color:red}</style></head><body>
<h1>Dining Locations &amp; Hours</h1>
<p>Fall Hours Begin Friday, September 18th</p>

<p>Arrillaga: Dinner 5:00pm - 8:00pm</p>
<script>analytics()</script>
<h2>Meet Your Dining Team</h2>
<p>Everything past here is promotional.</p>
</body></html>"""


class TestHoursText:
    def test_takes_the_hours_section_and_nothing_after_it(self):
        text = hourslib.fetch_hours_text(html=PAGE)
        assert text.startswith("Dining Locations & Hours")
        assert "Fall Hours Begin" in text
        assert "Meet Your Dining Team" not in text
        assert "promotional" not in text

    def test_drops_script_and_style(self):
        """Neither says anything about when a hall is open, and both change on
        their own schedule."""
        text = hourslib.fetch_hours_text(html=PAGE)
        assert "analytics" not in text and "color:red" not in text

    def test_collapses_the_blank_lines_the_markup_leaves(self):
        assert "\n\n" not in hourslib.fetch_hours_text(html=PAGE)

    def test_a_page_without_the_markers_is_kept_whole(self):
        """Better a fingerprint of too much than of nothing: the markers moving
        is itself a change worth being told about."""
        text = hourslib.fetch_hours_text(html="<html><body><p>Closed</p></body></html>")
        assert text == "Closed"


class TestCheck:
    def test_the_first_run_records_a_baseline(self, tmp_path):
        path = tmp_path / "hours_snapshot.json"
        result = hourslib.check(path, html=PAGE)
        assert result["first_run"] and not result["changed"]
        assert json.loads(path.read_text())["sha256"] == result["sha256"]

    def test_an_unchanged_page_is_quiet(self, tmp_path):
        path = tmp_path / "hours_snapshot.json"
        hourslib.check(path, html=PAGE)
        result = hourslib.check(path, html=PAGE)
        assert not result["changed"] and not result["first_run"]

    def test_a_changed_page_is_reported(self, tmp_path):
        path = tmp_path / "hours_snapshot.json"
        first = hourslib.check(path, html=PAGE)
        result = hourslib.check(path, html=PAGE.replace("5:00pm", "5:30pm"))
        assert result["changed"]
        assert result["previous_sha256"] == first["sha256"] != result["sha256"]

    def test_a_change_does_not_move_the_baseline_by_itself(self, tmp_path):
        """`make hours-accept` is a decision someone makes after editing
        config/halls.json, so the diff stays available until they do."""
        path = tmp_path / "hours_snapshot.json"
        hourslib.check(path, html=PAGE)
        before = path.read_text()
        hourslib.check(path, html=PAGE.replace("5:00pm", "5:30pm"))
        assert path.read_text() == before

    def test_accepting_it_does(self, tmp_path):
        path = tmp_path / "hours_snapshot.json"
        hourslib.check(path, html=PAGE)
        moved = PAGE.replace("5:00pm", "5:30pm")
        hourslib.check(path, html=moved, update=True)
        assert not hourslib.check(path, html=moved)["changed"]


def test_diff_says_so_when_there_is_no_baseline(tmp_path):
    assert hourslib.diff(tmp_path / "missing.json") == "(no snapshot yet)"
