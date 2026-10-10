# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""SOCATv2026 observation-point import — runs ONLY in the socat worker (own cgroup), never in abyssal-api,
and nothing here runs on import.

Zip -> parser (socat_points_parse) -> whole cruises batched to >= BATCH_MIN_OBS observations -> ONE transaction
per batch (plain typed arrays COPYed into TEMP staging, then INSERT...SELECT builds the geometry with ST_
functions, C1) into `socat_*_new` -> validate -> indexes + ANALYZE -> swap names in one transaction.

Resumable: every batch commits together with `staging_sha256 / staging_last_expocode / staging_rows` in
`socat_points_source`. A killed or failed run with the same zip (same sha256) skips every line up to and
including the last committed expocode — in FILE order, not string order (the parser's guard is "an expocode
that already ended reappears") — and carries on. The real file takes hours (pure-Python parse alone: 642 s).

`sync_socat_points` never raises, and a failed, blocked or shrunk (> MAX_DROP) refresh leaves the live tables
untouched. Rejected rows (QC E or WOCE != 2) are stored with their flags and counted (C4), not dropped.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import pathlib
import shutil
import subprocess
import time
import urllib.request
import zipfile
from datetime import timedelta

import db
from api_access.notify import notify_telegram
from ingestion import USER_AGENT
from ingestion import socat_points_parse as P
from ingestion import socat_points_rules as R
from schema.socat_points import (
    LOD_LEVELS, cruises_ddl, lod_ddl, lod_index_ddl, segments_ddl, segments_index_ddl,
    staging_autovacuum_off)
from sync_log import log_sync as _log_sync
from sync_log import log_sync_skipped

log = logging.getLogger(__name__)

SOURCE = R.SOURCE
ALERT_TITLE = "Abyssal SOCAT points import"
SCRATCH_DIR = pathlib.Path(os.getenv("SOCAT_SCRATCH_DIR", "/var/cache/abyssal-socat"))
ZIP_NAME = "SOCATv2026_synthesis_file.zip"

BATCH_MIN_OBS = 200_000        # a batch = whole cruises until at least this many observations (tests lower it)
SLICE_PAUSE_S = 1.0            # between batches: lets checkpoints, autovacuum and the site breathe
MAX_DROP = 0.10                # more segments/cruises fewer than live blocks the swap

# Disk stops (percent of the volume holding PostgreSQL). Refuse BEFORE loading when the projection reaches
# DISK_REFUSE_PCT; abort and drop the staging when the actual use reaches DISK_ABORT_PCT after a batch.
DISK_REFUSE_PCT = 80.0
DISK_ABORT_PCT = 82.0
DISK_PATH = os.getenv("SOCAT_DISK_PATH", "/var/lib/postgresql")
WAL_ALLOWANCE = 2 * 1024 ** 3          # max_wal_size is 1 GB (measured); 2 GiB covers checkpoint lag
STAGING_BUDGET = int(2.5 * 1024 ** 3)  # the plan's budget for the three `_new` tables with indexes
MAX_INTERRUPTS = 3                     # resumes of one staging before a repeating failure is called an error

SWAPPED_WITH_REJECTS_PREFIX = R.SWAPPED_WITH_REJECTS_PREFIX     # defined in the rules: the API must not import this module

_STAGE_SEG = "socat_stage_seg"
_STAGE_LOD = "socat_stage_lod"


class DiskStop(Exception):
    pass


class ResumeKeyMissing(Exception):
    """The staging says "last committed cruise X" but this file has no X: the staging belongs to another file."""


# ── download / fingerprint ───────────────────────────────────────────────────────────────────────────────

def _header_blocks(text: str) -> dict:
    """The LAST response's headers from `curl -D` output (redirects leave several blocks)."""
    blocks = [b for b in text.replace("\r\n", "\n").split("\n\n") if b.strip()]
    out: dict[str, str] = {}
    if blocks:
        for line in blocks[-1].split("\n")[1:]:
            k, _, v = line.partition(":")
            out[k.strip().lower()] = v.strip()
    return out


def default_fetch(dest: pathlib.Path) -> dict:
    """Download the NCEI zip with `/usr/bin/curl -4` (the VPS has an IPv6 black hole towards NCEI)."""
    hdr = dest.with_suffix(".headers")
    subprocess.run(
        ["/usr/bin/curl", "-4", "-fsSL", "--retry", "3", "--retry-delay", "10", "-A", USER_AGENT,
         "-D", str(hdr), "-o", str(dest), R.ZIP_URL], check=True, timeout=6 * 3600)
    h = _header_blocks(hdr.read_text(errors="replace"))
    hdr.unlink(missing_ok=True)
    fp = {"etag": h.get("etag"), "content_length": int(h.get("content-length") or 0),
          "last_modified": h.get("last-modified")}
    if fp["content_length"] and dest.stat().st_size != fp["content_length"]:
        raise OSError(f"truncated download: {dest.stat().st_size} of {fp['content_length']} bytes")
    return fp


def head_fingerprint() -> dict:
    """ETag / length / last-modified of the live zip (HEAD, no body) for the worker's change check."""
    req = urllib.request.Request(R.ZIP_URL, method="HEAD", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        return {"etag": r.headers.get("ETag"), "content_length": int(r.headers.get("Content-Length") or 0),
                "last_modified": r.headers.get("Last-Modified")}


def sha256_of(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


# ── disk ─────────────────────────────────────────────────────────────────────────────────────────────────

def _disk_usage() -> tuple[int, int]:
    """(total, used) bytes of the volume that holds the database."""
    path = DISK_PATH if os.path.exists(DISK_PATH) else "/"
    u = shutil.disk_usage(path)
    return u.total, u.used


def _disk_pct() -> float:
    total, used = _disk_usage()
    return 100.0 * used / total


# ── input stream ─────────────────────────────────────────────────────────────────────────────────────────

class _Tsv:
    """The synthesis TSV inside the zip as text; closes the ZipFile too (P.open_member leaves it to the GC)."""

    def __init__(self, zip_path):
        import io
        self.zf = zipfile.ZipFile(zip_path)
        self.text = io.TextIOWrapper(self.zf.open(P.MEMBER), encoding="utf-8", newline="")

    def close(self) -> None:
        try:
            self.text.close()
        finally:
            self.zf.close()


def member_size(zip_path) -> int:
    with zipfile.ZipFile(zip_path) as zf:
        return zf.getinfo(P.MEMBER).file_size


def read_header_info(zip_path) -> tuple[dict, str | None]:
    """(dataset table, "report created" stamp) from the head of the file; reads no data rows."""
    t = _Tsv(zip_path)
    try:
        first = t.text.readline().strip()
    finally:
        t.close()
    created = first.split(":", 1)[1].strip() if first.startswith("SOCAT data report created") else None
    t = _Tsv(zip_path)
    try:
        return P.read_dataset_table(t.text), created
    finally:
        t.close()


def skip_committed(lines, last_expocode):
    """Pass the header through, drop every data line up to and including the block of `last_expocode`
    (file order), pass the rest. Raises ResumeKeyMissing if that block never appears."""
    it = iter(lines)
    for line in it:
        yield line
        if line.startswith("Expocode\t") and "\tyr\t" in line:
            break
    else:
        return
    if last_expocode is None:
        yield from it
        return
    prefix = last_expocode + "\t"
    found = False
    for line in it:
        if line.startswith(prefix):
            found = True
            continue
        if found:
            if line.strip():
                yield line
                yield from it
                return
            continue
    if not found:
        raise ResumeKeyMissing(last_expocode)


def _nan_to_none(arr) -> list:
    return [None if v != v else v for v in arr]


def _seg_record(s: P.Segment) -> tuple:
    dts = [int(round(v)) for v in s.dt_s]
    return (s.expocode, s.qc_flag, s.ord0, len(s.lon), s.t0, s.lon.tolist(), s.lat.tolist(), dts,
            _nan_to_none(s.fco2), _nan_to_none(s.sst), _nan_to_none(s.sal),
            s.fco2_src.tolist(), s.fco2_flag.tolist(),
            (s.t0 + timedelta(seconds=min(dts))).year, (s.t0 + timedelta(seconds=max(dts))).year)


def _lod_record(p: P.LodPiece) -> tuple:
    return (p.level, p.expocode, p.qc_flag, p.n0, p.n_obs, p.year, p.fco2, p.sst, p.sal,
            [v[0] for v in p.vertices], [v[1] for v in p.vertices])


def _cruise_record(c: P.CruiseSummary, meta: P.CruiseMeta | None, qc: str) -> tuple:
    west, east, crosses = c.west, c.east, c.crosses_antimeridian
    if east == -180.0 and west > -180.0:       # Task 1 minor: an east edge of exactly +180 was folded to -180
        east = 180.0
        crosses = False
    m = meta
    return (c.expocode, m.version if m else None, m.dataset_name if m else None, m.platform_name if m else None,
            m.pis if m else None, m.source_doi if m else None, m.source_reference if m else None, qc,
            m.metadata_docs if m else None, c.first_time, c.last_time, c.n_obs, c.n_segments, c.n_rejected,
            west, east, c.south, c.north, crosses)


class Batch:
    __slots__ = ("segs", "lods", "cruises", "n_obs", "last_expocode", "done")

    def __init__(self):
        self.segs: list[tuple] = []
        self.lods: list[tuple] = []
        self.cruises: list[tuple] = []
        self.n_obs = 0
        self.last_expocode: str | None = None
        self.done = False


def take_batch(it, meta: dict, min_obs: int) -> Batch:
    """Pull whole cruises from the parser until >= min_obs observations (blocking: run in a thread)."""
    b = Batch()
    qc_of: dict[str, str] = {}
    while True:
        rec = next(it, None)
        if rec is None:
            b.done = True
            return b
        if isinstance(rec, P.Segment):
            qc_of.setdefault(rec.expocode, rec.qc_flag)       # constant per cruise
            b.segs.append(_seg_record(rec))
        elif isinstance(rec, P.LodPiece):
            qc_of.setdefault(rec.expocode, rec.qc_flag)
            b.lods.append(_lod_record(rec))
        else:                                               # CruiseSummary closes a cruise
            qc = qc_of.pop(rec.expocode, None) or (meta[rec.expocode].qc_flag if rec.expocode in meta else "E")
            b.cruises.append(_cruise_record(rec, meta.get(rec.expocode), qc))
            b.n_obs += rec.n_obs
            b.last_expocode = rec.expocode
            if b.n_obs >= min_obs:
                return b


# ── staging ──────────────────────────────────────────────────────────────────────────────────────────────

SEGS, LOD, CRUISES = "socat_segments", "socat_lod", "socat_cruises"


async def discard_staging(conn) -> None:
    for t in (SEGS, LOD, CRUISES):
        await conn.execute(f"DROP TABLE IF EXISTS {t}_new CASCADE")
    await conn.execute("UPDATE socat_points_source SET staging_sha256 = NULL, staging_last_expocode = NULL, "
                       "staging_rows = NULL, staging_started_at = NULL WHERE id = 1")


async def build_staging(conn, sha: str) -> None:
    """Fresh, empty `_new` trio (a leftover from a killed run is dropped first), autovacuum off."""
    await discard_staging(conn)
    for sql in (segments_ddl(f"{SEGS}_new") + lod_ddl(f"{LOD}_new") + cruises_ddl(f"{CRUISES}_new")):
        await conn.execute(sql)
    for t in (SEGS, LOD, CRUISES):
        await conn.execute(staging_autovacuum_off(f"{t}_new"))
    await conn.execute("UPDATE socat_points_source SET staging_sha256 = $1, staging_last_expocode = NULL, "
                       "staging_rows = 0, staging_started_at = now(), interrupted_expocode = NULL, "
                       "interrupt_count = NULL WHERE id = 1", sha)


async def _staging_state(conn, sha: str) -> tuple[str | None, int] | None:
    """(last committed expocode, rows) if a consistent staging for THIS sha can be resumed, else None."""
    row = await conn.fetchrow("SELECT staging_sha256, staging_last_expocode, staging_rows "
                              "FROM socat_points_source WHERE id = 1")
    if not row or row["staging_sha256"] != sha or row["staging_last_expocode"] is None:
        return None
    present = await conn.fetchval(
        "SELECT count(*) FROM pg_class WHERE relnamespace = current_schema()::regnamespace AND relname = ANY($1)",
        [f"{t}_new" for t in (SEGS, LOD, CRUISES)])
    if present != 3:
        return None
    stored = await conn.fetchval(f"SELECT coalesce(sum(n_obs), 0) FROM {CRUISES}_new")
    if stored != (row["staging_rows"] or 0):          # progress row and data disagree: do not trust either
        return None
    return row["staging_last_expocode"], row["staging_rows"]


_STAGE_DDL = (
    f"""CREATE TEMP TABLE IF NOT EXISTS {_STAGE_SEG} (
        expocode text, qc_flag char(1), ord0 integer, n_obs smallint, t0 timestamptz, lon float8[], lat float8[],
        dt_s integer[], fco2 float8[], sst float8[], sal float8[], fco2_src smallint[], fco2_flag smallint[],
        year_min smallint, year_max smallint)""",
    f"""CREATE TEMP TABLE IF NOT EXISTS {_STAGE_LOD} (
        level smallint, expocode text, qc_flag char(1), n0 integer, n_obs integer, year smallint,
        fco2 float8, sst float8, sal float8, lon float8[], lat float8[])""",
)

_SEG_COLS = ["expocode", "qc_flag", "ord0", "n_obs", "t0", "lon", "lat", "dt_s", "fco2", "sst", "sal",
             "fco2_src", "fco2_flag", "year_min", "year_max"]
_LOD_COLS = ["level", "expocode", "qc_flag", "n0", "n_obs", "year", "fco2", "sst", "sal", "lon", "lat"]
_CRUISE_COLS = ["expocode", "version", "dataset_name", "platform_name", "pis", "source_doi", "source_reference",
                "qc_flag", "metadata_docs", "first_time", "last_time", "n_obs", "n_segments", "n_rejected",
                "west", "east", "south", "north", "crosses_antimeridian"]

_EPS = 5e-7      # degrees; a flat or 1-observation envelope is widened by this much each side (~0.05 m)

_INSERT_SEGS = f"""
INSERT INTO {SEGS}_new (expocode, qc_flag, ord0, n_obs, t0, lon, lat, dt_s, fco2, sst, sal, fco2_src,
                        fco2_flag, year_min, year_max, bbox)
SELECT s.expocode, s.qc_flag, s.ord0, s.n_obs, s.t0, s.lon::real[], s.lat::real[], s.dt_s, s.fco2::real[],
       s.sst::real[], s.sal::real[], s.fco2_src, s.fco2_flag, s.year_min, s.year_max,
       ST_Transform(ST_MakeEnvelope(GREATEST(-180, b.x0 - b.ex), b.y0 - b.ey, LEAST(180, b.x1 + b.ex), b.y1 + b.ey, 4326), 3857)
FROM {_STAGE_SEG} s
CROSS JOIN LATERAL (SELECT min(x) AS x0, max(x) AS x1, min(y) AS y0, max(y) AS y1
                    FROM unnest(s.lon::real[]::float8[], s.lat::real[]::float8[]) AS u(x, y)) m
CROSS JOIN LATERAL (SELECT m.x0, m.x1,
                           GREATEST(-{R.MERC_LAT}, LEAST({R.MERC_LAT}, m.y0)) AS y0,
                           GREATEST(-{R.MERC_LAT}, LEAST({R.MERC_LAT}, m.y1)) AS y1) c
CROSS JOIN LATERAL (SELECT c.x0, c.x1, c.y0, c.y1,
                           CASE WHEN c.x1 - c.x0 < 1e-6 THEN {_EPS} ELSE 0 END AS ex,
                           CASE WHEN c.y1 - c.y0 < 1e-6 THEN {_EPS} ELSE 0 END AS ey) b"""

_INSERT_LOD = f"""
INSERT INTO {LOD}_new (level, expocode, qc_flag, n0, n_obs, year, fco2, sst, sal, geom)
SELECT s.level, s.expocode, s.qc_flag, s.n0, s.n_obs, s.year, s.fco2::real, s.sst::real, s.sal::real,
       ST_Transform(ST_SetSRID(
         CASE WHEN cardinality(s.lon) = 1
              THEN ST_MakePoint(s.lon[1], GREATEST(-{R.MERC_LAT}, LEAST({R.MERC_LAT}, s.lat[1])))
              ELSE ST_MakeLine(ARRAY(
                     SELECT ST_MakePoint(u.x, GREATEST(-{R.MERC_LAT}, LEAST({R.MERC_LAT}, u.y)))
                     FROM unnest(s.lon, s.lat) WITH ORDINALITY AS u(x, y, o) ORDER BY u.o)) END,
         4326), 3857)
FROM {_STAGE_LOD} s"""


async def write_batch(conn, b: Batch, rows_total: int) -> None:
    """One batch = one transaction: staging COPY, geometry INSERT...SELECT, cruises, progress."""
    async with conn.transaction():
        await conn.execute(f"TRUNCATE {_STAGE_SEG}, {_STAGE_LOD}")
        await conn.copy_records_to_table(_STAGE_SEG, records=b.segs, columns=_SEG_COLS)
        await conn.copy_records_to_table(_STAGE_LOD, records=b.lods, columns=_LOD_COLS)
        await conn.execute(_INSERT_SEGS)
        await conn.execute(_INSERT_LOD)
        await conn.copy_records_to_table(f"{CRUISES}_new", records=b.cruises, columns=_CRUISE_COLS)
        await conn.execute(f"TRUNCATE {_STAGE_SEG}, {_STAGE_LOD}")
        await conn.execute("UPDATE socat_points_source SET staging_last_expocode = $1, staging_rows = $2 "
                           "WHERE id = 1", b.last_expocode, rows_total)


async def _after_batch(n_batches: int) -> None:
    """Hook after each committed batch (tests kill a run here)."""


# ── validation ───────────────────────────────────────────────────────────────────────────────────────────

async def validate_staging(conn, parsed_rows: int) -> list[str]:
    """Reasons to block the swap (empty = OK). An empty live table (first run) never blocks on the drop."""
    reasons: list[str] = []
    seg_obs = await conn.fetchval(f"SELECT coalesce(sum(n_obs), 0) FROM {SEGS}_new")
    cr_obs, cr_rej, n_cruises = await conn.fetchrow(
        f"SELECT coalesce(sum(n_obs), 0), coalesce(sum(n_rejected), 0), count(*) FROM {CRUISES}_new")
    n_segs = await conn.fetchval(f"SELECT count(*) FROM {SEGS}_new")
    if parsed_rows == 0 or n_segs == 0:
        reasons.append("staging is empty")
    if not (seg_obs == cr_obs == parsed_rows):
        reasons.append(f"rows disagree: parsed {parsed_rows} / segments {seg_obs} / cruises {cr_obs}")
    drawn = await conn.fetchval(
        f"SELECT coalesce(sum(cardinality(array_positions(fco2_flag, 2::smallint))), 0) FROM {SEGS}_new "
        "WHERE qc_flag IN ('A','B','C','D')")
    if drawn != parsed_rows - cr_rej:
        reasons.append(f"drawn rows {drawn} != parsed {parsed_rows} - rejected {cr_rej}")
    for lv, n in await conn.fetch(
            f"SELECT level, coalesce(sum(n_obs), 0) FROM {LOD}_new WHERE qc_flag IN ('A','B','C','D') "
            "GROUP BY level ORDER BY level"):
        if n != drawn:
            reasons.append(f"LOD level {lv} represents {n} observations, drawn rows are {drawn}")
    levels = await conn.fetchval(f"SELECT count(DISTINCT level) FROM {LOD}_new")
    if drawn and levels != len(LOD_LEVELS):
        reasons.append(f"LOD has {levels} of {len(LOD_LEVELS)} levels")
    distinct = await conn.fetchval(f"SELECT count(DISTINCT expocode) FROM {SEGS}_new")
    if n_cruises != distinct:
        reasons.append(f"{n_cruises} cruise rows vs {distinct} expocodes in segments")
    missing = await conn.fetchval(
        f"""WITH w AS (SELECT DISTINCT expocode FROM {SEGS}_new WHERE 2 = ANY(fco2_flag)),
                 l AS (SELECT DISTINCT expocode, level FROM {LOD}_new)
            SELECT (SELECT count(*) FROM w) * {len(LOD_LEVELS)}
                 - (SELECT count(*) FROM l JOIN w USING (expocode))""")
    if missing:
        reasons.append(f"{missing} (cruise, level) pairs with WOCE-2 rows have no LOD piece")
    # Live counts come from the source row: this loader takes no lock on the live tables before the swap.
    live = await conn.fetchrow("SELECT n_segments, n_cruises FROM socat_points_source WHERE id = 1")
    live_segs, live_cruises = live["n_segments"], live["n_cruises"]
    for what, old, new in (("segments", live_segs, n_segs), ("cruises", live_cruises, n_cruises)):
        if old and new < old * (1 - MAX_DROP):
            reasons.append(f"{what} dropped {old} -> {new} (more than {int(MAX_DROP * 100)} %)")
    return reasons


async def _stats(conn) -> dict:
    qc = {r["qc_flag"]: r["n"] for r in await conn.fetch(
        f"SELECT qc_flag, sum(n_obs)::bigint AS n FROM {CRUISES}_new GROUP BY qc_flag ORDER BY qc_flag")}
    lod = {str(r["level"]): r["n"] for r in await conn.fetch(
        f"SELECT level, count(*) AS n FROM {LOD}_new GROUP BY level ORDER BY level")}
    cr = await conn.fetchrow(f"SELECT count(*) AS n, coalesce(sum(n_obs), 0) AS obs, "
                             f"coalesce(sum(n_rejected), 0) AS rej, coalesce(sum(n_segments), 0) AS segs "
                             f"FROM {CRUISES}_new")
    years = await conn.fetchrow(f"SELECT min(year_min) AS a, max(year_max) AS b FROM {SEGS}_new")
    bad_qc = await conn.fetchval(f"SELECT coalesce(sum(n_obs), 0) FROM {CRUISES}_new WHERE qc_flag NOT IN "
                                 "('A','B','C','D')")
    return {"qc": qc, "lod": lod, "cruises": cr["n"], "obs": cr["obs"], "rejected": cr["rej"],
            "segments": cr["segs"], "year_min": years["a"], "year_max": years["b"], "qc_not_a_d": bad_qc}


# ── swap ─────────────────────────────────────────────────────────────────────────────────────────────────

async def _swap_tx(conn, lock_timeout: str, in_tx) -> None:
    async with conn.transaction():
        # Bounded wait: a queued ACCESS EXCLUSIVE request blocks every new SELECT on the table.
        await conn.execute(f"SET LOCAL lock_timeout = '{lock_timeout}'")
        # ONE statement, one global order (the tile/obs SQL reads the source row, then at most one of these;
        # obs reads segments then cruises), so no reader/swap pair can deadlock.
        await conn.execute(f"LOCK TABLE {SEGS}, {LOD}, {CRUISES} IN ACCESS EXCLUSIVE MODE")
        for t in (SEGS, LOD, CRUISES):
            await conn.execute(f"DROP TABLE IF EXISTS {t}")
            await conn.execute(f"ALTER TABLE {t}_new RENAME TO {t}")
            # Constraints (pkey, CHECKs), indexes and the identity sequence are separate objects that keep
            # their `_new` names; rename them or the next ensure_socat_points builds a second set beside them.
            for (name,) in await conn.fetch(
                    "SELECT conname FROM pg_constraint WHERE conrelid = $1::regclass AND conname LIKE $2",
                    t, f"{t}\\_new%"):
                await conn.execute(f'ALTER TABLE {t} RENAME CONSTRAINT "{name}" TO "{t}{name[len(t) + 4:]}"')
            for (name,) in await conn.fetch(
                    "SELECT indexname FROM pg_indexes WHERE schemaname = current_schema() "
                    "AND tablename = $1 AND indexname LIKE $2", t, f"{t}\\_new%"):
                await conn.execute(f'ALTER INDEX "{name}" RENAME TO "{t}{name[len(t) + 4:]}"')
        seq = await conn.fetchval("SELECT pg_get_serial_sequence($1, 'seg_id')", SEGS)
        if seq and seq.endswith(f"{SEGS}_new_seg_id_seq"):
            await conn.execute(f"ALTER SEQUENCE {seq} RENAME TO {SEGS}_seg_id_seq")
        if in_tx is not None:
            await in_tx(conn)         # the source row: atomic with the swap, or neither


async def swap(conn, lock_timeout: str = "3s", backoff: tuple[float, ...] = (10, 30, 60), *, in_tx=None) -> None:
    """Index + ANALYZE + re-enable autovacuum on the staging tables, then replace the live trio in ONE
    transaction (DDL is transactional: any failure rolls every rename back). Each attempt waits at most
    `lock_timeout` for its locks; after the last failed attempt the LockNotAvailableError propagates, live
    tables untouched. `in_tx(conn)`, if given, runs inside the same transaction after the renames.
    Does not validate."""
    import asyncpg
    await conn.execute("SET maintenance_work_mem = '256MB'")      # server-side memory, outside the worker cgroup
    try:
        for sql in segments_index_ddl(f"{SEGS}_new") + lod_index_ddl(f"{LOD}_new"):
            await conn.execute(sql)
    finally:
        await conn.execute("RESET maintenance_work_mem")
    for t in (SEGS, LOD, CRUISES):
        await conn.execute(f"ANALYZE {t}_new")
        await conn.execute(f"ALTER TABLE {t}_new RESET (autovacuum_enabled)")
    for attempt in range(len(backoff) + 1):
        try:
            await _swap_tx(conn, lock_timeout, in_tx)
            return
        except asyncpg.exceptions.LockNotAvailableError:
            if attempt == len(backoff):
                raise
            await asyncio.sleep(backoff[attempt])


# ── outcome bookkeeping ──────────────────────────────────────────────────────────────────────────────────

async def _outcome(reason: str | None, rows: int = 0, *, alert: bool = True, note: str | None = None) -> None:
    """sync_log + the source row + a Telegram alert on failure paths. Never raises."""
    try:
        if reason is None:
            await _log_sync(SOURCE, rows, rows)
            if note:
                async with db.pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE sync_log SET skipped_reason = $2, skipped_at = NOW() WHERE source = $1",
                        SOURCE, f"{SWAPPED_WITH_REJECTS_PREFIX}: {note}")
        else:
            await log_sync_skipped(SOURCE, reason)
            async with db.pool.acquire() as conn:
                await conn.execute("UPDATE socat_points_source SET last_run_at = now(), last_decision = $1, "
                                   "last_failed_at = now(), last_failure = $2 WHERE id = 1",
                                   reason.split(":", 1)[0][:40], reason[:500])
    except Exception:
        log.exception("socat-points: could not write the outcome")
    if (reason is not None and alert) or note:
        try:
            await notify_telegram(f"socat-points: {reason or 'swapped, but ' + note}", ALERT_TITLE)
        except Exception:
            log.exception("socat-points: telegram notify failed")


def _result(outcome, rows=0, reasons=(), rejected=None) -> dict:
    return {"outcome": outcome, "rows": rows, "reasons": list(reasons), "rejected": rejected or {}}


# ── the import ───────────────────────────────────────────────────────────────────────────────────────────

async def sync_socat_points(*, zip_path=None, expected_sha256=None, fetch=None, scratch=None,
                            count_resume=True) -> dict:
    """One full (or resumed) import. Never raises. -> {"outcome": "swapped"|"blocked"|"lock_timeout"|"error"|
    "schema"|"disk"|"resumable", "rows": int, "reasons": [str], "rejected": {...}}. Every exit is logged.
    `count_resume=False`: the caller (socat_points_worker) already counted this start in
    interrupted_expocode / interrupt_count, so a resume must not count it a second time."""
    scratch_dir = pathlib.Path(scratch or SCRATCH_DIR)
    downloaded = None
    try:
        if zip_path is not None:
            zp = pathlib.Path(zip_path)
            sha = await asyncio.to_thread(sha256_of, zp)
            if expected_sha256 and sha != expected_sha256:
                msg = f"error: zip sha256 {sha[:12]} != expected {expected_sha256[:12]}"
                await _outcome(msg)
                return _result("error", reasons=[msg])
            fp, zip_extra = {}, 0                    # the phase-0 zip is already on disk
        else:
            zp, sha, fp, reused = await _obtain_zip(fetch or default_fetch, scratch_dir)
            downloaded = zp
            zip_extra = 0 if reused else zp.stat().st_size
        res = await _import(zp, sha, fp, zip_extra, count_resume)
        if downloaded is not None and res["outcome"] in ("swapped", "blocked", "schema", "disk"):
            downloaded.unlink(missing_ok=True)       # 1.4 GB we no longer need; kept for a resume otherwise
        return res
    except asyncio.CancelledError:
        raise
    except Exception as e:                        # the contract: never raises
        log.exception("socat-points: unexpected failure")
        await _outcome(f"error: {type(e).__name__}: {e}"[:300])
        return _result("error", reasons=[f"{type(e).__name__}: {e}"])


async def _obtain_zip(fetch, scratch_dir: pathlib.Path):
    scratch_dir.mkdir(parents=True, exist_ok=True)
    dest = scratch_dir / ZIP_NAME
    if dest.exists():                             # a resumable earlier run left it: reuse when it is the staged file
        sha = await asyncio.to_thread(sha256_of, dest)
        async with db.pool.acquire() as conn:
            staged = await conn.fetchval("SELECT staging_sha256 FROM socat_points_source WHERE id = 1")
        if staged == sha:
            return dest, sha, {}, True
        dest.unlink()
    fp = await asyncio.to_thread(fetch, dest)
    return dest, await asyncio.to_thread(sha256_of, dest), fp or {}, False


async def _import(zp: pathlib.Path, sha: str, fp: dict, zip_extra: int = 0, count_resume: bool = True) -> dict:
    try:
        meta, created = await asyncio.to_thread(read_header_info, zp)
    except P.SchemaError as e:
        await _outcome(f"schema: {e}")
        return _result("schema", reasons=[str(e)])
    except Exception as e:                       # BadZipFile on a truncated or HTML download, missing member
        await _outcome(f"error: unreadable zip: {type(e).__name__}: {e}"[:300])
        return _result("error", reasons=[str(e)])

    rows_total = 0
    committed = False
    async with db.pool.acquire() as conn:
        try:
            # The live tables and the source row are created by migrate.py: this loader never runs DDL on them.
            state = await _staging_state(conn, sha)
            if state is None:
                await discard_staging(conn)       # a leftover of ANOTHER file must not count as "used" forever
            existing = int(await conn.fetchval(
                "SELECT coalesce(sum(pg_total_relation_size(c.oid)), 0) FROM pg_class c "
                "WHERE c.relnamespace = current_schema()::regnamespace AND c.relname = ANY($1) AND c.relkind = 'r'",
                [f"{t}_new" for t in (SEGS, LOD, CRUISES)])) if state else 0
            total, used = _disk_usage()
            projected = used + max(0, STAGING_BUDGET - existing) + zip_extra + WAL_ALLOWANCE
            if 100.0 * projected / total >= DISK_REFUSE_PCT:
                msg = (f"disk: refusing, projected {100.0 * projected / total:.1f} % >= {DISK_REFUSE_PCT:.0f} % "
                       f"(used {used >> 20} MiB of {total >> 20} MiB)")
                await _outcome(msg)
                return _result("disk", reasons=[msg])

            if state is None:
                await build_staging(conn, sha)
                last, rows_total = None, 0
            else:
                last, rows_total = state
                if count_resume:
                    await conn.execute("UPDATE socat_points_source SET interrupted_expocode = staging_last_expocode, "
                                       "interrupt_count = COALESCE(interrupt_count, 0) + 1 WHERE id = 1")
                log.info("socat-points: resuming after %s (%d rows already staged)", last, rows_total)
            committed = last is not None

            for sql in _STAGE_DDL:
                await conn.execute(sql)
            tsv = _Tsv(zp)
            try:
                it = P.iter_records(skip_committed(tsv.text, last))
                t_start, n_batches = time.monotonic(), 0
                while True:
                    b = await asyncio.to_thread(take_batch, it, meta, BATCH_MIN_OBS)
                    if b.cruises:
                        rows_total += b.n_obs
                        await write_batch(conn, b, rows_total)
                        committed = True
                        n_batches += 1
                        log.info("socat-points: batch %d to %s, %d rows staged, %.0f s", n_batches,
                                 b.last_expocode, rows_total, time.monotonic() - t_start)
                        await _after_batch(n_batches)
                        pct = _disk_pct()
                        if pct >= DISK_ABORT_PCT:
                            raise DiskStop(f"disk at {pct:.1f} % >= {DISK_ABORT_PCT:.0f} % after batch {n_batches}")
                        if not b.done and SLICE_PAUSE_S:
                            await asyncio.sleep(SLICE_PAUSE_S)
                    if b.done:
                        break
            finally:
                tsv.close()

            reasons = await validate_staging(conn, rows_total)
            if reasons:
                await discard_staging(conn)
                await _outcome("blocked: " + "; ".join(reasons))
                return _result("blocked", rows_total, reasons)
            st = await _stats(conn)
            rejected = {"rows": st["rejected"], "qc_not_a_d_rows": st["qc_not_a_d"]}

            async def record_source(c) -> None:
                await c.execute("""UPDATE socat_points_source SET source_url = $1, etag = $2, content_length = $3,
                    last_modified = $4, sha256 = $5, release = $6, report_created = $7, loaded_at = now(),
                    last_checked_at = now(), refresh_requested_at = NULL, n_rows_source = $8, n_rows_stored = $9,
                    n_rows_rejected = $10, n_cruises = $11, n_datasets_listed = $12, n_segments = $13,
                    lod_counts = $14::jsonb, qc_counts = $15::jsonb, year_min = $16, year_max = $17,
                    tile_version = to_char(now() AT TIME ZONE 'UTC', 'YYYYMMDDHH24MISS') || '-' || left($5, 6),
                    tile_built_at = NULL, last_run_at = now(), last_decision = 'swapped', last_failed_at = NULL,
                    last_failure = NULL, last_rejects = $18::jsonb, last_rejects_at = now(),
                    staging_sha256 = NULL, staging_last_expocode = NULL, staging_rows = NULL,
                    staging_started_at = NULL, interrupted_expocode = NULL, interrupt_count = NULL
                    WHERE id = 1""",
                                R.ZIP_URL, fp.get("etag"), fp.get("content_length"),
                                fp.get("last_modified"), sha, R.RELEASE, created, rows_total, st["obs"],
                                st["rejected"], st["cruises"], len(meta), st["segments"],
                                json.dumps(st["lod"], allow_nan=False), json.dumps(st["qc"], allow_nan=False),
                                st["year_min"], st["year_max"], json.dumps(rejected, allow_nan=False))

            await swap(conn, in_tx=record_source)
        except DiskStop as e:
            await _drop_quietly(conn)
            await _outcome(f"disk: {e}")
            return _result("disk", rows_total, [str(e)])
        except P.SchemaError as e:
            await _drop_quietly(conn)
            await _outcome(f"schema: {e}")
            return _result("schema", rows_total, [str(e)])
        except ResumeKeyMissing as e:
            await _drop_quietly(conn)
            await _outcome(f"error: staging belongs to another file (no cruise {e} here); dropped, run again")
            return _result("error", rows_total, [f"resume key {e} not in file"])
        except Exception as e:
            if type(e).__name__ == "LockNotAvailableError":
                # The load is hours of work: keep the staging. The worker leaves last_failure = 'lock_timeout' (decision
                # 'resume', no back-off, no interrupt count): the next run skips every committed cruise, validates
                # again and retries the swap. A different zip sha discards it and starts over.
                await _outcome("lock_timeout: swap; live tables untouched, staging kept")
                return _result("lock_timeout", rows_total, [str(e)])
            log.exception("socat-points: load failed")
            if committed:
                n_int = await conn.fetchval("SELECT coalesce(interrupt_count, 0) FROM socat_points_source WHERE id = 1")
                if n_int >= MAX_INTERRUPTS:       # the same failure again and again: stop resuming it
                    await _drop_quietly(conn)
                    await _outcome(f"error: failed after {n_int} resumes: {type(e).__name__}: {e}"[:300])
                    return _result("error", rows_total, [f"{type(e).__name__}: {e}"])
                await _outcome(f"resumable: {type(e).__name__}: {e}"[:300])
                return _result("resumable", rows_total, [f"{type(e).__name__}: {e}"])
            await _drop_quietly(conn)
            await _outcome(f"error: load failed: {type(e).__name__}: {e}"[:300])
            return _result("error", rows_total, [f"{type(e).__name__}: {e}"])
        finally:
            try:
                await conn.execute(f"DROP TABLE IF EXISTS {_STAGE_SEG}, {_STAGE_LOD}")
            except Exception:
                log.exception("socat-points: could not drop the batch staging")

    note = f"{rejected['rows']} rows rejected (stored, not drawn)" if rejected["rows"] else None
    if note:
        log.warning("socat-points: %s", note)
    await _outcome(None, rows_total, note=note)
    return _result("swapped", rows_total, [], rejected)


async def _drop_quietly(conn) -> None:
    try:
        await discard_staging(conn)           # disk: a half-built `_new` trio is gigabytes
    except Exception:
        log.exception("socat-points: could not drop staging")
