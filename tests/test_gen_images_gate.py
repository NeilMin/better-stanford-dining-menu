import io
import json
from unittest.mock import MagicMock, patch
from PIL import Image
import pytest

from bsdm.cloudflare import CloudflareClient
from scripts.gen_images import (
    crop_and_resize_to_card,
    main,
)


def _make_test_image(color: str = "red", size: tuple[int, int] = (1024, 576)) -> Image.Image:
    return Image.new("RGB", size, color=color)


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


def test_vlm_retry_logic():
    # Test helper verifying score threshold logic
    scores = [4, 8]  # First fails, second succeeds
    client = MagicMock()
    client.is_configured.return_value = True
    client.evaluate_food_image.side_effect = [
        {"valid": False, "score": 4, "reason": "Plastic texture"},
        {"valid": True, "score": 8, "reason": "Good plating and sharp focus"},
    ]

    attempts = 0
    accepted = False
    for attempt in range(3):
        attempts += 1
        res = client.evaluate_food_image(b"fake", "Dish")
        if res["valid"] and res["score"] >= 7:
            accepted = True
            break

    assert attempts == 2
    assert accepted is True


def test_main_vlm_gate_pass_first_try(mock_gen_project, monkeypatch):
    monkeypatch.setattr("scripts.gen_images.ROOT", mock_gen_project)
    monkeypatch.setattr("scripts.gen_images.CATALOG", mock_gen_project / "data" / "dishes.json")
    monkeypatch.setattr("scripts.gen_images.IMAGES", mock_gen_project / "data" / "images")

    mock_cf = MagicMock(spec=CloudflareClient)
    mock_cf.is_configured.return_value = True
    mock_cf.evaluate_food_image.return_value = {
        "valid": True,
        "score": 9,
        "reason": "Appetizing dish with crisp textures",
    }
    monkeypatch.setattr("scripts.gen_images.CloudflareClient", lambda *a, **kw: mock_cf)

    test_img = _make_test_image("red")
    mock_gen_cf = MagicMock(return_value=(test_img, 0.4))
    monkeypatch.setattr("scripts.gen_images.generate_with_cloudflare", mock_gen_cf)

    code = main(["--backend", "cloudflare", "--limit", "1", "--no-search-first"])
    assert code == 0

    assert mock_gen_cf.call_count == 1
    assert mock_cf.evaluate_food_image.call_count == 1

    catalog = json.loads((mock_gen_project / "data" / "dishes.json").read_text())
    assert catalog["dish1"]["model"] == "cf-flux"
    assert catalog["dish1"]["image"] == "dish1.webp"
    assert catalog["dish1"]["vlm_score"] == 9
    assert catalog["dish1"]["vlm_reason"] == "Appetizing dish with crisp textures"
    assert (mock_gen_project / "data" / "images" / "dish1.webp").exists()


def test_main_vlm_gate_retry_and_succeed(mock_gen_project, monkeypatch):
    monkeypatch.setattr("scripts.gen_images.ROOT", mock_gen_project)
    monkeypatch.setattr("scripts.gen_images.CATALOG", mock_gen_project / "data" / "dishes.json")
    monkeypatch.setattr("scripts.gen_images.IMAGES", mock_gen_project / "data" / "images")

    mock_cf = MagicMock(spec=CloudflareClient)
    mock_cf.is_configured.return_value = True
    mock_cf.evaluate_food_image.side_effect = [
        {"valid": False, "score": 4, "reason": "Plastic look"},
        {"valid": True, "score": 8, "reason": "Crisp and juicy"},
    ]
    monkeypatch.setattr("scripts.gen_images.CloudflareClient", lambda *a, **kw: mock_cf)

    cf_calls = []

    def fake_cf(client, p, n):
        cf_calls.append(p)
        return _make_test_image("blue"), 0.3

    monkeypatch.setattr("scripts.gen_images.generate_with_cloudflare", fake_cf)

    code = main(["--backend", "cloudflare", "--limit", "1", "--no-search-first"])
    assert code == 0

    assert len(cf_calls) == 2
    assert mock_cf.evaluate_food_image.call_count == 2

    catalog = json.loads((mock_gen_project / "data" / "dishes.json").read_text())
    assert catalog["dish1"]["vlm_score"] == 8
    assert catalog["dish1"]["vlm_reason"] == "Crisp and juicy"


