# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""OBIS plankton occurrences — monthly full rebuild of plankton_occurrences.

Load/swap and the sync orchestrator live here; the rules and the per-dataset extraction are in
plankton_extract.py (re-exported below), run in a child process per dataset. The process wrapper
(lock, memory check, --force) is plankton_obis_worker.py.
"""
from __future__ import annotations

import datetime as dt  # noqa: F401
import pathlib
import re  # noqa: F401
import shutil

import asyncpg

from ingestion.plankton_extract import *  # noqa: F401,F403
from ingestion.plankton_extract import (  # noqa: F401  (underscore names are not covered by *)
    _I, _SELECT, _lit, _sql_list, _COPEPODA, _guard_missing_ranks, _pass1_hits, _pass2_write)
from schema.plankton import GROUPS, STARTED_PREFIX, STARTED_STALE_HOURS  # noqa: F401

# ---------------------------------------------------------------------------
# Load, validate, swap. The live tables are never written to: everything goes
# into `<table>_new`, and swap() renames them over the live pair in ONE
# transaction. A failed run leaves the live tables exactly as they were.
# ---------------------------------------------------------------------------
import math  # noqa: E402
import uuid  # noqa: E402

from schema.plankton import (  # noqa: E402
    datasets_ddl, occurrences_ddl, occurrences_index_ddl, progress_ddl)
from ingestion import plankton_aggregates as agg  # noqa: E402
from ingestion.plankton_aggregates import AggregatesInvalid  # noqa: E402,F401
from schema.plankton import AGG_TABLES, GRID_FACETS, SITE_FACETS, SITES, TILE_VERSION  # noqa: E402

OCC, DS, PROG = "plankton_occurrences", "plankton_datasets", "plankton_progress"
# ⛔ THE one order in which the live plankton tables are locked. Every swap path takes the tables it needs
# with ONE `LOCK TABLE` in this order, and the tile statement (services/plankton_tiles.py) reads them in the
# same relative order (version first, then sites -> site_facets | grid_facets): two sessions that take
# overlapping subsets in one global order cannot deadlock. Change it only together with the tile SQL.
SWAP_LOCK_ORDER = (TILE_VERSION, SITES, SITE_FACETS, GRID_FACETS, OCC, DS)
# What a failed attempt can mean "somebody else held a lock": a timeout, or a deadlock the server broke.
_LOCK_CONTENTION = (asyncpg.exceptions.LockNotAvailableError, asyncpg.exceptions.DeadlockDetectedError)
MAX_DROP = 0.10


class SwapBlocked(Exception):
    """validate_staging returned reasons; `.reasons` carries them."""

    def __init__(self, reasons: list[str]):
        super().__init__("; ".join(reasons))
        self.reasons = reasons


async def build_staging(conn) -> None:
    """Drop any leftover `_new` pair (killed run) and create fresh empty ones.
    Safe while the live tables exist: relation names (tables, indexes, identity
    sequences) all carry the `_new` prefix, so nothing collides with the live pair."""
    await conn.execute(f"DROP TABLE IF EXISTS {OCC}_new")
    await conn.execute(f"DROP TABLE IF EXISTS {DS}_new")
    await conn.execute(f"DROP TABLE IF EXISTS {PROG}_new")
    await agg.drop_aggregates(conn)
    for sql in datasets_ddl(f"{DS}_new"):
        await conn.execute(sql)
    for sql in occurrences_ddl(f"{OCC}_new", f"{DS}_new"):
        await conn.execute(sql)
    for sql in progress_ddl(f"{PROG}_new"):
        await conn.execute(sql)


async def discard_staging(conn) -> None:
    await conn.execute(f"DROP TABLE IF EXISTS {OCC}_new")
    await conn.execute(f"DROP TABLE IF EXISTS {DS}_new")
    await conn.execute(f"DROP TABLE IF EXISTS {PROG}_new")
    await agg.drop_aggregates(conn)


async def record_progress(conn, dataset_id: str, rows: int) -> None:
    """Ledger row: this dataset is completely loaded (call inside the dataset's load transaction)."""
    await conn.execute(
        f"INSERT INTO {PROG}_new (dataset_id, rows) VALUES ($1::uuid, $2) "
        f"ON CONFLICT (dataset_id) DO UPDATE SET rows = EXCLUDED.rows, finished_at = now()",
        dataset_id, rows)


async def load_datasets(conn, datasets: list[dict], mode: str = "insert") -> None:
    """Licence is normalised here (NULL/empty -> 'unknown'); 'restricted' datasets are not stored.
    mode: "insert" (fresh staging), "upsert" (resume: a dataset still to be loaded takes the new
    metadata/licence), "ignore" (resume: an already loaded dataset keeps the row its rows were
    loaded under)."""
    rows = []
    for d in datasets:
        lic = normalise_licence(d.get("licence"))
        if lic == "restricted":
            continue
        rows.append((uuid.UUID(str(d["dataset_id"])), d.get("title"), d.get("institution"), lic,
                     d.get("licence_raw"), d.get("url"), d.get("citation")))
    tail = {"insert": "",
            "ignore": " ON CONFLICT (dataset_id) DO NOTHING",
            "upsert": " ON CONFLICT (dataset_id) DO UPDATE SET title = EXCLUDED.title,"
                      " institution = EXCLUDED.institution, licence = EXCLUDED.licence,"
                      " licence_raw = EXCLUDED.licence_raw, url = EXCLUDED.url,"
                      " citation = EXCLUDED.citation"}[mode]
    await conn.executemany(
        f"""INSERT INTO {DS}_new (dataset_id, title, institution, licence, licence_raw, url, citation)
            VALUES ($1, $2, $3, $4, $5, $6, $7){tail}""", rows)


LOAD_MEMORY_LIMIT = "256MB"
_COLS = ("taxon_group", "scientific_name", "aphia_id", "taxon_order", "dataset_id", "licence",
         "is_edna", "depth_m", "event_date", "year", "month", "lon", "lat")
# Keys of the dict load_extract returns (every extract row lands in exactly one):
DROP_REASONS = ("excluded_dataset", "restricted", "unknown_dataset", "absence", "dropped",
                "bad_coords", "on_land", "excluded_order", "other_filter")


def _finite(x) -> bool:
    try:
        return x is not None and math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


_INT32 = 2**31


def _clean(text):
    """NUL bytes are illegal in PostgreSQL text and would abort the whole COPY."""
    return text.replace("\x00", "") if isinstance(text, str) else text


def _drop_reason(r: dict) -> str | None:
    """Why KEEP_SQL (or a schema CHECK) would reject this row; None = keep. Python mirror of
    KEEP_SQL, used for counting only — plus the R1 guard on lon/lat that KEEP_SQL cannot give."""
    if r.get("absence"):
        return "absence"
    if r.get("dropped"):
        return "dropped"
    lat, lon = r.get("lat"), r.get("lon")
    if (not _finite(lat) or not _finite(lon) or not -90 <= float(lat) <= 90
            or not -180 <= float(lon) <= 180 or (float(lat) == 0 and float(lon) == 0)):
        return "bad_coords"
    if LAND_FLAG and LAND_FLAG in (r.get("flags") or []):
        return "on_land"
    if (r.get("grp") == "copepoda" and r.get("ord") in EXCLUDED_COPEPOD_ORDERS
            and (r.get("genus") or "") not in PLANKTONIC_HARPACTICOID_GENERA):
        return "excluded_order"
    if not r.get("keep"):
        return "other_filter"
    return None


def _load_connection(path):
    """DuckDB for reading one extract in the load: capped, on-disk spill (a default connection would
    take 80 % of RAM inside a 2 GB cgroup). It lives in the PARENT next to the asyncpg connection,
    so it is small (it only streams a local parquet) and load_extract closes it every time."""
    import duckdb
    tmp = pathlib.Path(path).parent / "duckdb-load"
    tmp.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"SET memory_limit='{LOAD_MEMORY_LIMIT}'")
    con.execute("SET threads=1")
    con.execute(f"SET temp_directory={_lit(tmp)}")
    return con


