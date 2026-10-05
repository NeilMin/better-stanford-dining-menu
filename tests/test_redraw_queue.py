from pathlib import Path

from bsdm.queue import clear_queue, load_queue, save_queue, toggle_dish


def test_queue_file_operations(tmp_path: Path):
    q_file = tmp_path / "redraw_queue.json"
    assert load_queue(q_file) == []

    dish1 = {"id": "dish123", "name": "Saffron Rice", "image": "dish123.webp"}
    save_queue(q_file, [dish1])
    assert load_queue(q_file) == [dish1]

    # Toggle existing dish -> removes it
    updated = toggle_dish(q_file, dish1)
    assert updated == []
    assert load_queue(q_file) == []

    # Toggle new dish -> adds it
    updated = toggle_dish(q_file, dish1)
    assert len(updated) == 1
    assert updated[0]["id"] == "dish123"
    assert updated[0]["name"] == "Saffron Rice"
    assert updated[0]["image"] == "dish123.webp"
    assert "added_at" in updated[0]

    # Clear queue
    clear_queue(q_file)
    assert load_queue(q_file) == []


def test_queue_edge_cases(tmp_path: Path):
    # Non-existent directory handling in save_queue
    sub_dir = tmp_path / "nested" / "dir"
    q_file = sub_dir / "redraw_queue.json"
    dish = {"id": "dish999"}
    updated = toggle_dish(q_file, dish)
    assert len(updated) == 1
    assert updated[0]["id"] == "dish999"
    assert updated[0]["name"] == ""
    assert updated[0]["image"] == "dish999.webp"

    # Corrupted JSON handling in load_queue
    q_file.write_text("invalid json content", encoding="utf-8")
    assert load_queue(q_file) == []

    # Non-list JSON in load_queue
    q_file.write_text('{"foo": "bar"}', encoding="utf-8")
    assert load_queue(q_file) == []
