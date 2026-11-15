# Design Spec: Late Night Dining & Shake Smart Shakes Integration

## Summary
Integrate Stanford R&DE's permanent late-night dining services and newly introduced Shake Smart Shakes offering into Better Stanford Dining Menu.

## Context & Motivation
Stanford R&DE updated the Dining Locations & Hours page to officially introduce Shake Smart Shakes across campus late-night venues:
- Arrillaga Nights (Arrillaga Family Dining Commons): Tuesday – Saturday, 9:00 PM – 2:00 AM
- Late Night Kitchen at Lakeside (Lakeside Dining): Sunday – Thursday, 9:30 PM – 2:00 AM
- The Axe & Palm (Old Union, retail cafe): Monday – Friday 11:00 AM – 2:00 AM, Saturday – Sunday 5:00 PM – 2:00 AM

The 8 residential dining commons tracked by this application include Arrillaga and Lakeside. Previously, the website only supported Breakfast, Lunch, Brunch, and Dinner, leaving late-night services unrepresented even though `late_night` schedules were stored in `config/halls.json`.

## Goals
1. Add a dedicated `Late Night` (夜宵) meal tab alongside Breakfast, Lunch, and Dinner.
2. Dynamically switch Arrillaga and Lakeside logos to their official Late Night logos when Late Night is selected.
3. Feature the Shake Smart Shakes offering with official 16:9 artwork, description, dietary tags, and allergens.
4. Support midnight-crossing hours status checks (`open`, `soon`, `shut`) and automatic meal selection for late-night visitors.
5. Provide complete bilingual (English/Chinese) support.

## Architecture & Data Flow

### 1. Logo Assets
- Source: `data/shake_smart_banner.jpg` (official R&DE image on hours page).
- Crops:
  - `data/logos/arrillaga_late_night.webp`: The Arrillaga Nights oval logo.
  - `data/logos/lakeside_late_night.webp`: The Late Night Kitchen at Lakeside wordmark logo.
- Registration: Added to `data/logos/index.json`.

### 2. Dish Artwork & Data
- Dish: `Shake Smart Shakes` (dish ID: `bcda517df9b6`).
- Image: `data/images/bcda517df9b6.webp` (1024x576 16:9 format showing the shakes lineup).
- Catalog & Menu:
  - Added to `data/dishes.json` as a featured menu item.
  - Injected into `DATA.menus[date][hallId]["Late Night"]` for active late-night dining halls.

### 3. Build & Payload Generation (`bsdm/build.py`)
- Update `schedule_for(hall, day)`:
  - Check `hall.get("late_night")` and match weekday.
  - Export `meals["Late Night"] = hall["late_night"]["hours"]`.
- Update `hall_public(h)`:
  - If `h.get("late_night")`, include `late_night_logo: { file, w, h }` from logo index.
  - Export `late_night: h["late_night"]`.
- Expand `MEAL_ORDER` and iteration in `build_payload()` to include `"Late Night"`.
- Sync `config/halls.json` Lakeside late night hours to `["21:30", "02:00"]`.

### 4. Frontend Application (`web/app.js` & `web/app.css`)
- Expand `MEALS` array: `["Breakfast", "Lunch", "Dinner", "Late Night"]`.
- Expand `MEAL_ZH`: `"Late Night": "夜宵"`.
- In `hallLogo(hall)`:
  - If `state.meal === "Late Night"` and `hall.late_night_logo` exists, render `hall.late_night_logo`.
  - Otherwise, render default `hall.logo`.
- In `column(hallId, ...)`:
  - If `state.meal === "Late Night"` and `hall.late_night`, render concept subtitle as `Arrillaga Nights` / `Late Night Kitchen at Lakeside` (or Chinese translation).
- In `serviceStatus(date, span)`:
  - Support spans crossing midnight where `close < open` (e.g. 21:00 to 02:00).
- In `upcoming(halls)`:
  - Auto-select `Late Night` between 20:00 (Dinner close) and 02:00 (Late Night close) when late night is served.

## Testing & Verification
- Unit test for late-night schedule generation in `tests/test_build.py`.
- Unit test for midnight-crossing service status logic in `tests/test_web_js.py`.
- Full pytest suite verification (`make test`).
- End-to-end local build (`make site`) and local server preview (`make serve`).