async def load_extract(conn, path, licences: dict[str, str]) -> dict[str, int]:
    """COPY one extracted parquet (Task 8: every GROUP row, `keep` = KEEP_SQL verdict) into
    plankton_occurrences_new. Returns {"kept": n, <DROP_REASONS>: n}.
    R1: depth outside 0..11000 and month outside 1..12 become NULL; lon/lat NULL or out of
    range drops the row — one bad OBIS record never aborts the load.
    Licence comes from `licences` (normalised; missing/empty -> 'unknown'); 'restricted' rows are
    never stored; rows of a dataset absent from plankton_datasets_new cannot satisfy the FK and are
    counted as unknown_dataset."""
    stats = {"kept": 0, **{k: 0 for k in DROP_REASONS}}
    known = {r[0] for r in await conn.fetch(f"SELECT dataset_id FROM {DS}_new")}
    db = _load_connection(path)
    try:
        return await _load_rows(conn, db, path, licences, known, stats)
    finally:
        db.close()        # this connection lives in the PARENT: leaving it open would keep ~1,700 of them


async def _load_rows(conn, db, path, licences, known, stats) -> dict[str, int]:
    lic_cache: dict[str, str] = {}
    cur = db.execute(f"SELECT * FROM read_parquet({_lit(path)})")
    names = [d[0] for d in cur.description]
    batch: list[tuple] = []

    async def flush():
        if batch:
            await conn.copy_records_to_table(f"{OCC}_new", records=batch, columns=_COLS)
            stats["kept"] += len(batch)
            batch.clear()

    while rows := cur.fetchmany(50_000):
        for row in rows:
            r = dict(zip(names, row))
            ds = str(r["dataset_id"])
            if ds in EXCLUDED_DATASETS or (ds, r.get("grp")) in EXCLUDED_DATASET_GROUPS:
                stats["excluded_dataset"] += 1
                continue
            if ds not in lic_cache:
                lic_cache[ds] = normalise_licence(licences.get(ds))
            lic = lic_cache[ds]
            if lic == "restricted":
                stats["restricted"] += 1
                continue
            try:
                ds_uuid = uuid.UUID(ds)
            except ValueError:
                ds_uuid = None
            if ds_uuid not in known:
                stats["unknown_dataset"] += 1
                continue
            why = _drop_reason(r)
            if why:
                stats[why] += 1
                continue
            ev = parse_event_date(r.get("eventdate"))
            aphia = r.get("aphiaid")
            aphia = int(aphia) if _finite(aphia) and -_INT32 <= int(aphia) < _INT32 else None
            batch.append((r["grp"], _clean(r.get("sciname")), aphia, _clean(r.get("ord")),
                          ds_uuid, lic, bool(r.get("edna_struct")),
                          parse_depth(r.get("depth"), r.get("dmin"), r.get("dmax")),
                          ev, ev.year if ev else None,
                          parse_month(r.get("month")) or (ev.month if ev else None),
                          float(r["lon"]), float(r["lat"])))
            if len(batch) >= 50_000:
                await flush()
    await flush()
    return stats


async def validate_staging(conn) -> list[str]:
    """Reasons to block the swap (empty = OK): (a) fewer than 90 % of the live rows,
    (b) a taxon group with 0 rows. NULL licence/geom cannot occur: NOT NULL constraints reject them.
    An empty live table (first run) never blocks on (a)."""
    reasons: list[str] = []
    new = await conn.fetchval(f"SELECT count(*) FROM {OCC}_new")
    old = await conn.fetchval(f"SELECT count(*) FROM {OCC}")
    if old and new < old * (1 - MAX_DROP):
        reasons.append(f"rows dropped {old} -> {new} (more than {int(MAX_DROP * 100)} %)")
    present = {r[0] for r in await conn.fetch(f"SELECT DISTINCT taxon_group FROM {OCC}_new")}
    reasons += [f"group {g} has 0 rows" for g in GROUPS if g not in present]
    return reasons


class SwapLockTimeout(Exception):
    """The swap could not get its ACCESS EXCLUSIVE locks (a long reader held the live table)
    on any attempt. Live tables AND the `_new` staging pair are left intact, so a later
    attempt can call swap() again without re-extracting."""


SWAP_LOCK_TIMEOUT = "3s"
SWAP_BACKOFF_S: tuple[float, ...] = (10, 30, 60)   # between attempts -> 4 attempts


