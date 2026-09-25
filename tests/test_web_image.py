from __future__ import annotations

import io
from unittest.mock import MagicMock, patch
from PIL import Image
import pytest
import requests

from bsdm.web_image import (
    clean_search_query,
    is_aspect_ratio_safe,
    search_bing,
    search_duckduckgo,
    search_food_image,
    search_google_custom_search,
    search_pexels,
    search_unsplash,
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


def test_search_unsplash_success():
    session = MagicMock()
    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = {
        "results": [
            {
                "width": 1080,
                "height": 720,
                "urls": {"regular": "https://example.com/unsplash_taco.jpg"},
            }
        ]
    }
    session.get.return_value = mock_resp

    results = search_unsplash("Tacos", session)
    assert len(results) == 1
    assert results[0] == ("https://example.com/unsplash_taco.jpg", 1080, 720)


@patch("bsdm.web_image.search_bing")
@patch("bsdm.web_image.search_unsplash")
@patch("requests.Session.get")
def test_search_food_image_via_unsplash(mock_get, mock_unsplash, mock_bing):
    fake_img = _make_fake_image(width=800, height=600)
    mock_bing.return_value = []
    mock_unsplash.return_value = [("https://example.com/dish.jpg", 800, 600)]
    mock_get.return_value = MagicMock(status_code=200, content=fake_img)

    result = search_food_image("Beef Bulgogi", require_vlm=False)
    assert result == fake_img


@patch("bsdm.web_image.search_bing")
@patch("bsdm.web_image.search_unsplash")
@patch("bsdm.web_image.search_duckduckgo")
@patch("requests.Session.get")
def test_search_food_image_via_wikipedia(mock_get, mock_ddg, mock_unsplash, mock_bing):
    fake_img = _make_fake_image(width=800, height=600)
    mock_bing.return_value = []
    mock_unsplash.return_value = []
    mock_ddg.return_value = []

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

    result = search_food_image("Beef Bulgogi", require_vlm=False)
    assert result == fake_img


@patch("bsdm.web_image.search_bing")
@patch("bsdm.web_image.search_unsplash")
@patch("requests.Session.get")
def test_search_food_image_with_vlm_judge_accepts(mock_get, mock_unsplash, mock_bing):
    fake_img = _make_fake_image(width=800, height=600)
    mock_bing.return_value = []
    mock_unsplash.return_value = [("https://example.com/dish.jpg", 800, 600)]
    r_img = MagicMock(status_code=200, content=fake_img)
    mock_get.return_value = r_img

    mock_client = MagicMock()
    mock_client.is_configured.return_value = True
    mock_client.evaluate_food_image.return_value = {"valid": True, "score": 9, "reason": "Appetizing cooked dish"}

    result = search_food_image("Chicken Tikka Masala", client=mock_client)
    assert result == fake_img
    mock_client.evaluate_food_image.assert_called_once_with(fake_img, "Chicken Tikka Masala")


@patch("bsdm.web_image.search_bing")
@patch("bsdm.web_image.search_unsplash")
@patch("requests.Session.get")
def test_search_food_image_with_vlm_judge_rejects_and_returns_none(mock_get, mock_unsplash, mock_bing):
    fake_img = _make_fake_image(width=800, height=600)
    mock_bing.return_value = []
    mock_unsplash.return_value = [("https://example.com/dish.jpg", 800, 600)]
    r_img = MagicMock(status_code=200, content=fake_img)
    mock_get.return_value = r_img

    mock_client = MagicMock()
    mock_client.is_configured.return_value = True
    # VLM rejects as raw dough
    mock_client.evaluate_food_image.return_value = {"valid": False, "score": 3, "reason": "Uncooked raw dough"}

    result = search_food_image("Pepperoni Pizza", client=mock_client)
    assert result is None
    mock_client.evaluate_food_image.assert_called_once_with(fake_img, "Pepperoni Pizza")


@patch("bsdm.web_image.search_bing")
@patch("bsdm.web_image.search_unsplash")
@patch("requests.Session.get")
def test_search_food_image_falls_back_to_duckduckgo(mock_get, mock_unsplash, mock_bing):
    fake_img = _make_fake_image(width=800, height=600)
    mock_bing.return_value = []
    mock_unsplash.return_value = []

    # DDG token
    r_ddg_token = MagicMock(status_code=200, text='vqd="12345"')
    # DDG search
    r_ddg_search = MagicMock(status_code=200)
    r_ddg_search.json.return_value = {
        "results": [{"image": "https://example.com/ddg.jpg", "width": 800, "height": 600}]
    }
    # Image download
    r_img = MagicMock(status_code=200, content=fake_img)

    mock_get.side_effect = [r_ddg_token, r_ddg_search, r_img]

    result = search_food_image("Unusual Stanford Specialty", require_vlm=False)
    assert result == fake_img


@patch("bsdm.web_image.search_bing")
@patch("bsdm.web_image.search_unsplash")
@patch("requests.Session.get")
def test_search_food_image_skips_bad_geometry(mock_get, mock_unsplash, mock_bing):
    fake_img_good = _make_fake_image(width=800, height=600)
    mock_bing.return_value = []
    # Candidate 1: 500x1200 (tall vertical portrait), Candidate 2: 800x600 (safe)
    mock_unsplash.return_value = [
        ("https://example.com/tall.jpg", 500, 1200),
        ("https://example.com/good.jpg", 800, 600),
    ]
    r_good_img = MagicMock(status_code=200, content=fake_img_good)
    mock_get.return_value = r_good_img

    result = search_food_image("Pasta", require_vlm=False)
    assert result == fake_img_good


def test_search_google_custom_search_success():
    session = MagicMock()
    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = {
        "items": [
            {
                "title": "Delicious Salmon",
                "link": "https://example.com/salmon.jpg",
                "image": {"width": 1200, "height": 800},
            },
            {
                "title": "Raw Salmon Diagram",
                "link": "https://example.com/salmon_anatomy_diagram.jpg",
                "image": {"width": 600, "height": 400},
            },
        ]
    }
    session.get.return_value = mock_resp

    results = search_google_custom_search("Cilantro Lime Salmon", session, "fake_key", "fake_cx")
    assert len(results) == 1
    assert results[0] == ("https://example.com/salmon.jpg", 1200, 800)


def test_search_google_custom_search_error():
    session = MagicMock()
    mock_resp = MagicMock(status_code=403)
    mock_resp.raise_for_status.side_effect = requests.HTTPError("403 Forbidden")
    session.get.return_value = mock_resp

    results = search_google_custom_search("Cilantro Lime Salmon", session, "fake_key", "fake_cx")
    assert results == []


@patch("bsdm.web_image.search_google_custom_search")
@patch("requests.Session.get")
def test_search_food_image_prioritizes_google(mock_get, mock_google, monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setenv("GOOGLE_CSE_ID", "test-cx")

    fake_img = _make_fake_image(width=800, height=600)
    mock_google.return_value = [("https://example.com/google_salmon.jpg", 800, 600)]
    r_img = MagicMock(status_code=200, content=fake_img)
    mock_get.return_value = r_img

    result = search_food_image("Cilantro Lime Salmon", require_vlm=False)
    assert result == fake_img
    mock_google.assert_called_once()


def test_search_bing_success():
    session = MagicMock()
    mock_resp = MagicMock(status_code=200)
    mock_resp.text = """
    <div class="iusc" m="{&quot;murl&quot;:&quot;https://example.com/bing_dish.jpg&quot;,&quot;t&quot;:&quot;Salmon Dish&quot;}"></div>
    <div class="iusc" m="{&quot;murl&quot;:&quot;https://example.com/salmon_anatomy_diagram.jpg&quot;,&quot;t&quot;:&quot;Diagram&quot;}"></div>
    """
    session.get.return_value = mock_resp

    results = search_bing("Cilantro Lime Salmon", session)
    assert len(results) == 1
    assert results[0][0] == "https://example.com/bing_dish.jpg"


def test_search_bing_error():
    session = MagicMock()
    mock_resp = MagicMock(status_code=500)
    mock_resp.raise_for_status.side_effect = requests.HTTPError("500 Server Error")
    session.get.return_value = mock_resp

    results = search_bing("Cilantro Lime Salmon", session)
    assert results == []


@patch("bsdm.web_image.search_bing")
@patch("requests.Session.get")
def test_search_food_image_uses_bing_by_default(mock_get, mock_bing):
    fake_img = _make_fake_image(width=800, height=600)
    mock_bing.return_value = [("https://example.com/bing_salmon.jpg", 800, 600)]
    r_img = MagicMock(status_code=200, content=fake_img)
    mock_get.return_value = r_img

    result = search_food_image("Cilantro Lime Salmon", require_vlm=False)
    assert result == fake_img
    mock_bing.assert_called_once()



@patch("bsdm.web_image.search_bing")
@patch("requests.Session.get")
def test_search_food_image_without_client_and_require_vlm_returns_none(mock_get, mock_bing):
    fake_img = _make_fake_image(width=800, height=600)
    mock_bing.return_value = [("https://example.com/bing_dish.jpg", 800, 600)]
    mock_get.return_value = MagicMock(status_code=200, content=fake_img)

    result = search_food_image("Basmati Rice", client=None, require_vlm=True)
    assert result is None

@patch("bsdm.web_image.search_bing")
@patch("requests.Session.get")
def test_search_food_image_with_require_vlm_false_returns_candidate(mock_get, mock_bing):
    fake_img = _make_fake_image(width=800, height=600)
    mock_bing.return_value = [("https://example.com/bing_dish.jpg", 800, 600)]
    mock_get.return_value = MagicMock(status_code=200, content=fake_img)

    result = search_food_image("Basmati Rice", client=None, require_vlm=False)
    assert result == fake_img
