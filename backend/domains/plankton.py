# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""OBIS plankton — /v1/plankton/meta (counts, last import, tile version), and the stage-2 map:
/v1/plankton/tiles/{z}/{x}/{y}.pbf.

⚠️ Licences (Michal, 2026-10-07, amending stage 1): the map tiles show ALL licences, cc-by-nc included; the
legend says so. Every OTHER public endpoint or export (area export included) defaults to
licence IN ('cc0','cc-by'). → DATA-LICENCES.md, .claude/rules/layers/nc-licence-lineage.md.

/meta: production holds ~24 M rows, so the GROUP BY count must not run per request. It is cached in the
shared response cache for CACHE_TTL and ALSO keyed on the import's `sync_log` row and the tile version: both
change in another process (the worker), which cannot clear this process's cache."""
from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

import db
from auth import get_api_key
from response_cache import CACHE_TTL, store as _cache
from services import plankton_tiles as tiles
from schema.plankton import FAILED_TOKEN_RE, STARTED_PREFIX, STARTED_STALE_HOURS, SWAPPED_PARTIAL_PREFIX, band_sql, decade_sql

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
        checks = [name for marker, name in (("rows dropped", "row_drop"), (" has 0 rows", "missing_group"),
                                            ("aggregates:", "aggregates"))
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


async def _tile_version(conn) -> dict | None:
    try:
        async with conn.transaction():
            row = await conn.fetchrow("SELECT version, built_at FROM plankton_tile_version WHERE id = 1")
    except asyncpg.UndefinedTableError:
        return None
    return {"version": row["version"], "built_at": _iso(row["built_at"])} if row else None


COUNT_STATEMENT_TIMEOUT = "20s"   # a recount of ~24 M rows must never hold a pool connection for long
COUNT_BACKOFF_S = 60.0            # after a timed-out recount, do not start another one for this long
_COUNT_SQL = """SELECT taxon_group, licence, count(*) AS records
                FROM plankton_occurrences GROUP BY 1, 2 ORDER BY 1, 2"""
_counts_task: asyncio.Task | None = None            # single-flight: ONE recount at a time, callers share it
_last_counts: tuple[list, int] | None = None        # (rows, datasets) of the last recount that finished
_no_recount_before = 0.0                             # monotonic time; set when a recount timed out


async def _count_occurrences() -> tuple[list, int]:
    """The expensive part of /meta, on its own pool connection, under a statement timeout (QueryCanceledError
    propagates). A missing table (fresh DB, ensure_plankton not run yet) counts as empty."""
    async with db.pool.acquire() as conn:
        try:
            async with conn.transaction():
                await conn.execute(f"SET LOCAL statement_timeout = '{COUNT_STATEMENT_TIMEOUT}'")
                rows = await conn.fetch(_COUNT_SQL)
                datasets = await conn.fetchval("SELECT count(*) FROM plankton_datasets")
        except asyncpg.UndefinedTableError:
            return [], 0
    return list(rows), datasets


async def _counts() -> tuple[list, int, bool]:
    """(rows, datasets, stale). Concurrent callers await the SAME recount task. On a timeout the last good
    counts are served (stale=True) and no new recount starts for COUNT_BACKOFF_S; without any last good
    counts the answer is a 503 with Retry-After — never exception text."""
    global _counts_task, _last_counts, _no_recount_before
    if time.monotonic() < _no_recount_before:
        if _last_counts:
            return (*_last_counts, True)
        raise HTTPException(503, "plankton counts are being computed, try again", headers=_TOO_SLOW_COUNT)
    if _counts_task is None or _counts_task.done():
        _counts_task = asyncio.create_task(_count_occurrences())
    try:
        rows, datasets = await asyncio.shield(_counts_task)
    except asyncpg.QueryCanceledError:
        _no_recount_before = time.monotonic() + COUNT_BACKOFF_S
        if _last_counts:
            return (*_last_counts, True)
        raise HTTPException(503, "plankton counts are being computed, try again",
                            headers=_TOO_SLOW_COUNT) from None
    _last_counts = (rows, datasets)
    return rows, datasets, False


_TOO_SLOW_COUNT = {"Retry-After": "30", "Cache-Control": "no-store"}


@router.get("/v1/plankton/tile-version", dependencies=[Depends(get_api_key)])
async def plankton_tile_version():
    """What the map needs on first paint: the live tile version, one primary-key row. Never waits for /meta's
    counts (those can take a long time on ~24 M rows)."""
    if db.pool is None:
        raise HTTPException(503, "Database pool unavailable", headers={"Retry-After": "5", "Cache-Control": "no-store"})
    async with db.pool.acquire() as conn:
        tile = await _tile_version(conn)
    return {"tile_version": tile["version"] if tile else None, "tile_built_at": tile["built_at"] if tile else None}


@router.get("/v1/plankton/meta", dependencies=[Depends(get_api_key)])
async def plankton_meta():
    global _signature
    async with db.pool.acquire() as conn:
        last = await _last_import(conn)
        tile = await _tile_version(conn)
    # The connection is released here: a request that waits for the recount holds no pool slot.
    # Keyed on the tile version too: a swap or --aggregates-only run happens in the worker process, and
    # the map must get the new version at once (its tiles are immutable per version).
    sig = json.dumps({"last": last, "tile": tile}, sort_keys=True)
    hit = _cache.get(CACHE_KEY)
    if hit and sig == _signature and time.monotonic() - hit[0] < CACHE_TTL:
        return Response(content=hit[1], media_type="application/json")
    rows, datasets, stale = await _counts()
    body = {
        "total": sum(r["records"] for r in rows),
        "datasets": datasets,
        "by_group_licence": [dict(r) for r in rows],
        "last_import": last,
        "tile_version": tile["version"] if tile else None,
        "tile_built_at": tile["built_at"] if tile else None,
    }
    if stale:
        body["counts_stale"] = True      # last good counts: the recount timed out; not cached
        return Response(content=json.dumps(body).encode(), media_type="application/json")
    data = json.dumps(body).encode()
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


# P4: the semaphore is taken BEFORE a pool connection (the API pool is max_size=4, so >= 2 connections stay free
# for every other endpoint however many cold tiles queue up).
_RENDER_SEM = asyncio.Semaphore(2)
IMMUTABLE = "public, max-age=31536000, immutable"
SHORT = "public, max-age=60"
_NOT_BUILT = {"Retry-After": "300", "Cache-Control": "no-store"}
_TOO_SLOW = {"Retry-After": "5", "Cache-Control": "no-store"}
_MVT = "application/vnd.mapbox-vector-tile"
MAX_ZOOM = 12   # == plankton_tiles.TILE_MAX_ZOOM (a test pins it): the map's MVTLayer maxZoom; higher z only fills the disk cache with empty tiles
_LIVE_TTL = 30.0
_live: tuple[str | None, float] = (None, 0.0)   # (live tile version, monotonic time it was learned)
_refreshing: asyncio.Task | None = None


def _set_live_version(version: str | None) -> None:
    global _live
    _live = (version, time.monotonic())


def _live_version() -> str | None:
    version, at = _live
    return version if time.monotonic() - at < _LIVE_TTL else None


async def _refresh_live_version() -> None:
    try:
        async with db.pool.acquire() as conn:
            _set_live_version(await tiles.current_version(conn))
    except Exception:  # best effort: the hit path stays on the short max-age until a refresh works
        pass


def _refresh_live_version_soon() -> None:
    """Outside the hit path: when the in-process version is stale, refresh it in the background (one at a time)."""
    global _refreshing
    if _live_version() is None and db.pool is not None and (_refreshing is None or _refreshing.done()):
        _refreshing = asyncio.create_task(_refresh_live_version())


def _tile_response(data: bytes, cache_control: str) -> Response:
    headers = {"Cache-Control": cache_control}
    if not data:
        return Response(status_code=204, headers=headers)
    return Response(content=data, media_type=_MVT, headers=headers)


@router.get("/v1/plankton/tiles/{z}/{x}/{y}.pbf", dependencies=[Depends(get_api_key)])
async def plankton_tile(z: int, x: int, y: int, v: str | None = None, g: str | None = None,
                        d: str | None = None, b: str | None = None, e: str | None = None) -> Response:
    """Plankton map tile: 1° grid at z0-3, 0.25° grid at z4-6, places from z7, filtered exactly on the
    server (g = groups, d = decades, b = depth bands, e = 0 hides eDNA). Read-through disk cache keyed on the
    live tile version and the canonical filter key; immutable for the browser when `v` is that version."""
    if not (0 <= z <= MAX_ZOOM and 0 <= x < 2 ** z and 0 <= y < 2 ** z):
        raise HTTPException(400, "tile coordinates out of range")
    try:
        flt = tiles.parse_filter(g, d, b, e)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    root = tiles.cache_root()
    # P4 hit path, NO database access: only render() writes under <version>/, and only under the version
    # returned by the same statement as the bytes, so bytes in folder `v` are always version v's bytes.
    # The server's knowledge of the live version is in-process (_LIVE_TTL old at most): a stale value can only
    # downgrade the caching (short max-age), never mislabel bytes as immutable.
    if v is not None and tiles.VERSION_RE.fullmatch(v):
        data = await asyncio.to_thread(tiles.read_cached, tiles.tile_path(root, v, flt.key, z, x, y))
        if data is not None:
            _refresh_live_version_soon()
            return _tile_response(data, IMMUTABLE if _live_version() == v else SHORT)
    if db.pool is None:
        raise HTTPException(503, "Database pool unavailable", headers=_TOO_SLOW)
    # Miss / no usable v: the live version is one primary-key row; the connection is released before any wait.
    async with db.pool.acquire() as conn:
        version = await tiles.current_version(conn)
    _set_live_version(version)
    if version is None:
        raise HTTPException(503, "plankton tiles are not built yet", headers=_NOT_BUILT)
    path = tiles.tile_path(root, version, flt.key, z, x, y)
    data = await asyncio.to_thread(tiles.read_cached, path)
    if data is None:
        try:
            async with _RENDER_SEM:
                data = await asyncio.to_thread(tiles.read_cached, path)   # another request may have just filled it
                if data is None:
                    async with db.pool.acquire() as conn:
                        version, data = await tiles.render(conn, z, x, y, flt)
                    _set_live_version(version)
                    if version is None:
                        raise HTTPException(503, "plankton tiles are not built yet", headers=_NOT_BUILT)
                    # Reached only with a COMPLETE render: a timed-out one raised above and is never written.
                    path = tiles.tile_path(root, version, flt.key, z, x, y)
                    if await asyncio.to_thread(tiles.write_cached, path, data):
                        tiles.note_write(root)
        except asyncpg.QueryCanceledError:
            raise HTTPException(503, "plankton tile took too long, try again", headers=_TOO_SLOW) from None
        except asyncpg.UndefinedTableError:
            raise HTTPException(503, "plankton tiles are not built yet", headers=_NOT_BUILT) from None
    return _tile_response(data, IMMUTABLE if v == version else SHORT)


SITE_KEY_RE = re.compile(r"-?[0-9]{1,3}\.[0-9]{6},-?[0-9]{1,2}\.[0-9]{6}")
SITE_STATEMENT_TIMEOUT = "10s"
TOP_SPECIES = 10
MAX_DATASETS = 50


def _site_where(cutoff: int) -> str:
    """Rows of ONE place under the active filters. The ±1e-6° box lets the GIST index find the place; the
    rounded equality is the exact place definition the aggregates use (plankton_aggregates). The decade
    cutoff is the build year of the live tile version, so panel and tiles bucket the same way."""
    return ("o.geom && ST_MakeEnvelope($1::float8 - 1e-6, $2::float8 - 1e-6, $1::float8 + 1e-6, "
            "$2::float8 + 1e-6, 4326) "
            "AND round(o.lon::numeric, 6) = $3::numeric AND round(o.lat::numeric, 6) = $4::numeric "
            f"AND o.taxon_group = ANY($5::text[]) AND {decade_sql('o.year', str(int(cutoff)))} = ANY($6::smallint[]) "
            f"AND {band_sql('o.depth_m')} = ANY($7::smallint[]) AND ($8::boolean OR NOT o.is_edna)")


@router.get("/v1/plankton/site/{site_key}", dependencies=[Depends(get_api_key)])
async def plankton_site(site_key: str, g: str | None = None, d: str | None = None, b: str | None = None,
                        e: str | None = None):
    """One place of the plankton map, under the active map filters: groups, top species, years, depths, eDNA
    share, licences and datasets. ALL licences are shown (see the module docstring)."""
    if not SITE_KEY_RE.fullmatch(site_key):
        raise HTTPException(400, "malformed site key")
    try:
        flt = tiles.parse_filter(g, d, b, e)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    lon_s, lat_s = site_key.split(",")
    if db.pool is None:
        raise HTTPException(503, "Database pool unavailable", headers=_TOO_SLOW)
    try:
        async with db.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(f"SET LOCAL statement_timeout = '{SITE_STATEMENT_TIMEOUT}'")
                # ⛔ Lock order: the version table FIRST, then sites (SWAP_LOCK_ORDER). The swap locks them in that
                # order; reading sites first would let the panel and the swap wait for each other (deadlock).
                cutoff = await conn.fetchval("SELECT extract(year FROM (built_at AT TIME ZONE 'UTC'))::int "
                                             "FROM plankton_tile_version WHERE id = 1")
                if cutoff is None:
                    raise HTTPException(503, "plankton map is not built yet", headers=_NOT_BUILT)
                site = await conn.fetchrow("SELECT lon, lat FROM plankton_sites WHERE site_key = $1", site_key)
                if site is None:
                    raise HTTPException(404, "no such place in the current import")
                where = _site_where(cutoff)
                args = (float(lon_s), float(lat_s), Decimal(lon_s), Decimal(lat_s), *flt.sql_args())
                c = int(cutoff)
                stats = await conn.fetchrow(
                    "SELECT count(*) AS total, "
                    f"min(o.year) FILTER (WHERE o.year <= {c}) AS year_min, "
                    f"max(o.year) FILTER (WHERE o.year <= {c}) AS year_max, "
                    f"count(*) FILTER (WHERE o.year IS NULL OR o.year > {c}) AS undated, "
                    "min(o.depth_m) AS depth_min, max(o.depth_m) AS depth_max, "
                    "count(*) FILTER (WHERE o.depth_m IS NULL) AS no_depth, "
                    "count(*) FILTER (WHERE o.is_edna) AS edna "
                    f"FROM plankton_occurrences o WHERE {where}", *args)
                groups = await conn.fetch(
                    "SELECT o.taxon_group, count(*) AS n FROM plankton_occurrences o "
                    f"WHERE {where} GROUP BY 1 ORDER BY 2 DESC, 1", *args)
                species = await conn.fetch(
                    "SELECT o.scientific_name, o.taxon_group, count(*) AS n FROM plankton_occurrences o "
                    f"WHERE {where} AND o.scientific_name IS NOT NULL GROUP BY 1, 2 "
                    f"ORDER BY 3 DESC, 1 LIMIT {TOP_SPECIES}", *args)
                licences = await conn.fetch(
                    "SELECT o.licence, count(*) AS n FROM plankton_occurrences o "
                    f"WHERE {where} GROUP BY 1 ORDER BY 2 DESC, 1", *args)
                datasets = await conn.fetch(
                    "SELECT d.dataset_id, d.title, d.citation, d.url, d.licence, count(*) AS n, "
                    "count(*) OVER () AS datasets_total "
                    "FROM plankton_occurrences o JOIN plankton_datasets d ON d.dataset_id = o.dataset_id "
                    f"WHERE {where} GROUP BY d.dataset_id, d.title, d.citation, d.url, d.licence "
                    f"ORDER BY n DESC, d.title LIMIT {MAX_DATASETS}", *args)
    except (asyncpg.QueryCanceledError, asyncpg.DeadlockDetectedError, asyncpg.LockNotAvailableError):
        # too slow, or the monthly swap was holding its locks (we were the deadlock victim): try again shortly
        raise HTTPException(503, "plankton place took too long, try again", headers=_TOO_SLOW) from None
    except asyncpg.UndefinedTableError:
        raise HTTPException(503, "plankton map is not built yet", headers=_NOT_BUILT) from None
    total = stats["total"]
    return {
        "site_key": site_key, "lon": site["lon"], "lat": site["lat"], "total": total,
        "groups": [dict(r) for r in groups],
        "top_species": [dict(r) for r in species],
        "years": {"min": stats["year_min"], "max": stats["year_max"], "undated": stats["undated"]},
        "depth": {"min_m": stats["depth_min"], "max_m": stats["depth_max"], "no_depth": stats["no_depth"]},
        "edna": {"n": stats["edna"], "share": round(stats["edna"] / total, 4) if total else 0.0},
        "licences": [dict(r) for r in licences],
        "datasets": [{"dataset_id": str(r["dataset_id"]), "title": r["title"], "citation": r["citation"],
                      "url": r["url"], "licence": r["licence"], "n": r["n"],
                      "obis_url": f"https://obis.org/dataset/{r['dataset_id']}"} for r in datasets],
        "datasets_total": datasets[0]["datasets_total"] if datasets else 0,
    }
