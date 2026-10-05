from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from PIL import Image
import pytest

from scripts import gen_images
from scripts.gen_images import main

ROOT = Path(__file__).resolve().parent.parent


def test_gen_images_from_queue_flag(tmp_path: Path):
    queue_file = tmp_path / "test_queue.json"
    queue_file.write_text(json.dumps([
        {"id": "dish_123", "name": "Test Dish"}
    ]), encoding="utf-8")

    # Invoking with --count should read queue and count matched dishes without drawing
    with patch("sys.argv", ["gen_images.py", "--from-queue", str(queue_file), "--count"]):
        assert main() == 0


def test_gen_images_from_queue_empty(tmp_path: Path, capsys):
    queue_file = tmp_path / "empty_queue.json"
    queue_file.write_text("[]", encoding="utf-8")

    with patch("sys.argv", ["gen_images.py", "--from-queue", str(queue_file)]):
        assert main() == 0
    captured = capsys.readouterr()
    assert f"Redraw queue at {queue_file} is empty. Nothing to redraw." in captured.out


def test_gen_images_from_queue_nonexistent_file(tmp_path: Path, capsys):
    queue_file = tmp_path / "nonexistent_queue.json"

    with patch("sys.argv", ["gen_images.py", "--from-queue", str(queue_file)]):
        assert main() == 0
    captured = capsys.readouterr()
    assert f"Redraw queue at {queue_file} is empty. Nothing to redraw." in captured.out


def test_gen_images_from_queue_filters_and_forces(tmp_path: Path, monkeypatch, capsys):
    root = tmp_path / "project"
    images_dir = root / "data" / "images"
    images_dir.mkdir(parents=True)

    catalog = {
        "dish1": {
            "name": "Dish One",
            "prompt": "Prompt 1",
            "needs_image": True,
            "image": "dish1.webp",
            "priority": 1,
        },
        "dish2": {
            "name": "Dish Two",
            "prompt": "Prompt 2",
            "needs_image": True,
            "image": "dish2.webp",
            "priority": 1,
        },
        "dish3": {
            "name": "Dish Three",
            "prompt": "Prompt 3",
            "needs_image": True,
            "image": None,
            "priority": 1,
        },
    }
    catalog_file = root / "data" / "dishes.json"
    catalog_file.write_text(json.dumps(catalog), encoding="utf-8")

    # Create 16:9 images for dish1 and dish2 so is_current() is True
    im = Image.new("RGB", (1024, 576), color="red")
    im.save(images_dir / "dish1.webp")
    im.save(images_dir / "dish2.webp")

    monkeypatch.setattr(gen_images, "ROOT", root)
    monkeypatch.setattr(gen_images, "CATALOG", catalog_file)
    monkeypatch.setattr(gen_images, "IMAGES", images_dir)

    queue_file = root / "data" / "redraw_queue.json"
    queue_file.write_text(json.dumps([{"id": "dish1", "name": "Dish One"}]), encoding="utf-8")

    # Normal run without --from-queue or --force: dish1 and dish2 are skipped (already have images), only dish3 pending
    with patch("sys.argv", ["gen_images.py", "--count"]):
        assert main() == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "1"

    # Run with --from-queue: dish1 is forced despite having an image, dish2 and dish3 are filtered out
    with patch("sys.argv", ["gen_images.py", "--from-queue", str(queue_file), "--count"]):
        assert main() == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "1"


def test_gen_images_from_queue_default_path(tmp_path: Path, monkeypatch, capsys):
    root = tmp_path / "project"
    (root / "data").mkdir(parents=True)
    catalog_file = root / "data" / "dishes.json"
    catalog_file.write_text("{}", encoding="utf-8")
    default_queue = root / "data" / "redraw_queue.json"
    default_queue.write_text("[]", encoding="utf-8")

    monkeypatch.setattr(gen_images, "ROOT", root)
    monkeypatch.setattr(gen_images, "CATALOG", catalog_file)

    with patch("sys.argv", ["gen_images.py", "--from-queue"]):
        assert main() == 0
    captured = capsys.readouterr()
    assert f"Redraw queue at {default_queue} is empty. Nothing to redraw." in captured.out
