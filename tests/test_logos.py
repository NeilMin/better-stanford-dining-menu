"""Cutting the hall logos out of the R&DE map.

config/logos.json is pixel coordinates into one specific JPEG, which is why its
digest sits next to them: a redraw moves all eight at once and would turn the
crops into eight rectangles of street.
"""

from __future__ import annotations

import hashlib
import io
import json

import pytest
from PIL import Image

from bsdm import logos as logolib

RENDER = {"height": 72, "max_width": 240, "sharpen": 0.5,
          "flatten_above": 224, "flatten_saturation": 26}


def png(width, height, colour=(20, 40, 160)):
    image = Image.new("RGB", (width, height), colour)
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


@pytest.fixture
def map_blob():
    """A map with two "logos" painted into it: a wordmark and a roundel."""
    image = Image.new("RGB", (400, 200), (255, 255, 255))
    image.paste(Image.new("RGB", (100, 20), (20, 40, 160)), (10, 10))    # 5:1
    image.paste(Image.new("RGB", (30, 40), (100, 20, 90)), (200, 100))   # 3:4
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


@pytest.fixture
def config(map_blob):
    return {
        "_source": "https://rde.stanford.edu/map.jpg",
        "sha256": hashlib.sha256(map_blob).hexdigest(),
        "map_size": [400, 200],
        "render": dict(RENDER),
        "boxes": {"lakeside": [10, 10, 110, 30], "branner": [200, 100, 230, 140]},
    }


class TestScale:
    def test_height_is_what_normalises_the_set(self):
        """Every logo is drawn to the same line on the page."""
        assert logolib.scale([0, 0, 100, 50], RENDER) == (144, 72)

    def test_a_wordmark_hits_the_width_cap_and_gives_up_height(self):
        """Lakeside is five times as wide as it is tall; matching its height to
        Branner's would run it off the side of a column."""
        width, height = logolib.scale([0, 0, 500, 50], {**RENDER, "max_width": 240})
        assert width == 240 and height == 24

    def test_a_roundel_taller_than_it_is_wide_comes_out_smallest(self):
        """Which is the price of normalising on height, and is accepted: it is
        the only round green-and-purple one in the row."""
        assert logolib.scale([0, 0, 30, 40], RENDER) == (54, 72)

    def test_never_zero(self):
        width, height = logolib.scale([0, 0, 1, 400], RENDER)
        assert width >= 1 and height >= 1


class TestCheck:
    def test_the_map_the_boxes_were_read_off(self, config, map_blob):
        got = logolib.check(config, map_blob)
        assert got["matches"] and not got["resized"]
        assert got["size"] == [400, 200]

    def test_a_redrawn_map_is_refused(self, config):
        """Not fussiness: the crops would become eight pieces of street, and
        nothing downstream would notice."""
        got = logolib.check(config, png(400, 200, (7, 7, 7)))
        assert not got["matches"]

    def test_a_resized_map_is_called_out_separately(self, config):
        got = logolib.check(config, png(1920, 680))
        assert not got["matches"] and got["resized"]


class TestCut:
    def test_one_image_per_box_at_the_rendered_size(self, config, map_blob):
        cuts = logolib.cut(config, map_blob)
        assert set(cuts) == {"lakeside", "branner"}
        image, css_w, css_h = cuts["lakeside"]
        assert (image.width, image.height) == (240, 48), "5:1 wordmark, capped on width"
        assert (css_w, css_h) == (120, 24), "written at 2x the box the page gives it"

    def test_the_wash_behind_a_logo_is_flattened_to_white(self, config, map_blob):
        """The callouts on the map are slightly translucent, so a crop carries
        a wash of whatever the logo was standing on."""
        wash = Image.new("RGB", (40, 40), (238, 240, 237))     # bright and nearly grey
        source = Image.open(io.BytesIO(map_blob)).convert("RGB")
        source.paste(wash, (300, 10))
        buffer = io.BytesIO()
        source.save(buffer, "PNG")
        config = {**config, "sha256": "", "boxes": {"wash": [300, 10, 340, 50]}}

        image, _, _ = logolib.cut(config, buffer.getvalue())["wash"]
        assert image.getpixel((image.width // 2, image.height // 2)) == (255, 255, 255)

    def test_but_a_bright_colour_is_spared(self, config, map_blob):
        """Arrillaga's cream roof panel is the one thing the thresholds have to
        spare, so the test is strict on both axes: bright *and* nearly grey."""
        cream = Image.new("RGB", (40, 40), (245, 230, 180))
        source = Image.open(io.BytesIO(map_blob)).convert("RGB")
        source.paste(cream, (300, 10))
        buffer = io.BytesIO()
        source.save(buffer, "PNG")
        config = {**config, "sha256": "",
                  "render": {**RENDER, "sharpen": 0}, "boxes": {"roof": [300, 10, 340, 50]}}

        image, _, _ = logolib.cut(config, buffer.getvalue())["roof"]
        assert image.getpixel((image.width // 2, image.height // 2)) != (255, 255, 255)


class TestWrite:
    def test_writes_a_file_and_an_index_per_hall(self, project, config, map_blob):
        index = logolib.write(project.root, logolib.cut(config, map_blob))
        assert index["lakeside"] == {"file": "lakeside.webp", "w": 120, "h": 24}
        assert (logolib.out_dir(project.root) / "lakeside.webp").exists()
        assert json.loads((logolib.out_dir(project.root) / "index.json").read_text()) == index

    def test_the_files_are_lossless(self, project, config, map_blob):
        """Flat-colour marks with type in them; a lossy pass at this size
        smears the small caps under the wordmark."""
        logolib.write(project.root, logolib.cut(config, map_blob))
        with Image.open(logolib.out_dir(project.root) / "lakeside.webp") as im:
            assert im.format == "WEBP"
            assert im.getpixel((5, 5)) == (20, 40, 160), "the mark's own colour, unsmeared"

    def test_the_index_is_what_the_build_reads(self, project, config, map_blob):
        assert logolib.index(project.root) == {}, "no logos cut yet is not an error"
        written = logolib.write(project.root, logolib.cut(config, map_blob))
        assert logolib.index(project.root) == written
