"""The backlog of dishes with no picture, and how it is written up.

Drawing needs a GPU, so this is the one thing the nightly job can only ask about
-- see bsdm/pending.py. What is worth pinning down is the arithmetic underneath
the ask: which dishes count as waiting, in what order they are offered, and that
an issue body can be read back for "what is new tonight" after a person has
edited it.
"""

from __future__ import annotations

from bsdm import pending as pendinglib


def entry(name, *, priority=1, order=0, image=None, needs_image=True,
          first_seen="2026-09-20") -> dict:
    return {"name": name, "priority": priority, "min_order": order,
            "image": image, "needs_image": needs_image, "first_seen": first_seen,
            "placeholder": False, "station_only": False}


def catalog(project, **entries) -> None:
    project.write_catalog({did: e for did, e in entries.items()})


class TestWanted:
    def test_a_dish_with_no_image_is_waiting(self, project):
        catalog(project, aa=entry("Bulgogi"))
        assert [e["name"] for _, e in pendinglib.wanted(project.root)] == ["Bulgogi"]

    def test_a_drawn_dish_is_not(self, project):
        catalog(project, aa=entry("Bulgogi", image="aa.webp"))
        project.write_image("aa.webp")
        assert pendinglib.wanted(project.root) == []

    def test_a_catalog_naming_an_image_nobody_committed_is_still_waiting(self, project):
        """The same test build.py makes: the question is what the board shows.

        Images are drawn on a laptop and arrive as a commit, so the field and the
        file part company exactly when somebody forgets to `git add data/images`.
        """
        catalog(project, aa=entry("Bulgogi", image="aa.webp"))
        assert len(pendinglib.wanted(project.root)) == 1

    def test_stations_and_placeholders_are_not_waiting_for_anything(self, project):
        catalog(project, aa=entry("Cereal Bar", needs_image=False))
        assert pendinglib.wanted(project.root) == []

    def test_no_catalog_yet(self, project):
        assert pendinglib.wanted(project.root) == []

    def test_meat_first_then_menu_order(self, project):
        catalog(project,
                aa=entry("Side Salad", priority=2, order=0),
                bb=entry("Tofu Curry", priority=1, order=3),
                cc=entry("Bulgogi", priority=0, order=2),
                dd=entry("Roast Chicken", priority=0, order=1))
        assert [e["name"] for _, e in pendinglib.wanted(project.root)] == [
            "Roast Chicken", "Bulgogi", "Tofu Curry", "Side Salad"]

    def test_the_tally_names_the_tiers_that_have_something_in_them(self, project):
        catalog(project, aa=entry("Bulgogi", priority=0), bb=entry("Slaw", priority=2))
        got = pendinglib.tally(pendinglib.wanted(project.root))
        assert got == "1 meat, 1 side"


class TestBody:
    def test_every_dish_is_listed_under_its_tier(self, project):
        catalog(project, aa=entry("Bulgogi", priority=0), bb=entry("Slaw", priority=2))
        text = pendinglib.body(pendinglib.wanted(project.root))
        assert "### Meat (1)" in text and "### Sides (1)" in text
        assert "- Bulgogi — first on the menu 2026-09-20" in text
        assert "Other mains" not in text, "an empty tier is not a heading"

    def test_the_ids_survive_the_round_trip(self, project):
        catalog(project, aa=entry("Bulgogi"), bb=entry("Slaw", priority=2))
        text = pendinglib.body(pendinglib.wanted(project.root))
        assert pendinglib.listed(text) == {"aa", "bb"}

    def test_the_ids_survive_a_person_editing_the_issue(self):
        text = pendinglib.body([("aa", entry("Bulgogi"))])
        edited = "Neil: drawing these tonight\n\n" + text + "\n- [ ] and a note\n"
        assert pendinglib.listed(edited) == {"aa"}

    def test_an_issue_that_never_had_a_marker_offers_no_ids(self):
        assert pendinglib.listed("filed by hand") == set()
        assert pendinglib.listed(None) == set()

    def test_the_mention_is_only_there_when_asked_for(self, project):
        catalog(project, aa=entry("Bulgogi"))
        items = pendinglib.wanted(project.root)
        assert "cc @" not in pendinglib.body(items)
        assert "cc @neil" in pendinglib.body(items, "neil")

    def test_an_empty_backlog_still_renders(self):
        text = pendinglib.body([])
        assert pendinglib.listed(text) == set()
        assert "0 dishes" in text


class TestComment:
    def test_it_says_what_arrived_rather_than_the_whole_backlog(self):
        new = [("aa", entry("Bulgogi", priority=0))]
        items = new + [("bb", entry("Slaw", priority=2))]
        text = pendinglib.comment(new, items, "neil")
        assert text.startswith("@neil ")
        assert "1 dish" in text and "1 meat" in text
        assert "Bulgogi" in text and "Slaw" not in text
        assert "2 waiting in total" in text

    def test_a_long_night_is_summarised_rather_than_listed_in_full(self):
        new = [(f"{i:02x}", entry(f"Dish {i}")) for i in range(20)]
        text = pendinglib.comment(new, new)
        assert "Dish 0" in text and "Dish 19" not in text
        assert "and 8 more" in text
