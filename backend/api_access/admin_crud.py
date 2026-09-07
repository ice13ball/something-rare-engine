# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

from __future__ import annotations

from datetime import datetime

import db as _db
from .auth import bust_key_cache
from .keys import generate_key, hash_key, key_prefix


_KEY_COLS = ("k.id, k.org_id, k.member_label, k.key_prefix, k.scopes, "
             "k.rate_limit_per_day, k.rate_limit_per_min, k.expires_at, k.status, "
             "k.is_internal, k.created_at, k.created_by, k.last_used_at, k.notes, "
             "o.name AS org_name")


def clamp_key_limits(org, day, minute, expires_at):
    """Clamp per-key values to org caps. None per-key value inherits the cap."""
    cap_d = org["rate_limit_per_day_cap"]
    cap_m = org["rate_limit_per_min_cap"]
    cap_e = org["expires_at"]

    def _clamp_int(val, cap):
        if cap is None:
            return val
        if val is None:
            return cap
        return min(val, cap)

    d = _clamp_int(day, cap_d)
    m = _clamp_int(minute, cap_m)
    if cap_e is None:
        e = expires_at
    elif expires_at is None:
        e = cap_e
    else:
        e = min(expires_at, cap_e)
    return d, m, e


# ── orgs ──────────────────────────────────────────────────────────────────────
async def list_orgs(pool=None):
    pool = pool or _db.pool
    async with pool.acquire() as conn:
        return await conn.fetch("SELECT * FROM api_access.organizations ORDER BY created_at DESC")


async def create_org(pool=None, *, name, contact=None, scopes=None,
                     rate_limit_per_day_cap=None, rate_limit_per_min_cap=None,
                     max_keys=None, expires_at=None, created_by="super_admin", notes=None) -> int:
    pool = pool or _db.pool
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO api_access.organizations
                (name, contact, scopes, rate_limit_per_day_cap, rate_limit_per_min_cap,
                 max_keys, expires_at, created_by, notes)
            VALUES ($1,$2,COALESCE($3::text[],'{all}'::text[]),$4,$5,$6,$7,$8,$9) RETURNING id
            """,
            name, contact, scopes, rate_limit_per_day_cap, rate_limit_per_min_cap,
            max_keys, expires_at, created_by, notes,
        )


async def update_org(pool=None, *, org_id, **fields):
    pool = pool or _db.pool
    allowed = {"contact", "scopes", "rate_limit_per_day_cap", "rate_limit_per_min_cap",
               "max_keys", "expires_at", "status", "notes"}
    sets, args = [], []
    for k, v in fields.items():
        if k in allowed:
            args.append(v)
            sets.append(f"{k} = ${len(args)}")
    if not sets:
        return
    args.append(org_id)
    async with pool.acquire() as conn:
        await conn.execute(
            f"UPDATE api_access.organizations SET {', '.join(sets)} WHERE id = ${len(args)}", *args
        )
    bust_key_cache()


async def delete_org(pool=None, *, org_id) -> bool:
    """Hard-delete an org. Cascades to its api_keys, leak_flags, and org_admin
    users via ON DELETE CASCADE. Historical request_log/usage_rollup rows (no FK)
    are left as orphaned-by-key_id history. Refuses to delete the '_internal' org
    that holds the frontend BFF key. Returns True if a row was deleted, False if
    no org with that id exists.
    """
    pool = pool or _db.pool
    async with pool.acquire() as conn:
        name = await conn.fetchval(
            "SELECT name FROM api_access.organizations WHERE id = $1", org_id
        )
        if name is None:
            return False
        if name == "_internal":
            raise ValueError("the internal organization cannot be deleted")
        await conn.execute("DELETE FROM api_access.organizations WHERE id = $1", org_id)
    bust_key_cache()
    return True


# ── keys ──────────────────────────────────────────────────────────────────────
async def list_keys(pool=None, org_id=None):
    pool = pool or _db.pool
    async with pool.acquire() as conn:
        if org_id is None:
            return await conn.fetch(
                f"SELECT {_KEY_COLS} FROM api_access.api_keys k "
                "JOIN api_access.organizations o ON o.id = k.org_id ORDER BY k.created_at DESC"
            )
        return await conn.fetch(
            f"SELECT {_KEY_COLS} FROM api_access.api_keys k "
            "JOIN api_access.organizations o ON o.id = k.org_id "
            "WHERE k.org_id = $1 ORDER BY k.created_at DESC",
            org_id,
        )


async def create_key(pool, org_id, member_label, day, minute, expires_at, created_by):
    pool = pool or _db.pool
    async with pool.acquire() as conn:
        async with conn.transaction():
            org = await conn.fetchrow(
                "SELECT * FROM api_access.organizations WHERE id = $1 FOR UPDATE", org_id
            )
            if org is None:
                raise ValueError("organization not found")
            if org["max_keys"] is not None:
                active = await conn.fetchval(
                    "SELECT COUNT(*) FROM api_access.api_keys "
                    "WHERE org_id = $1 AND status = 'active'",
                    org_id,
                )
                if active >= org["max_keys"]:
                    raise ValueError("max_keys reached for organization")
            d, m, e = clamp_key_limits(org, day, minute, expires_at)
            raw = generate_key()
            kid = await conn.fetchval(
                """
                INSERT INTO api_access.api_keys
                    (org_id, member_label, key_hash, key_prefix, rate_limit_per_day,
                     rate_limit_per_min, expires_at, created_by)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING id
                """,
                org_id, member_label, hash_key(raw), key_prefix(raw), d, m, e, created_by,
            )
    bust_key_cache()
    return kid, raw


async def update_key(pool=None, *, key_id, **fields):
    pool = pool or _db.pool
    allowed = {"member_label", "rate_limit_per_day", "rate_limit_per_min",
               "expires_at", "status", "notes"}
    sets, args = [], []
    for k, v in fields.items():
        if k in allowed:
            args.append(v)
            sets.append(f"{k} = ${len(args)}")
    if not sets:
        return
    args.append(key_id)
    async with pool.acquire() as conn:
        await conn.execute(
            f"UPDATE api_access.api_keys SET {', '.join(sets)} WHERE id = ${len(args)}", *args
        )
    bust_key_cache()


async def revoke_key(pool=None, *, key_id):
    pool = pool or _db.pool
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE api_access.api_keys SET status = 'revoked' WHERE id = $1", key_id
        )
    bust_key_cache()


async def delete_key(pool=None, *, key_id) -> bool:
    """Permanently delete a key AND erase its request history: request_log rows
    (across all daily partitions — the DELETE on the partitioned parent cascades),
    usage_rollup rows, and leak_flags (via FK ON DELETE CASCADE). Refuses to
    delete an is_internal key (the frontend BFF key). Returns True if a key row
    was deleted, False if no key with that id exists.
    """
    pool = pool or _db.pool
    async with pool.acquire() as conn:
        rec = await conn.fetchrow(
            "SELECT is_internal FROM api_access.api_keys WHERE id = $1", key_id
        )
        if rec is None:
            return False
        if rec["is_internal"]:
            raise ValueError("internal keys cannot be deleted")
        async with conn.transaction():
            await conn.execute("DELETE FROM api_access.request_log WHERE key_id = $1", key_id)
            await conn.execute("DELETE FROM api_access.usage_rollup WHERE key_id = $1", key_id)
            await conn.execute("DELETE FROM api_access.api_keys WHERE id = $1", key_id)
    bust_key_cache()
    return True
