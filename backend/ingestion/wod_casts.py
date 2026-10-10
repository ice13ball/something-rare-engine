# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""WOD23 casts import (`wod-casts`) — runs ONLY in the wod-casts worker, never in abyssal-api; nothing runs on import.

Discovery (`discover_and_mark`) lists the NCEI year directories, HEADs every file and records the result in
`wod_files`. The import (`sync_wod_casts`) takes the pending files largest first and, per file: preflight on the
two filesystems, download to WOD_DOWNLOAD_DIR, parse into UNLOGGED staging tables (`staging_ddl()`, created here,
never by ensure_wod_casts), then ONE transaction that deletes the file's previous rows and inserts the staged ones.
When nothing is pending any more the LOD cells (`wod_cells`) are rebuilt as `wod_cells_new` and swapped with the
tile version in one transaction.

Cast-id duplicates (the same wod_unique_cast in two files): the first loaded wins. A repeat inside one file is
dropped before staging; a cast already stored by ANOTHER file is skipped by `ON CONFLICT (cast_id) DO NOTHING` on
the live table (staging has no key, nothing conflicts against it) and the points are derived from the casts that
were really inserted (join on cast_id AND file_id). Both are counted as `duplicate_cast_id`.
Identity per file (copied to `wod_files.rejects`, which also holds every parser stat):
  source = no_depth_levels + no_values + bad_coords + duplicate_cast_id + stored      drawn = stored - no_good - no_date
`no_good` / `no_date` are recomputed from the stored rows, so a duplicate never skews `drawn`.

`sync_wod_casts` never raises. A failed, blocked or interrupted file leaves the live rows of every other file
untouched; a file's rows are replaced only inside one transaction that also inserts its new rows.
"""
from __future__ import annotations

import asyncio
import collections
import contextlib
import json
import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

import asyncpg

import db
from ingestion import USER_AGENT
from ingestion import wod_casts_parse as P
from ingestion import wod_casts_rules as R
from schema.wod_casts import cells_ddl, cells_index_names, staging_ddl
from sync_log import log_sync as _log_sync
from sync_log import log_sync_skipped

log = logging.getLogger(__name__)

SOURCE = R.SOURCE
CURL = "/usr/bin/curl"
SLICE_PAUSE_S = 1.0                    # between COPY chunks: lets checkpoints, autovacuum and the site breathe
DISK_PATH = os.getenv("WOD_CASTS_DISK_PATH", "/var/lib/postgresql")      # the volume that holds PostgreSQL
STAGE_FRACTION = 0.12                  # staged bytes (staging + the swap insert) per byte of netCDF, measured in Phase 0
LOD_CELLS_ESTIMATE = int(1.2 * 1024 ** 3)   # wod_cells size (table + pkey); the live size is used once it is larger
DOWNLOAD_HEADROOM = 1024 ** 3          # the download filesystem keeps this much free beyond the file itself
DOWNLOAD_TIMEOUT_S = 3 * 3600
LOCK_BACKOFF = (10, 30, 60)            # four attempts at a 3 s lock_timeout
MAX_FAIL_STREAK = 3                    # consecutive failed files stop the run (network down, format changed)

CAST_COLUMNS = (["cast_id", "file_id", "instrument", "dataset", "lat", "lon", "cast_date", "cast_time",
                 "time_precision", "year"] + list(P.META_FIELDS)
                + ["access_no", "depth", "depth_flag"] + [v[0] for v in R.VARS] + [f"{v[0]}_f" for v in R.VARS]
                + ["pflag", "n_src", "n_good"])
POINT_COLUMNS = ["cast_id", "file_id", "year", "key", "x", "y", "picks"]


class DiskStop(Exception):
    pass


class SwapMismatch(Exception):
    """A count inside the swap transaction disagrees with the one measured before it: roll back."""


class LodMismatch(Exception):
    pass


# ── listing / HEAD ───────────────────────────────────────────────────────────────────────────────────────

def parse_year_dirs(html: str) -> list[int]:
    return sorted({int(y) for y in R.YEAR_DIR_RE.findall(html)})


def parse_year_files(html: str) -> list[tuple[str, str, int]]:
    """(file name, instrument, year) per dataset file link, in page order, each once."""
    seen: dict[str, tuple[str, str, int]] = {}
    for name, inst, year in R.FILE_HREF_RE.findall(html):
        seen.setdefault(name, (name, inst, int(year)))
    return list(seen.values())


def _header_blocks(text: str) -> dict:
    """The LAST response's headers from `curl -sSI` output (redirects leave several blocks) + its status line."""
    blocks = [b for b in text.replace("\r\n", "\n").split("\n\n") if b.strip()]
    out: dict[str, str] = {}
    if blocks:
        lines = blocks[-1].split("\n")
        out["_status"] = lines[0].strip()
        for line in lines[1:]:
            k, _, v = line.partition(":")
            out[k.strip().lower()] = v.strip()
    return out


