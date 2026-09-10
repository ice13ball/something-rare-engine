# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""NOAA Passive Acoustic Archive — generic ingest for 12 NOAA-archive programs.

This module is the Phase 4 bulk expansion of the acoustic_stations layer.
All 12 programs use the same public Google Cloud Storage bucket
`noaa-passive-bioacoustic` and one of two metadata-JSON schemas. The
existing NRS / SanctSound / NEFSC modules each cover a single program; this
module is a single generic walker driven by a `PROGRAMS` config dict.

Programs shipped (12):
- pifsc        — NOAA Pacific Islands FSC (HARPs around Hawaii, Cross, American Samoa)
- sefsc        — NOAA Southeast FSC (Gulf of Mexico HARPs)
- onms         — NOAA Office of National Marine Sanctuaries (sanctuary uploads
                 separate from the older sanctsound/ prefix)
- adeon        — Atlantic Deepwater Ecosystem Observation Network (AMAR landers)
- boem         — Bureau of Ocean Energy Management (offshore wind PAM,
                 Maryland/Virginia/Atlantic wind areas, Gulf of Mexico)
- aeon         — Atlantic Ecosystem Observation Network (AMAR landers)
- navy         — US Navy (MBARC LMR, USWTR)
- nps          — National Park Service (Glacier Bay cabled hydrophone)
- jasco        — JASCO Applied Sciences (ESRF Atlantic Canada PAM)
- fram         — Alfred Wegener Institute FRAM (Fram Strait, North Atlantic Arctic)
- coastal_studies_institute — UNC Coastal Studies Institute (NCROEP, Hatteras)
- ioos         — IOOS ESONS (estuarine soundscape, South Carolina)

Programs explicitly SKIPPED (bench 2026-05-11):
- swfsc        — all deployments are Drifters / Sonobuoys → no static lat/lon
                 in the metadata JSON (0/33 had DEPLOY_LAT). Mobile-platform
                 ingest is a separate Phase-5 problem.
- afsc         — single sonobuoy deployment, no fixed coords.

Two JSON schemas observed in the bucket:

**Schema A — "nested" (NRS/SanctSound/NEFSC style):** the canonical layout used
by 10 of the 12 programs (pifsc, sefsc, onms, boem, navy, nps, fram,
coastal_studies_institute, ioos). Coords sit in `DEPLOYMENT.DEPLOY_LAT`,
`DEPLOYMENT.DEPLOY_LON`, `DEPLOYMENT.DEPLOY_INSTRUMENT_DEPTH`, with
`DEPLOYMENT.DEPLOYMENT_TIME` and `DEPLOYMENT.RECOVERY_TIME` for the date span.

**Schema B — "flat-ADEON" style:** ADEON + AEON + JASCO. The DEPLOY_LAT,
DEPLOY_LON, START_DATE, END_DATE keys sit at the top level. Depths come from
`MIN_SENSOR_DEPTH` / `MAX_SENSOR_DEPTH`. Dates are in `'DD-Mon-YYYY'` format
(`'05-Nov-2018'`).

`_extract_record()` handles both schemas via try-A-then-B logic. Aggregation
to one row per site is done in `fetch_program_stations()`.

results that drove the per-program config dict.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from typing import Any, Callable

import httpx
from ingestion.http_retry import get_with_retry

log = logging.getLogger(__name__)

_BUCKET = "noaa-passive-bioacoustic"
_GCS_LIST = f"https://storage.googleapis.com/storage/v1/b/{_BUCKET}/o"
_GCS_OBJECT = f"https://storage.googleapis.com/{_BUCKET}"
_TIMEOUT = httpx.Timeout(60.0, connect=20.0)


