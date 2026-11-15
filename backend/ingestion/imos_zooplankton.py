# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""IMOS zooplankton abundance (AusCPR + National Reference Stations): ONE-SHOT import.

    python -m ingestion.imos_zooplankton <directory with the AODN WFS exports and MANIFEST.json> [--dry-run]

Not a periodic sync and never started by the API: the layer is a static snapshot (AODN WFS export of 2026-11-15).
Run it by hand on the VPS with the backend venv. Files read (each verified against MANIFEST.json sha256 first,
a mismatch aborts before anything is read):

    auscpr_zoop_copepods.csv + auscpr_zoop_non_copepods.csv   one row per CPR sample, joined on Sample_ID
    nrs_zoop_copepods.csv     + nrs_zoop_non_copepods.csv      one row per NRS sample, joined on TripCode

Column `abundances` holds a JSON object {taxon: individuals per m3}. Three kinds of cell, kept apart on purpose:
    a number > 0   present
    0              counted and absent  -> a row with abundance_m3 = 0
    null           NOT counted in that sample -> NO row (unknown, never a zero)
The NRS non-copepod file lists present taxa only: `noncopepod_zeros_explicit` is fixed per programme
(`NONCOPEPOD_ZEROS_EXPLICIT`, NRS false), so nothing downstream may read an unlisted taxon as zero.
⛔ The source `geom` column is `POINT (lat lon)`, swapped: coordinates come from Latitude / Longitude only.

Build: `_new` tables, loaded sample by sample in batches (memory stays at one batch), validated, then ONE
transaction drops the live pair and renames the new one in, under `SET LOCAL lock_timeout`. A failed run leaves the
live data untouched. The run holds the shared advisory lock 4242001 (obis-sync, vme-bake, plankton, glodap, socat,
wod, argo-doxy) and refuses to start while somebody else has it.
Exit codes: 0 swapped (or dry run ok), 2 checksum / data problem, 3 advisory lock busy, 4 swap lock timeout.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import logging
import math
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

import db
import log_redaction
from schema.imos_zooplankton import (
    ABUNDANCE_TABLE, SAMPLES_TABLE, abundance_ddl, renames, samples_ddl,
)
from ingestion.imos_zooplankton_rules import (KEY_PREFIX, NONCOPEPOD_ZERO_SHARE_EXPLICIT_MIN, NONCOPEPOD_ZERO_SHARE_IMPLICIT_MAX,
                                              NONCOPEPOD_ZEROS_EXPLICIT, SAMPLE_KEY_RE, SOURCE)
from sync_log import log_sync, log_sync_skipped

log = logging.getLogger("imos_zooplankton")

LOCK_KEY = 4242001                    # shared with obis_sync_worker, vme_bake_worker, plankton, glodap, socat, wod
LOCK_REASON = "advisory lock 4242001 held by another heavy job: import refused, run it again later"
SWAP_LOCK_TIMEOUT = "3s"
SWAP_BACKOFF = (10, 30, 60)           # four attempts at a 3 s lock_timeout
BATCH_SAMPLES = 500

# (programme, key column, copepod file, non-copepod file)
PROGRAMMES = (
    ("auscpr", "Sample_ID", "auscpr_zoop_copepods.csv", "auscpr_zoop_non_copepods.csv"),
    ("nrs", "TripCode", "nrs_zoop_copepods.csv", "nrs_zoop_non_copepods.csv"),
)
REQUIRED = {
    "auscpr": ("Sample_ID", "TripCode", "Region", "Latitude", "Longitude", "SampleTime_UTC", "SampleVolume_m3",
               "BiomassIndex_mgm3", "abundances"),
    "nrs": ("TripCode", "StationCode", "StationName", "Latitude", "Longitude", "SampleTime_UTC", "SampleDepth_m",
            "Biomass_mgm3", "abundances"),
}


class ImportProblem(Exception):
    """A checksum, schema or consistency failure: nothing is written (or the staging tables are dropped)."""


class SwapLockTimeout(Exception):
    """The swap could not get its locks in time; live data intact, staging pair left for inspection."""


# ── parsing ──────────────────────────────────────────────────────────────────

