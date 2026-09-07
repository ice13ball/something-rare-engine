# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Emptying a cache directory without needing to own its parent.

`shutil.rmtree(d)` removes `d` itself, which requires write access to d's
PARENT. Every raster cache here lives directly under /var/cache, which is
root-owned, so the service could create and fill these directories but never
remove them. Measured on production 2026-09-02:

    WARNING seabed raster cache clear failed:
    [Errno 13] Permission denied: '/var/cache/abyssal-seabed-raster'

Three of the four call sites passed `ignore_errors=True` or swallowed the
exception, so the failure was invisible: a sync would "clear" the cache, the
clear would fail, and stale tiles would keep being served with nothing in the
log to say so.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

log = logging.getLogger(__name__)


def empty_dir(path: str) -> None:
    """Delete everything INSIDE `path`, leaving the directory itself in place.

    Needs write access only to `path`, which the service owns. Missing directory
    is not an error — there is nothing to clear. Anything else is logged loudly:
    a cache that cannot be cleared serves stale data, and that must not be quiet.
    """
    p = Path(path)
    if not p.is_dir():
        return
    for child in p.iterdir():
        try:
            shutil.rmtree(child) if child.is_dir() else child.unlink()
        except Exception as e:  # noqa: BLE001 — one entry, not the whole clear
            log.warning("cache clear: could not remove %s: %s", child, e)
