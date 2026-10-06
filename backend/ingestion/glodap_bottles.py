# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""GLODAPv3 bottle import — runs ONLY in glodap_bottles_worker (own cgroup), never in abyssal-api.

Download the zipped master CSV -> header gate -> DuckDB stream ordered by cast -> build_cast ->
COPY into glodap_casts_new -> validate -> swap names in one transaction. `sync_glodap_bottles`
never raises, and a failed, blocked or shrunk (> MAX_DROP fewer casts) refresh leaves the live
tables untouched.

Memory: the real file is ~1 GB of CSV. Nothing here may hold "all rows" or "all casts" — DuckDB
sorts under a memory cap (spilling to the scratch dir) and the casts are pulled, built and COPYed
in small chunks, so the worker's resident set stays flat.
"""
from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import logging
import os
import pathlib
import shutil
import time
import urllib.error
import urllib.request
import zipfile
from collections import Counter

import duckdb

import db
from api_access.notify import notify_telegram
from ingestion import USER_AGENT
from ingestion.glodap_bottles_rules import (  # noqa: F401  (SOURCE and the prefixes are re-exported for callers)
    REQUIRED_COLUMNS, SOURCE, SWAPPED_WITH_REJECTS_PREFIX, build_cast, cast_number, clean_or_none, row_problem)
from schema.glodap_bottles import CAST_COLUMNS, casts_ddl, casts_index_ddl, cruises_ddl
from sync_log import log_sync as _log_sync
from sync_log import log_sync_skipped

log = logging.getLogger(__name__)
ZIP_URL = "https://glodap.info/glodap_files/v3/GLODAPv3_Merged_Master_File.csv.zip"
# The same master file, uncompressed, from NCEI (doi:10.25921/m6tp-mj50). NOT fetched automatically:
# it is the manual fallback if glodap.info is down (download, zip it as CSV_NAME, point `fetch` at it).
NCEI_URL = "https://www.ncei.noaa.gov/data/oceans/ncei/ocads/data/0315582/GLODAPv3_Merged_Master_File.csv"
CSV_NAME = "GLODAPv3_Merged_Master_File.csv"
SCRATCH_DIR = pathlib.Path(os.getenv("GLODAP_SCRATCH_DIR", "/var/cache/abyssal-glodap"))
DUCKDB_MEMORY_LIMIT = "700MB"
MAX_DROP = 0.10
BATCH = 2000                 # casts per COPY
CHUNK = 64                   # casts built per thread hop
CASTS, CRUISES = "glodap_casts", "glodap_cruises"
ALERT_TITLE = "Abyssal GLODAP bottle import"

# NERC Vocabulary Server collection C17 (ICES platform codes) -> ship names.
# Licence VERIFIED 2026-10-06 at https://vocab.nerc.ac.uk/about, section "Licensing", exact text:
#   "Unless otherwise specified, the content of the NVS and of these webpages is licensed under CC BY 4.0
#    (legal code)."  legal code: https://creativecommons.org/licenses/by/4.0/legalcode
# No override: the C17 concept records carry no licence property and the NVS VoID document names none.
# CC BY 4.0 requires attribution — "The NERC Vocabulary Server (NVS), National Oceanography Centre -
# British Oceanographic Data Centre (BODC), https://vocab.nerc.ac.uk" plus the collection's own
# title/URI (https://vocab.nerc.ac.uk/collection/C17/current/) — which DATA-LICENCES.md and the panel owe.
# The bulk collection document (~18 MB) is flaky (IncompleteRead), so codes are fetched one by one.
NVS_C17_URL = "https://vocab.nerc.ac.uk/collection/C17/current/{code}/?_profile=nvs&_mediatype=application/ld+json"
NVS_DEADLINE_S = 300.0


class HeaderMismatch(Exception):
    pass


def default_fetch(dest: pathlib.Path) -> dict:
    req = urllib.request.Request(ZIP_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as r, dest.open("wb") as f:
        shutil.copyfileobj(r, f, 1 << 20)
        fp = {"etag": r.headers.get("ETag"), "content_length": int(r.headers.get("Content-Length") or 0),
              "last_modified": r.headers.get("Last-Modified")}
    if fp["content_length"] and dest.stat().st_size != fp["content_length"]:
        raise OSError(f"truncated download: {dest.stat().st_size} of {fp['content_length']} bytes")
    return fp


def head_fingerprint() -> dict:
    req = urllib.request.Request(ZIP_URL, method="HEAD", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        return {"etag": r.headers.get("ETag"), "content_length": int(r.headers.get("Content-Length") or 0),
                "last_modified": r.headers.get("Last-Modified")}


def default_ship_lookup(codes: list[str]) -> dict[str, str]:
    """ICES platform code -> ship name from NVS C17 (licence: see NVS_C17_URL's comment). Sequential,
    one retry per code, an overall deadline; a missing or failing code is skipped, never fatal."""
    out: dict[str, str] = {}
    deadline = time.monotonic() + NVS_DEADLINE_S
    for c in codes:
        if time.monotonic() > deadline:
            log.warning("NVS C17: deadline reached, %d of %d codes resolved", len(out), len(codes))
            break
        req = urllib.request.Request(NVS_C17_URL.format(code=c),
                                     headers={"User-Agent": USER_AGENT, "Accept": "application/ld+json"})
        label = None
        for _ in (1, 2):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    label = json.load(r).get("skos:prefLabel")
                break
            except urllib.error.HTTPError as e:
                if e.code == 404:                  # unknown code: not a failure worth retrying
                    break
                log.warning("NVS C17 %s: %s", c, e)
            except Exception as e:                 # one bad code must not lose the other ~140
                log.warning("NVS C17 %s: %s", c, e)
        if isinstance(label, dict) and label.get("@value"):
            out[c] = label["@value"]
    return out


def unpack(zip_path: pathlib.Path, run_dir: pathlib.Path) -> pathlib.Path:
    with zipfile.ZipFile(zip_path) as z:            # BadZipFile on a truncated/HTML download
        bad = z.testzip()
        if bad:
            raise zipfile.BadZipFile(f"CRC error in {bad}")
        names = [n for n in z.namelist() if n.endswith(CSV_NAME)]
        if len(names) != 1:
            raise zipfile.BadZipFile(f"expected one {CSV_NAME}, got {z.namelist()}")
        z.extract(names[0], run_dir)
        return run_dir / names[0]


def sha256_of(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def check_header(csv_path: pathlib.Path) -> None:
    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        header = next(csv.reader(f), [])
    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if missing:
        raise HeaderMismatch(f"source header changed: missing {', '.join(missing)}")


def iter_casts(csv_path: pathlib.Path, scratch: pathlib.Path):
    """Yield the rows of one cast at a time, ordered by (expocode, station, cast). DuckDB under a memory
    cap spilling into `scratch/duckdb`; every column kept as text; only the columns the rules read."""
    con = duckdb.connect()
    try:
        spill = str(scratch / "duckdb").replace("'", "''")
        con.execute(f"SET memory_limit='{DUCKDB_MEMORY_LIMIT}'")
        con.execute("SET threads=2")
        con.execute(f"SET temp_directory='{spill}'")
        con.execute("SET preserve_insertion_order=false")
        cols = ", ".join(f'"{c}"' for c in REQUIRED_COLUMNS)
        rel = con.execute(f"""SELECT {cols} FROM read_csv(?, header=true, all_varchar=true)
                              ORDER BY expocode, station,
                                       (TRY_CAST("cast" AS DOUBLE) IS NULL OR isnan(TRY_CAST("cast" AS DOUBLE))
                                        OR isinf(TRY_CAST("cast" AS DOUBLE))
                                        OR TRY_CAST("cast" AS DOUBLE) = -9999) DESC, "cast" """, [str(csv_path)])
        names = [d[0] for d in rel.description]
        cur_key, cur = None, []
        while True:
            chunk = rel.fetchmany(20_000)
            if not chunk:
                break
            for t in chunk:
                row = dict(zip(names, t, strict=True))
                # every spelling of "no cast number" (-9999, NaN, empty) is ONE group, as in cast_key
                k = (row["expocode"], row["station"], row["cast"] if cast_number(row["cast"]) is not None else None)
                if k != cur_key and cur:
                    yield cur
                    cur = []
                cur_key = k
                cur.append(row)
        if cur:
            yield cur
    finally:
        con.close()


class Tally:
    """Counters of one run; filled by `take_casts` (in a worker thread) and read by the caller after."""

    def __init__(self) -> None:
        self.rows = 0           # every source row
        self.depthless = 0      # rows without a usable depth (not stored)
        self.rejected = Counter()   # depth-bearing rows refused: "key" (no expocode/station) / "position" / "date"
        self.dup_casts = 0      # casts whose cast_key was already taken by an earlier source group
        self.bad_casts = 0      # casts build_cast could not parse (junk text in a numeric column)
        self.casts = 0
        self.drawn = 0          # casts with at least one flag-2 value
        self.samples = 0
        self.seen: set[str] = set()

    @property
    def rejected_rows(self) -> int:
        return sum(self.rejected.values())

    def summary(self) -> str | None:
        parts = []
        if self.rejected:
            parts.append(f"rejected_rows={self.rejected_rows} (" + ", ".join(
                f"{k}={v}" for k, v in sorted(self.rejected.items())) + ")")
        if self.dup_casts:
            parts.append(f"duplicate_casts={self.dup_casts}")
        if self.bad_casts:
            parts.append(f"unparseable_casts={self.bad_casts}")
        return "; ".join(parts) or None


def rejects_json(tally: Tally) -> str:
    """The run's reject counts by reason, as stored in glodap_bottle_source.last_rejects (survives the daily
    skips that overwrite sync_log.skipped_reason). {} for a clean run, so it also clears the previous run's."""
    out = {}
    if tally.rejected:
        out["rejected_rows"] = tally.rejected_rows
        out["by_reason"] = dict(sorted(tally.rejected.items()))
    if tally.dup_casts:
        out["duplicate_casts"] = tally.dup_casts
    if tally.bad_casts:
        out["unparseable_casts"] = tally.bad_casts
    return json.dumps(out, allow_nan=False)


