"""The dishes the board is showing a placeholder for, written up as a to-do.

Drawing a picture needs the local ComfyUI, so it is the one step of the pipeline
CI cannot do for itself. A dish scraped tonight goes up with a placeholder icon
and stays that way until somebody runs `make images` on the laptop and commits
the result -- which means the nightly job cannot fix this, only ask, and the ask
has to survive being ignored for a week, because the answer needs a GPU and the
person holding it may be asleep.

Which is why the backlog is an issue and not a notification. A push arrives once
and is gone; an issue is a list that shrinks by itself as images land, and it is
still there on the evening you sit down to draw them. Going red was the other
option and is the wrong one: bsdm/source.py owns the red, and it means a hall
needs a config entry *tonight* or its menus are lost. A dish without a picture
is the normal state of a dish for its first day or two -- roughly twenty a night
-- and a signal that fires every night is not a signal.

Nothing here talks to GitHub; scripts/notify_images.py does that. What is here
is pure, and therefore testable without a socket: which dishes, in which order,
rendered as markdown.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# The issue body carries the ids it was written from, so that "what is new
# tonight" can be answered without keeping a file in data/ for it. GitHub holds
# the state, which is also where the state can be read by a person -- and an
# issue closed or edited by hand stays readable to the next run.
MARKER = re.compile(r"<!--\s*bsdm:images\s+([0-9a-f, ]*)-->")

TITLE = "Dishes waiting for a picture"
LABEL = "images"

# The words summarize() already uses for the three tiers, so the issue and the
# nightly log describe the same thing the same way.
TIERS = ((0, "Meat"), (1, "Other mains"), (2, "Sides"))


def rank(item: tuple[str, dict]) -> tuple:
    """Meat first, then other mains, then sides; within a tier, menu order.

    The order scripts/gen_images.py draws in, so the list reads top-down as the
    queue it is.
    """
    entry = item[1]
    return (entry.get("priority", 2), entry.get("min_order", 999), entry["name"])


def wanted(root: Path) -> list[tuple[str, dict]]:
    """Every dish the site has no picture for, in the order they will be drawn."""
    path = root / "data" / "dishes.json"
    if not path.exists():
        return []
    images = root / "data" / "images"
    catalog = json.loads(path.read_text())
    # The same test bsdm/build.py makes before it renders a thumb: the question
    # is what the board shows, not what the catalog claims. A catalog naming an
    # image file that is not committed is exactly the case worth reporting.
    missing = [
        (did, entry) for did, entry in catalog.items()
        if entry.get("needs_image")
        and not (entry.get("image") and (images / entry["image"]).exists())
    ]
    return sorted(missing, key=rank)


def dishes(n: int) -> str:
    return f"{n} dish" if n == 1 else f"{n} dishes"


def counts(items: list[tuple[str, dict]]) -> dict[int, int]:
    return {p: sum(1 for _, e in items if e.get("priority", 2) == p) for p, _ in TIERS}


def tally(items: list[tuple[str, dict]]) -> str:
    """A phrase like "7 meat, 8 other mains, 10 sides", empty tiers left out."""
    by = counts(items)
    return ", ".join(f"{by[p]} {label.lower().rstrip('s') if by[p] == 1 else label.lower()}"
                     for p, label in TIERS if by[p])


def listed(body: str | None) -> set[str]:
    """The dish ids an earlier run wrote into an issue body."""
    found = MARKER.search(body or "")
    if not found:
        return set()
    return {part.strip() for part in found.group(1).split(",") if part.strip()}


def body(items: list[tuple[str, dict]], mention: str | None = None) -> str:
    """The issue body: the whole backlog, rewritten from scratch every night."""
    lines = ["<!-- bsdm:images " + ",".join(did for did, _ in items) + " -->", ""]
    lines.append(
        f"**{dishes(len(items))}** on the board are showing a placeholder icon"
        + (f" -- {tally(items)}." if items else ".")
    )
    lines += [
        "",
        "Drawing a picture needs the ComfyUI on :8189, so CI cannot do it. They stay",
        "placeholders until the images are drawn on the laptop and committed:",
        "",
        "```sh",
        "make images                                            # the lot, meat first",
        "uv run python scripts/gen_images.py --max-priority 0   # meat only",
        "```",
    ]

    for priority, label in TIERS:
        tier = [(did, e) for did, e in items if e.get("priority", 2) == priority]
        if not tier:
            continue
        lines += ["", f"### {label} ({len(tier)})", ""]
        for _, entry in tier:
            lines.append(f"- {entry['name']} — first on the menu {entry['first_seen']}")

    lines += [
        "",
        "---",
        "",
        "Rewritten by the nightly job; a dish leaves the list when its image is",
        "committed, and the issue closes itself when the list is empty.",
    ]
    if mention:
        # Present from the moment the issue is created and never removed, so an
        # edit adds no new mention and therefore sends no mail. Only the comments
        # below are meant to arrive.
        lines += ["", f"cc @{mention}"]
    return "\n".join(lines) + "\n"


def comment(new: list[tuple[str, dict]], items: list[tuple[str, dict]],
            mention: str | None = None) -> str:
    """What to say on a night that turned up dishes nobody has drawn yet.

    The one thing here that is allowed to send mail, so it says what arrived
    tonight rather than restating the backlog, which is above it in the body.
    """
    names = ", ".join(entry["name"] for _, entry in new[:12])
    if len(new) > 12:
        names += f", and {len(new) - 12} more"
    who = f"@{mention} " if mention else ""
    return (
        f"{who}**{dishes(len(new))}** went up tonight with no picture "
        f"({tally(new)}):\n\n"
        f"{names}.\n\n"
        f"{len(items)} waiting in total. `make images` when the GPU is free.\n"
    )