def _num(s: str | None) -> float | None:
    """CSV cell -> float, None for blank / NaN / inf (a NaN must never reach a Postgres cast)."""
    if s is None or not s.strip():
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def _text(s: str | None) -> str | None:
    s = (s or "").strip()
    return s or None


def _time(s: str | None) -> datetime | None:
    """SampleTime_UTC is a naive ISO string in UTC."""
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def parse_abundances(raw: str, counters: dict) -> list[tuple[str, float]]:
    """JSON object -> [(taxon, abundance)] for every COUNTED taxon (zero included). null / NaN / negative cells are
    not counted: no row, tallied in `counters`. Names are whitespace-trimmed; a name that trims to a duplicate is an
    ImportProblem (summing two distinct source columns would invent a number)."""
    obj = json.loads(raw, parse_constant=lambda _c: None)
    if not isinstance(obj, dict):
        raise ImportProblem("abundances is not a JSON object")
    out: dict[str, float] = {}
    for name, v in obj.items():
        taxon = name.strip()
        if not taxon:
            raise ImportProblem("empty taxon name")
        if taxon in out or (taxon in obj and taxon != name):
            raise ImportProblem(f"taxon names collide after trimming: {name!r}")
        if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
            counters["null_cells"] += 1
            continue
        if not math.isfinite(v) or v < 0:
            counters["bad_cells"] += 1
            continue
        out[taxon] = float(v)
    return list(out.items())


def _read_rows(path: Path, programme: str):
    csv.field_size_limit(sys.maxsize)
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in REQUIRED[programme] if c not in (reader.fieldnames or [])]
        if missing:
            raise ImportProblem(f"{path.name}: missing columns {missing}")
        yield from reader


