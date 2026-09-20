import io
import json
from unittest.mock import MagicMock, patch
from PIL import Image
import pytest

from bsdm.cloudflare import CloudflareClient, CloudflareError, CloudflareQuotaError
from scripts.gen_images import (
    generate_with_cloudflare,
    generate_with_search_fallback,
    main,
)


def test_generate_with_cloudflare_returns_image():
    buf = io.BytesIO()
    Image.new("RGB", (100, 100), color="green").save(buf, format="PNG")
    png_bytes = buf.getvalue()

    client = MagicMock(spec=CloudflareClient)
    client.generate_image.return_value = png_bytes

    img, secs = generate_with_cloudflare(client, "Ramen prompt", "neg prompt")
    assert isinstance(img, Image.Image)
    assert secs >= 0
    client.generate_image.assert_called_once_with("Ramen prompt", negative_prompt="neg prompt")


def test_generate_with_cloudflare_propagates_quota_error():
    client = MagicMock(spec=CloudflareClient)
    client.generate_image.side_effect = CloudflareQuotaError("Rate limit exceeded (429)")

    with pytest.raises(CloudflareQuotaError, match="Rate limit exceeded"):
        generate_with_cloudflare(client, "Ramen prompt", "neg prompt")


@patch("bsdm.web_image.search_food_image")
def test_generate_with_search_fallback_returns_image(mock_search):
    buf = io.BytesIO()
    Image.new("RGB", (300, 300), color="yellow").save(buf, format="JPEG")
    mock_search.return_value = buf.getvalue()

    img, secs = generate_with_search_fallback("Curry")
    assert isinstance(img, Image.Image)
    assert img.size == (1024, 576)
    assert abs(img.width / img.height - 16 / 9) < 0.01
    assert secs >= 0
    mock_search.assert_called_once_with("Curry")


@patch("bsdm.web_image.search_food_image")
def test_generate_with_search_fallback_crops_wide_image(mock_search):
    buf = io.BytesIO()
    Image.new("RGB", (1600, 600), color="blue").save(buf, format="JPEG")
    mock_search.return_value = buf.getvalue()

    img, secs = generate_with_search_fallback("Wide Curry")
    assert isinstance(img, Image.Image)
    assert img.size == (1024, 576)


@patch("bsdm.web_image.search_food_image")
def test_generate_with_search_fallback_returns_none_on_no_data(mock_search):
    mock_search.return_value = None

    img, secs = generate_with_search_fallback("Unknown dish")
    assert img is None
    assert secs >= 0


@patch("bsdm.web_image.search_food_image")
def test_generate_with_search_fallback_returns_none_on_corrupt_data(mock_search):
    mock_search.return_value = b"corrupted non-image data"

    img, secs = generate_with_search_fallback("Broken dish")
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

    # Catalog with two dishes needing images
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


def _make_test_image(color: str = "red") -> Image.Image:
    return Image.new("RGB", (1024, 576), color=color)


def test_main_backend_explicit_cloudflare_unconfigured_fails(mock_gen_project, monkeypatch, capsys):
    monkeypatch.setattr("scripts.gen_images.ROOT", mock_gen_project)
    monkeypatch.setattr("scripts.gen_images.CATALOG", mock_gen_project / "data" / "dishes.json")
    monkeypatch.setattr("scripts.gen_images.IMAGES", mock_gen_project / "data" / "images")

    mock_cf = MagicMock()
    mock_cf.is_configured.return_value = False
    monkeypatch.setattr("scripts.gen_images.CloudflareClient", lambda *a, **kw: mock_cf)

    code = main(["--backend", "cloudflare"])
    assert code != 0
    err = capsys.readouterr().err
    assert "CF_ACCOUNT_ID" in err or "Cloudflare" in err


def test_main_backend_auto_uses_cloudflare_when_configured(mock_gen_project, monkeypatch):
    monkeypatch.setattr("scripts.gen_images.ROOT", mock_gen_project)
    monkeypatch.setattr("scripts.gen_images.CATALOG", mock_gen_project / "data" / "dishes.json")
    monkeypatch.setattr("scripts.gen_images.IMAGES", mock_gen_project / "data" / "images")

    mock_cf = MagicMock()
    mock_cf.is_configured.return_value = True
    monkeypatch.setattr("scripts.gen_images.CloudflareClient", lambda *a, **kw: mock_cf)

    test_img = _make_test_image("green")
    monkeypatch.setattr("scripts.gen_images.generate_with_cloudflare", lambda client, p, n: (test_img, 0.5))

    code = main(["--backend", "auto", "--limit", "1"])
    assert code == 0

    catalog = json.loads((mock_gen_project / "data" / "dishes.json").read_text())
    assert catalog["dish1"]["model"] == "cf-sdxl-lightning"
    assert catalog["dish1"]["image"] == "dish1.webp"
    assert (mock_gen_project / "data" / "images" / "dish1.webp").exists()


