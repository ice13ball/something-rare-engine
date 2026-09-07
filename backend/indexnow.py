# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""IndexNow notification — shared leaf helper.

Moved out of main.py (Task 3 of the backend vertical-split refactor). Imports
only stdlib + `httpx`, so any domain module or router can depend on this
without creating an import cycle back into main.py.
"""

import logging
import os

import httpx

log = logging.getLogger(__name__)

INDEXNOW_KEY = os.getenv("INDEXNOW_KEY", "")
SITE_HOST = "something-rare.com"


async def notify_indexnow(urls: list[str]):
    """Notify Bing/Google of updated URLs via IndexNow protocol."""
    if not INDEXNOW_KEY or not urls:
        return
    payload = {
        "host": SITE_HOST,
        "key": INDEXNOW_KEY,
        "keyLocation": f"https://{SITE_HOST}/{INDEXNOW_KEY}.txt",
        "urlList": urls[:10000],
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post("https://api.indexnow.org/indexnow", json=payload)
            log.info("IndexNow: submitted %d URLs, status %d", len(urls), resp.status_code)
    except Exception as exc:
        log.warning("IndexNow: notification failed: %s", exc)
