# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Sync-log recording and sync pause/resume — shared leaf helpers.

Moved out of main.py (Task 3 of the backend vertical-split refactor). Imports
only from `db` + stdlib, so any domain module or router can depend on this
without creating an import cycle back into main.py.
"""

import db


async def log_sync(source: str, added: int, total: int):
    async with db.pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO sync_log (source, last_synced_at, records_added, total_records)
               VALUES ($1, NOW(), $2, $3)
               ON CONFLICT (source) DO UPDATE
               SET last_synced_at = NOW(), records_added = $2, total_records = $3""",
            source, added, total,
        )


# ── Sync pause/resume ─────────────────────────────────────────────────────────
# Persisted in DB table `paused_syncs` — survives restarts.
# Checked by scheduled tasks and force-sync endpoint.

_paused_syncs_cache: set[str] | None = None  # in-memory cache, refreshed from DB


async def _load_paused_syncs() -> set[str]:
    """Load paused sync actions from DB into memory cache."""
    global _paused_syncs_cache
    async with db.pool.acquire() as conn:
        rows = await conn.fetch("SELECT action FROM paused_syncs")
    _paused_syncs_cache = {r["action"] for r in rows}
    return _paused_syncs_cache


async def is_sync_paused(action: str) -> bool:
    """Check if a sync action is paused. Uses in-memory cache, falls back to DB."""
    global _paused_syncs_cache
    if _paused_syncs_cache is None:
        await _load_paused_syncs()
    return action in _paused_syncs_cache


def invalidate_paused_cache() -> None:
    """Reset the in-memory paused-syncs cache so the next `is_sync_paused` call
    re-reads `paused_syncs` from the DB. Call after any INSERT/DELETE against
    that table (pause/unpause admin actions)."""
    global _paused_syncs_cache
    _paused_syncs_cache = None
