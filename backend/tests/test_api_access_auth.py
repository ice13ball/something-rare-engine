# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from backend.api_access.auth import (
    AccessDecision,
    KeyCache,
    KeyRecord,
    evaluate_access,
    resolve_and_check,
)
from backend.api_access.keys import hash_key

UTC = timezone.utc
NOW = datetime(2026, 6, 20, 12, 0, tzinfo=UTC)


def _rec(**kw) -> KeyRecord:
    base = dict(id=1, org_id=10, status="active", expires_at=None,
                scopes=("all",), is_internal=False)
    base.update(kw)
    return KeyRecord(**base)


# ── evaluate_access (pure) ────────────────────────────────────────────────────
def test_evaluate_access_unknown_key_403():
    d = evaluate_access(None, NOW)
    assert d == AccessDecision(False, 403, "unknown_key")


def test_evaluate_access_active_no_expiry_allowed():
    assert evaluate_access(_rec(), NOW).allowed is True


def test_evaluate_access_revoked_403():
    d = evaluate_access(_rec(status="revoked"), NOW)
    assert d.allowed is False and d.status_code == 403 and d.reason == "revoked"


def test_evaluate_access_expired_403():
    d = evaluate_access(_rec(expires_at=NOW - timedelta(seconds=1)), NOW)
    assert d.allowed is False and d.reason == "expired"


def test_evaluate_access_future_expiry_allowed():
    assert evaluate_access(_rec(expires_at=NOW + timedelta(days=1)), NOW).allowed


# ── KeyCache ──────────────────────────────────────────────────────────────────
def test_key_cache_loads_once_within_ttl_then_refreshes_after_ttl():
    calls = {"n": 0}
    rec = _rec()

    async def loader():
        calls["n"] += 1
        return {hash_key("k"): rec}

    async def run():
        cache = KeyCache(loader, ttl=1000.0)
        assert await cache.get(hash_key("k")) is rec
        assert await cache.get(hash_key("k")) is rec
        assert calls["n"] == 1          # cached within ttl
        cache.bust()
        assert await cache.get(hash_key("k")) is rec
        assert calls["n"] == 2          # bust forced a reload

    asyncio.run(run())


def test_key_cache_unknown_hash_returns_none():
    async def loader():
        return {}

    async def run():
        cache = KeyCache(loader, ttl=1000.0)
        assert await cache.get(hash_key("missing")) is None

    asyncio.run(run())


# ── resolve_and_check ─────────────────────────────────────────────────────────
def test_resolve_and_check_valid_key_allowed():
    rec = _rec()

    async def loader():
        return {hash_key("good"): rec}

    async def run():
        cache = KeyCache(loader, ttl=1000.0)
        decision, out = await resolve_and_check("good", cache=cache, now=NOW, env_key="ENVKEY")
        assert decision.allowed and out is rec

    asyncio.run(run())


def test_resolve_and_check_unknown_key_403():
    async def loader():
        return {}

    async def run():
        cache = KeyCache(loader, ttl=1000.0)
        decision, out = await resolve_and_check("nope", cache=cache, now=NOW, env_key="ENVKEY")
        assert decision.allowed is False and decision.status_code == 403

    asyncio.run(run())


def test_resolve_and_check_env_fallback_when_key_missing_from_db():
    async def loader():
        return {}                       # env key not yet seeded

    async def run():
        cache = KeyCache(loader, ttl=1000.0)
        decision, out = await resolve_and_check("ENVKEY", cache=cache, now=NOW, env_key="ENVKEY")
        assert decision.allowed and decision.reason == "env_fallback"

    asyncio.run(run())


def test_resolve_and_check_env_fallback_when_loader_raises():
    async def loader():
        raise RuntimeError("db down")

    async def run():
        cache = KeyCache(loader, ttl=1000.0)
        decision, _ = await resolve_and_check("ENVKEY", cache=cache, now=NOW, env_key="ENVKEY")
        assert decision.allowed and decision.reason == "env_fallback"
        # a non-env key fails closed when the DB is down
        decision2, _ = await resolve_and_check("other", cache=cache, now=NOW, env_key="ENVKEY")
        assert decision2.allowed is False and decision2.status_code == 403

    asyncio.run(run())