def _one_cast(rows: list[dict], tally: Tally) -> dict | None:
    tally.rows += len(rows)
    keep = []
    for r in rows:
        if clean_or_none(r["depth"]) is None:
            tally.depthless += 1
            continue
        why = row_problem(r)
        if why:
            tally.rejected[why] += 1
            continue
        keep.append(r)
    if not keep:
        return None
    try:
        c = build_cast(keep)
    except (ValueError, TypeError, OverflowError) as e:    # junk text in a numeric column
        tally.bad_casts += 1
        log.warning("glodap: cast %s/%s/%s skipped, unparseable: %s", rows[0]["expocode"], rows[0]["station"],
                    rows[0]["cast"], e)
        return None
    if c is None:
        return None
    if c["cast_key"] in tally.seen:
        tally.dup_casts += 1
        return None
    tally.seen.add(c["cast_key"])
    tally.casts += 1
    tally.samples += c["n_samples"]
    tally.drawn += c["n_good"] > 0
    return c


def take_casts(it, tally: Tally, n: int | None = None) -> list[dict]:
    """Pull up to `n` source casts from `it`, return the built casts. Blocking: call in a thread."""
    out = []
    for _ in range(n or CHUNK):
        rows = next(it, None)
        if rows is None:
            break
        c = _one_cast(rows, tally)
        if c is not None:
            out.append(c)
    else:
        return out
    out.append(None)           # sentinel: the source is exhausted
    return out


