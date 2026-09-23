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

Deliberately NOT here: `_sync_pf_source` (permafrost-only despite the generic
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


# ── Global Tailings Portal (GRID-Arendal) withdrawal — decided 2026-09-23 ──
#
# tailing.grida.no/about asks users to "contact GRID-Arendal to obtain
# permission to download the TSF dataset"; we never obtained it. Michal's
# decision 2026-09-23, same principle as the WDPA/KBA withdrawals
# (`test_wdpa_withdrawn.py`, `test_kba_withdrawn.py`) — but NOT their shape.
# `tailings` is not a withdrawn layer: it stays live at 11,587 facilities.
# This is a field-level + row-level cut inside one layer that keeps serving.
#
# Rows: `data_source = 'grid'` (Portal-only facilities, no WAPHA counterpart)
# must never be served. `wapha` and `grid-enriched` rows stay served.
#
# Columns: `_enrich_tailings_from_grid` (domains/land/extractive.py) writes
# every column below on a `grid-enriched` row too — the WAPHA source
# shapefile publishes exactly one attribute (`Name`), so none of these held a
# genuine WAPHA value before enrichment touched them; they are Portal data,
# full stop, regardless of the row's `data_source`. `dam_name`, `country`,
# `id`, `geom`/`geog`, `data_source`, `created_at` are NOT in this list —
# those are WAPHA's own or platform-derived and stay served.
#
# ⛔ DELETE NOTHING. This is a serving-layer decision, not a data migration —
# every one of these columns and every `grid` row stays in the database.
# Every backend surface that reads `tailings_dams` must apply BOTH of the
# constants below, at the SQL layer, not as a Python post-filter.
TAILINGS_SERVED_WHERE = "data_source IS DISTINCT FROM 'grid'"

TAILINGS_PORTAL_COLUMNS: tuple[str, ...] = (
    "mine_name", "dam_type", "height_m", "volume_m3", "status",
    "owner_company", "operator", "construction_year", "raise_type",
    "hazard_raw", "grid_facility_id", "classification_system",
    "disclosure_link", "disclosure_origin", "history_stability_concerns",
    "downstream_impact", "recent_independent_expert_review",
    "extreme_weather_secure", "currently_approved_design",
    "closure_plan_dam", "closure_plan_long_term_monitoring",
    "internal_external_eng_support", "relevant_engineering_records",
    "disclosure_notes", "partners", "planned_storage_5_years",
)

# What every surface MAY serve for a wapha/grid-enriched row. `risk_class` is
# not here either — retired 2026-09-22, platform-derived, unwritten since.
TAILINGS_PUBLIC_COLUMNS: tuple[str, ...] = (
    "id", "dam_name", "country", "data_source", "created_at",
)


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


# ── one-time repair: make the `dams` sync_log row describe the live table ──
#
# ⛔ A `sync_log` row is the ONLY freshness signal we have for a layer: the
# monitor classifies staleness from `last_synced_at`, and the LegendPanel
# "Dates & Freshness" tab shows that same date to users.
#
# `_sync_dams` is append-only behind a populated guard that force does NOT
# bypass, so the documented way to swap the dataset is a deliberate TRUNCATE
# plus the sync in one transaction. When GOODD was replaced by GDW v1.0
# (2026-09-11) the reload was run that way on production but outside the sync
# function, so nothing called `_log_land_sync`: the row kept saying
# `2026-04-11 / 38667` — the date and the size of a dataset we no longer
# serve — while the table held 41,145 GDW barriers. Five months of apparent
# staleness, and a wrong count in the user-facing tab.
#
# ⛔ A hand-run UPDATE on production would fix one database and nothing else.
# This runs as a recorded schema step, so a restored backup or a dev copy
# carrying the same stale row is corrected too.
#
# It derives BOTH values from the live table rather than hardcoding 41145 —
# hardcoding would make it a lie again the next time the dataset is replaced.
_DAMS_SYNC_LOG_REPAIR = """
    UPDATE sync_log AS s
       SET last_synced_at = d.loaded_at,
           records_added  = d.n,
           total_records  = d.n
      FROM (SELECT count(*) AS n, max(created_at) AS loaded_at FROM dams) AS d
     WHERE s.source = 'dams'
       AND d.loaded_at IS NOT NULL
       AND s.total_records <> d.n
 RETURNING d.n AS live_rows, d.loaded_at AS loaded_at
"""


async def ensure_dams_sync_log_matches_live_table() -> None:
    """Correct a `sync_log` row for `dams` that disagrees with the table.

    Three guards, each load-bearing — every one of them has a test that goes red
    when it is deleted (`tests/test_dams_sync_log_repair.py`):

    - `s.source = 'dams'` — never touches another layer's row.
    - `d.loaded_at IS NOT NULL` — carries TWO cases, because `max()` over zero
      rows is already NULL:
        * an **empty** `dams` table must not overwrite a truthful record with
          zero rows and no date. A fresh database that has not loaded dams yet
          keeps what its row says instead of being told it holds nothing.
        * rows **predating** the `created_at` default (which is a default, not a
          NOT NULL) would give `max(created_at) = NULL`, and a NULL
          `last_synced_at` reads to the monitor as a layer that never synced.
      ⛔ An `AND d.n > 0` clause was written here first and removed: it can never
      fire on its own, because `d.n = 0` implies `d.loaded_at IS NULL`. It read
      like the guard for the empty case while contributing nothing, and sabotage
      testing turned up zero red tests for it. If you ever replace `max(...)`
      with something that has a non-NULL fallback (`coalesce(..., now())`), the
      empty-table protection disappears with it — put the row-count clause back
      in the same commit.
    - `s.total_records <> d.n` — makes the step idempotent. A row that already
      agrees with the table is left exactly as it is, including its
      `last_synced_at`, so a healthy sync's own timestamp is never rewritten
      to the load time of the rows it happened to leave in place.
    """
    async with db.pool.acquire() as conn:
        fixed = await conn.fetchrow(_DAMS_SYNC_LOG_REPAIR)
    if fixed:
        log.warning(
            "sync_log: dams row disagreed with the table — corrected to "
            "%d rows loaded %s", fixed["live_rows"], fixed["loaded_at"],
        )