def head(url: str) -> dict:
    """{"content_length", "last_modified"} of one file (HEAD, no body). The VPS has no IPv6 route to NCEI: curl -4."""
    cp = subprocess.run([CURL, "-4", "-fsSIL", "--retry", "3", "--connect-timeout", "30", "-m", "120",
                         "-A", USER_AGENT, url], check=True, capture_output=True, text=True, timeout=600)
    h = _header_blocks(cp.stdout)
    try:
        length = int(h.get("content-length") or 0)
    except ValueError:
        length = 0
    if length <= 0:
        raise ValueError(f"no usable Content-Length ({h.get('_status')})")
    return {"content_length": length, "last_modified": h.get("last-modified")}


def _get_text(url: str) -> str:
    cp = subprocess.run([CURL, "-4", "-fsSL", "--retry", "3", "--connect-timeout", "30", "-m", "120",
                         "-A", USER_AGENT, url], check=True, capture_output=True, text=True, timeout=600)
    return cp.stdout


def default_fetch(url: str, dest: Path) -> None:
    """Download one NCEI file to `dest` with curl -4; raises on any failure (the caller checks the size)."""
    try:
        subprocess.run([CURL, "-4", "-fsS", "--retry", "3", "--connect-timeout", "30", "-A", USER_AGENT,
                        "-o", str(dest), url], check=True, capture_output=True, text=True,
                       timeout=DOWNLOAD_TIMEOUT_S)
    except subprocess.CalledProcessError as e:
        raise OSError(f"curl exit {e.returncode}: {(e.stderr or '').strip()[-200:]}") from None


async def discover_and_mark(conn, *, get_text=None, head_fn=None) -> dict:
    """List the tree, HEAD every file, upsert `wod_files`. A file turns `pending` when it is new or its
    (length, Last-Modified) differs from what was loaded; a vanished file becomes `missing` (rows kept) and only
    when its year directory listed successfully; a `missing` file that returns unchanged goes back to `loaded` (P12).
    A failed HEAD or listing leaves the affected rows unchanged and is reported."""
    get_text = get_text or _get_text
    head_fn = head_fn or head
    base = R.BASE_URL.rstrip("/")
    root = await asyncio.to_thread(get_text, base + "/")           # a failure here marks nothing
    years = parse_year_dirs(root)
    if not years:
        raise ValueError("the root listing holds no year directory")
    sem = asyncio.Semaphore(4)

    async def listing(y):
        async with sem:
            return await asyncio.to_thread(get_text, f"{base}/{y}/")
    pages = await asyncio.gather(*(listing(y) for y in years), return_exceptions=True)
    listed: dict[str, tuple[str, int]] = {}                       # url -> (instrument, year)
    ok_years: set[int] = set()
    years_failed: list[int] = []
    for y, page in zip(years, pages):
        if isinstance(page, BaseException) and not isinstance(page, Exception):
            raise page
        files = [] if isinstance(page, Exception) else parse_year_files(page)
        if not files:                                             # an error page is not an empty year
            years_failed.append(y)
            continue
        ok_years.add(y)
        for name, inst, fy in files:
            listed[f"{base}/{y}/{name}"] = (inst, fy)

    async def one_head(url):
        async with sem:
            return await asyncio.to_thread(head_fn, url)
    urls = sorted(listed)
    heads = await asyncio.gather(*(one_head(u) for u in urls), return_exceptions=True)
    got: dict[str, dict] = {}
    heads_failed: list[str] = []
    for u, h in zip(urls, heads):
        if isinstance(h, BaseException) and not isinstance(h, Exception):
            raise h
        if isinstance(h, Exception) or not h.get("content_length"):
            heads_failed.append(u)
        else:
            got[u] = h

    existing = {r["url"]: r for r in await conn.fetch("SELECT * FROM wod_files")}
    new = changed = missing = reappeared = 0
    async with conn.transaction():
        for u, h in got.items():
            inst, fy = listed[u]
            remote = (h["content_length"], h.get("last_modified"))
            row = existing.get(u)
            if row is None:
                await conn.execute(
                    "INSERT INTO wod_files (url, instrument, year, content_length, last_modified, seen_at, status) "
                    "VALUES ($1, $2, $3, $4, $5, now(), 'pending')", u, inst, fy, *remote)
                new += 1
                continue
            status = row["status"]
            loaded = (row["loaded_content_length"], row["loaded_last_modified"])
            if status == "missing":
                reappeared += 1
                status = "loaded" if (row["loaded_at"] is not None and remote == loaded) else "pending"
            elif status == "loaded" and remote != loaded:
                status = "pending"
                changed += 1
            elif status == "blocked" and remote != (row["content_length"], row["last_modified"]):
                status = "pending"                                # republished again since it was blocked
                changed += 1
            await conn.execute("UPDATE wod_files SET content_length = $2, last_modified = $3, seen_at = now(), "
                               "status = $4 WHERE file_id = $1", row["file_id"], *remote, status)
        for u, row in existing.items():
            if u not in listed and row["year"] in ok_years and row["status"] != "missing":
                await conn.execute("UPDATE wod_files SET status = 'missing' WHERE file_id = $1", row["file_id"])
                missing += 1
        await conn.execute("UPDATE wod_casts_source SET last_checked_at = now() WHERE id = 1")
    return {"new": new, "changed": changed, "missing": missing, "reappeared": reappeared,
            "listed": len(listed), "heads_failed": heads_failed, "years_failed": years_failed}


