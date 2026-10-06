# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""OBIS plankton rules + per-dataset extraction (DuckDB over the RAW OBIS parquet layout:
interpreted struct, flags VARCHAR[], extensions struct).

Deliberately free of database / schema / alerting imports: the extract runs in a CHILD process
(ingestion/plankton_extract_child.py, one per dataset, so every byte DuckDB and httpfs took goes
back to the OS when it exits), and that child must start in well under a second without pulling
in the `schema` package. plankton_obis re-exports everything here. Rules were measured on the
2026-10-02 coverage audit (docs/superpowers/plans/2026-10-02-plankton-measurements.md).
"""
from __future__ import annotations

import datetime as dt
import re

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


def trim_heap() -> None:
    """Return freed heap pages to the OS (glibc keeps them): without it the extract child creeps up
    by several MB per slice, 1.1 -> 1.4 GB over the 53 slices of the 5 GB iNaturalist file."""
    try:
        import ctypes
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        pass


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
    # ⛔ Measured on the 5.1 GB iNaturalist file (VPS, 2026-10-06): with the external file cache on,
    # the child crept 1.1 -> 1.4 GB over 53 slices and was heading for the 1.5 GB cap; off, RSS
    # stays flat (~95 MB between queries, ~1.13 GB peak while a 90 MB footer is being parsed) at the
    # price of re-reading the footer per query (~57 s/slice instead of ~35 s).
    con.execute("SET enable_external_file_cache=false")
    return con


def plan_slices(con, source: str, slice_bytes: int = SLICE_BYTES) -> list[tuple[int, int]]:
    """Split a file into [start, end) file_row_number windows on row-group boundaries,
    each holding about `slice_bytes` of uncompressed data (a single larger row group
    is its own slice). Peak memory is therefore bounded by the slice, not the file."""
    # ⛔ Do NOT aggregate inside DuckDB (`GROUP BY row_group_id` over parquet_metadata): on a 90 MB
    # footer (622 leaf columns x 1,157 row groups) that one query peaked at 1.6 GB RSS; the plain
    # three-column projection costs ~100 MB. Stream it and fold in Python.
    cur = con.execute(
        f"SELECT row_group_id, row_group_num_rows, total_uncompressed_size FROM parquet_metadata({_lit(source)})")
    groups: dict[int, list[int]] = {}
    while chunk := cur.fetchmany(50_000):
        for gid, n_rows, size in chunk:
            g = groups.setdefault(gid, [n_rows, 0])
            g[1] += size or 0
    rows = [(gid, *groups[gid]) for gid in sorted(groups)]
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
            trim_heap()
        if total == 0:
            return 0
        tmp = dest.with_suffix(".tmp")
        con.execute(f"COPY (SELECT * FROM read_parquet({_lit(parts_dir / '*.parquet')})) "
                    f"TO {_lit(tmp)} (FORMAT PARQUET, COMPRESSION ZSTD)")
        tmp.rename(dest)
        return total
    finally:
        shutil.rmtree(parts_dir, ignore_errors=True)
