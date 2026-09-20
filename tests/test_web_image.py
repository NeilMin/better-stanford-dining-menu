from __future__ import annotations

import io
from unittest.mock import MagicMock, patch
from PIL import Image
import pytest
import requests

from bsdm.web_image import search_food_image


def _make_fake_image(width: int = 200, height: int = 150, color: str = "blue") -> bytes:
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


@patch("requests.Session.get")
def test_search_food_image_success(mock_get):
    fake_img = _make_fake_image()
    assert len(fake_img) > 2048

    # Call 1: vqd token lookup; Call 2: search json; Call 3: image download
    r1 = MagicMock(status_code=200, text='vqd="4-12345"')
    r2 = MagicMock(status_code=200)
    r2.json.return_value = {"results": [{"image": "https://example.com/dish.jpg"}]}
    r3 = MagicMock(status_code=200, content=fake_img, headers={"Content-Type": "image/jpeg"})

    mock_get.side_effect = [r1, r2, r3]

    result = search_food_image("Chicken Teriyaki")
    assert result == fake_img


@patch("requests.Session.get")
def test_search_food_image_unquoted_vqd(mock_get):
    fake_img = _make_fake_image()

    # Unquoted vqd token pattern in HTML
    r1 = MagicMock(status_code=200, text='href="/?q=test&vqd=4-98765-123&other=1"')
    r2 = MagicMock(status_code=200)
    r2.json.return_value = {"results": [{"image": "https://example.com/dish.jpg"}]}
    r3 = MagicMock(status_code=200, content=fake_img)

    mock_get.side_effect = [r1, r2, r3]

    result = search_food_image("Beef Bulgogi")
    assert result == fake_img


@patch("requests.Session.get")
def test_search_food_image_no_results(mock_get):
    r1 = MagicMock(status_code=200, text='vqd="4-12345"')
    r2 = MagicMock(status_code=200)
    r2.json.return_value = {"results": []}

    mock_get.side_effect = [r1, r2]

    result = search_food_image("Super Rare Unheard Dish")
    assert result is None


@patch("requests.Session.get")
def test_search_food_image_token_request_fails(mock_get):
    mock_get.side_effect = requests.RequestException("Network error on token fetch")

    result = search_food_image("Chicken Teriyaki")
    assert result is None


@patch("requests.Session.get")
def test_search_food_image_no_token_in_html(mock_get):
    r1 = MagicMock(status_code=200, text="<html><body>No token here</body></html>")
    mock_get.side_effect = [r1]

    result = search_food_image("Chicken Teriyaki")
    assert result is None


@patch("requests.Session.get")
def test_search_food_image_search_endpoint_fails(mock_get):
    r1 = MagicMock(status_code=200, text='vqd="4-12345"')
    mock_get.side_effect = [r1, requests.RequestException("Search failed")]

    result = search_food_image("Chicken Teriyaki")
    assert result is None


@patch("requests.Session.get")
def test_search_food_image_search_invalid_json(mock_get):
    r1 = MagicMock(status_code=200, text='vqd="4-12345"')
    r2 = MagicMock(status_code=200)
    r2.json.side_effect = ValueError("Invalid JSON response")
    mock_get.side_effect = [r1, r2]

    result = search_food_image("Chicken Teriyaki")
    assert result is None


@patch("requests.Session.get")
def test_search_food_image_skips_invalid_candidates(mock_get):
    fake_img = _make_fake_image()

    r1 = MagicMock(status_code=200, text='vqd="4-12345"')
    r2 = MagicMock(status_code=200)
    r2.json.return_value = {
        "results": [
            {"image": "https://example.com/too_small.jpg"},
            {"image": "https://example.com/corrupt.jpg"},
            {"image": "https://example.com/good.jpg"},
        ]
    }
    # Candidate 1: too small (<= 2048 bytes)
    r_small = MagicMock(status_code=200, content=b"tiny payload")
    # Candidate 2: corrupt image (>= 2048 bytes but not valid image)
    r_corrupt = MagicMock(status_code=200, content=b"corrupt-data" * 200)
    # Candidate 3: good image
    r_good = MagicMock(status_code=200, content=fake_img)

    mock_get.side_effect = [r1, r2, r_small, r_corrupt, r_good]

    result = search_food_image("Pasta Primavera")
    assert result == fake_img


@patch("requests.Session.get")
def test_search_food_image_skips_empty_url(mock_get):
    fake_img = _make_fake_image()

    r1 = MagicMock(status_code=200, text='vqd="4-12345"')
    r2 = MagicMock(status_code=200)
    r2.json.return_value = {
        "results": [
            {"image": ""},
            {"image": "https://example.com/good.jpg"},
        ]
    }
    r_good = MagicMock(status_code=200, content=fake_img)

    mock_get.side_effect = [r1, r2, r_good]

    result = search_food_image("Pasta Primavera")
    assert result == fake_img


@patch("requests.Session.get")
def test_search_food_image_all_candidates_fail(mock_get):
    r1 = MagicMock(status_code=200, text='vqd="4-12345"')
    r2 = MagicMock(status_code=200)
    r2.json.return_value = {
        "results": [
            {"image": "https://example.com/fail1.jpg"},
            {"image": "https://example.com/fail2.jpg"},
            {"image": "https://example.com/fail3.jpg"},
        ]
    }
    r_fail = MagicMock(status_code=500, content=b"")

    mock_get.side_effect = [r1, r2, r_fail, r_fail, r_fail]

    result = search_food_image("Pasta Primavera")
    assert result is None
