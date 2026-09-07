# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import os
from datetime import datetime, timezone

import pytest

from backend.api_access.admin_crud import clamp_key_limits

UTC = timezone.utc


class _Org(dict):
    pass


def _org(**kw):
    base = dict(rate_limit_per_day_cap=1000, rate_limit_per_min_cap=60,
                expires_at=datetime(2027, 1, 1, tzinfo=UTC))
    base.update(kw)
    return base


def test_clamp_none_inherits_cap():
    d, m, e = clamp_key_limits(_org(), None, None, None)
    assert d == 1000 and m == 60 and e == datetime(2027, 1, 1, tzinfo=UTC)


def test_clamp_reduces_above_cap():
    d, m, _ = clamp_key_limits(_org(), 5000, 600, None)
    assert d == 1000 and m == 60


def test_clamp_keeps_below_cap():
    d, m, _ = clamp_key_limits(_org(), 200, 10, None)
    assert d == 200 and m == 10


def test_clamp_expiry_not_later_than_org():
    _, _, e = clamp_key_limits(_org(), None, None, datetime(2030, 1, 1, tzinfo=UTC))
    assert e == datetime(2027, 1, 1, tzinfo=UTC)


def test_clamp_uncapped_org_allows_any():
    org = _org(rate_limit_per_day_cap=None, rate_limit_per_min_cap=None, expires_at=None)
    d, m, e = clamp_key_limits(org, 99999, 9999, datetime(2030, 1, 1, tzinfo=UTC))
    assert d == 99999 and m == 9999 and e == datetime(2030, 1, 1, tzinfo=UTC)


TEST_DB = os.getenv("TEST_DATABASE_URL")


@pytest.mark.asyncio
@pytest.mark.skipif(not TEST_DB, reason="TEST_DATABASE_URL not set")
async def test_create_key_enforces_max_keys_and_returns_raw_once():
    import asyncpg
    from backend.api_access.schema import ensure_api_access_schema
    from backend.api_access.admin_crud import create_org, create_key
    from backend.api_access.keys import hash_key
    pool = await asyncpg.create_pool(TEST_DB, min_size=1, max_size=2)
    try:
        try:
            await pool.execute("CREATE SCHEMA IF NOT EXISTS api_access")
        except Exception:
            pass
        await ensure_api_access_schema(pool)
        await pool.execute("DELETE FROM api_access.organizations WHERE name LIKE 'test-org-%'")
        org_id = await create_org(pool, name="test-org-1", max_keys=1)
        kid, raw = await create_key(pool, org_id, "alice", None, None, None, "tester")
        assert raw.startswith("ak_live_")
        stored = await pool.fetchval(
            "SELECT key_hash FROM api_access.api_keys WHERE id=$1", kid
        )
        assert stored == hash_key(raw)
        with pytest.raises(ValueError):
            await create_key(pool, org_id, "bob", None, None, None, "tester")  # max_keys=1
    finally:
        await pool.close()


@pytest.mark.asyncio
@pytest.mark.skipif(not TEST_DB, reason="TEST_DATABASE_URL not set")
async def test_delete_org_cascades_keys_and_guards_internal():
    import asyncpg
    from backend.api_access.schema import ensure_api_access_schema
    from backend.api_access.admin_crud import create_org, create_key, delete_org
    pool = await asyncpg.create_pool(TEST_DB, min_size=1, max_size=2)
    try:
        try:
            await pool.execute("CREATE SCHEMA IF NOT EXISTS api_access")
        except Exception:
            pass
        await ensure_api_access_schema(pool)
        await pool.execute("DELETE FROM api_access.organizations WHERE name LIKE 'test-org-%'")

        # delete cascades the org's keys
        org_id = await create_org(pool, name="test-org-del")
        kid, _ = await create_key(pool, org_id, "carol", None, None, None, "tester")
        assert await delete_org(pool, org_id=org_id) is True
        assert await pool.fetchval(
            "SELECT COUNT(*) FROM api_access.organizations WHERE id=$1", org_id) == 0
        assert await pool.fetchval(
            "SELECT COUNT(*) FROM api_access.api_keys WHERE id=$1", kid) == 0

        # deleting a non-existent org returns False (not an error)
        assert await delete_org(pool, org_id=org_id) is False

        # the internal org is protected
        internal_id = await create_org(pool, name="_internal")
        try:
            with pytest.raises(ValueError):
                await delete_org(pool, org_id=internal_id)
        finally:
            await pool.execute("DELETE FROM api_access.organizations WHERE id=$1", internal_id)
    finally:
        await pool.close()


@pytest.mark.asyncio
@pytest.mark.skipif(not TEST_DB, reason="TEST_DATABASE_URL not set")
async def test_delete_key_erases_history_and_guards_internal():
    import asyncpg
    from datetime import datetime, timezone
    from backend.api_access.schema import ensure_api_access_schema
    from backend.api_access.logstore import ensure_log_schema
    from backend.api_access.admin_crud import create_org, create_key, delete_key
    pool = await asyncpg.create_pool(TEST_DB, min_size=1, max_size=2)
    try:
        try:
            await pool.execute("CREATE SCHEMA IF NOT EXISTS api_access")
        except Exception:
            pass
        await ensure_api_access_schema(pool)
        await ensure_log_schema(pool)
        await pool.execute("DELETE FROM api_access.organizations WHERE name LIKE 'test-org-%'")

        org_id = await create_org(pool, name="test-org-delkey")
        kid, _ = await create_key(pool, org_id, "dave", None, None, None, "tester")

        # seed history across all three history surfaces
        await pool.execute(
            "INSERT INTO api_access.request_log (key_id, org_id, ts, endpoint_label, status_code) "
            "VALUES ($1,$2,$3,'/x',200)", kid, org_id, datetime.now(timezone.utc))
        await pool.execute(
            "INSERT INTO api_access.usage_rollup (key_id, hour, endpoint_label, request_count) "
            "VALUES ($1, date_trunc('hour', NOW()), '/x', 1)", kid)
        await pool.execute(
            "INSERT INTO api_access.leak_flags (key_id, flag_type, severity) "
            "VALUES ($1,'spike','warn')", kid)

        assert await delete_key(pool, key_id=kid) is True
        assert await pool.fetchval("SELECT COUNT(*) FROM api_access.api_keys WHERE id=$1", kid) == 0
        assert await pool.fetchval("SELECT COUNT(*) FROM api_access.request_log WHERE key_id=$1", kid) == 0
        assert await pool.fetchval("SELECT COUNT(*) FROM api_access.usage_rollup WHERE key_id=$1", kid) == 0
        assert await pool.fetchval("SELECT COUNT(*) FROM api_access.leak_flags WHERE key_id=$1", kid) == 0

        # unknown id → False
        assert await delete_key(pool, key_id=kid) is False

        # internal keys are protected
        ikid, _ = await create_key(pool, org_id, "internal", None, None, None, "tester")
        await pool.execute("UPDATE api_access.api_keys SET is_internal=TRUE WHERE id=$1", ikid)
        with pytest.raises(ValueError):
            await delete_key(pool, key_id=ikid)

        await pool.execute("DELETE FROM api_access.organizations WHERE id=$1", org_id)
    finally:
        await pool.close()
