# Local Dish Image Redraw Overlay Tool Design

**Author**: Antigravity & NeilMin  
**Date**: 2026-10-05  
**Status**: Approved (Transitioning to Implementation Plan)

---

## 1. Background & Problem Statement

Better Stanford Dining Menu (BSDM) illustrates dining hall dishes with locally generated AI food photography (via ComfyUI RealVisXL on port `8189`). While reviewing the dining dashboard locally, the maintainer occasionally spots dishes whose generated images do not meet quality expectations (e.g. incorrect presentation or suboptimal composition).

Currently, reporting these dishes for regeneration requires copying dish names or IDs one by one into the chat assistant. This manual process introduces unnecessary friction.

The maintainer needs a **completely local overlay tool** that allows clicking to select dishes directly while browsing the local website. Once selection is complete, the maintainer returns to the chat session and simply says "你可以把它们重新生成了" (You can regenerate them now), and the assistant regenerates them in batch.

### Critical Invariant: Zero-Leak Production Purity
The user explicitly specified:
> "这个 tool 只有我本地用，我们不把它 deploy 到真正的网站上。"  
> "那用户打开我这网站查看源代码，他能看见我们这一层 overlay 吗？"

**Requirement**: The deployed production website (`https://stanford-dining.neilmin.com`) must contain **absolutely zero trace** of this tool. No overlay JavaScript, CSS, HTML elements, or API endpoints may exist in `web/app.js`, `web/app.css`, or the built artifact `site/index.html` uploaded by GitHub Actions (`pages.yml`). Anyone viewing page source on the live website must see 0 bytes of overlay code.

---

## 2. Goals & Non-Goals

### Goals
- **Seamless 3-Step Workflow**:
  1. Browse `http://127.0.0.1:8777` via `make serve` and click corner checkboxes on dishes to mark them for redraw.
  2. Switch to chat and notify the assistant ("可以重新生成了").
  3. Assistant reads the queue file and regenerates the dishes via ComfyUI.
- **Dynamic In-Memory Dev Injection**: The production files in `web/` remain completely untouched. The overlay code lives in `scripts/overlay/` and is dynamically injected into HTML responses in memory only by the local dev server (`scripts/serve.py`).
- **Real-Time Workspace Sync**: Toggling a card in the browser immediately updates `data/redraw_queue.json` via a local endpoint, surviving page refreshes and browser tab navigation.
- **Non-Destructive Card Interactions**: Clicking the selection badge toggles redraw status with `stopPropagation()`, preserving normal card clicks that open the full-photo Lightbox.
- **Batch Redraw Execution**: Easy CLI integration (e.g. `scripts/gen_images.py --from-queue`) for the assistant to run the redraw pipeline with `--force` on queued dishes.

### Non-Goals
- No remote server or external database dependency.
- No modifications to `bsdm/build.py`, `web/app.js`, `web/app.css`, or `web/index.html`.
- No changes to the production CI/CD deployment pipeline (`pages.yml`).

---

## 3. Architecture & Data Flow

```
[Local Browser: http://127.0.0.1:8777]
        │
        ├── 1. GET / (Request HTML)
        │         ▲
        │         │ 2. Injects <style> & <script> before </body>
        ▼         │
  [scripts/serve.py (Local Dev Server)] ◄─── Reads static files from site/
        │                               ◄─── Injects scripts/overlay/overlay.{css,js}
        │
        ├── 3. User clicks dish corner badge ──► POST /api/redraw-queue
        ▼
  [data/redraw_queue.json] (Workspace Queue File, git-ignored)
        │
        ▼
  [User returns to chat]: "你可以把它们重新生成了"
        │
        ▼
  [Assistant triggers CLI]:
  uv run python scripts/gen_images.py --from-queue (or --only <id> --force)
        │
        ├── Invokes ComfyUI (RealVisXL on port 8189)
        ├── Updates data/briefs.json, data/dishes.json, data/images/<id>.webp
        └── Rebuilds local preview: make site
```

---

## 4. Component Specifications