# ── disk ─────────────────────────────────────────────────────────────────────────────────────────────────

def _disk_usage(path) -> tuple[int, int, int]:
    """(total, used, free) bytes of the filesystem holding `path`."""
    u = shutil.disk_usage(path)
    return u.total, u.used, u.free


def _db_path() -> str:
    return DISK_PATH if os.path.exists(DISK_PATH) else "/"


def _db_fraction() -> float:
    total, used, _ = _disk_usage(_db_path())
    return used / total


async def _lod_reserve(conn) -> int:
    live = await conn.fetchval("SELECT coalesce(pg_total_relation_size(to_regclass('wod_cells')), 0)")
    return max(LOD_CELLS_ESTIMATE, int(live))


async def _preflight_file(conn, f, dl: Path) -> str | None:
    """Reason to refuse the file (nothing touched), or None. `/` holds the database and the unlogged staging:
    staging + the swap insert (each STAGE_FRACTION x file), the LOD build spill (2 x the wod_cells estimate, P27)
    and the WAL allowance must stay under DISK_STOP_PROJECTED. The download filesystem needs file + 1 GiB free."""
    cl = int(f["content_length"] or 0)
    total, used, _ = _disk_usage(_db_path())
    projected = used + 2 * int(STAGE_FRACTION * cl) + 2 * await _lod_reserve(conn) + R.WAL_ALLOWANCE_BYTES
    if os.stat(_db_path()).st_dev == os.stat(dl).st_dev:          # one filesystem for both: the download counts too
        projected += cl
    if projected > R.DISK_STOP_PROJECTED * total:
        return (f"disk: refusing {f['url']}, projected {100.0 * projected / total:.1f} % > "
                f"{100 * R.DISK_STOP_PROJECTED:.0f} % of the database filesystem")
    _, _, dfree = _disk_usage(dl)
    if dfree < cl + DOWNLOAD_HEADROOM:
        return f"disk: refusing {f['url']}, download filesystem has {dfree >> 20} MiB free for {cl >> 20} MiB + 1 GiB"
    return None


async def _preflight_lod(conn) -> str | None:
    total, used, _ = _disk_usage(_db_path())
    est = await _lod_reserve(conn)
    projected = used + est + 2 * est + R.WAL_ALLOWANCE_BYTES      # the new table + the build spill
    if projected > R.DISK_STOP_PROJECTED * total:
        return f"disk: refusing the LOD rebuild, projected {100.0 * projected / total:.1f} % > " \
               f"{100 * R.DISK_STOP_PROJECTED:.0f} %"
    return None


# ── parser stream ────────────────────────────────────────────────────────────────────────────────────────

_END = object()