async def build_staging(conn) -> None:
    """Fresh, empty `_new` pair (a leftover from a killed run is dropped first)."""
    await discard_staging(conn)
    for sql in casts_ddl(f"{CASTS}_new") + cruises_ddl(f"{CRUISES}_new"):
        await conn.execute(sql)


async def discard_staging(conn) -> None:
    await conn.execute(f"DROP TABLE IF EXISTS {CASTS}_new")
    await conn.execute(f"DROP TABLE IF EXISTS {CRUISES}_new")


def _record(c: dict) -> tuple:
    c = dict(c, levels=json.dumps(c["levels"], allow_nan=False))      # asyncpg: jsonb takes text
    return tuple(c.get(col) for col in CAST_COLUMNS)


async def validate_staging(conn) -> list[str]:
    """Reasons to block the swap (empty = OK). An empty live table (first run) never blocks on the drop."""
    reasons = []
    new = await conn.fetchval(f"SELECT count(*) FROM {CASTS}_new")
    old = await conn.fetchval(f"SELECT count(*) FROM {CASTS}")
    if new == 0:
        reasons.append("staging is empty")
    if old and new < old * (1 - MAX_DROP):
        reasons.append(f"casts dropped {old} -> {new} (more than {int(MAX_DROP * 100)} %)")
    cruises, cruise_casts = await conn.fetchrow(
        f"SELECT count(*), coalesce(sum(n_casts), 0) FROM {CRUISES}_new")
    expocodes = await conn.fetchval(f"SELECT count(DISTINCT expocode) FROM {CASTS}_new")
    if cruises != expocodes or cruise_casts != new:
        reasons.append(f"cruise table disagrees with the casts ({cruises} cruises / {cruise_casts} casts "
                       f"vs {expocodes} expocodes / {new} casts)")
    return reasons