### 4.1. Local Dev Server (`scripts/serve.py`)
- **Base**: Subclasses Python's `http.server.SimpleHTTPRequestHandler` bound to `127.0.0.1:8777` with directory `site/`.
- **Dynamic HTML Injection**:
  - Intercepts requests for `.html` files (or root `/` and `/<hallId>/`).
  - Reads the built `site/` HTML file.
  - Reads `scripts/overlay/overlay.css` and `scripts/overlay/overlay.js` from the repository root.
  - Replaces `</body>` with:
    ```html
    <style id="bsdm-redraw-overlay-style">/* overlay.css */</style>
    <script id="bsdm-redraw-overlay-script">/* overlay.js */</script>
    </body>
    ```
- **Local API Endpoints**:
  - `GET /api/redraw-queue`: Returns JSON array of currently queued dishes (`[{ "id": str, "name": str, "image": str, "updated_at": str }, ...]`).
  - `POST /api/redraw-queue`: Accepts JSON body `{ "action": "set", "queue": [...] }` or `{ "action": "toggle", "dish": {...} }`. Atomically writes to `data/redraw_queue.json`.
  - `POST /api/redraw-queue/clear`: Resets queue to `[]`.
- **Makefile Update**:
  ```makefile
  serve: site
      $(PY) scripts/serve.py
  ```

### 4.2. Overlay Frontend (`scripts/overlay/overlay.js` & `overlay.css`)
- **Card Badge**:
  - Injects a circular button badge (`.btn-redraw-toggle`) into the top-right corner of each illustratable dish card (`.card`).
  - Contains an intuitive icon (e.g. circular refresh symbol `⟳`).
  - Clicking calls `e.preventDefault()` and `e.stopPropagation()` to avoid triggering `openLightbox()`.
  - Selected state adds class `.card-redraw-active` to the card (conspicuous amber/red glowing border and filled badge).
- **Floating Dock Bar**:
  - Fixed to bottom right of viewport:
    - Badge: `🎯 待重画: <count> 道菜`
    - Actions: `[查看清单]` (expands compact modal/drawer showing selected thumbnails and names), `[清空]` (clears queue).
- **State Synchronization**:
  - On page load: fetches `GET /api/redraw-queue` to restore active highlights across any hall or date view.
  - Observes DOM changes (via `MutationObserver` on `#board`) so switching dates, meals, or halls immediately attaches badges and highlights active cards.

### 4.3. Data Storage (`data/redraw_queue.json`)
- Format:
  ```json
  [
    {
      "id": "42a7b39e0fba",
      "name": "Saffron Rice",
      "image": "42a7b39e0fba.webp",
      "added_at": "2026-10-05T14:00:00Z"
    }
  ]
  ```
- **Git Ignore**: Added to `.gitignore` so local selection state is never committed to git or leaked to GitHub.

### 4.4. CLI Regeneration Integration (`scripts/gen_images.py`)
- Add `--from-queue [FILE]` flag to `scripts/gen_images.py` (defaulting to `data/redraw_queue.json`).
- When `--from-queue` is passed:
  - Loads queued dish IDs.
  - Forces redraw (`args.force = True`) for matching dishes.
  - Optionally clears or prompts to clear the queue once successfully generated.

---

## 5. Security & Isolation Verification

1. **Production Purity Test**:
   - Automated unit test verifying that running `build()` produces `site/index.html` with zero occurrences of `bsdm-redraw-overlay`, `redraw-queue`, or overlay code.
   - Verifies `git status` on `web/` remains unmodified.
2. **Server API Tests**:
   - Tests `GET`, `POST`, and `clear` on `/api/redraw-queue` with mock requests, checking atomic file persistence.
   - Tests HTML response injection ensures valid HTML structure.

---

## 6. Implementation Steps

1. Create `scripts/overlay/overlay.css` and `scripts/overlay/overlay.js`.
2. Create `scripts/serve.py` with dynamic injection and `/api/redraw-queue` endpoints.
3. Update `Makefile` `serve` target to use `scripts/serve.py`.
4. Update `.gitignore` to ignore `data/redraw_queue.json`.
5. Update `scripts/gen_images.py` with `--from-queue` support.
6. Add automated unit tests in `tests/test_redraw_overlay.py`.
7. Verify end-to-end locally with `make serve` and `make test`.
