# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

from __future__ import annotations

import asyncio
import hmac
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Awaitable, Callable

from .keys import hash_key

if TYPE_CHECKING:
    from .quota import QuotaTracker


@dataclass(frozen=True)
class KeyRecord:
    id: int
    org_id: int
    status: str
    expires_at: datetime | None
    scopes: tuple[str, ...]
    is_internal: bool
    rate_limit_per_min: int | None = None
    rate_limit_per_day: int | None = None


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    status_code: int   # 200 when allowed, 403 otherwise
    reason: str


def evaluate_access(record: KeyRecord | None, now: datetime) -> AccessDecision:
    """Pure decision: is this key valid right now? (status + expiry only in v1).

    Quota and scope enforcement arrive in later phases; scopes are 'all' in v1.
    """
    if record is None:
        return AccessDecision(False, 403, "unknown_key")
    if record.status != "active":
        return AccessDecision(False, 403, "revoked")
    if record.expires_at is not None and record.expires_at <= now:
        return AccessDecision(False, 403, "expired")
    return AccessDecision(True, 200, "ok")


class KeyCache:
    """In-memory {key_hash: KeyRecord} cache with a TTL, refreshed via `loader`.

    Holds ALL keys (including revoked/expired); freshness on mutation comes from
    bust(). evaluate_access() does the active/expiry filtering at request time.
    """

    def __init__(self, loader: Callable[[], Awaitable[dict[str, KeyRecord]]], ttl: float = 60.0):
        self._loader = loader
        self._ttl = ttl
        self._data: dict[str, KeyRecord] = {}
        self._loaded_at: float = 0.0
        self._lock = asyncio.Lock()

    async def get(self, key_hash: str) -> KeyRecord | None:
        await self._maybe_refresh()
        return self._data.get(key_hash)

    async def _maybe_refresh(self) -> None:
        if self._data and (time.monotonic() - self._loaded_at) < self._ttl:
            return
        async with self._lock:
            if self._data and (time.monotonic() - self._loaded_at) < self._ttl:
                return
            self._data = await self._loader()
            self._loaded_at = time.monotonic()

    def bust(self) -> None:
        """Force the next get() to reload (call after any key/org mutation)."""
        self._loaded_at = 0.0
        self._data = {}


# ── module-global cache (used by the FastAPI dependency) ──────────────────────
_cache: KeyCache | None = None


def init_key_cache(pool) -> None:
    """Wire the global cache to a loader bound to the live asyncpg pool."""
    global _cache
    from .store import load_active_keys
    _cache = KeyCache(lambda: load_active_keys(pool))


def bust_key_cache() -> None:
    if _cache is not None:
        _cache.bust()


class _Unset:
    pass


_UNSET = _Unset()


async def resolve_and_check(
    raw: str,
    *,
    cache: KeyCache | None = None,
    now: datetime | None = None,
    env_key: str | _Unset = _UNSET,
    quota_tracker: "QuotaTracker | None" = None,
) -> tuple[AccessDecision, KeyRecord | None]:
    """Resolve a raw X-API-Key to an access decision.

    Order: cache lookup -> evaluate_access -> quota check. The frontend env key
    is always allowed as an emergency fallback (DB down, or key not yet seeded),
    but non-env keys fail closed when the cache/DB is unavailable.
    Internal keys (is_internal=True) and env-fallback paths are exempt from quota.
    """
    now = now or datetime.now(timezone.utc)
    if isinstance(env_key, _Unset):
        env_key = os.getenv("ABYSSAL_API_KEY")
    use = cache if cache is not None else _cache

    record: KeyRecord | None = None
    if use is not None:
        try:
            record = await use.get(hash_key(raw))
        except Exception:
            if env_key and hmac.compare_digest(raw.encode(), env_key.encode()):
                return AccessDecision(True, 200, "env_fallback"), None
            return AccessDecision(False, 403, "unavailable"), None

    decision = evaluate_access(record, now)
    if decision.allowed:
        if record is not None and not record.is_internal and (
            record.rate_limit_per_min is not None or record.rate_limit_per_day is not None
        ):
            from .quota import _quota
            tracker = quota_tracker if quota_tracker is not None else _quota
            if not tracker.check_and_count(
                record.id, record.rate_limit_per_min, record.rate_limit_per_day, now
            ):
                return AccessDecision(False, 429, "quota_exceeded"), record
        return decision, record
    if env_key and hmac.compare_digest(raw.encode(), env_key.encode()):
        return AccessDecision(True, 200, "env_fallback"), record
    return decision, record