async def _rename_new_objects(conn, table: str) -> None:
    """Constraints and indexes keep their `_new` names through ALTER TABLE ... RENAME; give them the
    conventional ones, or the next build_staging collides (CREATE INDEX IF NOT EXISTS would silently skip)."""
    for (name,) in await conn.fetch(
            "SELECT conname FROM pg_constraint WHERE conrelid = $1::regclass AND conname LIKE $2",
            table, f"{table}\\_new%"):
        await conn.execute(f'ALTER TABLE {table} RENAME CONSTRAINT "{name}" TO "{table}{name[len(table) + 4:]}"')
    for (name,) in await conn.fetch(
            "SELECT indexname FROM pg_indexes WHERE schemaname = current_schema() "
            "AND tablename = $1 AND indexname LIKE $2", table, f"{table}\\_new%"):
        await conn.execute(f'ALTER INDEX "{name}" RENAME TO "{table}{name[len(table) + 4:]}"')


async def _lock_for_swap(conn, tables) -> None:
    """Inside the caller's transaction: ACCESS EXCLUSIVE on `tables` (those that exist) in ONE statement,
    in SWAP_LOCK_ORDER. One statement + one global order = no lock-order inversion against the tile SQL."""
    wanted = [t for t in SWAP_LOCK_ORDER if t in tables]
    present = [r[0] for r in await conn.fetch(
        "SELECT t FROM unnest($1::text[]) WITH ORDINALITY AS u(t, o) WHERE to_regclass(t) IS NOT NULL ORDER BY o",
        wanted)]
    if present:
        await conn.execute(f"LOCK TABLE {', '.join(present)} IN ACCESS EXCLUSIVE MODE")


async def _swap_aggregates_in_tx(conn) -> None:
    """Inside the caller's transaction: the live aggregate tables are replaced by their `_new` build."""
    for t in AGG_TABLES:
        await conn.execute(f"DROP TABLE IF EXISTS {t}")
    for t in AGG_TABLES:
        await conn.execute(f"ALTER TABLE {t}_new RENAME TO {t}")
        await _rename_new_objects(conn, t)


async def _swap_tx(conn, lock_timeout: str) -> None:
    async with conn.transaction():
        # Bounded wait: a queued ACCESS EXCLUSIVE request blocks every new SELECT on the table.
        await conn.execute(f"SET LOCAL lock_timeout = '{lock_timeout}'")
        await _lock_for_swap(conn, SWAP_LOCK_ORDER)
        await conn.execute(f"DROP TABLE IF EXISTS {OCC}")
        await conn.execute(f"DROP TABLE IF EXISTS {DS}")
        await conn.execute(f"ALTER TABLE {DS}_new RENAME TO {DS}")
        await conn.execute(f"ALTER TABLE {OCC}_new RENAME TO {OCC}")
        for table in (OCC, DS):
            await _rename_new_objects(conn, table)
        seq = await conn.fetchval("SELECT pg_get_serial_sequence($1, 'id')", OCC)
        if seq and seq.endswith(f"{OCC}_new_id_seq"):
            await conn.execute(f"ALTER SEQUENCE {seq} RENAME TO {OCC}_id_seq")
        # Stage 2: the aggregates built from THIS staging go live in the same transaction, so the map
        # can never show new counts on an old grid (or the reverse).
        await _swap_aggregates_in_tx(conn)
        await conn.execute(f"DROP TABLE IF EXISTS {PROG}_new")      # the run's ledger dies with its staging


def _forget_meta_cache() -> None:
    """/v1/plankton/meta caches its counts; drop them the moment new data is live. (Only reaches
    this process; the API process also re-keys on sync_log, see domains/plankton.py.)"""
    from response_cache import store
    store.pop("plankton-meta", None)


async def _build_valid_aggregates(conn, source: str) -> str:
    """Build the `_new` aggregates from `source` in ONE transaction and check them; return the new version.
    Only AggregatesInvalid (a failed check) means "this staging is bad": the half-built aggregates are
    dropped and it propagates. Any other exception (asyncpg error, lock timeout, MemoryError) is
    infrastructure: the staging must survive for --resume / --aggregates-only, so it is tagged
    `keep_staging` (the orchestrator then does not discard) and re-raised unchanged."""
    try:
        async with conn.transaction():
            version = await agg.build_aggregates(conn, source)
        await agg.require_valid_aggregates(conn, source)
    except AggregatesInvalid:
        await agg.drop_aggregates(conn)
        raise
    except Exception as e:
        e.keep_staging = True
        raise
    return version


async def swap(conn, *, lock_timeout: str = SWAP_LOCK_TIMEOUT,
               backoff: tuple[float, ...] = SWAP_BACKOFF_S) -> None:
    """Index, count and ANALYZE the staging pair, build and check the aggregates from it, then replace the live pair in ONE transaction
    (DDL is transactional: any failure rolls every rename back). Does not validate.
    Each attempt waits at most `lock_timeout` for its locks; after the last failed attempt
    raises SwapLockTimeout, leaving live and `_new` intact."""
    import asyncio
    for sql in occurrences_index_ddl(f"{OCC}_new"):
        await conn.execute(sql)
    await conn.execute(
        f"UPDATE {DS}_new d SET record_count = c.n FROM "
        f"(SELECT dataset_id, count(*) n FROM {OCC}_new GROUP BY 1) c WHERE c.dataset_id = d.dataset_id")
    await conn.execute(f"ANALYZE {OCC}_new")
    await conn.execute(f"ANALYZE {DS}_new")
    # Before any lock is requested: a failed aggregate build must never cost the live tables a lock wait.
    await _build_valid_aggregates(conn, f"{OCC}_new")
    for attempt in range(len(backoff) + 1):
        try:
            await _swap_tx(conn, lock_timeout)
            _forget_meta_cache()
            return
        except _LOCK_CONTENTION as e:
            if attempt == len(backoff):
                raise SwapLockTimeout(
                    f"plankton swap: no lock on the live tables after {attempt + 1} attempts "
                    f"of {lock_timeout}; live and staging tables left intact") from e
            await asyncio.sleep(backoff[attempt])


async def swap_validated(conn) -> None:
    """validate_staging, then swap; on reasons drop the staging pair (live untouched)
    and raise SwapBlocked."""
    reasons = await validate_staging(conn)
    if reasons:
        await discard_staging(conn)
        raise SwapBlocked(reasons)
    try:
        await swap(conn)
    except AggregatesInvalid as e:
        await discard_staging(conn)
        raise SwapBlocked(e.reasons) from e