async def _swap_tx(conn, lock_timeout: str, in_tx) -> None:
    async with conn.transaction():
        # Bounded wait: a queued ACCESS EXCLUSIVE request blocks every new SELECT on the table.
        await conn.execute(f"SET LOCAL lock_timeout = '{lock_timeout}'")
        for t in (CASTS, CRUISES):
            await conn.execute(f"DROP TABLE IF EXISTS {t}")
            await conn.execute(f"ALTER TABLE {t}_new RENAME TO {t}")
            # Constraints, indexes and the identity sequence are separate objects that keep their `_new`
            # names; rename them or the next ensure_glodap_bottles builds a second set beside them.
            for (name,) in await conn.fetch(
                    "SELECT conname FROM pg_constraint WHERE conrelid = $1::regclass AND conname LIKE $2",
                    t, f"{t}\\_new%"):
                await conn.execute(f'ALTER TABLE {t} RENAME CONSTRAINT "{name}" TO "{t}{name[len(t) + 4:]}"')
            for (name,) in await conn.fetch(
                    "SELECT indexname FROM pg_indexes WHERE schemaname = current_schema() "
                    "AND tablename = $1 AND indexname LIKE $2", t, f"{t}\\_new%"):
                await conn.execute(f'ALTER INDEX "{name}" RENAME TO "{t}{name[len(t) + 4:]}"')
        seq = await conn.fetchval("SELECT pg_get_serial_sequence($1, 'id')", CASTS)
        if seq and seq.endswith(f"{CASTS}_new_id_seq"):
            await conn.execute(f"ALTER SEQUENCE {seq} RENAME TO {CASTS}_id_seq")
        if in_tx is not None:
            await in_tx(conn)         # e.g. the source row: atomic with the swap, or neither


async def swap(conn, lock_timeout: str = "3s", backoff: tuple[float, ...] = (10, 30, 60), *, in_tx=None) -> None:
    """Index + ANALYZE the staging tables, then replace the live pair in ONE transaction (DDL is
    transactional: any failure rolls every rename back). Each attempt waits at most `lock_timeout` for its
    locks; after the last failed attempt the LockNotAvailableError propagates, live tables untouched.
    `in_tx(conn)`, if given, runs inside the same transaction after the renames. Does not validate."""
    import asyncpg
    for sql in casts_index_ddl(f"{CASTS}_new"):
        await conn.execute(sql)
    await conn.execute(f"ANALYZE {CASTS}_new")
    await conn.execute(f"ANALYZE {CRUISES}_new")
    for attempt in range(len(backoff) + 1):
        try:
            await _swap_tx(conn, lock_timeout, in_tx)
            return
        except asyncpg.exceptions.LockNotAvailableError:
            if attempt == len(backoff):
                raise
            await asyncio.sleep(backoff[attempt])


