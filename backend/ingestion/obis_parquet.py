# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Pull OBIS occurrences from the AWS Open Data parquet bucket.

Replaces the OBIS REST API for `biodiversity.sync_biodiversity_hotspots()`
(domains/biodiversity.py). The REST API was paginated per species and
rate-limited; the parquet bucket exposes the data as columnar files we can
query in bulk.

Filter strategy (refined May 2026): depth >= 50 m floor. Curation happens
at the SPECIES level (14k deep-sea-relevant taxa from our curated list);
the depth floor excludes intertidal/surface records that bloat the table
(~100M rows, 33 GB) without contributing to offshore-claim or deep-sea
monitoring. Continental shelf depths (50–500 m) are preserved for offshore
activity coverage. Quality filters (`dropped`, `absence`) still apply.

Corals (July 2026) are the one exception: selected by taxonomic RANK and at
ANY depth, because reef-building Scleractinia live almost entirely above the
floor and the curated list — being derived from this very table — could never
learn a species the floor had already excluded. See `_CORAL_ORDERS`.

Source: s3://obis-open-data/occurrence/ (CC0/CC-BY/CC-BY-NC; per-dataset
licences in s3://obis-open-data/licenses.tsv). Requester pays = no, AWS
Open Data Sponsorship covers egress.

