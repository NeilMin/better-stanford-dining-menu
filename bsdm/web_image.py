from __future__ import annotations

import html
import io
import json
import logging
import os
from pathlib import Path
import re
import urllib.parse
from typing import TYPE_CHECKING

import requests
from PIL import Image

if TYPE_CHECKING:
    from bsdm.cloudflare import CloudflareClient

log = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)"


def _load_dotenv(env_path: Path | str | None = None) -> None:
    """Load API credentials from a .env file if not present in os.environ."""
    if "PYTEST_CURRENT_TEST" in os.environ and not env_path:
        return
    if os.getenv("GOOGLE_API_KEY") and os.getenv("GOOGLE_CSE_ID"):
        return
    candidates = [Path(env_path)] if env_path else [
        Path.cwd() / ".env",
        Path(__file__).resolve().parent.parent / ".env",
    ]
    for p in candidates:
        if p and p.is_file():
            try:
                for line in p.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k_clean = k.strip()
                        if k_clean in ("GOOGLE_API_KEY", "GOOGLE_CSE_ID", "PEXELS_API_KEY"):
                            if k_clean not in os.environ:
                                os.environ[k_clean] = v.strip().strip("\"'")
                return
            except Exception:
                pass



def clean_search_query(dish_name: str) -> str:
    """Normalize a dish name into an encyclopedic food search term."""
    clean = re.sub(r"\([^)]*\)", "", dish_name)
    clean = re.sub(r"\b(station|bar|counter|allergen friendly|house-made|housemade)\b", "", clean, flags=re.I)
    if "," in clean:
        clean = clean.split(",")[0]
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean or dish_name


def is_aspect_ratio_safe(
    width: int, height: int, max_portrait_ratio: float = 1.25, max_landscape_ratio: float = 2.5
) -> bool:
    """True if image aspect ratio is suitable for card presentation (avoids extreme vertical portraits)."""
    if width <= 0 or height <= 0:
        return False
    # If height > 1.25 * width, it is a tall vertical portrait that loses essential content when cropped to 16:9
    if height / width > max_portrait_ratio:
        return False
    # If width > 2.5 * height, it is an extreme panorama/banner
    if width / height > max_landscape_ratio:
        return False
    return True


_DISH_DESC_KEYWORDS = {
    "dish", "meal", "recipe", "food", "cuisine", "bread", "soup", "pie", "stew",
    "salad", "curry", "pasta", "pizza", "barbecue", "roast", "sandwich", "pudding",
    "pastry", "breakfast", "dinner", "lunch", "snack", "noodle", "dumpling",
    "appetizer", "dessert", "confectionery", "entree", "casserole", "stir-fry",
}

_NON_DISH_DESC_KEYWORDS = {
    "plant", "species", "genus", "breed", "animal", "person", "actor", "chef",
    "author", "politician", "company", "corporation", "brand", "cut of", "variety of",
    "chemical", "compound", "protein", "substance",
}

_BAD_FILENAME_RE = re.compile(
    r"(\b|_)(raw|uncooked|before_baking|before_cooking|diagram|cut|anatomy|map|logo|sign|advertis)(\b|_)",
    re.I,
)


def search_wikipedia(
    query: str, session: requests.Session, timeout: int = 15
) -> list[tuple[str, int | None, int | None]]:
    """Search English Wikipedia for page images matching query."""
    url = "https://en.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": query,
        "gsrlimit": 6,
        "prop": "pageimages|description",
        "piprop": "original|thumbnail",
        "pithumbsize": 1024,
    }
    try:
        r = session.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        log.warning("Wikipedia search failed for '%s': %s", query, exc)
        return []

    pages = data.get("query", {}).get("pages", {})

    def score_page(page_dict: dict) -> int:
        desc = (page_dict.get("description") or "").lower()
        title = page_dict.get("title", "").lower()
        img_src = (page_dict.get("thumbnail") or page_dict.get("original") or {}).get("source", "")
        if _BAD_FILENAME_RE.search(img_src):
            return -999
        score = 100 - page_dict.get("index", 99)
        if any(k in desc for k in _NON_DISH_DESC_KEYWORDS):
            score -= 50
        if any(k in desc for k in _DISH_DESC_KEYWORDS):
            score += 30
        title_words = set(re.findall(r"\w+", title))
        q_words = set(re.findall(r"\w+", query.lower()))
        score += len(title_words & q_words) * 20
        return score

    sorted_pages = sorted(pages.values(), key=score_page, reverse=True)
    candidates: list[tuple[str, int | None, int | None]] = []
    for page in sorted_pages:
        if score_page(page) < 0:
            continue
        thumb = page.get("thumbnail")
        orig = page.get("original")
        img_info = thumb or orig
        if not img_info or not img_info.get("source"):
            continue
        src = img_info["source"]
        if src.lower().endswith(".svg") or _BAD_FILENAME_RE.search(src):
            continue
        w = img_info.get("width")
        h = img_info.get("height")
        candidates.append((src, w, h))
    return candidates


