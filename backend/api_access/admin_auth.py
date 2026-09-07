# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

import bcrypt

import db as _db


# ── pure primitives ───────────────────────────────────────────────────────────
def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode("utf-8"), hashed.encode("ascii"))
    except Exception:
        return False


# Precomputed throwaway bcrypt hash (same default cost as real password hashes).
# Used to equalize login timing for unknown / ineligible / locked usernames so a
# valid account can't be detected by response latency (user enumeration).
_DUMMY_PW_HASH = bcrypt.hashpw(b"timing-equalizer", bcrypt.gensalt()).decode("ascii")


def dummy_verify(pw: str) -> bool:
    """Run one bcrypt verification against a throwaway hash so the login miss path
    costs the same as a real password check. Always returns False."""
    verify_password(pw, _DUMMY_PW_HASH)
    return False


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def lockout_state(failed: int, locked_until: datetime | None, now: datetime,
                  *, max_failed: int = 5, lock_minutes: int = 15) -> tuple[bool, datetime | None]:
    """Decide whether an account is locked. Returns (is_locked, new_locked_until).

    - An unexpired existing lock keeps the account locked (returns that window).
    - Reaching max_failed sets a fresh lock window.
    - Otherwise unlocked.
    """
    if locked_until is not None and locked_until > now:
        return True, locked_until
    if failed >= max_failed:
        return True, now + timedelta(minutes=lock_minutes)
    return False, None


# ── schema ────────────────────────────────────────────────────────────────────
_ADMIN_DDL = """
CREATE TABLE IF NOT EXISTS api_access.admin_users (
    id            BIGSERIAL PRIMARY KEY,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('super_admin','org_admin')),
    org_id        BIGINT REFERENCES api_access.organizations(id) ON DELETE CASCADE,
    status        TEXT NOT NULL DEFAULT 'active',
    failed_logins INTEGER NOT NULL DEFAULT 0,
    locked_until  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by    TEXT,
    last_login_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS api_access.admin_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    BIGINT NOT NULL REFERENCES api_access.admin_users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    ip         INET
);
CREATE INDEX IF NOT EXISTS admin_sessions_user ON api_access.admin_sessions(user_id);
"""


async def ensure_admin_schema(pool=None) -> None:
    pool = pool or _db.pool
    async with pool.acquire() as conn:
        await conn.execute("SET lock_timeout = '10s'")
        await conn.execute(_ADMIN_DDL)


# ── DB operations ────────────────────────────────────────────────────────────
async def create_admin_user(pool, username, password, role, org_id=None,
                            created_by="system") -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO api_access.admin_users (username, password_hash, role, org_id, created_by)
            VALUES ($1, $2, $3, $4, $5) RETURNING id
            """,
            username, hash_password(password), role, org_id, created_by,
        )


async def list_org_admins(pool, org_id):
    """All org_admin users belonging to one organization, newest first.
    Never returns password_hash."""
    async with pool.acquire() as conn:
        return await conn.fetch(
            """
            SELECT id, username, status, created_at, last_login_at
            FROM api_access.admin_users
            WHERE org_id = $1 AND role = 'org_admin'
            ORDER BY created_at DESC
            """,
            org_id,
        )


async def update_admin_password(pool, user_id, new_password) -> None:
    """Set a new bcrypt password hash for an admin user."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE api_access.admin_users SET password_hash = $2 WHERE id = $1",
            user_id, hash_password(new_password),
        )


async def delete_other_sessions(pool, user_id, keep_raw_token) -> None:
    """Revoke every session for a user except the one identified by keep_raw_token
    (used after a password change so the actor stays logged in but other devices
    are forced to re-authenticate)."""
    keep_hash = hash_token(keep_raw_token) if keep_raw_token else ""
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM api_access.admin_sessions WHERE user_id = $1 AND token_hash <> $2",
            user_id, keep_hash,
        )


async def delete_all_sessions(pool, user_id) -> int:
    """Revoke EVERY session for a user — all devices including the caller's. Used by the
    'sign out everywhere' control so a user who suspects a stolen cookie can invalidate
    all live sessions at once. Returns the number of sessions removed."""
    async with pool.acquire() as conn:
        status = await conn.execute(
            "DELETE FROM api_access.admin_sessions WHERE user_id = $1", user_id
        )
    return int(status.split()[-1])


async def delete_org_admin(pool, org_id, user_id) -> bool:
    """Delete one org_admin user belonging to a given org. Scoped to role and
    org_id so a crafted id can't remove a super_admin or another org's admin.
    The user's admin_sessions are removed via FK ON DELETE CASCADE. Returns True
    if a row was deleted."""
    async with pool.acquire() as conn:
        status = await conn.execute(
            "DELETE FROM api_access.admin_users "
            "WHERE id = $1 AND org_id = $2 AND role = 'org_admin'",
            user_id, org_id,
        )
    return status.split()[-1] != "0"


async def get_admin_by_username(pool, username):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM api_access.admin_users WHERE username = $1", username
        )


async def register_login_result(pool, user_id, success: bool, now) -> None:
    async with pool.acquire() as conn:
        if success:
            await conn.execute(
                "UPDATE api_access.admin_users SET failed_logins = 0, locked_until = NULL, "
                "last_login_at = $2 WHERE id = $1",
                user_id, now,
            )
            return
        # Atomic increment + conditional lock — no read-modify-write race under
        # concurrent failed logins. Thresholds match lockout_state defaults (5 / 15 min).
        lock_at = now + timedelta(minutes=15)
        await conn.execute(
            """
            UPDATE api_access.admin_users
            SET failed_logins = failed_logins + 1,
                locked_until = CASE WHEN failed_logins + 1 >= 5 THEN $2 ELSE locked_until END
            WHERE id = $1
            """,
            user_id, lock_at,
        )


async def create_session(pool, user_id, ip, ttl_hours: int = 12) -> str:
    from datetime import datetime, timedelta, timezone
    raw = new_session_token()
    expires = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO api_access.admin_sessions (token_hash, user_id, expires_at, ip) "
            "VALUES ($1, $2, $3, $4::inet)",
            hash_token(raw), user_id, expires, ip,
        )
    return raw


async def get_session_admin(pool, raw_token, now):
    if not raw_token:
        return None
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """
            SELECT u.* FROM api_access.admin_sessions s
            JOIN api_access.admin_users u ON u.id = s.user_id
            WHERE s.token_hash = $1 AND s.expires_at > $2 AND u.status = 'active'
            """,
            hash_token(raw_token), now,
        )


async def delete_session(pool, raw_token) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM api_access.admin_sessions WHERE token_hash = $1", hash_token(raw_token)
        )


async def bootstrap_super_admin(pool, username, password) -> bool:
    """Create the first super_admin if none exists. Idempotent + race-safe. Returns True if created."""
    if not username or not password:
        return False
    async with pool.acquire() as conn:
        created = await conn.fetchval(
            """
            INSERT INTO api_access.admin_users (username, password_hash, role, created_by)
            SELECT $1, $2, 'super_admin', 'bootstrap'
            WHERE NOT EXISTS (SELECT 1 FROM api_access.admin_users WHERE role = 'super_admin')
            RETURNING id
            """,
            username, hash_password(password),
        )
    return created is not None