async def rebuild_aggregates_from_live(conn, *, lock_timeout: str = SWAP_LOCK_TIMEOUT,
                                       backoff: tuple[float, ...] = SWAP_BACKOFF_S) -> str:
    """Build the stage-2 aggregates from the LIVE plankton_occurrences and swap only them in — the first
    deploy of the map layer (the next import is up to a month away) and repairs. Live rows are untouched.
    Raises SwapBlocked (a failed check; old aggregates stay live) or SwapLockTimeout; an infrastructure
    error propagates unchanged (there is no staging to keep, the live aggregates are intact either way).
    Returns the new version."""
    try:
        version = await _build_valid_aggregates(conn, OCC)
    except AggregatesInvalid as e:
        raise SwapBlocked(e.reasons) from e
    for attempt in range(len(backoff) + 1):
        try:
            async with conn.transaction():
                await conn.execute(f"SET LOCAL lock_timeout = '{lock_timeout}'")
                await _lock_for_swap(conn, AGG_TABLES)
                await _swap_aggregates_in_tx(conn)
            _forget_meta_cache()
            return version
        except _LOCK_CONTENTION as e:
            if attempt == len(backoff):
                raise SwapLockTimeout(
                    f"plankton aggregates: no lock after {attempt + 1} attempts of {lock_timeout}; "
                    "live aggregates left intact") from e
            await asyncio.sleep(backoff[attempt])


# ---------------------------------------------------------------------------
# Orchestrator. One run = select datasets (OBIS API) -> resolve licences -> per dataset
# extract / load / delete the extract -> validate -> swap. Every exit path writes
# sync_log under SOURCE; every failure path (blocked, lock timeout, error) alerts.
# ---------------------------------------------------------------------------
import asyncio  # noqa: E402
import contextlib  # noqa: E402
import csv  # noqa: E402
import ctypes  # noqa: E402
import gc  # noqa: E402
import io  # noqa: E402
import json as _json  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
import urllib.request  # noqa: E402

import asyncpg  # noqa: E402

import db  # noqa: E402
from api_access.notify import notify_telegram  # noqa: E402
from schema.plankton import SWAPPED_PARTIAL_PREFIX  # noqa: E402
from sync_log import log_sync, log_sync_skipped  # noqa: E402

log = logging.getLogger(__name__)
SOURCE = "plankton-obis"
# WoRMS-verified taxonIDs (preflight 2026-10-02). The OBIS /dataset API includes descendants.
TAXON_IDS = (1080, 1128, 148898, 592906, 115057, 369190, 19542, 146203)
OBIS_API = "https://api.obis.org/v3/dataset"
LICENCES_URL = "https://obis-open-data.s3.amazonaws.com/licenses.tsv"
SCRATCH_DIR = os.getenv("PLANKTON_SCRATCH_DIR", "/var/cache/abyssal-plankton")
ALERT_TITLE = "Abyssal plankton import TRIP"
LOCK_TIMEOUT_REASON = "swap lock timeout — live and staging intact"
# Written (as a sync_log skip) the moment a real import starts. A run killed by OOM / TimeoutStartSec /
# SIGTERM runs no except-block, so this marker is all it leaves; the worker reads one older than
# STARTED_STALE as a failed run, /v1/plankton/meta as "running" while fresh, "error" once stale.
STARTED_REASON = STARTED_PREFIX + ": import in progress"
SCRATCH_REASON = "error: scratch directory unusable"
# Dataset failures are loud: up to max(FAILED_FLOOR, FAILED_FRACTION of the attempted) the swap still
# goes ahead (with an alert and a count in sync_log); beyond that nothing is swapped.
FAILED_FLOOR = 3
FAILED_FRACTION = 0.02
ALERT_UUIDS = 10
# A closed/lost Postgres connection is never "one bad dataset": it ends the run at once.
_PG_CONNECTION_ERRORS = (asyncpg.InterfaceError, asyncpg.PostgresConnectionError,
                         asyncpg.exceptions.ConnectionDoesNotExistError)


class DatasetFailures(Exception):
    """Too many datasets failed (or all of them): the run ends without a swap."""


def failure_threshold(attempted: int) -> int:
    return max(FAILED_FLOOR, math.ceil(FAILED_FRACTION * attempted))


def _failed_summary(failed_ids: list[str], attempted: int) -> str:
    shown = ", ".join(failed_ids[:ALERT_UUIDS])
    more = f" (+{len(failed_ids) - ALERT_UUIDS} more)" if len(failed_ids) > ALERT_UUIDS else ""
    return f"{len(failed_ids)} of {attempted} datasets failed: {shown}{more}"


# ---------------------------------------------------------------------------
# Extract in a CHILD process, one per dataset (see plankton_extract_child.py for why).
# ---------------------------------------------------------------------------
CHILD_TIMEOUT_S = 150 * 60           # a hung S3 read ends the dataset, not the run
PROGRESS_EVERY = 50                  # datasets between progress lines ...
PROGRESS_SLOW_S = 60                 # ... or any single dataset slower than this
_BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent


