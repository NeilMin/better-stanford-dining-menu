"""Where a stored menu lives, and which of them a given job should read.

R&DE publishes a rolling window of today..today+6 and nothing before it, so a
day not scraped while it was up is gone for good and data/menus is the only
archive of it that will ever exist. That pulls in two directions: the board
shows only days the source still covers, while the classification deciding what
a dish *is* wants as many days as it can get.

So the stored menus are split on the one predicate the board already applied in
memory, and every job now says which side it wants instead of globbing a
directory and filtering afterwards:

    data/menus/live/2026-09-17.json                date >= today, what ships
    data/menus/archive/2026/09/2026-09-15.json     everything before that

    live(root)      the board           7 files, whatever the archive holds
    recent(root)    stations, catalog   a trailing window, bounded
    history(root)   an explicit replay  every menu ever stored

`today` is Pacific, because that is the day the halls are serving and the day
the board means. It matters more than it looks: the nightly job runs at 06:20
UTC, which is 23:20 the *previous* day in California, so a UTC reading would
archive a day with forty minutes left to run and leave the board short of it.

The archive is append-only. The scrape window starts at today, so a day that
has passed is never written again -- the bytes are settled, and git never has
to store that blob twice.
"""

from __future__ import annotations

import shutil
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Los_Angeles")

# How far back the classification windows reach. Stations need enough sightings
# to be sure (four services, seen at six in ten), and a counter R&DE retires
# should stop being called standing within a quarter rather than outlive the
# change by however long the archive happens to be. Two months is both.
RECENT_DAYS = 60


def today() -> date:
    """The day the halls are serving. The one definition; import it."""
    return datetime.now(TZ).date()


def date_of(path: Path) -> date:
    return date.fromisoformat(path.stem)


def live_dir(root: Path) -> Path:
    return root / "data" / "menus" / "live"


def archive_dir(root: Path) -> Path:
    return root / "data" / "menus" / "archive"


def live_path(root: Path, day: date) -> Path:
    return live_dir(root) / f"{day.isoformat()}.json"


def archive_path(root: Path, day: date) -> Path:
    return archive_dir(root) / f"{day.year:04d}" / f"{day.month:02d}" / f"{day.isoformat()}.json"


def live(root: Path) -> list[Path]:
    """The days the source still covers, oldest first."""
    return sorted(live_dir(root).glob("*.json"))


def archived(root: Path) -> list[Path]:
    """Every day that has passed, oldest first."""
    return sorted(archive_dir(root).glob("*/*/*.json"))


def history(root: Path) -> list[Path]:
    """Every menu ever stored. For replays and for the translation table, which
    has to keep offering a term it saw once and never got an answer for."""
    return archived(root) + live(root)


def recent(root: Path, days: int = RECENT_DAYS) -> list[Path]:
    """The trailing window, oldest first: live plus the last `days` archived.

    What a dish is judged on. Bounded so that a nightly run costs the same in
    March as it did in September, and so that the judgement tracks what the
    halls are doing now rather than averaging over everything they ever did.
    """
    cutoff = today() - timedelta(days=days)
    return [p for p in archived(root) if date_of(p) >= cutoff] + live(root)


def archive_past(root: Path) -> list[Path]:
    """Move days that have gone by out of live/. Returns what moved.

    Idempotent, and safe to run before or after a scrape: the window starts at
    today, so nothing it writes is ever a candidate to be moved by the same run.
    """
    moved = []
    for path in live(root):
        day = date_of(path)
        if day >= today():
            continue
        dest = archive_path(root, day)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(dest))
        moved.append(dest)
    return moved
