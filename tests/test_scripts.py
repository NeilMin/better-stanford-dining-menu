"""The entry points under scripts/.

Mostly thin, and deliberately so -- the rules live in bsdm/ where both
update.py and rebuild_catalog.py can reach them. What is left here is the part
that is genuinely theirs: what a run may hold in memory, what it may overwrite,
and what it exits with.
"""

from __future__ import annotations

import json
import subprocess
from datetime import date
from types import SimpleNamespace

import pytest
from PIL import Image

from conftest import load_script

update = load_script("update")
gen_images = load_script("gen_images")
translate = load_script("translate")
check_source = load_script("check_source")
notify_images = load_script("notify_images")


class TestScheduledMeals:
    """update.py probes the three core meals whatever the schedule says, so
    this only decides what is *warned* about -- but it is the same window
    arithmetic bsdm/build.py uses for the hours on the page."""

    HALL = {"schedules": [
        {"from": "2026-09-15", "to": "2026-09-17", "days": [0, 1, 2, 3, 4],
         "meals": {"Lunch": ["11:00", "14:30"], "Dinner": ["17:00", "20:00"]}},
        {"from": "2026-09-18", "days": [0, 1, 2, 3, 4, 5, 6],
         "meals": {"Breakfast": ["07:30", "10:00"], "Dinner": ["17:00", "20:00"]}},
    ]}

    def test_the_meals_that_schedule_expects(self):
        assert update.scheduled_meals(self.HALL, date(2026, 9, 17)) == {"Lunch", "Dinner"}
        assert update.scheduled_meals(self.HALL, date(2026, 9, 18)) == {"Breakfast", "Dinner"}

    def test_a_day_no_schedule_covers(self):
        assert update.scheduled_meals(self.HALL, date(2026, 9, 19)) == {"Breakfast", "Dinner"}
        assert update.scheduled_meals(self.HALL, date(2026, 9, 14)) == set()

    def test_it_agrees_with_the_hours_the_page_shows(self):
        """Two copies of one window rule, in two files. They are allowed to
        answer different questions, not different answers."""
        from bsdm import build as buildlib

        for day in (date(2026, 9, 16), date(2026, 9, 17), date(2026, 9, 19),
                    date(2026, 9, 20), date(2026, 9, 14)):
            assert update.scheduled_meals(self.HALL, day) == \
                set(buildlib.schedule_for(self.HALL, day)), day


class TestFetchServiceWithRetry:
    class FakeScraper:
        def __init__(self, dishes_to_return=()):
            self.dishes_to_return = list(dishes_to_return)
            self.fetches = []
            self.primed = False

        def prime(self):
            self.primed = True

        def fetch(self, menu_key, day, meal):
            from bsdm.scrape import Service, Dish
            self.fetches.append((menu_key, day, meal))
            dishes = [Dish(name=n) for n in self.dishes_to_return]
            return Service(menu_key, day.isoformat(), meal, dishes)

    def test_expected_meal_with_dishes_does_not_retry(self):
        initial_scraper = self.FakeScraper(dishes_to_return=["Pancakes"])
        created = []
        hall = {"id": "stern", "menu_key": "Stern"}
        day = date(2026, 9, 22)
        meal = "Breakfast"
        expected = {"Breakfast", "Lunch", "Dinner"}

        svc, scraper = update.fetch_service_with_retry(
            initial_scraper, hall, day, meal, expected,
            scraper_factory=lambda: created.append(1),
        )

        assert [d.name for d in svc.dishes] == ["Pancakes"]
        assert scraper is initial_scraper
        assert created == []

    def test_unexpected_meal_empty_does_not_retry(self):
        initial_scraper = self.FakeScraper(dishes_to_return=[])
        created = []
        hall = {"id": "casper", "menu_key": "GerhardCasper"}
        day = date(2026, 9, 22)
        meal = "Breakfast"
        expected = {"Lunch", "Dinner"}

        svc, scraper = update.fetch_service_with_retry(
            initial_scraper, hall, day, meal, expected,
            scraper_factory=lambda: created.append(1),
        )

        assert svc.dishes == []
        assert scraper is initial_scraper
        assert created == []

    def test_expected_meal_empty_retries_and_recovers(self):
        initial_scraper = self.FakeScraper(dishes_to_return=[])
        fresh_scraper = self.FakeScraper(dishes_to_return=["Roast Chicken"])
        hall = {"id": "stern", "menu_key": "Stern"}
        day = date(2026, 9, 22)
        meal = "Lunch"
        expected = {"Lunch", "Dinner"}

        svc, scraper = update.fetch_service_with_retry(
            initial_scraper, hall, day, meal, expected,
            scraper_factory=lambda: fresh_scraper,
        )

        assert [d.name for d in svc.dishes] == ["Roast Chicken"]
        assert scraper is fresh_scraper
        assert fresh_scraper.primed
        assert fresh_scraper.fetches == [("Stern", day, "Lunch")]

    def test_expected_meal_empty_retries_and_still_empty(self):
        initial_scraper = self.FakeScraper(dishes_to_return=[])
        fresh_scraper = self.FakeScraper(dishes_to_return=[])
        hall = {"id": "stern", "menu_key": "Stern"}
        day = date(2026, 9, 22)
        meal = "Lunch"
        expected = {"Lunch", "Dinner"}

        svc, scraper = update.fetch_service_with_retry(
            initial_scraper, hall, day, meal, expected,
            scraper_factory=lambda: fresh_scraper,
        )

        assert svc.dishes == []
        assert scraper is initial_scraper
        assert fresh_scraper.primed


