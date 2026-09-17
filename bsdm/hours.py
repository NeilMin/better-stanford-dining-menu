"""Watch the R&DE hours page for changes.

The page is prose, not data ("Fall Hours Begin Friday, September 18th" sitting
between a block of orientation-week exceptions and a weekday table), so a parser
would be guesswork that silently rots. Instead we fingerprint the hours section
and tell the operator to re-transcribe config/halls.json when it moves.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

HOURS_URL = "https://rde.stanford.edu/dining-hospitality/dining-locations-hours"

# The hours section sits between the page title and the promotional blocks.
_START = re.compile(r"DINING LOCATIONS\s*&\s*HOURS", re.I)
_END = re.compile(r"Meet Your Dining Team", re.I)


def fetch_page(timeout: int = 30) -> str:
    """The hours page itself. Also where bsdm/specials.py finds its link."""
    r = requests.get(HOURS_URL, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return r.text


def fetch_hours_text(timeout: int = 30, html: str | None = None) -> str:
    soup = BeautifulSoup(html if html is not None else fetch_page(timeout), "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = re.sub(r"\n\s*\n+", "\n", soup.get_text("\n"))
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

    start = next((i for i, ln in enumerate(lines) if _START.search(ln)), 0)
    end = next((i for i, ln in enumerate(lines) if _END.search(ln)), len(lines))
    return "\n".join(lines[start:end])


def check(snapshot_path: Path, update: bool = False, html: str | None = None) -> dict:
    """Compare the live hours section against the stored snapshot."""
    text = fetch_hours_text(html=html)
    digest = hashlib.sha256(text.encode()).hexdigest()

    previous = None
    if snapshot_path.exists():
        previous = json.loads(snapshot_path.read_text())

    changed = previous is not None and previous.get("sha256") != digest
    first_run = previous is None

    if first_run or update:
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(
            json.dumps({"sha256": digest, "url": HOURS_URL, "text": text}, indent=2) + "\n"
        )

    return {
        "changed": changed,
        "first_run": first_run,
        "sha256": digest,
        "previous_sha256": (previous or {}).get("sha256"),
        "text": text,
    }


def diff(snapshot_path: Path) -> str:
    """Unified diff of the stored snapshot against the live page."""
    import difflib

    if not snapshot_path.exists():
        return "(no snapshot yet)"
    old = json.loads(snapshot_path.read_text()).get("text", "")
    new = fetch_hours_text()
    return "\n".join(
        difflib.unified_diff(
            old.splitlines(), new.splitlines(), "snapshot", "live", lineterm="", n=2
        )
    )
