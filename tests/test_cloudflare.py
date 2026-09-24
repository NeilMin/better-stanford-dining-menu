import base64
import io
import json
import os
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
    img_data = client.generate_image("A bowl of ramen", negative_prompt="blurry", num_steps=8, model="@cf/bytedance/stable-diffusion-xl-lightning")
    assert img_data == png_bytes

    args, kwargs = mock_post.call_args
    assert "https://api.cloudflare.com/client/v4/accounts/acc123/ai/run/@cf/bytedance/stable-diffusion-xl-lightning" in args[0]
    assert kwargs["json"]["prompt"] == "A bowl of ramen"
    assert kwargs["json"]["negative_prompt"] == "blurry"
    assert kwargs["json"]["num_steps"] == 8
    assert kwargs["json"]["width"] == 1024
    assert kwargs["json"]["height"] == 576


@patch("requests.Session.post")
def test_generate_image_flux_payload(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Type": "image/png"}
    mock_resp.content = b"fake-flux-png"
    mock_post.return_value = mock_resp

    client = CloudflareClient(account_id="acc123", api_token="tok456")
    img_data = client.generate_image("A bowl of ramen", model="@cf/black-forest-labs/flux-1-schnell", num_steps=6)
    assert img_data == b"fake-flux-png"

    args, kwargs = mock_post.call_args
    assert "@cf/black-forest-labs/flux-1-schnell" in args[0]
    assert kwargs["json"] == {"prompt": "A bowl of ramen", "steps": 6}


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


@patch("requests.Session.post")
def test_evaluate_image_success(mock_post):
    buf = io.BytesIO()
    Image.new("RGB", (100, 100), color="blue").save(buf, format="JPEG")
    fake_img = buf.getvalue()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "result": {
            "response": '{"valid": true, "score": 9, "reason": "Freshly baked pizza"}'
        }
    }
    mock_post.return_value = mock_resp

    client = CloudflareClient(account_id="acc123", api_token="tok456")
    eval_res = client.evaluate_image(fake_img, "Pizza")
    assert eval_res["valid"] is True
    assert eval_res["score"] == 9
    assert eval_res["reason"] == "Freshly baked pizza"

    args, kwargs = mock_post.call_args
    assert "@cf/meta/llama-3.2-11b-vision-instruct" in args[0]
    prompt_text = kwargs["json"]["prompt"]
    assert "Pizza" in prompt_text
    assert "CATEGORY MISMATCH" in prompt_text
    assert "THALI / BANQUET" in prompt_text
    assert "PROTEIN MISMATCH" in prompt_text
    assert isinstance(kwargs["json"]["image"], list)


@patch("requests.Session.post")
def test_evaluate_image_failure_fallback(mock_post):
    client = CloudflareClient(account_id="acc123", api_token="tok456")
    # Invalid image bytes
    res = client.evaluate_image(b"not-an-image", "Pizza")
    assert res == {"valid": False, "score": 0, "reason": "Invalid image bytes"}

    # Mock server error
    buf = io.BytesIO()
    Image.new("RGB", (64, 64)).save(buf, format="JPEG")
    mock_post.side_effect = requests.RequestException("Timeout")
    res_err = client.evaluate_image(buf.getvalue(), "Pizza")
    assert res_err == {"valid": False, "score": 0, "reason": "Evaluation failed"}


def test_compile_dish_prompt_parses_json():
    client = CloudflareClient("acc123", "tok456")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "result": {
            "response": json.dumps({
                "prompt": "Juicy beef hot dog in a soft bun",
                "negative": "yellow sludge, plastic",
            })
        }
    }
    client.session.post = MagicMock(return_value=mock_resp)

    res = client.compile_dish_prompt(
        name="Beef Hot Dog",
        ingredients="beef, sorbitol, sodium lactate",
        tags=["halal"],
        category="beef",
    )
    assert res["prompt"] == "Juicy beef hot dog in a soft bun"
    assert "yellow sludge" in res["negative"]


def test_compile_dish_prompt_dict_response():
    client = CloudflareClient("acc123", "tok456")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "result": {
            "response": {
                "prompt": "Crisp chicken fajita bowl",
                "negative": "burrito, wrap",
            }
        }
    }
    client.session.post = MagicMock(return_value=mock_resp)

    res = client.compile_dish_prompt(
        name="Chicken Fajitas",
        ingredients="chicken breast, bell peppers, onions",
        tags=["gluten-free"],
        category="poultry",
    )
    assert res["prompt"] == "Crisp chicken fajita bowl"
    assert res["negative"] == "burrito, wrap"


def test_compile_dish_prompt_markdown_fenced():
    client = CloudflareClient("acc123", "tok456")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "result": {
            "response": "```json\n" + json.dumps({
                "prompt": "Lemon Herb Rice",
                "negative": "burnt, noodles",
            }) + "\n```"
        }
    }
    client.session.post = MagicMock(return_value=mock_resp)

    res = client.compile_dish_prompt(
        name="Lemon Herb Rice",
        ingredients="rice, lemon juice, parsley",
    )
    assert res["prompt"] == "Lemon Herb Rice"
    assert res["negative"] == "burnt, noodles"


def test_compile_dish_prompt_invalid_response_raises():
    client = CloudflareClient("acc123", "tok456")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "result": {
            "response": "Not a json response without prompt key"
        }
    }
    client.session.post = MagicMock(return_value=mock_resp)

    with pytest.raises(CloudflareError, match="Failed to compile prompt"):
        client.compile_dish_prompt(
            name="Mystery Soup",
            ingredients="water, salt",
        )


def test_evaluate_food_image_parses_score():
    client = CloudflareClient("acc123", "tok456")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "result": {
            "response": '{"valid": true, "score": 9, "reason": "Appetizing plating and crisp focus"}'
        }
    }
    client.session.post = MagicMock(return_value=mock_resp)

    # Fake 10x10 PNG bytes
    buf = io.BytesIO()
    Image.new("RGB", (10, 10), "white").save(buf, format="JPEG")
    res = client.evaluate_food_image(buf.getvalue(), dish_name="Beef Hot Dog")
    assert res["valid"] is True
    assert res["score"] == 9
    assert "Appetizing" in res["reason"]


def test_dotenv_fallback(monkeypatch, tmp_path):
    from bsdm.cloudflare import _load_dotenv

    monkeypatch.delenv("CF_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("CF_API_TOKEN", raising=False)

    fake_env = tmp_path / ".env"
    fake_env.write_text('CF_ACCOUNT_ID="env_from_file_id"\nCF_API_TOKEN="env_from_file_tok"\n')

    _load_dotenv(env_path=fake_env)
    assert os.getenv("CF_ACCOUNT_ID") == "env_from_file_id"
    assert os.getenv("CF_API_TOKEN") == "env_from_file_tok"

    client = CloudflareClient()
    assert client.is_configured() is True
    assert client.account_id == "env_from_file_id"
    assert client.api_token == "env_from_file_tok"