class ChildFailed(Exception):
    """The extract child died, timed out or reported an error. `.reason` is type / exit code only
    (never a message: those can carry the source URL)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


_CHILD_PIDS: set[int] = set()        # live extract children (the memory guard's fallback reads their RSS)


def _child_argv() -> list[str]:
    return [sys.executable, "-m", "ingestion.plankton_extract_child"]


async def extract_in_child(source: str, dest: pathlib.Path, scratch: pathlib.Path,
                           title: str | None = None, *, timeout: float | None = None) -> tuple[int, int]:
    """Run extract_dataset for ONE dataset in a fresh interpreter -> (rows, child peak RSS MB).
    Raises ChildFailed on a non-zero exit, a signal (OOM kill), no result, or `timeout` seconds
    (default CHILD_TIMEOUT_S). The child is ALWAYS gone when this returns or raises, including when
    the parent is cancelled: no zombie keeps eating the cgroup's memory."""
    timeout = CHILD_TIMEOUT_S if timeout is None else timeout
    request = _json.dumps({"source": source, "dest": str(dest), "scratch": str(scratch), "title": title})
    proc = await asyncio.create_subprocess_exec(
        *_child_argv(), cwd=str(_BACKEND_DIR), stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    _CHILD_PIDS.add(proc.pid)
    try:
        try:
            out, _ = await asyncio.wait_for(proc.communicate(request.encode()), timeout)
        except asyncio.TimeoutError:
            raise ChildFailed(f"timeout after {int(timeout)} s") from None
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        _CHILD_PIDS.discard(proc.pid)
    lines = out.decode("utf-8", "replace").strip().splitlines()
    try:
        result = _json.loads(lines[-1]) if lines else {}
    except ValueError:
        result = {}
    rc = proc.returncode
    if rc != 0:
        how = f"killed by signal {-rc}" if rc < 0 else f"exit code {rc}"
        err = result.get("error") if isinstance(result, dict) else None
        raise ChildFailed(f"{how}" + (f" ({str(err)[:60]})" if err else ""))
    if not isinstance(result, dict) or "rows" not in result:
        raise ChildFailed("exit code 0 but no result")
    return int(result["rows"]), int(result.get("peak_rss_mb") or 0)


# ---------------------------------------------------------------------------
# Parallel extraction. The import is network-bound (S3 latency/throughput), so several extract children
# run at once; Postgres loads stay sequential on the parent's ONE connection (see _import).
# Admission (strictly in listing order, no overtaking, so a giant is never starved):
#   1. weight budget — S3 object size: >= 2 GB -> 3 (alone), 0.5-2 GB -> 2, smaller -> 1; the weights of
#      the RUNNING children never exceed WEIGHT_BUDGET (unknown size -> treated as big);
#   2. at most PLANKTON_PARALLEL children, counting finished-but-not-yet-loaded extracts too, so
#      parquet files waiting for the load never exceed that number (bounded scratch disk);
#   3. a live memory guard: no new child while the memory in use is above MEM_GUARD_MB — except when
#      nothing is running (a lone parent above the guard must still make progress: no deadlock).
# ---------------------------------------------------------------------------
WEIGHT_BUDGET = 3
BIG_BYTES, MID_BYTES = 2 * 1024**3, 512 * 1024**2
MEM_GUARD_MB = 1250
MEM_POLL_S = 2.0
DEFAULT_PARALLEL = 3


def _parallel() -> int:
    """PLANKTON_PARALLEL (default 3; 1 = the old strictly sequential behaviour)."""
    try:
        return max(1, int(os.getenv("PLANKTON_PARALLEL", DEFAULT_PARALLEL)))
    except ValueError:
        return DEFAULT_PARALLEL


def weight_for_size(size: int | None) -> int:
    if size is None or size >= BIG_BYTES:
        return WEIGHT_BUDGET
    return 2 if size >= MID_BYTES else 1


def _source_size(source: str) -> int | None:
    """Byte size of an extract source: a local file (tests) or an S3 object via HEAD Content-Length.
    None on any failure (the caller then assumes big)."""
    try:
        if "://" not in str(source):
            return os.stat(source).st_size
        for attempt in range(2):
            try:
                req = urllib.request.Request(str(source), method="HEAD")
                with urllib.request.urlopen(req, timeout=20) as r:
                    return int(r.headers["Content-Length"])
            except Exception:
                if attempt:
                    raise
    except Exception:
        return None
    return None


def _cgroup_anon_mb() -> int | None:
    """Anonymous memory of THIS cgroup (cgroup v2 memory.stat). Not memory.current: that counts the
    page cache of the parquet files too, which the kernel reclaims and which would hold the guard shut."""
    try:
        with open("/proc/self/cgroup") as f:
            rel = next(line.strip().split("::", 1)[1] for line in f if line.startswith("0::"))
        with open(f"/sys/fs/cgroup{rel}/memory.stat") as f:
            for line in f:
                if line.startswith("anon "):
                    return int(line.split()[1]) // (1024 * 1024)
    except (OSError, StopIteration, IndexError, ValueError):
        pass
    return None


def _pid_rss_mb(pid: int) -> int:
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) // 1024
    except OSError:
        pass
    return 0


def _mem_in_use_mb() -> int:
    """Memory in use by the import: the cgroup's anonymous memory when readable, else the parent's RSS
    plus the RSS of the live extract children."""
    anon = _cgroup_anon_mb()
    if anon is not None:
        return anon
    return _rss_mb() + sum(_pid_rss_mb(pid) for pid in list(_CHILD_PIDS))


def _memory_allows_child() -> bool:
    return _mem_in_use_mb() <= MEM_GUARD_MB


class ExtractStream:
    """Runs `run_one(i)` for `ids` with the admission rules above and yields (i, result, error) in
    COMPLETION order. The consumer's loop body (the load) runs between two `next` calls; a slot is only
    released when the consumer asks for the next result, which is what bounds the files on disk.
    Always iterate it inside `contextlib.aclosing(...)`: closing cancels every running task (each child
    is killed in extract_in_child's own finally)."""

    def __init__(self, ids, run_one, weigh, parallel, *, budget=WEIGHT_BUDGET, mem_ok=None):
        self.queue = list(ids)
        self.run_one, self.weigh = run_one, weigh
        self.parallel, self.budget = max(1, parallel), budget
        self.mem_ok = mem_ok or _memory_allows_child
        self.tasks: dict[asyncio.Task, tuple[str, int]] = {}

    @property
    def in_flight(self) -> int:
        return sum(1 for t in self.tasks if not t.done())

    def _running(self):
        return [t for t in self.tasks if not t.done()]

    async def results(self):
        nxt = 0
        weights: dict[str, int] = {}
        try:
            while nxt < len(self.queue) or self.tasks:
                blocked_on_memory = False
                while nxt < len(self.queue) and len(self.tasks) < self.parallel:
                    i = self.queue[nxt]
                    if i not in weights:
                        weights[i] = await self.weigh(i)
                    w = weights[i]
                    running = self._running()
                    if running:
                        if sum(self.tasks[t][1] for t in running) + w > self.budget:
                            break
                        if not self.mem_ok():
                            blocked_on_memory = True
                            break
                    nxt += 1
                    self.tasks[asyncio.ensure_future(self.run_one(i))] = (i, w)
                done, _ = await asyncio.wait(
                    list(self.tasks), return_when=asyncio.FIRST_COMPLETED,
                    timeout=MEM_POLL_S if blocked_on_memory else None)
                # ONE result per round: the slot is released and the admission loop runs again before the
                # next result is handed out.
                if not done:
                    continue                             # memory poll tick: look at admission again
                t = next(iter(done))
                i, _w = self.tasks[t]
                if t.cancelled():
                    t.result()                           # raises CancelledError: not "one failed dataset"
                err = t.exception()
                if err is not None and not isinstance(err, Exception):
                    raise err
                yield i, (None if err else t.result()), err
                del self.tasks[t]                        # released only now: the consumer has loaded it
        finally:
            pending = list(self.tasks)
            for t in pending:
                t.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            self.tasks.clear()


