# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""OBIS plankton occurrences — monthly full rebuild of plankton_occurrences.

Rules, extraction, load/swap and the sync orchestrator live here; the process
wrapper (lock, memory check) is plankton_obis_worker.py. Rules were measured on
the 2026-10-02 coverage audit (docs/superpowers/plans/2026-10-02-plankton-measurements.md).
All SQL below is DuckDB over the RAW OBIS parquet layout (interpreted struct,
flags VARCHAR[], extensions struct).
"""
from __future__ import annotations

import datetime as dt
import re

from schema.plankton import GROUPS, STARTED_PREFIX, STARTED_STALE_HOURS  # noqa: F401  (re-exported)

PLANKTONIC_HARPACTICOID_GENERA: tuple[str, ...] = (
    "Microsetella", "Macrosetella", "Miracia", "Euterpina", "Clytemnestra", "Aegisthus")
EXCLUDED_COPEPOD_ORDERS: tuple[str, ...] = ("Harpacticoida", "Siphonostomatoida", "Monstrilloida")
NON_CALCIFYING_HAPTOPHYTE_ORDERS: tuple[str, ...] = ("Prymnesiales", "Phaeocystales")
# "Continuous Plankton Recorder Dataset (CPR Survey) - Zooplankton" (CC-BY-NC): a 96.3 % duplicate
# of the CC-BY "The CPR Survey" (5c4667b8-...), which we keep.
EXCLUDED_DATASETS: frozenset[str] = frozenset({"10134dbd-457e-4a97-9a89-b4e9f81482ca"})
EXCLUDED_DATASET_GROUPS: frozenset[tuple[str, str]] = frozenset()
# OBIS land flag (upper case; raw `flags` is VARCHAR[]).
LAND_FLAG: str | None = "ON_LAND"
EDNA_TITLE_RE = r"microbiome|metagenom|amplicon|18s|16s|metabarcod|edna|e-dna|sequenc|omics"
_DNA_EXT = 'extensions."http://rs.gbif.org/terms/1.0/DNADerivedData"'


def _sql_list(values) -> str:
    return ", ".join("'" + v.replace("'", "''") + "'" for v in sorted(values)) or "NULL"


_I = "interpreted"
# Copepoda may be ranked as class or subclass; both columns are real raw names.
_COPEPODA = f"({_I}.\"class\" = 'Copepoda' OR {_I}.subclass = 'Copepoda')"

GROUP_SQL = f"""CASE
  WHEN {_COPEPODA} THEN 'copepoda'
  WHEN {_I}."order" = 'Euphausiacea' THEN 'euphausiacea'
  WHEN {_I}.phylum = 'Bacillariophyta' OR {_I}.division = 'Bacillariophyta'
       OR {_I}."class" IN ('Bacillariophyceae','Coscinodiscophyceae','Mediophyceae') THEN 'diatoms'
  WHEN {_I}."class" IN ('Coccolithophyceae','Prymnesiophyceae')
       AND coalesce({_I}."order", '') NOT IN ({_sql_list(NON_CALCIFYING_HAPTOPHYTE_ORDERS)}) THEN 'coccolithophores'
  WHEN {_I}."class" = 'Dinophyceae' OR 'Dinoflagellata' IN (
       {_I}.phylum, {_I}.division, {_I}.subphylum, {_I}.infraphylum) THEN 'dinoflagellates'