def search_pexels(
    query: str, session: requests.Session, api_key: str, timeout: int = 15
) -> list[tuple[str, int | None, int | None]]:
    """Search Pexels API for food photos (if PEXELS_API_KEY is configured)."""
    url = "https://api.pexels.com/v1/search"
    headers = {"Authorization": api_key}
    params = {"query": f"{query} food", "per_page": 5}
    try:
        r = session.get(url, headers=headers, params=params, timeout=timeout)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        log.warning("Pexels search failed for '%s': %s", query, exc)
        return []

    photos = data.get("photos", [])
    candidates: list[tuple[str, int | None, int | None]] = []
    for photo in photos:
        src = photo.get("src", {}).get("large2x") or photo.get("src", {}).get("large")
        if not src:
            continue
        w = photo.get("width")
        h = photo.get("height")
        candidates.append((src, w, h))
    return candidates


def search_unsplash(
    query: str, session: requests.Session, timeout: int = 15
) -> list[tuple[str, int | None, int | None]]:
    """Search Unsplash for professional food photography."""
    url = "https://unsplash.com/napi/search/photos"
    params = {"query": f"{query} food", "per_page": 5}
    try:
        r = session.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        log.warning("Unsplash search failed for '%s': %s", query, exc)
        return []

    results = data.get("results", [])
    candidates: list[tuple[str, int | None, int | None]] = []
    for item in results:
        urls = item.get("urls", {})
        src = urls.get("regular") or urls.get("full") or urls.get("small")
        if not src:
            continue
        w = item.get("width")
        h = item.get("height")
        candidates.append((src, w, h))
    return candidates


def search_duckduckgo(
    query: str, session: requests.Session, timeout: int = 15
) -> list[tuple[str, int | None, int | None]]:
    """Search DuckDuckGo Images without API key for candidate image URLs."""
    search_term = f"{query} restaurant dish gourmet plating food photography"
    token_url = f"https://duckduckgo.com/?{urllib.parse.urlencode({'q': search_term})}"
    try:
        r = session.get(token_url, timeout=timeout)
        r.raise_for_status()
    except Exception as exc:
        log.warning("DuckDuckGo token lookup failed for '%s': %s", query, exc)
        return []

    match = re.search(r'vqd=([0-9-_]+)', r.text) or re.search(r'vqd="([^"]+)"', r.text)
    if not match:
        log.warning("Could not extract vqd token for '%s'", query)
        return []
    vqd = match.group(1)

    search_url = (
        f"https://duckduckgo.com/i.js?l=us-en&o=json&q={urllib.parse.quote(search_term)}"
        f"&vqd={vqd}&f=,,,&p=1"
    )
    try:
        r = session.get(search_url, timeout=timeout)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        log.warning("DuckDuckGo image search request failed for '%s': %s", query, exc)
        return []

    results = data.get("results", [])
    candidates: list[tuple[str, int | None, int | None]] = []
    for item in results[:5]:
        img_url = item.get("image")
        if not img_url:
            continue
        w = item.get("width")
        h = item.get("height")
        candidates.append((img_url, w, h))
    return candidates


def search_bing(
    query: str, session: requests.Session, timeout: int = 15
) -> list[tuple[str, int | None, int | None]]:
    """Search Bing Images without API key for high-resolution culinary food photography."""
    search_term = f"{query} recipe dish plating food photography"
    url = "https://www.bing.com/images/search"
    params = {"q": search_term, "form": "HDRSC2", "first": 1}
    try:
        r = session.get(url, params=params, timeout=timeout)
        r.raise_for_status()
    except Exception as exc:
        log.warning("Bing image search request failed for '%s': %s", query, exc)
        return []

    m_matches = re.findall(r'm="({.*?})"', r.text)
    candidates: list[tuple[str, int | None, int | None]] = []
    for m in m_matches:
        try:
            data = json.loads(html.unescape(m))
            img_url = data.get("murl")
            if not img_url or _BAD_FILENAME_RE.search(img_url):
                continue
            candidates.append((img_url, None, None))
            if len(candidates) >= 10:
                break
        except Exception:
            continue
    return candidates


