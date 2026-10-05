import io
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scripts.serve import BSDMDevHandler, inject_overlay

ROOT = Path(__file__).resolve().parent.parent


def test_inject_overlay():
    html = "<html><head><title>Test</title></head><body><h1>Content</h1></body></html>"
    css = ".btn { color: red; }"
    js = "console.log('overlay');"

    injected = inject_overlay(html, css, js)
    assert '<style id="bsdm-redraw-overlay-style">\n.btn { color: red; }\n</style>' in injected
    assert '<script id="bsdm-redraw-overlay-script">\nconsole.log(\'overlay\');\n</script>' in injected
    assert injected.endswith("</body></html>")


def test_inject_overlay_no_body():
    html = "<html><head><title>Test</title></head><div>No body tag</div></html>"
    css = ".btn { color: red; }"
    js = "console.log('overlay');"

    assert inject_overlay(html, css, js) == html


def test_handler_api_routes(tmp_path: Path):
    queue_file = tmp_path / "data" / "redraw_queue.json"
    queue_file.parent.mkdir(parents=True, exist_ok=True)
    queue_file.write_text("[]", encoding="utf-8")

    # Mock handler without spinning up real sockets
    handler = BSDMDevHandler.__new__(BSDMDevHandler)
    handler.queue_file = queue_file
    handler.wfile = io.BytesIO()
    handler.send_response = MagicMock()
    handler.send_header = MagicMock()
    handler.end_headers = MagicMock()

    # GET /api/redraw-queue
    handler.handle_get_queue()
    response_data = json.loads(handler.wfile.getvalue().decode("utf-8"))
    assert response_data == []
    handler.send_response.assert_called_with(200)

    # POST /api/redraw-queue (toggle dish: add)
    handler.wfile = io.BytesIO()
    handler.rfile = io.BytesIO(
        json.dumps({
            "action": "toggle",
            "dish": {"id": "dish1", "name": "Bulgogi", "image": "dish1.webp"},
        }).encode("utf-8")
    )
    handler.headers = {"Content-Length": str(len(handler.rfile.getvalue()))}
    handler.handle_post_queue()

    response_data = json.loads(handler.wfile.getvalue().decode("utf-8"))
    assert len(response_data) == 1
    assert response_data[0]["id"] == "dish1"
    assert response_data[0]["name"] == "Bulgogi"

    # POST /api/redraw-queue (toggle dish: remove)
    handler.wfile = io.BytesIO()
    handler.rfile = io.BytesIO(
        json.dumps({
            "action": "toggle",
            "dish": {"id": "dish1"},
        }).encode("utf-8")
    )
    handler.headers = {"Content-Length": str(len(handler.rfile.getvalue()))}
    handler.handle_post_queue()

    response_data = json.loads(handler.wfile.getvalue().decode("utf-8"))
    assert len(response_data) == 0

    # POST /api/redraw-queue (set queue)
    handler.wfile = io.BytesIO()
    handler.rfile = io.BytesIO(
        json.dumps({
            "action": "set",
            "queue": [{"id": "dish2", "name": "Kimchi"}],
        }).encode("utf-8")
    )
    handler.headers = {"Content-Length": str(len(handler.rfile.getvalue()))}
    handler.handle_post_queue()

    response_data = json.loads(handler.wfile.getvalue().decode("utf-8"))
    assert len(response_data) == 1
    assert response_data[0]["id"] == "dish2"

    # POST /api/redraw-queue/clear
    handler.wfile = io.BytesIO()
    handler.handle_clear_queue()
    response_data = json.loads(handler.wfile.getvalue().decode("utf-8"))
    assert response_data == {"status": "cleared", "count": 0}

    # Verify queue is now empty
    handler.wfile = io.BytesIO()
    handler.handle_get_queue()
    assert json.loads(handler.wfile.getvalue().decode("utf-8")) == []


def test_handler_post_queue_errors(tmp_path: Path):
    queue_file = tmp_path / "data" / "redraw_queue.json"
    handler = BSDMDevHandler.__new__(BSDMDevHandler)
    handler.queue_file = queue_file
    handler.wfile = io.BytesIO()
    handler.send_error = MagicMock()

    # Invalid JSON
    handler.rfile = io.BytesIO(b"not json")
    handler.headers = {"Content-Length": str(len(handler.rfile.getvalue()))}
    handler.handle_post_queue()
    handler.send_error.assert_called_with(400, "Invalid JSON payload")

    # Non-dict JSON
    handler.send_error.reset_mock()
    handler.rfile = io.BytesIO(b'["list", "not", "object"]')
    handler.headers = {"Content-Length": str(len(handler.rfile.getvalue()))}
    handler.handle_post_queue()
    handler.send_error.assert_called_with(400, "Payload must be a JSON object")

    # Missing dish on toggle
    handler.send_error.reset_mock()
    handler.rfile = io.BytesIO(json.dumps({"action": "toggle"}).encode("utf-8"))
    handler.headers = {"Content-Length": str(len(handler.rfile.getvalue()))}
    handler.handle_post_queue()
    handler.send_error.assert_called_with(400, "Missing dish info")

    # Unsupported action
    handler.send_error.reset_mock()
    handler.rfile = io.BytesIO(json.dumps({"action": "unknown"}).encode("utf-8"))
    handler.headers = {"Content-Length": str(len(handler.rfile.getvalue()))}
    handler.handle_post_queue()
    handler.send_error.assert_called_with(400, "Unsupported action: unknown")


