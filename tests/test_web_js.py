"""The half of the project that runs in the browser.

Two tokenizers split the same ingredient string: bsdm/zh.py decides which terms
to send for translation, web/app.js splits it again to reassemble the list in
Chinese. They have to agree exactly. When they do not, the page asks the table
for a term that was never offered, and the failure shows up as one stray
English word in the middle of a Chinese sentence -- not as an error anywhere.
"""

from __future__ import annotations

import json

import pytest

from bsdm import zh as zhlib

from jsbridge import NODE, call

pytestmark = [pytest.mark.node,
              pytest.mark.skipif(NODE is None, reason="needs node to run web/app.js")]

# Real ingredient strings, including the ones that are not well-formed. R&DE
# emits a few that open a parenthesis and never close it, and one that closes a
# bracket it never opened, which is why neither side parses a tree.
INGREDIENTS = [
    "steel cut oats",
    "rice, beans (black), corn",
    "cheese sauce (cheddar cheese (milk, cultures), cream), macaroni",
    "chicken breast, canola/olive oil blend, salt",
    "**No onion, no garlic** tofu, rice",
    "cheese sauce (cheddar, milk",
    "rice] beans",
    "  SEA   SALT  ,  Water ",
    "",
    "tomato sauce (tomato, basil), [organic] spinach",
]


def js_terms(strings, tmp_path):
    """What app.js would look up, for each string: its ZH_TERMS keys in order."""
    return call(
        ["ZH_PUNCT", "zhIngredients"],
        "return INPUT.map((text) => { LOOKED_UP.length = 0; zhIngredients(text); "
        "return LOOKED_UP.slice(); });",
        payload=strings,
        prelude=("const LOOKED_UP = [];\n"
                 "const ZH_TERMS = { get: (k) => { LOOKED_UP.push(k); return undefined; } };"),
        tmp_path=tmp_path,
    )


class TestTokenizerMirror:
    def test_both_sides_split_the_same_string_the_same_way(self, tmp_path):
        """Same separators, same key: whitespace collapsed, lowercased."""
        assert js_terms(INGREDIENTS, tmp_path) == [zhlib.terms_in(s) for s in INGREDIENTS]

    def test_the_page_only_ever_asks_for_a_key_python_offered(self, tmp_path):
        """The asymmetry that matters. A term the browser splits out but Python
        never sent for translation is a hole the table can never fill."""
        for text, looked_up in zip(INGREDIENTS, js_terms(INGREDIENTS, tmp_path)):
            assert set(looked_up) <= set(zhlib.terms_in(text)), text


class TestChineseReassembly:
    def render(self, text, table, tmp_path):
        return call(
            ["ZH_PUNCT", "zhIngredients"],
            "return zhIngredients(INPUT);",
            payload=text,
            prelude=f"const ZH_TERMS = new Map(Object.entries({json.dumps(table)}));",
            tmp_path=tmp_path,
        )

    def test_the_list_comes_back_with_chinese_punctuation(self, tmp_path):
        table = {"rice": "米饭", "beans": "豆子", "black": "黑色"}
        got = self.render("rice, beans (black)", table, tmp_path)
        assert got == "米饭、豆子（黑色）"

    def test_a_bracket_is_rendered_as_a_parenthesis(self, tmp_path):
        got = self.render("rice [black]", {"rice": "米饭", "black": "黑色"},
                          tmp_path)
        assert got == "米饭（黑色）"

    def test_an_untranslated_term_keeps_its_english(self, tmp_path):
        """One stray English word in a Chinese list, rather than a hole in it."""
        got = self.render("rice, tamarind paste", {"rice": "米饭"}, tmp_path)
        assert got == "米饭、tamarind paste"

    def test_the_lookup_is_case_and_whitespace_insensitive(self, tmp_path):
        got = self.render("  SEA   SALT ", {"sea salt": "海盐"}, tmp_path)
        assert got == "海盐"


