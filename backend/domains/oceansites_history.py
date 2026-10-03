# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""OceanSITES historical record — the GDAC catalogue and the mooring↔file links.

``oceansites_stations`` is the OceanOPS register; ~970 of its 1,038 moorings are
closed, inactive or only registered, and the live-observation sync
(``sensors.sync_oceansites_obs``) can say nothing about them. What they measured,
where it was published, sits in the OceanSITES GDAC. This module:

1. ``refresh_catalogue()``  — the GDAC's one index file → ``oceansites_gdac_files``
   (UPSERT, never delete);
2. ``rebuild_links()``      — position + name matching → ``oceansites_station_files``
   and the ``history_*`` summary columns on ``oceansites_stations``;
3. ``fetch_series()``      — every-k-th real measurements of the linked files over
   OPeNDAP → ``oceansites_gdac_series`` (see ``ingestion/oceansites_opendap.py``);
4. ``GET /v1/oceansites/{ref}/history`` — what steps 1-3 left, merged per mooring.

Parsing and matching are pure and live in ``ingestion/oceansites_history.py``.

A second source shares every table: the Davis Strait moorings (``DS_*``) are not in
the GDAC but in a CC0 dataset at the NSF Arctic Data Center
(``ingestion/oceansites_adc.py``). ``oceansites_gdac_files.source`` says which archive
a row came from (``gdac`` | ``adc_davis``); ``refresh_adc()`` catalogues AND samples
those files in one pass (they are plain downloads, not OPeNDAP), ``rebuild_links()``
matches both sources, and the ``history_*`` summary counts both.

⛔ "Missing" and "broken" must not share a code path. On 2026-10-01 the GDAC
answered 503 to everything for about an hour. An index we could not fetch says
nothing about the catalogue: stored rows are left exactly as they were.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import time
from datetime import datetime, timezone

import db
import httpx
from auth import get_api_key
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from ingestion import oceansites_adc as adc
from ingestion import oceansites_history as ingest
from ingestion import oceansites_opendap as dap
from ingestion.oceansites_gdac import gdac_reachable
from response_cache import CACHE_TTL, store as _cache
from sync_log import log_sync as _log_sync
from sync_log import log_sync_skipped as _log_sync_skipped

log = logging.getLogger(__name__)

router = APIRouter()

SYNC_SOURCE = "oceansites-history"

_UPSERT_SQL = """
    INSERT INTO oceansites_gdac_files
        (file, site_dir, platform_code, data_mode, start_time, end_time,
         lat, lon, position_source, bbox_south, bbox_north, bbox_west, bbox_east,
         min_depth, max_depth, parameters, size_bytes, gdac_update_date,
         date_update, seen_at)
    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19, NOW())
    ON CONFLICT (file) DO UPDATE SET
        site_dir = EXCLUDED.site_dir, platform_code = EXCLUDED.platform_code,
        data_mode = EXCLUDED.data_mode, start_time = EXCLUDED.start_time,
        end_time = EXCLUDED.end_time, lat = EXCLUDED.lat, lon = EXCLUDED.lon,
        position_source = EXCLUDED.position_source,
        bbox_south = EXCLUDED.bbox_south, bbox_north = EXCLUDED.bbox_north,
        bbox_west = EXCLUDED.bbox_west, bbox_east = EXCLUDED.bbox_east,
        min_depth = EXCLUDED.min_depth, max_depth = EXCLUDED.max_depth,
        parameters = EXCLUDED.parameters, size_bytes = EXCLUDED.size_bytes,
        gdac_update_date = EXCLUDED.gdac_update_date,
        date_update = EXCLUDED.date_update, seen_at = NOW()
"""

_BATCH = 5000


def _row_args(r: dict) -> tuple:
    return (
        r["file"], r["site_dir"], r["platform_code"], r["data_mode"],
        r["start_time"], r["end_time"], r["lat"], r["lon"], r["position_source"],
        r["bbox_south"], r["bbox_north"], r["bbox_west"], r["bbox_east"],
        r["min_depth"], r["max_depth"], r["parameters"], r["size_bytes"],
        r["gdac_update_date"], r["date_update"],
    )


async def refresh_catalogue() -> int | None:
    """Fetch the GDAC index and UPSERT one row per ``DATA/`` file.

    Returns the number of rows written, or ``None`` when the index could not be
    fetched. ⛔ ``None`` is "could not look", never "nothing there": no row is
    touched, and the caller must not treat it as an empty catalogue. Rows that
    drop out of a later index are kept (the catalogue is a record, not a mirror).
    """
    text = await ingest.fetch_index()
    if text is None:
        return None
    # ~60k lines of parsing and median-fallback: keep it off the event loop.
    rows = await asyncio.to_thread(ingest.parse_index, text)
    if not rows:
        log.warning("OceanSITES index parsed to zero DATA/ rows — catalogue left as it was")
        return None
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            for i in range(0, len(rows), _BATCH):
                await conn.executemany(_UPSERT_SQL, [_row_args(r) for r in rows[i:i + _BATCH]])
    return len(rows)


