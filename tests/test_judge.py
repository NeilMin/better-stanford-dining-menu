"""The judge: questions asked blind, answers compared here."""

from __future__ import annotations

import pytest

from bsdm import judge
from bsdm.llm import LLMError

BRIEF = {
    "dish": "miso-glazed black cod",
    "checks": [{"q": "Is the fish flesh white?", "yes": True},
               {"q": "Does it look like tofu?", "yes": False}],
}
# The brief's two, then recognition, platter, text.
ALL_RIGHT = ["yes", "no", "yes", "no", "no"]


def verdict(fake_llm, answers, seen="a glazed white fish fillet"):
    fake_llm.verdicts.append({"answers": answers, "seen": seen})
    return judge.inspect(b"picture", BRIEF, fake_llm)


def test_the_judge_is_not_told_which_answer_is_wanted(fake_llm):
    verdict(fake_llm, ALL_RIGHT)
    prompt = fake_llm.calls[-1][1]
    assert "Is the fish flesh white?" in prompt
    assert "true" not in prompt.lower() and "expected" not in prompt.lower()


def test_every_answer_as_expected_passes(fake_llm):
    v = verdict(fake_llm, ALL_RIGHT)
    assert v["pass"] and v["failed"] == []
    assert (v["seen"], v["judge"]) == ("a glazed white fish fillet", "fake")


def test_one_wrong_answer_fails_and_says_which(fake_llm):
    v = verdict(fake_llm, ["yes", "yes", "yes", "no", "no"], seen="a block of tofu in sauce")
    assert not v["pass"]
    assert v["failed"] == [{"q": "Does it look like tofu?", "expected": "no", "got": "yes"}]


def test_unclear_fails_a_defining_feature(fake_llm):
    """The picture has to show the dish, not merely fail to rule it out."""
    assert not verdict(fake_llm, ["unclear", "no", "yes", "no", "no"])["pass"]


def test_unclear_passes_a_mistake(fake_llm):
    """A mistake only counts if it can be seen."""
    assert verdict(fake_llm, ["yes", "unclear", "yes", "no", "no"])["pass"]


def test_recognition_fails_only_on_a_definite_no(fake_llm):
    assert verdict(fake_llm, ["yes", "no", "unclear", "no", "no"])["pass"]
    assert not verdict(fake_llm, ["yes", "no", "no", "no", "no"])["pass"]


def test_a_platter_or_text_fails_any_dish(fake_llm):
    assert not verdict(fake_llm, ["yes", "no", "yes", "yes", "no"])["pass"]
    assert not verdict(fake_llm, ["yes", "no", "yes", "no", "yes"])["pass"]


def test_answers_are_read_loosely(fake_llm):
    assert verdict(fake_llm, ["Yes.", "NO", "yes, clearly", "No", "no"])["pass"]


def test_the_wrong_number_of_answers_is_an_error_not_a_verdict(fake_llm):
    fake_llm.verdicts.append({"answers": ["yes"], "seen": "?"})
    with pytest.raises(LLMError):
        judge.inspect(b"picture", BRIEF, fake_llm)