async def cast_stream(path, instrument: str, stats):
    """`P.iter_casts` in ONE thread; lists of CHUNK_CASTS casts cross an `asyncio.Queue(maxsize=2)` (the producer
    blocks while it is full), so memory holds a few chunks. Yields casts one by one; a producer exception is
    re-raised here. Close it with `contextlib.aclosing` so an abandoned stream stops the thread."""
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue(maxsize=2)
    stop = threading.Event()

    def put(item) -> None:
        asyncio.run_coroutine_threadsafe(q.put(item), loop).result()

    def produce() -> None:
        try:
            chunk: list = []
            for cast in P.iter_casts(path, instrument, stats):
                if stop.is_set():
                    return
                chunk.append(cast)
                if len(chunk) >= R.CHUNK_CASTS:
                    put(chunk)
                    chunk = []
            if chunk:
                put(chunk)
            put(_END)
        except BaseException as e:                                # noqa: BLE001 - handed to the consumer
            if not stop.is_set():
                with contextlib.suppress(Exception):
                    put(e)

    prod = asyncio.ensure_future(asyncio.to_thread(produce))
    try:
        while True:
            item = await q.get()
            if item is _END:
                break
            if isinstance(item, BaseException):
                raise item
            for cast in item:
                yield cast
    finally:
        stop.set()
        while not prod.done():                                    # free a producer blocked on a full queue
            while not q.empty():
                q.get_nowait()
            await asyncio.sleep(0.05)
        await prod


def _cast_record(c: P.Cast, file_id: int) -> tuple:
    return (c.cast_id, file_id, c.instrument, c.dataset, c.lat, c.lon, c.cast_date, c.cast_time, c.time_precision,
            c.year, *(c.meta[k] for k in P.META_FIELDS), c.access_no, c.depth, c.depth_flag,
            *(c.values[v[0]] for v in R.VARS), *(c.flags[v[0]] for v in R.VARS), c.pflag, c.n_src, c.n_good)


def _tag_count(tag: str) -> int:
    return int(tag.split()[-1])


def _merge_flags(current: dict, info: dict[str, dict[int, str]]) -> dict:
    out = {k: dict(v) for k, v in current.items()}
    for var, meanings in info.items():
        out.setdefault(var, {}).update({str(k): v for k, v in meanings.items()})
    return out


async def _ensure_staging(conn) -> None:
    for sql in staging_ddl():
        await conn.execute(sql)


async def _truncate_staging(conn) -> None:
    await conn.execute("TRUNCATE wod_casts_stage, wod_points_stage")


async def _with_lock_retries(fn):
    """Run fn() (one transaction); a lock_timeout is retried after each LOCK_BACKOFF pause, then propagates."""
    for attempt in range(len(LOCK_BACKOFF) + 1):
        try:
            return await fn()
        except asyncpg.exceptions.LockNotAvailableError:
            if attempt == len(LOCK_BACKOFF):
                raise
            await asyncio.sleep(LOCK_BACKOFF[attempt])
    raise AssertionError("unreachable")


# ── one file ─────────────────────────────────────────────────────────────────────────────────────────────

_INSERT_CASTS = (f"INSERT INTO wod_casts ({', '.join(CAST_COLUMNS)}) SELECT {', '.join(CAST_COLUMNS)} "
                 "FROM wod_casts_stage ON CONFLICT (cast_id) DO NOTHING")
_INSERT_POINTS = (f"INSERT INTO wod_cast_points ({', '.join(POINT_COLUMNS)}) "
                  f"SELECT {', '.join('p.' + c for c in POINT_COLUMNS)} FROM wod_points_stage p "
                  "JOIN wod_casts c ON c.cast_id = p.cast_id AND c.file_id = p.file_id")


