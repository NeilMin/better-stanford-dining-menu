from __future__ import annotations

import io
from unittest.mock import MagicMock, patch
from PIL import Image
import pytest
import requests

from bsdm.web_image import (
    clean_search_query,
    is_aspect_ratio_safe,
    search_duckduckgo,
    search_food_image,
    search_pexels,
    search_wikipedia,
)


def _make_fake_image(width: int = 400, height: int = 300, color: str = "blue") -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGB", (width, height), color=color)
    img.save(buf, format="JPEG", quality=95)
    data = buf.getvalue()
    if len(data) <= 2048:
        buf = io.BytesIO()
        img = Image.new("RGB", (500, 500), color=color)
        img.save(buf, format="JPEG", quality=95)
        data = buf.getvalue()
    return data


def test_clean_search_query():
    assert clean_search_query("Chicken Tikka Masala (Halal)") == "Chicken Tikka Masala"
    assert clean_search_query("Allergen Friendly Pizza Station") == "Pizza"
    assert clean_search_query("House-made Pasta Bar") == "Pasta"
    assert clean_search_query("Curry, Rice, Salad") == "Curry"
    assert clean_search_query("Steamed Broccoli") == "Steamed Broccoli"


def test_is_aspect_ratio_safe():
    assert is_aspect_ratio_safe(1024, 1024)  # 1:1
    assert is_aspect_ratio_safe(1280, 720)   # 16:9
    assert is_aspect_ratio_safe(800, 600)    # 4:3
    # Too tall (portrait)
    assert not is_aspect_ratio_safe(600, 900)  # 900/600 = 1.5 > 1.25
    # Too wide (extreme banner)
    assert not is_aspect_ratio_safe(2000, 500)  # 2000/500 = 4.0 > 2.5
    # Invalid
    assert not is_aspect_ratio_safe(0, 100)


def test_search_wikipedia_success():
    session = MagicMock()
    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = {
        "query": {
            "pages": {
                "123": {
                    "index": 1,
                    "thumbnail": {"source": "https://example.com/pizza.jpg", "width": 1024, "height": 768},
                },
                "124": {
                    "index": 2,
                    "thumbnail": {"source": "https://example.com/diagram.svg", "width": 500, "height": 500},
                },
            }
        }
    }
    session.get.return_value = mock_resp

    results = search_wikipedia("Pepperoni Pizza", session)
    assert len(results) == 1
    assert results[0] == ("https://example.com/pizza.jpg", 1024, 768)


def test_search_pexels_success():
    session = MagicMock()
    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = {
        "photos": [
            {
                "width": 1200,
                "height": 800,
                "src": {"large2x": "https://example.com/pexels_dish.jpg"},
            }
        ]
    }
    session.get.return_value = mock_resp

    results = search_pexels("Bulgogi", session, api_key="fake-key")
    assert len(results) == 1
    assert results[0] == ("https://example.com/pexels_dish.jpg", 1200, 800)


def test_search_duckduckgo_success():
    session = MagicMock()
    r_token = MagicMock(status_code=200, text='vqd="4-12345"')
    r_search = MagicMock(status_code=200)
    r_search.json.return_value = {
        "results": [{"image": "https://example.com/ddg_dish.jpg", "width": 800, "height": 600}]
    }
    session.get.side_effect = [r_token, r_search]

    results = search_duckduckgo("Ramen", session)
    assert len(results) == 1
    assert results[0] == ("https://example.com/ddg_dish.jpg", 800, 600)


@patch("requests.Session.get")
def test_search_food_image_via_wikipedia(mock_get):
    fake_img = _make_fake_image(width=800, height=600)

    # Wikipedia API response
    r_wiki = MagicMock(status_code=200)
    r_wiki.json.return_value = {
        "query": {
            "pages": {
                "1": {
                    "index": 1,
                    "thumbnail": {"source": "https://example.com/dish.jpg", "width": 800, "height": 600},
                }
            }
        }
    }
    # Image download response
    r_img = MagicMock(status_code=200, content=fake_img)

    mock_get.side_effect = [r_wiki, r_img]

    result = search_food_image("Beef Bulgogi")
    assert result == fake_img


