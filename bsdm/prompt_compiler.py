from __future__ import annotations

import logging
from typing import Any

from bsdm.cloudflare import CloudflareClient, CloudflareQuotaError

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
        if only:
            target = only.strip()
            if target.startswith("="):
                if entry["name"].strip().lower() != target[1:].strip().lower():
                    continue
            elif target.lower() != did.lower() and target.lower() not in entry["name"].lower():
                continue
        if not force and entry.get("prompt_compiled") and entry.get("prompt_compiler_rev", 0) >= COMPILER_REV:
            continue
        pending.append((did, entry))

    if limit is not None:
        pending = pending[:limit]

    count = 0
    for did, entry in pending:
        dish_name = entry.get("name", "Unknown")
        try:
            res = client.compile_dish_prompt(
                name=dish_name,
                ingredients=entry.get("ingredients", ""),
                tags=entry.get("tags", []),
                category=entry.get("category", "other"),
            )
            compiled_prompt = (res.get("prompt") or "").strip()
            if not compiled_prompt:
                log.warning("Empty compiled prompt for '%s'", dish_name)
                continue
            entry["prompt"] = compiled_prompt
            entry["negative"] = (res.get("negative") or "").strip()
            entry["prompt_compiled"] = True
            entry["prompt_compiler_rev"] = COMPILER_REV
            count += 1
            log.info("Compiled prompt for '%s'", dish_name)
        except CloudflareQuotaError as exc:
            log.warning("Cloudflare quota exceeded while compiling prompts: %s", exc)
            break
        except Exception as exc:
            log.warning("Failed to compile prompt for '%s': %s", dish_name, exc)

    return count
