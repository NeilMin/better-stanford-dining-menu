"""The Chinese layer: names translated whole, ingredients term by term.

The tokenizer here is half of a pair -- web/app.js splits the same string again
to reassemble the list in the browser. tests/test_web_js.py holds the two
halves against each other; this file is about the table itself.
"""

from __future__ import annotations

import json

from bsdm import zh as zhlib

from conftest import dish


class TestTokenizer:
    def test_norm_collapses_whitespace_and_case(self):
        assert zhlib.norm("  Sea   SALT ") == "sea salt"

    def test_terms_in_drops_the_separators(self):
        assert zhlib.terms_in("rice, beans (black), corn") == ["rice", "beans", "black", "corn"]

    def test_terms_in_keeps_the_order_it_found_them(self):
        assert zhlib.terms_in("b, a, c") == ["b", "a", "c"]

    def test_terms_in_survives_unbalanced_punctuation(self):
        """A few R&DE strings open a parenthesis they never close, and one
        closes a bracket it never opened. The split is structure-free on
        purpose: every separator is translated where it stands."""
        assert zhlib.terms_in("cheese sauce (cheddar, milk") == ["cheese sauce", "cheddar", "milk"]
        assert zhlib.terms_in("rice] beans") == ["rice", "beans"]

    def test_terms_in_is_empty_for_nothing(self):
        assert zhlib.terms_in("") == [] and zhlib.terms_in(None) == []


class TestTable:
    def test_a_missing_file_still_has_every_section(self, project):
        table = zhlib.load(project.root)
        assert set(table) == set(zhlib.SECTIONS)

    def test_dishes_keep_their_english_alongside(self, project):
        """Keyed by id, so the English is what makes the file reviewable by
        hand. Terms are keyed by the English itself, and storing it twice
        would be noise."""
        table = zhlib.load(project.root)
        zhlib.put(table, "dishes", "abc123", "Roast Chicken", "烤鸡")
        zhlib.put(table, "terms", "salt", "salt", "盐")
        assert table["dishes"]["abc123"] == {"en": "Roast Chicken", "zh": "烤鸡"}
        assert table["terms"]["salt"] == "盐"

    def test_get_reads_both_shapes(self, project):
        table = {"dishes": {"a": {"en": "X", "zh": "烤鸡"}}, "terms": {"salt": "盐"}}
        assert zhlib.get(table, "dishes", "a") == "烤鸡"
        assert zhlib.get(table, "terms", "salt") == "盐"

    def test_an_untranslated_key_is_none_not_empty(self, project):
        table = {"terms": {"salt": ""}, "dishes": {"a": {"en": "X", "zh": ""}}}
        assert zhlib.get(table, "terms", "salt") is None
        assert zhlib.get(table, "dishes", "a") is None
        assert zhlib.get(table, "terms", "never seen") is None

    def test_save_round_trips_without_escaping_the_chinese(self, project):
        zhlib.save(project.root, {"terms": {"salt": "盐"}})
        assert "盐" in zhlib.path_for(project.root).read_text()
        assert zhlib.load(project.root)["terms"]["salt"] == "盐"


class TestMerge:
    def test_re_reads_the_table_rather_than_holding_it(self, project):
        """A first run is a couple of dozen model calls over several minutes.
        A wholesale write would drop whatever a hand edit added meanwhile."""
        zhlib.save(project.root, {"terms": {"salt": "盐"}})
        # ...as if someone corrected a translation while the run was going.
        table = zhlib.load(project.root)
        table["terms"]["pepper"] = "胡椒"
        zhlib.save(project.root, table)

        zhlib.merge(project.root, "terms", {"sugar": ("sugar", "糖")})

        got = zhlib.load(project.root)["terms"]
        assert got == {"salt": "盐", "pepper": "胡椒", "sugar": "糖"}

    def test_a_batch_lands_whole(self, project):
        zhlib.merge(project.root, "dishes", {
            "a": ("Roast Chicken", "烤鸡"), "b": ("Rice", "米饭")})
        assert len(zhlib.load(project.root)["dishes"]) == 2


class TestWanted:
    def stocked(self, project):
        project.add_hall("wilbur", concept="Home of the Kosher Kitchen")
        project.add_hall("stern", concept=None)
        project.write_catalog({"d1": {"name": "Roast Chicken"}, "d2": {"name": "Rice Pilaf"}})
        # An archived day as well as a live one: a term seen once and never
        # answered for has to stay on the list.
        project.archive_menu("2026-08-01", {"wilbur": {"Dinner": [
            dish("Gone Dish", "tamarind paste")]}})
        project.write_menu("2026-09-17", {"wilbur": {"Dinner": [
            dish("Roast Chicken", "chicken thigh, salt")]}})
        project.write_specials({"meal": "Dinner", "entries": [
            {"text": "Jerk Pork Belly", "from": "2026-09-15", "to": "2026-09-19",
             "halls": ["wilbur"], "label": "Wilbur"}]})
        return project

    def test_dish_names_come_from_the_catalog(self, project):
        want = zhlib.wanted(self.stocked(project).root)
        assert want["dishes"] == {"d1": "Roast Chicken", "d2": "Rice Pilaf"}

    def test_terms_come_from_every_menu_ever_stored(self, project):
        """Not the live window: a dropped batch would otherwise mean a term is
        silently never asked about again."""
        want = zhlib.wanted(self.stocked(project).root)
        assert "tamarind paste" in want["terms"], "an archived day still owes a translation"
        assert {"chicken thigh", "salt"} <= set(want["terms"])

    def test_only_halls_with_a_concept_line(self, project):
        want = zhlib.wanted(self.stocked(project).root)
        assert want["halls"] == {"wilbur": "Home of the Kosher Kitchen"}

    def test_specials_are_offered_whole(self, project):
        want = zhlib.wanted(self.stocked(project).root)
        assert want["specials"] == {"Jerk Pork Belly": "Jerk Pork Belly"}

    def test_missing_is_what_has_no_answer_yet(self, project):
        project = self.stocked(project)
        project.write_zh({"dishes": {"d1": {"en": "Roast Chicken", "zh": "烤鸡"}},
                          "terms": {}, "halls": {}, "specials": {}})
        missing = zhlib.missing(project.root)
        assert list(missing["dishes"]) == ["d2"]
        assert "salt" in missing["terms"]

    def test_summarize_counts_each_section(self, project):
        line = zhlib.summarize(self.stocked(project).root)
        assert line.startswith("Chinese: 0/2 dish names")
        assert "hall concepts" in line and "specials" in line
