# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

from __future__ import annotations

from .auth import KeyRecord
from .keys import hash_key, key_prefix


async def load_active_keys(pool) -> dict[str, KeyRecord]:
    """Load every api_key row into a {key_hash: KeyRecord} dict for the cache.

    Includes revoked/expired keys; evaluate_access() filters them at request
    time. The set is small (one row per member), so a full load is cheap.
    """
    rows = await pool.fetch(
        """
        SELECT id, org_id, status, expires_at, scopes, is_internal, key_hash,
               rate_limit_per_min, rate_limit_per_day
        FROM api_access.api_keys
        """
    )
    out: dict[str, KeyRecord] = {}
    for r in rows:
        out[r["key_hash"]] = KeyRecord(
            id=r["id"], org_id=r["org_id"], status=r["status"],
            expires_at=r["expires_at"], scopes=tuple(r["scopes"]),
            is_internal=r["is_internal"],
            rate_limit_per_min=r["rate_limit_per_min"],
            rate_limit_per_day=r["rate_limit_per_day"],
        )
    return out


async def seed_internal_key(pool, raw_key: str) -> None:
    """Upsert the '_internal' org and the frontend key (is_internal=True).

    No-op if raw_key is falsy. Idempotent: ON CONFLICT keeps the existing rows
    so re-running on every boot never duplicates or rotates the frontend key.
    """
    if not raw_key:
        return
    async with pool.acquire() as conn:
        org_id = await conn.fetchval(
            """
            INSERT INTO api_access.organizations (name, created_by, notes)
            VALUES ('_internal', 'system', 'Holder of the frontend BFF key')
            ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """
        )
        await conn.execute(
            """
            INSERT INTO api_access.api_keys
                (org_id, member_label, key_hash, key_prefix, is_internal, created_by, notes)
            VALUES ($1, 'frontend-bff', $2, $3, TRUE, 'system', 'Seeded from ABYSSAL_API_KEY env')
            ON CONFLICT (key_hash) DO NOTHING
            """,
            org_id,
            hash_key(raw_key),
            key_prefix(raw_key),
        )