def test_handler_routing(tmp_path: Path):
    handler = BSDMDevHandler.__new__(BSDMDevHandler)
    handler.handle_get_queue = MagicMock()
    handler.handle_post_queue = MagicMock()
    handler.handle_clear_queue = MagicMock()
    handler.send_error = MagicMock()

    # do_GET /api/redraw-queue
    handler.path = "/api/redraw-queue"
    handler.do_GET()
    handler.handle_get_queue.assert_called_once()

    # do_GET with query param
    handler.handle_get_queue.reset_mock()
    handler.path = "/api/redraw-queue?ts=123"
    handler.do_GET()
    handler.handle_get_queue.assert_called_once()

    # do_POST /api/redraw-queue
    handler.path = "/api/redraw-queue"
    handler.do_POST()
    handler.handle_post_queue.assert_called_once()

    # do_POST /api/redraw-queue/clear
    handler.path = "/api/redraw-queue/clear"
    handler.do_POST()
    handler.handle_clear_queue.assert_called_once()

    # do_POST unknown route
    handler.path = "/api/unknown"
    handler.do_POST()
    handler.send_error.assert_called_with(404, "Endpoint not found")


def test_handler_send_head_injection(tmp_path: Path):
    site_dir = tmp_path / "site"
    site_dir.mkdir(parents=True)
    html_file = site_dir / "index.html"
    html_file.write_text("<!doctype html><html><body><h1>Stanford Menus</h1></body></html>", encoding="utf-8")

    overlay_dir = tmp_path / "overlay"
    overlay_dir.mkdir(parents=True)
    (overlay_dir / "overlay.css").write_text(".overlay { z-index: 999; }", encoding="utf-8")
    (overlay_dir / "overlay.js").write_text("console.log('init overlay');", encoding="utf-8")

    handler = BSDMDevHandler.__new__(BSDMDevHandler)
    handler.overlay_dir = overlay_dir
    handler.path = "/index.html"
    handler.translate_path = MagicMock(return_value=str(html_file))
    handler.send_response = MagicMock()
    handler.send_header = MagicMock()
    handler.end_headers = MagicMock()

    body_io = handler.send_head()
    assert body_io is not None
    content = body_io.read().decode("utf-8")

    assert '<style id="bsdm-redraw-overlay-style">\n.overlay { z-index: 999; }\n</style>' in content
    assert '<script id="bsdm-redraw-overlay-script">\nconsole.log(\'init overlay\');\n</script>' in content
    assert content.endswith("</body></html>")

    handler.send_response.assert_called_with(200)
    handler.send_header.assert_any_call("Content-Type", "text/html; charset=utf-8")
    handler.send_header.assert_any_call("Cache-Control", "no-cache")


def test_handler_send_head_dir_index(tmp_path: Path):
    site_dir = tmp_path / "site"
    site_dir.mkdir(parents=True)
    html_file = site_dir / "index.html"
    html_file.write_text("<html><body>Index Page</body></html>", encoding="utf-8")

    overlay_dir = tmp_path / "overlay"
    overlay_dir.mkdir(parents=True)
    (overlay_dir / "overlay.css").write_text("/* css */", encoding="utf-8")
    (overlay_dir / "overlay.js").write_text("/* js */", encoding="utf-8")

    handler = BSDMDevHandler.__new__(BSDMDevHandler)
    handler.overlay_dir = overlay_dir
    handler.path = "/"
    handler.translate_path = MagicMock(return_value=str(site_dir))
    handler.send_response = MagicMock()
    handler.send_header = MagicMock()
    handler.end_headers = MagicMock()

    body_io = handler.send_head()
    assert body_io is not None
    content = body_io.read().decode("utf-8")
    assert "/* css */" in content
    assert "/* js */" in content


def test_handler_send_head_fallback_non_html(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    file_path = tmp_path / "site" / "app.css"
    file_path.parent.mkdir(parents=True)
    file_path.write_text("body { margin: 0; }", encoding="utf-8")

    handler = BSDMDevHandler.__new__(BSDMDevHandler)
    handler.path = "/app.css"
    handler.translate_path = MagicMock(return_value=str(file_path))
    super_send_head = MagicMock(return_value=io.BytesIO(b"super body"))
    monkeypatch.setattr("http.server.SimpleHTTPRequestHandler.send_head", super_send_head)

    res = handler.send_head()
    assert res.read() == b"super body"
    super_send_head.assert_called_once()

