(() => {
  "use strict";

  const DATA = JSON.parse(document.getElementById("menu-data").textContent);
  const MEALS = ["Breakfast", "Lunch", "Dinner"];
  const STORE = "bsdm.prefs.v3";

  const DIET = [
    { key: "vegetarian", label: "Vegetarian", cls: "badge-v", short: "VEG" },
    { key: "vegan", label: "Vegan", cls: "badge-vgn", short: "VEGAN" },
    { key: "gluten-free", label: "Gluten-free", cls: "badge-gf", short: "GF" },
    { key: "halal", label: "Halal", cls: "badge-halal", short: "HALAL" },
    { key: "kosher", label: "Kosher", cls: "badge-kosher", short: "KOSHER" },
  ];

  const PROTEIN = {
    beef: "Beef", pork: "Pork", poultry: "Poultry", seafood: "Seafood", lamb: "Lamb",
  };

  const ICONS = {
    soup: "🍲", grill: "🔥", sandwich: "🥪", salad: "🥗", bread: "🍞",
    pizza: "🍕", dessert: "🍰", pasta: "🍝", plate: "🍽️",
  };

  const hallById = new Map(DATA.halls.map((h) => [h.id, h]));

  // Derived from the viewer's clock, not from build time: the site is rebuilt
  // daily but a tab left open overnight must not keep calling yesterday "Today".
  const isoLocal = (d) => d.toLocaleDateString("en-CA");
  const TODAY = isoLocal(new Date());
  const TOMORROW = isoLocal(new Date(Date.now() + 86400000));

  // ---------- preferences ----------

  const fallback = {
    halls: DATA.defaults.selected.slice(),
    date: DATA.window.includes(TODAY) ? TODAY : DATA.window[0],
    meal: "Dinner",
    diet: [],
    meatFirst: true,
    photos: true,
    stations: true,
    theme: "auto",
  };

  function load() {
    try {
      return { ...fallback, ...JSON.parse(localStorage.getItem(STORE) || "{}") };
    } catch {
      return { ...fallback };
    }
  }

  function save() {
    try {
      localStorage.setItem(STORE, JSON.stringify(state));
    } catch {
      /* private browsing or blocked storage -- preferences just don't persist */
    }
  }

  const state = load();

  // A stored date falls out of the rolling 7-day window within a week.
  if (!DATA.window.includes(state.date)) state.date = fallback.date;
  state.halls = state.halls.filter((id) => hallById.has(id));
  if (!state.halls.length) state.halls = DATA.defaults.selected.slice();

  // ---------- helpers ----------

  const el = (tag, props = {}, kids = []) => {
    const node = Object.assign(document.createElement(tag), props);
    for (const kid of [].concat(kids)) {
      if (kid != null) node.append(kid);
    }
    return node;
  };

  const fmtTime = (hhmm) => {
    const [h, m] = hhmm.split(":").map(Number);
    const suffix = h < 12 || h === 24 ? "am" : "pm";
    const hour = h % 12 === 0 ? 12 : h % 12;
    return m ? `${hour}:${String(m).padStart(2, "0")}${suffix}` : `${hour}${suffix}`;
  };

  const dayLabel = (iso) => {
    if (iso === TODAY) return "Today";
    if (iso === TOMORROW) return "Tomorrow";
    return new Date(iso + "T12:00:00").toLocaleDateString(undefined, { weekday: "short" });
  };

  const dayFull = (iso) =>
    new Date(iso + "T12:00:00").toLocaleDateString(undefined, {
      weekday: "long", month: "long", day: "numeric",
    });

  /** Resolve a menu entry ("<dishId>.<variantIndex>") to a display record. */
  function resolve(ref) {
    const dot = ref.lastIndexOf(".");
    const id = ref.slice(0, dot);
    return { id, ...DATA.dishes[id], ...DATA.dishes[id].v[Number(ref.slice(dot + 1))] };
  }

  const EMPTY = { daily: [], stations: [] };

  function service(date, hallId, meal) {
    return ((DATA.menus[date] || {})[hallId] || {})[meal] || EMPTY;
  }

  /** Meals any selected hall serves that day, in breakfast..dinner order. */
  function availableMeals(date) {
    const seen = new Set();
    for (const hallId of state.halls) {
      for (const meal of Object.keys((DATA.menus[date] || {})[hallId] || {})) seen.add(meal);
    }
    return MEALS.filter((m) => seen.has(m));
  }

  function hoursFor(date, hallId, meal) {
    return ((DATA.hours[date] || {})[hallId] || {})[meal] || null;
  }

  /** open | soon | shut | null, compared against the viewer's clock. */
  function serviceStatus(date, span) {
    if (!span || date !== TODAY) return null;
    const now = new Date();
    const minutes = now.getHours() * 60 + now.getMinutes();
    const toMin = (s) => {
      const [h, m] = s.split(":").map(Number);
      return h * 60 + m;
    };
    const [open, close] = [toMin(span[0]), toMin(span[1])];
    if (minutes >= open && minutes <= close) return "open";
    if (open - minutes > 0 && open - minutes <= 90) return "soon";
    return "shut";
  }

  function matchesDiet(rec) {
    return state.diet.every((d) => rec.tags.includes(d));
  }

  function badgesFor(rec, onlyHere) {
    const badges = el("div", { className: "badges" });
    if (onlyHere) {
      badges.append(el("span", { className: "badge badge-only", textContent: "ONLY HERE" }));
    }
    if (PROTEIN[rec.category]) {
      badges.append(el("span", {
        className: "badge badge-protein",
        textContent: PROTEIN[rec.category].toUpperCase(),
      }));
    }
    for (const d of DIET) {
      if (rec.tags.includes(d.key)) {
        badges.append(el("span", { className: "badge " + d.cls, textContent: d.short }));
      }
    }
    return badges;
  }

  function detailsFor(rec) {
    const out = [];
    if (rec.alg && rec.alg.length) {
      const line = el("p", { className: "allergens" });
      line.append(el("b", { textContent: "Allergens: " }), rec.alg.join(", "));
      out.push(line);
    }
    if (rec.placeholder) {
      out.push(el("p", {
        className: "placeholder-note",
        textContent: "Changes daily — ask at the counter.",
      }));
    } else if (rec.ing) {
      const more = el("details", { className: "more" }, [
        el("summary", { textContent: "Ingredients" }),
        el("p", { className: "ingredients", textContent: rec.ing }),
      ]);
      if (rec.trace && rec.trace.length) {
        more.append(el("p", {
          className: "ingredients",
          textContent: "Shared equipment with: " + rec.trace.join(", "),
        }));
      }
      out.push(more);
    }
    return out;
  }

  // ---------- rendering ----------

  /** A dish cooked today. Name leads, so the list is readable before any image loads. */
  function dishCard(rec, onlyHere) {
    const card = el("article", {
      className: "card" + (PROTEIN[rec.category] ? " card-meat" : ""),
    });

    const head = el("div", { className: "card-head" }, [
      el("h3", { className: "dish-name", textContent: rec.name }),
    ]);
    const badges = badgesFor(rec, onlyHere);
    if (badges.childElementCount) head.append(badges);
    card.append(head);

    if (state.photos) {
      if (rec.image) {
        card.append(el("img", {
          className: "thumb",
          src: "img/" + rec.image,
          alt: rec.name,
          loading: "lazy",
          decoding: "async",
          width: 1024,
          height: 576,
        }));
      } else {
        card.append(el("div", {
          className: "thumb-none",
          title: rec.placeholder
            ? "This entry changes daily, so it is deliberately not illustrated."
            : "No image generated for this dish yet.",
        }, [
          el("span", { className: "glyph", textContent: ICONS[rec.icon] || ICONS.plate }),
          rec.placeholder ? "Varies daily" : "Image pending",
        ]));
      }
    }

    const detail = detailsFor(rec);
    if (detail.length) card.append(el("div", { className: "card-body" }, detail));
    return card;
  }

  /** A counter that is there every day. Rendered dense: it is not the news. */
  function stationRow(rec, onlyHere) {
    const row = el("div", { className: "station" }, [
      el("span", { className: "station-name", textContent: rec.name }),
    ]);
    const badges = badgesFor(rec, onlyHere);
    if (badges.childElementCount) row.append(badges);

    const detail = detailsFor(rec);
    if (!detail.length) return row;

    return el("details", { className: "station-wrap" }, [
      el("summary", {}, [row]),
      el("div", { className: "station-detail" }, detail),
    ]);
  }

  function render() {
    document.documentElement.dataset.theme = state.theme;
    renderControls();

    const board = document.getElementById("board");
    board.replaceChildren();

    const meals = availableMeals(state.date);
    if (meals.length && !meals.includes(state.meal)) state.meal = meals[meals.length - 1];

    // A dish shown by exactly one selected hall is the reason to walk there.
    // Counted over the day's menu only: every hall has a salad bar.
    const spread = new Map();
    for (const hallId of state.halls) {
      for (const ref of service(state.date, hallId, state.meal).daily) {
        const id = ref.slice(0, ref.lastIndexOf("."));
        spread.set(id, (spread.get(id) || 0) + 1);
      }
    }

    for (const hallId of state.halls) board.append(column(hallId, spread));

    renderDigest(spread);
    document.getElementById("stamp").textContent = `${dayFull(state.date)} · ${state.meal}`;
    save();
  }

  /** How much the selected halls actually differ -- the whole point of comparing. */
  function renderDigest(spread) {
    const node = document.getElementById("digest");
    const serving = state.halls.filter((h) => service(state.date, h, state.meal).daily.length);
    if (serving.length < 2) {
      node.replaceChildren();
      return;
    }

    const total = spread.size;
    const everywhere = [...spread.values()].filter((n) => n === serving.length).length;
    const unique = [...spread.values()].filter((n) => n === 1).length;

    node.replaceChildren(
      el("b", { textContent: String(total) }),
      ` dishes on today's menu across ${serving.length} halls · `,
      el("b", { textContent: String(everywhere) }),
      " at every one · ",
      el("b", { textContent: String(unique) }),
      " at only one.",
    );
    if (unique === 0) {
      node.append(" ", el("span", {
        className: "warn",
        textContent: "These menus are identical — go wherever is closest.",
      }));
    }
  }

  function column(hallId, spread) {
    const hall = hallById.get(hallId);
    const col = el("section", { className: "column" });
    col.style.setProperty("--hall", hall.accent);

    const svc = service(state.date, hallId, state.meal);
    let daily = svc.daily.map(resolve).filter(matchesDiet);
    const stations = svc.stations.map(resolve).filter(matchesDiet);

    if (state.meatFirst) {
      daily = daily
        .map((r, i) => [r, i])
        .sort((a, b) => (PROTEIN[b[0].category] ? 1 : 0) - (PROTEIN[a[0].category] ? 1 : 0)
          || a[1] - b[1])
        .map(([r]) => r);
    }

    const span = hoursFor(state.date, hallId, state.meal);
    const status = serviceStatus(state.date, span);

    const head = el("header", { className: "col-head" }, [
      el("h2", { className: "col-name", textContent: hall.short }),
    ]);
    if (hall.concept) {
      head.append(el("p", { className: "col-concept", textContent: hall.concept }));
    }

    const meta = el("div", { className: "col-meta" });
    if (span) {
      meta.append(el("span", {
        className: "hours",
        textContent: `${fmtTime(span[0])} – ${fmtTime(span[1])}`,
      }));
    }
    if (status) {
      meta.append(el("span", {
        className: `pill pill-${status}`,
        textContent: { open: "Open now", soon: "Opens soon", shut: "Closed" }[status],
      }));
    }
    meta.append(el("span", {
      className: "count",
      textContent: `${daily.length} on the menu`,
    }));
    const onlyHere = daily.filter((r) => spread.get(r.id) === 1).length;
    if (onlyHere) {
      meta.append(el("span", { className: "only-count", textContent: `${onlyHere} only here` }));
    }
    if (hall.address) {
      meta.append(el("a", {
        className: "maplink",
        href: "https://maps.google.com/?q=" + encodeURIComponent(hall.address),
        target: "_blank",
        rel: "noopener",
        textContent: "map",
      }));
    }
    head.append(meta);
    col.append(head);

    if (!svc.daily.length && !svc.stations.length) {
      col.append(el("div", {
        className: "empty",
        textContent: `No ${state.meal.toLowerCase()} service here on ${dayLabel(state.date)}.`,
      }));
      return col;
    }

    if (!daily.length) {
      col.append(el("div", {
        className: "empty",
        textContent: state.diet.length
          ? "Nothing on today's menu matches the filters."
          : "Nothing specific listed for today.",
      }));
    } else {
      for (const rec of daily) col.append(dishCard(rec, spread.get(rec.id) === 1));
    }

    if (stations.length) {
      const wrap = el("section", { className: "stations" });
      const head = el("div", { className: "stations-head" }, [
        el("span", { className: "stations-title", textContent: "Always here" }),
        el("span", { className: "stations-count", textContent: String(stations.length) }),
      ]);
      const toggle = el("button", {
        className: "stations-toggle",
        type: "button",
        textContent: state.stations ? "hide" : "show",
      });
      toggle.addEventListener("click", () => {
        state.stations = !state.stations;
        render();
      });
      head.append(toggle);
      wrap.append(head);

      if (state.stations) {
        const list = el("div", { className: "station-list" });
        for (const rec of stations) list.append(stationRow(rec, false));
        wrap.append(list);
      }
      col.append(wrap);
    }

    return col;
  }

  // ---------- controls ----------

  function chip(label, pressed, onClick, extra = {}) {
    const b = el("button", {
      className: "chip" + (extra.className ? " " + extra.className : ""),
      type: "button",
      ...extra.props,
    });
    b.setAttribute("aria-pressed", String(pressed));
    b.append(label);
    if (extra.sub) b.append(el("span", { className: "sub", textContent: extra.sub }));
    if (extra.accent) b.style.setProperty("--hall", extra.accent);
    b.addEventListener("click", onClick);
    return b;
  }

  function renderControls() {
    document.getElementById("days").replaceChildren(...DATA.window.map((iso) =>
      chip(dayLabel(iso), iso === state.date, () => {
        state.date = iso;
        render();
      }, { sub: iso.slice(5).replace("-", "/") })));

    const meals = availableMeals(state.date);
    document.getElementById("meals").replaceChildren(...MEALS.map((m) =>
      chip(m, m === state.meal, () => {
        state.meal = m;
        render();
      }, { props: { disabled: !meals.includes(m) } })));

    document.getElementById("halls").replaceChildren(...DATA.halls.map((h) =>
      chip(h.short, state.halls.includes(h.id), () => {
        const i = state.halls.indexOf(h.id);
        if (i >= 0) state.halls.splice(i, 1);
        else state.halls.push(h.id);
        if (!state.halls.length) state.halls.push(h.id);
        render();
      }, { className: "chip-hall", accent: h.accent })));

    document.getElementById("diet").replaceChildren(
      ...DIET.map((d) =>
        chip(d.label, state.diet.includes(d.key), () => {
          const i = state.diet.indexOf(d.key);
          if (i >= 0) state.diet.splice(i, 1);
          else state.diet.push(d.key);
          render();
        })),
      chip("Meat first", state.meatFirst, () => {
        state.meatFirst = !state.meatFirst;
        render();
      }, { className: "chip-ghost" }),
      chip("Photos", state.photos, () => {
        state.photos = !state.photos;
        render();
      }, { className: "chip-ghost" }),
      chip("Reset", false, () => {
        try {
          localStorage.removeItem(STORE);
        } catch { /* storage blocked; the in-memory reset below still applies */ }
        Object.assign(state, structuredClone(fallback));
        render();
      }, { className: "chip-ghost" }),
    );

    document.getElementById("theme").textContent =
      { auto: "◐ Auto", light: "☀ Light", dark: "☾ Dark" }[state.theme];
  }

  document.getElementById("theme").addEventListener("click", () => {
    state.theme = { auto: "light", light: "dark", dark: "auto" }[state.theme];
    render();
  });

  // Left/right arrows step through the week.
  document.addEventListener("keydown", (e) => {
    if (e.target.matches("input, textarea, select")) return;
    const i = DATA.window.indexOf(state.date);
    if (e.key === "ArrowLeft" && i > 0) {
      state.date = DATA.window[i - 1];
      render();
    } else if (e.key === "ArrowRight" && i < DATA.window.length - 1) {
      state.date = DATA.window[i + 1];
      render();
    }
  });

  render();
})();