def test_main_vlm_gate_retries_exhausted_uses_best(mock_gen_project, monkeypatch):
    monkeypatch.setattr("scripts.gen_images.ROOT", mock_gen_project)
    monkeypatch.setattr("scripts.gen_images.CATALOG", mock_gen_project / "data" / "dishes.json")
    monkeypatch.setattr("scripts.gen_images.IMAGES", mock_gen_project / "data" / "images")

    mock_cf = MagicMock(spec=CloudflareClient)
    mock_cf.is_configured.return_value = True
    mock_cf.evaluate_food_image.side_effect = [
        {"valid": False, "score": 4, "reason": "Dim lighting"},
        {"valid": False, "score": 6, "reason": "Acceptable but slightly blurry"},
        {"valid": False, "score": 3, "reason": "Uncooked appearance"},
    ]
    monkeypatch.setattr("scripts.gen_images.CloudflareClient", lambda *a, **kw: mock_cf)

    test_img = _make_test_image("purple")
    monkeypatch.setattr("scripts.gen_images.generate_with_cloudflare", lambda c, p, n: (test_img, 0.4))

    code = main(["--backend", "cloudflare", "--limit", "1", "--no-search-first", "--max-vlm-retries", "3"])
    assert code == 0

    assert mock_cf.evaluate_food_image.call_count == 3

    catalog = json.loads((mock_gen_project / "data" / "dishes.json").read_text())
    assert catalog["dish1"]["vlm_score"] == 6
    assert catalog["dish1"]["vlm_reason"] == "Acceptable but slightly blurry"
    assert catalog["dish1"]["image"] == "dish1.webp"


def test_main_vlm_gate_disabled_flag(mock_gen_project, monkeypatch):
    monkeypatch.setattr("scripts.gen_images.ROOT", mock_gen_project)
    monkeypatch.setattr("scripts.gen_images.CATALOG", mock_gen_project / "data" / "dishes.json")
    monkeypatch.setattr("scripts.gen_images.IMAGES", mock_gen_project / "data" / "images")

    mock_cf = MagicMock(spec=CloudflareClient)
    mock_cf.is_configured.return_value = True
    monkeypatch.setattr("scripts.gen_images.CloudflareClient", lambda *a, **kw: mock_cf)

    test_img = _make_test_image("green")
    mock_gen_cf = MagicMock(return_value=(test_img, 0.5))
    monkeypatch.setattr("scripts.gen_images.generate_with_cloudflare", mock_gen_cf)

    code = main(["--backend", "cloudflare", "--limit", "1", "--no-search-first", "--no-vlm-gate"])
    assert code == 0

    assert mock_gen_cf.call_count == 1
    assert mock_cf.evaluate_food_image.call_count == 0

    catalog = json.loads((mock_gen_project / "data" / "dishes.json").read_text())
    assert catalog["dish1"]["image"] == "dish1.webp"
    assert "vlm_score" not in catalog["dish1"]


def test_main_vlm_gate_comfyui_retries_with_different_seeds(mock_gen_project, monkeypatch):
    monkeypatch.setattr("scripts.gen_images.ROOT", mock_gen_project)
    monkeypatch.setattr("scripts.gen_images.CATALOG", mock_gen_project / "data" / "dishes.json")
    monkeypatch.setattr("scripts.gen_images.IMAGES", mock_gen_project / "data" / "images")

    mock_cf = MagicMock(spec=CloudflareClient)
    mock_cf.is_configured.return_value = True
    mock_cf.evaluate_food_image.side_effect = [
        {"valid": False, "score": 5, "reason": "Messy styling"},
        {"valid": True, "score": 8, "reason": "Studio lighting"},
    ]
    monkeypatch.setattr("scripts.gen_images.CloudflareClient", lambda *a, **kw: mock_cf)

    mock_comfy = MagicMock()
    mock_comfy.available.return_value = True

    seeds_recorded = []

    def fake_comfy_generate(model, prompt, negative, seed, steps=None):
        seeds_recorded.append(seed)
        return _make_test_image("orange"), 1.1

    mock_comfy.generate.side_effect = fake_comfy_generate
    monkeypatch.setattr("scripts.gen_images.ComfyClient", lambda *a, **kw: mock_comfy)

    code = main(["--backend", "comfyui", "--limit", "1"])
    assert code == 0

    assert mock_comfy.generate.call_count == 2
    assert mock_cf.evaluate_food_image.call_count == 2
    assert seeds_recorded[0] != seeds_recorded[1]

    catalog = json.loads((mock_gen_project / "data" / "dishes.json").read_text())
    assert catalog["dish1"]["model"] == "sdxl"
    assert catalog["dish1"]["vlm_score"] == 8
    assert catalog["dish1"]["seed"] == seeds_recorded[1]


