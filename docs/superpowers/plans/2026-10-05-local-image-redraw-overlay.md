# Local Dish Image Redraw Overlay Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a completely local-only overlay tool and dev server allowing maintainers to visually select dish images on `http://127.0.0.1:8777` for AI regeneration, saving to `data/redraw_queue.json` in real time, with 100% zero trace on the deployed production site.

**Architecture:** A local development server `scripts/serve.py` replaces `python3 -m http.server` in `make serve`. It dynamically injects `scripts/overlay/overlay.css` and `scripts/overlay/overlay.js` before `</body>` in memory only when serving HTML. The frontend overlay attaches click-to-select badges to dish cards and syncs state to `/api/redraw-queue`. A `--from-queue` flag on `scripts/gen_images.py` allows one-step batch regeneration of selected dishes.

**Tech Stack:** Python 3 standard library (`http.server`, `urllib`, `json`), Vanilla JavaScript (DOM manipulation, MutationObserver, Fetch API), CSS3 (CSS Grid, transitions, sticky dock), Pytest.

## Global Constraints
- Absolute zero code leakage: `web/` source files (`app.js`, `app.css`, `index.html`) and `bsdm/build.py` must NOT be modified.
- Production site artifact (`site/index.html`) must contain 0 bytes of overlay code.
- No new external pip/npm dependencies (pure Python standard library and vanilla browser JS).
- No network sockets in unit tests (follow `tests/conftest.py` rules).
- `data/redraw_queue.json` must be git-ignored.

---

### Task 1: Update `.gitignore` and Create Core Queue Data Model Helpers

**Files:**
- Modify: `.gitignore:1-40`
- Create: `bsdm/queue.py`
- Test: `tests/test_redraw_queue.py`

**Interfaces:**
- Consumes: None
- Produces:
  - `bsdm.queue.load_queue(path: Path) -> list[dict]`
  - `bsdm.queue.save_queue(path: Path, queue: list[dict]) -> None`
  - `bsdm.queue.clear_queue(path: Path) -> None`
  - `bsdm.queue.toggle_dish(path: Path, dish: dict) -> list[dict]`

- [ ] **Step 1: Write the failing test for queue helpers**

```python
# tests/test_redraw_queue.py
from pathlib import Path
from bsdm.queue import load_queue, save_queue, clear_queue, toggle_dish


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
    assert "added_at" in updated[0]

    # Clear queue
    clear_queue(q_file)
    assert load_queue(q_file) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_redraw_queue.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bsdm.queue'`

- [ ] **Step 3: Implement `bsdm/queue.py` and update `.gitignore`**

```python
# bsdm/queue.py
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
```

Add `data/redraw_queue.json` to `.gitignore`:
```gitignore
# Local redraw selection queue
data/redraw_queue.json
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_redraw_queue.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add .gitignore bsdm/queue.py tests/test_redraw_queue.py
git commit -m "feat(queue): add data model and atomic file operations for redraw queue"
```

---

### Task 2: Implement Overlay Assets (`scripts/overlay/overlay.css` and `scripts/overlay/overlay.js`)

**Files:**
- Create: `scripts/overlay/overlay.css`
- Create: `scripts/overlay/overlay.js`
- Test: `tests/test_overlay_assets.py`

**Interfaces:**
- Consumes: `/api/redraw-queue` (GET/POST)
- Produces: Client-side DOM elements (`.btn-redraw-toggle`, `.card-redraw-active`, `#bsdm-redraw-dock`)

- [ ] **Step 1: Write test verifying overlay assets exist and are syntactically sound**

```python
# tests/test_overlay_assets.py
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_overlay_files_exist():
    css_file = ROOT / "scripts" / "overlay" / "overlay.css"
    js_file = ROOT / "scripts" / "overlay" / "overlay.js"

    assert css_file.exists(), "overlay.css must exist"
    assert js_file.exists(), "overlay.js must exist"

    css_text = css_file.read_text(encoding="utf-8")
    js_text = js_file.read_text(encoding="utf-8")

    assert ".btn-redraw-toggle" in css_text
    assert ".card-redraw-active" in css_text
    assert "bsdm-redraw-dock" in css_text

    assert "fetch('/api/redraw-queue'" in js_text
    assert "stopPropagation" in js_text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_overlay_assets.py -v`
Expected: FAIL with `AssertionError: overlay.css must exist`

- [ ] **Step 3: Implement `scripts/overlay/overlay.css`**