class TestDrawOrder:
    def test_the_queue_and_the_backlog_are_ordered_by_the_same_rule(self):
        """gen_images draws in this order and the issue lists in it. One rule."""
        from bsdm import pending as pendinglib
        assert gen_images.rank is pendinglib.rank


class TestSeed:
    def test_is_derived_from_the_dish_id(self):
        """So regenerating a dish reproduces its picture rather than rolling a
        different dinner."""
        assert gen_images.seed_for("a1b2c3d4e5f6") == gen_images.seed_for("a1b2c3d4e5f6")
        assert gen_images.seed_for("a1b2c3d4e5f6") != gen_images.seed_for("f6e5d4c3b2a1")

    def test_is_a_seed_a_sampler_will_take(self):
        seed = gen_images.seed_for("ffffffffffff")
        assert isinstance(seed, int) and 0 <= seed < 2 ** 32


class TestIsCurrent:
    def image(self, tmp_path, width, height):
        path = tmp_path / "x.webp"
        Image.new("RGB", (width, height), (1, 2, 3)).save(path, "WEBP")
        return path

    def test_an_image_that_still_matches_the_card(self, tmp_path):
        """What is on disk, not what the sampler drew: bsdm.comfy.to_webp
        crops the 1344x768 render to the 16:9 the cards display."""
        assert gen_images.is_current(self.image(tmp_path, 1024, 576))

    def test_one_drawn_for_an_older_card_shape(self, tmp_path):
        """Changing the card's aspect ratio should redraw the library rather
        than let the browser centre-crop half of every older picture away."""
        assert not gen_images.is_current(self.image(tmp_path, 1024, 1024))

    def test_a_file_that_is_not_an_image(self, tmp_path):
        path = tmp_path / "broken.webp"
        path.write_bytes(b"not an image")
        assert not gen_images.is_current(path)


class TestRecordImage:
    def test_merges_into_the_catalog_on_disk(self, project, monkeypatch):
        project.write_catalog({"d1": {"name": "Roast Chicken", "image": None}})
        catalog = project.root / "data" / "dishes.json"
        monkeypatch.setattr(gen_images, "CATALOG", catalog)

        gen_images.record_image("d1", {"image": "d1.webp", "seed": 7})

        got = json.loads(catalog.read_text())["d1"]
        assert got == {"name": "Roast Chicken", "image": "d1.webp", "seed": 7}

    def test_never_holds_the_catalog_in_memory(self, project, monkeypatch):
        """A full backfill runs for hours. rebuild_catalog.py may well
        reclassify dishes while it is still going, and a wholesale write would
        silently revert that work."""
        project.write_catalog({"d1": {"name": "A", "category": "other"},
                               "d2": {"name": "B", "category": "other"}})
        catalog = project.root / "data" / "dishes.json"
        monkeypatch.setattr(gen_images, "CATALOG", catalog)

        # ...as if a rebuild landed between the read and the write.
        reclassified = json.loads(catalog.read_text())
        reclassified["d1"]["category"] = "poultry"
        reclassified["d3"] = {"name": "C", "category": "beef"}
        catalog.write_text(json.dumps(reclassified))

        gen_images.record_image("d2", {"image": "d2.webp"})

        got = json.loads(catalog.read_text())
        assert got["d1"]["category"] == "poultry", "a reclassification was reverted"
        assert "d3" in got, "a dish added meanwhile was dropped"
        assert got["d2"]["image"] == "d2.webp"

    def test_a_dish_the_catalog_does_not_have_yet(self, project, monkeypatch):
        project.write_catalog({})
        catalog = project.root / "data" / "dishes.json"
        monkeypatch.setattr(gen_images, "CATALOG", catalog)
        gen_images.record_image("new", {"image": "new.webp"})
        assert json.loads(catalog.read_text())["new"] == {"image": "new.webp"}