async def _outcome(reason: str | None, casts: int = 0, *, alert: bool = True, note: str | None = None) -> None:
    """Record the exit in sync_log and alert on failure paths. Never raises: a failing log or alert must
    not mask the real outcome."""
    try:
        if reason is None:
            await _log_sync(SOURCE, casts, casts)         # full rebuild: every cast held was "added"
            if note:
                async with db.pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE sync_log SET skipped_reason = $2, skipped_at = NOW() WHERE source = $1",
                        SOURCE, f"{SWAPPED_WITH_REJECTS_PREFIX}: {note}")
        else:
            await log_sync_skipped(SOURCE, reason)
    except Exception:
        log.exception("glodap-bottles: could not write sync_log")
    if reason is not None and alert or note:
        try:
            await notify_telegram(f"glodap-bottles: {reason or 'swapped, but ' + note}", ALERT_TITLE)
        except Exception:
            log.exception("glodap-bottles: telegram notify failed")


def _cruise_row(c: dict) -> dict:
    return {"platform_code": c["platform_code"], "doi": c["doi"], "first_date": c["obs_date"],
            "last_date": c["obs_date"], "n_casts": 0, "first_cast_key": c["cast_key"],
            "lat": c["lat"], "lon": c["lon"]}


def _fold_into_cruise(cruises: dict, c: dict) -> None:
    cr = cruises.setdefault(c["expocode"], _cruise_row(c))
    cr["n_casts"] += 1
    if c["obs_date"] < cr["first_date"]:
        cr.update(first_date=c["obs_date"], first_cast_key=c["cast_key"], lat=c["lat"], lon=c["lon"])
    cr["last_date"] = max(cr["last_date"], c["obs_date"])


async def _load(conn, csv_path: pathlib.Path, run_dir: pathlib.Path, tally: Tally) -> dict[str, dict]:
    """Stream the CSV into glodap_casts_new; return the per-expocode cruise aggregates."""
    cruises: dict[str, dict] = {}
    batch: list[tuple] = []
    it = iter_casts(csv_path, run_dir)
    try:
        done = False
        while not done:
            built = await asyncio.to_thread(take_casts, it, tally)
            if built and built[-1] is None:
                done = True
                built.pop()
            for c in built:
                _fold_into_cruise(cruises, c)
                batch.append(_record(c))
            if len(batch) >= BATCH or (done and batch):
                await conn.copy_records_to_table(f"{CASTS}_new", records=batch, columns=list(CAST_COLUMNS))
                batch = []
    finally:
        it.close()
    return cruises


async def sync_glodap_bottles(*, fetch=None, ship_lookup=None, scratch=None) -> dict:
    """One full import. Never raises. -> {"outcome": "swapped"|"blocked"|"lock_timeout"|"error"|"schema",
    "casts": int, "reasons": [str], "rejected": {...}}. Every exit is logged via sync_log."""
    try:
        return await _sync(fetch or default_fetch, ship_lookup or default_ship_lookup,
                           pathlib.Path(scratch or SCRATCH_DIR) / "run")
    except asyncio.CancelledError:
        raise
    except Exception as e:                    # the contract: never raises
        log.exception("glodap-bottles: unexpected failure")
        await _outcome(f"error: {type(e).__name__}: {e}"[:300])
        return {"outcome": "error", "casts": 0, "reasons": [f"{type(e).__name__}: {e}"], "rejected": {}}