```css
/* scripts/overlay/overlay.css */
/* Local Redraw Selection Overlay Styles (Zero-Leak Dev Tool) */

.card {
  position: relative;
  transition: box-shadow 0.15s ease, border-color 0.15s ease;
}

/* Card active/selected state */
.card.card-redraw-active {
  outline: 3px solid #e11d48 !important;
  outline-offset: -1px;
  box-shadow: 0 0 16px rgba(225, 29, 72, 0.45) !important;
}

/* Corner toggle button */
.btn-redraw-toggle {
  position: absolute;
  top: 8px;
  right: 8px;
  z-index: 10;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 4px 8px;
  border-radius: 9999px;
  background: rgba(15, 23, 42, 0.75);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
  color: #f8fafc;
  border: 1px solid rgba(255, 255, 255, 0.25);
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  user-select: none;
  transition: transform 0.12s ease, background 0.15s ease, border-color 0.15s ease;
  line-height: 1;
}

.btn-redraw-toggle:hover {
  transform: scale(1.06);
  background: rgba(15, 23, 42, 0.9);
  border-color: rgba(255, 255, 255, 0.5);
}

.btn-redraw-toggle.is-selected {
  background: #e11d48;
  border-color: #fda4af;
  color: #ffffff;
  box-shadow: 0 2px 8px rgba(225, 29, 72, 0.5);
}

.btn-redraw-toggle svg {
  width: 12px;
  height: 12px;
  fill: none;
  stroke: currentColor;
  stroke-width: 2.2;
  stroke-linecap: round;
  stroke-linejoin: round;
}

/* Floating dock at bottom-right */
#bsdm-redraw-dock {
  position: fixed;
  bottom: 20px;
  right: 20px;
  z-index: 9999;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}

.redraw-dock-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 14px;
  border-radius: 9999px;
  background: #0f172a;
  color: #f8fafc;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
  border: 1px solid #334155;
  font-size: 13px;
  font-weight: 500;
}

.redraw-dock-count {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #f43f5e;
  font-weight: 700;
}

.redraw-dock-count.has-items {
  color: #fb7185;
}

.redraw-dock-btn {
  background: #1e293b;
  color: #e2e8f0;
  border: 1px solid #475569;
  border-radius: 6px;
  padding: 4px 8px;
  font-size: 11px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.redraw-dock-btn:hover {
  background: #334155;
  color: #ffffff;
}

.redraw-dock-btn.btn-clear {
  color: #94a3b8;
}

.redraw-dock-btn.btn-clear:hover {
  background: #475569;
  color: #fca5a5;
}

/* Drawer modal for reviewing selected items */
.redraw-drawer {
  width: 320px;
  max-height: 400px;
  margin-bottom: 10px;
  background: #0f172a;
  border: 1px solid #334155;
  border-radius: 12px;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.45);
  display: none;
  flex-direction: column;
  overflow: hidden;
  color: #f8fafc;
}

.redraw-drawer.is-open {
  display: flex;
}

.redraw-drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border-bottom: 1px solid #1e293b;
  font-size: 13px;
  font-weight: 600;
}

.redraw-drawer-list {
  padding: 8px 12px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.redraw-drawer-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 8px;
  background: #1e293b;
  border-radius: 6px;
  font-size: 12px;
}

.redraw-drawer-item-title {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 220px;
}

.redraw-drawer-item-remove {
  background: none;
  border: none;
  color: #94a3b8;
  cursor: pointer;
  padding: 2px 6px;
  font-size: 14px;
}

.redraw-drawer-item-remove:hover {
  color: #f43f5e;
}
```

- [ ] **Step 4: Implement `scripts/overlay/overlay.js`**