async def rebuild_links() -> dict | None:
    """Rebuild ``oceansites_station_files`` from the stored catalogue, and write
    the ``history_*`` summary onto ``oceansites_stations``.

    Both sources are matched: GDAC files by position AND name, Davis Strait (ADC)
    files by name AND date (``ingestion/oceansites_adc.match_adc_files``, no position).
    Delete-then-insert of the link table is fine — it is derived, not source —
    but it happens inside ONE transaction with the summary update, so a reader
    never sees links without their summary or an emptied table.

    Returns ``{"linked_stations", "linked_files", "links", "rejected_nearby", ...}``,
    or ``None`` when the catalogue holds nothing to match (nothing to match against
    is not "nothing matches": links and summaries stay as they were).
    """
    async with db.pool.acquire() as conn:
        stations = [dict(r) for r in await conn.fetch(
            "SELECT ref, name, lat, lon, deploy_date FROM oceansites_stations"
        )]
        deployments = [dict(r) for r in await conn.fetch(
            "SELECT base_ref, name, lat, lon, deploy_date FROM oceansites_deployments"
        )]
        files = [dict(r) for r in await conn.fetch(
            "SELECT file, site_dir, platform_code, lat, lon, "
            "bbox_south, bbox_north, bbox_west, bbox_east FROM oceansites_gdac_files "
            "WHERE source = 'gdac' AND lat IS NOT NULL AND lon IS NOT NULL"
        )]
        adc_files = [dict(r) for r in await conn.fetch(
            "SELECT file, platform_code, start_time, end_time, lat, lon "
            "FROM oceansites_gdac_files WHERE source = $1", adc.SOURCE
        )]
    if not files and not adc_files:
        return None

    # match_files wants positioned deployments only (it measures to them)
    positioned = [d for d in deployments if d["lat"] is not None and d["lon"] is not None]
    links, rejected = await asyncio.to_thread(ingest.match_files, stations, positioned, files)
    adc_links = await asyncio.to_thread(adc.match_adc_files, stations, deployments, adc_files)
    links = links + adc_links

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM oceansites_station_files")
            if links:
                await conn.copy_records_to_table(
                    "oceansites_station_files",
                    records=[(l["station_ref"], l["file"], l["rule"], l["distance_km"]) for l in links],
                    columns=["station_ref", "file", "rule", "distance_km"],
                )
            await conn.execute("""
                UPDATE oceansites_stations s
                   SET history_files = COALESCE(a.n, 0),
                       history_start = a.t0,
                       history_end   = a.t1
                  FROM oceansites_stations s2
                  LEFT JOIN (
                        SELECT sf.station_ref, COUNT(*) AS n,
                               MIN(f.start_time) AS t0, MAX(f.end_time) AS t1
                          FROM oceansites_station_files sf
                          JOIN oceansites_gdac_files f USING (file)
                         GROUP BY sf.station_ref
                       ) a ON a.station_ref = s2.ref
                 WHERE s.ref = s2.ref
            """)
    return {
        "linked_stations": len({l["station_ref"] for l in links}),
        "linked_files": len({l["file"] for l in links}),
        "links": len(links),
        "adc_linked_stations": len({l["station_ref"] for l in adc_links}),
        "adc_linked_files": len({l["file"] for l in adc_links}),
        "adc_links": len(adc_links),
        "rejected_nearby": len(rejected),
        "rejected_sample": rejected[:15],
    }


# ── Series: sampled measurements of the linked files ───────────────────────

_SERIES_UPSERT_SQL = """
    INSERT INTO oceansites_gdac_series
        (file, variable, depth_index, depth_m, units, long_name, standard_name,
         n_total, stride, times, vals, qc, first_time, last_time,
         gdac_update_date, fetched_at)
    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15, NOW())
    ON CONFLICT (file, variable, depth_index) DO UPDATE SET
        depth_m = EXCLUDED.depth_m, units = EXCLUDED.units, long_name = EXCLUDED.long_name,
        standard_name = EXCLUDED.standard_name, n_total = EXCLUDED.n_total,
        stride = EXCLUDED.stride, times = EXCLUDED.times, vals = EXCLUDED.vals,
        qc = EXCLUDED.qc, first_time = EXCLUDED.first_time, last_time = EXCLUDED.last_time,
        gdac_update_date = EXCLUDED.gdac_update_date, fetched_at = NOW()
"""

_FETCHED_UPSERT_SQL = """
    INSERT INTO oceansites_gdac_fetched
        (file, outcome, detail, change_marker, standard_names, n_series, citation, fetched_at)
    VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
    ON CONFLICT (file) DO UPDATE SET
        outcome = EXCLUDED.outcome, detail = EXCLUDED.detail,
        change_marker = EXCLUDED.change_marker, standard_names = EXCLUDED.standard_names,
        n_series = EXCLUDED.n_series, citation = EXCLUDED.citation, fetched_at = NOW()
"""

DEFAULT_MAX_FILES_PER_RUN = 6000  # measured full first fill: 5,448 files, ~14 min
_CONCURRENCY = 4
_ABORT_AFTER_UNAVAILABLE = 10  # consecutive "server cannot answer" files end the run


def max_files_per_run() -> int:
    """``OCEANSITES_HISTORY_MAX_FILES_PER_RUN`` (default 6000). The measured full
    first fill is 5,448 files (~14 min), so one run completes it; set a lower value
    to spread it over several runs."""
    raw = os.getenv("OCEANSITES_HISTORY_MAX_FILES_PER_RUN", "")
    try:
        n = int(raw)
    except ValueError:
        return DEFAULT_MAX_FILES_PER_RUN
    return n if n >= 1 else DEFAULT_MAX_FILES_PER_RUN


async def _store_file(file: str, names: set[str], marker: str | None, gdac_stamp: datetime | None,
                      result: "dap.FileFetch | None", previous: dict | None,
                      outcome: str = "ok", detail: str | None = None) -> None:
    """One file, one transaction: its series rows and its read-log row together.

    ``outcome`` 'empty' / 'refused' (``result`` None) settle a file that has no
    data to give; they write no series rows and leave any stored ones alone.
    For an 'ok' file the rows of every variable that was read are REPLACED (deleted
    and inserted in this one transaction); ``detail`` then carries any note on what
    was left out (packed variables).
    """
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            if result is None:
                await conn.execute(_FETCHED_UPSERT_SQL, file, outcome, detail, marker,
                                   sorted(names), 0, None)
                return
            stamp = gdac_stamp if dap.valid_stamp(gdac_stamp) else None
            # A republished file is read again, and the new read is the whole truth about
            # the variables it answered for: a level that is now all fill, or a depth_step
            # that moved, must not leave the old rows behind to be merged with the new.
            # ⛔ Only variables READ successfully this time: one the server refused
            # ("constraint refused") or one we could not plan says nothing, so its stored
            # rows stay. And this code is not reached for a failed or refused file at all.
            if result.variables_read:
                await conn.execute(
                    "DELETE FROM oceansites_gdac_series WHERE file = $1 AND variable = ANY($2::text[])",
                    file, sorted(result.variables_read))
            for r in result.series:
                await conn.execute(
                    _SERIES_UPSERT_SQL, file, r.variable, r.depth_index, r.depth_m, r.units,
                    r.long_name, r.standard_name, r.n_total, r.stride, r.times, r.vals, r.qc,
                    r.first_time, r.last_time, stamp,
                )
            kept = set(names)
            if previous and previous.get("outcome") == "ok" and previous.get("change_marker") == marker:
                kept |= set(previous.get("standard_names") or ())
            await conn.execute(_FETCHED_UPSERT_SQL, file, "ok", detail, marker, sorted(kept),
                               len(result.series), result.citation)