def _rss_mb() -> int:
    """Resident set of THIS process (VmRSS on Linux, peak elsewhere)."""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) // 1024
    except OSError:
        pass
    import resource
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak / (1024 * 1024) if sys.platform == "darwin" else peak / 1024)


def _release_memory() -> None:
    """Hand freed heap back to the OS: glibc keeps it otherwise, and a run lasts hours."""
    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        pass


def _retrying(fetch):
    """fetch() with up to 6 attempts and a linear back-off; the last failure propagates."""
    for attempt in range(6):
        try:
            return fetch()
        except Exception:
            if attempt == 5:
                raise
            time.sleep(5 * (attempt + 1))


def _http_json(url: str, params: dict) -> dict:
    from urllib.parse import urlencode

    def fetch():
        with urllib.request.urlopen(f"{url}?{urlencode(params)}", timeout=120) as r:
            return _json.load(r)
    return _retrying(fetch)


def _http_text(url: str) -> str:
    def fetch():
        with urllib.request.urlopen(url, timeout=300) as r:
            return r.read().decode("utf-8")
    return _retrying(fetch)


async def select_datasets(fetch_json) -> dict[str, dict]:
    """OBIS dataset objects (id -> metadata) holding any of TAXON_IDS, deduplicated across taxa.
    ⛔ Paginates with `skip`: the API silently ignores `offset` and returns page one forever."""
    out: dict[str, dict] = {}
    for taxon in TAXON_IDS:
        skip = 0
        while True:
            j = await asyncio.to_thread(fetch_json, OBIS_API, {"taxonid": taxon, "size": 100, "skip": skip})
            results = j.get("results") or []
            if not results:
                break
            for d in results:
                try:
                    ds_id = str(uuid.UUID(str(d["id"])))   # canonical lower-case; used for paths and URLs
                except (ValueError, KeyError, AttributeError, TypeError):
                    log.warning("plankton-obis: skipping dataset with invalid id %.60r", d.get("id"))
                    continue
                out[ds_id] = {**d, "id": ds_id}
            skip += len(results)
            if skip >= (j.get("total") or 0):
                break
    return out


def parse_licences(tsv: str) -> dict[str, dict]:
    rows = csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE)
    return {r["id"]: r for r in rows if r.get("id")}


def resolve_dataset(meta: dict, tsv_row: dict | None) -> dict:
    """Licence: the dataset's own `intellectualrights` (OBIS API) FIRST; licenses.tsv only when
    that is empty (the tsv misses ~1,600 of ~6,900 datasets, incl. the CPR Survey).
    Citation: tsv citation, else the API citation, else the title."""
    tsv_row = tsv_row or {}
    raw = (meta.get("intellectualrights") or "").strip() or (tsv_row.get("license") or "").strip() or None
    inst = meta.get("institutes") or []
    return dict(
        dataset_id=str(meta["id"]), title=meta.get("title"),
        institution=inst[0].get("name") if inst and isinstance(inst[0], dict) else None,
        licence=normalise_licence(raw), licence_raw=raw, url=meta.get("url"),
        citation=(tsv_row.get("citation") or "").strip() or meta.get("citation") or meta.get("title"))


def _scrub(exc: BaseException, limit: int = 200) -> str:
    """type + short message with every URL (they may carry tokens) masked."""
    msg = re.sub(r"https?://\S+", "<url>", str(exc)).replace("\n", " ")
    return f"{type(exc).__name__}: {msg}"[:limit]


async def _outcome(skip_reason: str | None, kept: int = 0, *, alert: bool) -> None:
    """Record the exit in sync_log (never raises: a failing log must not mask the real outcome)
    and, for failure paths, alert."""
    try:
        if skip_reason is None:
            await log_sync(SOURCE, kept, kept)       # full rebuild: every row held was "added"
        else:
            await log_sync_skipped(SOURCE, skip_reason)
    except Exception:
        log.exception("plankton-obis: could not write sync_log")
    if alert:
        await notify_telegram(f"plankton-obis: {skip_reason}", ALERT_TITLE)


async def _record_partial(res: dict) -> None:
    """The swap went through but some datasets were lost: record the count in a fixed-format token
    on the success row (sync_log.skipped_reason; last_synced_at stays the success) and alert."""
    n, msg = res["failed_datasets"], _failed_summary(res["failed_ids"], res["attempted"])
    try:
        async with db.pool.acquire() as conn:
            await conn.execute(
                "UPDATE sync_log SET skipped_reason = $2, skipped_at = NOW() WHERE source = $1",
                SOURCE, f"{SWAPPED_PARTIAL_PREFIX}: failed_datasets={n}")
    except Exception:
        log.exception("plankton-obis: could not record failed_datasets in sync_log")
    await notify_telegram(f"plankton-obis: swapped, but {msg}", ALERT_TITLE)


async def _mark_started() -> None:
    """Leave the "started" marker in sync_log. Never raises. It is overwritten by every normal exit
    (log_sync clears it, log_sync_skipped replaces it); only a killed process leaves it behind."""
    try:
        await log_sync_skipped(SOURCE, STARTED_REASON)
    except Exception:
        log.exception("plankton-obis: could not write the started marker")


TILES_SOURCE = "plankton-tiles"


async def bake_tiles() -> None:
    """After a swap (import or --aggregates-only): pre-bake the default map view into the tile cache and
    record the outcome in sync_log under TILES_SOURCE. Never raises: the data is already live; a failed bake
    only makes first views slower until tiles are rendered on demand. The logged outcome is a fixed
    vocabulary ("error: <ExceptionType>" / "error: bake deadline" / "error: consecutive timeouts" / "error: no tile version" /
    "skipped: version changed" / "skipped: N tiles timed out"), never exception text."""
    from services import plankton_tiles as tiles
    started = time.monotonic()
    try:
        n, skipped = await tiles.prebake(db.pool, tiles.cache_root())
    except Exception as e:
        log.exception("plankton-tiles: pre-bake failed")
        alert = True
        if isinstance(e, tiles.BakeVersionChanged):
            reason, alert = "skipped: version changed", False
        elif isinstance(e, tiles.BakeNoVersion):
            reason = "error: no tile version"
        elif isinstance(e, tiles.BakeConsecutiveTimeouts):
            reason = "error: consecutive timeouts"
        elif isinstance(e, tiles.BakeStopped):
            reason = "error: bake deadline"
        else:
            reason = f"error: {type(e).__name__}"
        try:
            await log_sync_skipped(TILES_SOURCE, reason)
        except Exception:
            log.exception("plankton-tiles: could not write sync_log")
        if alert:
            await notify_telegram(f"plankton-tiles: pre-bake failed ({reason})", ALERT_TITLE)
        return
    log.info("plankton-tiles: %d tiles baked, %d timed out, in %d s", n, skipped, time.monotonic() - started)
    try:
        if skipped:
            await log_sync_skipped(TILES_SOURCE, f"skipped: {skipped} tiles timed out")
        else:
            await log_sync(TILES_SOURCE, n, n)
    except Exception:
        log.exception("plankton-tiles: could not write sync_log")


