import io
import json
from unittest.mock import MagicMock, patch
from PIL import Image
import pytest

from bsdm.cloudflare import CloudflareClient, CloudflareError, CloudflareQuotaError
from scripts.gen_images import (
    crop_and_resize_to_card,
    generate_with_cloudflare,
    generate_with_search,
    generate_with_search_fallback,
    main,
)


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
    client.generate_image.assert_called_once_with("Ramen prompt", negative_prompt="neg prompt")


def test_generate_with_cloudflare_propagates_quota_error():
    client = MagicMock(spec=CloudflareClient)
    client.generate_image.side_effect = CloudflareQuotaError("Rate limit exceeded (429)")

    with pytest.raises(CloudflareQuotaError, match="Rate limit exceeded"):
        generate_with_cloudflare(client, "Ramen prompt", "neg prompt")


@patch("bsdm.web_image.search_food_image")
def test_generate_with_search_returns_image(mock_search):
    buf = io.BytesIO()
    Image.new("RGB", (800, 600), color="yellow").save(buf, format="JPEG")
    mock_search.return_value = buf.getvalue()

    mock_client = MagicMock()
    img, secs = generate_with_search("Curry", client=mock_client, min_score=7)
    assert isinstance(img, Image.Image)
    assert img.size == (1024, 576)
    assert abs(img.width / img.height - 16 / 9) < 0.01
    assert secs >= 0
    mock_search.assert_called_once_with("Curry", client=mock_client, min_score=7)


@patch("bsdm.web_image.search_food_image")
def test_generate_with_search_returns_none_on_no_data(mock_search):
    mock_search.return_value = None

    img, secs = generate_with_search("Unknown dish")
    assert img is None
    assert secs >= 0


@patch("bsdm.web_image.search_food_image")
def test_generate_with_search_returns_none_on_corrupt_data(mock_search):
    mock_search.return_value = b"corrupted non-image data"

    img, secs = generate_with_search("Broken dish")
    assert img is None
    assert secs >= 0


@pytest.fixture
def mock_gen_project(tmp_path):
    root = tmp_path / "project"
    root.mkdir(parents=True)
    data_dir = root / "data"
    data_dir.mkdir()
    images_dir = data_dir / "images"
    images_dir.mkdir()

    catalog = {
        "dish1": {
            "name": "Roast Chicken",
            "prompt": "Juicy roast chicken on a plate",
            "priority": 0,
            "min_order": 0,
            "needs_image": True,
            "image": None,
        },
        "dish2": {
            "name": "Steamed Broccoli",
            "prompt": "Fresh steamed broccoli florets",
            "priority": 2,
            "min_order": 5,
            "needs_image": True,
            "image": None,
        },
    }
    (data_dir / "dishes.json").write_text(json.dumps(catalog))
    return root


def test_main_tier1_web_search_accepted_before_ai(mock_gen_project, monkeypatch):
    monkeypatch.setattr("scripts.gen_images.ROOT", mock_gen_project)
    monkeypatch.setattr("scripts.gen_images.CATALOG", mock_gen_project / "data" / "dishes.json")
    monkeypatch.setattr("scripts.gen_images.IMAGES", mock_gen_project / "data" / "images")

    mock_cf = MagicMock()
    mock_cf.is_configured.return_value = True
    monkeypatch.setattr("scripts.gen_images.CloudflareClient", lambda *a, **kw: mock_cf)

    # Web search succeeds at Tier 1
    test_img = _make_test_image("orange")
    mock_search_card = MagicMock(return_value=(test_img, 0.4))
    monkeypatch.setattr("scripts.gen_images.generate_with_search", mock_search_card)

    mock_gen_cf = MagicMock()
    monkeypatch.setattr("scripts.gen_images.generate_with_cloudflare", mock_gen_cf)

    code = main(["--backend", "auto", "--limit", "1"])
    assert code == 0

    catalog = json.loads((mock_gen_project / "data" / "dishes.json").read_text())
    assert catalog["dish1"]["model"] == "web-search"
    assert catalog["dish1"]["image"] == "dish1.webp"
    assert (mock_gen_project / "data" / "images" / "dish1.webp").exists()

    # Tier 2 (AI Generation) was not called because Tier 1 succeeded
    assert not mock_gen_cf.called


def test_main_backend_auto_uses_cloudflare_flux_when_tier1_fails(mock_gen_project, monkeypatch):
    monkeypatch.setattr("scripts.gen_images.ROOT", mock_gen_project)
    monkeypatch.setattr("scripts.gen_images.CATALOG", mock_gen_project / "data" / "dishes.json")
    monkeypatch.setattr("scripts.gen_images.IMAGES", mock_gen_project / "data" / "images")

    mock_cf = MagicMock()
    mock_cf.is_configured.return_value = True
    monkeypatch.setattr("scripts.gen_images.CloudflareClient", lambda *a, **kw: mock_cf)

    # Tier 1 search returns None
    monkeypatch.setattr("scripts.gen_images.generate_with_search", lambda d, client=None, min_score=7: (None, 0.2))

    test_img = _make_test_image("green")
    monkeypatch.setattr("scripts.gen_images.generate_with_cloudflare", lambda client, p, n: (test_img, 0.5))

    code = main(["--backend", "auto", "--limit", "1"])
    assert code == 0

    catalog = json.loads((mock_gen_project / "data" / "dishes.json").read_text())
    assert catalog["dish1"]["model"] == "cf-flux"
    assert catalog["dish1"]["image"] == "dish1.webp"
    assert (mock_gen_project / "data" / "images" / "dish1.webp").exists()