def search_google_custom_search(
    query: str,
    session: requests.Session,
    api_key: str,
    cse_id: str,
    timeout: int = 15,
) -> list[tuple[str, int | None, int | None]]:
    """Search Google Custom Search JSON API for high-resolution dish photos."""
    url = "https://customsearch.googleapis.com/customsearch/v1"
    params = {
        "key": api_key,
        "cx": cse_id,
        "q": query,
        "searchType": "image",
        "imgType": "photo",
        "num": 8,
        "safe": "active",
    }
    try:
        r = session.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        log.warning("Google Custom Search API request failed for '%s': %s", query, exc)
        return []

    items = data.get("items", [])
    candidates: list[tuple[str, int | None, int | None]] = []
    for item in items:
        img_url = item.get("link")
        if not img_url:
            continue
        if _BAD_FILENAME_RE.search(img_url):
            continue
        img_info = item.get("image", {})
        w = img_info.get("width")
        h = img_info.get("height")
        candidates.append((img_url, w, h))
    return candidates


def search_food_image(
    dish_name: str,
    client: CloudflareClient | None = None,
    min_score: int = 7,
    timeout: int = 15,
) -> bytes | None:
    """Find a high-quality, authentic food photo for dish_name with optional VLM quality evaluation."""
    _load_dotenv()
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    query = clean_search_query(dish_name)

    candidates: list[tuple[str, int | None, int | None]] = []

    # Tier 0: Google Custom Search API (if grandfathered account configured)
    google_key = os.getenv("GOOGLE_API_KEY")
    google_cx = os.getenv("GOOGLE_CSE_ID")
    if google_key and google_cx:
        candidates.extend(search_google_custom_search(query, session, google_key, google_cx, timeout=timeout))

    # Tier 1: Bing Images (high-resolution commercial culinary photography from recipe sites)
    if not candidates:
        candidates.extend(search_bing(query, session, timeout=timeout))

    # Tier 2: Professional stock photo sources first (Unsplash & Pexels)
    if not candidates:
        pexels_key = os.getenv("PEXELS_API_KEY")
        if pexels_key:
            candidates.extend(search_pexels(query, session, pexels_key, timeout=timeout))

    if not candidates:
        candidates.extend(search_unsplash(query, session, timeout=timeout))

    # Tier 3: Commercial culinary photography via DuckDuckGo (legacy fallback)
    if not candidates:
        candidates.extend(search_duckduckgo(query, session, timeout=timeout))

    # Tier 4: Last resort fallback to Wikipedia (deprioritized due to amateur snapshots)
    if not candidates:
        candidates.extend(search_wikipedia(query, session, timeout=timeout))

    if not candidates:
        log.info("No candidate images found for '%s' (query='%s')", dish_name, query)
        return None

    for img_url, w, h in candidates:
        if w is not None and h is not None and not is_aspect_ratio_safe(w, h):
            log.debug("Skipping candidate image (%dx%d) due to aspect ratio: %s", w, h, img_url)
            continue

        try:
            r = session.get(img_url, timeout=timeout)
            if r.status_code != 200 or len(r.content) < 2048:
                continue

            with Image.open(io.BytesIO(r.content)) as im:
                actual_w, actual_h = im.size

            if actual_w < 300 or actual_h < 200:
                continue

            if not is_aspect_ratio_safe(actual_w, actual_h):
                continue

            if client is not None and client.is_configured():
                eval_fn = getattr(client, "evaluate_food_image", client.evaluate_image)
                eval_res = eval_fn(r.content, dish_name)
                score = eval_res.get("score", 0)
                valid = eval_res.get("valid", False)
                reason = eval_res.get("reason", "")
                if valid and score >= min_score:
                    log.info("VLM accepted candidate for '%s': score=%d (%s)", dish_name, score, reason)
                    return r.content
                else:
                    log.info("VLM rejected candidate for '%s': valid=%s, score=%d (%s)", dish_name, valid, score, reason)
                    continue
            else:
                return r.content

        except Exception as exc:
            log.debug("Failed downloading or evaluating %s: %s", img_url, exc)
            continue

    return None
