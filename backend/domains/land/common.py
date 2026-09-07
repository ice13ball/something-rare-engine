# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Genuinely cross-family helpers shared by several land-layer sync
functions, extracted verbatim from `land_layers.py`.

- `_log_land_sync` — sync-log writer used by ~24 call sites across every
  land layer family (mining footprints, KBAs, WDPA, tailings, fires, air
  quality, landslides, dams, water risk, DataCite-backed layers, ...). Also
  imported directly by `vessel_events.py` by this exact name, and by
  `domains/arctic.py`'s `_sync_arctic_rivers` / `_sync_permafrost_thaw`.
- `_pg_conn_string` — parses `DATABASE_URL` into an ogr2ogr `PG:` connection
  string. Used by every land sync that shells out to `ogr2ogr` (mining
  footprints, KBAs, WDPA, tailings, landslides, dams).
- `_datacite_extract_coords` / `_datacite_paginate` — shared DataCite API
  client helpers. Used by four sync functions: `_sync_wod_profiles`,
  `_sync_pangaea_records`, `_sync_bco_dmo_datasets`, `_sync_noaa_datasets`.

Deliberately NOT here: `_normalise_hazard` (tailings-only, called only by
`_sync_dams`) and `_sync_pf_source` (permafrost-only despite the generic
name) — both look shared and are not. Left alone in `land_layers.py`.
"""

from __future__ import annotations

import logging
import os
import re
import urllib.parse

import httpx

import db

log = logging.getLogger("land_layers")


async def _log_land_sync(source: str, added: int, total: int):
    """Log sync results to sync_log table (same table as sea layers)."""
    async with db.pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO sync_log (source, last_synced_at, records_added, total_records)
            VALUES ($1, NOW(), $2, $3)
            ON CONFLICT (source) DO UPDATE
            SET last_synced_at = NOW(), records_added = $2, total_records = $3
        """, source, added, total)


async def _log_land_sync_failure(source: str, live_total: int, detail: str):
    """Record that a sync RAN AND FAILED, without claiming it succeeded.

    ⛔ Deliberately does not touch `last_synced_at`. The staleness monitor reads
    that column, so stamping NOW() on a failure would silence the alert on
    exactly the source that needs one — the failure would look like a healthy
    sync that happened to import nothing. Leaving it alone keeps the source
    ageing while `records_added = 0` records that the attempt happened.

    `total_records` is set from the LIVE table, which the failed swap left
    untouched, so the row keeps describing what is actually being served.
    """
    log.error("%s: sync failed, live data left intact — %s", source, detail)
    async with db.pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO sync_log (source, last_synced_at, records_added, total_records)
            VALUES ($1, NULL, 0, $2)
            ON CONFLICT (source) DO UPDATE
            SET records_added = 0, total_records = $2
        """, source, live_total)


def _pg_conn_string() -> str:
    """Parse DATABASE_URL into ogr2ogr PG: connection string."""
    parsed = urllib.parse.urlparse(os.environ.get("DATABASE_URL", ""))
    return (
        f"PG:host={parsed.hostname} port={parsed.port or 5432} "
        f"dbname={parsed.path.lstrip('/')} user={parsed.username} "
        f"password={parsed.password}"
    )


def _datacite_extract_coords(attrs: dict) -> tuple[float, float] | None:
    """Extract a representative (lon, lat) from a DataCite attributes dict."""
    for geo in attrs.get("geoLocations") or []:
        pt = geo.get("geoLocationPoint")
        if pt:
            try:
                return float(pt["pointLongitude"]), float(pt["pointLatitude"])
            except (KeyError, TypeError, ValueError):
                pass
        box = geo.get("geoLocationBox")
        if box:
            try:
                lon = (float(box["westBoundLongitude"]) + float(box["eastBoundLongitude"])) / 2
                lat = (float(box["southBoundLatitude"]) + float(box["northBoundLatitude"])) / 2
                return lon, lat
            except (KeyError, TypeError, ValueError):
                pass
    return None


async def _datacite_paginate(
    client: httpx.AsyncClient,
    provider_id: str,
    query: str,
    max_records: int = 5000,
) -> list[dict]:
    """Fetch up to max_records DOI records from DataCite for a provider+query."""
    results: list[dict] = []
    cursor = "1"
    page_size = min(1000, max_records)
    while len(results) < max_records:
        try:
            r = await client.get(
                "https://api.datacite.org/dois",
                params={
                    "provider-id": provider_id,
                    "query": query,
                    "resource-type-id": "dataset",
                    "page[size]": page_size,
                    "page[cursor]": cursor,
                    "fields[dois]": "doi,titles,geoLocations,publicationYear",
                },
            )
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            log.warning("datacite paginate error (provider=%s query=%s): %s", provider_id, query, e)
            break
        items = data.get("data") or []
        results.extend(items)
        next_cursor = (
            (data.get("links") or {}).get("next") or ""
        )
        # DataCite next link contains page[cursor]=X
        if not next_cursor or not items or len(results) >= max_records:
            break
        # Extract cursor value from next URL
        m = re.search(r"page%5Bcursor%5D=([^&]+)|page\[cursor\]=([^&]+)", next_cursor)
        cursor = (m.group(1) or m.group(2)) if m else None
        if not cursor:
            break
    return results[:max_records]
