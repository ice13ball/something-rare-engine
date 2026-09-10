# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""SAMBAH (Static Acoustic Monitoring of the Baltic Sea Harbour Porpoise) ingest.

~298 C-POD hydrophone stations deployed 2011-2013 across 8 Baltic riparian states,
published on Dryad (DOI 10.5061/dryad.n5tb2rbx7, Amundin et al. 2022).
License: CC0 1.0 Universal (Public Domain Dedication) — unrestricted use.

Auth: Dryad API v2 uses OAuth2 client credentials.  Set env vars
DRYAD_CLIENT_ID and DRYAD_CLIENT_SECRET in backend/.env.  The function
exchanges them for a short-lived bearer token on each sync run.
Without the credentials the function logs a WARNING and returns [].

Ingest path
-----------
1. POST to /oauth/token with client_credentials → get bearer token.
2. Fetch dataset metadata from Dryad API v2 → extract current version ID.
3. Fetch file list for that version → locate station_info.csv.
4. Download station_info.csv (≈730 KB) with bearer token.
5. Parse CSV: station, lat, lon, depth, country → one row per station.

"""
from __future__ import annotations

import csv
import io
import logging
import os
from datetime import date
from typing import Any

import httpx
from ingestion.http_retry import get_with_retry

log = logging.getLogger(__name__)

_DATASET_DOI  = "10.5061/dryad.n5tb2rbx7"
_DRYAD_BASE   = "https://datadryad.org"
_DRYAD_API    = f"{_DRYAD_BASE}/api/v2"
_TOKEN_URL    = f"{_DRYAD_BASE}/oauth/token"
_PORTAL_URL   = "https://doi.org/10.5061/dryad.n5tb2rbx7"
_OPERATOR     = "SAMBAH consortium (EU LIFE08 NAT/S/000261; lead: Kolmården Wildlife Park)"
_DEPLOY_START = date(2011, 5, 1)
_DEPLOY_END   = date(2013, 4, 30)
_MODEL        = "Chelonia C-POD"
_HZ_LO        = 20_000.0   # C-POD click-detector passband
_HZ_HI        = 160_000.0
_TIMEOUT      = httpx.Timeout(60.0)
# Dryad mandates CC0 1.0 (public-domain dedication) for all hosted data;
# the Amundin et al. 2022 SAMBAH deposit is no exception. Unrestricted use.
_LICENSE      = "CC0 1.0"


async def _get_bearer_token(client: httpx.AsyncClient) -> str:
    """Exchange DRYAD_CLIENT_ID / DRYAD_CLIENT_SECRET for a bearer token."""
    client_id     = os.environ["DRYAD_CLIENT_ID"]
    client_secret = os.environ["DRYAD_CLIENT_SECRET"]
    r = await client.post(
        _TOKEN_URL,
        data={
            "grant_type":    "client_credentials",
            "client_id":     client_id,
            "client_secret": client_secret,
        },
    )
    r.raise_for_status()
    return r.json()["access_token"]


async def fetch_sambah_stations() -> list[dict[str, Any]]:
    """Download SAMBAH station coordinates from Dryad and return station rows.

    Returns [] and logs WARNING if DRYAD_CLIENT_ID / DRYAD_CLIENT_SECRET are not set.
    Each row maps to one row in acoustic_stations (source='sambah').
    """
    if not os.environ.get("DRYAD_CLIENT_ID") or not os.environ.get("DRYAD_CLIENT_SECRET"):
        log.warning(
            "fetch_sambah_stations: DRYAD_CLIENT_ID / DRYAD_CLIENT_SECRET not set — "
            "skipping SAMBAH ingest. Add them to backend/.env to populate ~298 Baltic "
            "C-POD stations."
        )
        return []

    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        token = await _get_bearer_token(client)
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        # Step 1: fetch dataset metadata to get current version ID
        encoded_doi = _DATASET_DOI.replace("/", "%2F").replace(":", "%3A")
        meta_url = f"{_DRYAD_API}/datasets/doi%3A{encoded_doi}"
        r = await get_with_retry(client, meta_url, headers=headers, label="sambah metadata")
        r.raise_for_status()
        meta = r.json()

        # Version ID is in _links["stash:version"]["href"] = "/api/v2/versions/182859"
        version_href = meta.get("_links", {}).get("stash:version", {}).get("href", "")
        version_id = version_href.rstrip("/").split("/")[-1] if version_href else None
        if not version_id:
            log.error("fetch_sambah_stations: could not determine Dryad version ID from %s", meta_url)
            return []

        log.info("fetch_sambah_stations: Dryad version_id=%s", version_id)

        # Step 2: fetch file list for this version
        files_url = f"{_DRYAD_API}/versions/{version_id}/files"
        r = await get_with_retry(client, files_url, headers=headers, label="sambah file list")
        r.raise_for_status()
        files_data = r.json()

        file_entries = files_data.get("_embedded", {}).get("stash:files", [])
        station_file = next(
            (f for f in file_entries if "station_info" in f.get("path", "").lower()),
            None,
        )
        if station_file is None:
            log.error(
                "fetch_sambah_stations: station_info.csv not found in Dryad version %s files",
                version_id,
            )
            return []

        # File entries have no top-level "id"; extract from _links["stash:download"]["href"]
        download_href = (
            station_file.get("_links", {})
            .get("stash:download", {})
            .get("href", "")
        )
        if not download_href:
            self_href = station_file.get("_links", {}).get("self", {}).get("href", "")
            file_id = self_href.rstrip("/").split("/")[-1] if self_href else None
            download_href = f"/api/v2/files/{file_id}/download"
        log.info("fetch_sambah_stations: downloading path=%s href=%s", station_file.get("path"), download_href)

        # Step 3: download station_info.csv
        download_url = f"{_DRYAD_BASE}{download_href}"
        r = await get_with_retry(client, download_url, headers=headers, label="sambah download")
        r.raise_for_status()
        csv_text = r.text

    # Step 4: parse CSV
    rows: list[dict[str, Any]] = []
    reader = csv.DictReader(io.StringIO(csv_text))
    fieldnames_lower = {(f.strip().lower() if f else ""): f for f in (reader.fieldnames or [])}

    def _col(row: dict, *candidates: str) -> str | None:
        for c in candidates:
            for k, orig in fieldnames_lower.items():
                if c in k:
                    val = row.get(orig, "").strip()
                    if val:
                        return val
        return None

    for line in reader:
        station_raw = _col(line, "station", "id", "no")
        lat_raw     = _col(line, "lat", "latitude", "y")
        lon_raw     = _col(line, "lon", "long", "longitude", "x")
        depth_raw   = _col(line, "depth", "dep")
        country_raw = _col(line, "country", "nation", "state")

        if not station_raw or not lat_raw or not lon_raw:
            continue

        try:
            lat = float(lat_raw)
            lon = float(lon_raw)
        except ValueError:
            log.debug("fetch_sambah_stations: skipping row with bad lat/lon: %s %s", lat_raw, lon_raw)
            continue

        # Basic sanity: Baltic Sea bounding box ~54-66°N, 10-31°E (generous)
        if not (50.0 <= lat <= 68.0 and 5.0 <= lon <= 35.0):
            log.debug("fetch_sambah_stations: skipping out-of-bounds station %s (%.4f, %.4f)", station_raw, lat, lon)
            continue

        depth_m: float | None = None
        if depth_raw:
            try:
                depth_m = float(depth_raw)
            except ValueError:
                pass

        station_num = station_raw.strip().lstrip("0") or station_raw.strip()
        name_parts = [f"SAMBAH station {station_num}"]
        if country_raw:
            name_parts.append(f"({country_raw})")

        rows.append({
            "station_id":   f"sambah:{station_num}",
            "source":       "sambah",
            "name":         " ".join(name_parts),
            "operator":     _OPERATOR,
            "lat":          lat,
            "lon":          lon,
            "depth_m":      depth_m,
            "deploy_start": _DEPLOY_START,
            "deploy_end":   _DEPLOY_END,
            "model":        _MODEL,
            "hz_range_lo":  _HZ_LO,
            "hz_range_hi":  _HZ_HI,
            "portal_url":   _PORTAL_URL,
            "license":      _LICENSE,
        })

    log.info("fetch_sambah_stations: parsed %d stations from Dryad CSV", len(rows))
    return rows


async def fetch_sambah_soundscape(station_id: str, days: int = 90) -> list[dict[str, Any]]:
    """Return [] — Dryad archive contains raw detection files only.

    No decoded SPL or decade-band time series is published.  Same Phase-1
    empty-state pattern as PALAOA / OOI / IMOS / MARS.
    """
    return []
