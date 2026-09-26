import io
import json
from unittest.mock import MagicMock

import pytest
from PIL import Image

from bsdm.cloudflare import KLEIN_MODEL, CloudflareClient, CloudflareQuotaError
from scripts import gen_images
from scripts.gen_images import crop_and_resize_to_card, generate_with_cloudflare, main


def _make_test_image(color: str = "red", size: tuple[int, int] = (1024, 576)) -> Image.Image:
    return Image.new("RGB", size, color=color)


def test_crop_and_resize_to_card():
    # Square 1000x1000 cropped to 16:9
    square = _make_test_image("blue", (1000, 1000))
    card = crop_and_resize_to_card(square)
    assert card.size == (1024, 576)

    # Wide 1600x600 cropped to 16:9
    wide = _make_test_image("yellow", (1600, 600))
    card = crop_and_resize_to_card(wide)
    assert card.size == (1024, 576)


def test_generate_with_cloudflare_returns_card_image():
    buf = io.BytesIO()
    Image.new("RGB", (1024, 1024), color="green").save(buf, format="PNG")
    png_bytes = buf.getvalue()

    client = MagicMock(spec=CloudflareClient)
    client.generate_image.return_value = png_bytes

    img, secs = generate_with_cloudflare(client, "Ramen prompt", "neg prompt")
    assert isinstance(img, Image.Image)
    assert img.size == (1024, 576)
    assert secs >= 0
    client.generate_image.assert_called_once_with("Ramen prompt", negative_prompt="neg prompt",
                                                  model=KLEIN_MODEL, seed=None)


def test_generate_with_cloudflare_propagates_quota_error():
    client = MagicMock(spec=CloudflareClient)
    client.generate_image.side_effect = CloudflareQuotaError("Rate limit exceeded (429)")

    with pytest.raises(CloudflareQuotaError, match="Rate limit exceeded"):
        generate_with_cloudflare(client, "Ramen prompt", "neg prompt")


@pytest.fixture
def proj(tmp_path, monkeypatch, fake_llm):
    root = tmp_path / "project"
    (root / "data" / "images").mkdir(parents=True)
    catalog = {
        "dish1": {"name": "Roast Chicken", "ingredients": "chicken", "tags": [], "category": "poultry",
                  "prompt": "Juicy roast chicken on a plate", "priority": 0, "min_order": 0,
                  "needs_image": True, "image": None},
        "dish2": {"name": "Steamed Broccoli", "ingredients": "broccoli", "tags": ["vegan"],
                  "category": "vegan", "prompt": "Fresh steamed broccoli florets", "priority": 2,
                  "min_order": 5, "needs_image": True, "image": None},
    }
    (root / "data" / "dishes.json").write_text(json.dumps(catalog))
    monkeypatch.setattr(gen_images, "ROOT", root)
    monkeypatch.setattr(gen_images, "CATALOG", root / "data" / "dishes.json")
    monkeypatch.setattr(gen_images, "IMAGES", root / "data" / "images")
    monkeypatch.setattr(gen_images, "pick_llm", lambda *a, **kw: fake_llm)

    comfy = MagicMock()
    comfy.available.return_value = False
    monkeypatch.setattr(gen_images, "ComfyClient", lambda *a, **kw: comfy)
    cf = MagicMock(spec=CloudflareClient)
    cf.is_configured.return_value = True
    monkeypatch.setattr(gen_images, "CloudflareClient", lambda *a, **kw: cf)
    return root, comfy, cf


BRIEF = {"dish": "roast chicken", "look": "golden pieces", "vessel": "plate", "avoid": [],
         "checks": [{"q": "Is it chicken?", "yes": True}]}
PASS = {"answers": ["yes", "yes", "no", "no"], "seen": "chicken"}


def test_auto_draws_with_cloudflare_when_comfyui_is_down(proj, monkeypatch, fake_llm):
    root, _comfy, _cf = proj
    drawn = MagicMock(return_value=(_make_test_image(), 0.2))
    monkeypatch.setattr(gen_images, "generate_with_cloudflare", drawn)
    fake_llm.briefs.append(BRIEF)
    fake_llm.verdicts.append(PASS)

    assert main(["--limit", "1"]) == 0
    assert drawn.call_count == 1
    assert json.loads((root / "data" / "dishes.json").read_text())["dish1"]["model"] == "cf-klein"


def test_a_spent_cloudflare_quota_stops_the_run_cleanly(proj, monkeypatch, fake_llm):
    """Tomorrow's allocation will draw them; a red run would say nothing new."""
    _root, _comfy, _cf = proj
    drawn = MagicMock(side_effect=CloudflareQuotaError("429"))
    monkeypatch.setattr(gen_images, "generate_with_cloudflare", drawn)
    fake_llm.briefs.append(BRIEF)

    assert main([]) == 0
    assert drawn.call_count == 1, "kept asking after the quota was gone"


def test_nothing_to_draw_with_is_an_error(proj):
    _root, _comfy, cf = proj
    cf.is_configured.return_value = False
    assert main([]) == 2


def test_main_limit_zero_exits_cleanly(proj):
    assert main(["--limit", "0"]) == 0
