"""The brief: what the writer is told, what it may answer, how it becomes a prompt."""

from __future__ import annotations

import json

import pytest

from bsdm import brief as brieflib
from bsdm import dishes as dishlib
from bsdm.brief import BriefError

GYRO = {
    "dish": "Greek gyro meat",
    "look": "thin shaved slices of beef and lamb, browned edges",
    "vessel": "plate",
    "avoid": ["pita bread", "ground meat"],
    "checks": [{"q": "Is the meat in thin slices?", "yes": True},
               {"q": "Is the meat ground?", "yes": False}],
}


def entry(name="Beef & Lamb Gyro Meat", ingredients="beef, lamb, salt, onion", tags=(), **kw):
    e = {"name": name, "ingredients": ingredients, "tags": list(tags)}
    e["category"] = dishlib.classify(e)
    return {**e, **kw}


class TestParse:
    def test_a_well_formed_answer(self):
        assert brieflib.parse(json.dumps(GYRO)) == GYRO

    def test_a_trailing_full_stop_is_dropped_from_look(self):
        """look is spliced into a comma-separated prompt."""
        assert brieflib.parse(json.dumps({**GYRO, "look": "sliced meat."}))["look"] == "sliced meat"

    @pytest.mark.parametrize("change", [
        {"look": ""},
        {"dish": None},
        {"vessel": "platter"},
        {"checks": []},
        {"checks": [{"q": "Is it meat?", "yes": "yes"}]},  # a string is not an expectation
    ])
    def test_what_cannot_be_drawn_or_judged_is_refused(self, change):
        with pytest.raises(BriefError):
            brieflib.parse(json.dumps({**GYRO, **change}))


class TestRequest:
    def test_the_writer_sees_what_you_could_see_not_the_seasoning(self):
        text = brieflib.write_request(entry())
        assert "Dish: Beef & Lamb Gyro Meat" in text
        assert "beef, lamb, onion" in text
        assert "salt" not in text.split("Reply with")[0]

    def test_the_hall_label_is_passed_on(self):
        text = brieflib.write_request(entry("Chana Masala", "chickpeas, tomato", tags=["vegan"]))
        assert "Dietary label from the hall: vegan" in text

    def test_a_special_says_it_has_only_a_name(self):
        text = brieflib.write_request(entry("Jerk Pork Belly", "", special=True))
        assert "only the name" in text


class TestWriteAndRevise:
    def test_a_written_brief_is_stamped(self, fake_llm):
        fake_llm.briefs.append(GYRO)
        b = brieflib.write(entry(), fake_llm)
        assert b["rev"] == brieflib.BRIEF_REV
        assert (b["model"], b["name"], b["revisions"]) == ("fake", "Beef & Lamb Gyro Meat", 0)

    def test_one_call_writes_several_briefs_in_order(self, fake_llm):
        lasagna = {**GYRO, "dish": "vegetable lasagna"}
        fake_llm.briefs += [GYRO, lasagna]
        dishes = [entry(), entry("Vegetable Lasagna", "pasta, ricotta", tags=["vegetarian"])]
        written = brieflib.write_many(dishes, fake_llm)
        assert len(fake_llm.calls) == 1
        prompt = fake_llm.calls[0][1]
        assert "[1]\nDish: Beef & Lamb Gyro Meat" in prompt and "[2]\nDish: Vegetable Lasagna" in prompt
        assert "Reply with this JSON object" not in prompt
        assert [b["dish"] for b in written] == ["Greek gyro meat", "vegetable lasagna"]
        assert [b["name"] for b in written] == ["Beef & Lamb Gyro Meat", "Vegetable Lasagna"]
        assert all(b["rev"] == brieflib.BRIEF_REV and b["revisions"] == 0 for b in written)

    def test_a_brief_the_batch_left_out_or_mangled_comes_back_none(self, fake_llm):
        fake_llm.briefs.append(json.dumps({"1": {**GYRO, "vessel": "tray"}, "3": GYRO}))
        written = brieflib.write_many([entry(), entry("Carnitas"), entry("Pozole")], fake_llm)
        assert written[:2] == [None, None]  # a vessel that is not one; no "2" at all
        assert written[2]["name"] == "Pozole"

    def test_a_revision_keeps_the_checks_whatever_the_writer_says(self, fake_llm):
        """A model asked to get past its own failed check will decide the check was wrong."""
        fake_llm.briefs.append(GYRO)
        first = brieflib.write(entry(), fake_llm)
        fake_llm.briefs.append({**GYRO, "look": "shaved gyro meat, no bread",
                                "checks": [{"q": "Is there food?", "yes": True}]})
        verdict = {"seen": "ground meat on a flatbread",
                   "failed": [{"q": "Is the meat ground?", "expected": "no", "got": "yes"}]}
        second = brieflib.revise(entry(), first, [verdict], fake_llm)

        assert second["checks"] == GYRO["checks"]
        assert second["look"] == "shaved gyro meat, no bread"
        assert second["revisions"] == 1
        request = fake_llm.calls[-1][1]
        assert "ground meat on a flatbread" in request
        assert '"Is the meat ground?" should be no, was yes' in request


    def test_a_check_no_picture_could_answer_may_be_reworded_keeping_its_answer(self, fake_llm):
        """"Is the meat pork?" cannot be settled by a photo of curry; left alone it
        holds the dish on its placeholder for good."""
        first = {**GYRO, "rev": brieflib.BRIEF_REV, "revisions": 0}
        unclear = {"seen": "meat in sauce",
                   "failed": [{"q": "Is the meat in thin slices?", "expected": "yes", "got": "unclear"}]}
        fake_llm.briefs.append({**GYRO, "rephrased": {
            "Is the meat in thin slices?": "Is the meat in long thin strips rather than chunks?",
            "Is the meat ground?": "Is it a burger?"}})
        second = brieflib.revise(entry(), first, [unclear, unclear], fake_llm)

        assert second["checks"][0] == {"q": "Is the meat in long thin strips rather than chunks?", "yes": True}
        assert second["checks"][1] == GYRO["checks"][1], "a check never answered unclear was rewritten"
        assert "could not be answered" in fake_llm.calls[-1][1]

    def test_a_check_once_answered_wrongly_is_never_reworded(self, fake_llm):
        first = {**GYRO, "rev": brieflib.BRIEF_REV, "revisions": 0}
        verdicts = [
            {"seen": "?", "failed": [{"q": "Is the meat in thin slices?", "expected": "yes", "got": "unclear"}]},
            {"seen": "mince", "failed": [{"q": "Is the meat in thin slices?", "expected": "yes", "got": "no"}]},
        ]
        fake_llm.briefs.append({**GYRO, "rephrased": {"Is the meat in thin slices?": "Is there meat?"}})
        second = brieflib.revise(entry(), first, verdicts, fake_llm)
        assert second["checks"] == GYRO["checks"]
        assert "could not be answered" not in fake_llm.calls[-1][1]


