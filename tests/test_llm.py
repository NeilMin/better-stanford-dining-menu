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