@patch("requests.Session.get")
def test_search_food_image_with_vlm_judge_accepts(mock_get):
    fake_img = _make_fake_image(width=800, height=600)

    r_wiki = MagicMock(status_code=200)
    r_wiki.json.return_value = {
        "query": {
            "pages": {
                "1": {
                    "thumbnail": {"source": "https://example.com/dish.jpg", "width": 800, "height": 600},
                }
            }
        }
    }
    r_img = MagicMock(status_code=200, content=fake_img)
    mock_get.side_effect = [r_wiki, r_img]

    mock_client = MagicMock()
    mock_client.is_configured.return_value = True
    mock_client.evaluate_image.return_value = {"valid": True, "score": 9, "reason": "Appetizing cooked dish"}

    result = search_food_image("Chicken Tikka Masala", client=mock_client)
    assert result == fake_img
    mock_client.evaluate_image.assert_called_once_with(fake_img, "Chicken Tikka Masala")


@patch("requests.Session.get")
def test_search_food_image_with_vlm_judge_rejects_and_returns_none(mock_get):
    fake_img = _make_fake_image(width=800, height=600)

    r_wiki = MagicMock(status_code=200)
    r_wiki.json.return_value = {
        "query": {
            "pages": {
                "1": {
                    "thumbnail": {"source": "https://example.com/dish.jpg", "width": 800, "height": 600},
                }
            }
        }
    }
    r_img = MagicMock(status_code=200, content=fake_img)
    mock_get.side_effect = [r_wiki, r_img]

    mock_client = MagicMock()
    mock_client.is_configured.return_value = True
    # VLM rejects as raw dough
    mock_client.evaluate_image.return_value = {"valid": False, "score": 3, "reason": "Uncooked raw dough"}

    result = search_food_image("Pepperoni Pizza", client=mock_client)
    assert result is None
    mock_client.evaluate_image.assert_called_once_with(fake_img, "Pepperoni Pizza")


@patch("requests.Session.get")
def test_search_food_image_falls_back_to_duckduckgo(mock_get):
    fake_img = _make_fake_image(width=800, height=600)

    # Wikipedia returns empty
    r_wiki = MagicMock(status_code=200)
    r_wiki.json.return_value = {"query": {"pages": {}}}

    # DDG token
    r_ddg_token = MagicMock(status_code=200, text='vqd="12345"')
    # DDG search
    r_ddg_search = MagicMock(status_code=200)
    r_ddg_search.json.return_value = {
        "results": [{"image": "https://example.com/ddg.jpg", "width": 800, "height": 600}]
    }
    # Image download
    r_img = MagicMock(status_code=200, content=fake_img)

    mock_get.side_effect = [r_wiki, r_ddg_token, r_ddg_search, r_img]

    result = search_food_image("Unusual Stanford Specialty")
    assert result == fake_img


@patch("requests.Session.get")
def test_search_food_image_skips_bad_geometry(mock_get):
    # Candidate 1: 500x1200 (tall vertical portrait)
    # Candidate 2: 800x600 (safe)
    fake_img_good = _make_fake_image(width=800, height=600)

    r_wiki = MagicMock(status_code=200)
    r_wiki.json.return_value = {
        "query": {
            "pages": {
                "1": {
                    "index": 1,
                    "thumbnail": {"source": "https://example.com/tall.jpg", "width": 500, "height": 1200},
                },
                "2": {
                    "index": 2,
                    "thumbnail": {"source": "https://example.com/good.jpg", "width": 800, "height": 600},
                },
            }
        }
    }
    r_good_img = MagicMock(status_code=200, content=fake_img_good)
    # Only r_wiki and r_good_img should be called, tall.jpg skipped
    mock_get.side_effect = [r_wiki, r_good_img]

    result = search_food_image("Pasta")
    assert result == fake_img_good