def verify_manifest(directory: Path) -> dict:
    """sha256 of every file this layer reads against MANIFEST.json. Returns the manifest."""
    mpath = directory / "MANIFEST.json"
    if not mpath.is_file():
        raise ImportProblem(f"{mpath} not found")
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    files = manifest.get("files") or {}
    for _p, _k, cop, non in PROGRAMMES:
        for name in (cop, non):
            entry = files.get(name)
            if not entry or not entry.get("sha256"):
                raise ImportProblem(f"{name}: not listed in MANIFEST.json")
            path = directory / name
            if not path.is_file():
                raise ImportProblem(f"{name}: file missing")
            h = hashlib.sha256()
            with open(path, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            if h.hexdigest() != entry["sha256"]:
                raise ImportProblem(f"{name}: sha256 mismatch (manifest {entry['sha256'][:12]}…, file {h.hexdigest()[:12]}…)")
            log.info("sha256 ok: %s", name)
    return manifest


def snapshot_date(manifest: dict) -> date:
    """The day the WFS exports were taken: the earliest retrieved_utc among the files this layer reads."""
    stamps = []
    for _p, _k, cop, non in PROGRAMMES:
        for name in (cop, non):
            stamps.append(manifest["files"][name]["retrieved_utc"])
    return min(datetime.fromisoformat(s) for s in stamps).date()


# ── load ─────────────────────────────────────────────────────────────────────

_SAMPLE_SQL = f"""
INSERT INTO {SAMPLES_TABLE}_new
  (sample_key, programme, trip_code, region, station_code, station_name, lat, lon, geom, sample_time_utc,
   sample_depth_m, sample_volume_m3, biomass_mgm3, copepod_total_m3, n_copepod_taxa_present,
   noncopepod_zeros_explicit, snapshot)
VALUES ($1,$2,$3,$4,$5,$6,$7,$8, ST_SetSRID(ST_MakePoint($8,$7),4326), $9,$10,$11,$12,$13,$14,false,$15)
"""


def _stats() -> dict:
    return {"samples": {}, "abund": {True: 0, False: 0}, "zero": {True: 0, False: 0}, "null_cells": 0,
            "bad_cells": 0, "t_min": None, "t_max": None, "noncop_zero_cells": {}}


async def _copy_abundance(conn, rows: list[tuple]) -> None:
    if rows:
        await conn.copy_records_to_table(f"{ABUNDANCE_TABLE}_new", records=rows,
                                         columns=["sample_key", "taxon", "is_copepod", "abundance_m3"])


async def _load_copepods(conn, directory: Path, programme: str, key_col: str, fname: str, snap: date,
                         st: dict, meta: dict) -> None:
    """Pass 1: the samples (one row each) and their copepod abundances."""
    samples: list[tuple] = []
    ab: list[tuple] = []
    for r in _read_rows(directory / fname, programme):
        raw_key = (r[key_col] or "").strip()
        if not raw_key:
            raise ImportProblem(f"{fname}: a row without {key_col}")
        key = KEY_PREFIX[programme] + raw_key
        if not SAMPLE_KEY_RE.match(key):
            raise ImportProblem(f"{fname}: sample key {key!r} is not of the form the API accepts")
        if key in meta:
            raise ImportProblem(f"{fname}: duplicate sample {key}")
        lat, lon = _num(r["Latitude"]), _num(r["Longitude"])
        if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ImportProblem(f"{fname}: {key} has no valid Latitude/Longitude")
        t = _time(r["SampleTime_UTC"])
        counted = parse_abundances(r["abundances"], st)
        total = sum(v for _t, v in counted) if counted else None
        present = sum(1 for _t, v in counted if v > 0) if counted else None
        if programme == "auscpr":
            region, code, name = _text(r["Region"]), None, None
            depth, volume, biomass = None, _num(r["SampleVolume_m3"]), _num(r["BiomassIndex_mgm3"])
        else:
            region, code, name = None, _text(r["StationCode"]), _text(r["StationName"])
            depth, volume, biomass = _num(r["SampleDepth_m"]), None, _num(r["Biomass_mgm3"])
        samples.append((key, programme, _text(r["TripCode"]), region, code, name, lat, lon, t, depth, volume,
                        biomass, total, present, snap))
        meta[key] = (lat, lon, t)
        st["samples"][programme] = st["samples"].get(programme, 0) + 1
        if t is not None:
            st["t_min"] = t if st["t_min"] is None or t < st["t_min"] else st["t_min"]
            st["t_max"] = t if st["t_max"] is None or t > st["t_max"] else st["t_max"]
        for taxon, v in counted:
            ab.append((key, taxon, True, v))
            st["abund"][True] += 1
            st["zero"][True] += v == 0
        if len(samples) >= BATCH_SAMPLES:
            await conn.executemany(_SAMPLE_SQL, samples)
            await _copy_abundance(conn, ab)
            samples, ab = [], []
    if samples:
        await conn.executemany(_SAMPLE_SQL, samples)
        await _copy_abundance(conn, ab)


async def _load_noncopepods(conn, directory: Path, programme: str, key_col: str, fname: str,
                            st: dict, meta: dict) -> set[str]:
    """Pass 2: the non-copepod abundances. Every row must be a sample pass 1 saw, at the same place and time."""
    seen: set[str] = set()
    ab: list[tuple] = []
    zero_cells = 0
    cells = 0
    for i, r in enumerate(_read_rows(directory / fname, programme), 1):
        key = KEY_PREFIX[programme] + (r[key_col] or "").strip()
        if key not in meta:
            raise ImportProblem(f"{fname}: {key} is not in the copepod file")
        if key in seen:
            raise ImportProblem(f"{fname}: duplicate sample {key}")
        seen.add(key)
        lat, lon, t = meta[key]
        if (_num(r["Latitude"]) is None or abs(_num(r["Latitude"]) - lat) > 1e-6
                or abs((_num(r["Longitude"]) or 1e9) - lon) > 1e-6 or _time(r["SampleTime_UTC"]) != t):
            raise ImportProblem(f"{fname}: {key} differs from the copepod file in position or time")
        for taxon, v in parse_abundances(r["abundances"], st):
            ab.append((key, taxon, False, v))
            st["abund"][False] += 1
            st["zero"][False] += v == 0
            zero_cells += v == 0
            cells += 1
        if i % BATCH_SAMPLES == 0:
            await _copy_abundance(conn, ab)
            ab = []
    await _copy_abundance(conn, ab)
    st["noncop_zero_cells"][programme] = zero_cells
    share = zero_cells / cells if cells else 0.0
    explicit = NONCOPEPOD_ZEROS_EXPLICIT[programme]
    if (explicit and share < NONCOPEPOD_ZERO_SHARE_EXPLICIT_MIN) or (not explicit and share > NONCOPEPOD_ZERO_SHARE_IMPLICIT_MAX):
        raise ImportProblem(f"{fname}: zero share {share:.3f} contradicts NONCOPEPOD_ZEROS_EXPLICIT[{programme}]={explicit}; "
                            "the export changed shape, re-check before importing")
    return seen


async def build_staging(conn, directory: Path, snap: date) -> dict:
    """Create the `_new` pair and fill it. Raises ImportProblem on any inconsistency (staging is dropped by the caller)."""
    await conn.execute(f"DROP TABLE IF EXISTS {ABUNDANCE_TABLE}_new, {SAMPLES_TABLE}_new")
    for sql in samples_ddl("_new") + abundance_ddl("_new"):
        await conn.execute(sql)
    st = _stats()
    for programme, key_col, cop, non in PROGRAMMES:
        meta: dict[str, tuple] = {}
        await _load_copepods(conn, directory, programme, key_col, cop, snap, st, meta)
        seen = await _load_noncopepods(conn, directory, programme, key_col, non, st, meta)
        if seen != set(meta):
            raise ImportProblem(f"{programme}: the non-copepod file lacks {len(set(meta) - seen)} samples of the copepod file")
        # Explicit zeros are a property of what the programme's non-copepod file contains.
        await conn.execute(
            f"UPDATE {SAMPLES_TABLE}_new SET noncopepod_zeros_explicit = $1 WHERE programme = $2",
            NONCOPEPOD_ZEROS_EXPLICIT[programme], programme)
        log.info("%s: %d samples, non-copepod zero cells %d", programme, len(meta), st["noncop_zero_cells"][programme])
    return st


async def validate_staging(conn, st: dict) -> None:
    n = await conn.fetchval(f"SELECT count(*) FROM {SAMPLES_TABLE}_new")
    if n != sum(st["samples"].values()) or n == 0:
        raise ImportProblem(f"staging holds {n} samples, parsed {sum(st['samples'].values())}")
    a = await conn.fetchval(f"SELECT count(*) FROM {ABUNDANCE_TABLE}_new")
    if a != st["abund"][True] + st["abund"][False] or a == 0:
        raise ImportProblem(f"staging holds {a} abundance rows, parsed {st['abund'][True] + st['abund'][False]}")
    # Null-safe checks: count the bad rows with IS NULL / IS NOT TRUE, never NOT (a AND b).
    bad = await conn.fetchval(f"SELECT count(*) FROM {SAMPLES_TABLE}_new WHERE geom IS NULL OR sample_time_utc IS NULL")
    if bad:
        log.warning("%d samples have no sample time (kept, drawn, shown undated)", bad)


# ── swap ─────────────────────────────────────────────────────────────────────

async def _swap_tx(conn) -> None:
    async with conn.transaction():
        await conn.execute(f"SET LOCAL lock_timeout = '{SWAP_LOCK_TIMEOUT}'")
        await conn.execute(f"DROP TABLE IF EXISTS {ABUNDANCE_TABLE}")
        await conn.execute(f"DROP TABLE IF EXISTS {SAMPLES_TABLE}")
        for table in (SAMPLES_TABLE, ABUNDANCE_TABLE):
            await conn.execute(f"ALTER TABLE {table}_new RENAME TO {table}")
            for kind, name in renames("_new")[table]:
                live = name.replace("_new", "", 1)
                if kind == "constraint":
                    await conn.execute(f'ALTER TABLE {table} RENAME CONSTRAINT "{name}" TO "{live}"')
                else:
                    await conn.execute(f'ALTER INDEX "{name}" RENAME TO "{live}"')


async def swap(conn) -> None:
    for attempt, pause in enumerate((*SWAP_BACKOFF, None)):
        try:
            await _swap_tx(conn)
            return
        except asyncpg.exceptions.LockNotAvailableError as e:
            if pause is None:
                raise SwapLockTimeout(f"no lock after {attempt + 1} attempts of {SWAP_LOCK_TIMEOUT}; "
                                      "live data intact") from e
            log.warning("swap: lock not available (attempt %d), retrying in %d s", attempt + 1, pause)
            await asyncio.sleep(pause)


# ── run ──────────────────────────────────────────────────────────────────────

def print_summary(st: dict, snap: date, swapped: bool) -> None:
    total = st["abund"][True] + st["abund"][False]
    zeros = st["zero"][True] + st["zero"][False]
    print("IMOS zooplankton import" + (" (dry run, nothing written)" if not swapped else ""))
    print(f"  snapshot            {snap}")
    for p in ("auscpr", "nrs"):
        print(f"  samples {p:<10}  {st['samples'].get(p, 0):>9,}   non-copepod zero cells: "
              f"{st['noncop_zero_cells'].get(p, 0):,} -> zeros explicit: {NONCOPEPOD_ZEROS_EXPLICIT[p]}")
    print(f"  abundance rows      {total:>9,}   (copepods {st['abund'][True]:,}, non-copepods {st['abund'][False]:,})")
    print(f"  of which zero       {zeros:>9,}   (copepods {st['zero'][True]:,}, non-copepods {st['zero'][False]:,})")
    print(f"  null cells skipped  {st['null_cells']:>9,}   (not counted: no row)   non-finite/negative skipped: {st['bad_cells']:,}")
    print(f"  sample time range   {st['t_min']} .. {st['t_max']}")


async def run(directory: Path, dry_run: bool = False) -> int:
    manifest = verify_manifest(directory)
    snap = snapshot_date(manifest)
    if dry_run:
        st = await _dry_run(directory)
        print_summary(st, snap, swapped=False)
        return 0

    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=3)
    db.pool = pool                          # sync_log reads db.pool
    try:
        # ONE connection for the whole run: a session advisory lock is released when its connection goes away.
        async with pool.acquire() as conn:
            if not await conn.fetchval("SELECT pg_try_advisory_lock($1)", LOCK_KEY):
                log.error(LOCK_REASON)
                await log_sync_skipped(SOURCE, LOCK_REASON)
                return 3
            try:
                try:
                    st = await build_staging(conn, directory, snap)
                    await validate_staging(conn, st)
                except BaseException:
                    await conn.execute(f"DROP TABLE IF EXISTS {ABUNDANCE_TABLE}_new, {SAMPLES_TABLE}_new")
                    raise
                try:
                    await swap(conn)
                except SwapLockTimeout as e:
                    log.error("%s", e)
                    await log_sync_skipped(SOURCE, f"swap lock timeout: {e}")
                    return 4
                await conn.execute(f"ANALYZE {SAMPLES_TABLE}")
                await conn.execute(f"ANALYZE {ABUNDANCE_TABLE}")
                n = sum(st["samples"].values())
                await log_sync(SOURCE, n, n)
                print_summary(st, snap, swapped=True)
                return 0
            except ImportProblem as e:
                log.error("import refused: %s", e)
                await log_sync_skipped(SOURCE, f"import refused: {e}"[:300])
                return 2
            finally:
                await conn.execute("SELECT pg_advisory_unlock($1)", LOCK_KEY)
    finally:
        await pool.close()


async def _dry_run(directory: Path) -> dict:
    """Parse everything, write nothing (same code path minus the database)."""
    class _NoDb:
        async def executemany(self, *_a):
            pass

        async def copy_records_to_table(self, *_a, **_k):
            pass

    st = _stats()
    conn = _NoDb()
    snap = date.today()
    for programme, key_col, cop, non in PROGRAMMES:
        meta: dict[str, tuple] = {}
        await _load_copepods(conn, directory, programme, key_col, cop, snap, st, meta)
        seen = await _load_noncopepods(conn, directory, programme, key_col, non, st, meta)
        if seen != set(meta):
            raise ImportProblem(f"{programme}: the non-copepod file lacks samples of the copepod file")
    return st


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("directory", type=Path, help="directory holding the CSV exports and MANIFEST.json (read-only)")
    ap.add_argument("--dry-run", action="store_true", help="verify checksums and parse everything, write nothing")
    args = ap.parse_args(argv)
    load_dotenv()
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log_redaction.install()
    try:
        return asyncio.run(run(args.directory, args.dry_run))
    except ImportProblem as e:
        log.error("import refused: %s", e)
        return 2


if __name__ == "__main__":
    sys.exit(main())