async def fetch_series(client: httpx.AsyncClient | None = None,
                       max_files: int | None = None) -> dict | None:
    """Sample the linked files' measurements into ``oceansites_gdac_series``.

    Per (mooring, variable) at most 30 files are chosen (D > M > P > R, longest
    first, skipping a span already covered); a file read before and unchanged
    since is not read again; at most ``max_files`` files are read per run, the
    best-placed first, and how many remain is logged.

    Returns the run summary, or ``None`` when the OPeNDAP server could not be
    reached (nothing was read, nothing stored was touched).

    ⛔ "Cannot answer" and "answered no" are different. A 5xx, a timeout or a dropped
    connection is counted and skipped and writes NOTHING (not a row, not a read-log
    entry, not an empty series over a stored one): the file stays due. A 4xx for a
    file is the server's answer: it is recorded as ``refused`` with the file's change
    marker and left alone until the GDAC republishes the file. A run in which
    ``_ABORT_AFTER_UNAVAILABLE`` files in a row meet an unavailable server stops
    early and says so.
    """
    cap = max_files if max_files is not None else max_files_per_run()
    if not await gdac_reachable():
        log.warning("OceanSITES history series: OPeNDAP server unreachable — nothing read, "
                    "stored series untouched")
        return None

    async with db.pool.acquire() as conn:
        cands = [dict(r) for r in await conn.fetch(
            """SELECT sf.station_ref, f.file, f.data_mode, f.start_time, f.end_time, f.parameters,
                      f.size_bytes, f.gdac_update_date, f.date_update
                 FROM oceansites_station_files sf
                 JOIN oceansites_gdac_files f USING (file)
                WHERE f.source = 'gdac' AND f.parameters && $1::text[]""",
            sorted(dap.HISTORY_STANDARD_NAMES))]
        fetched = {r["file"]: dict(r) for r in await conn.fetch(
            "SELECT file, outcome, change_marker, standard_names FROM oceansites_gdac_fetched")}
    plan = await asyncio.to_thread(dap.plan_run, cands, fetched, cap)
    info = {c["file"]: c for c in cands}

    summary = {"selected": plan["selected"], "needed": plan["needed"], "todo": len(plan["todo"]),
               "remaining": plan["remaining"], "ok": 0, "empty": 0, "refused": 0, "failed": 0,
               "failed_unavailable": 0, "aborted": False, "series_rows": 0, "requests": 0,
               "packed_skipped": 0,
               "seconds": 0.0}
    t0 = time.monotonic()
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=dap.HTTP_TIMEOUT)
    sem = asyncio.Semaphore(_CONCURRENCY)
    state = {"unavailable_run": 0}

    async def one(file: str, names: set[str]) -> None:
        async with sem:
            if summary["aborted"]:
                return
            row = info[file]
            marker = dap.change_marker(row)
            try:
                res = await dap.fetch_file_series(client, file, names)
            except dap.UnsupportedFile as exc:
                log.debug("OceanSITES history: %s has nothing sampleable (%s)", file, exc)
                summary["packed_skipped"] += len(exc.packed)
                await _store_file(file, names, marker, None, None, fetched.get(file), "empty", str(exc)[:200])
                summary["empty"] += 1
                state["unavailable_run"] = 0
                return
            except dap.OpendapError as exc:
                if exc.kind == "rejected":
                    # A 4xx is the server's settled answer for this file/constraint: record it
                    # (with the marker) so it is not asked again until the file is republished.
                    log.info("OceanSITES history: %s refused (%s)", file, exc)
                    await _store_file(file, names, marker, None, None, fetched.get(file),
                                      "refused", str(exc)[:200])
                    summary["refused"] += 1
                    state["unavailable_run"] = 0
                    return
                # unavailable (5xx / timeout / connection): transient, says nothing about the
                # file -> counted, NEVER recorded, the file stays due.
                summary["failed"] += 1
                summary["failed_unavailable"] += 1
                state["unavailable_run"] += 1
                if state["unavailable_run"] >= _ABORT_AFTER_UNAVAILABLE:
                    summary["aborted"] = True
                log.info("OceanSITES history: %s skipped (%s)", file, exc)
                return
            except Exception:  # a parser surprise on one file must not end the run
                summary["failed"] += 1
                log.exception("OceanSITES history: %s could not be decoded — skipped", file)
                return
            state["unavailable_run"] = 0
            packed = [v for v, why in res.skipped if why == dap.PACKED_REASON]
            summary["packed_skipped"] += len(packed)
            note = ("unsupported packed variables left out: " + ", ".join(packed))[:200] if packed else None
            await _store_file(file, names, marker, row.get("gdac_update_date"), res, fetched.get(file),
                              "ok", note)
            summary["ok"] += 1
            summary["series_rows"] += len(res.series)
            summary["requests"] += res.requests

    try:
        outcomes = await asyncio.gather(*(one(f, names) for f, names in plan["todo"]),
                                        return_exceptions=True)
        for o in outcomes:  # a database error on one file: counted, the siblings carry on
            if isinstance(o, BaseException):
                summary["failed"] += 1
                log.error("OceanSITES history: storing a file failed: %r", o)
    finally:
        if own_client:
            await client.aclose()
    summary["seconds"] = round(time.monotonic() - t0, 1)
    log.info(
        "OceanSITES history series: %d files selected, %d needed reading, %d attempted "
        "(%d ok, %d with nothing sampleable, %d refused by the server, %d failed of which %d server-unavailable%s), "
        "%d series rows, %d requests in %.0f s; %d packed variables left out (scale_factor/add_offset "
        "unsupported); %d files remain for later runs",
        summary["selected"], summary["needed"], summary["todo"], summary["ok"],
        summary["empty"], summary["refused"], summary["failed"], summary["failed_unavailable"],
        ", RUN ABORTED: server kept failing" if summary["aborted"] else "",
        summary["series_rows"], summary["requests"], summary["seconds"], summary["packed_skipped"],
        summary["remaining"],
    )
    return summary