```javascript
// scripts/overlay/overlay.js
(() => {
  "use strict";

  // In-memory queue of selected dish IDs -> dish object
  let queueMap = new Map();
  let drawerOpen = false;

  const ICONS = {
    refresh: '<svg viewBox="0 0 24 24"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/></svg>',
    check: '<svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>',
  };

  async function fetchQueue() {
    try {
      const res = await fetch("/api/redraw-queue");
      if (res.ok) {
        const items = await res.json();
        queueMap = new Map(items.map((it) => [it.id, it]));
        syncAllCards();
        updateDockUI();
      }
    } catch (err) {
      console.warn("[Overlay] Could not connect to /api/redraw-queue:", err);
    }
  }

  async function toggleDishOnServer(dish) {
    // Optimistic local update
    if (queueMap.has(dish.id)) {
      queueMap.delete(dish.id);
    } else {
      queueMap.set(dish.id, dish);
    }
    syncAllCards();
    updateDockUI();

    try {
      const res = await fetch("/api/redraw-queue", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "toggle", dish }),
      });
      if (res.ok) {
        const items = await res.json();
        queueMap = new Map(items.map((it) => [it.id, it]));
        syncAllCards();
        updateDockUI();
      }
    } catch (err) {
      console.error("[Overlay] Failed to toggle dish on server:", err);
    }
  }

  async function clearQueueOnServer() {
    queueMap.clear();
    syncAllCards();
    updateDockUI();

    try {
      await fetch("/api/redraw-queue/clear", { method: "POST" });
    } catch (err) {
      console.error("[Overlay] Failed to clear queue on server:", err);
    }
  }

  function getDishInfo(card) {
    const thumb = card.querySelector("img.thumb");
    if (!thumb) return null;
    const src = thumb.getAttribute("src") || "";
    const match = src.match(/img\/([^/?#]+)\.webp/);
    if (!match) return null;

    const id = match[1];
    const nameEl = card.querySelector(".dish-name");
    const name = nameEl ? nameEl.textContent.trim() : id;
    return { id, name, image: `${id}.webp` };
  }

  function syncCard(card) {
    const info = getDishInfo(card);
    if (!info) return;

    let btn = card.querySelector(".btn-redraw-toggle");
    if (!btn) {
      btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn-redraw-toggle";
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        toggleDishOnServer(info);
      });
      card.appendChild(btn);
    }

    const isSelected = queueMap.has(info.id);
    if (isSelected) {
      card.classList.add("card-redraw-active");
      btn.classList.add("is-selected");
      btn.innerHTML = `${ICONS.check} <span>已选重画</span>`;
      btn.title = "已加入重画队列 (点击取消)";
    } else {
      card.classList.remove("card-redraw-active");
      btn.classList.remove("is-selected");
      btn.innerHTML = `${ICONS.refresh} <span>重画</span>`;
      btn.title = "标记此图，加入重画队列";
    }
  }

  function syncAllCards() {
    document.querySelectorAll(".card").forEach(syncCard);
  }

  function createDock() {
    if (document.getElementById("bsdm-redraw-dock")) return;

    const dock = document.createElement("div");
    dock.id = "bsdm-redraw-dock";
    dock.innerHTML = `
      <div class="redraw-drawer" id="bsdm-redraw-drawer">
        <div class="redraw-drawer-header">
          <span>待重画清单 (<span id="redraw-drawer-count">0</span>)</span>
          <button class="redraw-dock-btn" id="redraw-close-drawer">关闭</button>
        </div>
        <div class="redraw-drawer-list" id="redraw-drawer-list"></div>
      </div>
      <div class="redraw-dock-bar">
        <span class="redraw-dock-count" id="redraw-dock-count">🎯 待重画: 0</span>
        <button class="redraw-dock-btn" id="redraw-toggle-drawer">清单</button>
        <button class="redraw-dock-btn btn-clear" id="redraw-clear-btn">清空</button>
      </div>
    `;
    document.body.appendChild(dock);

    document.getElementById("redraw-toggle-drawer").addEventListener("click", () => {
      drawerOpen = !drawerOpen;
      updateDockUI();
    });

    document.getElementById("redraw-close-drawer").addEventListener("click", () => {
      drawerOpen = false;
      updateDockUI();
    });

    document.getElementById("redraw-clear-btn").addEventListener("click", () => {
      if (queueMap.size === 0) return;
      if (confirm(`确认清空选中的 ${queueMap.size} 道重画菜品？`)) {
        clearQueueOnServer();
      }
    });
  }

  function updateDockUI() {
    const count = queueMap.size;
    const countEl = document.getElementById("redraw-dock-count");
    if (countEl) {
      countEl.textContent = `🎯 待重画: ${count}`;
      countEl.classList.toggle("has-items", count > 0);
    }

    const drawerCount = document.getElementById("redraw-drawer-count");
    if (drawerCount) drawerCount.textContent = count;

    const drawer = document.getElementById("bsdm-redraw-drawer");
    if (drawer) {
      drawer.classList.toggle("is-open", drawerOpen);
      const listEl = document.getElementById("redraw-drawer-list");
      if (listEl) {
        if (count === 0) {
          listEl.innerHTML = '<div style="padding: 12px; color: #64748b; text-align: center;">暂无选中菜品，点击卡片右上角“重画”添加</div>';
        } else {
          listEl.innerHTML = Array.from(queueMap.values())
            .map(
              (item) => `
            <div class="redraw-drawer-item">
              <span class="redraw-drawer-item-title" title="${item.name}">${item.name}</span>
              <button class="redraw-drawer-item-remove" data-id="${item.id}" title="移除">×</button>
            </div>
          `
            )
            .join("");

          listEl.querySelectorAll(".redraw-drawer-item-remove").forEach((btn) => {
            btn.addEventListener("click", (e) => {
              const id = e.currentTarget.getAttribute("data-id");
              const item = queueMap.get(id);
              if (item) toggleDishOnServer(item);
            });
          });
        }
      }
    }
  }

  function init() {
    createDock();
    fetchQueue();

    // Observe board updates when user switches date/meal/halls
    const observer = new MutationObserver(() => {
      syncAllCards();
    });
    const board = document.getElementById("board") || document.body;
    observer.observe(board, { childList: true, subtree: true });

    // Initial sync
    syncAllCards();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_overlay_assets.py -v`
