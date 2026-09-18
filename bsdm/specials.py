"""The dinner specials calendar, which R&DE publishes only as a PDF.

The menu app knows nothing about specials. They live in a poster -- a two-week
grid made in Canva -- linked from the Dining Locations & Hours page, replaced
every fortnight under a filename nobody could predict ("Dining Hall Specials
Calendar_Sept14-25.pdf", "Dining_Hall_Specials_Calendar_Aug3-14_0.pdf",
"Dining Hall Specials Calendar_H Frame Nov17-28.pdf"). So the link is scraped
from the page rather than guessed, and every PDF is kept in data/specials/: the
page only ever points at the current one, and a fortnight that is not saved
while it is up is gone.

Reading the poster is geometry, not text order. Each special is a coloured bar
drawn across the days it runs, with "Hall: dish" sitting on top of it:

    SUNDAY  MONDAY   TUESDAY  WEDNESDAY  THURSDAY  FRIDAY  SATURDAY
       13      14        15         16         17      18        19
            |= Stern: Esquite fries ===============================|
            |= AFDC ...|= AFDC: Chicken Tikka Masala ==============|
                       (^ the maroon "reopens Tuesday" block, on top)

so the bar's horizontal extent is the date range and its vertical extent is what
groups the lines of one entry together. Text is assigned to the *smallest* bar
that contains it, which is what keeps a note drawn over the top of a row -- the
maroon block above, a Thanksgiving band mid-week -- from being read as part of
the special underneath it.

Bars are told from the grid they sit on by the weekend: every background stripe
runs the full width of the calendar, and no special has ever run on a Saturday
or a Sunday, so a rectangle covering a weekend column is furniture.

What this deliberately does not do is decide whether a hall is open. The bars
span Monday to Friday even when a hall reopens on the Tuesday; the scraped menus
already know which days have a dinner service, so build.py only ever puts a
special on a day that hall is actually serving.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urljoin, unquote

import requests
from bs4 import BeautifulSoup

from bsdm.hours import HOURS_URL, fetch_page

MONTHS = {m.upper(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], 1)}

WEEKDAYS = ["SUNDAY", "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY"]

# "DINNER SPECIALS FOR SEPTEMBER 14 - 25, 2026" -- the meal and the fortnight.
# Seen with and without spaces around the dash, and with the second month
# spelled out when the range crosses one.
TITLE_RE = re.compile(
    r"(?P<meal>BREAKFAST|BRUNCH|LUNCH|DINNER)\s+SPECIALS\s+FOR\s+"
    r"(?P<m1>[A-Za-z]+)\.?\s*(?P<d1>\d{1,2})\s*[-–—]\s*"
    r"(?:(?P<m2>[A-Za-z]+)\.?\s*)?(?P<d2>\d{1,2})\s*,?\s*(?P<y>\d{4})",
    re.I)

# The link on the hours page, matched on the words in the filename and the link
# text rather than on a path, because the path is a new invention every
# fortnight. Two passes: R&DE also publishes things like special-diet guidance,
# so a link that says "calendar" as well wins outright, and the loose match is
# only the fallback.
LINK_RE = re.compile(r"special", re.I)
LINK_STRONG_RE = re.compile(r"special.*calendar|calendar.*special", re.I | re.S)

# "Hall: dish". The label is everything before the first colon, which is also
# where a list of halls would be ("Stern & Wilbur: ...").
ENTRY_RE = re.compile(r"^\s*(?P<label>[^:]{1,80}?)\s*:\s*(?P<text>\S.*)$", re.S)

_LABEL_SPLIT = re.compile(r"\s*(?:\||&|/|,| and )\s*", re.I)

# "AFDC: No Dinner Special this week". Kept in data/specials.json, because it is
# what the poster says, but not put on the board: a hall with no special and a
# hall announcing it has none look the same to someone deciding where to eat.
_NOTHING_RE = re.compile(r"^no\s+\w*\s*special", re.I)


def _key(label: str) -> str:
    return re.sub(r"[^a-z0-9]", "", label.lower())


def alias_table(config: dict) -> dict[str, str]:
    """{normalised label: hall id} from config/halls.json."""
    table = {}
    for hall in config["halls"]:
        for name in [hall["id"], hall["short"], hall["name"], *hall.get("aliases", [])]:
            table.setdefault(_key(name), hall["id"])
    return table


def resolve_halls(label: str, table: dict[str, str]) -> list[str]:
    """The halls a label names, or [] if any part of it is not a hall.

    All or nothing on purpose: a label is only a hall list when every piece of
    it resolves, so "Traditional Thanksgiving Dinner at all Dining Halls" stays
    a campus-wide note instead of being filed under whichever word happened to
    match.
    """
    parts = [p for p in _LABEL_SPLIT.split(label.strip()) if p]
    if not parts:
        return []
    out = []
    for part in parts:
        hall = table.get(_key(part))
        if not hall:
            return []
        if hall not in out:
            out.append(hall)
    return out


# ---------- the page ----------

def find_link(html: str, base: str = HOURS_URL) -> str | None:
    """The specials calendar PDF linked from the hours page."""
    soup = BeautifulSoup(html, "html.parser")
    candidates = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href.lower().split("?")[0].endswith(".pdf"):
            continue
        haystack = unquote(href) + " " + a.get_text(" ", strip=True)
        if LINK_RE.search(haystack):
            candidates.append((bool(LINK_STRONG_RE.search(haystack)), urljoin(base, href)))
    if not candidates:
        return None
    return next((url for strong, url in candidates if strong), candidates[0][1])


def download(url: str, timeout: int = 60) -> bytes:
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return r.content


# ---------- the PDF ----------

def _subpaths(items):
    """Split one drawing into its closed rectangles.

    Canva emits both weeks of a colour as a single path object with two
    subpaths, so the path's own bounding box spans the whole calendar. A new
    subpath starts wherever a segment does not begin where the last one ended.
    """
    current, previous = [], None
    for item in items:
        if item[0] not in ("l", "c"):
            continue
        start, end = item[1], item[-1]
        if previous is None or abs(start.x - previous.x) > .5 or abs(start.y - previous.y) > .5:
            if current:
                yield current
            current = []
        current.append((start, end))
        previous = end
    if current:
        yield current


def _bbox(segments):
    xs = [p.x for a, b in segments for p in (a, b)]
    ys = [p.y for a, b in segments for p in (a, b)]
    return min(xs), min(ys), max(xs), max(ys)


def _text_lines(page) -> list[dict]:
    lines = []
    for block in page.get_text("dict")["blocks"]:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            text = "".join(span["text"] for span in line["spans"])
            if text.strip():
                lines.append({"text": text, "box": line["bbox"]})
    return lines


def parse(blob: bytes) -> dict:
    """Read one specials poster into {meal, from, to, entries: [...]}."""
    import pymupdf  # imported here so the menu scrape does not need it loaded

    with pymupdf.open(stream=blob, filetype="pdf") as doc:
        page = doc[0]
        lines = _text_lines(page)
        drawings = [
            (d.get("fill"), list(_subpaths(d["items"])))
            for d in page.get_drawings() if d.get("fill")
        ]

    match = next((m for m in (TITLE_RE.search(l["text"]) for l in lines) if m), None)
    if not match:
        raise ValueError("no 'SPECIALS FOR <month> <d>-<d>, <year>' title on page 1")

    year = int(match["y"])
    start = dt.date(year, MONTHS[match["m1"].upper()], int(match["d1"]))
    end = dt.date(year, MONTHS[(match["m2"] or match["m1"]).upper()], int(match["d2"]))
    if end < start:                       # a range that runs into January
        end = dt.date(year + 1, end.month, end.day)

    # One x per weekday, from the header row. The weekend cells are narrower
    # than the weekday ones, so a centre is a safer handle than an edge.
    centres: list[float | None] = []
    for name in WEEKDAYS:
        hit = next((l for l in lines if l["text"].strip().upper() == name), None)
        centres.append((hit["box"][0] + hit["box"][2]) / 2 if hit else None)
    if centres.count(None) > 1:
        raise ValueError("could not find the weekday header row")

    # The big numerals, grouped into week rows. A week is not always seven of
    # them: a fortnight starting on the 1st leaves the Sunday cell blank.
    weeks: list[dict] = []
    numerals = sorted(
        (l for l in lines if re.fullmatch(r"\d{1,2}", l["text"].strip())
         and _height(l) > 30),
        key=lambda l: l["box"][1])
    for line in numerals:
        column = _nearest_column(line, centres)
        if weeks and line["box"][1] - weeks[-1]["top"] < 40:
            weeks[-1]["days"][column] = int(line["text"])
            weeks[-1]["bottom"] = max(weeks[-1]["bottom"], line["box"][3])
        else:
            weeks.append({"top": line["box"][1], "bottom": line["box"][3],
                          "days": {column: int(line["text"])}})
    if not weeks:
        raise ValueError("could not find the date rows")

    for index, week in enumerate(weeks):
        column, day = sorted(week["days"].items())[0]
        anchor = start + dt.timedelta(days=7 * index)
        base = min((anchor + dt.timedelta(days=k) for k in range(-10, 11)
                    if (anchor + dt.timedelta(days=k)).day == day),
                   key=lambda d: abs((d - anchor).days), default=None)
        if base is None:
            raise ValueError(f"week {index + 1} starts on a {day} that is not near {anchor}")
        week["dates"] = {i: base + dt.timedelta(days=i - column) for i in range(7)}

    bands = []
    for fill, paths in drawings:
        if min(fill) > 0.95:                         # the page's own white ground
            continue
        for segments in paths:
            x0, y0, x1, y1 = _bbox(segments)
            if y0 < weeks[0]["bottom"] or not 20 < y1 - y0 < 400:
                continue
            columns = [i for i, c in enumerate(centres) if c and x0 - 2 <= c <= x1 + 2]
            # Anything reaching into a weekend column is the grid, not a bar.
            if not columns or 0 in columns or 6 in columns:
                continue
            bands.append({"x0": x0, "y0": y0, "x1": x1, "y1": y1,
                          "columns": columns, "lines": []})

    skip = {*WEEKDAYS}
    for line in lines:
        stripped = line["text"].strip()
        if stripped.upper() in skip or re.fullmatch(r"\d{1,2}", stripped):
            continue
        cx = (line["box"][0] + line["box"][2]) / 2
        cy = (line["box"][1] + line["box"][3]) / 2
        inside = [b for b in bands
                  if b["x0"] - 2 <= cx <= b["x1"] + 2 and b["y0"] - 2 <= cy <= b["y1"] + 2]
        if inside:
            # Smallest wins: a note is drawn on top of the bar it interrupts.
            min(inside, key=lambda b: (b["x1"] - b["x0"]) * (b["y1"] - b["y0"]))["lines"].append(line)

    entries = []
    for band in sorted(bands, key=lambda b: (b["y0"], b["x0"])):
        if not band["lines"]:
            continue
        band["lines"].sort(key=lambda l: (round(l["box"][1]), l["box"][0]))
        text = re.sub(r"\s+", " ", " ".join(l["text"] for l in band["lines"])).strip()
        week = max((w for w in weeks if w["bottom"] <= band["y0"] + 4),
                   key=lambda w: w["bottom"], default=None)
        if week is None:
            continue
        days = [week["dates"][c] for c in band["columns"]]
        # The label is only split off here, never dropped: whether "X: y" is a
        # hall's special or a sentence that happens to contain a colon is not
        # something the poster's geometry can tell you. attach_halls decides.
        entry = {"label": None, "text": text, "dish": None,
                 "from": min(days).isoformat(), "to": max(days).isoformat()}
        if hit := ENTRY_RE.match(text):
            entry["label"] = hit["label"].strip()
            entry["dish"] = re.sub(r"\s+", " ", hit["text"]).strip()
        entries.append(entry)

    # A note drawn across several rows lands in each of them; it is one note.
    seen, unique = set(), []
    for entry in entries:
        key = (entry["text"], entry["from"], entry["to"])
        if key not in seen:
            seen.add(key)
            unique.append(entry)

    return {
        "title": match.group(0).strip(),
        "meal": match["meal"].title(),
        "from": start.isoformat(),
        "to": end.isoformat(),
        "entries": unique,
    }


def _height(line: dict) -> float:
    return line["box"][3] - line["box"][1]


def _nearest_column(line: dict, centres: list[float | None]) -> int:
    cx = (line["box"][0] + line["box"][2]) / 2
    return min((i for i, c in enumerate(centres) if c), key=lambda i: abs(cx - centres[i]))


def attach_halls(entries: list[dict], table: dict[str, str]) -> list[dict]:
    """Decide, per entry, whether its "X: y" is a hall and its dish.

    When it is, the hall moves into `halls` and `text` narrows to the dish --
    the column already says which hall it is. When it is not, `text` keeps the
    whole line, colon and all, because "Reminder: closed Friday" is a sentence,
    not a label on a dish.
    """
    for entry in entries:
        entry["halls"] = resolve_halls(entry["label"], table) if entry["label"] else []
        if entry["halls"] and entry.get("dish"):
            entry["text"] = entry["dish"]
        entry.pop("dish", None)
    return entries


# ---------- the archive ----------

def store_path(root: Path) -> Path:
    return root / "data" / "specials.json"


def archive_dir(root: Path) -> Path:
    return root / "data" / "specials"


def load(root: Path) -> dict:
    path = store_path(root)
    return json.loads(path.read_text()) if path.exists() else {"calendars": []}


def save(root: Path, store: dict) -> None:
    store["calendars"].sort(key=lambda c: (c.get("from") or "", c["url"]))
    store_path(root).write_text(
        json.dumps(store, indent=1, ensure_ascii=False) + "\n")


def _archive_name(url: str, parsed: dict | None) -> str:
    """Where a poster is filed, relative to data/specials/.

    Filed under the fortnight it covers rather than the night it was fetched,
    in YYYY/MM as the menus are, so that a couple of years of them stays
    legible in a listing. An edition too reshaped to read has no dates to file
    it under and goes in undated/ until someone works out what it says.
    """
    # R&DE sometimes hangs a ?t=<timestamp> cache-buster off these, which is not
    # part of the name of anything.
    base = unquote(url.rsplit("/", 1)[-1]).split("?")[0].removesuffix(".pdf")
    stem = re.sub(r"[^A-Za-z0-9]+", "-", base).strip("-") or "specials"
    start = (parsed or {}).get("from")
    if not start:
        return f"undated/undated_{stem}.pdf"
    return f"{start[:4]}/{start[5:7]}/{start}_{stem}.pdf"


def update(root: Path, config: dict, *, force: bool = False,
           html: str | None = None) -> dict:
    """Follow the link on the hours page and fold the poster into data/.

    Returns a summary; raising is left to the caller, which in the daily scrape
    logs and carries on. Specials are a bonus on top of the menu, and a poster
    R&DE has reshaped must not cost us a night's menus.
    """
    page = html if html is not None else fetch_page()
    url = find_link(page)
    if not url:
        return {"url": None, "status": "no link on the hours page"}

    store = load(root)
    existing = next((c for c in store["calendars"] if c["url"] == url), None)

    blob = download(url)
    digest = hashlib.sha256(blob).hexdigest()
    if existing and existing.get("sha256") == digest and not force:
        return {"url": url, "status": "unchanged", "entries": len(existing.get("entries", []))}

    parsed, error = None, None
    try:
        parsed = parse(blob)
    except Exception as exc:                          # a reshaped poster, not a crash
        error = f"{type(exc).__name__}: {exc}"

    # Archived whichever way it went: the page only ever points at the current
    # fortnight, so an unparsed poster is still the only copy that will exist.
    name = _archive_name(url, parsed)
    out = archive_dir(root) / name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(blob)

    record = {"url": url, "file": name, "sha256": digest,
              "fetched_at": dt.datetime.now(dt.timezone.utc)
                              .replace(microsecond=0).isoformat()}
    if parsed:
        attach_halls(parsed["entries"], alias_table(config))
        record.update(parsed)
    else:
        record["error"] = error

    store["calendars"] = [c for c in store["calendars"] if c["url"] != url] + [record]
    save(root, store)

    if error:
        return {"url": url, "status": "unreadable", "error": error, "file": name}
    unplaced = sorted({e["label"] for e in record["entries"]
                       if e["label"] and not e["halls"]})
    return {
        "url": url, "status": "updated" if existing else "new", "file": name,
        "title": record["title"], "meal": record["meal"],
        "from": record["from"], "to": record["to"],
        "entries": len(record["entries"]),
        "placed": sum(1 for e in record["entries"] if e["halls"]),
        "unplaced_labels": unplaced,
    }


def for_window(root: Path, window: list[str]) -> dict:
    """{date: {"halls": {hallId: [text]}, "notes": [text]}} over the published days.

    Every calendar is consulted, not just the newest: the archive keeps the ones
    that have rolled off the page, and a window can straddle two fortnights.
    """
    if not window:
        return {}
    out: dict[str, dict] = {}
    for calendar in load(root).get("calendars", []):
        meal = calendar.get("meal")
        for entry in calendar.get("entries", []):
            if _NOTHING_RE.match(entry["text"]):
                continue
            first = dt.date.fromisoformat(entry["from"])
            last = dt.date.fromisoformat(entry["to"])
            day = first
            while day <= last:
                iso = day.isoformat()
                day += dt.timedelta(days=1)
                if iso not in window:
                    continue
                slot = out.setdefault(iso, {"meal": meal, "halls": {}, "notes": []})
                if entry["halls"]:
                    for hall in entry["halls"]:
                        texts = slot["halls"].setdefault(hall, [])
                        if entry["text"] not in texts:
                            texts.append(entry["text"])
                elif entry["text"] not in slot["notes"]:
                    slot["notes"].append(entry["text"])
    return out


def dishes(root: Path) -> list[dict]:
    """Every special tied to a hall, as {"text", "from", "to"}, for the catalog.

    A special is served as a dish, so it is drawn like one. Notes -- entries no
    hall claims -- are announcements, not food, and are left out.
    """
    seen: dict[str, dict] = {}
    for calendar in load(root).get("calendars", []):
        for entry in calendar.get("entries", []):
            if not entry.get("halls") or _NOTHING_RE.match(entry["text"]):
                continue
            span = seen.setdefault(entry["text"], {
                "text": entry["text"], "from": entry["from"], "to": entry["to"],
            })
            span["from"] = min(span["from"], entry["from"])
            span["to"] = max(span["to"], entry["to"])
    return list(seen.values())


def texts(root: Path) -> list[str]:
    """Every distinct special and note, for the Chinese layer to translate."""
    seen = {}
    for calendar in load(root).get("calendars", []):
        for entry in calendar.get("entries", []):
            if not _NOTHING_RE.match(entry["text"]):
                seen[entry["text"]] = entry["text"]
    return list(seen)