class TestCompose:
    def test_the_prompt_is_dish_then_look_then_the_house_style(self):
        positive, _ = brieflib.compose(entry(), GYRO)
        assert positive.startswith("Greek gyro meat, thin shaved slices of beef and lamb")
        assert positive.endswith(dishlib.photo_style(bowl=False))

    def test_a_bowl_brief_is_served_in_a_bowl(self):
        positive, _ = brieflib.compose(entry(), {**GYRO, "vessel": "bowl"})
        assert "white ceramic bowl" in positive

    def test_klein_is_told_to_fill_the_frame_and_sdxl_is_not(self):
        sdxl, _ = brieflib.compose(entry(), {**GYRO, "vessel": "bowl"})
        klein, _ = brieflib.compose(entry(), {**GYRO, "vessel": "bowl"}, close=True)
        assert "generous empty margin" in sdxl and "fills most of the frame" not in sdxl
        assert "the bowl fills most of the frame" in klein and "margin" not in klein

    def test_a_vegetarian_dish_excludes_meat_even_if_the_brief_forgot(self):
        veg = entry("Vegetable Lasagna", "pasta, ricotta, spinach", tags=["vegetarian"])
        _, negative = brieflib.compose(veg, {**GYRO, "avoid": ["soup"]})
        assert "soup" in negative
        assert "meat" in negative.split(", ")
        assert negative.endswith(dishlib.NEGATIVE_PROMPT)

    def test_a_term_is_named_once(self):
        veg = entry("Vegetable Lasagna", "pasta", tags=["vegetarian"])
        _, negative = brieflib.compose(veg, {**GYRO, "avoid": ["Meat", "meat"]})
        assert [t.lower() for t in negative.split(", ")].count("meat") == 1


class TestASpread:
    """"National Hispanic Heritage Month Dinner": a table of dishes, not a plate."""

    SPREAD = {**GYRO, "dish": "Latin American feast", "spread": True, "hand": True}

    def test_it_is_not_plated_on_one_white_plate(self):
        positive, _ = brieflib.compose(entry(), self.SPREAD)
        assert positive.endswith(dishlib.photo_style(bowl=False, spread=True))
        assert "plate" not in dishlib.photo_style(bowl=False, spread=True)

    def test_the_house_negative_no_longer_forbids_a_table_of_dishes(self):
        _, negative = brieflib.compose(entry(), self.SPREAD)
        for word in ("table spread", "feast", "multiple dishes", "duplicate plates"):
            assert word not in negative
        assert negative.endswith(dishlib.SPREAD_NEGATIVE_PROMPT)

    def test_every_other_dish_still_is(self):
        _, negative = brieflib.compose(entry(), GYRO)
        assert "table spread" in negative and "feast" in negative

    def test_the_rest_of_the_house_negative_is_kept(self):
        assert "watermark" in dishlib.SPREAD_NEGATIVE_PROMPT
        assert dishlib.NEGATIVE_PROMPT.startswith(dishlib.SPREAD_NEGATIVE_PROMPT)


def test_a_hand_written_brief_is_not_handed_back_to_a_model(fake_llm):
    """A new BRIEF_REV rewrites every brief a model wrote. This dish has only a
    name on the poster, and a model given only the name makes the dish up."""
    hand = {"rev": 1, "hand": True}
    assert brieflib.is_current(hand)
    assert not brieflib.is_current({"rev": 1})


def test_a_revision_keeps_a_brief_a_spread_and_by_hand(fake_llm):
    first = {**GYRO, "rev": brieflib.BRIEF_REV, "revisions": 0, "spread": True, "hand": True}
    fake_llm.briefs.append(GYRO)
    second = brieflib.revise(entry(), first, [{"seen": "?", "failed": []}], fake_llm)
    assert second["spread"] and second["hand"]


def test_record_merges_into_the_file_on_disk(tmp_path):
    """Like record_image(): a long run must not write back a stale copy."""
    brieflib.record(tmp_path, "a", {"dish": "one"})
    brieflib.record(tmp_path, "b", {"dish": "two"})
    brieflib.record(tmp_path, "a", {"dish": "one, again"})
    assert brieflib.load(tmp_path) == {"a": {"dish": "one, again"}, "b": {"dish": "two"}}


def test_a_brief_from_older_instructions_is_not_current():
    assert brieflib.is_current({"rev": brieflib.BRIEF_REV})
    assert not brieflib.is_current({"rev": brieflib.BRIEF_REV - 1})
    assert not brieflib.is_current(None)