async def _sync(fetch, ship_lookup, run_dir: pathlib.Path) -> dict:
    shutil.rmtree(run_dir, ignore_errors=True)
    try:
        try:
            (run_dir / "duckdb").mkdir(parents=True, exist_ok=True)
        except OSError as e:
            await _outcome(f"error: scratch directory unusable: {e}")
            return {"outcome": "error", "casts": 0, "reasons": [str(e)], "rejected": {}}
        try:
            zip_path = run_dir / "glodap.zip"
            fp = await asyncio.to_thread(fetch, zip_path)
            fp = dict(fp, sha256=await asyncio.to_thread(sha256_of, zip_path))
            csv_path = await asyncio.to_thread(unpack, zip_path, run_dir)
            zip_path.unlink(missing_ok=True)            # 120 MB we no longer need while the CSV is read
            await asyncio.to_thread(check_header, csv_path)
        except HeaderMismatch as e:
            await _outcome(str(e))
            return {"outcome": "schema", "casts": 0, "reasons": [str(e)], "rejected": {}}
        except Exception as e:
            await _outcome(f"error: download/unpack failed: {type(e).__name__}: {e}"[:300])
            return {"outcome": "error", "casts": 0, "reasons": [str(e)], "rejected": {}}

        tally = Tally()
        async with db.pool.acquire() as conn:
            try:
                await build_staging(conn)
                cruises = await _load(conn, csv_path, run_dir, tally)
                codes = sorted({v["platform_code"] for v in cruises.values() if v["platform_code"]})
                try:
                    ships = await asyncio.to_thread(ship_lookup, codes)
                except Exception as e:                  # names are decoration: the import goes on without
                    log.warning("glodap: ship lookup failed: %s", e)
                    ships = {}
                missing_ships = sum(1 for c in codes if c not in ships)
                await conn.copy_records_to_table(f"{CRUISES}_new", columns=[
                    "expocode", "platform_code", "ship_name", "doi", "first_date", "last_date", "n_casts",
                    "first_cast_key", "lat", "lon"], records=[
                    (e, v["platform_code"], ships.get(v["platform_code"]), v["doi"], v["first_date"],
                     v["last_date"], v["n_casts"], v["first_cast_key"], v["lat"], v["lon"])
                    for e, v in cruises.items()])
                reasons = await validate_staging(conn)
                if reasons:
                    await discard_staging(conn)
                    await _outcome("blocked: " + "; ".join(reasons))
                    return {"outcome": "blocked", "casts": tally.casts, "reasons": reasons,
                            "rejected": dict(tally.rejected)}

                async def record_source(c) -> None:
                    await c.execute("""UPDATE glodap_bottle_source SET source_url=$1, etag=$2, content_length=$3,
                        last_modified=$4, sha256=$5, loaded_at=now(), last_checked_at=now(),
                        refresh_requested_at=NULL, n_rows_source=$6, n_rows_depthless=$7, n_casts=$8,
                        n_casts_drawn=$9, n_samples=$10, ship_lookup_failed=$11,
                        last_failed_at=NULL, last_failure=NULL,
                        last_rejects=$12::jsonb, last_rejects_at=now() WHERE id=1""",
                                    ZIP_URL, fp.get("etag"), fp.get("content_length"), fp.get("last_modified"),
                                    fp["sha256"], tally.rows, tally.depthless, tally.casts, tally.drawn,
                                    tally.samples, missing_ships, rejects_json(tally))

                await swap(conn, in_tx=record_source)
            except Exception as e:
                try:
                    await discard_staging(conn)          # disk: a half-built _new is hundreds of MB
                except Exception:
                    log.exception("glodap: could not drop staging")
                if type(e).__name__ == "LockNotAvailableError":
                    await _outcome("lock_timeout on swap; live tables untouched")
                    return {"outcome": "lock_timeout", "casts": tally.casts, "reasons": [str(e)],
                            "rejected": dict(tally.rejected)}
                await _outcome(f"error: load failed: {type(e).__name__}: {e}"[:300])
                return {"outcome": "error", "casts": tally.casts, "reasons": [f"{type(e).__name__}: {e}"],
                        "rejected": dict(tally.rejected)}
        try:
            from domains import glodap_points
            glodap_points.clear_caches()     # drop this process's cached map document (the API re-checks loaded_at itself)
        except Exception:
            log.exception("glodap: could not clear the points cache")
        note = tally.summary()
        if note:
            log.warning("glodap: %s", note)
        await _outcome(None, tally.casts, note=note)
        return {"outcome": "swapped", "casts": tally.casts, "reasons": [], "rejected": dict(tally.rejected)}
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)
