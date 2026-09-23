from unittest.mock import MagicMock, patch
import json
import pytest

from bsdm.prompt_compiler import COMPILER_REV, compile_pending


def test_compile_pending_updates_entries():
    catalog = {
        "dish1": {
            "name": "Beef Hot Dog",
            "ingredients": "beef, salt, sorbitol",
            "tags": ["halal"],
            "category": "beef",
            "needs_image": True,
            "prompt": "Old heuristic prompt",
            "negative": "Old negative",
        }
    }
    client = MagicMock()
    client.is_configured.return_value = True
    client.compile_dish_prompt.return_value = {
        "prompt": "New compiled hot dog prompt",
        "negative": "New negative exclusions",
    }

    updated = compile_pending(catalog, client, limit=None, force=True)
    assert updated == 1
    assert catalog["dish1"]["prompt"] == "New compiled hot dog prompt"
    assert catalog["dish1"]["negative"] == "New negative exclusions"
    assert catalog["dish1"]["prompt_compiled"] is True
    assert catalog["dish1"]["prompt_compiler_rev"] == COMPILER_REV


def test_compile_pending_skips_without_needs_image():
    catalog = {
        "dish1": {
            "name": "Side Salad",
            "needs_image": False,
            "prompt": "salad prompt",
        }
    }
    client = MagicMock()
    client.is_configured.return_value = True

    updated = compile_pending(catalog, client)
    assert updated == 0
    client.compile_dish_prompt.assert_not_called()


def test_compile_pending_skips_already_compiled():
    catalog = {
        "dish1": {
            "name": "Beef Hot Dog",
            "needs_image": True,
            "prompt_compiled": True,
            "prompt_compiler_rev": COMPILER_REV,
            "prompt": "Existing compiled prompt",
            "negative": "Existing negative",
        }
    }
    client = MagicMock()
    client.is_configured.return_value = True

    updated = compile_pending(catalog, client, force=False)
    assert updated == 0
    client.compile_dish_prompt.assert_not_called()

    # With force=True, it should recompile
    client.compile_dish_prompt.return_value = {
        "prompt": "Recompiled prompt",
        "negative": "Recompiled negative",
    }
    updated_force = compile_pending(catalog, client, force=True)
    assert updated_force == 1
    assert catalog["dish1"]["prompt"] == "Recompiled prompt"


def test_compile_pending_recompiles_older_rev():
    catalog = {
        "dish1": {
            "name": "Beef Hot Dog",
            "needs_image": True,
            "prompt_compiled": True,
            "prompt_compiler_rev": 0,
            "prompt": "Old rev prompt",
        }
    }
    client = MagicMock()
    client.is_configured.return_value = True
    client.compile_dish_prompt.return_value = {
        "prompt": "New rev prompt",
        "negative": "New negative",
    }

    updated = compile_pending(catalog, client, force=False)
    assert updated == 1
    assert catalog["dish1"]["prompt"] == "New rev prompt"
    assert catalog["dish1"]["prompt_compiler_rev"] == COMPILER_REV


def test_compile_pending_only_filter():
    catalog = {
        "dish1": {"name": "Beef Hot Dog", "needs_image": True},
        "dish2": {"name": "Chicken Fajitas", "needs_image": True},
    }
    client = MagicMock()
    client.is_configured.return_value = True
    client.compile_dish_prompt.return_value = {
        "prompt": "P",
        "negative": "N",
    }

    updated = compile_pending(catalog, client, only="fajita")
    assert updated == 1
    assert "prompt" in catalog["dish2"]
    assert "prompt" not in catalog["dish1"]


def test_compile_pending_limit():
    catalog = {
        "dish1": {"name": "Dish 1", "needs_image": True},
        "dish2": {"name": "Dish 2", "needs_image": True},
        "dish3": {"name": "Dish 3", "needs_image": True},
    }
    client = MagicMock()
    client.is_configured.return_value = True
    client.compile_dish_prompt.return_value = {
        "prompt": "P",
        "negative": "N",
    }

    updated = compile_pending(catalog, client, limit=2)
    assert updated == 2
    assert client.compile_dish_prompt.call_count == 2


def test_compile_pending_unconfigured_client():
    catalog = {"dish1": {"name": "Dish 1", "needs_image": True}}
    client = MagicMock()
    client.is_configured.return_value = False

    updated = compile_pending(catalog, client)
    assert updated == 0
    client.compile_dish_prompt.assert_not_called()


def test_compile_pending_handles_exception():
    catalog = {
        "dish1": {"name": "Error Dish", "needs_image": True},
        "dish2": {"name": "Good Dish", "needs_image": True},
    }
    client = MagicMock()
    client.is_configured.return_value = True
    client.compile_dish_prompt.side_effect = [
        RuntimeError("API error"),
        {"prompt": "Good P", "negative": "Good N"},
    ]

    updated = compile_pending(catalog, client)
    assert updated == 1
    assert "prompt" not in catalog["dish1"]
    assert catalog["dish2"]["prompt"] == "Good P"


def test_cli_unconfigured(monkeypatch, capsys):
    from scripts.compile_prompts import main

    with patch("scripts.compile_prompts.CloudflareClient") as MockClient:
        MockClient.return_value.is_configured.return_value = False
        monkeypatch.setattr("sys.argv", ["compile_prompts.py"])
        rc = main()
        assert rc == 1
        err = capsys.readouterr().err
        assert "CF_ACCOUNT_ID and CF_API_TOKEN" in err


def test_cli_success(tmp_path, monkeypatch, capsys):
    from scripts.compile_prompts import main

    temp_catalog_path = tmp_path / "dishes.json"
    temp_catalog_path.write_text(json.dumps({
        "dish1": {"name": "Beef Hot Dog", "needs_image": True}
    }))

    with patch("scripts.compile_prompts.CloudflareClient") as MockClient, \
         patch("scripts.compile_prompts.CATALOG_PATH", temp_catalog_path):
        client_inst = MockClient.return_value
        client_inst.is_configured.return_value = True
        client_inst.compile_dish_prompt.return_value = {
            "prompt": "Plated hot dog",
            "negative": "No sauce",
        }
        monkeypatch.setattr("sys.argv", ["compile_prompts.py", "--force"])
        rc = main()
        assert rc == 0
        out = capsys.readouterr().out
        assert "Successfully compiled prompts for 1 dishes" in out

        saved = json.loads(temp_catalog_path.read_text())
        assert saved["dish1"]["prompt"] == "Plated hot dog"
        assert saved["dish1"]["prompt_compiled"] is True


def test_cli_no_updates(tmp_path, monkeypatch, capsys):
    from scripts.compile_prompts import main

    temp_catalog_path = tmp_path / "dishes.json"
    temp_catalog_path.write_text(json.dumps({
        "dish1": {"name": "Side Salad", "needs_image": False}
    }))

    with patch("scripts.compile_prompts.CloudflareClient") as MockClient, \
         patch("scripts.compile_prompts.CATALOG_PATH", temp_catalog_path):
        client_inst = MockClient.return_value
        client_inst.is_configured.return_value = True
        monkeypatch.setattr("sys.argv", ["compile_prompts.py"])
        rc = main()
        assert rc == 0
        out = capsys.readouterr().out
        assert "No dishes needed prompt compilation" in out

