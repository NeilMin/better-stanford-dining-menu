"""Helper functions for managing data/redraw_queue.json."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def load_queue(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_queue(path: Path, queue: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(queue, indent=2, ensure_ascii=False) + "\n"
    # Atomic write to avoid race conditions or half-written files
    dir_name = str(path.parent)
    with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, encoding="utf-8") as tf:
        tf.write(payload)
        temp_name = tf.name
    os.replace(temp_name, path)


def clear_queue(path: Path) -> None:
    save_queue(path, [])


def toggle_dish(path: Path, dish: dict) -> list[dict]:
    current = load_queue(path)
    did = dish["id"]
    existing_idx = next((i for i, item in enumerate(current) if item.get("id") == did), None)
    if existing_idx is not None:
        current.pop(existing_idx)
    else:
        entry = {
            "id": did,
            "name": dish.get("name", ""),
            "image": dish.get("image", f"{did}.webp"),
            "added_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        current.append(entry)
    save_queue(path, current)
    return current
