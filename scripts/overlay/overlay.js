// Local Redraw Selection Overlay (Zero-Leak Dev Tool)
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
      const res = await fetch('/api/redraw-queue');
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
      const res = await fetch('/api/redraw-queue', {
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
      await fetch('/api/redraw-queue/clear', { method: "POST" });
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
    const stateStr = isSelected ? "selected" : "unselected";
    if (btn.dataset.state === stateStr) return;
    btn.dataset.state = stateStr;

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
          listEl.replaceChildren();
          Array.from(queueMap.values()).forEach((item) => {
            const itemEl = document.createElement("div");
            itemEl.className = "redraw-drawer-item";

            const titleEl = document.createElement("span");
            titleEl.className = "redraw-drawer-item-title";
            titleEl.title = item.name;
            titleEl.textContent = item.name;

            const removeBtn = document.createElement("button");
            removeBtn.type = "button";
            removeBtn.className = "redraw-drawer-item-remove";
            removeBtn.title = "移除";
            removeBtn.textContent = "×";
            removeBtn.dataset.id = item.id;
            removeBtn.addEventListener("click", () => {
              toggleDishOnServer(item);
            });

            itemEl.appendChild(titleEl);
            itemEl.appendChild(removeBtn);
            listEl.appendChild(itemEl);
          });
        }
      }
    }
  }

  function init() {
    createDock();
    fetchQueue();

    const board = document.getElementById("board") || document.body;
    const observer = new MutationObserver(() => {
      observer.disconnect();
      syncAllCards();
      observer.observe(board, { childList: true, subtree: true });
    });

    // Initial sync
    syncAllCards();

    // Observe board updates when user switches date/meal/halls
    observer.observe(board, { childList: true, subtree: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
