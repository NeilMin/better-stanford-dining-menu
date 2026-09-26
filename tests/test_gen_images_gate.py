"""The loop in gen_images.py: brief, draw, judge, revise -- and never keep a failure.

The old gate kept the best of three failures and, when it could not judge at
all, kept whatever it had drawn. These pin the opposite: a picture is written
only after it passes, and a dish nothing passes for keeps its placeholder.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from PIL import Image

from bsdm import brief as brieflib
from bsdm.llm import LLMError, Unavailable
from scripts import gen_images
from scripts.gen_images import main

BRIEF = {
    "dish": "roast chicken", "look": "golden roast chicken pieces, crisp skin", "vessel": "plate",
    "avoid": ["beef"], "checks": [{"q": "Is it chicken?", "yes": True}],
}
PASS = {"answers": ["yes", "yes", "no", "no"], "seen": "roast chicken on a plate"}
FAIL = {"answers": ["no", "no", "no", "no"], "seen": "a beef steak"}


@pytest.fixture
def setup(tmp_path, monkeypatch, fake_llm):
    root = tmp_path / "project"
    (root / "data" / "images").mkdir(parents=True)
    catalog = {
        "aaaa0001": {"name": "Roast Chicken", "ingredients": "chicken, rosemary", "tags": [],
                     "category": "poultry", "prompt": "rule-based roast chicken prompt",
                     "negative": "rule negative", "priority": 0, "min_order": 0,
                     "needs_image": True, "image": None},
        "bbbb0002": {"name": "Steamed Broccoli", "ingredients": "broccoli", "tags": ["vegan"],
                     "category": "vegan", "prompt": "rule-based broccoli prompt",
                     "negative": "rule negative", "priority": 2, "min_order": 5,
                     "needs_image": True, "image": None},
    }
    (root / "data" / "dishes.json").write_text(json.dumps(catalog))
    monkeypatch.setattr(gen_images, "ROOT", root)
    monkeypatch.setattr(gen_images, "CATALOG", root / "data" / "dishes.json")
    monkeypatch.setattr(gen_images, "IMAGES", root / "data" / "images")

    drawn = []
    comfy = MagicMock()
    comfy.available.return_value = True

    def generate(model, positive, negative, seed, steps=None):
        drawn.append({"positive": positive, "negative": negative, "seed": seed})
        return Image.new("RGB", (1344, 768), "orange"), 0.1

    comfy.generate.side_effect = generate
    monkeypatch.setattr(gen_images, "ComfyClient", lambda *a, **kw: comfy)
    cf = MagicMock()
    cf.is_configured.return_value = False
    monkeypatch.setattr(gen_images, "CloudflareClient", lambda *a, **kw: cf)
    monkeypatch.setattr(gen_images, "pick_llm", lambda *a, **kw: fake_llm)

    class Setup:
        pass

    s = Setup()
    s.root, s.drawn, s.llm, s.comfy = root, drawn, fake_llm, comfy
    s.catalog = lambda: json.loads((root / "data" / "dishes.json").read_text())
    s.image = lambda did: root / "data" / "images" / f"{did}.webp"
    return s


def run(*args):
    return main(["--backend", "comfyui", "--only", "Roast Chicken", *args])


def test_a_picture_that_passes_is_kept_with_its_verdict(setup):
    setup.llm.briefs.append(BRIEF)
    setup.llm.verdicts.append(PASS)
    assert run() == 0

    entry = setup.catalog()["aaaa0001"]
    assert setup.image("aaaa0001").exists()
    assert entry["image"] == "aaaa0001.webp"
    assert entry["judge"]["seen"] == "roast chicken on a plate"
    assert entry["brief_rev"] == brieflib.BRIEF_REV
    assert entry["seed"] == gen_images.seed_for("aaaa0001")
    assert brieflib.load(setup.root)["aaaa0001"]["dish"] == "roast chicken"
    assert setup.drawn[0]["positive"].startswith("roast chicken, golden roast chicken pieces")


def test_a_failed_picture_is_drawn_again_with_another_seed(setup):
    setup.llm.briefs.append(BRIEF)
    setup.llm.verdicts += [FAIL, PASS]
    run()
    seeds = [d["seed"] for d in setup.drawn]
    assert len(seeds) == 2 and seeds[0] != seeds[1]
    assert setup.catalog()["aaaa0001"]["seed"] == seeds[1]


def test_when_nothing_passes_nothing_is_written(setup):
    """The placeholder icon is less wrong than a wrong picture."""
    setup.llm.briefs += [BRIEF, {**BRIEF, "look": "whole roast chicken, golden skin"}]
    setup.llm.verdicts += [FAIL, FAIL, FAIL, FAIL]
    assert run("--attempts", "2", "--revisions", "1") == 0

    entry = setup.catalog()["aaaa0001"]
    assert not setup.image("aaaa0001").exists()
    assert entry["image"] is None
    assert entry["rejected"]["pictures"] == 4
    assert entry["rejected"]["seen"] == "a beef steak"
    brief = brieflib.load(setup.root)["aaaa0001"]
    assert brief["revisions"] == 1 and brief["look"] == "whole roast chicken, golden skin"
    assert brief["checks"] == BRIEF["checks"]
    assert setup.drawn[2]["positive"].startswith("roast chicken, whole roast chicken")


def test_a_redraw_that_fails_leaves_the_old_picture_alone(setup):
    old = setup.image("aaaa0001")
    Image.new("RGB", (1024, 576), "blue").save(old, format="WEBP")
    before = old.read_bytes()
    catalog = setup.catalog()
    catalog["aaaa0001"]["image"] = "aaaa0001.webp"
    (setup.root / "data" / "dishes.json").write_text(json.dumps(catalog))

    setup.llm.briefs += [BRIEF, BRIEF]
    setup.llm.verdicts += [FAIL] * 4
    run("--force")
    assert old.read_bytes() == before
    assert setup.catalog()["aaaa0001"]["image"] == "aaaa0001.webp"


def test_a_picture_the_judge_could_not_read_is_not_kept(setup):
    setup.llm.briefs.append(BRIEF)
    setup.llm.verdicts += [LLMError("garbled"), PASS]
    run()
    assert len(setup.drawn) == 2
    assert setup.catalog()["aaaa0001"]["seed"] == setup.drawn[1]["seed"]


def test_a_spent_subscription_stops_the_run_and_keeps_nothing_unjudged(setup):
    setup.llm.briefs.append(BRIEF)
    setup.llm.verdicts.append(Unavailable("usage limit reached"))
    assert main(["--backend", "comfyui"]) == 0
    assert len(setup.drawn) == 1, "went on drawing pictures nobody could judge"
    assert not setup.image("aaaa0001").exists()


def test_without_the_claude_cli_nothing_is_drawn(setup, monkeypatch):
    monkeypatch.setattr(gen_images, "pick_llm", lambda *a, **kw: type(setup.llm)(available=False))
    assert run() == 2
    assert setup.drawn == []


def test_no_judge_without_claude_draws_once_from_the_rule_prompt(setup, monkeypatch):
    monkeypatch.setattr(gen_images, "pick_llm", lambda *a, **kw: type(setup.llm)(available=False))
    assert run("--no-judge") == 0
    assert [d["positive"] for d in setup.drawn] == ["rule-based roast chicken prompt"]
    entry = setup.catalog()["aaaa0001"]
    assert entry["image"] == "aaaa0001.webp" and "judge" not in entry


def test_a_kept_picture_drops_the_old_gates_fields(setup):
    catalog = setup.catalog()
    catalog["aaaa0001"].update(vlm_score=3, vlm_reason="looks like beef", rejected={"at": "x"})
    (setup.root / "data" / "dishes.json").write_text(json.dumps(catalog))
    setup.llm.briefs.append(BRIEF)
    setup.llm.verdicts.append(PASS)
    run()
    entry = setup.catalog()["aaaa0001"]
    assert not {"vlm_score", "vlm_reason", "rejected"} & set(entry)


def test_a_current_brief_is_reused_not_rewritten(setup):
    brieflib.record(setup.root, "aaaa0001", {**BRIEF, "rev": brieflib.BRIEF_REV, "revisions": 0})
    setup.llm.verdicts.append(PASS)
    run()
    assert [kind for kind, _ in setup.llm.calls] == ["judge"]


def _with_old_picture(setup, **fields):
    old = setup.image("aaaa0001")
    Image.new("RGB", (1024, 576), "blue").save(old, format="WEBP")
    catalog = setup.catalog()
    catalog["aaaa0001"].update(image="aaaa0001.webp", **fields)
    (setup.root / "data" / "dishes.json").write_text(json.dumps(catalog))
    return old, old.read_bytes()


def test_audit_keeps_an_old_picture_that_passes_and_draws_nothing(setup):
    old, before = _with_old_picture(setup)
    setup.llm.briefs.append(BRIEF)
    setup.llm.verdicts.append(PASS)
    assert run("--audit") == 0
    assert setup.drawn == []
    assert old.read_bytes() == before
    assert setup.catalog()["aaaa0001"]["judge"]["seen"] == "roast chicken on a plate"


def test_audit_redraws_an_old_picture_that_fails(setup):
    old, before = _with_old_picture(setup)
    setup.llm.briefs.append(BRIEF)
    setup.llm.verdicts += [FAIL, PASS]
    run("--audit")
    assert len(setup.drawn) == 1
    assert old.read_bytes() != before
    assert setup.catalog()["aaaa0001"]["judge"]["seen"] == "roast chicken on a plate"


def test_audit_leaves_a_picture_a_judge_has_already_passed(setup):
    _with_old_picture(setup, judge={"judge": "fake", "seen": "chicken", "at": "x"})
    assert run("--audit") == 0
    assert setup.llm.calls == [] and setup.drawn == []


def test_a_dish_that_failed_three_runs_is_left_alone(setup):
    """Four drawings a night, for ever, out of a free allocation."""
    catalog = setup.catalog()
    catalog["aaaa0001"]["rejected"] = {"tries": gen_images.MAX_TRIES, "brief_rev": brieflib.BRIEF_REV}
    (setup.root / "data" / "dishes.json").write_text(json.dumps(catalog))
    assert run() == 0
    assert setup.drawn == [] and setup.llm.calls == []


def test_new_brief_rules_or_a_flag_give_it_another_go(setup):
    catalog = setup.catalog()
    catalog["aaaa0001"]["rejected"] = {"tries": gen_images.MAX_TRIES, "brief_rev": brieflib.BRIEF_REV - 1}
    (setup.root / "data" / "dishes.json").write_text(json.dumps(catalog))
    setup.llm.briefs.append(BRIEF)
    setup.llm.verdicts.append(PASS)
    run()
    assert len(setup.drawn) == 1


def test_each_failed_run_counts(setup):
    setup.llm.briefs += [BRIEF, BRIEF]
    setup.llm.verdicts += [FAIL] * 4
    run()
    assert setup.catalog()["aaaa0001"]["rejected"]["tries"] == 1
