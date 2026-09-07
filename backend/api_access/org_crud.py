# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

# backend/api_access/org_crud.py
from __future__ import annotations

import db as _db
from . import admin_crud
from .admin_crud import _KEY_COLS, clamp_key_limits
from .auth import bust_key_cache


async def list_keys_for_org(pool, org_id):
    pool = pool or _db.pool
    async with pool.acquire() as conn:
        return await conn.fetch(
            f"SELECT {_KEY_COLS} FROM api_access.api_keys k "
            "JOIN api_access.organizations o ON o.id = k.org_id "
            "WHERE k.org_id = $1 ORDER BY k.created_at DESC",
            org_id,
        )


async def create_key_for_org(pool, org_id, member_label, day, minute, expires_at, created_by):
    # Reuses the super-admin create path: FOR UPDATE txn + max_keys + cap clamp.
    return await admin_crud.create_key(
        pool, org_id, member_label, day, minute, expires_at, created_by
    )


_UPDATABLE = {"member_label", "rate_limit_per_day", "rate_limit_per_min", "expires_at", "notes"}


async def update_key_in_org(pool, *, org_id, key_id, **fields) -> bool:
    pool = pool or _db.pool
    fields = {k: v for k, v in fields.items() if k in _UPDATABLE}
    if not fields:
        return False
    async with pool.acquire() as conn:
        async with conn.transaction():
            org = await conn.fetchrow(
                "SELECT * FROM api_access.organizations WHERE id = $1", org_id
            )
            if org is None:
                return False
            # Clamp any limit/expiry fields to the org cap before writing.
            # clamp_key_limits treats a None per-key value as "inherit the cap", so it
            # always returns a clamped value for all three. We only write back the ones
            # actually present in `fields` (the `in fields` guards) — a field the caller
            # didn't send is never touched, even though clamp computed a value for it.
            if {"rate_limit_per_day", "rate_limit_per_min", "expires_at"} & fields.keys():
                d, m, e = clamp_key_limits(
                    org,
                    fields.get("rate_limit_per_day"),
                    fields.get("rate_limit_per_min"),
                    fields.get("expires_at"),
                )
                if "rate_limit_per_day" in fields:
                    fields["rate_limit_per_day"] = d
                if "rate_limit_per_min" in fields:
                    fields["rate_limit_per_min"] = m
                if "expires_at" in fields:
                    fields["expires_at"] = e
            sets, args = [], []
            for k, v in fields.items():
                args.append(v)
                sets.append(f"{k} = ${len(args)}")
            args.extend([key_id, org_id])
            status = await conn.execute(
                f"UPDATE api_access.api_keys SET {', '.join(sets)} "
                f"WHERE id = ${len(args)-1} AND org_id = ${len(args)}",
                *args,
            )
    changed = status.split()[-1] != "0"
    if changed:
        bust_key_cache()
    return changed


async def revoke_key_in_org(pool, *, org_id, key_id) -> bool:
    pool = pool or _db.pool
    async with pool.acquire() as conn:
        status = await conn.execute(
            "UPDATE api_access.api_keys SET status='revoked' WHERE id=$1 AND org_id=$2",
            key_id, org_id,
        )
    changed = status.split()[-1] != "0"
    if changed:
        bust_key_cache()
    return changed


async def key_belongs_to_org(conn, key_id, org_id) -> bool:
    return await conn.fetchval(
        "SELECT 1 FROM api_access.api_keys WHERE id=$1 AND org_id=$2", key_id, org_id
    ) is not None


async def usage_for_key_in_org(pool, org_id, key_id):
    pool = pool or _db.pool
    async with pool.acquire() as conn:
        if not await key_belongs_to_org(conn, key_id, org_id):
            return None
        hourly = await conn.fetch(
            "SELECT hour, SUM(request_count) AS requests, SUM(error_count) AS errors, "
            "SUM(total_bytes) AS bytes FROM api_access.usage_rollup WHERE key_id=$1 "
            "GROUP BY hour ORDER BY hour DESC LIMIT 168",
            key_id,
        )
        by_ep = await conn.fetch(
            "SELECT endpoint_label, SUM(request_count) AS requests, SUM(error_count) AS errors, "
            "SUM(total_bytes) AS bytes FROM api_access.usage_rollup WHERE key_id=$1 "
            "GROUP BY endpoint_label ORDER BY requests DESC LIMIT 50",
            key_id,
        )
    return {"hourly": [dict(r) for r in hourly], "by_endpoint": [dict(r) for r in by_ep]}


async def sources_for_key_in_org(pool, org_id, key_id):
    pool = pool or _db.pool
    async with pool.acquire() as conn:
        if not await key_belongs_to_org(conn, key_id, org_id):
            return None
        countries = await conn.fetch(
            "SELECT COALESCE(country,'??') AS country, COUNT(*) AS n FROM api_access.request_log "
            "WHERE key_id=$1 GROUP BY country ORDER BY n DESC LIMIT 25", key_id)
        agents = await conn.fetch(
            "SELECT COALESCE(user_agent,'(none)') AS ua, COUNT(*) AS n FROM api_access.request_log "
            "WHERE key_id=$1 GROUP BY user_agent ORDER BY n DESC LIMIT 25", key_id)
    return {"countries": [dict(r) for r in countries], "user_agents": [dict(r) for r in agents]}


async def list_flags_for_org(pool, org_id):
    pool = pool or _db.pool
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT f.id, f.key_id, f.flag_type, f.detail, f.severity, f.detected_at, "
            "k.member_label FROM api_access.leak_flags f "
            "JOIN api_access.api_keys k ON k.id = f.key_id "
            "WHERE k.org_id=$1 AND f.acknowledged_at IS NULL ORDER BY f.detected_at DESC",
            org_id,
        )


async def ack_flag_in_org(pool, *, org_id, flag_id) -> bool:
    pool = pool or _db.pool
    async with pool.acquire() as conn:
        status = await conn.execute(
            "UPDATE api_access.leak_flags SET acknowledged_at=NOW() WHERE id=$1 "
            "AND key_id IN (SELECT id FROM api_access.api_keys WHERE org_id=$2)",
            flag_id, org_id,
        )
    return status.split()[-1] != "0"
