import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bsdm.cloudflare import CloudflareError, CloudflareQuotaError
from scripts.translate import SYSTEM, RULES, ask_cloudflare, main


def test_ask_cloudflare_translates():
    mock_client = MagicMock()
    mock_client.translate.return_value = {"Fried Rice": "炒饭"}

    res = ask_cloudflare(["Fried Rice"], "dishes", mock_client)
    assert res == {"Fried Rice": "炒饭"}
    mock_client.translate.assert_called_once_with(
        ["Fried Rice"], "dishes", SYSTEM, RULES["dishes"]
    )


def test_ask_cloudflare_different_section():
    mock_client = MagicMock()
    mock_client.translate.return_value = {"Kosher Kitchen": "犹太洁食厨房"}

    res = ask_cloudflare(["Kosher Kitchen"], "halls", mock_client)
    assert res == {"Kosher Kitchen": "犹太洁食厨房"}
    mock_client.translate.assert_called_once_with(
        ["Kosher Kitchen"], "halls", SYSTEM, RULES["halls"]
    )


def test_ask_cloudflare_propagates_quota_error():
    mock_client = MagicMock()
    mock_client.translate.side_effect = CloudflareQuotaError("Rate limit exceeded")

    with pytest.raises(CloudflareQuotaError, match="Rate limit exceeded"):
        ask_cloudflare(["Fried Rice"], "dishes", mock_client)


def test_ask_cloudflare_propagates_cloudflare_error():
    mock_client = MagicMock()
    mock_client.translate.side_effect = CloudflareError("API down")

    with pytest.raises(CloudflareError, match="API down"):
        ask_cloudflare(["Fried Rice"], "dishes", mock_client)


@pytest.fixture
def mock_zh_project(tmp_path):
    root = tmp_path / "project"
    root.mkdir(parents=True)
    data_dir = root / "data"
    data_dir.mkdir()
    config_dir = root / "config"
    config_dir.mkdir()

    # Create dummy zh.json and wanted items
    (data_dir / "zh.json").write_text(
        json.dumps({"version": 1, "dishes": {}, "terms": {}, "halls": {}, "specials": {}})
    )
    # Write a dummy dish catalog with dishes to translate
    (data_dir / "dishes.json").write_text(
        json.dumps({
            "d1": {"name": "Fried Rice"},
            "d2": {"name": "Spring Rolls"},
        })
    )
    # Write empty halls.json and specials.json
    (config_dir / "halls.json").write_text(json.dumps({"halls": []}))
    (data_dir / "specials.json").write_text(json.dumps({"calendars": []}))
    return root


def test_main_backend_auto_uses_cloudflare_when_configured(mock_zh_project, monkeypatch):
    monkeypatch.setattr("scripts.translate.ROOT", mock_zh_project)

    mock_client = MagicMock()
    mock_client.is_configured.return_value = True
    monkeypatch.setattr("scripts.translate.CloudflareClient", lambda: mock_client)

    mock_ask_cf = MagicMock(return_value={"Fried Rice": "炒饭", "Spring Rolls": "春卷"})
    monkeypatch.setattr("scripts.translate.ask_cloudflare", mock_ask_cf)

    mock_ask_claude = MagicMock()
    monkeypatch.setattr("scripts.translate.ask", mock_ask_claude)

    code = main(["--backend", "auto", "--section", "dishes"])
    assert code == 0
    assert mock_ask_cf.called
    assert not mock_ask_claude.called


def test_main_backend_auto_falls_back_to_claude_when_not_configured(mock_zh_project, monkeypatch):
    monkeypatch.setattr("scripts.translate.ROOT", mock_zh_project)

    mock_client = MagicMock()
    mock_client.is_configured.return_value = False
    monkeypatch.setattr("scripts.translate.CloudflareClient", lambda: mock_client)

    mock_ask_cf = MagicMock()
    monkeypatch.setattr("scripts.translate.ask_cloudflare", mock_ask_cf)

    mock_ask_claude = MagicMock(return_value={"Fried Rice": "炒饭", "Spring Rolls": "春卷"})
    monkeypatch.setattr("scripts.translate.ask", mock_ask_claude)

    code = main(["--backend", "auto", "--section", "dishes"])
    assert code == 0
    assert not mock_ask_cf.called
    assert mock_ask_claude.called


def test_main_backend_explicit_cloudflare_unconfigured_exits_error(mock_zh_project, monkeypatch, capsys):
    monkeypatch.setattr("scripts.translate.ROOT", mock_zh_project)

    mock_client = MagicMock()
    mock_client.is_configured.return_value = False
    monkeypatch.setattr("scripts.translate.CloudflareClient", lambda: mock_client)

    code = main(["--backend", "cloudflare", "--section", "dishes"])
    assert code != 0
    err = capsys.readouterr().err
    assert "CF_ACCOUNT_ID" in err or "Cloudflare" in err


def test_main_backend_explicit_claude_ignores_cf_config(mock_zh_project, monkeypatch):
    monkeypatch.setattr("scripts.translate.ROOT", mock_zh_project)

    mock_client = MagicMock()
    mock_client.is_configured.return_value = True
    monkeypatch.setattr("scripts.translate.CloudflareClient", lambda: mock_client)

    mock_ask_cf = MagicMock()
    monkeypatch.setattr("scripts.translate.ask_cloudflare", mock_ask_cf)

    mock_ask_claude = MagicMock(return_value={"Fried Rice": "炒饭", "Spring Rolls": "春卷"})
    monkeypatch.setattr("scripts.translate.ask", mock_ask_claude)

    code = main(["--backend", "claude", "--section", "dishes"])
    assert code == 0
    assert not mock_ask_cf.called
    assert mock_ask_claude.called


def test_main_handles_quota_error_gracefully(mock_zh_project, monkeypatch, capsys):
    monkeypatch.setattr("scripts.translate.ROOT", mock_zh_project)

    mock_client = MagicMock()
    mock_client.is_configured.return_value = True
    monkeypatch.setattr("scripts.translate.CloudflareClient", lambda: mock_client)

    call_count = 0

    def fake_ask_cf(items, section, client):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {items[0]: "已翻译"}
        raise CloudflareQuotaError("Daily rate limit exceeded (429)")

    monkeypatch.setattr("scripts.translate.ask_cloudflare", fake_ask_cf)

    # Use batch size 1 and jobs 1 so batches run sequentially
    code = main(["--backend", "cloudflare", "--section", "dishes", "--batch", "1", "--jobs", "1"])
    assert code == 0  # Exits cleanly on quota error

    err = capsys.readouterr().err
    assert "quota exceeded" in err

    # Verify first batch was persisted in zh.json
    zh_content = json.loads((mock_zh_project / "data" / "zh.json").read_text())
    assert len(zh_content["dishes"]) == 1


def test_main_dry_run(mock_zh_project, monkeypatch, capsys):
    monkeypatch.setattr("scripts.translate.ROOT", mock_zh_project)

    mock_client = MagicMock()
    mock_client.is_configured.return_value = True
    monkeypatch.setattr("scripts.translate.CloudflareClient", lambda: mock_client)

    code = main(["--dry-run", "--section", "dishes"])
    assert code == 0
    out = capsys.readouterr().out
    assert "dishes:" in out
    assert "Fried Rice" in out
