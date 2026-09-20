from __future__ import annotations

import io
import logging
import re
import urllib.parse

import requests
from PIL import Image

log = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)"


def search_food_image(dish_name: str, timeout: int = 15) -> bytes | None:
    """Search DuckDuckGo Images without API key, download top valid food photo."""
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    query = f"{dish_name} food dish recipe"
    # Step 1: obtain DuckDuckGo vqd token
    token_url = f"https://duckduckgo.com/?{urllib.parse.urlencode({'q': query})}"
    try:
        r = session.get(token_url, timeout=timeout)
        r.raise_for_status()
    except requests.RequestException as exc:
        log.warning("DuckDuckGo token lookup failed for '%s': %s", dish_name, exc)
        return None

    match = re.search(r'vqd=([0-9-_]+)', r.text) or re.search(r'vqd="([^"]+)"', r.text)
    if not match:
        log.warning("Could not extract vqd token for '%s'", dish_name)
        return None
    vqd = match.group(1)

    # Step 2: query images endpoint
    search_url = (
        f"https://duckduckgo.com/i.js?l=us-en&o=json&q={urllib.parse.quote(query)}"
        f"&vqd={vqd}&f=,,,&p=1"
    )
    try:
        r = session.get(search_url, timeout=timeout)
        r.raise_for_status()
        data = r.json()
    except (requests.RequestException, ValueError) as exc:
        log.warning("DuckDuckGo image search request failed for '%s': %s", dish_name, exc)
        return None

    results = data.get("results", [])
    if not results:
        return None

    # Step 3: attempt downloading top candidate
    for item in results[:3]:
        img_url = item.get("image")
        if not img_url:
            continue
        try:
            img_r = session.get(img_url, timeout=timeout)
            if img_r.status_code == 200 and len(img_r.content) > 2048:
                # Validate that PIL can parse it as an image
                with Image.open(io.BytesIO(img_r.content)) as im:
                    im.verify()
                return img_r.content
        except Exception:
            continue

    return None