class TestTranslateAsk:
    ARGS = SimpleNamespace(claude_bin="claude", model="sonnet", timeout=240)

    def answer(self, monkeypatch, stdout, returncode=0):
        calls = {}

        def fake_run(cmd, **kwargs):
            calls["cmd"] = cmd
            calls["kwargs"] = kwargs
            return subprocess.CompletedProcess(cmd, returncode, stdout, "")

        monkeypatch.setattr(translate.subprocess, "run", fake_run)
        return calls

    def test_a_plain_json_answer(self, monkeypatch):
        self.answer(monkeypatch, '{"salt": "盐", "sugar": "糖"}')
        assert translate.ask(["salt", "sugar"], "terms", self.ARGS) == \
            {"salt": "盐", "sugar": "糖"}

    def test_a_stray_markdown_fence_does_not_cost_a_whole_batch(self, monkeypatch):
        """The system prompt forbids one. Belt and braces."""
        self.answer(monkeypatch, '```json\n{"salt": "盐"}\n```')
        assert translate.ask(["salt"], "terms", self.ARGS) == {"salt": "盐"}

    def test_a_key_the_model_renormalised_still_matches(self, monkeypatch):
        """The term it translated is still the term that was asked about."""
        self.answer(monkeypatch, '{"Sea  Salt": "海盐"}')
        assert translate.ask(["sea salt"], "terms", self.ARGS) == {"sea salt": "海盐"}

    def test_an_item_the_model_skipped_just_stays_missing(self, monkeypatch):
        """A dropped item is normal -- the next run picks it up."""
        self.answer(monkeypatch, '{"salt": "盐"}')
        assert translate.ask(["salt", "sugar"], "terms", self.ARGS) == {"salt": "盐"}

    def test_an_empty_or_non_string_answer_is_not_a_translation(self, monkeypatch):
        self.answer(monkeypatch, '{"salt": "", "sugar": null, "rice": 5}')
        assert translate.ask(["salt", "sugar", "rice"], "terms", self.ARGS) == {}

    def test_the_cli_failing_is_an_error_the_caller_can_retry(self, monkeypatch):
        self.answer(monkeypatch, "boom", returncode=1)
        with pytest.raises(translate.TranslateError):
            translate.ask(["salt"], "terms", self.ARGS)

    def test_an_unparseable_answer_is_too(self, monkeypatch):
        self.answer(monkeypatch, "I'm afraid I can't do that")
        with pytest.raises(translate.TranslateError):
            translate.ask(["salt"], "terms", self.ARGS)

    def test_a_timeout_is_too(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, 240)

        monkeypatch.setattr(translate.subprocess, "run", fake_run)
        with pytest.raises(translate.TranslateError, match="240s"):
            translate.ask(["salt"], "terms", self.ARGS)

    def test_it_runs_outside_the_repo(self, monkeypatch):
        """The translator wants none of the project's context, and loading it
        would be paid for on every batch."""
        calls = self.answer(monkeypatch, "{}")
        translate.ask(["salt"], "terms", self.ARGS)
        assert calls["kwargs"]["cwd"] != str(translate.ROOT)
        assert "--strict-mcp-config" in calls["cmd"]