def test_main_vlm_gate_unconfigured_cf(mock_gen_project, monkeypatch):
    monkeypatch.setattr("scripts.gen_images.ROOT", mock_gen_project)
    monkeypatch.setattr("scripts.gen_images.CATALOG", mock_gen_project / "data" / "dishes.json")
    monkeypatch.setattr("scripts.gen_images.IMAGES", mock_gen_project / "data" / "images")

    mock_cf = MagicMock(spec=CloudflareClient)
    mock_cf.is_configured.return_value = False
    monkeypatch.setattr("scripts.gen_images.CloudflareClient", lambda *a, **kw: mock_cf)

    mock_comfy = MagicMock()
    mock_comfy.available.return_value = True
    mock_comfy.generate.return_value = (_make_test_image("teal"), 0.8)
    monkeypatch.setattr("scripts.gen_images.ComfyClient", lambda *a, **kw: mock_comfy)

    code = main(["--backend", "comfyui", "--limit", "1"])
    assert code == 0

    assert mock_comfy.generate.call_count == 1
    assert mock_cf.evaluate_food_image.call_count == 0

    catalog = json.loads((mock_gen_project / "data" / "dishes.json").read_text())
    assert catalog["dish1"]["image"] == "dish1.webp"
    assert "vlm_score" not in catalog["dish1"]


def test_main_vlm_gate_exact_threshold_seven(mock_gen_project, monkeypatch):
    monkeypatch.setattr("scripts.gen_images.ROOT", mock_gen_project)
    monkeypatch.setattr("scripts.gen_images.CATALOG", mock_gen_project / "data" / "dishes.json")
    monkeypatch.setattr("scripts.gen_images.IMAGES", mock_gen_project / "data" / "images")

    mock_cf = MagicMock(spec=CloudflareClient)
    mock_cf.is_configured.return_value = True
    mock_cf.evaluate_food_image.return_value = {
        "valid": True,
        "score": 7,
        "reason": "Borderline acceptable commercial standard",
    }
    monkeypatch.setattr("scripts.gen_images.CloudflareClient", lambda *a, **kw: mock_cf)

    test_img = _make_test_image("brown")
    monkeypatch.setattr("scripts.gen_images.generate_with_cloudflare", lambda c, p, n: (test_img, 0.4))

    code = main(["--backend", "cloudflare", "--limit", "1", "--no-search-first"])
    assert code == 0

    assert mock_cf.evaluate_food_image.call_count == 1
    catalog = json.loads((mock_gen_project / "data" / "dishes.json").read_text())
    assert catalog["dish1"]["vlm_score"] == 7
    assert catalog["dish1"]["vlm_reason"] == "Borderline acceptable commercial standard"


def test_main_vlm_gate_eval_exception_handling(mock_gen_project, monkeypatch, capsys):
    monkeypatch.setattr("scripts.gen_images.ROOT", mock_gen_project)
    monkeypatch.setattr("scripts.gen_images.CATALOG", mock_gen_project / "data" / "dishes.json")
    monkeypatch.setattr("scripts.gen_images.IMAGES", mock_gen_project / "data" / "images")

    mock_cf = MagicMock(spec=CloudflareClient)
    mock_cf.is_configured.return_value = True
    # First attempt raises exception during eval; second attempt succeeds
    mock_cf.evaluate_food_image.side_effect = [
        RuntimeError("Transient vision timeout"),
        {"valid": True, "score": 8, "reason": "Passed on retry"},
    ]
    monkeypatch.setattr("scripts.gen_images.CloudflareClient", lambda *a, **kw: mock_cf)

    test_img = _make_test_image("yellow")
    monkeypatch.setattr("scripts.gen_images.generate_with_cloudflare", lambda c, p, n: (test_img, 0.4))

    code = main(["--backend", "cloudflare", "--limit", "1", "--no-search-first"])
    assert code == 0

    assert mock_cf.evaluate_food_image.call_count == 2
    err = capsys.readouterr().err
    assert "Transient vision timeout" in err

    catalog = json.loads((mock_gen_project / "data" / "dishes.json").read_text())
    assert catalog["dish1"]["vlm_score"] == 8
    assert catalog["dish1"]["vlm_reason"] == "Passed on retry"