async def load_file(conn, f, path: Path) -> dict:
    """Stage one downloaded file and replace that file's rows in ONE transaction. Raises SchemaError (nothing
    staged), DiskStop, asyncpg LockNotAvailableError (after the back-off) or any DB error; the caller cleans up."""
    stats: collections.Counter = collections.Counter()
    fid = f["file_id"]
    info = await asyncio.to_thread(P.read_file_info, path, f["instrument"])    # SchemaError before anything is staged
    await _ensure_staging(conn)
    await _truncate_staging(conn)
    batch_c: list = []
    batch_p: list = []
    seen: set[int] = set()
    dup_in_file = 0

    async def flush() -> None:
        await conn.copy_records_to_table("wod_casts_stage", records=batch_c, columns=CAST_COLUMNS)
        await conn.copy_records_to_table("wod_points_stage", records=batch_p, columns=POINT_COLUMNS)
        batch_c.clear()
        batch_p.clear()
        frac = _db_fraction()
        if frac >= R.DISK_STOP_ACTUAL:
            raise DiskStop(f"disk at {100 * frac:.1f} % >= {100 * R.DISK_STOP_ACTUAL:.0f} % during {f['url']}")
        if SLICE_PAUSE_S:
            await asyncio.sleep(SLICE_PAUSE_S)

    async with contextlib.aclosing(cast_stream(path, f["instrument"], stats)) as stream:
        async for c in stream:
            if c.cast_id in seen:                                 # a repeat inside this file: the first one wins
                dup_in_file += 1
                continue
            seen.add(c.cast_id)
            batch_c.append(_cast_record(c, fid))
            if c.n_good > 0 and c.year is not None:
                batch_p.append((c.cast_id, fid, c.year, c.key, c.x, c.y, c.picks))
            if len(batch_c) >= R.CHUNK_CASTS:
                await flush()
    if batch_c:
        await flush()
    seen.clear()

    staged = await conn.fetchval("SELECT count(*) FROM wod_casts_stage")
    would = await conn.fetchval(                                  # P33: distinct casts this file would really store
        "SELECT count(*) FROM wod_casts_stage s WHERE NOT EXISTS "
        "(SELECT 1 FROM wod_casts c WHERE c.cast_id = s.cast_id AND c.file_id <> $1)", fid)
    prev = f["n_stored"]
    if prev and would < (1 - R.DROP_BLOCK_FRACTION) * prev:       # prev 0/None (first load, all-duplicate file): never
        await conn.execute("UPDATE wod_files SET status = 'blocked', failure = $2, failed_at = now() "
                           "WHERE file_id = $1", fid, f"stored casts would drop {prev} -> {would}")
        await _truncate_staging(conn)
        return {"outcome": "blocked", "staged": would, "previous": prev}

    async def swap() -> dict:
        async with conn.transaction():                            # the per-file atomic swap
            await conn.execute("SET LOCAL lock_timeout = '3s'")
            await conn.execute("SET LOCAL statement_timeout = 0")
            await conn.execute("DELETE FROM wod_cast_points WHERE file_id = $1", fid)
            await conn.execute("DELETE FROM wod_casts WHERE file_id = $1", fid)
            inserted = _tag_count(await conn.execute(_INSERT_CASTS))
            if inserted != would:
                raise SwapMismatch(f"inserted {inserted} casts, expected {would}")
            drawn = _tag_count(await conn.execute(_INSERT_POINTS))
            no_good, no_date = await conn.fetchrow(
                "SELECT count(*) FILTER (WHERE n_good = 0), "
                "count(*) FILTER (WHERE n_good > 0 AND year IS NULL) FROM wod_casts WHERE file_id = $1", fid)
            if drawn != inserted - no_good - no_date:
                raise SwapMismatch(f"drawn {drawn} != stored {inserted} - no_good {no_good} - no_date {no_date}")
            st = dict(stats)
            st["duplicate_cast_id"] = dup_in_file + (staged - inserted)
            st["no_good"], st["no_date"] = no_good, no_date       # of the STORED casts only
            st["stored"] = inserted
            ident = sum(st.get(k, 0) for k in ("no_depth_levels", "no_values", "bad_coords", "duplicate_cast_id",
                                               "stored"))
            if ident != st.get("source", 0):
                raise SwapMismatch(f"source {st.get('source', 0)} != reject terms + stored {ident}")
            cur = await conn.fetchval("SELECT flag_meanings FROM wod_casts_source WHERE id = 1 FOR UPDATE")
            merged = _merge_flags(json.loads(cur) if cur else {}, info.flag_meanings)
            tag = await conn.execute("UPDATE wod_casts_source SET flag_meanings = $1::jsonb WHERE id = 1",
                                     json.dumps(merged, allow_nan=False))
            if _tag_count(tag) != 1:
                raise SwapMismatch("wod_casts_source row is missing")
            await conn.execute(
                """UPDATE wod_files SET status = 'loaded', loaded_content_length = $2, loaded_last_modified = $3,
                     loaded_at = clock_timestamp(), n_casts_source = $4, n_stored = $5, n_drawn = $6,
                     rejects = $7::jsonb, failure = NULL, failed_at = NULL WHERE file_id = $1""",
                fid, f["content_length"], f["last_modified"], st.get("source", 0), inserted, drawn,
                json.dumps(st, allow_nan=False))
            return {"stored": inserted, "drawn": drawn, "rejects": st}

    res = await _with_lock_retries(swap)
    await _truncate_staging(conn)
    return {"outcome": "loaded", **res}


# ── LOD rebuild ──────────────────────────────────────────────────────────────────────────────────────────

