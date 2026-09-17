#!/usr/bin/env python3
"""Scrape the rolling menu window into data/menus/ and refresh the dish catalog.

Runs with no GPU and no local services, so it is what CI executes daily.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bsdm import hours as hourslib  # noqa: E402
from bsdm.catalog import build as build_catalog, summarize as summarize_catalog  # noqa: E402
from bsdm.scrape import MenuScraper  # noqa: E402
from bsdm import specials as specialslib  # noqa: E402
from bsdm.stations import analyze as analyze_stations  # noqa: E402
from bsdm import zh as zhlib  # noqa: E402

TZ = ZoneInfo("America/Los_Angeles")
CORE_MEALS = ("Breakfast", "Lunch", "Dinner")
log = logging.getLogger("update")


def load_config() -> dict:
    return json.loads((ROOT / "config" / "halls.json").read_text())


def scheduled_meals(hall: dict, day) -> set[str]:
    """Meals config/halls.json expects this hall to serve on `day`."""
    iso = day.isoformat()
    weekday = day.weekday()
    for sched in hall.get("schedules", []):
        if sched["from"] > iso:
            continue
        if sched.get("to") and sched["to"] < iso:
            continue
        if weekday in sched.get("days", []):
            return set(sched.get("meals", {}))
    return set()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--delay", type=float, default=0.4, help="seconds between requests")
    ap.add_argument("--all-meals", action="store_true",
                    help="probe Brunch on every day, not just as a canary")
    ap.add_argument("--halls", help="comma-separated hall ids to limit the scrape to")
    ap.add_argument("--skip-hours", action="store_true")
    ap.add_argument("--skip-specials", action="store_true")
    ap.add_argument("--show-hours-diff", action="store_true",
                    help="print how the R&DE hours page differs from the snapshot and exit")
    ap.add_argument("--accept-hours", action="store_true",
                    help="record the current hours page as the new snapshot")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    if args.show_hours_diff:
        print(hourslib.diff(ROOT / "data" / "hours_snapshot.json") or "(no differences)")
        return 0
    if args.accept_hours:
        hourslib.check(ROOT / "data" / "hours_snapshot.json", update=True)
        print("Hours snapshot updated.")
        return 0

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )

    config = load_config()
    halls = [h for h in config["halls"] if h["active"]]
    if args.halls:
        wanted = {s.strip() for s in args.halls.split(",")}
        halls = [h for h in halls if h["id"] in wanted]

    scraper = MenuScraper(delay=args.delay)
    scraper.prime()
    days = scraper.available_days()
    log.info("Window: %s .. %s (%d days), %d halls", days[0], days[-1], len(days), len(halls))

    menus_dir = ROOT / "data" / "menus"
    menus_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(TZ).isoformat(timespec="seconds")

    total_services = total_dishes = 0

    for day in days:
        payload = {"date": day.isoformat(), "scraped_at": now, "halls": {}}
        for hall in halls:
            expected = scheduled_meals(hall, day)
            # Always probe the three core meals so a stale schedule can't hide a
            # service; Brunch is vestigial in the app, so it is only probed on the
            # first day of the window as a canary.
            meals = list(CORE_MEALS)
            if args.all_meals or day == days[0]:
                meals.append("Brunch")
            meals += [m for m in expected if m not in meals]

            served = {}
            for meal in meals:
                svc = scraper.fetch(hall["menu_key"], day, meal)
                if not svc.dishes:
                    if meal in expected:
                        log.warning("  %s %s %s: scheduled but empty", day, hall["id"], meal)
                    continue
                served[meal] = [d.to_dict() for d in svc.dishes]
                total_services += 1
                total_dishes += len(svc.dishes)


            if served:
                payload["halls"][hall["id"]] = served
            log.debug("  %s %s -> %s", day, hall["id"], ",".join(served) or "closed")

        out = menus_dir / f"{day.isoformat()}.json"
        out.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n")
        open_halls = len(payload["halls"])
        log.info("%s  %d halls open, %d services", day, open_halls,
                 sum(len(v) for v in payload["halls"].values()))

    # Stations first: which entries are standing counters decides which dishes
    # need pictures, so the catalog is derived after the table exists.
    table = analyze_stations(menus_dir)
    (ROOT / "data" / "stations.json").write_text(
        json.dumps(table, indent=1, ensure_ascii=False, sort_keys=True) + "\n"
    )
    n_stations = sum(len(m["stations"]) for h in table["halls"].values() for m in h.values())
    log.info("Stations: %d standing counters across %d halls (%d days of history)",
             n_stations, len(table["halls"]), table["days_analyzed"])

    # The hours page is fetched once and read for two things: whether the hours
    # themselves moved, and which specials calendar it is currently linking to.
    page = None
    if not (args.skip_hours and args.skip_specials):
        try:
            page = hourslib.fetch_page()
        except Exception as exc:  # network flakiness must not fail the menu run
            log.warning("Could not fetch the hours page: %s", exc)

    if not args.skip_hours and page is not None:
        try:
            result = hourslib.check(ROOT / "data" / "hours_snapshot.json", html=page)
            if result["first_run"]:
                log.info("Hours snapshot created.")
            elif result["changed"]:
                log.warning("!! R&DE hours page CHANGED -- re-check config/halls.json")
                log.warning("   run: python scripts/update.py --show-hours-diff")
            else:
                log.info("Hours page unchanged.")
        except Exception as exc:
            log.warning("Hours check failed: %s", exc)

    # Specials live in a PDF poster that is replaced every fortnight and linked
    # only from that page, so an edition not saved while it is up is gone. A
    # poster we cannot read is still archived, and still must not cost us the
    # night's menus.
    if not args.skip_specials and page is not None:
        try:
            result = specialslib.update(ROOT, config, html=page)
            if not result["url"]:
                log.info("Specials: no calendar linked from the hours page.")
            elif result["status"] == "unchanged":
                log.info("Specials: unchanged (%d entries).", result["entries"])
            elif result["status"] == "unreadable":
                log.warning("!! Specials calendar could not be read: %s", result["error"])
                log.warning("   archived as data/specials/%s -- check the layout by hand:",
                            result["file"])
                log.warning("   python scripts/fetch_specials.py --dry-run data/specials/%s",
                            result["file"])
            else:
                log.info("Specials: %s calendar %s..%s, %d entries (%d tied to a hall)",
                         result["status"], result["from"], result["to"],
                         result["entries"], result["placed"])
                if result["unplaced_labels"]:
                    log.warning("   !! labels matching no hall: %s -- add an alias in "
                                "config/halls.json", ", ".join(result["unplaced_labels"]))
        except Exception as exc:
            log.warning("Specials check failed: %s", exc)

    catalog_path = ROOT / "data" / "dishes.json"
    previous = json.loads(catalog_path.read_text()) if catalog_path.exists() else {}
    # Same code path as scripts/rebuild_catalog.py, so scraping and rebuilding
    # cannot drift apart. After the specials, which are dishes too: a poster
    # fetched tonight has to be in the catalog tonight to queue its pictures.
    catalog = build_catalog(menus_dir, table, previous, specialslib.dishes(ROOT))
    catalog_path.write_text(json.dumps(catalog, indent=1, ensure_ascii=False, sort_keys=True) + "\n")

    log.info("Scraped %d services / %d dish rows", total_services, total_dishes)
    log.info("%s", summarize_catalog(catalog))

    # Informational: translating needs the Claude Code CLI, so like image
    # generation it happens on a laptop and arrives as a commit. CI just says
    # how much of today's menu is still waiting for one.
    log.info("%s", zhlib.summarize(ROOT))
    untranslated = sum(len(v) for v in zhlib.missing(ROOT).values())
    if untranslated:
        log.info("%d new items to translate -- run: make translate", untranslated)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
