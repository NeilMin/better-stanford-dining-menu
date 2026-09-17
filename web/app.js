(() => {
  "use strict";

  const DATA = JSON.parse(document.getElementById("menu-data").textContent);
  const MEALS = ["Breakfast", "Lunch", "Dinner"];
  // v4 added `lang` to the persisted shape.
  const STORE = "bsdm.prefs.v4";

  const DIET = [
    { key: "vegetarian", label: "Vegetarian", zh: "素食", cls: "badge-v", short: "VEG", shortZh: "素" },
    { key: "vegan", label: "Vegan", zh: "纯素", cls: "badge-vgn", short: "VEGAN", shortZh: "纯素" },
    { key: "gluten-free", label: "Gluten-free", zh: "无麸质", cls: "badge-gf", short: "GF", shortZh: "无麸质" },
    { key: "halal", label: "Halal", zh: "清真", cls: "badge-halal", short: "HALAL", shortZh: "清真" },
    { key: "kosher", label: "Kosher", zh: "洁食", cls: "badge-kosher", short: "KOSHER", shortZh: "洁食" },
  ];

  const PROTEIN = {
    beef: "Beef", pork: "Pork", poultry: "Poultry", seafood: "Seafood", lamb: "Lamb",
  };
  const PROTEIN_ZH = {
    beef: "牛肉", pork: "猪肉", poultry: "禽肉", seafood: "海鲜", lamb: "羊肉",
  };

  const MEAL_ZH = { Breakfast: "早餐", Lunch: "午餐", Dinner: "晚餐", Brunch: "早午餐" };

  // R&DE's allergen codes. Anything not listed shows as it came.
  const ALLERGEN_ZH = {
    MILK: "奶", EGG: "蛋", WHEAT: "小麦", SOY: "大豆", FISH: "鱼", SHELLFISH: "贝类",
    SESAME: "芝麻", COCONUT: "椰子", PEANUT: "花生", TREENUT: "坚果",
    TRACEALLERGENS: "微量过敏原",
  };

  const ICONS = {
    soup: "🍲", grill: "🔥", sandwich: "🥪", salad: "🥗", bread: "🍞",
    pizza: "🍕", dessert: "🍰", pasta: "🍝", plate: "🍽️",
  };

  // ---------- language ----------
  //
  // English is the default because the menus, and the signs at the counters,
  // are in English. So Chinese mode does not replace a dish name, it adds one:
  // the Chinese name is what you read, the English line under it is what you
  // match against the sign. Ingredients, allergens and the interface have no
  // sign to match against, so those are replaced outright.
  const UI = {
    en: {
      langChip: "中文",
      langLabel: "切换到中文",
      docTitle: "Stanford Dining, Side by Side",
      brandA: "Stanford Dining, ",
      brandB: "Side by Side",
      lblDay: "Day", lblMeal: "Meal", lblHalls: "Halls", lblFilter: "Filter",
      today: "Today", tomorrow: "Tomorrow",
      meal: (m) => m,
      diet: (d) => d.label,
      dietShort: (d) => d.short,
      protein: (c) => PROTEIN[c].toUpperCase(),
      onlyHere: "ONLY HERE",
      meatFirst: "Meat first", photos: "Photos", reset: "Reset",
      theme: (mode) => ({ auto: "◐ Auto", light: "☀ Light", dark: "☾ Dark" }[mode]),
      status: (s) => ({ open: "Open now", soon: "Opens soon", shut: "Closed" }[s]),
      count: (n) => `${n} on the menu`,
      onlyCount: (n) => `${n} only here`,
      map: "map",
      special: "Special",
      specialBadge: "★ SPECIAL",
      specialTip: (meal) => `${meal} special, from R&DE's specials calendar`,
      specialNote: "Limited-time special from R&DE's calendar. No ingredient list published — ask at the counter.",
      alwaysHere: "Always here",
      toggle: (shown) => (shown ? "hide" : "show"),
      allergens: "Allergens: ",
      allergenList: (list) => list.join(", "),
      ingredients: "Ingredients",
      traces: (list) => "Shared equipment with: " + list.join(", "),
      varies: "Changes daily — ask at the counter.",
      variesShort: "Varies daily",
      variesTip: "This entry changes daily, so it is deliberately not illustrated.",
      pending: "Image pending",
      pendingTip: "No image generated for this dish yet.",
      noService: (meal, day) => `No ${meal.toLowerCase()} service here on ${day}.`,
      noMatch: "Nothing on today's menu matches the filters.",
      noneListed: "Nothing specific listed for today.",
      digest: (b, total, halls, every, unique) => [
        b(total), ` dishes on today's menu across ${halls} halls · `,
        b(every), " at every one · ", b(unique), " at only one.",
      ],
      identical: "These menus are identical — go wherever is closest.",
      footerSrc: (a, built) => [
        "Menus scraped from the ",
        a("https://rdeapps.stanford.edu/dininghallmenu/", "R&DE Dining Hall Menu"),
        "; hours and addresses from ",
        a("https://rde.stanford.edu/dining-hospitality/dining-locations-hours",
          "Dining Locations & Hours"),
        `. Built ${built}. `,
        a("https://github.com/NeilMin/better-stanford-dining-menu", "Source on GitHub"),
        ".",
      ],
      footerNote: (strong) => [
        strong("Dish photographs are AI-generated from each dish's name and ingredient list."),
        " They illustrate what a dish usually looks like and are not photographs of the food " +
        "being served. Allergen and ingredient text is reproduced from R&DE and is subject to " +
        "change without notice — if you have an allergy, confirm at the hall.",
      ],
    },
    zh: {
      langChip: "English",
      langLabel: "Switch to English",
      docTitle: "斯坦福食堂 · 并排比较",
      brandA: "斯坦福食堂，",
      brandB: "并排比较",
      lblDay: "日期", lblMeal: "餐别", lblHalls: "食堂", lblFilter: "筛选",
      today: "今天", tomorrow: "明天",
      meal: (m) => MEAL_ZH[m] || m,
      diet: (d) => d.zh,
      dietShort: (d) => d.shortZh,
      protein: (c) => PROTEIN_ZH[c] || PROTEIN[c],
      onlyHere: "只此一家",
      meatFirst: "荤菜优先", photos: "图片", reset: "重置",
      theme: (mode) => ({ auto: "◐ 自动", light: "☀ 浅色", dark: "☾ 深色" }[mode]),
      status: (s) => ({ open: "供应中", soon: "即将开始", shut: "已结束" }[s]),
      count: (n) => `菜单 ${n} 道`,
      onlyCount: (n) => `${n} 道独有`,
      map: "地图",
      special: "特供",
      specialBadge: "★ 特供",
      specialTip: (meal) => `${meal}限时特供，来自 R&DE 的特供日历`,
      specialNote: "R&DE 特供日历上的限时特供，没有公布配料——过敏请到窗口确认。",
      alwaysHere: "常设窗口",
      toggle: (shown) => (shown ? "收起" : "展开"),
      allergens: "过敏原：",
      allergenList: (list) => list.map((a) => ALLERGEN_ZH[a] || a).join("、"),
      ingredients: "配料",
      traces: (list) => "与这些共用设备：" + list.map((a) => ALLERGEN_ZH[a] || a).join("、"),
      varies: "每天不一样，到窗口问一下。",
      variesShort: "每日不同",
      variesTip: "这一项每天都换，所以刻意不配图。",
      pending: "图片待生成",
      pendingTip: "这道菜还没有生成图片。",
      noService: (meal, day) => `${day}这里不供应${MEAL_ZH[meal] || meal}。`,
      noMatch: "今天没有符合筛选条件的菜。",
      noneListed: "今天没有列出具体菜品。",
      digest: (b, total, halls, every, unique) => [
        `${halls} 家食堂今天一共 `, b(total), " 道菜 · ",
        b(every), " 道每家都有 · ", b(unique), " 道只此一家。",
      ],
      identical: "这几家菜单完全一样——去最近的那家就行。",
      footerSrc: (a, built) => [
        "菜单抓取自 ",
        a("https://rdeapps.stanford.edu/dininghallmenu/", "R&DE 餐厅菜单"),
        "，营业时间和地址来自 ",
        a("https://rde.stanford.edu/dining-hospitality/dining-locations-hours",
          "Dining Locations & Hours"),
        `。构建于 ${built}。`,
        "源代码见 ",
        a("https://github.com/NeilMin/better-stanford-dining-menu", "GitHub"),
        "。",
      ],
      footerNote: (strong) => [
        strong("菜品照片由 AI 根据菜名和配料表生成。"),
        "它们画的是这道菜通常的样子，不是当天出餐的实拍。" +
        "过敏原和配料信息转载自 R&DE，可能随时变动——如果你对某种食物过敏，请到餐厅当面确认。",
      ],
      // Dish names and ingredients are translated offline into data/zh.json;
      // anything that run has not reached yet stays English on the page.
    },
  };

  /** A string from the table for the current language; arguments fill it in. */
  const t = (key, ...args) => {
    const value = (UI[state.lang] || UI.en)[key];
    return typeof value === "function" ? value(...args) : value;
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
    lang: "en",
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
  if (!UI[state.lang]) state.lang = fallback.lang;

  // ---------- helpers ----------

  const el = (tag, props = {}, kids = []) => {
    const node = Object.assign(document.createElement(tag), props);
    for (const kid of [].concat(kids)) {
      if (kid != null) node.append(kid);
    }
    return node;
  };

  const locale = () => (state.lang === "zh" ? "zh-CN" : undefined);

  const fmtTime = (hhmm) => {
    // Chinese dining hours are written on a 24-hour clock, which the stored
    // "17:00" already is.
    if (state.lang === "zh") return hhmm.replace(/^0/, "");
    const [h, m] = hhmm.split(":").map(Number);
    const suffix = h < 12 || h === 24 ? "am" : "pm";
    const hour = h % 12 === 0 ? 12 : h % 12;
    return m ? `${hour}:${String(m).padStart(2, "0")}${suffix}` : `${hour}${suffix}`;
  };

  const dayLabel = (iso) => {
    if (iso === TODAY) return t("today");
    if (iso === TOMORROW) return t("tomorrow");
    return new Date(iso + "T12:00:00").toLocaleDateString(locale(), { weekday: "short" });
  };

  const dayFull = (iso) =>
    new Date(iso + "T12:00:00").toLocaleDateString(locale(), {
      weekday: "long", month: "long", day: "numeric",
    });

  // ---------- Chinese ingredient lists ----------

  const ZH_TERMS = new Map(Object.entries(DATA.zh_terms || {}));
  const ZH_PUNCT = new Map([
    [",", "、"], ["(", "（"], [")", "）"], ["[", "（"], ["]", "）"],
  ]);

  /** Rebuild an ingredient list in Chinese, term by term.
   *
   * Mirrors bsdm/zh.py, which has to split the same way to know which terms to
   * offer for translation: same separators, same lookup key. A term the table
   * has never seen keeps its English, which reads as one stray word in a
   * Chinese list rather than as a hole in it.
   */
  function zhIngredients(text) {
    let out = "";
    for (const piece of text.split(/([,()\[\]])/)) {
      const punct = ZH_PUNCT.get(piece);
      if (punct !== undefined) {
        out += punct;
        continue;
      }
      const term = piece.replace(/\s+/g, " ").trim();
      if (term) out += ZH_TERMS.get(term.toLowerCase()) || term;
    }
    return out;
  }

  const ingredientText = (text) => (state.lang === "zh" ? zhIngredients(text) : text);

  /** The Chinese name to lead a dish with, or null to lead with the English. */
  const zhName = (rec) => (state.lang === "zh" && rec.zh) || null;

  /** Resolve a menu entry ("<dishId>.<variantIndex>") to a display record. */
  function resolve(ref) {
    const dot = ref.lastIndexOf(".");
    const id = ref.slice(0, dot);
    return { id, ...DATA.dishes[id], ...DATA.dishes[id].v[Number(ref.slice(dot + 1))] };
  }

  const EMPTY = { specials: [], daily: [], stations: [] };

  /** What the specials calendar says to the whole campus, for this date.
   *
   *  Guarded on the meal: the calendar is a dinner calendar, and a dinner
   *  notice has no business on the lunch board. A hall's own specials need no
   *  guard -- the build files them under the calendar's meal already.
   */
  function noticesFor(date) {
    const day = DATA.notices[date];
    if (!day || day.meal !== state.meal) return [];
    return day.notes || [];
  }

  /** Chinese for a notice, or English if it has not been translated yet. */
  function zhSpecial(text) {
    return state.lang === "zh" ? DATA.zh_specials[text] || null : null;
  }

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

  function badgesFor(rec, onlyHere, special = false) {
    const badges = el("div", { className: "badges" });
    if (special) {
      badges.append(el("span", { className: "badge badge-special", textContent: t("specialBadge") }));
    }
    if (onlyHere) {
      badges.append(el("span", { className: "badge badge-only", textContent: t("onlyHere") }));
    }
    if (PROTEIN[rec.category]) {
      badges.append(el("span", {
        className: "badge badge-protein",
        textContent: t("protein", rec.category),
      }));
    }
    for (const d of DIET) {
      if (rec.tags.includes(d.key)) {
        badges.append(el("span", { className: "badge " + d.cls, textContent: t("dietShort", d) }));
      }
    }
    return badges;
  }

  function detailsFor(rec, special = false) {
    const out = [];
    // The poster names the dish and nothing else. Saying so is better than an
    // empty body that reads as "no allergens".
    if (special && !rec.ing) {
      out.push(el("p", { className: "special-note", textContent: t("specialNote") }));
    }
    if (rec.alg && rec.alg.length) {
      const line = el("p", { className: "allergens" });
      line.append(el("b", { textContent: t("allergens") }), t("allergenList", rec.alg));
      out.push(line);
    }
    if (rec.placeholder) {
      out.push(el("p", { className: "placeholder-note", textContent: t("varies") }));
    } else if (rec.ing) {
      const more = el("details", { className: "more" }, [
        el("summary", { textContent: t("ingredients") }),
        el("p", { className: "ingredients", textContent: ingredientText(rec.ing) }),
      ]);
      if (rec.trace && rec.trace.length) {
        more.append(el("p", { className: "ingredients", textContent: t("traces", rec.trace) }));
      }
      out.push(more);
    }
    return out;
  }

  // ---------- rendering ----------

  /** A dish cooked today. Name leads, so the list is readable before any image loads.
   *  A special is the same card, marked out: it is the dish you walk over for. */
  function dishCard(rec, onlyHere, special = false) {
    const card = el("article", {
      className: "card" + (PROTEIN[rec.category] ? " card-meat" : "") +
        (special ? " card-special" : ""),
    });
    if (special) card.title = t("specialTip", t("meal", state.meal));

    const zh = zhName(rec);
    const head = el("div", { className: "card-head" }, [
      el("h3", { className: "dish-name", textContent: zh || rec.name }),
    ]);
    // Bilingual, not translated: the counter's sign still says "Magnolia Boil".
    if (zh) head.append(el("p", { className: "dish-name-en", textContent: rec.name }));
    // Appended even when empty: the badge row is reserved space in the
    // stylesheet, so a dish with no tags keeps the same card as the one beside
    // it in the next hall.
    head.append(badgesFor(rec, onlyHere, special));
    card.append(head);

    if (state.photos) {
      if (rec.image) {
        card.append(el("img", {
          className: "thumb",
          src: "img/" + rec.image,
          alt: zh || rec.name,
          loading: "lazy",
          decoding: "async",
          width: 1024,
          height: 576,
        }));
      } else {
        card.append(el("div", {
          className: "thumb-none",
          title: rec.placeholder ? t("variesTip") : t("pendingTip"),
        }, [
          el("span", { className: "glyph", textContent: ICONS[rec.icon] || ICONS.plate }),
          rec.placeholder ? t("variesShort") : t("pending"),
        ]));
      }
    }

    // Likewise: a dish that lists no allergens still gets the body, which
    // reserves that line.
    card.append(el("div", { className: "card-body" }, detailsFor(rec, special)));
    return card;
  }

  /** A counter that is there every day. Rendered dense: it is not the news. */
  function stationRow(rec, onlyHere) {
    const zh = zhName(rec);
    const row = el("div", { className: "station" }, [
      el("span", { className: "station-name", textContent: zh || rec.name }),
    ]);
    if (zh) row.append(el("span", { className: "station-name-en", textContent: rec.name }));
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
    renderChrome();
    renderControls();

    const board = document.getElementById("board");
    board.replaceChildren();

    const meals = availableMeals(state.date);
    if (meals.length && !meals.includes(state.meal)) state.meal = meals[meals.length - 1];

    // A dish shown by exactly one selected hall is the reason to walk there.
    // Counted over the day's menu only: every hall has a salad bar.
    const spread = new Map();
    for (const hallId of state.halls) {
      const svc = service(state.date, hallId, state.meal);
      for (const ref of [...svc.specials, ...svc.daily]) {
        const id = ref.slice(0, ref.lastIndexOf("."));
        spread.set(id, (spread.get(id) || 0) + 1);
      }
    }

    for (const hallId of state.halls) board.append(column(hallId, spread));

    // The columns are laid on the board's own rows so that the slots line up
    // across the halls (.board, in the stylesheet). The deepest column decides
    // how many rows there are: one for the header, one per card, and a last one
    // for the standing counters to run into.
    let cards = 1;
    let standing = false;
    for (const col of board.children) {
      const tail = col.lastElementChild.classList.contains("stations");
      if (tail) standing = true;
      cards = Math.max(cards, col.childElementCount - 1 - (tail ? 1 : 0));
    }
    board.style.setProperty("--rows", String(1 + cards + (standing ? 1 : 0)));

    renderDigest(spread);
    renderNotices();
    document.getElementById("stamp").textContent =
      `${dayFull(state.date)} · ${t("meal", state.meal)}`;
    save();
  }

  /** How much the selected halls actually differ -- the whole point of comparing. */
  function renderDigest(spread) {
    const node = document.getElementById("digest");
    const serving = state.halls.filter((h) => {
      const svc = service(state.date, h, state.meal);
      return svc.specials.length || svc.daily.length;
    });
    if (serving.length < 2) {
      node.replaceChildren();
      return;
    }

    const total = spread.size;
    const everywhere = [...spread.values()].filter((n) => n === serving.length).length;
    const unique = [...spread.values()].filter((n) => n === 1).length;

    const bold = (n) => el("b", { textContent: String(n) });
    node.replaceChildren(...t("digest", bold, total, serving.length, everywhere, unique));
    if (unique === 0) {
      node.append(" ", el("span", { className: "warn", textContent: t("identical") }));
    }
  }

  /** Whatever the specials calendar says to the whole campus at once. */
  function renderNotices() {
    const node = document.getElementById("notices");
    const notes = noticesFor(state.date);
    node.replaceChildren(...notes.map((text) => {
      const zh = zhSpecial(text);
      const line = el("p", { className: "notice" }, [
        el("span", { className: "special-tag", textContent: t("special") }),
        el("span", { textContent: zh || text }),
      ]);
      if (zh) line.append(el("span", { className: "special-en", textContent: text }));
      return line;
    }));
  }

  // The logos run from Branner's roundel, taller than it is wide, to Lakeside's
  // 5:1 wordmark. One height for all of them makes the wordmarks run long and
  // one width makes the roundels tower, so the height gives way to the aspect
  // ratio part of the way: a wide logo gets shorter but not so short that its
  // lettering goes illegible. Capped so no logo pushes into the name.
  const LOGO = { h: 38, give: 0.45, maxW: 80, maxH: 36 };
  function logoSize(ratio) {
    let h = Math.min(LOGO.h / ratio ** LOGO.give, LOGO.maxH);
    let w = h * ratio;
    if (w > LOGO.maxW) { w = LOGO.maxW; h = w / ratio; }
    return [Math.round(w), Math.round(h)];
  }

  function column(hallId, spread) {
    const hall = hallById.get(hallId);
    const col = el("section", { className: "column" });
    col.style.setProperty("--hall", hall.accent);

    const svc = service(state.date, hallId, state.meal);
    // Specials lead, whatever the sort: meat-first reorders the rest only.
    const specials = svc.specials.map(resolve).filter(matchesDiet);
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

    // Beside the name rather than above it, so the logo costs no height of its
    // own. The slot is appended whether or not this hall has a logo: it holds
    // the header's top line to one height, so a missing logo cannot lift this
    // hall's hours above the ones beside it. R&DE publishes the logos only
    // inside one map image, so a new hall has none until someone reads its box
    // off that map.
    const logo = el("div", { className: "col-logo" });
    if (hall.logo) {
      const [w, h] = logoSize(hall.logo.w / hall.logo.h);
      const img = el("img", {
        src: "logo/" + hall.logo.file,
        // Decorative: the hall's name is right beside it, and reading the logo
        // out as well would just say it twice.
        alt: "",
        width: w,
        height: h,
        decoding: "async",
      });
      img.style.setProperty("--logo-w", w + "px");
      img.style.setProperty("--logo-h", h + "px");
      logo.append(img);
    }

    const title = el("div", { className: "col-title" }, [
      el("h2", { className: "col-name", textContent: hall.short }),
    ]);
    const concept = (state.lang === "zh" && hall.concept_zh) || hall.concept;
    if (concept) {
      title.append(el("p", { className: "col-concept", textContent: concept }));
    }
    const head = el("header", { className: "col-head" }, [
      el("div", { className: "col-top" }, [title, logo]),
    ]);

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
        textContent: t("status", status),
      }));
    }
    meta.append(el("span", {
      className: "count",
      textContent: t("count", specials.length + daily.length),
    }));
    const onlyHere = [...specials, ...daily].filter((r) => spread.get(r.id) === 1).length;
    if (onlyHere) {
      meta.append(el("span", { className: "only-count", textContent: t("onlyCount", onlyHere) }));
    }
    if (hall.address) {
      meta.append(el("a", {
        className: "maplink",
        href: "https://maps.google.com/?q=" + encodeURIComponent(hall.address),
        target: "_blank",
        rel: "noopener",
        textContent: t("map"),
      }));
    }
    head.append(meta);
    col.append(head);

    if (!svc.specials.length && !svc.daily.length && !svc.stations.length) {
      col.append(el("div", {
        className: "empty",
        textContent: t("noService", state.meal, dayLabel(state.date)),
      }));
      return col;
    }

    if (!specials.length && !daily.length) {
      col.append(el("div", {
        className: "empty",
        textContent: state.diet.length ? t("noMatch") : t("noneListed"),
      }));
    } else {
      for (const rec of specials) col.append(dishCard(rec, spread.get(rec.id) === 1, true));
      for (const rec of daily) col.append(dishCard(rec, spread.get(rec.id) === 1));
    }

    if (stations.length) {
      const wrap = el("section", { className: "stations" });
      const head = el("div", { className: "stations-head" }, [
        el("span", { className: "stations-title", textContent: t("alwaysHere") }),
        el("span", { className: "stations-count", textContent: String(stations.length) }),
      ]);
      const toggle = el("button", {
        className: "stations-toggle",
        type: "button",
        textContent: t("toggle", state.stations),
      });
      toggle.addEventListener("click", () => {
        state.stations = !state.stations;
        render();
      });
      head.append(toggle);
      wrap.append(head);
      // Runs from the row under this hall's last card to the bottom of the
      // board; see .stations in the stylesheet. Read before the block is
      // appended, so the count is the header plus this hall's cards.
      wrap.style.gridRow = `${col.childElementCount + 1} / -1`;

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
      chip(t("meal", m), m === state.meal, () => {
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
        chip(t("diet", d), state.diet.includes(d.key), () => {
          const i = state.diet.indexOf(d.key);
          if (i >= 0) state.diet.splice(i, 1);
          else state.diet.push(d.key);
          render();
        })),
      chip(t("meatFirst"), state.meatFirst, () => {
        state.meatFirst = !state.meatFirst;
        render();
      }, { className: "chip-ghost" }),
      chip(t("photos"), state.photos, () => {
        state.photos = !state.photos;
        render();
      }, { className: "chip-ghost" }),
      chip(t("reset"), false, () => {
        try {
          localStorage.removeItem(STORE);
        } catch { /* storage blocked; the in-memory reset below still applies */ }
        Object.assign(state, structuredClone(fallback));
        render();
      }, { className: "chip-ghost" }),
    );

    document.getElementById("theme").textContent = t("theme", state.theme);
  }

  /** The text that lives in index.html rather than in a chip: labels, the
   *  masthead and the footer. Rebuilt on every render because switching
   *  language rewrites all of it. */
  function renderChrome() {
    // Not just for screen readers: it is what picks the CJK font in app.css.
    document.documentElement.lang = state.lang === "zh" ? "zh-Hans" : "en";
    document.title = t("docTitle");

    document.getElementById("brand").replaceChildren(
      t("brandA"), el("span", { textContent: t("brandB") }));

    for (const [id, key] of [["lbl-day", "lblDay"], ["lbl-meal", "lblMeal"],
                             ["lbl-halls", "lblHalls"], ["lbl-filter", "lblFilter"]]) {
      document.getElementById(id).textContent = t(key);
    }

    const link = (href, text) =>
      el("a", { href, target: "_blank", rel: "noopener", textContent: text });
    const built = (state.lang === "zh" && DATA.generated_at_zh) || DATA.generated_at;
    document.getElementById("foot-src").replaceChildren(...t("footerSrc", link, built));
    document.getElementById("foot-note").replaceChildren(
      ...t("footerNote", (text) => el("strong", { textContent: text })));

    const lang = document.getElementById("lang");
    lang.textContent = t("langChip");
    lang.setAttribute("aria-label", t("langLabel"));
  }

  document.getElementById("lang").addEventListener("click", () => {
    state.lang = state.lang === "zh" ? "en" : "zh";
    render();
  });

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