Expected: PASS

- [ ] **Step 6: Commit changes**

```bash
git add scripts/overlay/ tests/test_overlay_assets.py
git commit -m "feat(overlay): implement zero-leak overlay CSS and JS client code"
```

---

### Task 3: Implement Local Dev Server with Dynamic In-Memory Injection (`scripts/serve.py`)

**Files:**
- Create: `scripts/serve.py`
- Modify: `Makefile:44-46`
- Test: `tests/test_serve_server.py`

**Interfaces:**
- Consumes: `bsdm.queue` (`load_queue`, `save_queue`, `clear_queue`, `toggle_dish`), `site/`, `scripts/overlay/`
- Produces: HTTP Server handling static files, HTML injection, and `/api/redraw-queue`

- [ ] **Step 1: Write test for server handler and injection**

```python
# tests/test_serve_server.py
import io
import json
from pathlib import Path
from unittest.mock import MagicMock
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

    # POST /api/redraw-queue (toggle dish)
    handler.wfile = io.BytesIO()
    handler.rfile = io.BytesIO(json.dumps({
        "action": "toggle",
        "dish": {"id": "dish1", "name": "Bulgogi", "image": "dish1.webp"}
    }).encode("utf-8"))
    handler.headers = {"Content-Length": str(len(handler.rfile.getvalue()))}
    handler.handle_post_queue()

    response_data = json.loads(handler.wfile.getvalue().decode("utf-8"))
    assert len(response_data) == 1
    assert response_data[0]["id"] == "dish1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_serve_server.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.serve'`

- [ ] **Step 3: Implement `scripts/serve.py`**

```python
#!/usr/bin/env python3
"""Local development preview server with dynamic in-memory overlay injection.

Runs during `make serve` at http://127.0.0.1:8777.
Dynamically injects scripts/overlay/overlay.css and scripts/overlay/overlay.js
into HTML responses, and provides /api/redraw-queue for real-time dish selection.
"""

from __future__ import annotations

import argparse
import http.server
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

    def do_GET(self) -> None:
        if self.path == "/api/redraw-queue":
            self.handle_get_queue()
            return
        super().do_GET()

    def do_POST(self) -> None:
        if self.path == "/api/redraw-queue":
            self.handle_post_queue()
            return
        elif self.path == "/api/redraw-queue/clear":
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
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, json.JSONDecodeError):
            self.send_error(400, "Invalid JSON payload")
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
            index = p / "index.html"
            if index.exists():
                p = index
        if p.is_file() and p.suffix.lower() == ".html":
            try:
                raw_html = p.read_text(encoding="utf-8")
                css_text = (OVERLAY_DIR / "overlay.css").read_text(encoding="utf-8")
                js_text = (OVERLAY_DIR / "overlay.js").read_text(encoding="utf-8")
                modified_html = inject_overlay(raw_html, css_text, js_text)
                body = modified_html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                import io
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
```

Update `Makefile` line 44-46:
```makefile
serve: site                ## preview at http://127.0.0.1:8777
	$(PY) scripts/serve.py
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_serve_server.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add scripts/serve.py Makefile tests/test_serve_server.py
git commit -m "feat(serve): implement dynamic overlay injection in local dev server"
```

---

### Task 4: CLI Batch Regeneration Integration (`scripts/gen_images.py --from-queue`)

**Files:**
- Modify: `scripts/gen_images.py:165-225`
- Test: `tests/test_gen_images_queue.py`

**Interfaces:**
- Consumes: `bsdm.queue.load_queue`, `data/redraw_queue.json`
- Produces: CLI argument `--from-queue [PATH]` which forces redraw for matching dish IDs.

