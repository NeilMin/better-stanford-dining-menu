from __future__ import annotations

import logging
from typing import Any

from bsdm.cloudflare import CloudflareClient

log = logging.getLogger(__name__)

COMPILER_REV = 1


def compile_pending(
    catalog: dict[str, Any],
    client: CloudflareClient,
    limit: int | None = None,
    force: bool = False,
    only: str | None = None,
) -> int:
    """Compile structured prompts for catalog dishes missing compiled prompts."""
    if not client.is_configured():
        log.warning("CloudflareClient not configured; skipping prompt compilation")
        return 0

    pending = []
    for did, entry in catalog.items():
        if not entry.get("needs_image"):
            continue
        if only and only.lower() not in entry["name"].lower():
            continue
        if not force and entry.get("prompt_compiled") and entry.get("prompt_compiler_rev", 0) >= COMPILER_REV:
            continue
        pending.append((did, entry))

    if limit is not None:
        pending = pending[:limit]

    count = 0
    for did, entry in pending:
        try:
            res = client.compile_dish_prompt(
                name=entry["name"],
                ingredients=entry.get("ingredients", ""),
                tags=entry.get("tags", []),
                category=entry.get("category", "other"),
            )
            entry["prompt"] = res["prompt"]
            entry["negative"] = res["negative"]
            entry["prompt_compiled"] = True
            entry["prompt_compiler_rev"] = COMPILER_REV
            count += 1
            log.info("Compiled prompt for '%s'", entry["name"])
        except Exception as exc:
            log.warning("Failed to compile prompt for '%s': %s", entry["name"], exc)

    return count