# Per-program config. `operator` and `portal_url` are constants surfaced in
# every row. `prefix` is the GCS prefix to walk; `display` is the panel label.
# `min_depth_ok` lets us drop suspicious near-surface depths from sources that
# include shoreline ESONS-style deployments (depths < 0.5 m mean "intertidal"
# and are kept as-is — not filtered, just noted).
PROGRAMS: dict[str, dict[str, Any]] = {
    "pifsc": {
        "display":   "NOAA PIFSC",
        "operator":  "NOAA Pacific Islands Fisheries Science Center",
        "prefix":    "pifsc/audio/",
        "portal":    "https://www.fisheries.noaa.gov/about/pacific-islands-fisheries-science-center",
        "skip_mobile_platforms": True,
    },
    "sefsc": {
        "display":   "NOAA SEFSC",
        "operator":  "NOAA Southeast Fisheries Science Center",
        "prefix":    "sefsc/audio/",
        "portal":    "https://www.fisheries.noaa.gov/about/southeast-fisheries-science-center",
        "skip_mobile_platforms": True,
    },
    "onms": {
        "display":   "NOAA ONMS",
        "operator":  "NOAA Office of National Marine Sanctuaries",
        "prefix":    "onms/audio/",
        "portal":    "https://sanctuaries.noaa.gov/science/monitoring/sound/",
        "skip_mobile_platforms": True,
    },
    "adeon": {
        "display":   "ADEON",
        "operator":  "ADEON — Atlantic Deepwater Ecosystem Observation Network",
        "prefix":    "adeon/audio/",
        "portal":    "https://adeon.unh.edu/",
        "skip_mobile_platforms": True,
    },
    "boem": {
        "display":   "BOEM",
        "operator":  "Bureau of Ocean Energy Management",
        "prefix":    "boem/audio/",
        "portal":    "https://www.boem.gov/environment/environmental-studies",
        "skip_mobile_platforms": True,
    },
    "aeon": {
        "display":   "AEON",
        "operator":  "AEON — Atlantic Ecosystem Observation Network",
        "prefix":    "aeon/audio/",
        "portal":    "https://www.boem.gov/environment/environmental-studies",
        "skip_mobile_platforms": True,
    },
    "navy": {
        "display":   "US Navy",
        "operator":  "US Navy (MBARC, USWTR)",
        "prefix":    "navy/audio/",
        "portal":    "https://www.navfac.navy.mil/",
        "skip_mobile_platforms": True,
    },
    "nps": {
        "display":   "National Park Service",
        "operator":  "US National Park Service",
        "prefix":    "nps/audio/",
        "portal":    "https://www.nps.gov/subjects/sound/index.htm",
        "skip_mobile_platforms": True,
    },
    "jasco": {
        "display":   "JASCO",
        "operator":  "JASCO Applied Sciences (ESRF — Environmental Studies Research Funds, Canada)",
        "prefix":    "jasco/audio/",
        "portal":    "https://www.jasco.com/",
        "skip_mobile_platforms": True,
    },
    "fram": {
        "display":   "FRAM",
        "operator":  "Alfred Wegener Institute — FRAM Observatory",
        "prefix":    "fram/audio/",
        "portal":    "https://www.awi.de/en/expedition/observatories/ocean-fram.html",
        "skip_mobile_platforms": True,
    },
    "coastal_studies_institute": {
        "display":   "Coastal Studies Institute",
        "operator":  "Coastal Studies Institute (East Carolina University / UNC)",
        "prefix":    "coastal_studies_institute/audio/",
        "portal":    "https://coastalstudiesinstitute.org/",
        "skip_mobile_platforms": True,
    },
    "ioos": {
        "display":   "IOOS ESONS",
        "operator":  "US Integrated Ocean Observing System (ESONS)",
        "prefix":    "ioos/audio/",
        "portal":    "https://ioos.noaa.gov/project/passive-acoustic-monitoring/",
        "skip_mobile_platforms": True,
    },
}

# Platforms we consider mobile / non-positional. When `skip_mobile_platforms`
# is set on a program config, deployments with these PLATFORM_NAME values are
# dropped (they don't have a stable DEPLOY_LAT/LON to place on a map).
_MOBILE_PLATFORMS = {"glider", "drifter", "sonobuoy", "auv", "rov", "ship", "vessel"}


def _safe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