class TestPureHelpers:
    def test_hours_read_the_way_each_language_writes_them(self, tmp_path):
        got = call(["fmtTime"], "return INPUT.map((t) => fmtTime(t));",
                   payload=["07:30", "11:00", "17:00", "12:00", "20:30", "00:00"],
                   prelude="const state = { lang: 'en' };", tmp_path=tmp_path)
        assert got == ["7:30am", "11am", "5pm", "12pm", "8:30pm", "12am"]

    def test_chinese_keeps_the_twenty_four_hour_clock(self, tmp_path):
        """Which "17:00" already is."""
        got = call(["fmtTime"], "return INPUT.map((t) => fmtTime(t));",
                   payload=["07:30", "17:00"],
                   prelude="const state = { lang: 'zh' };", tmp_path=tmp_path)
        assert got == ["7:30", "17:00"]

    def test_a_wordmark_gives_up_height_where_a_roundel_does_not(self, tmp_path):
        """The logos run from Branner's roundel to Lakeside's 5:1 wordmark. One
        height for all of them makes the wordmarks run long."""
        got = call(["LOGO", "logoSize"], "return INPUT.map((r) => logoSize(r));",
                   payload=[0.75, 1.0, 5.0], tmp_path=tmp_path)
        roundel, square, wordmark = got
        assert roundel[1] >= square[1] >= wordmark[1], "taller shapes keep more height"
        assert all(w <= 80 and h <= 36 for w, h in got), "nothing pushes into the name"

    def test_the_first_visit_opens_in_the_browsers_language(self, tmp_path):
        """Chinese for a browser that asks for Chinese first, English for every
        other answer -- including a browser that asks for a language the page
        does not speak, and one that offers English ahead of Chinese."""
        got = call(["preferredLang"],
                   "return INPUT.map((asked) => { navigator = { languages: asked, "
                   "language: asked[0] }; return preferredLang(); });",
                   payload=[["zh-CN", "en-US"],
                            ["zh-Hans"],
                            ["ZH"],
                            ["en-US", "zh-CN"],
                            ["fr-FR"],
                            [],
                            [None]],
                   prelude="let navigator;\nconst UI = { en: {}, zh: {} };",
                   tmp_path=tmp_path)
        assert got == ["zh", "zh", "zh", "en", "en", "en", "en"]

    def test_the_pinned_hall_row_shows_only_while_a_board_is_under_it(self, tmp_path):
        """It stands in for the headers, so it appears when they have gone under
        the top bar -- and goes again at the bottom, where a strip left hanging
        over the footer would be naming columns that are no longer on screen."""
        got = call(["pinsFit"], "return INPUT.map((a) => pinsFit(...a));",
                   # line, strip height, where the headers end, where the board does
                   payload=[[56, 48, 300, 4000],
                            [56, 48, 56, 4000],
                            [56, 48, -900, 104],
                            [56, 48, -900, 90]],
                   tmp_path=tmp_path)
        assert got == [False, True, True, False]

    def test_a_dish_matches_a_diet_only_by_carrying_every_tag(self, tmp_path):
        got = call(["matchesDiet"], "return INPUT.map((tags) => matchesDiet({ tags }));",
                   payload=[["vegan", "halal"], ["vegan"], []],
                   prelude="const state = { diet: ['vegan', 'halal'] };", tmp_path=tmp_path)
        assert got == [True, False, False]

    def test_open_soon_and_shut_are_read_off_the_viewers_clock(self, tmp_path):
        """A tab left open overnight must not keep calling yesterday "Today",
        so the comparison is against the browser's own time, not build time."""
        prelude = ("const TODAY = '2026-09-17';\n"
                   "Date = class extends Date { constructor() { super('2026-09-17T17:30'); } };")
        got = call(["serviceStatus"],
                   "return INPUT.map(([d, s]) => serviceStatus(d, s));",
                   payload=[["2026-09-17", ["17:00", "20:00"]],
                            ["2026-09-17", ["18:30", "20:00"]],
                            ["2026-09-17", ["07:30", "10:00"]],
                            ["2026-09-18", ["17:00", "20:00"]],
                            ["2026-09-17", None]],
                   prelude=prelude, tmp_path=tmp_path)
        assert got == ["open", "soon", "shut", None, None]


def test_the_stored_preferences_key_is_versioned(tmp_path):
    """Bumped whenever the persisted shape changes. Stale localStorage once
    looked exactly like a scraper bug."""
    import re

    from jsbridge import APP_JS

    match = re.search(r'const STORE = "bsdm\.prefs\.v(\d+)"', APP_JS.read_text())
    assert match and int(match.group(1)) >= 1
