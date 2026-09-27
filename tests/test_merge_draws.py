"""Folding several CI machines' pictures back into a catalog a scrape has moved on from.

Each machine drew on a copy of data/ that was current when the night began. What
it hands back must add its pictures and nothing else: a stale copy of the
catalog applied wholesale would undo the scrape that ran while it was drawing.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from scripts.merge_draws import merge

A = {"name": "Roast Chicken", "ingredients": "chicken", "needs_image": True, "image": None}
B = {"name": "Steamed Broccoli", "ingredients": "broccoli", "needs_image": True, "image": None}
C = {"name": "Old Special", "ingredients": "", "needs_image": True, "image": None}


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, sort_keys=True))


def git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    """A repo whose base commit is the night's start, and a scrape made since."""
    root = tmp_path / "repo"
    write(root / "data" / "dishes.json", {"a": A, "b": B, "c": C})
    write(root / "data" / "briefs.json", {"b": {"dish": "broccoli", "rev": 6}})
    (root / "data" / "images").mkdir()
    git(root, "init", "-q")
    git(root, "-c", "user.email=t@t", "-c", "user.name=t", "add", ".")
    git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip()
    # Tonight's scrape: new ingredients for a, c dropped, a new dish d.
    write(root / "data" / "dishes.json", {
        "a": {**A, "ingredients": "chicken, lemon"}, "b": B,
        "d": {"name": "New Dish", "ingredients": "tofu", "needs_image": True, "image": None},
    })
    return root, base


def shard(tmp_path, name, dishes, briefs=None, pictures=()):
    out = tmp_path / name
    write(out / "data" / "dishes.json", dishes)
    write(out / "data" / "briefs.json", briefs or {})
    (out / "data" / "images").mkdir(parents=True, exist_ok=True)
    for did in pictures:
        (out / "data" / "images" / f"{did}.webp").write_bytes(b"webp " + did.encode())
    return out


DRAWN = {"image": "a.webp", "model": "sdxl", "seed": 7, "generated_at": "2026-09-28T03:00:00+00:00",
         "judge": {"judge": "gemma", "seen": "roast chicken", "at": "2026-09-28T03:00:00+00:00"}}


def test_a_picture_lands_and_the_scrape_since_is_kept(repo, tmp_path):
    root, base = repo
    one = shard(tmp_path, "s1", {"a": {**A, **DRAWN}, "b": B, "c": C}, pictures=["a"])
    counts = merge(root, base, [one])

    dishes = json.loads((root / "data" / "dishes.json").read_text())
    assert dishes["a"]["image"] == "a.webp" and dishes["a"]["judge"]["judge"] == "gemma"
    assert dishes["a"]["ingredients"] == "chicken, lemon", "the shard's stale copy undid the scrape"
    assert "c" not in dishes and "d" in dishes
    assert (root / "data" / "images" / "a.webp").read_bytes() == b"webp a"
    assert counts["pictures"] == 1


def test_every_machine_s_share_is_applied(repo, tmp_path):
    root, base = repo
    one = shard(tmp_path, "s1", {"a": {**A, **DRAWN}, "b": B, "c": C}, pictures=["a"])
    two = shard(tmp_path, "s2", {"a": A, "b": {**B, **DRAWN, "image": "b.webp"}, "c": C}, pictures=["b"])
    merge(root, base, [one, two])
    dishes = json.loads((root / "data" / "dishes.json").read_text())
    assert dishes["a"]["image"] == "a.webp" and dishes["b"]["image"] == "b.webp"


def test_a_dish_the_scrape_dropped_is_not_brought_back(repo, tmp_path):
    root, base = repo
    one = shard(tmp_path, "s1", {"a": A, "b": B, "c": {**C, **DRAWN, "image": "c.webp"}}, pictures=["c"])
    counts = merge(root, base, [one])
    assert "c" not in json.loads((root / "data" / "dishes.json").read_text())
    assert not (root / "data" / "images" / "c.webp").exists()
    assert counts["gone"] == 1


def test_a_rejection_is_recorded_without_a_picture(repo, tmp_path):
    root, base = repo
    rejected = {"rejected": {"tries": 1, "pictures": 4, "seen": "a steak"}}
    merge(root, base, [shard(tmp_path, "s1", {"a": {**A, **rejected}, "b": B, "c": C})])
    dishes = json.loads((root / "data" / "dishes.json").read_text())
    assert dishes["a"]["rejected"]["tries"] == 1 and dishes["a"]["image"] is None
    assert not list((root / "data" / "images").iterdir())


def test_only_briefs_a_machine_wrote_are_taken(repo, tmp_path):
    root, base = repo
    # Written on the laptop while the machines were drawing.
    write(root / "data" / "briefs.json", {"b": {"dish": "steamed broccoli florets", "rev": 6}})
    one = shard(tmp_path, "s1", {"a": A, "b": B, "c": C},
                briefs={"a": {"dish": "roast chicken", "rev": 6}, "b": {"dish": "broccoli", "rev": 6}})
    counts = merge(root, base, [one])
    briefs = json.loads((root / "data" / "briefs.json").read_text())
    assert briefs["a"]["dish"] == "roast chicken"
    assert briefs["b"]["dish"] == "steamed broccoli florets", "an untouched stale brief overwrote a newer one"
    assert counts["briefs"] == 1


def test_a_field_the_machine_dropped_is_dropped(repo, tmp_path):
    root, base = repo
    write(root / "data" / "dishes.json", {"a": {**A, "vlm_score": 3}, "b": B})
    git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qam", "old gate")
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip()
    merge(root, base, [shard(tmp_path, "s1", {"a": {**A, **DRAWN}, "b": B}, pictures=["a"])])
    assert "vlm_score" not in json.loads((root / "data" / "dishes.json").read_text())["a"]