END"""

_LAND = (f"AND NOT list_contains(coalesce(flags, []::VARCHAR[]), '{LAND_FLAG}')" if LAND_FLAG else "")
KEEP_SQL = f"""(
  NOT coalesce(absence, false) AND NOT coalesce(dropped, false)
  AND dataset_id NOT IN ({_sql_list(EXCLUDED_DATASETS)})
  AND {_I}.decimalLatitude IS NOT NULL AND {_I}.decimalLongitude IS NOT NULL
  AND {_I}.decimalLatitude BETWEEN -90 AND 90 AND {_I}.decimalLongitude BETWEEN -180 AND 180
  AND NOT ({_I}.decimalLatitude = 0 AND {_I}.decimalLongitude = 0)
  {_LAND}
  AND NOT coalesce({_COPEPODA}
           AND {_I}."order" IN ({_sql_list(EXCLUDED_COPEPOD_ORDERS)})
           AND coalesce({_I}.genus, '') NOT IN ({_sql_list(PLANKTONIC_HARPACTICOID_GENERA)}), false)
)"""

# eDNA = a non-empty DNADerivedData extension list. CPR rows carry an EMPTY list,
# so `IS NOT NULL` would flag 100 % of CPR.
EDNA_SQL = f"(coalesce(len({_DNA_EXT}), 0) > 0)"


def edna_sql(columns, title_expr: str = "''") -> str:
    """EDNA_SQL, or the dataset-title regex fallback when `extensions` is absent."""
    if "extensions" in set(columns):
        return EDNA_SQL
    return f"regexp_matches(lower({title_expr}), '{EDNA_TITLE_RE}')"


_NC_RE = re.compile(r"(?<![a-z])nc(?![a-z])|non-?commercial")
_ND_RE = re.compile(r"(?<![a-z])nd(?![a-z])|no-?deriv")
_RESTRICTED_RE = re.compile(r"^restricted(?![a-z])")


def normalise_licence(text: str | None) -> str:
    """cc0 | cc-by | cc-by-sa | cc-by-nc | unknown | restricted.
    'restricted' is returned so the caller can DROP the dataset; it is never stored.
    Order matters: NC wins over every other class (an NC dataset must never read as open);
    ND has no schema class and a map/export is arguably a derivative -> unknown."""
    t = re.sub(r"[\s_]+", "-", (text or "").strip().lower())
    if not t:
        return "unknown"
    if _RESTRICTED_RE.match(t):
        return "restricted"
    if _NC_RE.search(t):
        return "cc-by-nc"
    if _ND_RE.search(t):
        return "unknown"
    if "cc0" in t or "creative-commons-zero" in t or "publicdomain/zero" in t:
        return "cc0"
    if "by-sa" in t or "sharealike" in t or "share-alike" in t:
        return "cc-by-sa"
    if ("cc-by" in t or "creative-commons-attribution" in t or "licenses/by/" in t
            or "opendatacommons.org/licenses/by" in t or "open-government-licence" in t):
        return "cc-by"
    return "unknown"


def parse_depth(depth, dmin, dmax) -> float | None:
    try:
        if depth is not None:
            d = float(depth)
        elif dmin is not None and dmax is not None:
            d = (float(dmin) + float(dmax)) / 2
        elif dmin is not None or dmax is not None:
            d = float(dmin if dmin is not None else dmax)
        else:
            return None
    except (TypeError, ValueError):
        return None
    return d if 0 <= d <= 11000 else None


def parse_month(value) -> int | None:
    try:
        m = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return m if 1 <= m <= 12 else None


_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ].*)?$")


def parse_event_date(value) -> dt.date | None:
    m = _DATE_RE.match(str(value or "").strip())
    if not m:
        return None
    try:
        return dt.date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Extraction: one OBIS parquet (S3 https URL or local path) -> local parquet of
# plankton-group rows. Filters ONLY on GROUP_SQL; KEEP_SQL is evaluated into the
# `keep` column but never used to drop rows, so the loader can count drops per reason.
# ---------------------------------------------------------------------------
import pathlib  # noqa: E402
import shutil  # noqa: E402

OBIS_HTTP_BASE = "https://obis-open-data.s3.amazonaws.com/occurrence/"
DUCKDB_MEMORY_LIMIT = "700MB"          # worker budget is 2 GB; spec F12 caps DuckDB at <= 750 MB
SLICE_BYTES = 192 * 1024 * 1024        # uncompressed row-group bytes read per slice
# Raw columns the loader needs that a new OBIS dataset might lack: carried as NULL.
_OPTIONAL_COLUMNS = {"absence": "BOOLEAN", "dropped": "BOOLEAN", "flags": "VARCHAR[]"}

_SELECT = f"""
  dataset_id, ({GROUP_SQL}) AS grp, {KEEP_SQL} AS keep,
  {_I}.scientificName AS sciname, {_I}.aphiaid AS aphiaid, {_I}."order" AS ord, {_I}.genus AS genus,
  {_I}.decimalLatitude AS lat, {_I}.decimalLongitude AS lon,
  {_I}.depth AS depth, {_I}.minimumDepthInMeters AS dmin, {_I}.maximumDepthInMeters AS dmax,
  {_I}."month" AS month, {_I}.eventDate AS eventdate, {_I}.basisOfRecord AS basis,
  ({{edna}}) AS edna_struct,
  absence, dropped, flags"""


def _lit(path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


# Fields of the `interpreted` struct that GROUP_SQL / KEEP_SQL / _SELECT read, with the type each is
# read as. Everything except the coordinates (a file without them has nothing to place: it SHOULD
# fail). DuckDB raises on a missing struct key, so a file lacking one is read with that field as a
# typed NULL: the rows still extract, the column is NULL.
_GUARDED_FIELDS = {
    **{f: "VARCHAR" for f in ("class", "subclass", "order", "phylum", "division", "subphylum",
                              "infraphylum", "genus", "scientificName", "basisOfRecord", "eventDate", "month")},
    "aphiaid": "BIGINT", "depth": "DOUBLE", "minimumDepthInMeters": "DOUBLE", "maximumDepthInMeters": "DOUBLE"}
_RANK_FIELDS = tuple(_GUARDED_FIELDS)            # kept for the fallback list when `interpreted` is absent
_RANK_REF = re.compile(r'interpreted\.(?:"(\w+)"|(\w+))')


def _guard_missing_ranks(sql: str, fields) -> str:
    """Replace `interpreted.<field>` by a typed NULL for every guarded field absent from `fields`."""
    have = {f.lower() for f in fields}
    by_lower = {k.lower(): t for k, t in _GUARDED_FIELDS.items()}

    def sub(m):
        name = (m.group(1) or m.group(2)).lower()
        return f"NULL::{by_lower[name]}" if name in by_lower and name not in have else m.group(0)
    return _RANK_REF.sub(sub, sql)


def connect_duckdb(scratch: pathlib.Path):
    import duckdb
    tmp = pathlib.Path(scratch) / "duckdb"
    tmp.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute(f"SET memory_limit='{DUCKDB_MEMORY_LIMIT}'")
    con.execute("SET threads=2")
    con.execute(f"SET temp_directory={_lit(tmp)}")
    con.execute("SET preserve_insertion_order=false")
    con.execute("SET http_timeout=180000")
    con.execute("SET http_retries=6")
    return con


def plan_slices(con, source: str, slice_bytes: int = SLICE_BYTES) -> list[tuple[int, int]]:
    """Split a file into [start, end) file_row_number windows on row-group boundaries,
    each holding about `slice_bytes` of uncompressed data (a single larger row group
    is its own slice). Peak memory is therefore bounded by the slice, not the file."""
    rows = con.execute(
        f"SELECT row_group_id, any_value(row_group_num_rows), sum(total_uncompressed_size) "
        f"FROM parquet_metadata({_lit(source)}) GROUP BY row_group_id ORDER BY row_group_id").fetchall()
    slices: list[tuple[int, int]] = []
    start = pos = acc = 0
    for _, n_rows, size in rows:
        if acc and acc + (size or 0) > slice_bytes:
            slices.append((start, pos))
            start, acc = pos, 0
        pos += n_rows
        acc += size or 0
    if pos > start:
        slices.append((start, pos))
    return slices


def _pass1_hits(con, src: str, a: int, b: int, group_sql: str = GROUP_SQL) -> int:
    """Pass 1: read ONLY the columns GROUP_SQL touches (+ row number) for window [a, b)
    and park the hit row numbers in temp table `hits`. GROUP_SQL is a CASE expression,
    so DuckDB cannot push it into the reader; narrowing the projection is what saves the
    HTTP fetch of every other column chunk."""
    con.execute("DROP TABLE IF EXISTS hits")
    con.execute(
        f"CREATE TEMP TABLE hits AS SELECT file_row_number AS r "
        f"FROM read_parquet({src}, file_row_number=true) "
        f"WHERE file_row_number >= {a} AND file_row_number < {b} AND ({group_sql}) IS NOT NULL")
    return con.execute("SELECT count(*) FROM hits").fetchone()[0]


def _pass2_write(con, src: str, a: int, b: int, extra: str, select: str, part,
                 group_sql: str = GROUP_SQL) -> None:
    """Pass 2: full projection, only for the pass-1 hit rows (same window, so the
    reader can still prune row groups)."""
    con.execute(
        f"COPY (SELECT {select} FROM (SELECT *{extra} FROM read_parquet({src}, file_row_number=true) "
        f"WHERE file_row_number >= {a} AND file_row_number < {b} "
        f"AND file_row_number IN (SELECT r FROM hits)) "
        f"WHERE ({group_sql}) IS NOT NULL) TO {_lit(part)} (FORMAT PARQUET, COMPRESSION ZSTD)")


def extract_dataset(con, source: str, dest: pathlib.Path, *, title: str | None = None,
                    slice_bytes: int = SLICE_BYTES) -> int:
    """Write the plankton-group rows of ONE OBIS file to `dest`; return the row count
    (0 -> nothing written). The file is read slice by slice (see plan_slices) so a 6 GB
    dataset costs no more memory than a small one. Files lacking `extensions` get the
    eDNA flag from the dataset `title` regex; lacking absence/dropped/flags get NULL."""
    dest = pathlib.Path(dest)
    src = _lit(source)
    cols = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet({src})").fetchall()]
    extra = "".join(f", NULL::{t} AS {c}" for c, t in _OPTIONAL_COLUMNS.items() if c not in cols)
    edna = edna_sql(cols, _lit(title or ""))
    try:
        fields = [r[0] for r in con.execute(f"DESCRIBE SELECT interpreted.* FROM read_parquet({src})").fetchall()]
    except Exception:          # no `interpreted` struct at all: leave the SQL alone, the read reports it
        fields = list(_RANK_FIELDS)
    group_sql = _guard_missing_ranks(GROUP_SQL, fields)
    select = _guard_missing_ranks(_SELECT.format(edna=edna), fields)
    parts_dir = dest.parent / (dest.name + ".parts")
    shutil.rmtree(parts_dir, ignore_errors=True)
    parts_dir.mkdir(parents=True)
    try:
        parts, total = [], 0
        for i, (a, b) in enumerate(plan_slices(con, source, slice_bytes)):
            part = parts_dir / f"{i:05d}.parquet"
            if _pass1_hits(con, src, a, b, group_sql) == 0:
                continue  # nothing plankton in this window: pass 2 never runs
            _pass2_write(con, src, a, b, extra, select, part, group_sql)
            n = con.execute(f"SELECT count(*) FROM read_parquet({_lit(part)})").fetchone()[0]
            if n:
                parts.append(part)
                total += n
            else:
                part.unlink(missing_ok=True)
        if total == 0:
            return 0
        tmp = dest.with_suffix(".tmp")
        con.execute(f"COPY (SELECT * FROM read_parquet({_lit(parts_dir / '*.parquet')})) "
                    f"TO {_lit(tmp)} (FORMAT PARQUET, COMPRESSION ZSTD)")
        tmp.rename(dest)
        return total
    finally:
        shutil.rmtree(parts_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Load, validate, swap. The live tables are never written to: everything goes
# into `<table>_new`, and swap() renames them over the live pair in ONE
# transaction. A failed run leaves the live tables exactly as they were.
# ---------------------------------------------------------------------------
import math  # noqa: E402
import uuid  # noqa: E402

from schema.plankton import (  # noqa: E402
    datasets_ddl, occurrences_ddl, occurrences_index_ddl)

OCC, DS = "plankton_occurrences", "plankton_datasets"
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
    for sql in datasets_ddl(f"{DS}_new"):
        await conn.execute(sql)
    for sql in occurrences_ddl(f"{OCC}_new", f"{DS}_new"):
        await conn.execute(sql)


async def discard_staging(conn) -> None:
    await conn.execute(f"DROP TABLE IF EXISTS {OCC}_new")
    await conn.execute(f"DROP TABLE IF EXISTS {DS}_new")


async def load_datasets(conn, datasets: list[dict]) -> None:
    """Licence is normalised here (NULL/empty -> 'unknown'); 'restricted' datasets are not stored."""
    rows = []
    for d in datasets:
        lic = normalise_licence(d.get("licence"))
        if lic == "restricted":
            continue
        rows.append((uuid.UUID(str(d["dataset_id"])), d.get("title"), d.get("institution"), lic,
                     d.get("licence_raw"), d.get("url"), d.get("citation")))
    await conn.executemany(
        f"""INSERT INTO {DS}_new (dataset_id, title, institution, licence, licence_raw, url, citation)
            VALUES ($1, $2, $3, $4, $5, $6, $7)""", rows)


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
    """DuckDB for reading one extract in the load: same cap and on-disk spill as extract_dataset
    (a default connection would take 80 % of RAM inside a 2 GB cgroup)."""
    import duckdb
    tmp = pathlib.Path(path).parent / "duckdb-load"
    tmp.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"SET memory_limit='{DUCKDB_MEMORY_LIMIT}'")
    con.execute("SET threads=2")
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
    lic_cache: dict[str, str] = {}
    db = _load_connection(path)
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


async def _swap_tx(conn, lock_timeout: str) -> None:
    async with conn.transaction():
        # Bounded wait: a queued ACCESS EXCLUSIVE request blocks every new SELECT on the table.
        await conn.execute(f"SET LOCAL lock_timeout = '{lock_timeout}'")
        await conn.execute(f"DROP TABLE IF EXISTS {OCC}")
        await conn.execute(f"DROP TABLE IF EXISTS {DS}")
        await conn.execute(f"ALTER TABLE {DS}_new RENAME TO {DS}")
        await conn.execute(f"ALTER TABLE {OCC}_new RENAME TO {OCC}")
        # Constraints, indexes and the identity sequence are separate objects that keep their
        # `_new` names; rename them to the conventional ones or the next build_staging collides.
        for table in (OCC, DS):
            for (name,) in await conn.fetch(
                    "SELECT conname FROM pg_constraint WHERE conrelid = $1::regclass AND conname LIKE $2",
                    table, f"{table}\\_new%"):
                await conn.execute(f'ALTER TABLE {table} RENAME CONSTRAINT "{name}" TO "{table}{name[len(table) + 4:]}"')
            for (name,) in await conn.fetch(
                    "SELECT indexname FROM pg_indexes WHERE schemaname = current_schema() "
                    "AND tablename = $1 AND indexname LIKE $2", table, f"{table}\\_new%"):
                await conn.execute(f'ALTER INDEX "{name}" RENAME TO "{table}{name[len(table) + 4:]}"')
        seq = await conn.fetchval("SELECT pg_get_serial_sequence($1, 'id')", OCC)
        if seq and seq.endswith(f"{OCC}_new_id_seq"):
            await conn.execute(f"ALTER SEQUENCE {seq} RENAME TO {OCC}_id_seq")


def _forget_meta_cache() -> None:
    """/v1/plankton/meta caches its counts; drop them the moment new data is live. (Only reaches
    this process; the API process also re-keys on sync_log, see domains/plankton.py.)"""
    from response_cache import store
    store.pop("plankton-meta", None)


async def swap(conn, *, lock_timeout: str = SWAP_LOCK_TIMEOUT,
               backoff: tuple[float, ...] = SWAP_BACKOFF_S) -> None:
    """Index, count and ANALYZE the staging pair, then replace the live pair in ONE transaction
    (DDL is transactional: any failure rolls every rename back). Does not validate.
    Each attempt waits at most `lock_timeout` for its locks; after the last failed attempt
    raises SwapLockTimeout, leaving live and `_new` intact."""
    import asyncio
    import asyncpg
    for sql in occurrences_index_ddl(f"{OCC}_new"):
        await conn.execute(sql)
    await conn.execute(
        f"UPDATE {DS}_new d SET record_count = c.n FROM "
        f"(SELECT dataset_id, count(*) n FROM {OCC}_new GROUP BY 1) c WHERE c.dataset_id = d.dataset_id")
    await conn.execute(f"ANALYZE {OCC}_new")
    await conn.execute(f"ANALYZE {DS}_new")
    for attempt in range(len(backoff) + 1):
        try:
            await _swap_tx(conn, lock_timeout)
            _forget_meta_cache()
            return
        except asyncpg.exceptions.LockNotAvailableError as e:
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
    await swap(conn)


# ---------------------------------------------------------------------------
# Orchestrator. One run = select datasets (OBIS API) -> resolve licences -> per dataset
# extract / load / delete the extract -> validate -> swap. Every exit path writes
# sync_log under SOURCE; every failure path (blocked, lock timeout, error) alerts.
# ---------------------------------------------------------------------------
import asyncio  # noqa: E402
import csv  # noqa: E402
import io  # noqa: E402
import json as _json  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
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


async def _import(fetch_json, fetch_licences, source_for, scratch: pathlib.Path) -> dict:
    """Everything up to and including the swap. Raises SwapBlocked / SwapLockTimeout / anything."""
    meta = await select_datasets(fetch_json)
    try:
        lic_rows = parse_licences(await asyncio.to_thread(fetch_licences))
    except Exception as e:      # only a fallback source (intellectualrights comes first): never abort for it
        log.warning("plankton-obis: licenses.tsv unavailable (%s) — using intellectualrights only", type(e).__name__)
        lic_rows = {}
    resolved = {i: resolve_dataset(m, lic_rows.get(i)) for i, m in meta.items()}
    licences = {i: d["licence"] for i, d in resolved.items()}
    con = connect_duckdb(scratch)
    drops = {k: 0 for k in DROP_REASONS}
    failed_ids: list[str] = []
    skipped = attempted = 0
    async with db.pool.acquire() as conn:
        await build_staging(conn)
        await load_datasets(conn, list(resolved.values()))
        for i in meta:                      # ONE dataset at a time: extract -> load -> delete
            if i in EXCLUDED_DATASETS or licences[i] == "restricted":
                skipped += 1                # always dropped: do not even download it
                continue
            attempted += 1
            dest = scratch / f"{i}.parquet"
            phase = "extract"
            try:
                if await asyncio.to_thread(extract_dataset, con, source_for(i), dest,
                                           title=meta[i].get("title")):
                    phase = "load"
                    stats = await load_extract(conn, dest, licences)
                    for k in drops:
                        drops[k] += stats[k]
            except Exception as e:
                # A lost Postgres connection is not a dataset failure: stop now instead of
                # downloading and extracting every remaining dataset for nothing.
                if isinstance(e, _PG_CONNECTION_ERRORS) or conn.is_closed() \
                        or (phase == "load" and isinstance(e, ConnectionError)):
                    raise
                # One bad dataset (S3 404, corrupt parquet, odd schema) must not sink the month's
                # run. Type only: the message can carry the source URL. The >10 % drop check in
                # swap_validated still protects the live table if too much goes missing.
                failed_ids.append(i)
                log.warning("plankton-obis: dataset %s failed (%s) — skipped", i, type(e).__name__)
                try:
                    await conn.execute(f"DELETE FROM {OCC}_new WHERE dataset_id = $1::uuid", i)
                except Exception:
                    log.warning("plankton-obis: could not drop the partial rows of dataset %s", i)
            finally:
                dest.unlink(missing_ok=True)
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
            "skipped_datasets": skipped}


async def sync_plankton_obis(*, fetch_json=None, fetch_licences=None, source_for=None,
                             scratch: pathlib.Path | None = None) -> dict:
    """Monthly full rebuild. Never raises (the worker decides about retries from `outcome`):
    "swapped" | "blocked" (validation, live untouched, staging dropped) |
    "lock_timeout" (live untouched, `_new` staging pair LEFT in place until the next run's
    build_staging drops it) | "error" (live untouched, staging dropped best-effort).
    Seams: fetch_json(url, params) -> dict, fetch_licences() -> tsv text, source_for(id) -> path/URL."""
    fetch_json = fetch_json or _http_json
    fetch_licences = fetch_licences or (lambda: _http_text(LICENCES_URL))
    source_for = source_for or (lambda i: f"{OBIS_HTTP_BASE}{i}.parquet")
    run_dir = pathlib.Path(scratch or SCRATCH_DIR) / "run"
    await _mark_started()
    try:
        shutil.rmtree(run_dir, ignore_errors=True)
        try:
            run_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            log.exception("plankton-obis: scratch directory unusable")
            await _outcome(SCRATCH_REASON, alert=True)
            return {"outcome": "error", "kept": 0, "reasons": [SCRATCH_REASON]}
        res = await _import(fetch_json, fetch_licences, source_for, run_dir)
    except DatasetFailures as e:
        # Staging was never swapped in; the live table is untouched. Full message (count + UUIDs): UUIDs are public ids.
        try:
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
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)
    return res