class TestCheckSource:
    """The nightly job's last step. Exiting non-zero is the point: a red run
    sends mail, and a warning in a green log does not."""

    def run_in(self, project, monkeypatch, capsys):
        monkeypatch.setattr(check_source, "ROOT", project.root)
        code = check_source.main()
        return code, capsys.readouterr().out

    def test_a_clean_night_is_green(self, project, monkeypatch, capsys):
        project.set_today("2026-09-17")
        project.add_hall("wilbur", menu_key="Wilbur")
        from bsdm import source as sourcelib
        sourcelib.record(project.root, halls=["Wilbur"], window=["2026-09-17"],
                         specials_url="https://x/p.pdf")
        code, out = self.run_in(project, monkeypatch, capsys)
        assert code == 0 and "all accounted for" in out

    def test_a_hall_config_has_never_heard_of_goes_red(self, project, monkeypatch, capsys):
        project.set_today("2026-09-17")
        project.add_hall("wilbur", menu_key="Wilbur")
        from bsdm import source as sourcelib
        sourcelib.record(project.root, halls=["Wilbur", "Toyon"], window=["2026-09-17"],
                         specials_url="https://x/p.pdf")
        code, out = self.run_in(project, monkeypatch, capsys)
        assert code == 1 and "Toyon" in out

    def test_a_checkout_that_has_never_scraped_is_not_a_finding(self, project, monkeypatch,
                                                                capsys):
        project.add_hall("wilbur", menu_key="Wilbur")
        code, out = self.run_in(project, monkeypatch, capsys)
        assert code == 0 and "run scripts/update.py first" in out


class TestNotifyImages:
    """Drawing needs a GPU, so the nightly job can only ask. The whole design is
    in which of these calls sends mail: a body edit does not, a comment does, and
    twenty new dishes a night is the normal state of a rotating menu."""

    def run_in(self, project, monkeypatch, capsys, issues=(), **kwargs):
        """main() with `gh` replaced by a recorder, so no test files an issue."""
        calls = []

        def fake_gh(*args, stdin=None):
            calls.append((args, stdin))
            if args[:2] == ("repo", "view"):
                return json.dumps({"owner": {"login": "neil"}})
            if args[:2] == ("issue", "list"):
                return json.dumps(list(issues))
            if args[:2] == ("issue", "create"):
                return "https://github.com/neil/x/issues/7\n"
            return ""

        monkeypatch.setattr(notify_images, "ROOT", project.root)
        monkeypatch.setattr(notify_images, "gh", fake_gh)
        monkeypatch.setattr("sys.argv", ["notify_images.py"] + list(kwargs.get("argv", [])))
        code = notify_images.main()
        return code, capsys.readouterr().out, calls

    def waiting(self, project, *names):
        project.write_catalog({
            f"{i:02x}": {"name": n, "priority": 0, "min_order": i, "image": None,
                         "needs_image": True, "first_seen": "2026-09-20"}
            for i, n in enumerate(names)})

    def verbs(self, calls):
        return [" ".join(args[:2]) for args, _ in calls]

    def test_the_first_night_files_the_issue_and_assigns_it(self, project, monkeypatch, capsys):
        self.waiting(project, "Bulgogi")
        code, out, calls = self.run_in(project, monkeypatch, capsys)
        assert code == 0 and "issues/7" in out
        assert "issue create" in self.verbs(calls)
        body = next(stdin for args, stdin in calls if args[:2] == ("issue", "create"))
        assert "Bulgogi" in body and "cc @neil" in body
        assert any("--add-assignee" in args for args, _ in calls), "so GitHub mails the owner"

    def test_a_night_with_nothing_new_edits_the_body_and_says_nothing(self, project,
                                                                      monkeypatch, capsys):
        self.waiting(project, "Bulgogi")
        from bsdm import pending as pendinglib
        open_issue = {"number": 7, "state": "OPEN",
                      "body": pendinglib.body(pendinglib.wanted(project.root))}
        code, out, calls = self.run_in(project, monkeypatch, capsys, issues=[open_issue])
        assert code == 0 and "nothing new tonight" in out
        assert "issue edit" in self.verbs(calls)
        assert "issue comment" not in self.verbs(calls), "an edit sends no mail; that is the point"

    def test_a_dish_the_body_has_never_carried_is_worth_a_comment(self, project,
                                                                  monkeypatch, capsys):
        self.waiting(project, "Bulgogi", "Gyro Chicken")
        open_issue = {"number": 7, "state": "OPEN", "body": "<!-- bsdm:images 00 -->"}
        code, out, calls = self.run_in(project, monkeypatch, capsys, issues=[open_issue])
        assert code == 0 and "1 new tonight" in out
        said = next(stdin for args, stdin in calls if args[:2] == ("issue", "comment"))
        assert "@neil" in said and "Gyro Chicken" in said
        assert "Bulgogi" not in said, "it says what arrived, not what is still waiting"

    def test_new_dishes_reopen_an_issue_somebody_closed(self, project, monkeypatch, capsys):
        self.waiting(project, "Bulgogi")
        closed = {"number": 7, "state": "CLOSED", "body": ""}
        code, out, calls = self.run_in(project, monkeypatch, capsys, issues=[closed])
        assert code == 0 and "Reopened #7" in out
        assert "issue reopen" in self.verbs(calls)

    def test_an_empty_backlog_closes_the_issue(self, project, monkeypatch, capsys):
        project.write_catalog({})
        open_issue = {"number": 7, "state": "OPEN", "body": ""}
        code, out, calls = self.run_in(project, monkeypatch, capsys, issues=[open_issue])
        assert code == 0 and "Closed #7" in out
        assert "issue close" in self.verbs(calls)

    def test_nothing_waiting_and_nothing_filed_is_not_an_issue_to_open(self, project,
                                                                      monkeypatch, capsys):
        project.write_catalog({})
        code, out, calls = self.run_in(project, monkeypatch, capsys)
        assert code == 0 and "Nothing is waiting" in out
        assert "issue create" not in self.verbs(calls)

    def test_a_dry_run_touches_nothing(self, project, monkeypatch, capsys):
        self.waiting(project, "Bulgogi")
        code, out, calls = self.run_in(project, monkeypatch, capsys, argv=["--dry-run"])
        assert code == 0 and "Bulgogi" in out and calls == []

    def test_github_being_unreachable_is_the_one_thing_worth_going_red_for(self, project,
                                                                          monkeypatch, capsys):
        """A backlog nobody was told about is the failure this exists to prevent.

        It is the last step of the night and runs on always(), so a red here
        costs the tick and nothing else -- the menus are long committed.
        """
        self.waiting(project, "Bulgogi")

        def broken(*args, stdin=None):
            raise notify_images.GhError("gh: could not authenticate")

        monkeypatch.setattr(notify_images, "ROOT", project.root)
        monkeypatch.setattr(notify_images, "gh", broken)
        monkeypatch.setattr("sys.argv", ["notify_images.py"])
        assert notify_images.main() == 1


