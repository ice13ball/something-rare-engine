# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import os
from datetime import datetime, timedelta, timezone

import pytest

from backend.api_access.admin_auth import (
    hash_password, verify_password, new_session_token, hash_token, lockout_state,
)

TEST_DB = os.getenv("TEST_DATABASE_URL")

UTC = timezone.utc
NOW = datetime(2026, 6, 20, 12, 0, tzinfo=UTC)


def test_password_hash_roundtrip():
    h = hash_password("s3cret-pw")
    assert h != "s3cret-pw"
    assert verify_password("s3cret-pw", h) is True
    assert verify_password("wrong", h) is False


def test_password_hash_is_salted_unique():
    assert hash_password("same") != hash_password("same")


def test_session_token_unique_and_hash_deterministic():
    a, b = new_session_token(), new_session_token()
    assert a != b and len(a) >= 32
    assert hash_token(a) == hash_token(a) and len(hash_token(a)) == 64
    assert hash_token(a) != hash_token(b)


def test_lockout_triggers_after_threshold():
    locked, until = lockout_state(5, None, NOW, max_failed=5, lock_minutes=15)
    assert locked is True
    assert until == NOW + timedelta(minutes=15)


def test_lockout_not_yet_at_threshold():
    locked, until = lockout_state(2, None, NOW, max_failed=5)
    assert locked is False and until is None


def test_lockout_respects_existing_window():
    future = NOW + timedelta(minutes=5)
    locked, until = lockout_state(5, future, NOW)
    assert locked is True and until == future


def test_lockout_expired_window_clears():
    past = NOW - timedelta(minutes=1)
    locked, until = lockout_state(1, past, NOW)
    assert locked is False


def test_verify_password_malformed_hash_returns_false():
    assert verify_password("pw", "not-a-bcrypt-hash") is False
    assert verify_password("pw", "") is False


def test_verify_password_non_string_hash_is_safe():
    assert verify_password("pw", None) is False  # type: ignore[arg-type]
    assert verify_password("pw", 12345) is False  # type: ignore[arg-type]


@pytest.mark.asyncio
@pytest.mark.skipif(not TEST_DB, reason="TEST_DATABASE_URL not set")
async def test_admin_user_session_lifecycle():
    import asyncpg
    from datetime import datetime, timezone
    from backend.api_access.schema import ensure_api_access_schema
    from backend.api_access.admin_auth import (
        ensure_admin_schema, create_admin_user, get_admin_by_username,
        create_session, get_session_admin, delete_session, register_login_result,
        bootstrap_super_admin,
    )
    pool = await asyncpg.create_pool(TEST_DB, min_size=1, max_size=2)
    try:
        try:
            await pool.execute("CREATE SCHEMA IF NOT EXISTS api_access")
        except Exception:
            pass
        await ensure_api_access_schema(pool)
        await ensure_admin_schema(pool)
        await pool.execute("DELETE FROM api_access.admin_users WHERE username LIKE 'test-%'")

        uid = await create_admin_user(pool, "test-op@example.com", "pw123456", "super_admin")
        assert isinstance(uid, int)
        rec = await get_admin_by_username(pool, "test-op@example.com")
        assert rec["role"] == "super_admin" and rec["username"] == "test-op@example.com"

        now = datetime.now(timezone.utc)
        tok = await create_session(pool, uid, "100.85.0.1", ttl_hours=12)
        admin = await get_session_admin(pool, tok, now)
        assert admin is not None and admin["id"] == uid

        await delete_session(pool, tok)
        assert await get_session_admin(pool, tok, now) is None

        # bootstrap is idempotent: a super_admin now exists → returns False
        assert await bootstrap_super_admin(pool, "test-op@example.com", "pw") is False
    finally:
        await pool.close()


@pytest.mark.asyncio
@pytest.mark.skipif(not TEST_DB, reason="TEST_DATABASE_URL not set")
async def test_delete_org_admin_scoped_and_cascades_sessions():
    import asyncpg
    from datetime import datetime, timezone
    from backend.api_access.schema import ensure_api_access_schema
    from backend.api_access.admin_crud import create_org
    from backend.api_access.admin_auth import (
        ensure_admin_schema, create_admin_user, create_session,
        get_session_admin, delete_org_admin,
    )
    pool = await asyncpg.create_pool(TEST_DB, min_size=1, max_size=2)
    try:
        try:
            await pool.execute("CREATE SCHEMA IF NOT EXISTS api_access")
        except Exception:
            pass
        await ensure_api_access_schema(pool)
        await ensure_admin_schema(pool)
        await pool.execute("DELETE FROM api_access.admin_users WHERE username LIKE 'test-oa-%'")
        await pool.execute("DELETE FROM api_access.organizations WHERE name LIKE 'test-org-%'")

        org_id = await create_org(pool, name="test-org-oa")
        uid = await create_admin_user(pool, "test-oa-1@example.com", "pw123456", "org_admin", org_id)
        tok = await create_session(pool, uid, "100.85.0.2", ttl_hours=8)
        now = datetime.now(timezone.utc)
        assert await get_session_admin(pool, tok, now) is not None

        # wrong org_id does not match → no delete
        assert await delete_org_admin(pool, org_id + 9999, uid) is False
        # correct scope deletes the row and cascades the session
        assert await delete_org_admin(pool, org_id, uid) is True
        assert await pool.fetchval(
            "SELECT COUNT(*) FROM api_access.admin_users WHERE id=$1", uid) == 0
        assert await get_session_admin(pool, tok, now) is None

        # a super_admin cannot be removed via this org-scoped path
        sid = await create_admin_user(pool, "test-oa-super@example.com", "pw123456", "super_admin")
        assert await delete_org_admin(pool, org_id, sid) is False
        await pool.execute("DELETE FROM api_access.admin_users WHERE id=$1", sid)
        await pool.execute("DELETE FROM api_access.organizations WHERE id=$1", org_id)
    finally:
        await pool.close()
