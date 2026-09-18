"""What R&DE offered the last time we looked, and what about it needs a person.

config/halls.json is hand-transcribed ground truth, and deliberately so: a hall
needs a menu_key, an id, a schedule, the aliases the specials poster calls it
by, an address and a crop box into the campus map, and the location dropdown
carries exactly one of those. So a hall R&DE adds cannot be picked up
automatically, and this module does not try. What it does is notice.

Noticing is the part that was missing. The scrape iterates config and never
asks the dropdown what else is there, so a new hall was invisible: no error, no
warning, CI green, and every night that passes is a night of its menus gone for
good, because the source keeps seven days and no more. A warning in the log
would have been the same silence with more words -- nobody reads a log that
ends in a green tick. So the finding is recorded here, and the nightly job ends
by failing on it, which is the one notification that arrives by itself.

Deliberately not a scrape failure: the menus are already written and committed
by the time this is looked at. The night's work lands, the site publishes, and
the run still goes red.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from bsdm import specials as specialslib
from bsdm.menus import today


def path(root: Path) -> Path:
    return root / "data" / "source.json"


def record(root: Path, *, halls: list[str], window: list[str],
           specials_url: str | None) -> dict:
    """Write down what the source is currently offering."""
    snapshot = {
        "seen_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "halls": sorted(halls),
        "window": [window[0], window[-1]] if window else [],
        "specials_url": specials_url,
    }
    path(root).write_text(json.dumps(snapshot, indent=1, ensure_ascii=False) + "\n")
    return snapshot


def load(root: Path) -> dict:
    p = path(root)
    return json.loads(p.read_text()) if p.exists() else {}


def drift(root: Path, config: dict) -> list[str]:
    """What a person has to do something about. Empty on a normal night."""
    snapshot = load(root)
    if not snapshot:
        return []

    found = []

    offered = set(snapshot.get("halls", []))
    # Unknown is measured against every hall named in config, active or not, so
    # that a hall deliberately switched off does not come back as a discovery.
    # Missing is measured against the active ones only, for the same reason from
    # the other side: EVGR sits in the dropdown while config has it inactive,
    # and that is a decision, not drift. A dropdown entry is not a hall serving
    # food -- an option that answers with empty menus looks identical -- so
    # nothing here tries to read a reopening out of one.
    known = {h["menu_key"] for h in config["halls"]}
    active = {h["menu_key"] for h in config["halls"] if h.get("active")}
    if unknown := sorted(offered - known):
        found.append(
            f"R&DE's location dropdown lists {len(unknown)} hall(s) that "
            f"config/halls.json does not: {', '.join(unknown)}.\n"
            "  Nothing is being scraped for them, and the source keeps only seven\n"
            "  days, so every night that passes is a night of their menus lost.\n"
            "  Add an entry per hall: menu_key, id, schedule, aliases, address,\n"
            "  and a crop box in config/logos.json."
        )
    if gone := sorted(active - offered):
        found.append(
            f"config/halls.json names {len(gone)} hall(s) the dropdown no longer "
            f"offers: {', '.join(gone)}.\n"
            "  Set active: false if it has closed, or fix the menu_key if it was "
            "renamed."
        )

    # A poster nobody can find is the failure mode the archive cannot recover
    # from, and it is silent by nature: the hours page simply stops linking one.
    # Only worth saying when there is also no calendar on file covering today --
    # a fortnight with no specials at all is a normal thing for R&DE to publish.
    if not snapshot.get("specials_url"):
        iso = today().isoformat()
        covered = any(c.get("from") and c.get("to") and c["from"] <= iso <= c["to"]
                      for c in specialslib.load(root).get("calendars", []))
        if not covered:
            found.append(
                "No specials calendar is linked from the hours page, and none on "
                "file covers today.\n"
                "  Either R&DE has moved the poster or renamed it past "
                "bsdm/specials.py's link match\n"
                "  (it looks for 'special', preferring a link that also says "
                "'calendar').\n"
                "  Check the hours page by hand: an edition not saved while it is "
                "up is gone for good."
            )

    return found
