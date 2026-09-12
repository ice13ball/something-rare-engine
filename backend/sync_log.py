# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Sync-log recording and sync pause/resume — shared leaf helpers.

Moved out of main.py (Task 3 of the backend vertical-split refactor). Imports
only from `db` + stdlib, so any domain module or router can depend on this
without creating an import cycle back into main.py.
"""

import db


async def log_sync(source: str, added: int, total: int):
    # ⛔ A success CLEARS the skip marker. Without that a source that skipped once
    # would carry its reason forever, and a reader could not tell a layer that is
    # broken now from one that recovered three months ago — the marker would
    # describe the past while the dates describe the present.
    async with db.pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO sync_log (source, last_synced_at, records_added, total_records)
               VALUES ($1, NOW(), $2, $3)
               ON CONFLICT (source) DO UPDATE
               SET last_synced_at = NOW(), records_added = $2, total_records = $3,
                   skipped_reason = NULL, skipped_at = NULL""",
            source, added, total,
        )


async def log_sync_skipped(source: str, reason: str) -> None:
    """Record that a sync RAN and deliberately did nothing — without claiming it
    refreshed anything.

    ⛔ This exists because the two obvious alternatives are both wrong.

    Returning silently (what five ONC token guards did) leaves no row at all, so
    "never ran" and "ran, could not run" are indistinguishable from outside.
    That is not hypothetical: `sbma-cook-islands` has no `sync_log` row and no
    rows in `offshore_activities`, and nothing anywhere says which of the two it
    is.

    Calling `log_sync(source, 0, 0)` instead is worse than silence, because it
    stamps `last_synced_at = NOW()`. A layer whose API token is not configured
    then reads as freshly synced, forever, to the staleness monitor and to the
    LegendPanel "Dates & Freshness" tab. `onc-ctd-series` was doing exactly this.

    So this deliberately leaves BOTH `last_synced_at` and `total_records` alone:

    - `last_synced_at` keeps ageing, which is the signal the monitor classifies
      on. Same reasoning as `domains/land/common.py::_log_land_sync_failure`.
    - `total_records` still describes what is actually being served. A skipped
      run did not empty the table, and writing 0 would replace one lie with
      another — the layer may hold perfectly good data from when the token WAS
      configured.

    On a first-ever run the inserted row carries `last_synced_at = NULL`, which
    reads as "has never completed" rather than as any particular date.

    Guarded by `tests/test_sync_log_skipped.py`.
    """
    async with db.pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO sync_log
                   (source, last_synced_at, records_added, total_records,
                    skipped_reason, skipped_at)
               VALUES ($1, NULL, 0, 0, $2, NOW())
               ON CONFLICT (source) DO UPDATE
               SET records_added  = 0,
                   skipped_reason = $2,
                   skipped_at     = NOW()""",
            source, reason,
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
