# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

from __future__ import annotations

import asyncio
import logging
import os

log = logging.getLogger(__name__)

# No built-in path. An alert helper is deployment-specific, and a default
# pointing at one maintainer's home directory is only ever correct on one host —
# everywhere else it is a path that happens not to exist, which this module
# treats as "skip the alert". Requiring NOTIFY_SCRIPT makes the unconfigured
# case say so instead of looking like a delivery that quietly found nothing.
DEFAULT_SCRIPT = ""


async def notify_telegram(message: str, title: str = "Abyssal API-key alert",
                          *, script: str | None = None) -> bool:
    """Send a Telegram alert via notify.sh. Never raises; returns success bool."""
    path = script or os.getenv("NOTIFY_SCRIPT", DEFAULT_SCRIPT)
    if not path:
        log.warning("notify_telegram: NOTIFY_SCRIPT is unset; alert not sent")
        return False
    if not os.path.exists(path):
        log.warning("notify_telegram: script not found at %s; skipping alert", path)
        return False
    try:
        proc = await asyncio.create_subprocess_exec(
            path, message, title,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        rc = await asyncio.wait_for(proc.wait(), timeout=15)
        if rc != 0:
            log.warning("notify_telegram: %s exited %s", path, rc)
        return rc == 0
    except Exception:
        log.exception("notify_telegram failed")
        return False