def test_main_backend_auto_falls_back_to_comfyui(mock_gen_project, monkeypatch):
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


def test_main_cloudflare_quota_error_stops_gracefully(mock_gen_project, monkeypatch, capsys):
    monkeypatch.setattr("scripts.gen_images.ROOT", mock_gen_project)
    monkeypatch.setattr("scripts.gen_images.CATALOG", mock_gen_project / "data" / "dishes.json")
    monkeypatch.setattr("scripts.gen_images.IMAGES", mock_gen_project / "data" / "images")

    mock_cf = MagicMock()
    mock_cf.is_configured.return_value = True
    monkeypatch.setattr("scripts.gen_images.CloudflareClient", lambda *a, **kw: mock_cf)

    calls = 0

    def fake_gen_cf(client, p, n):
        nonlocal calls
        calls += 1
        if calls == 1:
            return _make_test_image("green"), 0.5
        raise CloudflareQuotaError("Rate limit 429")

    monkeypatch.setattr("scripts.gen_images.generate_with_cloudflare", fake_gen_cf)
    monkeypatch.setattr("scripts.gen_images.generate_with_search_fallback", lambda d: (None, 0.1))

    code = main(["--backend", "cloudflare"])
    assert code == 0  # Clean exit on quota error
    err = capsys.readouterr().err
    assert "quota" in err.lower()

    catalog = json.loads((mock_gen_project / "data" / "dishes.json").read_text())
    assert catalog["dish1"]["image"] == "dish1.webp"
    assert catalog["dish2"]["image"] is None


def test_main_cloudflare_quota_error_rescued_by_search_fallback(mock_gen_project, monkeypatch, capsys):
    monkeypatch.setattr("scripts.gen_images.ROOT", mock_gen_project)
    monkeypatch.setattr("scripts.gen_images.CATALOG", mock_gen_project / "data" / "dishes.json")
    monkeypatch.setattr("scripts.gen_images.IMAGES", mock_gen_project / "data" / "images")

    mock_cf = MagicMock()
    mock_cf.is_configured.return_value = True
    monkeypatch.setattr("scripts.gen_images.CloudflareClient", lambda *a, **kw: mock_cf)

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
    assert mock_gen_cf.call_count == 1
    assert mock_fallback.call_count == 1


def test_main_search_fallback_on_failure(mock_gen_project, monkeypatch):
    monkeypatch.setattr("scripts.gen_images.ROOT", mock_gen_project)
    monkeypatch.setattr("scripts.gen_images.CATALOG", mock_gen_project / "data" / "dishes.json")
    monkeypatch.setattr("scripts.gen_images.IMAGES", mock_gen_project / "data" / "images")

    mock_cf = MagicMock()
    mock_cf.is_configured.return_value = True
    monkeypatch.setattr("scripts.gen_images.CloudflareClient", lambda *a, **kw: mock_cf)

    # Cloudflare generation fails with CloudflareError
    def fake_gen_cf(client, p, n):
        raise CloudflareError("Generation rejected / filtered")

    monkeypatch.setattr("scripts.gen_images.generate_with_cloudflare", fake_gen_cf)

    # Search fallback succeeds
    fallback_img = _make_test_image("orange")
    mock_fallback = MagicMock(return_value=(fallback_img, 0.3))
    monkeypatch.setattr("scripts.gen_images.generate_with_search_fallback", mock_fallback)

    code = main(["--backend", "cloudflare", "--limit", "1"])
    assert code == 0
    assert mock_fallback.called

    catalog = json.loads((mock_gen_project / "data" / "dishes.json").read_text())
    assert catalog["dish1"]["model"] == "web-search"
    assert catalog["dish1"]["image"] == "dish1.webp"


def test_main_no_search_fallback_when_disabled(mock_gen_project, monkeypatch):
    monkeypatch.setattr("scripts.gen_images.ROOT", mock_gen_project)
    monkeypatch.setattr("scripts.gen_images.CATALOG", mock_gen_project / "data" / "dishes.json")
    monkeypatch.setattr("scripts.gen_images.IMAGES", mock_gen_project / "data" / "images")

    mock_cf = MagicMock()
    mock_cf.is_configured.return_value = True
    monkeypatch.setattr("scripts.gen_images.CloudflareClient", lambda *a, **kw: mock_cf)

    def fake_gen_cf(client, p, n):
        raise CloudflareError("Failed")

    monkeypatch.setattr("scripts.gen_images.generate_with_cloudflare", fake_gen_cf)

    mock_fallback = MagicMock()
    monkeypatch.setattr("scripts.gen_images.generate_with_search_fallback", mock_fallback)

    code = main(["--backend", "cloudflare", "--limit", "1", "--no-search-fallback"])
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
