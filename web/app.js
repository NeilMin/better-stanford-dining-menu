(() => {
  "use strict";

  const DATA = JSON.parse(document.getElementById("menu-data").textContent);
  const MEALS = ["Breakfast", "Lunch", "Dinner"];
  // v4 added `lang` to the persisted shape.
  const STORE = "bsdm.prefs.v4";

  const DIET = [
    { key: "vegetarian", label: "Vegetarian", zh: "素食", cls: "badge-v", short: "Veg", shortZh: "素" },
    { key: "vegan", label: "Vegan", zh: "纯素", cls: "badge-vgn", short: "Vegan", shortZh: "纯素" },
    { key: "gluten-free", label: "Gluten-free", zh: "无麸质", cls: "badge-gf", short: "GF", shortZh: "无麸质" },
    { key: "halal", label: "Halal", zh: "清真", cls: "badge-halal", short: "Halal", shortZh: "清真" },
    { key: "kosher", label: "Kosher", zh: "犹太洁食", cls: "badge-kosher", short: "Kosher", shortZh: "洁食" },
  ];

  const PROTEIN = {
    beef: "Beef", pork: "Pork", poultry: "Poultry", seafood: "Seafood", lamb: "Lamb",
  };
  const PROTEIN_ZH = {
    beef: "牛肉", pork: "猪肉", poultry: "禽肉", seafood: "海鲜", lamb: "羊肉",
  };

  const MEAL_ZH = { Breakfast: "早餐", Lunch: "午餐", Dinner: "晚餐", Brunch: "早午餐" };

  // R&DE's allergen codes. Anything not listed shows as it came.
  const ALLERGEN_EN = {
    MILK: "Milk", EGG: "Egg", WHEAT: "Wheat", SOY: "Soy", FISH: "Fish", SHELLFISH: "Shellfish",
    SESAME: "Sesame", COCONUT: "Coconut", PEANUT: "Peanut", TREENUT: "Tree nuts",
    TRACEALLERGENS: "Trace allergens",
  };
  const ALLERGEN_ZH = {
    MILK: "乳制品", EGG: "蛋类", WHEAT: "小麦", SOY: "大豆", FISH: "鱼类", SHELLFISH: "甲壳贝类",
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
      protein: (c) => PROTEIN[c],
      onlyHere: "Only here",
      meatFirst: "Meat first", photos: "Show photos", reset: "Reset",
      theme: (mode) => ({ auto: "Auto", light: "Light", dark: "Dark" }[mode]),
      status: (s) => ({ open: "Open now", soon: "Opens soon", shut: "Closed" }[s]),
      count: (n) => `${n} on the menu`,
      onlyCount: (n) => `${n} only here`,
      map: "Map",
      special: "Special",
      specialBadge: "Special",
      specialTip: (meal) => `${meal} special, from R&DE's specials calendar`,
      specialNote: "Limited-time special from R&DE's calendar. No ingredient list published — ask at the counter.",
      alwaysHere: "Always here",
      toggle: (shown) => (shown ? "Hide" : "Show"),
      allergens: "Allergens: ",
      allergenList: (list) => list.map((a) => ALLERGEN_EN[a] || a).join(", "),
      ingredients: "Ingredients",
      traces: (list) => "Shared equipment with: " + list.map((a) => ALLERGEN_EN[a] || a).join(", "),
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
      tourDay: ["Pick a day",
        "Menus run a week ahead. Tap a day, or use ← → on a keyboard. The page always opens on today."],
      tourMeal: ["Pick a meal",
        "Breakfast, lunch or dinner. A greyed-out meal is one none of your halls serve that day."],
      tourHalls: ["Pick your halls",
        "Tap a hall to add or drop it; each gets a column, side by side. Your halls, meal, language and theme are remembered."],
      // 语言 in the title so a Chinese reader spots the stop meant for them.
      tourLang: ["Language · 语言", "Switch to another language here."],
      tourNext: "Next", tourDone: "Got it", tourSkip: "Skip",
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
      docTitle: "舌尖上的斯坦福，一站式食堂菜单",
      brandA: "舌尖上的斯坦福，",
      brandB: "一站式食堂菜单",
      lblDay: "日期", lblMeal: "餐次", lblHalls: "食堂", lblFilter: "筛选",
      today: "今天", tomorrow: "明天",
      meal: (m) => MEAL_ZH[m] || m,
      diet: (d) => d.zh,
      dietShort: (d) => d.shortZh,
      protein: (c) => PROTEIN_ZH[c] || PROTEIN[c],
      onlyHere: "只此一家",
      meatFirst: "荤菜靠前", photos: "显示图片", reset: "重置",
      theme: (mode) => ({ auto: "自动", light: "浅色", dark: "深色" }[mode]),
      status: (s) => ({ open: "供应中", soon: "即将开餐", shut: "休息中" }[s]),
      count: (n) => `共 ${n} 道菜`,
      onlyCount: (n) => `独有 ${n} 道`,
      map: "地图",
      special: "限定",
      specialBadge: "限定",
      specialTip: (meal) => `${meal}限定菜品，出自 R&DE 的限定菜日历`,
      specialNote: "R&DE 日历上的限时菜品，未公布配料表——有过敏请到窗口确认。",
      alwaysHere: "常设窗口",
      toggle: (shown) => (shown ? "收起" : "展开"),
      allergens: "过敏原：",
      allergenList: (list) => list.map((a) => ALLERGEN_ZH[a] || a).join("、"),
      ingredients: "配料",
      traces: (list) => "共用加工设备：" + list.map((a) => ALLERGEN_ZH[a] || a).join("、"),
      varies: "每日更换，请到窗口询问。",
      variesShort: "每日不同",
      variesTip: "此项每日更换，因此不配图。",
      pending: "图片待生成",
      pendingTip: "这道菜暂时还没有图片。",
      noService: (meal, day) => `${day}本食堂不供应${MEAL_ZH[meal] || meal}。`,
      noMatch: "今日菜单中没有符合筛选条件的菜品。",
      noneListed: "今日未列出具体菜品。",
      digest: (b, total, halls, every, unique) => [
        `今天 ${halls} 家食堂共 `, b(total), " 道菜 · 其中 ",
        b(every), " 道家家都有 · ", b(unique), " 道仅此一家。",
      ],
      identical: "这几家的菜单完全相同——去离你最近的那家就好。",
      tourDay: ["选日期", "菜单提前一周公布。点日期切换，电脑上也可以按 ← →。每次打开都从今天开始。"],
      tourMeal: ["选餐次", "早餐、午餐、晚餐任选。灰掉的餐次是你选的食堂当天都不供应。"],
      tourHalls: ["选食堂", "点一下添加或移除，每家食堂占一列，并排对比。食堂、餐次、语言和主题都会记住。"],
      tourLang: ["语言 · Language", "在这里可以切换成其他语言。"],
      tourNext: "下一步", tourDone: "知道了", tourSkip: "跳过",
      footerSrc: (a, built) => [
        "菜单抓取自 ",
        a("https://rdeapps.stanford.edu/dininghallmenu/", "R&DE 食堂菜单"),
        "，营业时间和地址来自 ",
        a("https://rde.stanford.edu/dining-hospitality/dining-locations-hours",
          "R&DE 餐饮地点与营业时间"),
        `。更新于 ${built}。`,
        "源代码托管在 ",
        a("https://github.com/NeilMin/better-stanford-dining-menu", "GitHub"),
        "。",
      ],
      footerNote: (strong) => [
        strong("菜品图片由 AI 根据菜名和配料表生成。"),
        "图片仅示意这道菜通常的样子，并非实际出餐的照片。" +
        "过敏原和配料信息转载自 R&DE，可能随时变更，恕不另行通知——如有食物过敏，请到食堂当面确认。",
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

  // The date is the one choice that is not remembered: you open the page to see
  // what is on today, and a day picked last Tuesday is a stale answer to that.
  // Older saves still carry one, so it is dropped on the way in as well as out.
  function load() {
    try {
      const { date, ...saved } = JSON.parse(localStorage.getItem(STORE) || "{}");
      return { ...fallback, ...saved };
    } catch {
      return { ...fallback };
    }
  }

  function save() {
    try {
      const { date, ...kept } = state;
      localStorage.setItem(STORE, JSON.stringify(kept));
    } catch {
      /* private browsing or blocked storage -- preferences just don't persist */
    }
  }

  const state = load();

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

  /** A dish cooked today. The picture leads, so the pictures in one row start
   *  level across the halls whatever length the names beneath them run to; the
   *  box is reserved at its final size, so the name does not jump when it loads.
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
    card.append(head);

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

    // ...and how many halls are up decides how wide the board asks to be, which
    // on a wide enough screen is wider than the page (--width, in the
    // stylesheet). It goes on the board and nowhere else: the top bar, the title
    // and the chips keep the page's width whatever is selected, because controls
    // that move when you pick a hall are worse than a board you have to scroll.
    board.style.setProperty("--cols", String(board.childElementCount));

    renderDigest(spread);
    renderNotices();
    document.getElementById("stamp").replaceChildren(
      el("span", { className: "stamp-meal", textContent: t("meal", state.meal) }),
      " ",
      el("span", { className: "stamp-day", textContent: dayFull(state.date) }),
    );
    // A render can switch the language under the tip or resize the row it points at.
    if (tour) drawTour(false);
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

    // The name is underlined in the hall's colour -- the specials poster prints
    // it on a bar of that colour -- so the board and the poster read as one key.
    const title = el("div", { className: "col-title" }, [
      el("h2", { className: "col-name" }, [el("span", { textContent: hall.short })]),
    ]);
    const concept = (state.lang === "zh" && hall.concept_zh) || hall.concept;
    if (concept) {
      title.append(el("p", { className: "col-concept", textContent: concept }));
    }
    const head = el("header", { className: "col-head" }, [
      el("div", { className: "col-top" }, [title, logo]),
    ]);

    // Two lines, each read across the headers: when it serves, then what it has.
    const when = el("p", { className: "col-when" });
    if (span) {
      when.append(el("span", {
        className: "hours",
        textContent: `${fmtTime(span[0])} – ${fmtTime(span[1])}`,
      }));
    }
    if (status) {
      when.append(el("span", {
        className: `status status-${status}`,
        textContent: t("status", status),
      }));
    }
    const stats = el("p", { className: "col-stats" }, [
      el("span", { className: "count", textContent: t("count", specials.length + daily.length) }),
    ]);
    const onlyHere = [...specials, ...daily].filter((r) => spread.get(r.id) === 1).length;
    if (onlyHere) {
      stats.append(el("span", { className: "only-count", textContent: t("onlyCount", onlyHere) }));
    }
    if (hall.address) {
      stats.append(el("a", {
        className: "maplink",
        href: "https://maps.google.com/?q=" + encodeURIComponent(hall.address),
        target: "_blank",
        rel: "noopener",
        textContent: t("map"),
      }));
    }
    head.append(el("div", { className: "col-meta" }, [when, stats]));
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
    b.append(el("span", { className: "label", textContent: label }));
    if (extra.sub) b.append(el("span", { className: "sub", textContent: extra.sub }));
    if (extra.accent) b.style.setProperty("--hall", extra.accent);
    b.addEventListener("click", onClick);
    return b;
  }

  function renderControls() {
    // A calendar strip: the day's name over its date. The month is in the
    // headline, and the full date on hover.
    document.getElementById("days").replaceChildren(...DATA.window.map((iso) =>
      chip(dayLabel(iso), iso === state.date, () => {
        state.date = iso;
        render();
      }, {
        className: "chip-day",
        sub: String(Number(iso.slice(8))),
        props: { title: dayFull(iso) },
      })));

    const meals = availableMeals(state.date);
    document.getElementById("meals").replaceChildren(...MEALS.map((m) =>
      chip(t("meal", m), m === state.meal, () => {
        state.meal = m;
        render();
      }, { className: "chip-seg", props: { disabled: !meals.includes(m) } })));

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
      }, { className: "chip-view" }),
      chip(t("photos"), state.photos, () => {
        state.photos = !state.photos;
        render();
      }, { className: "chip-view" }),
      chip(t("reset"), false, () => {
        try {
          localStorage.removeItem(STORE);
        } catch { /* storage blocked; the in-memory reset below still applies */ }
        Object.assign(state, structuredClone(fallback));
        render();
      }, { className: "chip-reset" }),
    );

    const theme = document.getElementById("theme");
    theme.textContent = t("theme", state.theme);
    // Picks the drawn icon in app.css.
    theme.dataset.mode = state.theme;
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

  // ---------- first-visit tour ----------
  //
  // Four stops, shown once per browser. The flag lives apart from STORE, so
  // Reset or a STORE bump does not replay the tour to someone who has seen it.
  //
  // The ring and the tip are overlays laid over the target, not styles on it:
  // on a phone each control row is a horizontal scroller with a masked edge,
  // which would clip a ring drawn on the row's own children.
  const TOUR_SEEN = "bsdm.tour.v1";
  const TOUR = [
    { key: "tourDay", target: () => document.getElementById("days").parentElement },
    { key: "tourMeal", target: () => document.getElementById("meals").parentElement },
    { key: "tourHalls", target: () => document.getElementById("halls").parentElement },
    { key: "tourLang", target: () => document.getElementById("lang") },
  ];
  let tour = null;

  function startTour() {
    try {
      if (localStorage.getItem(TOUR_SEEN)) return;
      // Written up front, as on neilmin.github.io: leaving mid-tour counts as seen.
      localStorage.setItem(TOUR_SEEN, "1");
    } catch {
      return; // with nowhere to remember it, it would show on every visit
    }
    tour = {
      step: 0,
      ring: el("div", { className: "tour-ring" }),
      tip: el("div", { className: "tour-tip", role: "dialog" }),
      row: null,
    };
    document.body.append(tour.ring, tour.tip);
    addEventListener("resize", placeTour);
    // Captured, because a scrolling control row does not bubble its scroll.
    document.addEventListener("scroll", placeTour, true);
    drawTour(true);
    // Only now, so the ring's first placement is a jump rather than a glide in
    // from the corner.
    requestAnimationFrame(() => tour && tour.ring.classList.add("tour-glide"));
  }

  /** Put the phone's scrolled control row back the way the tour found it. */
  function leaveStep() {
    if (tour.row) tour.row[0].scrollLeft = tour.row[1];
    tour.row = null;
  }

  function stepTour() {
    leaveStep();
    tour.step += 1;
    drawTour(true);
  }

  function endTour() {
    leaveStep();
    tour.ring.remove();
    tour.tip.remove();
    tour = null;
    removeEventListener("resize", placeTour);
    document.removeEventListener("scroll", placeTour, true);
  }

  /** Fill the tip for the current stop. `arriving` is false when a render
   *  redraws it in place, which must neither scroll the row nor move focus. */
  function drawTour(arriving) {
    const stop = TOUR[tour.step];
    const [title, body] = t(stop.key);
    const last = tour.step === TOUR.length - 1;

    const next = el("button", {
      type: "button",
      className: "tour-next",
      textContent: t(last ? "tourDone" : "tourNext"),
    });
    next.addEventListener("click", last ? endTour : stepTour);
    const actions = el("div", { className: "tour-actions" }, [
      el("span", { className: "tour-count", textContent: `${tour.step + 1} / ${TOUR.length}` }),
    ]);
    if (!last) {
      const skip = el("button", { type: "button", className: "tour-skip", textContent: t("tourSkip") });
      skip.addEventListener("click", endTour);
      actions.append(skip);
    }
    actions.append(next);

    tour.tip.setAttribute("aria-label", title);
    tour.tip.replaceChildren(
      el("p", { className: "tour-title", textContent: title }),
      el("p", { className: "tour-body", textContent: body }),
      actions,
    );

    if (arriving) {
      const target = stop.target();
      const row = target.closest(".controls");
      if (row) {
        tour.row = [row, row.scrollLeft];
        target.scrollIntoView({ block: "nearest", inline: "nearest" });
      }
      next.focus({ preventScroll: true });
    }
    placeTour();
  }

  function placeTour() {
    if (!tour) return;
    const target = TOUR[tour.step].target();
    const r = target.getBoundingClientRect();
    // Ring only the part you can see: on a phone the week runs off the row's edge.
    const row = target.closest(".controls");
    const clip = row ? row.getBoundingClientRect() : { left: 0, right: innerWidth };
    const left = Math.max(r.left, clip.left, 8);
    const right = Math.min(r.right, clip.right, innerWidth - 8);
    const pad = 5;
    Object.assign(tour.ring.style, {
      left: `${left - pad}px`,
      top: `${r.top - pad}px`,
      width: `${right - left + 2 * pad}px`,
      height: `${r.height + 2 * pad}px`,
    });

    const w = tour.tip.offsetWidth;
    const mid = (left + right) / 2;
    const x = Math.min(Math.max(mid - w / 2, 12), innerWidth - w - 12);
    tour.tip.style.left = `${x}px`;
    tour.tip.style.top = `${r.bottom + pad + 10}px`;
    tour.tip.style.setProperty("--arrow", `${Math.min(Math.max(mid - x, 18), w - 18)}px`);
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
    if (e.key === "Escape" && tour) {
      endTour();
      return;
    }
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
  // A beat after the page appears, so the ring reads as something happening.
  setTimeout(startTour, 450);
})();