- [ ] **Step 1: Write test for `--from-queue` argument handling in `scripts/gen_images.py`**

```python
# tests/test_gen_images_queue.py
import json
from pathlib import Path
from unittest.mock import patch
import pytest
from scripts.gen_images import main

ROOT = Path(__file__).resolve().parent.parent


def test_gen_images_from_queue_flag(tmp_path: Path):
    queue_file = tmp_path / "test_queue.json"
    queue_file.write_text(json.dumps([
        {"id": "dish_123", "name": "Test Dish"}
    ]), encoding="utf-8")

    # Invoking with --count should read queue and count matched dishes without drawing
    with patch("sys.argv", ["gen_images.py", "--from-queue", str(queue_file), "--count"]):
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_gen_images_queue.py -v`
Expected: FAIL with `unrecognized arguments: --from-queue`

- [ ] **Step 3: Modify `scripts/gen_images.py` to support `--from-queue`**

In `scripts/gen_images.py`:
1. Import `load_queue` from `bsdm.queue`:
   ```python
   from bsdm.queue import load_queue
   ```
2. Add argument to argument parser:
   ```python
   ap.add_argument("--from-queue", nargs="?", const=str(ROOT / "data" / "redraw_queue.json"),
                   help="Read dishes to redraw from redraw_queue.json and force regeneration")
   ```
3. In `main()`, load queue IDs if `--from-queue` is provided:
   ```python
   queue_ids: set[str] | None = None
   if args.from_queue:
       q_path = Path(args.from_queue)
       queue_items = load_queue(q_path)
       if not queue_items:
           print(f"Redraw queue at {q_path} is empty. Nothing to redraw.")
           return 0
       queue_ids = {item["id"] for item in queue_items}
       args.force = True
   ```
4. In the catalog pending dish loop:
   ```python
   if queue_ids is not None and did not in queue_ids:
       continue
   ```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_gen_images_queue.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add scripts/gen_images.py tests/test_gen_images_queue.py
git commit -m "feat(gen_images): add --from-queue option for batch regenerating queued dishes"
```

---

### Task 5: Zero-Leak Isolation & Production Purity Verification

**Files:**
- Create: `tests/test_production_purity.py`

**Interfaces:**
- Consumes: `bsdm.build.build`, `site/index.html`, `web/`
- Produces: Test suite validating that NO overlay code ever leaks into production files.

- [ ] **Step 1: Write comprehensive production purity test**

```python
# tests/test_production_purity.py
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_web_source_purity():
    """Verify that web/ source files have zero overlay references."""
    forbidden_terms = [
        "bsdm-redraw",
        "btn-redraw-toggle",
        "card-redraw-active",
        "/api/redraw-queue",
        "redraw_queue",
    ]

    web_dir = ROOT / "web"
    for file in web_dir.iterdir():
        if file.suffix in (".html", ".js", ".css"):
            text = file.read_text(encoding="utf-8")
            for term in forbidden_terms:
                assert term not in text, f"Leak detected in {file.name}: found {term!r}"


def test_site_build_purity():
    """Verify that built site/ artifacts contain 0 bytes of overlay code."""
    forbidden_terms = [
        "bsdm-redraw-overlay",
        "btn-redraw-toggle",
        "card-redraw-active",
        "/api/redraw-queue",
        "redraw_queue",
    ]

    site_index = ROOT / "site" / "index.html"
    if site_index.exists():
        text = site_index.read_text(encoding="utf-8")
        for term in forbidden_terms:
            assert term not in text, f"Leak detected in site/index.html: found {term!r}"
```

- [ ] **Step 2: Run test to verify it passes on pristine codebase**

Run: `uv run pytest tests/test_production_purity.py -v`
Expected: PASS

- [ ] **Step 3: Commit changes**

```bash
git add tests/test_production_purity.py
git commit -m "test: add zero-leak production purity verification test"
```

---

### Task 6: Full Integration Test & End-to-End Verification

**Files:**
- Run full pytest test suite: `uv run pytest`
- Verify `make test` passes.
- Verify `make site` passes.

- [ ] **Step 1: Run full test suite**

Run: `make test`
Expected: All tests pass in ~2s with zero failures.

- [ ] **Step 2: Verify site rebuild passes**

Run: `make site`
Expected: Static site builds cleanly with no warnings or errors.

- [ ] **Step 3: Verify git status is clean and ready**

Run: `git status`
Expected: Clean working tree on main branch.
