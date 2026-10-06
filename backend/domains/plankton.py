# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""OBIS plankton — stage 1 serves counts only. No occurrence endpoint exists yet;
when stage 2 adds one, its default filter is licence IN ('cc0','cc-by').

Production holds ~21.6 M rows, so the GROUP BY count must not run per request. The
result is cached in the shared response cache for CACHE_TTL, and ALSO keyed on the
`sync_log` row of the import: the import runs in its own process (the worker), which
cannot clear this process's cache, so a changed `last_synced_at` is what makes a fresh
import visible at once. The sync_log read is a one-row primary-key lookup."""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone

import asyncpg
from fastapi import APIRouter, Depends
from fastapi.responses import Response

import db
from auth import get_api_key
from response_cache import CACHE_TTL, store as _cache
from schema.plankton import FAILED_TOKEN_RE, STARTED_PREFIX, STARTED_STALE_HOURS, SWAPPED_PARTIAL_PREFIX

router = APIRouter()

CACHE_KEY = "plankton-meta"
SOURCE = "plankton-obis"
_signature: object = None  # the sync_log state the cached payload was built for


def _classify(reason: str | None, synced_at, skipped_at=None) -> tuple[str | None, list[str] | None]:
    """Coarse, fixed-vocabulary outcome of the last import. ⛔ Never returns text taken from
    sync_log: for errors that is `Type: message` (file paths, DB identifiers, hosts), and this
    endpoint is served to external API-key holders. The full reason stays in sync_log for admins.
    Prefixes are the ones plankton_obis.py / plankton_obis_worker.py write."""
    if reason is None:
        return ("swapped" if synced_at else None), None
    if reason.startswith(SWAPPED_PARTIAL_PREFIX):
        return "swapped", None
    if reason.startswith("swap blocked"):
        checks = [name for marker, name in (("rows dropped", "row_drop"), (" has 0 rows", "missing_group"))
                  if marker in reason]
        return "blocked", checks
    if reason.startswith("swap lock timeout"):
        return "lock_timeout", None
    if reason.startswith(STARTED_PREFIX):
        # "running" while the marker is fresh; once older than the unit's TimeoutStartSec the process
        # was killed without a trace, which is a failed run.
        stale = skipped_at is not None and (
            datetime.now(timezone.utc) - skipped_at > timedelta(hours=STARTED_STALE_HOURS))
        return ("error" if stale else "running"), None
    if reason.startswith("low memory"):
        return "low_memory", None
    return "error", None


def _failed_datasets(reason: str | None) -> int:
    """The dataset-failure count, from the fixed token on a partial swap and from nothing else."""
    if reason and reason.startswith(SWAPPED_PARTIAL_PREFIX):
        m = re.search(FAILED_TOKEN_RE, reason)
        if m:
            return int(m.group(1))
    return 0


def _iso(value):
    return value.isoformat() if value else None


async def _last_import(conn) -> dict | None:
    try:
        row = await conn.fetchrow(
            """SELECT last_synced_at, records_added, total_records, skipped_reason, skipped_at
               FROM sync_log WHERE source = $1""", SOURCE)
    except asyncpg.UndefinedTableError:
        return None
    if row is None:
        return None
    outcome, checks = _classify(row["skipped_reason"], row["last_synced_at"], row["skipped_at"])
    last = {
        "synced_at": _iso(row["last_synced_at"]),
        "records_added": row["records_added"],
        "total_records": row["total_records"],
        "outcome": outcome,
        "skipped_at": _iso(row["skipped_at"]),
        "failed_datasets": _failed_datasets(row["skipped_reason"]),
    }
    if checks is not None:
        last["blocked_checks"] = checks
    return last


@router.get("/v1/plankton/meta", dependencies=[Depends(get_api_key)])
async def plankton_meta():
    global _signature
    async with db.pool.acquire() as conn:
        last = await _last_import(conn)
        sig = json.dumps(last, sort_keys=True) if last else None
        hit = _cache.get(CACHE_KEY)
        if hit and sig == _signature and time.monotonic() - hit[0] < CACHE_TTL:
            return Response(content=hit[1], media_type="application/json")
        try:
            rows = await conn.fetch("""SELECT taxon_group, licence, count(*) AS records
                                       FROM plankton_occurrences GROUP BY 1, 2 ORDER BY 1, 2""")
            datasets = await conn.fetchval("SELECT count(*) FROM plankton_datasets")
        except asyncpg.UndefinedTableError:   # fresh DB, ensure_plankton not run yet
            rows, datasets = [], 0
    data = json.dumps({
        "total": sum(r["records"] for r in rows),
        "datasets": datasets,
        "by_group_licence": [dict(r) for r in rows],
        "last_import": last,
    }).encode()
    _cache[CACHE_KEY] = (time.monotonic(), data)
    _signature = sig
    return Response(content=data, media_type="application/json")


def clear_caches() -> None:
    """Admin cache sweep hook (registered in domains/__init__.py). Clears the whole shared
    response cache, like seafloor.clear_caches(): redundant with admin_cache_clear()'s own
    `_cache.clear()`, but it keeps the aliased `_cache` honest under test_domain_cache_clear."""
    global _signature
    _cache.clear()
    _signature = None
