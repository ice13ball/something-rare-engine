# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Shared TTL cache for serialized endpoint responses.

A generic mechanism, not domain data — which is why it is a leaf module rather
than living in main.py or being copied per domain. Consumers alias it as
`_cache` so their call sites stay byte-identical to the pre-refactor code:

    from response_cache import CACHE_TTL, store as _cache

Cleared wholesale by /admin/cache/clear.
"""
from __future__ import annotations

CACHE_TTL = 21600  # 6 hours

store: dict[str, tuple[float, bytes]] = {}


def clear() -> None:
    """Drop every cached response. Idempotent.

    Currently unused by any caller — main.py's admin_cache_clear() clears the
    store directly via its `_cache` alias (`_cache.clear()`). Kept intentionally
    as this module's documented API for dropping the cache without reaching
    into `store` directly; do not delete as dead code.
    """
    store.clear()
