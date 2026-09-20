import base64
import io
import json
from unittest.mock import MagicMock, patch

import pytest
import requests
from PIL import Image

from bsdm.cloudflare import (
    CloudflareClient,
    CloudflareError,
    CloudflareQuotaError,
    DEFAULT_IMAGE_MODEL,
    DEFAULT_TRANSLATION_MODEL,
)


def test_is_configured(monkeypatch):
    monkeypatch.delenv("CF_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("CF_API_TOKEN", raising=False)

    client = CloudflareClient(account_id="acc123", api_token="tok456")
    assert client.is_configured() is True

    unconfigured = CloudflareClient(account_id="", api_token="")
    assert unconfigured.is_configured() is False

    # Check environment variable fallback
    monkeypatch.setenv("CF_ACCOUNT_ID", "env_acc")
    monkeypatch.setenv("CF_API_TOKEN", "env_tok")
    env_client = CloudflareClient()
    assert env_client.is_configured() is True
    assert env_client.account_id == "env_acc"
    assert env_client.api_token == "env_tok"


def test_unconfigured_call_raises_error():
    client = CloudflareClient(account_id="", api_token="")
    with pytest.raises(CloudflareError, match="account_id and api_token are required"):
        client.translate(["Chicken"], section="dishes", system_prompt="Sys", rules="Rules")

    with pytest.raises(CloudflareError, match="account_id and api_token are required"):
        client.generate_image("A bowl of soup")


@patch("requests.Session.post")
def test_translate_success(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "success": True,
        "result": {
            "response": json.dumps({"Chicken Thigh": "鸡腿", "Tofu": "豆腐"})
        },
    }
    mock_post.return_value = mock_resp

    client = CloudflareClient(account_id="acc123", api_token="tok456")
    res = client.translate(["Chicken Thigh", "Tofu"], section="dishes", system_prompt="Sys", rules="Rules")
    assert res == {"Chicken Thigh": "鸡腿", "Tofu": "豆腐"}


@patch("requests.Session.post")
def test_translate_dict_response_success(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "success": True,
        "result": {
            "response": {"Chicken Thigh": "鸡腿", "Tofu": "豆腐"}
        },
    }
    mock_post.return_value = mock_resp

    client = CloudflareClient(account_id="acc123", api_token="tok456")
    res = client.translate(["Chicken Thigh", "Tofu"], section="dishes", system_prompt="Sys", rules="Rules")
    assert res == {"Chicken Thigh": "鸡腿", "Tofu": "豆腐"}

    # Verify endpoint and headers
    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert f"https://api.cloudflare.com/client/v4/accounts/acc123/ai/run/{DEFAULT_TRANSLATION_MODEL}" in args[0]
    assert kwargs["json"]["messages"][0]["content"] == "Sys"
    assert client.session.headers.get("Authorization") == "Bearer tok456"


@patch("requests.Session.post")
def test_translate_markdown_fenced_json(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    fenced_output = "```json\n" + json.dumps({"Chicken Thigh": "鸡腿"}) + "\n```"
    mock_resp.json.return_value = {
        "success": True,
        "result": {"response": fenced_output},
    }
    mock_post.return_value = mock_resp

    client = CloudflareClient(account_id="acc123", api_token="tok456")
    res = client.translate(["Chicken Thigh"], section="dishes", system_prompt="Sys", rules="Rules")
    assert res == {"Chicken Thigh": "鸡腿"}


@patch("requests.Session.post")
def test_translate_case_insensitive_matching(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    # Model returns lowercase key
    mock_resp.json.return_value = {
        "success": True,
        "result": {"response": json.dumps({"chicken thigh": "鸡腿"})},
    }
    mock_post.return_value = mock_resp

    client = CloudflareClient(account_id="acc123", api_token="tok456")
    res = client.translate(["Chicken Thigh"], section="dishes", system_prompt="Sys", rules="Rules")
    assert res == {"Chicken Thigh": "鸡腿"}


@patch("requests.Session.post")
def test_translate_quota_exceeded(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 429
    mock_resp.text = "Daily quota exceeded"
    mock_post.return_value = mock_resp

    client = CloudflareClient(account_id="acc123", api_token="tok456")
    with pytest.raises(CloudflareQuotaError, match="quota exceeded"):
        client.translate(["Chicken"], section="dishes", system_prompt="Sys", rules="Rules")


@patch("requests.Session.post")
def test_translate_empty_response(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"success": True, "result": {"response": ""}}
    mock_post.return_value = mock_resp

    client = CloudflareClient(account_id="acc123", api_token="tok456")
    with pytest.raises(CloudflareError, match="Empty response"):
        client.translate(["Chicken"], section="dishes", system_prompt="Sys", rules="Rules")


@patch("requests.Session.post")
def test_translate_malformed_json(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"success": True, "result": {"response": "Not valid json {"}}
    mock_post.return_value = mock_resp

    client = CloudflareClient(account_id="acc123", api_token="tok456")
    with pytest.raises(CloudflareError, match="Malformed translation JSON"):
        client.translate(["Chicken"], section="dishes", system_prompt="Sys", rules="Rules")


@patch("requests.Session.post")
def test_translate_not_a_dict(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"success": True, "result": {"response": '["chicken", "tofu"]'}}
    mock_post.return_value = mock_resp

    client = CloudflareClient(account_id="acc123", api_token="tok456")
    with pytest.raises(CloudflareError, match="Expected dict"):
        client.translate(["Chicken"], section="dishes", system_prompt="Sys", rules="Rules")


@patch("requests.Session.post")
def test_generate_image_binary_success(mock_post):
    buf = io.BytesIO()
    Image.new("RGB", (64, 36), color="red").save(buf, format="PNG")
    png_bytes = buf.getvalue()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Type": "image/png"}
    mock_resp.content = png_bytes
    mock_post.return_value = mock_resp

    client = CloudflareClient(account_id="acc123", api_token="tok456")
    img_data = client.generate_image("A bowl of ramen", negative_prompt="blurry", num_steps=8)
    assert img_data == png_bytes

    args, kwargs = mock_post.call_args
    assert f"https://api.cloudflare.com/client/v4/accounts/acc123/ai/run/{DEFAULT_IMAGE_MODEL}" in args[0]
    assert kwargs["json"]["prompt"] == "A bowl of ramen"
    assert kwargs["json"]["negative_prompt"] == "blurry"
    assert kwargs["json"]["num_steps"] == 8
    assert kwargs["json"]["width"] == 1024
    assert kwargs["json"]["height"] == 576


@patch("requests.Session.post")
def test_generate_image_base64_json_success(mock_post):
    raw_bytes = b"fake-jpeg-data"
    b64_str = base64.b64encode(raw_bytes).decode("ascii")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Type": "application/json"}
    mock_resp.json.return_value = {"result": {"image": b64_str}}
    mock_resp.content = b'{"result": ...}'
    mock_post.return_value = mock_resp

    client = CloudflareClient(account_id="acc123", api_token="tok456")
    img_data = client.generate_image("A bowl of ramen")
    assert img_data == raw_bytes


@patch("requests.Session.post")
def test_generate_image_quota_exceeded(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 429
    mock_resp.text = "Rate limit reached"
    mock_post.return_value = mock_resp

    client = CloudflareClient(account_id="acc123", api_token="tok456")
    with pytest.raises(CloudflareQuotaError, match="quota exceeded"):
        client.generate_image("A bowl of ramen")


@patch("requests.Session.post")
def test_http_error(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.text = "Internal Server Error"
    mock_post.return_value = mock_resp

    client = CloudflareClient(account_id="acc123", api_token="tok456")
    with pytest.raises(CloudflareError, match="Cloudflare error 500"):
        client.generate_image("A bowl of ramen")


@patch("requests.Session.post")
def test_network_request_exception(mock_post):
    mock_post.side_effect = requests.RequestException("Connection timed out")

    client = CloudflareClient(account_id="acc123", api_token="tok456")
    with pytest.raises(CloudflareError, match="Cloudflare request failed"):
        client.generate_image("A bowl of ramen")