def _sum_arrays(src: str, n: int, from_cells: bool) -> str:
    if from_cells:
        s = ", ".join(f"sum({src}.s[{i}]::float8)::real" for i in range(1, n + 1))
        c = ", ".join(f"sum({src}.c[{i}])::int" for i in range(1, n + 1))
    else:
        s = ", ".join(f"sum({src}.picks[{i}])::real" for i in range(1, n + 1))
        c = ", ".join(f"nullif(count({src}.picks[{i}]), 0)::int" for i in range(1, n + 1))
    return f"ARRAY[{s}]::real[] AS s, ARRAY[{c}]::int[] AS c"


def lod_build_sql() -> list[str]:
    """Finest level from the narrow table, every coarser level from the next finer one. Levels come from R."""
    top = R.LOD_LEVELS[-1]
    out = [f"""INSERT INTO wod_cells_new (level, cell, year, n, rep, sx, sy, s, c)
      SELECT {top}, (p.key >> {2 * (R.GRID_BITS - R.level_bits(top))})::int, p.year, count(*)::int, max(p.cast_id),
             sum(p.x::float8), sum(p.y::float8), {_sum_arrays('p', R.N_PICKS, False)}
      FROM wod_cast_points p GROUP BY 2, 3"""]
    for lv in reversed(R.LOD_LEVELS[:-1]):
        out.append(f"""INSERT INTO wod_cells_new (level, cell, year, n, rep, sx, sy, s, c)
          SELECT {lv}, (w.cell >> 4)::int, w.year, sum(w.n)::int, max(w.rep), sum(w.sx), sum(w.sy),
                 {_sum_arrays('w', R.N_PICKS, True)}
          FROM wod_cells_new w WHERE w.level = {lv + 1} GROUP BY 2, 3""")
    return out


def _sum_rejects(rows) -> dict:
    out: dict[str, int] = collections.Counter()
    for r in rows:
        if r["rejects"]:
            for k, v in json.loads(r["rejects"]).items():
                out[k] += int(v)
    return dict(out)


async def rebuild_lod(conn) -> dict:
    """Build `wod_cells_new` (one transaction: a failure leaves nothing behind), validate every level against the
    casts, then swap it in with the tile version, in ONE transaction (4 attempts; the live table stays on failure)."""
    async with conn.transaction():
        await conn.execute("SET LOCAL statement_timeout = 0")
        await conn.execute("SET LOCAL maintenance_work_mem = '256MB'")
        await conn.execute("DROP TABLE IF EXISTS wod_cells_new")
        for sql in cells_ddl("wod_cells_new"):
            await conn.execute(sql)
        for sql in lod_build_sql():
            await conn.execute(sql)
        n_points = await conn.fetchval("SELECT count(*) FROM wod_cast_points")
        per_level = {r["level"]: r["n"] for r in await conn.fetch(
            "SELECT level, coalesce(sum(n), 0)::bigint AS n FROM wod_cells_new GROUP BY level")}
        for lv in R.LOD_LEVELS:
            if per_level.get(lv, 0) != n_points:
                raise LodMismatch(f"LOD level {lv} represents {per_level.get(lv, 0)} casts, the table holds {n_points}")
        if set(per_level) - set(R.LOD_LEVELS):
            raise LodMismatch(f"unexpected LOD levels {sorted(set(per_level) - set(R.LOD_LEVELS))}")
        await conn.execute("ANALYZE wod_cells_new")
    lod_counts = {str(r["level"]): r["n"] for r in await conn.fetch(
        "SELECT level, count(*) AS n FROM wod_cells_new GROUP BY level ORDER BY level")}
    n_stored = await conn.fetchval("SELECT count(*) FROM wod_casts")
    years = await conn.fetchrow("SELECT min(year) AS a, max(year) AS b FROM wod_cast_points")
    rejects = _sum_rejects(await conn.fetch("SELECT rejects FROM wod_files WHERE status = 'loaded'"))

    async def swap() -> str:
        async with conn.transaction():
            await conn.execute("SET LOCAL lock_timeout = '3s'")
            await conn.execute("LOCK TABLE wod_cells IN ACCESS EXCLUSIVE MODE")
            await conn.execute("DROP TABLE wod_cells")
            await conn.execute("ALTER TABLE wod_cells_new RENAME TO wod_cells")
            for old, new in zip(cells_index_names("wod_cells_new"), cells_index_names("wod_cells")):
                await conn.execute(f'ALTER INDEX "{old}" RENAME TO "{new}"')
            return await conn.fetchval(
                """UPDATE wod_casts_source SET
                     tile_version = to_char(clock_timestamp() AT TIME ZONE 'UTC', 'YYYYMMDDHH24MISS') || '-' ||
                       coalesce((SELECT left(md5(string_agg(url || ':' || coalesce(loaded_last_modified, '') || ':' ||
                                 coalesce(loaded_content_length::text, ''), ',' ORDER BY file_id)), 6)
                                 FROM wod_files WHERE status = 'loaded'), '000000'),
                     tile_built_at = clock_timestamp(), loaded_at = clock_timestamp(), point_min_zoom = $1,
                     n_stored = $2, n_drawn = $3, year_min = $4, year_max = $5, lod_counts = $6::jsonb,
                     last_rejects = $7::jsonb, last_rejects_at = clock_timestamp()
                   WHERE id = 1 RETURNING tile_version""",
                R.POINT_MIN_ZOOM, n_stored, n_points, years["a"], years["b"],
                json.dumps(lod_counts, allow_nan=False), json.dumps(rejects, allow_nan=False))

    try:
        version = await _with_lock_retries(swap)
    except BaseException:
        with contextlib.suppress(Exception):
            await conn.execute("DROP TABLE IF EXISTS wod_cells_new")   # the live table is intact; free the space
        raise
    if version is None:
        raise LodMismatch("wod_casts_source row is missing")
    return {"version": version, "lod_counts": lod_counts}