async def _table_exists(conn, name: str) -> bool:
    return bool(await conn.fetchval("SELECT to_regclass($1)", name))


async def _prepare_resume(conn) -> set[str] | None:
    """The ids already loaded into the existing staging pair, or None = nothing to resume (the caller
    falls back to a normal full run). NEVER builds or drops staging.
    Ledger present: its rows are exact (each was written in the same transaction as the dataset's load).
    Ledger absent (a run that predates it): the distinct dataset_ids in plankton_occurrences_new, and the
    ledger is created and seeded from their counts. That fallback is only exact if the old run was stopped
    while no COPY was running (old code: 50k-row autocommitted batches) — see plankton_obis_worker."""
    if not (await _table_exists(conn, f"{OCC}_new") and await _table_exists(conn, f"{DS}_new")):
        log.warning("plankton-obis: --resume but %s_new / %s_new do not both exist — running a normal full import",
                    OCC, DS)
        return None
    if not await _table_exists(conn, f"{PROG}_new"):
        async with conn.transaction():
            for sql in progress_ddl(f"{PROG}_new"):
                await conn.execute(sql)
            await conn.execute(f"INSERT INTO {PROG}_new (dataset_id, rows) "
                               f"SELECT dataset_id, count(*)::int FROM {OCC}_new GROUP BY 1")
        log.warning("plankton-obis: --resume: no ledger — seeded %s_new from the rows already in %s_new",
                    PROG, OCC)
    return {str(r[0]) for r in await conn.fetch(f"SELECT dataset_id FROM {PROG}_new")}


async def _load_one(conn, dest, licences, dataset_id: str) -> dict[str, int]:
    """ONE transaction per dataset: every COPY batch of its rows AND its ledger row commit together, or
    (a failure, a kill) none of it does."""
    async with conn.transaction():
        stats = await load_extract(conn, dest, licences)
        await record_progress(conn, dataset_id, stats["kept"])
    return stats


async def _import(fetch_json, fetch_licences, source_for, scratch: pathlib.Path, resume: bool = False,
                  state: dict | None = None) -> dict:
    """Everything up to and including the swap. Raises SwapBlocked / SwapLockTimeout / anything."""
    meta = await select_datasets(fetch_json)
    try:
        lic_rows = parse_licences(await asyncio.to_thread(fetch_licences))
    except Exception as e:      # only a fallback source (intellectualrights comes first): never abort for it
        log.warning("plankton-obis: licenses.tsv unavailable (%s) — using intellectualrights only", type(e).__name__)
        lic_rows = {}
    resolved = {i: resolve_dataset(m, lic_rows.get(i)) for i, m in meta.items()}
    licences = {i: d["licence"] for i, d in resolved.items()}
    drops = {k: 0 for k in DROP_REASONS}
    failed_ids: list[str] = []
    attempted = rows_so_far = 0
    total = len(meta)
    never = {i for i in meta if i in EXCLUDED_DATASETS or licences[i] == "restricted"}   # not even downloaded
    skipped = len(never)
    parallel = _parallel()
    async with db.pool.acquire() as conn:
        done: set[str] = set()
        if resume:
            found = await _prepare_resume(conn)
            resume = found is not None
            done = found or set()
            if state is not None:
                state["resumed"] = resume       # the caller keeps (does not discard) a resumed staging on failure
        if resume:
            # Datasets loaded earlier that a full run would no longer keep (unlisted, excluded, restricted):
            # their rows go, so a resumed run ends with the same table a full run would.
            stale = sorted(i for i in done if i not in meta or i in never)
            if stale:
                log.warning("plankton-obis: --resume: dropping %d already-loaded datasets that are no longer kept", len(stale))
                await conn.execute(f"DELETE FROM {OCC}_new WHERE dataset_id = ANY($1::uuid[])", stale)
                await conn.execute(f"DELETE FROM {PROG}_new WHERE dataset_id = ANY($1::uuid[])", stale)
                await conn.execute(f"DELETE FROM {DS}_new WHERE dataset_id = ANY($1::uuid[])", stale)
                done -= set(stale)
            await load_datasets(conn, [d for i, d in resolved.items() if i not in done], mode="upsert")
            await load_datasets(conn, [d for i, d in resolved.items() if i in done], mode="ignore")
            rows_so_far = await conn.fetchval(f"SELECT coalesce(sum(rows), 0)::bigint FROM {PROG}_new")
            log.info("plankton-obis: --resume: %d of %d datasets already loaded (%d rows), %d to go",
                     len(done), total, rows_so_far, total - len(done) - skipped)
        else:
            await build_staging(conn)
            await load_datasets(conn, list(resolved.values()))
        todo = [i for i in meta if i not in never and i not in done]
        processed = total - len(todo)

        async def run_one(i):
            started = time.monotonic()
            rows, peak = await extract_in_child(source_for(i), scratch / f"{i}.parquet", scratch,
                                                title=meta[i].get("title"))
            return rows, peak, time.monotonic() - started

        async def weigh(i):
            return weight_for_size(await asyncio.to_thread(_source_size, source_for(i)))

        stream = ExtractStream(todo, run_one, weigh, parallel)
        # Extracts run `parallel` at a time; the loads below stay ONE at a time on this connection,
        # in completion order.
        async with contextlib.aclosing(stream.results()) as results:
            async for i, res, err in results:
                attempted += 1
                processed += 1
                dest = scratch / f"{i}.parquet"
                phase, started, child_peak, took_extract = "extract", time.monotonic(), 0, 0.0
                try:
                    if err is not None:
                        raise err
                    rows, child_peak, took_extract = res
                    if rows:
                        phase = "load"
                        stats = await _load_one(conn, dest, licences, i)
                        rows_so_far += stats["kept"]
                        for k in drops:
                            drops[k] += stats[k]
                    else:
                        phase = "load"
                        await record_progress(conn, i, 0)
                except Exception as e:
                    # A lost Postgres connection is not a dataset failure: stop now instead of
                    # downloading and extracting every remaining dataset for nothing.
                    if isinstance(e, _PG_CONNECTION_ERRORS) or conn.is_closed() \
                            or (phase == "load" and isinstance(e, ConnectionError)):
                        raise
                    # One bad dataset (S3 404, corrupt parquet, odd schema, a child killed by the OOM
                    # killer or the timeout) must not sink the month's run. Type / exit code only: a
                    # message can carry the source URL. The >10 % drop check in swap_validated still
                    # protects the live table if too much goes missing. A failed load was one
                    # transaction (_load_one): nothing of the dataset is left, and it has NO ledger
                    # row, so a resume retries it.
                    failed_ids.append(i)
                    if isinstance(e, ChildFailed):
                        log.warning("plankton-obis: dataset %s extract child failed (%s) — skipped", i, e.reason)
                    else:
                        log.warning("plankton-obis: dataset %s failed (%s) — skipped", i, type(e).__name__)
                finally:
                    dest.unlink(missing_ok=True)
                _release_memory()
                took = took_extract + (time.monotonic() - started)
                if took > PROGRESS_SLOW_S or processed % PROGRESS_EVERY == 0:
                    log.info("plankton-obis: %d/%d datasets, rows so far %d, failed %d, rss %d MB "
                             "(child peak %d MB, last dataset %d s, in flight %d)",
                             processed, total, rows_so_far, len(failed_ids), _rss_mb(), child_peak, took,
                             stream.in_flight)
        failed = len(failed_ids)
        if attempted and failed == attempted:
            raise DatasetFailures(f"every attempted dataset failed ({_failed_summary(failed_ids, attempted)})"
                                  " — a code or connection fault, not a data problem")
        if failed > failure_threshold(attempted):
            raise DatasetFailures(f"too many datasets failed, no swap ({_failed_summary(failed_ids, attempted)};"
                                  f" threshold {failure_threshold(attempted)})")
        # datasets that contributed no row are noise in the attribution table
        await conn.execute(
            f"DELETE FROM {DS}_new d WHERE NOT EXISTS (SELECT 1 FROM {OCC}_new o WHERE o.dataset_id = d.dataset_id)")
        await swap_validated(conn)           # raises SwapBlocked (staging dropped) / SwapLockTimeout
        groups = {r[0]: r[1] for r in await conn.fetch(
            f"SELECT taxon_group, count(*) FROM {OCC} GROUP BY 1 ORDER BY 1")}
        split = {r[0]: r[1] for r in await conn.fetch(
            f"SELECT licence, count(*) FROM {DS} GROUP BY 1 ORDER BY 1")}
    kept = sum(groups.values())
    return {"outcome": "swapped", "kept": kept, "total": kept, "datasets": sum(split.values()),
            "groups": groups, "licences": split, "drops": drops, "reasons": [],
            "failed_datasets": failed, "failed_ids": failed_ids, "attempted": attempted,
            "skipped_datasets": skipped, "resumed": resume, "already_loaded": len(done)}