class TestVerifyStored:
    """`make verify` re-fetches live and diffs against data/. Its whole value
    is that a scraper fault looks exactly like a shared cycle menu, so it has
    to read the stored side correctly or every hall reports DIFFERS."""

    @pytest.fixture
    def verify(self, project, monkeypatch):
        module = load_script("verify")
        monkeypatch.setattr(module, "ROOT", project.root)
        return module

    def test_reads_a_day_the_source_still_covers(self, project, verify):
        from conftest import dish as row

        project.write_menu("2026-09-17", {"wilbur": {"Dinner": [
            row("Roast Chicken"), row("Steamed Rice")]}})
        assert verify.stored("2026-09-17", "wilbur", "Dinner") == \
            ["Roast Chicken", "Steamed Rice"]

    def test_and_one_that_has_since_been_archived(self, project, verify):
        """--day takes either side of the split."""
        from conftest import dish as row

        project.archive_menu("2026-09-15", {"wilbur": {"Dinner": [row("Roast Chicken")]}})
        assert verify.stored("2026-09-15", "wilbur", "Dinner") == ["Roast Chicken"]

    def test_a_day_never_scraped_is_empty(self, project, verify):
        assert verify.stored("2020-01-01", "wilbur", "Dinner") == []

    def test_a_meal_that_hall_does_not_serve_is_empty(self, project, verify):
        project.write_menu("2026-09-17", {"wilbur": {"Dinner": []}})
        assert verify.stored("2026-09-17", "wilbur", "Breakfast") == []