# ── Davis Strait (NSF Arctic Data Center): catalogue + series in one pass ──

_ADC_FILE_UPSERT_SQL = """
    INSERT INTO oceansites_gdac_files
        (file, site_dir, platform_code, data_mode, start_time, end_time,
         lat, lon, position_source, min_depth, max_depth, parameters, size_bytes,
         gdac_update_date, source, landing_url, seen_at)
    VALUES ($1,$2,$3,NULL,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15, NOW())
    ON CONFLICT (file) DO UPDATE SET
        site_dir = EXCLUDED.site_dir, platform_code = EXCLUDED.platform_code,
        start_time = EXCLUDED.start_time, end_time = EXCLUDED.end_time,
        lat = EXCLUDED.lat, lon = EXCLUDED.lon, position_source = EXCLUDED.position_source,
        min_depth = EXCLUDED.min_depth, max_depth = EXCLUDED.max_depth,
        parameters = EXCLUDED.parameters, size_bytes = EXCLUDED.size_bytes,
        gdac_update_date = EXCLUDED.gdac_update_date, source = EXCLUDED.source,
        landing_url = EXCLUDED.landing_url, seen_at = NOW()
"""


def _adc_stamp(value: str | None) -> datetime | None:
    """The Solr ``dateModified`` (``2024-02-23T00:21:07.863Z``) as an aware datetime."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


async def _store_adc_file(entry: dict, parsed: "adc.ParsedFile", marker: str) -> None:
    """One ADC file, one transaction: its catalogue row, its series and its read-log row.

    A file is parsed whole, so its stored series are REPLACED (all variables): a
    republished file that no longer yields a level must not leave the old rows behind.
    An unreadable or unplaceable file never reaches here (see ``refresh_adc``).
    """
    key = entry["key"]
    names = sorted({r.standard_name for r in parsed.series})
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                _ADC_FILE_UPSERT_SQL, key, key.rsplit("/", 1)[0], parsed.mooring, parsed.start,
                parsed.end, parsed.lat, parsed.lon, "file" if parsed.lat is not None else None,
                parsed.min_depth, parsed.max_depth, parsed.parameters, entry.get("size"),
                _adc_stamp(entry.get("date_modified")), adc.SOURCE, adc.LANDING_URL,
            )
            await conn.execute("DELETE FROM oceansites_gdac_series WHERE file = $1", key)
            for r in parsed.series:
                await conn.execute(
                    _SERIES_UPSERT_SQL, key, r.variable, r.depth_index, r.depth_m, r.units,
                    r.long_name, r.standard_name, r.n_total, r.stride, r.times, r.vals, r.qc,
                    r.first_time, r.last_time, _adc_stamp(entry.get("date_modified")),
                )
            await conn.execute(
                _FETCHED_UPSERT_SQL, key, "ok" if parsed.series else "empty",
                None if parsed.series else "read fine, no sampleable variable", marker,
                names, len(parsed.series), adc.CITATION,
            )


async def _settle_adc_file(entry: dict, marker: str, outcome: str, detail: str) -> None:
    """Record a deterministic "nothing to read" (no row for the file, no series touched)."""
    async with db.pool.acquire() as conn:
        await conn.execute(_FETCHED_UPSERT_SQL, entry["key"], outcome, detail[:200], marker, [], 0, None)


async def refresh_adc(client: httpx.AsyncClient | None = None, max_files: int | None = None) -> dict | None:
    """Catalogue and sample the Davis Strait files of the NSF Arctic Data Center.

    Lists the dataset (DataONE Solr), keeps the files that can matter (an instrument we
    read, a mooring that has a ``DS_<mooring>`` row in the register), skips the ones read
    before and unchanged (their MD5 is the change marker), downloads the rest ONCE
    (bounded concurrency, size cap, MD5 and size checked against the index) and stores
    catalogue row + strided series + read-log row per file in one transaction.

    Returns the run summary, or ``None`` when the ADC could not be asked (nothing was
    read, nothing stored was touched).

    ⛔ "Cannot answer" and "answered no" are different, exactly as for the GDAC. A 5xx, a
    timeout, a truncated or corrupt download counts as ``failed_unavailable`` and writes
    NOTHING: the file stays due. A 4xx, a file over the size cap, a file that is not a
    netCDF we can place, or one whose ``mooring_number`` contradicts its name is a settled
    answer: recorded with its change marker and left alone until the ADC republishes it.
    An unexpected exception on one file is counted and does not end the run.
    """
    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=adc.HTTP_TIMEOUT)
    try:
        entries = await adc.fetch_listing(client)
        if entries is None:
            return None
        async with db.pool.acquire() as conn:
            moorings = {m for r in await conn.fetch(
                "SELECT name FROM oceansites_stations WHERE name IS NOT NULL "
                "UNION SELECT name FROM oceansites_deployments WHERE name IS NOT NULL")
                for m in [adc.station_mooring(r["name"])] if m}
            fetched = {r["file"]: dict(r) for r in await conn.fetch(
                "SELECT file, outcome, change_marker FROM oceansites_gdac_fetched WHERE file LIKE $1",
                adc.KEY_PREFIX + "%")}
        read = [e for e in entries if adc.in_scope(e)]
        relevant = [e for e in read if adc._norm(e["mooring"]) in moorings]
        due = [e for e in relevant
               if fetched.get(e["key"], {}).get("change_marker") != adc.change_marker(e)]
        cap = max_files if max_files is not None else max_files_per_run()
        todo = due[:cap]
        summary = {"listed": len(entries), "not_read_instrument": len(entries) - len(read),
                   "no_register_row": len(read) - len(relevant), "relevant": len(relevant),
                   "due": len(due), "attempted": len(todo), "remaining": len(due) - len(todo),
                   "ok": 0, "empty": 0, "refused": 0, "failed": 0, "failed_unavailable": 0,
                   "aborted": False, "series_rows": 0, "bytes": 0, "seconds": 0.0}
        t0 = time.monotonic()
        sem = asyncio.Semaphore(adc.CONCURRENCY)
        parse_lock = asyncio.Lock()  # downloads overlap; the HDF5 library is not thread-safe, so parses do not
        state = {"unavailable_run": 0}

        async def one(entry: dict) -> None:
            async with sem:
                if summary["aborted"]:
                    return
                marker = adc.change_marker(entry)
                try:
                    body = await adc.download(client, entry)
                except adc.AdcError as exc:
                    if exc.kind == "rejected":
                        log.info("ADC Davis: %s refused (%s)", entry["file_name"], exc)
                        await _settle_adc_file(entry, marker, "refused", str(exc))
                        summary["refused"] += 1
                        state["unavailable_run"] = 0
                        return
                    summary["failed"] += 1
                    summary["failed_unavailable"] += 1
                    state["unavailable_run"] += 1
                    if state["unavailable_run"] >= adc.ABORT_AFTER_UNAVAILABLE:
                        summary["aborted"] = True
                    log.info("ADC Davis: %s skipped (%s)", entry["file_name"], exc)
                    return
                state["unavailable_run"] = 0
                summary["bytes"] += len(body)
                try:
                    async with parse_lock:
                        parsed = await asyncio.to_thread(
                            adc.parse_file, body, entry["mooring"], entry.get("depth"))
                except adc.MooringMismatch as exc:
                    # The name and the file disagree about which mooring this is (or nothing
                    # in the file names it): say so and do not guess. Precision over recall.
                    await _settle_adc_file(entry, marker, "refused", str(exc))
                    summary["refused"] += 1
                    return
                except dap.UnsupportedFile as exc:
                    await _settle_adc_file(entry, marker, "empty", str(exc))
                    summary["empty"] += 1
                    return
                except Exception:  # a parser surprise on one file must not end the run
                    summary["failed"] += 1
                    log.exception("ADC Davis: %s could not be decoded — skipped", entry["file_name"])
                    return
                await _store_adc_file(entry, parsed, marker)
                summary["ok" if parsed.series else "empty"] += 1
                summary["series_rows"] += len(parsed.series)

        outcomes = await asyncio.gather(*(one(e) for e in todo), return_exceptions=True)
        for o in outcomes:  # a database error on one file: counted, the siblings carry on
            if isinstance(o, BaseException):
                summary["failed"] += 1
                log.error("ADC Davis: storing a file failed: %r", o)
        summary["seconds"] = round(time.monotonic() - t0, 1)
        log.info(
            "ADC Davis: %d objects listed (%d not read: ADCP/unknown name, %d for moorings with no register row), "
            "%d relevant, %d due, %d attempted: %d ok, %d with nothing sampleable, %d refused, %d failed of which "
            "%d server-unavailable%s; %d series rows, %.1f MB in %.0f s; %d remain for later runs",
            summary["listed"], summary["not_read_instrument"], summary["no_register_row"],
            summary["relevant"], summary["due"], summary["attempted"], summary["ok"], summary["empty"],
            summary["refused"], summary["failed"], summary["failed_unavailable"],
            ", RUN ABORTED: server kept failing" if summary["aborted"] else "",
            summary["series_rows"], summary["bytes"] / 1e6, summary["seconds"], summary["remaining"],
        )
        return summary
    finally:
        if own:
            await client.aclose()


async def sync_oceansites_history() -> int:
    """Weekly: refresh the GDAC catalogue and the Davis Strait (ADC) files, then relink
    moorings to files.

    Returns the number of moorings linked to at least one file of either source. Every
    return path leaves a ``sync_log`` trace; the unreachable ones use
    ``log_sync_skipped`` so a dead server does not stamp the layer as freshly
    synced (``log_sync`` sets ``last_synced_at``).
    """
    n = await refresh_catalogue()
    # The ADC step is independent of the GDAC one: either archive being down must not
    # stop the other from being read, and neither may blank what the other stored.
    try:
        adc_run = await refresh_adc()
    except Exception:
        log.exception("OceanSITES history: ADC Davis step failed — its stored rows stand")
        adc_run = None
    finally:
        drop_history_caches()  # ADC series rows may have changed even when the step then failed
    if n is None and adc_run is None:
        await _log_sync_skipped(
            SYNC_SOURCE,
            "GDAC index and ADC listing not fetched (unreachable or unusable) — stored catalogue and links untouched",
        )
        return 0

    summary = await rebuild_links()
    if summary is None:  # cannot happen right after a successful refresh; kept honest
        await _log_sync_skipped(SYNC_SOURCE, "catalogue holds no matchable files — links untouched")
        return 0
    # The links and the history_* columns on the map's stations are committed:
    # the map payload and every cached history response are stale from here on.
    drop_history_caches()

    # The catalogue and links above are committed. A failure below cannot undo
    # them, and must not turn this run into a failed one: the series step reports
    # for itself (fetch_series logs; None = server unreachable, stored rows untouched).
    try:
        await fetch_series()
    except Exception:
        log.exception("OceanSITES history: series step failed — catalogue and links stand")
    finally:
        drop_history_caches()  # series rows may have changed even when the step then failed

    log.info(
        "OceanSITES history: %d GDAC files catalogued, %d moorings linked to %d files "
        "(%d links; %d moorings / %d links from the ADC Davis Strait dataset), "
        "%d station/file pairs within %.0f km rejected on name",
        n or 0, summary["linked_stations"], summary["linked_files"], summary["links"],
        summary["adc_linked_stations"], summary["adc_links"],
        summary["rejected_nearby"], ingest.MAX_LINK_KM,
    )
    await _log_sync(SYNC_SOURCE, summary["linked_stations"], n or 0)
    return summary["linked_stations"]


# ── GET /v1/oceansites/{ref}/history ───────────────────────────────────────

OCEANSITES_CITATION = (
    "These data were collected and made freely available by the international "
    "OceanSITES project and the national programs that contribute to it."
)
OPENDAP_HTML = "https://tds0.ifremer.fr/thredds/dodsC/CORIOLIS-OCEANSITES-GDAC-OBS/{file}.html"
MAX_POINTS = 600                 # per merged series, so the payload stays small
WITHHELD_QC = frozenset({3, 4, 9})   # bad-but-correctable, bad, missing (OceanSITES flags)

# ── Gross range test (applied AFTER the QC flag, counted apart as `range_withheld`) ──
# The stored series are pass-through and some values the source did NOT flag are
# physically impossible. Measured on the first production sync (2026-10-01, 21,456
# series, ~2.2M points, ~3.5k of them outside any plausible range): ALOHA UCUR/VCUR
# ±12 m/s (no QC); PAP PSAL exactly 0 with QC 1; CCE1/CCE2 UCUR -39.088 and VCUR
# -24.892 repeated 153 times (no QC); PYLOS/E1M3A TEMP/PSAL -999.99 and 99.999
# (QC 0/1); CORC-GIZO TEMP 105 degC; LINE-W TEMP -17.8 (QC 1). One such point flattens
# a whole sparkline. The stored data are NOT touched: the endpoint withholds and counts.
#
# Limits are the Argo Quality Control Manual's global range test (Test 6): temperature
# -2.5 .. 40.0 degC, salinity 2.0 .. 41.0 (PSS-78). Currents have no Argo equivalent; a
# 5 m/s ceiling (500 cm/s) lies above the strongest open-ocean currents (Gulf Stream /
# Agulhas cores reach ~2.5 m/s, tidal jets in straits a little more), so anything past
# it is an instrument or processing artefact, not an event.
# ⛔ A test applies only when the series DECLARES a unit of the family the limits are
# written in; any other quantity, or an unknown unit, is never tested (a unit is never
# guessed, so a "1" on temperature or a bare "m" on a current is left alone).
_CELSIUS = frozenset({"degree_Celsius", "degrees_Celsius", "degree_C", "deg_C", "celsius", "Celsius"})
_SALINITY_UNITS = frozenset({"1", "psu", "PSU", "1e-3", "0.001"})
_MS = frozenset({"m/s", "m s-1", "meters_per_second", "m.s-1"})
_CMS = frozenset({"cm/s", "cm s-1", "centimeters_per_second"})
RANGE_TESTS: dict[str, tuple[tuple[frozenset, float, float], ...]] = {
    "sea_water_temperature":         ((_CELSIUS, -2.5, 40.0),),
    "sea_surface_temperature":       ((_CELSIUS, -2.5, 40.0),),
    "sea_water_practical_salinity":  ((_SALINITY_UNITS, 2.0, 41.0),),
    "sea_water_salinity":            ((_SALINITY_UNITS, 2.0, 41.0),),
    "eastward_sea_water_velocity":   ((_MS, -5.0, 5.0), (_CMS, -500.0, 500.0)),
    "northward_sea_water_velocity":  ((_MS, -5.0, 5.0), (_CMS, -500.0, 500.0)),
}


def _range_limits(standard_name: str | None, units: str | None) -> tuple[float, float] | None:
    for fam, lo, hi in RANGE_TESTS.get(standard_name or "", ()):
        if units is not None and units.strip() in fam:
            return lo, hi
    return None
_MODE_ORDER = {"D": 0, "M": 1, "P": 2, "R": 3}
_CACHE_PREFIX = "oceansites-history:"
DEFAULT_MAX_POINTS = 200       # per series in the default (3 depths per quantity) response
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def clear_caches() -> None:
    """/admin/cache/clear: drop this domain's cached responses. The shared store
    is cleared wholesale by the admin sweep anyway (see response_cache)."""
    _cache.clear()


def drop_history_caches() -> None:
    """Forget the cached history responses and the map payload that carries the
    ``history_*`` summary. Called when the history sync has written."""
    for key in [k for k in _cache if k.startswith(_CACHE_PREFIX)]:
        _cache.pop(key, None)
    from domains import sensors  # late: sensors must not need this module to import

    sensors.clear_oceansites_map_cache()


def _iso(t: datetime | None) -> str | None:
    if t is None:
        return None
    return t.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _depth_bucket(depth_m: float | None) -> int | None:
    """Whole metres, halves up. Python's round() would send 0.5 to 0 and 1.5 to 2."""
    if depth_m is None or not math.isfinite(depth_m):
        return None
    return math.floor(depth_m + 0.5)