async def sync_plankton_obis(*, fetch_json=None, fetch_licences=None, source_for=None,
                             scratch: pathlib.Path | None = None, resume: bool = False) -> dict:
    """Monthly full rebuild. Never raises (the worker decides about retries from `outcome`):
    "swapped" | "blocked" (validation, live untouched, staging dropped) |
    "lock_timeout" (live untouched, `_new` staging pair LEFT in place until the next run's
    build_staging drops it) | "error" (live untouched, staging dropped best-effort).
    Seams: fetch_json(url, params) -> dict, fetch_licences() -> tsv text, source_for(id) -> path/URL.
    resume=True continues an interrupted run on the EXISTING staging pair (never build_staging): see
    _prepare_resume. Extraction parallelism: PLANKTON_PARALLEL (default 3)."""
    fetch_json = fetch_json or _http_json
    fetch_licences = fetch_licences or (lambda: _http_text(LICENCES_URL))
    source_for = source_for or (lambda i: f"{OBIS_HTTP_BASE}{i}.parquet")
    run_dir = pathlib.Path(scratch or SCRATCH_DIR) / "run"
    state = {"resumed": False}
    await _mark_started()
    try:
        shutil.rmtree(run_dir, ignore_errors=True)
        try:
            run_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            log.exception("plankton-obis: scratch directory unusable")
            await _outcome(SCRATCH_REASON, alert=True)
            return {"outcome": "error", "kept": 0, "reasons": [SCRATCH_REASON]}
        res = await _import(fetch_json, fetch_licences, source_for, run_dir, resume=resume, state=state)
    except DatasetFailures as e:
        # Staging was never swapped in; the live table is untouched. Full message (count + UUIDs): UUIDs are public ids.
        try:
            if not state["resumed"]:       # a resumed staging holds hours of work: keep it for the next --resume
                async with db.pool.acquire() as conn:
                    await discard_staging(conn)
        except Exception:
            log.exception("plankton-obis: could not discard staging after dataset failures")
        res = {"outcome": "error", "kept": 0, "reasons": [str(e)]}
        await _outcome("error: " + str(e), alert=True)
    except SwapBlocked as e:
        res = {"outcome": "blocked", "kept": 0, "reasons": e.reasons}
        await _outcome("swap blocked — " + "; ".join(e.reasons), alert=True)
    except SwapLockTimeout:
        res = {"outcome": "lock_timeout", "kept": 0, "reasons": [LOCK_TIMEOUT_REASON]}
        await _outcome(LOCK_TIMEOUT_REASON, alert=True)
    except Exception as e:
        log.exception("plankton-obis failed")
        try:
            # keep_staging: an infrastructure error in the aggregate build (see _build_valid_aggregates)
            if not state["resumed"] and not getattr(e, "keep_staging", False):
                async with db.pool.acquire() as conn:
                    await discard_staging(conn)
        except Exception:
            log.exception("plankton-obis: could not discard staging after the error")
        res = {"outcome": "error", "kept": 0, "reasons": [_scrub(e)]}
        await _outcome("error: " + _scrub(e), alert=True)
    else:
        log.info("plankton-obis: swapped %s rows from %s datasets", res["kept"], res["datasets"])
        await _outcome(None, res["kept"], alert=False)
        if res["failed_datasets"]:
            await _record_partial(res)
        await bake_tiles()
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)
    return res
