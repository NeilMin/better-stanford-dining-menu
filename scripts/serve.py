#!/usr/bin/env python3
"""Local development preview server with dynamic in-memory overlay injection.

Runs during `make serve` at http://127.0.0.1:8777.
Dynamically injects scripts/overlay/overlay.css and scripts/overlay/overlay.js
into HTML responses, and provides /api/redraw-queue for real-time dish selection.
"""

from __future__ import annotations

import argparse
import http.server
import io
import json
import socketserver
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bsdm import queue as queuelib  # noqa: E402

OVERLAY_DIR = ROOT / "scripts" / "overlay"
QUEUE_FILE = ROOT / "data" / "redraw_queue.json"


def inject_overlay(html_text: str, css_text: str, js_text: str) -> str:
    """Inject overlay styles and script right before </body> in memory."""
    if "</body>" not in html_text:
        return html_text

    injection = (
        f'\n<style id="bsdm-redraw-overlay-style">\n{css_text}\n</style>\n'
        f'<script id="bsdm-redraw-overlay-script">\n{js_text}\n</script>\n'
    )
    return html_text.replace("</body>", f"{injection}</body>", 1)


class BSDMDevHandler(http.server.SimpleHTTPRequestHandler):
    queue_file = QUEUE_FILE
    overlay_dir = OVERLAY_DIR

    def do_GET(self) -> None:
        clean_path = self.path.split("?")[0]
        if clean_path in ("/api/redraw-queue", "/api/redraw-queue/"):
            self.handle_get_queue()
            return
        super().do_GET()

    def do_POST(self) -> None:
        clean_path = self.path.split("?")[0]
        if clean_path in ("/api/redraw-queue", "/api/redraw-queue/"):
            self.handle_post_queue()
            return
        elif clean_path in ("/api/redraw-queue/clear", "/api/redraw-queue/clear/"):
            self.handle_clear_queue()
            return
        self.send_error(404, "Endpoint not found")

    def handle_get_queue(self) -> None:
        items = queuelib.load_queue(self.queue_file)
        payload = json.dumps(items, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def handle_post_queue(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(length).decode("utf-8")
            body = json.loads(raw_body)
        except (ValueError, json.JSONDecodeError):
            self.send_error(400, "Invalid JSON payload")
            return

        if not isinstance(body, dict):
            self.send_error(400, "Payload must be a JSON object")
            return

        action = body.get("action", "toggle")
        if action == "toggle":
            dish = body.get("dish")
            if not dish or not dish.get("id"):
                self.send_error(400, "Missing dish info")
                return
            updated = queuelib.toggle_dish(self.queue_file, dish)
        elif action == "set":
            queue = body.get("queue", [])
            queuelib.save_queue(self.queue_file, queue)
            updated = queue
        else:
            self.send_error(400, f"Unsupported action: {action}")
            return

        payload = json.dumps(updated, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def handle_clear_queue(self) -> None:
        queuelib.clear_queue(self.queue_file)
        payload = b'{"status": "cleared", "count": 0}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_head(self):
        """Intercept HTML file delivery to inject overlay assets in memory."""
        path = self.translate_path(self.path)
        p = Path(path)
        if p.is_dir():
            clean_path = self.path.split("?")[0]
            if not clean_path.endswith("/"):
                return super().send_head()
            index = p / "index.html"
            if index.exists():
                p = index
        if p.is_file() and p.suffix.lower() == ".html":
            try:
                raw_html = p.read_text(encoding="utf-8")
                css_text = (self.overlay_dir / "overlay.css").read_text(encoding="utf-8")
                js_text = (self.overlay_dir / "overlay.js").read_text(encoding="utf-8")
                modified_html = inject_overlay(raw_html, css_text, js_text)
                body = modified_html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                return io.BytesIO(body)
            except OSError:
                pass
        return super().send_head()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8777)
    ap.add_argument("--bind", default="127.0.0.1")
    ap.add_argument("--dir", default=str(ROOT / "site"))
    args = ap.parse_args()

    out_dir = Path(args.dir)
    if not (out_dir / "index.html").exists():
        print(f"Warning: {out_dir}/index.html does not exist. Run `make site` first.", file=sys.stderr)

    handler = lambda *h_args, **h_kwargs: BSDMDevHandler(*h_args, directory=str(out_dir), **h_kwargs)

    class ReusableTCPServer(socketserver.TCPServer):
        allow_reuse_address = True

    with ReusableTCPServer((args.bind, args.port), handler) as httpd:
        print(f"BSDM Local Dev Server (with redraw overlay) listening at http://{args.bind}:{args.port}")
        print("Press Ctrl+C to stop.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
