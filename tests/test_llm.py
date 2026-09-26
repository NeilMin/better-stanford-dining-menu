"""The claude CLI wrapper: what it sends, and which failures stop the night."""

from __future__ import annotations

import base64
import io
import json
import subprocess

import pytest
from PIL import Image

from bsdm import llm as llmlib
from bsdm.llm import ClaudeCLI, LLMError, Unavailable, parse_json


def png(size=(1344, 768)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, "orange").save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def cli(monkeypatch):
    """A ClaudeCLI whose subprocess is recorded and answered by `reply`."""
    sent = {}
    reply = {"stdout": "", "stderr": "", "returncode": 0}

    def run(cmd, input=None, **kw):
        sent.update(cmd=cmd, input=input, **kw)
        return subprocess.CompletedProcess(cmd, reply["returncode"], reply["stdout"], reply["stderr"])

    monkeypatch.setattr(llmlib.subprocess, "run", run)
    monkeypatch.setattr(llmlib.shutil, "which", lambda b: f"/usr/bin/{b}")
    return ClaudeCLI(model="sonnet"), sent, reply


def stream(*events) -> str:
    return "\n".join(json.dumps(e) for e in events) + "\n"


def test_the_answer_is_the_result_event(cli):
    client, _sent, reply = cli
    reply["stdout"] = stream({"type": "system"}, {"type": "assistant"},
                             {"type": "result", "result": '{"ok": 1}', "is_error": False})
    assert client.ask("hello") == '{"ok": 1}'


def test_an_image_travels_inline_as_a_jpeg_no_larger_than_the_judge_needs(cli):
    client, sent, reply = cli
    reply["stdout"] = stream({"type": "result", "result": "fine"})
    client.ask("what is this?", images=[png()], system="be brief")

    message = json.loads(sent["input"])["message"]
    image, text = message["content"]
    assert text == {"type": "text", "text": "what is this?"}
    assert image["source"]["media_type"] == "image/jpeg"
    with Image.open(io.BytesIO(base64.b64decode(image["source"]["data"]))) as im:
        assert max(im.size) <= 768
    assert "--system-prompt" in sent["cmd"] and "be brief" in sent["cmd"]


def test_it_runs_outside_the_repo_with_no_tools_that_run_code(cli):
    """Like translate.py: the project's context is not wanted, and would be paid for."""
    client, sent, reply = cli
    reply["stdout"] = stream({"type": "result", "result": "fine"})
    client.ask("x")
    assert "--restricted" in sent["cmd"]
    assert "--strict-mcp-config" in sent["cmd"]
    assert "better-stanford-dining-menu" not in str(sent["cwd"])


def test_a_spent_subscription_is_unavailable_not_an_error(cli):
    client, _sent, reply = cli
    reply["stdout"] = stream({"type": "result", "is_error": True,
                              "result": "Claude AI usage limit reached|1760000000"})
    with pytest.raises(Unavailable):
        client.ask("x")


def test_not_being_logged_in_is_unavailable(cli):
    client, _sent, reply = cli
    reply.update(returncode=1, stderr="Invalid API key · Please run /login")
    with pytest.raises(Unavailable):
        client.ask("x")


def test_any_other_failure_is_an_error_for_that_call_only(cli):
    client, _sent, reply = cli
    reply.update(returncode=1, stderr="something odd happened")
    with pytest.raises(LLMError) as err:
        client.ask("x")
    assert not isinstance(err.value, Unavailable)


def test_a_missing_binary_is_unavailable(monkeypatch):
    monkeypatch.setattr(llmlib.shutil, "which", lambda b: None)
    client = ClaudeCLI()
    assert not client.available()
    with pytest.raises(Unavailable):
        client.ask("x")


def test_parse_json_tolerates_a_fence_and_a_preamble():
    assert parse_json('Here you go:\n```json\n{"a": [1, 2]}\n```') == {"a": [1, 2]}
    with pytest.raises(LLMError):
        parse_json("no json here")
    with pytest.raises(LLMError):
        parse_json("[1, 2]")