Strategy (in-place batch download): listing the ~6,880 parquet files via
DuckDB glob is fast, but reading them remotely via httpfs over WAN is too
slow (each metadata fetch is a fresh HTTP round-trip and predicate pushdown
on `scientificName` doesn't help for unsorted columns). Instead we download
batches of N files locally to a tempdir, run DuckDB over the local glob
(disk-speed reads), yield chunks to the caller, and delete the tempdir
before fetching the next batch. OBIS occurrence parquets are large
(~350-400 MB each), so scratch peaks at roughly N x ~380 MB — keep
files_per_batch small (default 12 ~= 4.5 GB) to bound disk. Throughput is
dominated by VPS-to-AWS bandwidth plus local DuckDB CPU.
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
import time
import urllib.request
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

log = logging.getLogger(__name__)

OBIS_PARQUET_GLOB = "s3://obis-open-data/occurrence/*.parquet"
OBIS_HTTP_BASE = "https://obis-open-data.s3.amazonaws.com/occurrence/"

# DuckDB spill + batch scratch MUST be on disk, not the /tmp tmpfs (RAM).
# /tmp is a 7.7 GiB tmpfs on the VPS; spilling there defeats memory_limit and OOMs the box.
OBIS_SCRATCH_DIR = os.getenv("OBIS_SCRATCH_DIR", "/var/cache/abyssal-obis-tmp")

# Corals are selected by taxonomic rank rather than by species name, and are
# exempt from the depth floor the rest of the table uses.
#
# Rank, not name, for two reasons. The curated species list is derived from
# `SELECT DISTINCT scientific_name` on the very table it fills, so a species that
# only ever occurs above 50 m can never enter it — the depth floor filters it out
# before it can be learned. And a rank predicate keeps pace with OBIS on its own:
# newly published coral species arrive without anyone maintaining a list.
#
# Octocorallia appears under both its pre- and post-2022 ordinal names: WoRMS split
# Alcyonacea into Malacalcyonacea + Scleralcyonacea, and OBIS carries records under
# either depending on when the contributor last published.
_CORAL_ORDERS = (
    "Scleractinia",       # stony / reef-building corals
    "Antipatharia",       # black corals
    "Malacalcyonacea",    # soft corals (post-2022 split)
    "Scleralcyonacea",    # gorgonians, sea pens, blue coral (post-2022 split)
    "Alcyonacea",         # pre-2022 octocoral order
    "Pennatulacea",       # pre-2022 sea pens
    "Helioporacea",       # pre-2022 blue coral
    "Zoantharia",         # zoanthids
    "Corallimorpharia",   # coral anemones
)

# Hydrozoan corals are matched by FAMILY, not order. Their order, Anthoathecata,
# is overwhelmingly non-coral hydroids — matching on it would sweep in tens of
# thousands of unrelated records.
_CORAL_FAMILIES = ("Milleporidae", "Stylasteridae")


def _sql_str_list(values: tuple[str, ...]) -> str:
    """Render a literal IN-list. Values are our own constants, never user input."""
    return ", ".join("'" + v.replace("'", "''") + "'" for v in values)


_IS_CORAL = f"""(
            interpreted."order" IN ({_sql_str_list(_CORAL_ORDERS)})
         OR interpreted.family  IN ({_sql_str_list(_CORAL_FAMILIES)})
        )"""

# The `interpreted` struct is OBIS's quality-controlled namespace; `source` is the
# raw provider data. Depth floor 50 m excludes intertidal/surface noise while
# keeping continental shelf (50–500 m offshore claims) and deep-sea records —
# corals excepted, since reef-building Scleractinia live almost entirely above it.
_WHERE_QUALITY = f"""
    dropped  IS NOT TRUE
    AND absence  IS NOT TRUE
    AND interpreted.decimalLatitude  IS NOT NULL
    AND interpreted.decimalLongitude IS NOT NULL
    AND (interpreted.minimumDepthInMeters >= 50 OR {_IS_CORAL})
"""


def _connect():
    """Open a DuckDB connection with httpfs ready for anonymous S3 reads.

    DuckDB's default ``memory_limit`` is ~80% of system RAM (≈12.8 GB on this
    16 GB VPS) — a single parquet scan/semi-join grabbed multi-GB and OOM-killed
    the whole box on 2026-07-14 (see memory ``infra_apiv2_oom_ssh_bind_incident``).
    Cap it hard and let larger-than-memory operations spill to a disk temp dir
    instead of ballooning RSS. This bounds DuckDB well under the obis-sync
    cgroup ``MemoryMax=5G``, so the box can no longer be taken down by this sync.
    """
    import duckdb
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs; SET s3_region='us-east-1';")
    _tmp = os.path.join(OBIS_SCRATCH_DIR, "duckdb-obis")
    os.makedirs(_tmp, exist_ok=True)
    con.execute("SET memory_limit='3GB'")
    con.execute("SET threads=2")
    con.execute(f"SET temp_directory='{_tmp}'")
    con.execute("SET preserve_insertion_order=false")
    return con


def _list_parquet_files(con) -> list[str]:
    """Use DuckDB's glob() to enumerate all parquet files in the bucket."""
    return [
        row[0]
        for row in con.execute(f"SELECT file FROM glob('{OBIS_PARQUET_GLOB}')").fetchall()
    ]


def _s3_to_http(s3_path: str) -> str:
    """Map s3://obis-open-data/occurrence/<uuid>.parquet → https URL."""
    fname = s3_path.rsplit("/", 1)[-1]
    return f"{OBIS_HTTP_BASE}{fname}"


def _download_one(url: str, dest: str, timeout: int = 120) -> str | None:
    """Download a single parquet file to local disk. Returns dest on success."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            with open(dest, "wb") as f:
                shutil.copyfileobj(r, f, length=1024 * 1024)
        return dest
    except Exception as exc:
        log.warning("obis_parquet: download failed %s: %s", url, exc)
        return None


def _download_batch(s3_paths: list[str], target_dir: str, parallel: int = 12) -> list[str]:
    """Download a batch of parquet files in parallel. Returns list of local paths."""
    paths: list[str] = []
    urls = [(_s3_to_http(p), os.path.join(target_dir, p.rsplit("/", 1)[-1])) for p in s3_paths]
    with ThreadPoolExecutor(max_workers=parallel) as pool:
        futures = [pool.submit(_download_one, u, d) for u, d in urls]
        for fut in as_completed(futures):
            result = fut.result()
            if result:
                paths.append(result)
    return paths


def _sweep_stale_batch_dirs(max_age_s: int = 2 * 3600) -> None:
    """Remove orphaned ``obis-batch-*`` scratch dirs from a previously killed run.

    Each batch deletes its own tempdir in a ``finally`` below, but a hard kill
    (SIGKILL after a systemd stop-timeout) skips that cleanup and orphans a
    multi-GB dir. Sweeping leftovers at sync start bounds the leak to at most
    one interrupted batch. Age-gated so a concurrent in-process sync's live
    batch dir (minutes old) is never removed.
    """
    cutoff = time.time() - max_age_s
    seen: set[str] = set()
    for base in (OBIS_SCRATCH_DIR, tempfile.gettempdir(), "/var/tmp", "/tmp"):
        if base in seen:
            continue
        seen.add(base)
        try:
            entries = os.listdir(base)
        except OSError:
            continue
        for name in entries:
            if not name.startswith("obis-batch-"):
                continue
            path = os.path.join(base, name)
            try:
                if os.path.isdir(path) and os.stat(path).st_mtime < cutoff:
                    shutil.rmtree(path, ignore_errors=True)
                    log.warning("obis_parquet: swept stale scratch dir %s", path)
            except OSError:
                pass


def fetch_deep_occurrences_for_species(
    species: list[str],
    chunk_size: int = 5_000,
    files_per_batch: int = 12,
    stats: dict[str, int] | None = None,
) -> Iterator[list[dict[str, Any]]]:
    """Stream OBIS occurrences for the curated species list, plus all corals.

    Two selection paths: the curated species list at depth >= 50 m, and corals at
    any depth matched by taxonomic rank (see `_CORAL_ORDERS` / `_CORAL_FAMILIES`).
    The coral path exists because reef-building Scleractinia live almost entirely
    above the depth floor and so could never enter the curated list.

    Reads parquet files in batches of `files_per_batch` so progress is
    visible and memory bounded. Each batch may yield several chunks of
    `chunk_size` rows.

    Yields chunks of dicts shaped to match `biodiversity_hotspots` columns:
      obis_id, dataset_id, occurrence_id, scientific_name, phylum, class_name,
      order_name, family, depth, lat, lon

    Pass a `stats` dict to learn how much of the catalogue was actually read:
    `files_total` and `files_ok` (files both downloaded AND queried without
    error). **A caller that deletes rows on the strength of this pass MUST
    require `files_ok == files_total`** — batches whose download or query fails
    are skipped with a warning and the generator still completes normally, so
    running to the end proves nothing about coverage on its own.
    """
    if not species:
        return

    # Clean up scratch dirs orphaned by a previously killed run (SIGKILL skips
    # the per-batch finally below). Bounds the /var/tmp leak across runs.
    _sweep_stale_batch_dirs()

    con = _connect()
    con.execute("CREATE TEMP TABLE curated (scientificName VARCHAR)")
    con.executemany("INSERT INTO curated VALUES (?)", [(s,) for s in species])

    files = _list_parquet_files(con)
    log.info("obis_parquet: %d parquet files to process in batches of %d", len(files), files_per_batch)
    if stats is not None:
        stats["files_total"] = len(files)
        stats["files_ok"] = 0

    batch_query_template = f"""
        SELECT
            _id                                          AS obis_id,
            dataset_id                                   AS dataset_id,
            interpreted.occurrenceID                     AS occurrence_id,
            interpreted.scientificName                   AS scientific_name,
            interpreted.phylum                           AS phylum,
            interpreted.class                            AS class_name,
            interpreted.\"order\"                        AS order_name,
            interpreted.family                           AS family,
            interpreted.minimumDepthInMeters             AS depth,
            interpreted.decimalLatitude                  AS lat,
            interpreted.decimalLongitude                 AS lon
          FROM read_parquet(?)
         WHERE {_WHERE_QUALITY}
           AND (interpreted.scientificName IN (SELECT scientificName FROM curated)
                OR {_IS_CORAL})
    """

    for i in range(0, len(files), files_per_batch):
        batch_s3 = files[i:i + files_per_batch]
        os.makedirs(OBIS_SCRATCH_DIR, exist_ok=True)
        batch_dir = tempfile.mkdtemp(prefix="obis-batch-", dir=OBIS_SCRATCH_DIR)
        try:
            log.info("obis_parquet: batch %d–%d / %d — downloading", i, i + len(batch_s3), len(files))
            local_paths = _download_batch(batch_s3, batch_dir)
            if len(local_paths) < len(batch_s3):
                # A PARTIAL download used to pass silently: the batch was queried
                # with whatever arrived and nothing recorded the shortfall, so a
                # caller could not tell a full pass from a holed one.
                log.warning("obis_parquet: batch %d–%d downloaded %d of %d files — %d missing",
                            i, i + len(batch_s3), len(local_paths), len(batch_s3),
                            len(batch_s3) - len(local_paths))
            if not local_paths:
                log.warning("obis_parquet: batch %d–%d download yielded 0 files — skipping", i, i + len(batch_s3))
                continue
            log.info("obis_parquet: batch %d–%d / %d — querying %d local files",
                     i, i + len(batch_s3), len(files), len(local_paths))
            try:
                cursor = con.execute(batch_query_template, [local_paths])
                col_names = [d[0] for d in cursor.description]
                batch_rows = 0
                while True:
                    rows = cursor.fetchmany(chunk_size)
                    if not rows:
                        break
                    batch_rows += len(rows)
                    yield [dict(zip(col_names, row)) for row in rows]
                log.info("obis_parquet: batch %d–%d yielded %d rows", i, i + len(batch_s3), batch_rows)
                # Counted only here: a file is "ok" once it has been downloaded AND
                # read to the end without error. Anything less leaves files_ok short
                # of files_total, which is what blocks a purge downstream.
                if stats is not None:
                    stats["files_ok"] += len(local_paths)
            except Exception as exc:
                log.warning("obis_parquet: batch %d–%d query failed (%s) — skipping", i, i + len(batch_s3), exc)
        finally:
            shutil.rmtree(batch_dir, ignore_errors=True)


def list_parquet_file_count() -> int:
    """Quick sanity check: how many parquet files does OBIS expose?"""
    con = _connect()
    return con.execute(
        f"SELECT COUNT(*) FROM glob('{OBIS_PARQUET_GLOB}')"
    ).fetchone()[0]