_MONTH_ABBR = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _parse_date(value: Any) -> date | None:
    """Parse ISO ('2018-07-30T00:00:00Z') or ADEON-style ('05-Nov-2018') dates."""
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    # ISO first
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        pass
    # ADEON-style 'DD-Mon-YYYY' (e.g. '05-Nov-2018' or '5-Nov-2018')
    parts = s.split()[0].split("-")
    if len(parts) == 3:
        try:
            dd = int(parts[0])
            mon = _MONTH_ABBR.get(parts[1].lower().strip(".")[:4]) or _MONTH_ABBR.get(parts[1].lower().strip(".")[:3])
            yy = int(parts[2])
            if mon and 1 <= dd <= 31 and 1900 <= yy <= 2100:
                return date(yy, mon, dd)
        except (ValueError, KeyError):
            pass
    return None


def _str_or_none(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


async def _list_all(client: httpx.AsyncClient, prefix: str, delimiter: str | None = "/") -> tuple[list[str], list[dict[str, Any]]]:
    """Walk GCS pagination, returning (prefixes, items). `delimiter=None`
    means recursive — list every object under prefix."""
    prefixes: list[str] = []
    items: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        params: dict[str, str] = {"prefix": prefix, "maxResults": "1000"}
        if delimiter:
            params["delimiter"] = delimiter
        if page_token:
            params["pageToken"] = page_token
        resp = await get_with_retry(client, _GCS_LIST, params=params, label="noaa archive listing")
        resp.raise_for_status()
        data = resp.json()
        prefixes.extend(data.get("prefixes") or [])
        items.extend(data.get("items") or [])
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return prefixes, items


async def _discover_metadata_jsons(client: httpx.AsyncClient, root_prefix: str, max_depth: int = 6) -> list[str]:
    """Hierarchical BFS to find every `metadata/*.json` under `root_prefix`.

    A recursive GCS list (`delimiter=None`) over `{prog}/audio/` paginates
    through hundreds of thousands of `.aif`/`.wav` audio files before hitting
    `metadata/*.json` — minutes per program. Walking the directory hierarchy
    with `delimiter='/'` instead lets us skip audio leaves entirely: we only
    descend into `audio/` to find project/site/deployment folders, then
    flatten each folder's `metadata/` subdir directly.
    """
    out: list[str] = []
    queue: list[tuple[str, int]] = [(root_prefix, 0)]
    while queue:
        cur, depth = queue.pop(0)
        # Look for a metadata/ subdirectory at this level — if present, list
        # only `.json` files in it (these are small; cheap one-page calls).
        meta_subprefix = f"{cur}metadata/"
        try:
            _, meta_items = await _list_all(client, meta_subprefix, delimiter=None)
        except Exception:
            meta_items = []
        leaf_has_meta = False
        for it in meta_items:
            name = it.get("name") or ""
            if _is_metadata_json(name):
                out.append(name)
                leaf_has_meta = True
        if leaf_has_meta:
            # This is a deployment leaf — don't descend further
            continue
        if depth >= max_depth:
            continue
        # Otherwise list direct children with delimiter and queue them
        try:
            subs, _ = await _list_all(client, cur, delimiter="/")
        except Exception:
            subs = []
        for sub in subs:
            tail = sub.rstrip("/").rsplit("/", 1)[-1]
            # Skip well-known non-deployment dirs to keep the walk cheap
            if tail in ("audio", "ancillary", "metadata", "products", "documentation", "supplementary"):
                continue
            queue.append((sub, depth + 1))
    return out


async def _fetch_json(client: httpx.AsyncClient, object_name: str) -> dict[str, Any] | None:
    url = f"{_GCS_OBJECT}/{object_name}"
    try:
        resp = await get_with_retry(client, url, label="noaa archive object")
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        log.debug("acoustic_noaa_archive_ingest: fetch %s failed: %s", url, exc)
        return None


def _is_metadata_json(name: str) -> bool:
    """A metadata JSON is `*.json` under a `/metadata/` directory, not an
    index (`*_deployments*.json`) and not an ingest sidecar (`*-ingest.json`)."""
    lname = name.lower()
    if not lname.endswith(".json"):
        return False
    if "/metadata/" not in lname:
        return False
    leaf = lname.rsplit("/", 1)[-1]
    if "deployments" in leaf:
        return False
    if leaf.endswith("-ingest.json"):
        return False
    return True


def _extract_record(meta: dict[str, Any], program: str) -> dict[str, Any] | None:
    """Pull station fields from one metadata JSON.

    Tries Schema A (nested DEPLOYMENT.*) first, then Schema B (flat top-level
    DEPLOY_LAT etc.). Returns None if no usable lat/lon found.
    """
    if not isinstance(meta, dict):
        return None

    platform = _str_or_none(meta.get("PLATFORM_NAME"))
    if PROGRAMS[program].get("skip_mobile_platforms") and platform:
        if platform.lower() in _MOBILE_PLATFORMS:
            return None

    instrument = _str_or_none(meta.get("INSTRUMENT_TYPE")) \
              or _str_or_none(meta.get("MODEL")) \
              or platform \
              or "Hydrophone"

    site = _str_or_none(meta.get("SITE"))
    aliases = meta.get("SITE_ALIASES")
    site_alias: str | None = None
    if isinstance(aliases, list):
        for a in aliases:
            v = _str_or_none(a)
            if v:
                site_alias = v
                break

    proj_name_raw = meta.get("PROJECT_NAME")
    if isinstance(proj_name_raw, list) and proj_name_raw:
        project_name = _str_or_none(proj_name_raw[0])
    else:
        project_name = _str_or_none(proj_name_raw)

    sea_area: str | None = None

    lat: float | None = None
    lon: float | None = None
    depth_m: float | None = None
    deploy_start: date | None = None
    deploy_end: date | None = None

    # Schema A — nested DEPLOYMENT
    dep = meta.get("DEPLOYMENT")
    if isinstance(dep, dict):
        lat_raw = dep.get("DEPLOY_LAT") or dep.get("deploy_lat")
        lon_raw = dep.get("DEPLOY_LON") or dep.get("deploy_lon")
        depth_raw = dep.get("DEPLOY_INSTRUMENT_DEPTH") or dep.get("deploy_instrument_depth")
        bottom_raw = dep.get("DEPLOY_BOTTOM_DEPTH") or dep.get("deploy_bottom_depth")
        # NEFSC SBNMS publishes arrays — take first element so we still capture
        # a representative position; the dedicated NEFSC module handles the
        # multi-MARU expansion in detail. (Not expected for the 12 programs
        # we ship here, but defensive.)
        if isinstance(lat_raw, list):
            lat_raw = lat_raw[0] if lat_raw else None
            if isinstance(lon_raw, list):
                lon_raw = lon_raw[0] if lon_raw else None
        lat = _safe_float(lat_raw)
        lon = _safe_float(lon_raw)
        depth_v = _safe_float(depth_raw)
        if depth_v is None:
            depth_v = _safe_float(bottom_raw)
        if depth_v is not None:
            # ⛔ Neither DEPLOY_INSTRUMENT_DEPTH nor DEPLOY_BOTTOM_DEPTH has a
            # public field dictionary we could find for this bucket's metadata
            # JSON (Schema A, shared with NEFSC/NRS/SanctSound). abs() is OUR
            # assumption, not theirs: a genuine height above the seafloor would
            # be silently turned into a depth. Recorded rather than resolved -
            # see docs/methods/data-passthrough.md.
            depth_m = abs(depth_v)
        deploy_start = _parse_date(dep.get("DEPLOYMENT_TIME") or dep.get("deployment_time") or dep.get("AUDIO_START"))
        deploy_end = _parse_date(dep.get("RECOVERY_TIME") or dep.get("recovery_time") or dep.get("AUDIO_END"))
        sea_area = _str_or_none(dep.get("SEA_AREA") or dep.get("sea_area"))

    # Schema B — flat ADEON-style (only used when Schema A didn't find coords)
    if lat is None or lon is None:
        lat = _safe_float(meta.get("DEPLOY_LAT"))
        lon = _safe_float(meta.get("DEPLOY_LON"))
        if depth_m is None:
            d_min = _safe_float(meta.get("MIN_SENSOR_DEPTH"))
            d_max = _safe_float(meta.get("MAX_SENSOR_DEPTH"))
            d_pick = d_min if d_min is not None else d_max
            if d_pick is None:
                d_pick = _safe_float(meta.get("MIN_BOTTOM_DEPTH")) \
                      or _safe_float(meta.get("MAX_BOTTOM_DEPTH"))
            if d_pick is not None:
                # ⛔ None of MIN/MAX_SENSOR_DEPTH or MIN/MAX_BOTTOM_DEPTH (Schema
                # B, flat ADEON-style) has a public field dictionary we could
                # find. abs() is OUR assumption, not a documented source
                # convention: a genuine height above the seafloor would be
                # silently turned into a depth. Recorded rather than resolved -
                # see docs/methods/data-passthrough.md.
                depth_m = abs(d_pick)
        if deploy_start is None:
            deploy_start = _parse_date(meta.get("START_DATE") or meta.get("START_TIME"))
        if deploy_end is None:
            deploy_end = _parse_date(meta.get("END_DATE") or meta.get("END_TIME"))

    if lat is None or lon is None:
        return None
    # Sanity-check the lat/lon bounds. Some flat-schema JSONs publish
    # 0-360 longitudes; normalise.
    if lon > 180:
        lon -= 360
    # NAVY USWTR data publishes a few SoCal sites with the sign dropped on
    # longitude (`DEPLOY_LON = 118.78` instead of `-118.78`). Detected via
    # `SEA_AREA = 'Northern Pacific'` + lon in 100..180 range. Confirmed by
    # cross-checking the SWAL Flip07/Flip08 sites against the published
    # CalCOFI SoCal grid — true positions are -118.78, -119.18 etc.
    if sea_area and "pacific" in sea_area.lower() and 100 <= lon <= 180 and 0 <= lat <= 60:
        lon = -lon
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return None

    return {
        "lat":          lat,
        "lon":          lon,
        "depth_m":      depth_m,
        "deploy_start": deploy_start,
        "deploy_end":   deploy_end,
        "instrument":   instrument,
        "platform":     platform,
        "site":         site,
        "site_alias":   site_alias,
        "project_name": project_name,
        "sea_area":     sea_area,
    }


def _site_key(record: dict[str, Any], path: str, program: str) -> str:
    """Cluster identifier for grouping multiple deployments into one station.

    Three regimes:

    1. **SITE field populated** (most nested-schema programs): use SITE
       verbatim. PIFSC `Hawaii_K`, ONMS `CI01`, NPS `BartlettCove`, etc.
    2. **Flat ADEON/AEON/JASCO schema**: the JSON's top-level SITE field is
       usually empty or duplicates the project name (`AEON1-NEC`), but a
       single bottom-lander hosts 5-7 AMAR recorder configurations each with
       its own metadata file. Cluster by **(project_subfolder, lat~0.01°)** so
       the 80 ADEON metadata files collapse to ~7 sites (BLE, CHB, HAT, JAX,
       SAV, VAC, WIL).
    3. **Empty SITE, no flat schema (rare)**: use the second path segment
       under `{program}/audio/` as a fallback.
    """
    # Flat-schema programs publish SITE as either '' or the platform/project
    # name (e.g. AEON's 'AEON1-NEC'). The 2nd-segment project folder is the
    # real disambiguator (e.g. `aeon/audio/aeon1-nec/aeon_aeon1-nec_amar700...`).
    if program in {"adeon", "aeon", "jasco"}:
        parts = path.split("/")
        try:
            idx = parts.index("audio")
        except ValueError:
            idx = 0
        project_subfolder = parts[idx + 1] if idx + 1 < len(parts) else "site"
        lat = record.get("lat") or 0.0
        lon = record.get("lon") or 0.0
        # 0.01° ≈ 1 km — same lander cycles its mooring within ±100 m
        return f"{project_subfolder}@{round(lat, 2):.2f}_{round(lon, 2):.2f}"

    site = record.get("site")
    if site:
        return site.strip()
    parts = path.split("/")
    try:
        idx = parts.index("audio")
    except ValueError:
        idx = 0
    folders = parts[idx + 1: -2]
    if folders:
        return "/".join(folders)
    lat = record.get("lat") or 0.0
    lon = record.get("lon") or 0.0
    return f"{round(lat, 2):.2f}_{round(lon, 2):.2f}"


def _slug(s: str) -> str:
    out = []
    for ch in s.lower():
        if ch.isalnum():
            out.append(ch)
        elif ch in ("-", "_"):
            out.append(ch)
        else:
            out.append("_")
    return "".join(out).strip("_")[:60] or "site"


def _name_for(program: str, site_key: str, records: list[dict[str, Any]]) -> str:
    """Build a human-readable name. Prefer SITE_ALIASES[0] from any record,
    falling back to the site key, then "{program_display} {site}"."""
    cfg = PROGRAMS[program]
    for r in records:
        if r.get("site_alias"):
            site_part = r["site"] or site_key
            return f"{r['site_alias']} ({cfg['display']} {site_part})" if site_part != r["site_alias"] else r["site_alias"]
    # No alias — use site key, project name, or program display
    if records:
        site = records[-1].get("site") or site_key
        project = records[-1].get("project_name")
        if project and site:
            return f"{cfg['display']} {site} — {project}"
        if site:
            return f"{cfg['display']} {site}"
    return f"{cfg['display']} {site_key}"


async def fetch_program_stations(program: str) -> list[dict[str, Any]]:
    """Walk one program's prefix, extract one row per cluster (site/SITE).

    Strategy:
    1. Recursive list of all `metadata/*.json` under `{prefix}` (one paginated
       call without delimiter — GCS handles up to thousands of objects per
       page).
    2. Fetch each metadata JSON in series. Per-JSON try/except so one bad
       file doesn't sink the program.
    3. Group records by `_site_key()`; aggregate one row per site (most-recent
       deployment provides position/depth/hardware; min(deploy_start) and
       max(deploy_end) span the run).
    """
    cfg = PROGRAMS.get(program)
    if cfg is None:
        log.warning("acoustic_noaa_archive_ingest: unknown program %r", program)
        return []
    prefix = cfg["prefix"]

    rows: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            meta_paths = await _discover_metadata_jsons(client, prefix)
        except Exception as exc:
            log.warning("acoustic_noaa_archive_ingest: list %s failed: %s", prefix, exc)
            return []
        log.info("acoustic_noaa_archive_ingest: %s -> %d metadata JSONs", program, len(meta_paths))
        if not meta_paths:
            return []

        # Fetch JSONs in bounded-concurrency batches. Sequential fetching
        # of 80+ metadata files runs into per-program 30s+ wall time, which
        # the orchestrator can't afford across 12 programs.
        sem = asyncio.Semaphore(32)

        async def _bounded(path: str) -> tuple[str, dict[str, Any] | None]:
            async with sem:
                return path, await _fetch_json(client, path)

        results = await asyncio.gather(*[_bounded(p) for p in meta_paths])

        # Group by site as we go.
        clusters: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        for path, meta in results:
            if meta is None:
                continue
            try:
                rec = _extract_record(meta, program)
            except Exception as exc:
                log.debug("acoustic_noaa_archive_ingest: parse %s failed: %s", path, exc)
                continue
            if rec is None:
                continue
            key = _site_key(rec, path, program)
            clusters.setdefault(key, []).append((path, rec))

    if not clusters:
        log.info("acoustic_noaa_archive_ingest: %s produced no usable records", program)
        return []

    for site_key, members in clusters.items():
        records = [m[1] for m in members]
        # Most-recent deployment: max(deploy_start) — falls back to last in
        # iteration order if no dates exist.
        dated = [r for r in records if r.get("deploy_start") is not None]
        latest = max(dated, key=lambda r: r["deploy_start"]) if dated else records[-1]

        starts = [r["deploy_start"] for r in records if r.get("deploy_start") is not None]
        deploy_start = min(starts) if starts else None
        any_open = any(r.get("deploy_end") is None for r in records)
        ends = [r["deploy_end"] for r in records if r.get("deploy_end") is not None]
        deploy_end = None if any_open else (max(ends) if ends else None)

        slug = _slug(site_key) or _slug(latest.get("site") or "site")
        station_id = f"{program}:{slug}"

        rows.append({
            "station_id":   station_id,
            "source":       program,
            "name":         _name_for(program, site_key, records),
            "operator":     PROGRAMS[program]["operator"],
            "lat":          latest["lat"],
            "lon":          latest["lon"],
            "depth_m":      latest.get("depth_m"),
            "deploy_start": deploy_start,
            "deploy_end":   deploy_end,
            "model":        latest.get("instrument") or "Hydrophone",
            # NOAA archive products vary too much per recorder type to map a
            # single Hz range here. Panels display the model string; legend
            # documents the typical bands.
            "hz_range_lo":  None,
            "hz_range_hi":  None,
            "portal_url":   PROGRAMS[program]["portal"],
        })

    # Sort for stable output (alphabetic by station_id) so log diffs across
    # syncs stay readable.
    rows.sort(key=lambda r: r["station_id"])
    log.info("acoustic_noaa_archive_ingest: %s -> %d aggregated stations", program, len(rows))
    return rows


# ---------------------------------------------------------------------------
# Per-program convenience wrappers — keep the orchestrator wiring shape
# identical to the existing NRS / SanctSound / NEFSC modules (one
# `fetch_{prog}_stations` async function per source).
# ---------------------------------------------------------------------------

def _make_station_fetcher(program: str) -> Callable[[], Any]:
    async def _f() -> list[dict[str, Any]]:
        return await fetch_program_stations(program)
    _f.__name__ = f"fetch_{program}_stations"
    _f.__qualname__ = _f.__name__
    return _f


def _make_soundscape_fetcher(program: str) -> Callable[..., Any]:
    async def _f(station_id: str, days: int = 90) -> list[dict[str, Any]]:
        # Phase 4: no NOAA archive program publishes a first-party SPL /
        # decade-band aggregate via REST. Phase 5+ would tap the
        # `*/products/sound_level_metrics/` NetCDF/CSV tree.
        return []
    _f.__name__ = f"fetch_{program}_soundscape"
    _f.__qualname__ = _f.__name__
    return _f


# Generate the 12 fetchers up-front so callers can import them by name.
fetch_pifsc_stations                       = _make_station_fetcher("pifsc")
fetch_sefsc_stations                       = _make_station_fetcher("sefsc")
fetch_onms_stations                        = _make_station_fetcher("onms")
fetch_adeon_stations                       = _make_station_fetcher("adeon")
fetch_boem_stations                        = _make_station_fetcher("boem")
fetch_aeon_stations                        = _make_station_fetcher("aeon")
fetch_navy_stations                        = _make_station_fetcher("navy")
fetch_nps_stations                         = _make_station_fetcher("nps")
fetch_jasco_stations                       = _make_station_fetcher("jasco")
fetch_fram_stations                        = _make_station_fetcher("fram")
fetch_coastal_studies_institute_stations   = _make_station_fetcher("coastal_studies_institute")
fetch_ioos_stations                        = _make_station_fetcher("ioos")

fetch_pifsc_soundscape                     = _make_soundscape_fetcher("pifsc")
fetch_sefsc_soundscape                     = _make_soundscape_fetcher("sefsc")
fetch_onms_soundscape                      = _make_soundscape_fetcher("onms")
fetch_adeon_soundscape                     = _make_soundscape_fetcher("adeon")
fetch_boem_soundscape                      = _make_soundscape_fetcher("boem")
fetch_aeon_soundscape                      = _make_soundscape_fetcher("aeon")
fetch_navy_soundscape                      = _make_soundscape_fetcher("navy")
fetch_nps_soundscape                       = _make_soundscape_fetcher("nps")
fetch_jasco_soundscape                     = _make_soundscape_fetcher("jasco")
fetch_fram_soundscape                      = _make_soundscape_fetcher("fram")
fetch_coastal_studies_institute_soundscape = _make_soundscape_fetcher("coastal_studies_institute")
fetch_ioos_soundscape                      = _make_soundscape_fetcher("ioos")