def _mode_rank(mode: str | None) -> int:
    return _MODE_ORDER.get(mode or "", 9)


def _thin(pts: list, cap: int) -> tuple[list, int]:
    """At most ``cap`` points, always including the first and the last real one.

    Keeps every m-th point from the first and appends the last when the stepping
    misses it; m is the smallest step that fits. Returns (points, m); m = 1 when
    nothing was dropped.
    """
    n = len(pts)
    if n <= cap:
        return pts, 1
    m = math.ceil(n / cap)
    while True:
        keep = pts[::m]
        if keep[-1] is not pts[-1]:
            keep = keep + [pts[-1]]
        if len(keep) <= cap:
            return keep, m
        m += 1


def _pick_depths(depths: list) -> set:
    """Shallowest, deepest and the one closest to the median depth (fewer if fewer exist).

    ``None`` (a file that declares no depth) is not a depth: it never takes a slot from
    real depths and is picked only when no numeric depth exists at all (``all_depths``
    still returns it).
    """
    real = sorted(d for d in depths if d is not None)
    has_none = any(d is None for d in depths)
    if not real:
        return {None} if has_none else set()
    if len(real) <= 3:
        chosen = set(real)
    else:
        chosen = {real[0], real[-1]}
        mid = real[len(real) // 2] if len(real) % 2 else (real[len(real) // 2 - 1] + real[len(real) // 2]) / 2
        rest = [d for d in real if d not in chosen]
        chosen.add(min(rest, key=lambda d: (abs(d - mid), d)))
    return chosen


def merge_series(rows: list[dict], *, max_points: int = MAX_POINTS,
                 pick_depths: bool = False) -> list[dict]:
    """Merge stored series rows into one series per (standard_name, depth, units).

    A *row* is one (file, variable, depth level) of ``oceansites_gdac_series``.
    Rows of the same quantity at the same whole-metre depth from different files
    are joined and sorted by time.

    * ``units`` belongs to the key: a unit is never converted or reconciled, so
      two spellings stay two series rather than one with a guessed unit.
    * Two samples with the identical timestamp are one instant: the file with the
      better ``data_mode`` (D > M > P > R) wins, then the later GDAC update stamp,
      then the file name; the others are counted in ``duplicates_dropped``. This is
      decided on the raw sample, before QC, so a series never mixes two sources
      at one instant.
    * A NULL value is a fill value the file declared (or a non-finite one): it
      is dropped and counted in ``missing``. A value whose QC flag is 3, 4 or 9
      is dropped and counted in ``qc_withheld``. The two counts are never
      added together — a missing sample is not a rejected one.
    * A value that survives those two but lies outside the physical range of its
      quantity (``RANGE_TESTS``, only where the declared unit is known) is dropped and
      counted in ``range_withheld`` — a third, separate count.
    * ``n_total_measurements`` is counted after that resolution (see the comment at
      the field): a measurement in two overlapping files is counted once.
    * Points are real every-k-th samples, never averages. Above ``max_points``
      every m-th point is kept (the first and the last real point always are)
      and ``stride_max`` carries the extra factor.
    * ``pick_depths``: per (standard_name, units) only the shallowest, the deepest
      and the depth nearest the median are returned; every series carries
      ``depths_available``, all its quantity's depths, shallow to deep.
    """
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        key = (r["standard_name"] or r["variable"], _depth_bucket(r["depth_m"]), r["units"])
        groups.setdefault(key, []).append(r)

    by_quantity: dict[tuple, list] = {}
    for std, depth, units in groups:
        by_quantity.setdefault((std, units), []).append(depth)
    shown: dict[tuple, set] = {
        q: (_pick_depths(ds) if pick_depths else set(ds)) for q, ds in by_quantity.items()
    }

    out = []
    for (std, depth, units), grp in groups.items():
        if depth not in shown[(std, units)]:
            continue
        # one sample per instant, the best source first
        best: dict[datetime, tuple] = {}
        dropped = 0
        dropped_weight = 0      # source measurements the losing samples stood for
        for r in grp:
            rank = (_mode_rank(r.get("data_mode")), -(r.get("gdac_update_date") or _EPOCH).timestamp(),
                    r["file"])
            qcs = r["qc"]
            for i, (t, v) in enumerate(zip(r["times"], r["vals"])):
                q = qcs[i] if i < len(qcs) else None
                cur = best.get(t)
                if cur is None:
                    best[t] = (rank, v, q, r["stride"])
                    continue
                dropped += 1
                if rank < cur[0]:
                    dropped_weight += cur[3]
                    best[t] = (rank, v, q, r["stride"])
                else:
                    dropped_weight += r["stride"]
        pts: list[list] = []
        missing = withheld = out_of_range = 0
        limits = _range_limits(std, units)
        for t in sorted(best):
            _, v, q, _ = best[t]
            if v is None or not math.isfinite(v):
                missing += 1
            elif q is not None and q in WITHHELD_QC:
                withheld += 1
            elif limits is not None and not (limits[0] <= v <= limits[1]):
                out_of_range += 1
            else:
                pts.append([t, v])
        pts, extra = _thin(pts, max_points)
        first = grp[0]
        out.append({
            "variable": first["variable"],
            "standard_name": std,
            "long_name": first["long_name"],
            "units": units,
            "depth_m": depth,
            "depths_available": sorted(d for d in by_quantity[(std, units)] if d is not None),
            "points": [[_iso(t), v] for t, v in pts],
            # Measurements in the source files AFTER the duplicate instants are resolved:
            # each file's total, less what the losing samples stood for (one sample = its
            # file's stride in measurements). Exact when the overlapping files were read at
            # stride 1; with a larger stride an overlap is only seen where sampled instants
            # coincide, so it is then a ceiling. Never below the points actually held.
            "n_total_measurements": max(sum(r["n_total"] for r in grp) - dropped_weight, len(best)),
            "stride_max": max(r["stride"] for r in grp) * extra,
            "qc_withheld": withheld,
            "range_withheld": out_of_range,
            "missing": missing,
            "duplicates_dropped": dropped,
        })
    out.sort(key=lambda s: (s["standard_name"], s["depth_m"] is None, s["depth_m"] or 0, s["units"] or ""))
    return out


async def _build_history(ref: str, all_depths: bool = False) -> dict | None:
    async with db.pool.acquire() as conn:
        st = await conn.fetchrow(
            "SELECT history_start, history_end, history_files FROM oceansites_stations WHERE ref = $1",
            ref,
        )
        if st is None:
            return None
        # Files the plotted series were read from, best mode first.
        files = await conn.fetch(
            """SELECT f.file, f.data_mode, f.start_time, f.end_time, f.min_depth, f.max_depth,
                      f.source, f.landing_url
               FROM oceansites_gdac_files f
               WHERE f.file IN (SELECT l.file FROM oceansites_station_files l WHERE l.station_ref = $1)
                 AND EXISTS (SELECT 1 FROM oceansites_gdac_series s WHERE s.file = f.file)
               ORDER BY f.start_time NULLS LAST, f.file""",
            ref,
        )
        rows = await conn.fetch(
            """SELECT s.file, s.variable, s.depth_index, s.depth_m, s.units, s.long_name,
                      s.standard_name, s.n_total, s.stride, s.times, s.vals, s.qc,
                      s.gdac_update_date, f.data_mode
               FROM oceansites_gdac_series s
               LEFT JOIN oceansites_gdac_files f ON f.file = s.file
               WHERE s.file IN (SELECT l.file FROM oceansites_station_files l WHERE l.station_ref = $1)
               ORDER BY s.file, s.variable, s.depth_index""",
            ref,
        )
        cites = await conn.fetch(
            """SELECT DISTINCT d.citation FROM oceansites_gdac_fetched d
               WHERE d.citation IS NOT NULL AND d.citation <> ''
                 AND d.file IN (SELECT s.file FROM oceansites_gdac_series s
                                WHERE s.file IN (SELECT l.file FROM oceansites_station_files l
                                                 WHERE l.station_ref = $1))
               ORDER BY d.citation""",
            ref,
        )
    # CPU-bound over up to ~350k samples (TAO): off the event loop, like the index parse.
    series = await asyncio.to_thread(
        merge_series,
        [dict(r) for r in rows],
        max_points=MAX_POINTS if all_depths else DEFAULT_MAX_POINTS,
        pick_depths=not all_depths,
    )
    def _file_entry(f) -> dict:
        if f["source"] == adc.SOURCE:
            # a plain download at the Arctic Data Center: the DOI is the landing page,
            # there is no OPeNDAP endpoint
            url, opendap = f["landing_url"] or adc.LANDING_URL, None
        else:
            url = opendap = OPENDAP_HTML.format(file=f["file"])
        return {
            "file": f["file"],
            "source": f["source"],
            "data_mode": f["data_mode"],
            "start": _iso(f["start_time"]),
            "end": _iso(f["end_time"]),
            "min_depth": f["min_depth"],
            "max_depth": f["max_depth"],
            "url": url,
            "url_opendap_html": opendap,
        }

    file_list = sorted(
        (_file_entry(f) for f in files),
        key=lambda f: (f["start"] or "", _MODE_ORDER.get(f["data_mode"], 9), f["file"]),
    )
    # Which archives the plotted series came from. The OceanSITES data-policy citation
    # leads when a GDAC file contributes (or when nothing does: the empty response keeps
    # its shape); a mooring whose record is ONLY from the Arctic Data Center is not
    # credited to OceanSITES. The ADC dataset citation is added whenever an ADC file
    # contributes, then the files' own.
    sources = {f["source"] for f in file_list}
    lead: list[str] = []
    if adc.SOURCE in sources:
        lead.append(adc.CITATION)
    if sources != {adc.SOURCE}:
        lead.insert(0, OCEANSITES_CITATION)
    citations = lead + [
        c["citation"].strip() for c in cites
        if c["citation"].strip() not in lead
    ]
    return {
        "ref": ref,
        "start": _iso(st["history_start"]),
        "end": _iso(st["history_end"]),
        "n_catalogue_files": st["history_files"] or 0,   # every catalogued file (either source) linked to the mooring
        "n_files_read": len(file_list),                  # the files `series` were read from
        "citation": citations[0],
        "citations": citations,
        "files": file_list,
        "series": series,
    }


@router.get("/v1/oceansites/{ref}/history", dependencies=[Depends(get_api_key)])
async def get_oceansites_history(
    ref: str,
    all_depths: bool = Query(
        False,
        description="true: every depth of every quantity at up to 600 points per series. "
                    "Default: the shallowest, deepest and median-depth series per quantity "
                    "at up to 200 points (`depths_available` lists them all).",
    ),
):
    """Historical record of one OceanSITES mooring: the GDAC, or for the Davis Strait
    moorings (`DS_*`) the NSF Arctic Data Center (CC0, doi:10.18739/A2416T169).

    Each entry of `files` carries its `source` (`gdac` | `adc_davis`) and a `url`
    (the OPeNDAP page for a GDAC file, the DOI for an ADC file). Series are every-k-th
    real measurements of the mooring's files, merged
    across files by standard name and depth, NOT averages. Values flagged bad
    (QC 3, 4, 9) are withheld and counted in `qc_withheld`; fill values are
    counted in `missing`; unflagged values outside the physical range of a
    quantity with a known unit are counted in `range_withheld`. By default each quantity returns its shallowest, deepest
    and median-depth series at up to 200 points (`depths_available` lists all
    depths); `all_depths=true` returns every depth at up to 600 points. 404 = no such station; 200 with empty lists = a known
    mooring with no stored history.
    """
    key = f"{_CACHE_PREFIX}{ref}:{int(all_depths)}"
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_TTL:
        return Response(content=hit[1], media_type="application/json")
    body = await _build_history(ref, all_depths)
    if body is None:
        # 404 = "no such station"; a known mooring without history is a 200 below.
        raise HTTPException(status_code=404, detail=f"No OceanSITES station '{ref}'")
    # allow_nan=False: a NaN must raise (500), never ship as a token no browser parses.
    data = json.dumps(body, allow_nan=False).encode()
    _cache[key] = (time.monotonic(), data)
    return Response(content=data, media_type="application/json")