# ── the import ───────────────────────────────────────────────────────────────────────────────────────────

_PENDING_SQL = """SELECT file_id, url, instrument, year, content_length, last_modified, n_stored FROM wod_files
    WHERE status = 'pending' OR (status = 'failed' AND (failed_at IS NULL OR failed_at < now() - interval '1 day'))
    ORDER BY content_length DESC NULLS LAST, file_id"""

_LOD_DUE_SQL = """SELECT (SELECT count(*) FROM wod_files WHERE status = 'loaded') > 0
    AND NOT EXISTS (SELECT 1 FROM wod_files WHERE status = 'pending'
                    OR (status = 'failed' AND (failed_at IS NULL OR failed_at < now() - interval '1 day')))
    AND (s.tile_built_at IS NULL OR (SELECT max(loaded_at) FROM wod_files) > s.tile_built_at)
    FROM wod_casts_source s WHERE s.id = 1"""


async def _mark_failed(conn, f, kind: str, msg: str) -> dict:
    """P34: the file goes to `failed` (the status CHECK has no 'error') with the message; the run goes on."""
    text = f"{kind}: {msg}"[:500]
    await conn.execute("UPDATE wod_files SET status = 'failed', failure = $2, failed_at = now() WHERE file_id = $1",
                       f["file_id"], text)
    log.warning("wod-casts: %s: %s", f["url"], text)
    return {"url": f["url"], "outcome": "schema" if kind == "schema" else "failed", "reason": text}


async def _process_file(conn, f, fetch, dl: Path) -> dict:
    name = f["url"].rsplit("/", 1)[-1]
    path, part = dl / name, dl / (name + ".part")
    try:
        part.unlink(missing_ok=True)
        path.unlink(missing_ok=True)
        try:
            await asyncio.to_thread(fetch, f["url"], part)
            size = part.stat().st_size
        except Exception as e:
            return await _mark_failed(conn, f, "download", f"{type(e).__name__}: {e}")
        if size != f["content_length"]:
            return await _mark_failed(conn, f, "download", f"size {size} != HEAD content-length {f['content_length']}")
        part.replace(path)
        try:
            res = await load_file(conn, f, path)
        except P.SchemaError as e:
            await _truncate_quietly(conn)
            return await _mark_failed(conn, f, "schema", str(e))
        except DiskStop as e:
            await _truncate_quietly(conn)
            return {"url": f["url"], "outcome": "disk", "reason": f"disk: {e}"}
        except asyncpg.exceptions.LockNotAvailableError as e:
            await _truncate_quietly(conn)
            return {"url": f["url"], "outcome": "lock_timeout", "reason": f"lock_timeout: swap of {f['url']}: {e}"}
        except Exception as e:
            log.exception("wod-casts: load failed for %s", f["url"])
            await _truncate_quietly(conn)
            return await _mark_failed(conn, f, "error", f"{type(e).__name__}: {e}")
        return {"url": f["url"], **res}
    finally:
        part.unlink(missing_ok=True)
        path.unlink(missing_ok=True)


