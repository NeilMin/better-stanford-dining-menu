"""Cut each hall's logo out of the R&DE dining halls map.

R&DE draws every hall's logo on one map image and publishes nothing else: there
is no per-hall logo file anywhere on rde.stanford.edu, in its sitemap, or in the
Wayback index of its file tree. So the map *is* the source, and the logos are
pixel rectangles inside it -- recorded in config/logos.json and verified by hand,
the same way config/halls.json holds the hours.

That makes the crop boxes coordinates into one specific file, so the file's
digest is recorded alongside them. A map redraw moves every logo at once and
silently turns eight crops into eight pieces of street: `check()` refuses to cut
against a map it does not recognise, and `make logos-diff` says what changed.

Logos are written at 2x the box the page gives them, because that is the only
resolution that exists -- the map is 1920px wide and a hall's logo is 30-145px
tall inside it, so the header is sized around what the source can carry rather
than the other way round.
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import requests
from PIL import Image, ImageFilter

CONFIG = "config/logos.json"


def load(root: Path) -> dict:
    return json.loads((root / CONFIG).read_text())


def out_dir(root: Path) -> Path:
    return root / "data" / "logos"


def fetch(config: dict, timeout: int = 60) -> bytes:
    r = requests.get(config["_source"], timeout=timeout,
                     headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return r.content


def check(config: dict, blob: bytes) -> dict:
    """Compare a downloaded map against the one the boxes were read off."""
    digest = hashlib.sha256(blob).hexdigest()
    size = list(Image.open(io.BytesIO(blob)).size)
    return {
        "sha256": digest,
        "size": size,
        "matches": digest == config["sha256"],
        "resized": size != list(config["map_size"]),
    }


def scale(box: list[int], render: dict) -> tuple[int, int]:
    """The pixel size one logo is written at.

    Height is what normalises the set -- every logo is drawn to the same line on
    the page. The width cap is the escape hatch for the wordmarks: Lakeside is
    five times as wide as it is tall, and matching its height to Branner's would
    run it off the side of a column.
    """
    w, h = box[2] - box[0], box[3] - box[1]
    out_h = render["height"]
    out_w = max(1, round(w * out_h / h))
    if out_w > render["max_width"]:
        out_w = render["max_width"]
        out_h = max(1, round(h * out_w / w))
    return out_w, out_h


def _flatten(image: Image.Image, floor: int, saturation: int) -> Image.Image:
    """Whiten the map showing through the logo's callout box.

    The callouts on the map are slightly translucent, so a crop carries a wash
    of whatever the logo was standing on -- pale green parkland behind Ricker,
    pink buildings behind Arrillaga. The wash is bright and almost colourless;
    the logos are not, except for Arrillaga's cream roof panel, which is the one
    thing the thresholds have to spare. So the test is deliberately strict on
    both axes: bright *and* nearly grey.
    """
    px = image.load()
    for y in range(image.height):
        for x in range(image.width):
            r, g, b = px[x, y]
            high = max(r, g, b)
            if high >= floor and high - min(r, g, b) <= saturation:
                px[x, y] = (255, 255, 255)
    return image


def cut(config: dict, blob: bytes) -> dict[str, tuple[Image.Image, int, int]]:
    """{hall id: (image, css width, css height)} for every box in the config."""
    source = Image.open(io.BytesIO(blob)).convert("RGB")
    render = config["render"]
    amount = render.get("sharpen", 0)
    out = {}
    for hall_id, box in config["boxes"].items():
        w, h = scale(box, render)
        # LANCZOS both ways: most of these are mild upscales, because the map is
        # the highest resolution R&DE publishes. What the unsharp pass buys back
        # is the edge the JPEG lost, not detail -- these are flat-colour marks,
        # so the ringing an unsharp mask would show on a photograph has nothing
        # to bite on.
        crop = source.crop(tuple(box))
        if floor := render.get("flatten_above", 0):
            crop = _flatten(crop, floor, render.get("flatten_saturation", 30))
        image = crop.resize((w, h), Image.LANCZOS)
        if amount:
            image = image.filter(
                ImageFilter.UnsharpMask(radius=1.2, percent=round(amount * 100), threshold=2)
            )
        out[hall_id] = (image, w // 2, h // 2)
    return out


def write(root: Path, cuts: dict[str, tuple[Image.Image, int, int]]) -> dict[str, dict]:
    """Write data/logos/<hallId>.webp and return the index the site is built from."""
    directory = out_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    index = {}
    for hall_id, (image, css_w, css_h) in cuts.items():
        name = f"{hall_id}.webp"
        # Lossless: these are flat-colour marks with type in them, and a lossy
        # pass at this size smears the small caps under the wordmark.
        image.save(directory / name, "WEBP", lossless=True, quality=100, method=6)
        index[hall_id] = {"file": name, "w": css_w, "h": css_h}
    (directory / "index.json").write_text(
        json.dumps(index, indent=1, sort_keys=True) + "\n"
    )
    return index


def index(root: Path) -> dict[str, dict]:
    """The written logos, or {} if none have been cut yet."""
    path = out_dir(root) / "index.json"
    return json.loads(path.read_text()) if path.exists() else {}