class FakeSession:
    """Answers Gemini posts from a queue of (status, body) and records them."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.posts = []

    def post(self, url, json=None, timeout=None, headers=None):
        self.posts.append({"url": url, "json": json, "headers": headers})
        status, body = self.replies.pop(0)
        resp = type("R", (), {})()
        resp.status_code, resp.text = status, str(body)
        resp.json = lambda: body
        return resp


def answer(text):
    return (200, {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}]})


def quota(delay=None):
    details = [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay}] if delay else []
    return (429, {"error": {"code": 429, "details": details}})


def test_gemini_sends_the_picture_inline_and_the_key_in_a_header():
    session = FakeSession(answer('{"ok": true}'))
    g = llmlib.Gemini(model="gemini-test", key="secret", session=session)
    assert g.ask("what is this?", images=[png()], system="be brief") == '{"ok": true}'

    post = session.posts[0]
    assert "gemini-test:generateContent" in post["url"] and "secret" not in post["url"]
    assert post["headers"] == {"x-goog-api-key": "secret"}
    image, text = post["json"]["contents"][0]["parts"]
    assert image["inline_data"]["mime_type"] == "image/jpeg"
    assert text == {"text": "what is this?"}
    assert post["json"]["systemInstruction"] == {"parts": [{"text": "be brief"}]}
    assert post["json"]["generationConfig"]["responseMimeType"] == "application/json"


def test_gemini_waits_out_a_per_minute_limit(monkeypatch):
    slept = []
    monkeypatch.setattr(llmlib.time, "sleep", slept.append)
    session = FakeSession(quota("12s"), answer("fine"))
    assert llmlib.Gemini(key="k", session=session).ask("x") == "fine"
    assert slept == [13.0]


def test_gemini_out_of_daily_quota_is_unavailable(monkeypatch):
    monkeypatch.setattr(llmlib.time, "sleep", lambda s: None)
    with pytest.raises(Unavailable):
        llmlib.Gemini(key="k", session=FakeSession(quota())).ask("x")
    with pytest.raises(Unavailable):
        llmlib.Gemini(key="k", session=FakeSession(quota("3600s"))).ask("x")


def test_gemini_with_a_bad_key_or_none_is_unavailable():
    with pytest.raises(Unavailable):
        llmlib.Gemini(key="k", session=FakeSession((403, {"error": "denied"}))).ask("x")
    g = llmlib.Gemini(key="", session=FakeSession())
    assert not g.available()
    with pytest.raises(Unavailable):
        g.ask("x")


def test_gemini_with_nothing_to_say_is_an_error_for_that_call():
    blocked = (200, {"candidates": [], "promptFeedback": {"blockReason": "OTHER"}})
    with pytest.raises(LLMError) as err:
        llmlib.Gemini(key="k", session=FakeSession(blocked)).ask("x")
    assert not isinstance(err.value, Unavailable)


def test_auto_prefers_the_claude_cli_then_gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(llmlib.shutil, "which", lambda b: "/usr/bin/claude")
    assert isinstance(llmlib.pick("auto"), ClaudeCLI)
    monkeypatch.setattr(llmlib.shutil, "which", lambda b: None)
    assert isinstance(llmlib.pick("auto"), llmlib.Gemini)
    monkeypatch.delenv("GEMINI_API_KEY")
    assert isinstance(llmlib.pick("auto"), ClaudeCLI), "with neither, report the CLI as missing"


def test_gemini_retries_an_overload_then_gives_up_for_the_night(monkeypatch):
    slept = []
    monkeypatch.setattr(llmlib.time, "sleep", slept.append)
    assert llmlib.Gemini(key="k", session=FakeSession((503, {}), answer("ok"))).ask("x") == "ok"
    with pytest.raises(Unavailable):
        llmlib.Gemini(key="k", session=FakeSession(*[(503, {})] * 4)).ask("x")
    assert slept == [10, 10, 30, 90]


def test_gemini_defaults_to_the_moving_alias():
    """Versions are retired for new keys; the site runs unattended for years."""
    assert llmlib.Gemini(key="k").model.endswith("-latest")