async def _truncate_quietly(conn) -> None:
    try:
        await _truncate_staging(conn)
    except Exception:
        log.exception("wod-casts: could not truncate the staging")


def _result(outcome: str, files: list, version, reasons: list) -> dict:
    return {"outcome": outcome, "files": files, "version": version, "reasons": list(reasons)}


async def _record(res: dict, added: int) -> None:
    """sync_log for every exit; never raises. complete/partial refresh the freshness stamp, the rest are skips."""
    try:
        if res["outcome"] in ("complete", "partial"):
            async with db.pool.acquire() as conn:
                total = await conn.fetchval("SELECT count(*) FROM wod_casts")
            await _log_sync(SOURCE, added, total)
        else:
            reason = f"{res['outcome']}: " + "; ".join(res["reasons"])
            await log_sync_skipped(SOURCE, reason[:500])
    except Exception:
        log.exception("wod-casts: could not write the outcome")


async def sync_wod_casts(*, budget_s: float = R.RUN_BUDGET_S, fetch=None, scratch=None) -> dict:
    """Load every pending file (largest first) within `budget_s`, then rebuild the LOD when nothing is left.
    -> {"outcome": complete|partial|disk|blocked|error|schema|lock_timeout, "files": [...], "version", "reasons"}.
    Never raises; every exit writes sync_log."""
    files: list[dict] = []
    reasons: list[str] = []
    try:
        res = await _sync(budget_s, fetch or default_fetch, Path(scratch or R.DOWNLOAD_DIR), files, reasons)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.exception("wod-casts: unexpected failure")
        res = _result("error", files, None, reasons + [f"{type(e).__name__}: {e}"])
    await _record(res, sum(x.get("stored", 0) for x in files if x.get("outcome") == "loaded"))
    return res


async def _sync(budget_s, fetch, dl: Path, files: list, reasons: list) -> dict:
    t0 = time.monotonic()
    try:
        dl.mkdir(exist_ok=True)                                   # no parents: an unmounted volume must stop the run
    except OSError as e:
        return _result("error", files, None, [f"download directory {dl}: {e}"])
    for stale in list(dl.glob("*.part")) + list(dl.glob("wod_*_*.nc")):
        stale.unlink(missing_ok=True)                             # leftovers of a killed run (the worker holds the lock)
    partial = False
    streak = 0
    async with db.pool.acquire() as conn:
        for f in await conn.fetch(_PENDING_SQL):
            if time.monotonic() - t0 >= budget_s:
                partial = True
                break
            if streak >= MAX_FAIL_STREAK:
                reasons.append(f"stopped after {streak} consecutive failed files")
                break
            why = await _preflight_file(conn, f, dl)
            if why:
                return _result("disk", files, None, reasons + [why])
            entry = await _process_file(conn, f, fetch, dl)
            files.append(entry)
            kind = entry["outcome"]
            if kind in ("disk", "lock_timeout"):
                return _result(kind, files, None, reasons + [entry["reason"]])
            streak = streak + 1 if kind in ("failed", "schema") else 0
            if kind != "loaded" and entry.get("reason"):
                reasons.append(f"{f['url'].rsplit('/', 1)[-1]}: {entry['reason']}")
            if kind == "blocked":
                reasons.append(f"blocked: {f['url']}: stored casts would drop {entry['previous']} -> {entry['staged']}")

        version = await conn.fetchval("SELECT tile_version FROM wod_casts_source WHERE id = 1")
        if not partial and await conn.fetchval(_LOD_DUE_SQL):
            why = await _preflight_lod(conn)
            if why:
                return _result("disk", files, version, reasons + [why])
            try:
                version = (await rebuild_lod(conn))["version"]
            except asyncpg.exceptions.LockNotAvailableError as e:
                return _result("lock_timeout", files, version, reasons + [f"lock_timeout: LOD swap: {e}"])
            except Exception as e:
                log.exception("wod-casts: LOD rebuild failed")
                return _result("error", files, version, reasons + [f"LOD rebuild failed: {type(e).__name__}: {e}"])

    kinds = {x["outcome"] for x in files}
    if partial:
        outcome = "partial"
    elif "failed" in kinds or streak >= MAX_FAIL_STREAK:
        outcome = "error"
    elif "schema" in kinds:
        outcome = "schema"
    elif "blocked" in kinds:
        outcome = "blocked"
    else:
        outcome = "complete"
    return _result(outcome, files, version, reasons)