def test_main_backend_auto_falls_back_to_comfyui_when_available(mock_gen_project, monkeypatch):
    monkeypatch.setattr("scripts.gen_images.ROOT", mock_gen_project)
    monkeypatch.setattr("scripts.gen_images.CATALOG", mock_gen_project / "data" / "dishes.json")
    monkeypatch.setattr("scripts.gen_images.IMAGES", mock_gen_project / "data" / "images")

    mock_cf = MagicMock()
    mock_cf.is_configured.return_value = False
    monkeypatch.setattr("scripts.gen_images.CloudflareClient", lambda *a, **kw: mock_cf)

    mock_comfy = MagicMock()
    mock_comfy.available.return_value = True
    test_img = _make_test_image("blue")
    mock_comfy.generate.return_value = (test_img, 1.2)
    monkeypatch.setattr("scripts.gen_images.ComfyClient", lambda *a, **kw: mock_comfy)

    code = main(["--backend", "auto", "--limit", "1"])
    assert code == 0

    catalog = json.loads((mock_gen_project / "data" / "dishes.json").read_text())
    assert catalog["dish1"]["model"] == "sdxl"
    assert catalog["dish1"]["image"] == "dish1.webp"


def test_main_cloudflare_quota_error_rescued_by_search_fallback(mock_gen_project, monkeypatch, capsys):
    monkeypatch.setattr("scripts.gen_images.ROOT", mock_gen_project)
    monkeypatch.setattr("scripts.gen_images.CATALOG", mock_gen_project / "data" / "dishes.json")
    monkeypatch.setattr("scripts.gen_images.IMAGES", mock_gen_project / "data" / "images")

    mock_cf = MagicMock()
    mock_cf.is_configured.return_value = True
    monkeypatch.setattr("scripts.gen_images.CloudflareClient", lambda *a, **kw: mock_cf)

    # Tier 1 fails
    monkeypatch.setattr("scripts.gen_images.generate_with_search", lambda d, client=None, min_score=7: (None, 0.1))

    # Cloudflare immediately raises quota error on dish1
    mock_gen_cf = MagicMock(side_effect=CloudflareQuotaError("Rate limit 429"))
    monkeypatch.setattr("scripts.gen_images.generate_with_cloudflare", mock_gen_cf)

    # Search fallback rescues dish1
    fallback_img = _make_test_image("orange")
    mock_fallback = MagicMock(return_value=(fallback_img, 0.3))
    monkeypatch.setattr("scripts.gen_images.generate_with_search_fallback", mock_fallback)

    code = main(["--backend", "cloudflare"])
    assert code == 0  # Clean exit on quota error
    err = capsys.readouterr().err
    assert "quota" in err.lower()

    # Dish 1 was rescued by search fallback
    catalog = json.loads((mock_gen_project / "data" / "dishes.json").read_text())
    assert catalog["dish1"]["image"] == "dish1.webp"
    assert catalog["dish1"]["model"] == "web-search"
    assert (mock_gen_project / "data" / "images" / "dish1.webp").exists()

    # Dish 2 was NOT attempted because quota_exceeded broke the loop after dish1
    assert catalog["dish2"]["image"] is None


def test_main_no_search_fallback_when_disabled(mock_gen_project, monkeypatch):
    monkeypatch.setattr("scripts.gen_images.ROOT", mock_gen_project)
    monkeypatch.setattr("scripts.gen_images.CATALOG", mock_gen_project / "data" / "dishes.json")
    monkeypatch.setattr("scripts.gen_images.IMAGES", mock_gen_project / "data" / "images")

    mock_cf = MagicMock()
    mock_cf.is_configured.return_value = True
    monkeypatch.setattr("scripts.gen_images.CloudflareClient", lambda *a, **kw: mock_cf)

    monkeypatch.setattr("scripts.gen_images.generate_with_search", lambda d, client=None, min_score=7: (None, 0.1))

    def fake_gen_cf(client, p, n):
        raise CloudflareError("Failed")

    monkeypatch.setattr("scripts.gen_images.generate_with_cloudflare", fake_gen_cf)

    mock_fallback = MagicMock()
    monkeypatch.setattr("scripts.gen_images.generate_with_search_fallback", mock_fallback)

    code = main(["--backend", "cloudflare", "--limit", "1", "--no-search-fallback", "--no-search-first"])
    assert code == 1  # 1 failure and 0 done
    assert not mock_fallback.called

    catalog = json.loads((mock_gen_project / "data" / "dishes.json").read_text())
    assert catalog["dish1"]["image"] is None


def test_main_limit_zero_exits_cleanly(mock_gen_project, monkeypatch):
    monkeypatch.setattr("scripts.gen_images.ROOT", mock_gen_project)
    monkeypatch.setattr("scripts.gen_images.CATALOG", mock_gen_project / "data" / "dishes.json")
    monkeypatch.setattr("scripts.gen_images.IMAGES", mock_gen_project / "data" / "images")

    code = main(["--limit", "0"])
    assert code == 0
