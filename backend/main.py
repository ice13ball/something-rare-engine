# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from ingestion.cadence import should_sync
from zoneinfo import ZoneInfo

import asyncpg
import auth
import db as _db
from dotenv import load_dotenv
from services.ocean_currents import backtrack as _backtrack, CMEMSUnavailableError
import services.currents_bake as currents_bake
from services import woa_climatology
from sync_log import log_sync as _log_sync, is_sync_paused, _load_paused_syncs, invalidate_paused_cache
from response_cache import CACHE_TTL, store as _cache
from auth import require_admin_token as _require_admin_token
from services.plume_history import compute_pending_plume_paths as _compute_plume_paths
from fastapi import FastAPI, HTTPException, Security, Depends, Query, Request
from routers.spatial_v2 import router as spatial_v2_router
from routers.reports import router as reports_router
from routers.reports_v2 import router as reports_v2_router
from routers.feedback import router as feedback_router
from routers.export import router as export_router
from routers.admin_api import router as admin_api_router
from routers.org_admin_api import router as org_admin_api_router
from routers.admin_layers_api import router as admin_layers_api_router
from routers import admin_profiles_api
import domains
from domains import acoustic
from domains import arctic
from domains import biodiversity
from domains import blog
from domains import cables
from domains import fields
from domains import geo_context
from domains import geochem
from domains import isa
from domains import offshore
from domains import onc
from domains import seafloor
from domains import sensors
from domains import seo
from domains import seo_hubs
from land_layers import (
    router as land_layers_router, sync_all_land_sources,
    _sync_air_quality_readings, _sync_mining_footprints, _sync_kbas, _sync_wdpa,
    _sync_tailings, _enrich_tailings_from_grid, _sync_active_fires, _sync_air_quality, _sync_landslides, _sync_dams, _sync_water_risk,
    refresh_monitoring_density,
    _sync_wod_profiles, _sync_pangaea_records,
    _sync_bco_dmo, _sync_noaa_datasets, _sync_obis_seamap,
    _sync_ncei_icoads, _sync_cchdo_cruises,
)
from land_overlaps import router as land_overlaps_router, refresh_overlap_views
from vessel_events import (
    router as vessel_events_router,
    auto_discover_contractors,
    sync_vessel_events_stub,
)
from ais_sync import (
    router as ais_router,
    run_aoi_seed,
    run_partition_maintenance,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, HTMLResponse
from fastapi.security.api_key import APIKeyHeader
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from api_docs import build_openapi
import log_redaction

load_dotenv()


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
# ⛔ Must come AFTER load_dotenv() and after basicConfig has made the handlers, or it
# silently protects less than it looks like it does. Closes the ONC-token leak found
# in the journal on 2026-09-08 — see backend/log_redaction.py.
_redacted_secret_count = log_redaction.install()
log = logging.getLogger(__name__)
log.info("log redaction active for %d secret values", _redacted_secret_count)

# Whether the running commit's schema (migrate.py's job) matches what's actually
# in the database. Set once at startup by lifespan(), read by /health.
SCHEMA_STATE = "unknown"


def classify_schema_state(row, running_sha: str | None) -> str:
    """Three answers, and none of them stops the process.

    "unknown" — we cannot tell which commit this is (no git, no env var). A
                deployment that cannot know its own commit must not be told its
                schema is stale.
    "stale"   — no migration row, or one recorded against a different commit.
    "ok"      — the recorded commit is the running one.
    """
    if running_sha is None:
        return "unknown"
    if not row or not row.get("git_sha"):
        return "stale"
    return "ok" if row["git_sha"] == running_sha else "stale"


# Wall-clock budget for reading schema_migrations at startup. A lock on that
# row, or an exhausted pool, would otherwise hang lifespan() forever — uvicorn
# never binds the port, nothing listens, and `systemctl is-active` reports
# "active" regardless (the 2026-08-21 incident, on a new code path: a
# crash-loop is loud and self-restarting, that hang was silent and permanent).
SCHEMA_CHECK_TIMEOUT_S = 10.0


class _SchemaCheckFailed(Exception):
    """The schema_migrations fetch failed for a reason OTHER than the table
    being missing — a connection reset, an exhausted pool, a lock on the row,
    a permission error, or the wall-clock timeout above firing. None of those
    mean the schema is stale; they mean the check itself failed, so the
    caller maps this to SCHEMA_STATE "unknown", never "stale" — reporting
    "stale" here would have /health claim a mismatch it never observed."""


async def _fetch_schema_migration_row(pool: asyncpg.Pool,
                                       timeout_s: float = SCHEMA_CHECK_TIMEOUT_S):
    """Read schema_migrations' one row under the wall-clock guard above.

    Returns the row, or None if the table does not exist yet — a real "stale"
    verdict, since migrate.py has never run against this database. Raises
    _SchemaCheckFailed for anything else, timeout included.
    """
    async def _read():
        async with pool.acquire() as conn:
            return await conn.fetchrow(
                "SELECT git_sha, applied_at FROM schema_migrations WHERE id = 1"
            )
    try:
        return await asyncio.wait_for(_read(), timeout=timeout_s)
    except asyncpg.exceptions.UndefinedTableError:
        return None
    except asyncio.TimeoutError as e:
        raise _SchemaCheckFailed(f"timed out after {timeout_s:.0f}s") from e
    except Exception as e:
        raise _SchemaCheckFailed(f"{type(e).__name__}: {e}") from e


async def _check_schema_state(pool: asyncpg.Pool, running_sha: str | None,
                               timeout_s: float = SCHEMA_CHECK_TIMEOUT_S):
    """Fetch schema_migrations and classify it against running_sha. Never raises.

    Thin enough that lifespan() (which cannot be unit-tested without a live
    pool) stays a one-line caller, while this can be exercised directly with
    a fake pool. Returns (state, row) — row is the schema_migrations row (or
    None) on a normal fetch, and always None when the fetch itself failed, so
    callers can still log the recorded git_sha/applied_at on "ok"/"stale".
    """
    try:
        row = await _fetch_schema_migration_row(pool, timeout_s)
        row = dict(row) if row else None
    except _SchemaCheckFailed as e:
        log.error(
            "schema check failed (%s) — reporting \"unknown\", not \"stale\": "
            "we did not observe a mismatch, we failed to look.", e,
        )
        return "unknown", None
    return classify_schema_state(row, running_sha), row


# Exact allow-list only. No wildcard regex — a `*.onrender.com` pattern would let any
# attacker-registered subdomain pass CORS. localhost is intentionally absent: local
# frontend dev runs against a local backend, not this public one. Add a localhost entry
# back temporarily only if you must point a local SPA at apiv2.
ALLOWED_ORIGINS = [
    "https://something-rare.com",
    "https://www.something-rare.com",
    "https://something-rare-frontend-dev-3w2whlwtbq-ew.a.run.app",
]

API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=True)

async def get_api_key(request: Request, api_key: str = Security(api_key_header)):
    from api_access.auth import resolve_and_check
    decision, record = await resolve_and_check(api_key)
    if decision.allowed:
        request.state.api_key_id = record.id if record else None
        request.state.api_org_id = record.org_id if record else None
        return api_key
    msg = "Rate limit exceeded" if decision.status_code == 429 else "Invalid API key"
    raise HTTPException(decision.status_code, msg)

_pool: asyncpg.Pool | None = None

# ── Constants ────────────────────────────────────────────────────────────────

OBIS_API = "https://api.obis.org/v3/occurrence"
SYNC_INTERVAL_SECONDS = 7 * 24 * 3600  # weekly

_hotspot_grid_lock = asyncio.Lock()  # prevents concurrent rebuilds stacking up
_layer_config_cache:   str | None = None
_layer_config_cache_ts: float = 0.0
_startup_profiles_cache: bytes | None = None
_startup_profiles_cache_ts: float = 0.0

# Argo sync cadence — used only by _argo_sync_task, which stays in main.py
# (the sync body it calls now lives in domains/sensors.py).
ARGO_SYNC_INTERVAL_SECONDS = 12 * 3600   # 12 hours

# ── Sync helpers ──────────────────────────────────────────────────────────────

GBIF_SPECIES_URL = "https://api.gbif.org/v1/species/{key}"


async def _backfill_woa_anomalies(batch_size: int = 1000) -> int:
    """One-shot: fill woa_* for argo_profiles rows that don't have them yet."""
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT profile_id, profile_date, deep_pressure_m,
                      ST_Y(geom) AS lat, ST_X(geom) AS lon
               FROM argo_profiles
               WHERE woa_surface_temp_c IS NULL AND woa_deep_temp_c IS NULL
               LIMIT $1""",
            batch_size,
        )
    if not rows:
        log.info("woa backfill: all argo rows already enriched")
        return 0
    log.info("woa backfill: processing %d profiles", len(rows))
    updated = 0
    enriched = 0
    for r in rows:
        w = await asyncio.to_thread(
            woa_climatology.enrich_profile, float(r["lat"]), float(r["lon"]),
            r["profile_date"].month, 0.0, r["deep_pressure_m"],
        )
        async with _pool.acquire() as conn:
            await conn.execute(
                """UPDATE argo_profiles SET
                     woa_surface_temp_c=$1, woa_surface_sal=$2,
                     woa_deep_temp_c=$3, woa_deep_sal=$4, woa_deep_oxygen_umol_kg=$5,
                     woa_deep_aou=$6, woa_deep_o2sat=$7,
                     woa_deep_phosphate=$8, woa_deep_silicate=$9, woa_deep_nitrate=$10
                   WHERE profile_id=$11""",
                w["woa_surface_temp_c"], w["woa_surface_sal"],
                w["woa_deep_temp_c"], w["woa_deep_sal"], w["woa_deep_oxygen_umol_kg"],
                w["woa_deep_aou"], w["woa_deep_o2sat"],
                w["woa_deep_phosphate"], w["woa_deep_silicate"], w["woa_deep_nitrate"],
                r["profile_id"],
            )
        updated += 1
        # A row only drops out of the re-select filter (woa_surface_temp_c IS NULL
        # AND woa_deep_temp_c IS NULL) if at least one of those becomes non-NULL.
        # Profiles whose coords fall outside the WOA grid stay all-NULL forever, so
        # count only genuine progress — otherwise the caller's loop re-selects the
        # same un-enrichable rows endlessly and starves the worker (outage 2026-06-29).
        if w["woa_surface_temp_c"] is not None or w["woa_deep_temp_c"] is not None:
            enriched += 1
    async with _pool.acquire() as conn:
        await sensors.populate_argo_cache(conn)
    log.info("woa backfill: updated %d profiles (%d newly enriched)", updated, enriched)
    return enriched


async def _woa_backfill_task():
    """One-shot WOA backfill. Waits for the startup bake (grids on disk) + extra.
    Loops batches until none remain."""
    await asyncio.sleep(900)
    while True:
        try:
            n = await _backfill_woa_anomalies()
        except Exception:
            log.exception("woa backfill batch failed")
            return
        if n == 0:
            return
        await asyncio.sleep(5)


async def _log_noise_risk_count_on_startup():
    """Log current noise_risk_grid row count to sync_log so the dashboard shows it."""
    try:
        async with _pool.acquire() as conn:
            count = await conn.fetchval("SELECT COUNT(*) FROM noise_risk_grid")
            if count:
                await _log_sync("noise_risk", 0, count)
                log.info("noise_risk: %d grid cells (static — use Force Sync to refresh)", count)
    except Exception:
        pass  # table may not exist yet on first deploy


async def _run_unless_paused(action: str, fn, label: str | None = None):
    """Run a sync function unless its action is paused. Serialized via
    _sync_lock (shared with _run_tracked) so weekly-chain and admin
    force-sync paths cannot overlap. Returns True if it ran."""
    if await is_sync_paused(action):
        log.info("%s: skipped (paused)", label or action)
        return False
    async with _sync_lock:
        await fn()
    return True


# ─────────────────────────────────────────────────────────────────────────────

async def _sync_all_sources():
    """Weekly sync: pull new records from every external source into DB."""
    log.info("Weekly sync starting…")

    # ArcGIS layers + mining contracts
    if not await is_sync_paused("arcgis"):
        async with _pool.acquire() as conn:
            await isa.sync_reserved_areas(conn)
            await isa.sync_apeis(conn)
            await isa.sync_relinquished_areas(conn)
            await isa.sync_mining_contracts(conn)
    else:
        log.info("arcgis: skipped (paused)")

    # OBIS runs as its own systemd service (obis-sync.service) — not here.
    # Argo is still managed by the weekly chain.
    if not await is_sync_paused("argo"):
        await sensors.sync_argo_profiles()
    else:
        log.info("argo: skipped (paused)")

    # Per-source weekly tasks — each isolated so one upstream outage can't
    # abort the whole chain (e.g. PANGAEA seamounts ZIP returning 503 was
    # silently blocking gbif/chess/cables/etc for weeks).
    for action, fn, label in [
        ("seamounts",        seafloor.sync_seamounts,      "seamounts"),
        ("vents",            seafloor.sync_hydrothermal_vents, "vents"),
        ("eez",              geo_context.sync_eez,                    "eez"),
        ("protected-sites",  geo_context.sync_protected_marine_sites, "protected_sites"),
        ("claim-enrichment", isa.enrich_claim_boundaries, "claim_enrichment"),
        ("cables",           cables.sync_submarine_cables, "submarine_cables"),
        ("onc-cables",       cables.sync_onc_cables,       "onc_cables"),
        ("ooi-cables",       cables.sync_ooi_cables,       "ooi_cables"),
        ("noaa-cables",      cables.sync_noaa_cables,      "noaa_cables"),
        ("nz-cables",        cables.sync_nz_cables,        "nz_cables"),
        ("au-cables",        cables.sync_au_cables,        "au_cables"),
        ("onc-instruments",  onc.sync_onc_instruments,        "onc_instruments"),
        # ("ports", …) — port_locations layer permanently disabled 2026-07-07; removed
        # from the weekly auto-sync chain so the table no longer changes. Force-sync
        # wiring left intact but dormant.
        ("oceansites",       sensors.sync_oceansites,       "oceansites"),
        ("onc",              onc.sync_onc,                    "onc"),
        ("chess",            biodiversity.sync_chess,                  "chess"),
        ("deepdata",         biodiversity.sync_deepdata,               "deepdata"),
        ("deepdata-stations", biodiversity.sync_deepdata_stations,     "deepdata_stations"),
        ("mbari-vars",       biodiversity.sync_mbari_vars,             "mbari_vars"),
        ("noaa-corals",      biodiversity.sync_noaa_corals,            "noaa_corals"),
        ("worms",            biodiversity.sync_worms_taxa,             "worms"),
        ("acoustic-stations",   acoustic.sync_acoustic_stations,    "acoustic_stations"),
        ("acoustic-soundscape", acoustic.sync_acoustic_soundscape,  "acoustic_soundscape"),
        ("arctic-rivers",       arctic.sync_arctic_rivers_logged, "arctic_river_stations"),
        ("permafrost-thaw",     arctic.sync_permafrost_thaw_logged, "permafrost_thaw_features"),
        ("seaflea",             geochem.sync_seaflea,       "seaflea_seeps"),
        ("sios",                arctic.sync_sios,                 "sios_datasets"),
        ("arcade",              arctic.sync_arcade,               "arctic_catchments"),
    ]:
        try:
            await _run_unless_paused(action, fn, label)
        except Exception as e:
            log.error("%s sync failed: %s", label, e)

    # Enrich species with images from GBIF/iNaturalist (batch of 2000 per weekly run)
    await biodiversity.enrich_species_images(batch_size=2000)

    # Backfill IUCN categories for species already enriched with images
    try:
        iucn_count = await biodiversity.backfill_iucn_categories(batch_size=500)
        log.info("iucn_backfill: updated %d species", iucn_count)
    except Exception as exc:
        log.warning("iucn_backfill: failed — %s", exc)

    # Pre-compute plume paths for any near-mining Argo profiles not yet processed
    try:
        plume_count = await _compute_plume_paths(_pool, max_batch=500)
        log.info("plume_history: sync complete — %d new paths", plume_count)
    except Exception as exc:
        log.warning("plume_history: sync failed — %s", exc)

    # hotspot_grid is rebuilt by obis-sync.service after each OBIS run.
    # The weekly chain no longer calls rebuild_hotspot_grid() here.

    # Rebuild species-per-claim cache after hotspots/contracts may have changed.
    # Calls services/species_cache.py (NOT routers/reports.py — that file is the
    # frozen v1 restore path and its rebuild SQL has a UniqueViolationError bug
    # that left the cache empty on every run). _log_sync so a silent failure
    # surfaces in the admin dashboard.
    try:
        from services.species_cache import refresh_species_cache
        cnt = await refresh_species_cache()
        await _log_sync("species-cache", cnt, cnt)
    except Exception as exc:
        log.warning("species_cache: refresh failed — %s", exc)
        try:
            await _log_sync("species-cache", 0, 0)
        except Exception:
            pass

    log.info("Weekly sync complete")


async def _run_with_log(fn, label: str):
    """Run an async function, logging any exception without crashing the service."""
    try:
        await fn()
    except Exception:
        log.exception("%s failed", label)


async def _startup_data_check():
    """Light check on startup: log table counts, no heavy network calls."""
    tables = [
        "mining_contracts", "reserved_areas", "isa_apeis", "relinquished_areas",
        "biodiversity_hotspots", "seamounts", "argo_profiles",
        "hydrothermal_vents", "maritime_boundaries", "protected_marine_sites",
        "submarine_cables", "onc_cables", "ooi_cables", "noaa_cables", "nz_cables", "au_cables", "port_locations", "oceansites_stations", "onc_locations",
        "chess_occurrences",
    ]
    async with _pool.acquire() as conn:
        for t in tables:
            try:
                exists = await conn.fetchval("SELECT to_regclass($1)", t)
                if exists is None:
                    log.warning("startup check: %s — table MISSING", t)
                    continue
                n = await conn.fetchval(f"SELECT COUNT(*) FROM {t}")  # noqa: S608
                if n == 0:
                    log.warning("startup check: %s — table EMPTY (0 rows)", t)
                else:
                    log.info("startup check: %s = %d rows", t, n)
            except Exception as exc:
                log.warning("startup check: %s — query failed: %s: %s", t, type(exc).__name__, exc)


async def _weekly_sync_task():
    # First sync delayed 1 hour after boot — gives VPS time to settle
    await asyncio.sleep(3600)
    while True:
        try:
            await _sync_all_sources()
        except Exception:
            log.exception("Weekly sync failed")
        await asyncio.sleep(SYNC_INTERVAL_SECONDS)


async def _argo_sync_task():
    """Sync Argo floats every 12h — independent of the weekly full sync."""
    await asyncio.sleep(1800)  # 30 min delay after boot
    while True:
        try:
            await _run_unless_paused("argo", sensors.sync_argo_profiles, "argo_12h")
        except Exception:
            log.exception("Argo 12h sync failed")
        await asyncio.sleep(ARGO_SYNC_INTERVAL_SECONDS)


async def _worms_sync_task():
    await asyncio.sleep(300)  # 5 min — external-API tier, no heavy DB scan
    while True:
        try:
            await _run_unless_paused("worms", biodiversity.sync_worms_taxa, "worms")
        except Exception:
            log.exception("worms sync failed")
        await asyncio.sleep(SYNC_INTERVAL_SECONDS)  # weekly cadence


LAND_SYNC_INTERVAL_SECONDS = 6 * 3600  # 6 hours — fires need frequent updates

MONITORING_DENSITY_REFRESH_INTERVAL_SECONDS = 12 * 3600

SIO_BIC_SYNC_INTERVAL_SECONDS = 7 * 24 * 3600  # weekly


async def _sio_bic_sync_task():
    """Weekly SIO-BIC catalogue refresh. 4h startup delay so OBIS/ChEss syncs
    settle first; the 12h monitoring-density refresh picks up new rows on its
    next cycle automatically."""
    await asyncio.sleep(4 * 3600)
    while True:
        try:
            await _run_with_log(biodiversity.sync_sio_bic, "sio-bic catalogue sync")
        except Exception:
            log.exception("SIO-BIC sync failed")
        await asyncio.sleep(SIO_BIC_SYNC_INTERVAL_SECONDS)


async def _slow_sources_sync_task():
    """Daily tick for sources that had no periodic caller at all.

    `memento` and `ncei_icoads_files` were reachable only from the admin
    force-sync map. An audit on 2026-09-02 found memento 72 days stale and
    ncei_icoads_files holding 0 rows — neither was broken, both were simply
    never called. The cadence registry decides whether each actually runs, so a
    daily tick is cheap: a Static or Blocked source costs one SELECT.

    90-minute startup delay: this scans large tables and must stay well clear of
    the cold start and the SAR seed, per the engine rule on heavy background work.
    """
    from domains.geochem import sync_memento
    from domains.land.density import _sync_ncei_icoads

    await asyncio.sleep(90 * 60)
    while True:
        for source, fn in (("memento", sync_memento),
                           ("ncei_icoads_files", _sync_ncei_icoads)):
            try:
                async with db.pool.acquire() as conn:
                    last = await conn.fetchval(
                        "SELECT last_synced_at FROM sync_log WHERE source = $1", source)
                run, why = should_sync(source, last, datetime.now(timezone.utc))
                log.info("%s", why)
                if run:
                    await _run_with_log(fn, source)
            except Exception:
                log.exception("%s: slow-source sync failed", source)
        await asyncio.sleep(24 * 3600)


async def _monitoring_density_refresh_task():
    """Rebuild monitoring_density_grid every 12h so new rows from upstream source
    syncs (GBIF/Argo/ONC/WOD/…) surface on the map automatically.
    2h startup delay lets the first weekly sync settle before aggregating."""
    await asyncio.sleep(2 * 3600)
    while True:
        try:
            await _run_with_log(refresh_monitoring_density, "monitoring density refresh")
        except Exception:
            log.exception("Monitoring density refresh task failed")
        await asyncio.sleep(MONITORING_DENSITY_REFRESH_INTERVAL_SECONDS)


async def _land_sync_task():
    """Periodic land layer sync. Fires every 6h, air quality daily,
    static layers have skip-if-populated guards inside their sync functions."""
    await asyncio.sleep(1800)  # 30 min delay after boot
    while True:
        try:
            await sync_all_land_sources()
            log.info("Land layer sync complete")
        except Exception:
            log.exception("Land layer sync failed")
        await asyncio.sleep(LAND_SYNC_INTERVAL_SECONDS)


ONC_SENSOR_SYNC_INTERVAL_SECONDS = 24 * 3600  # daily


# CURRENTS_BAKE_INTERVAL_SECONDS, _currents_meta_cache, _sync_currents and
# _bake_all_currents moved to domains/fields/currents.py (Task 5, Phase 3).
# _currents_bake_task/_currents_backfill_task below stay here (startup
# orchestration) and call fields.currents.* / services.currents_bake directly.

# ── Staggered startup delays for the heavy field-layer bakes ─────────────────
# All nine of these used to sit at a flat 300 s, so every restart fired them
# SIMULTANEOUSLY at T+5 min. Each one is individually guarded (skip-if-present /
# 30-day sync_log), so in steady state they no-op — but on a cold env, after lost
# holdings, or a forced run they all do real work at once, via asyncio.to_thread,
# i.e. real CPU + real RAM concurrently. That is the same shape as the OOM
# crash-loop this box already suffered once. Spread them ~4 min apart, lightest
# first, GEBCO (7.5 GB read) last. Keep them distinct when adding a new bake.
_BAKE_STARTUP_DELAY = {
    "currents":        300,
    "seabed":          540,
    "cascade":         780,
    "woa":            1020,
    "oxygen":         1260,
    "carbon":         1500,
    "acidification":  1740,
    "socat":          1980,
    "bathymetry_grid": 2220,
    # coral-acid-exposure: deliberately NOT +240 from bathymetry_grid's neighbour slot —
    # it consumes BOTH the acidification horizons (1740) and the baked GEBCO grid (2220),
    # so it must run after both. Keep it distinct from every other value in this dict.
    "coral_exposure": 2460,
    # CHI has no upstream-bake dependency (reads its own KNB GeoTIFF); slotted last in the
    # stagger only so its 60 MB download + reproject doesn't fight cold-start traffic.
    "chi": 2700,
}


async def _currents_bake_task():
    """Daily CMEMS current-texture bake. Staggered startup delay (external-API tier
    per the Background task discipline table — no heavy DB scan)."""
    await asyncio.sleep(_BAKE_STARTUP_DELAY["currents"])
    while True:
        try:
            await fields.currents.bake_all_currents()
        except Exception:
            log.exception("Currents bake task failed")
        await asyncio.sleep(fields.currents.CURRENTS_BAKE_INTERVAL_SECONDS)


async def _currents_backfill_task(force: bool = False):
    """One-time ~180-day history backfill. External-API tier (10 min delay).
    Idempotent: skips days already on disk; restart-safe; guarded by sync_log."""
    if not force:
        await asyncio.sleep(600)
        # Inline sync_log idempotence guard — matches the existing pattern used by
        # the cable syncs (no _recent_sync helper exists in this codebase).
        async with _pool.acquire() as conn:
            last = await conn.fetchval(
                "SELECT last_synced_at FROM sync_log WHERE source = 'currents-backfill'")
        if last is not None and (datetime.now(timezone.utc) - last) < timedelta(hours=20):
            log.info("currents backfill: recent run found — skipping")
            return
    today = datetime.now(timezone.utc).date()
    total = 0
    for slug in ("surface", "1000m"):
        have = set(currents_bake.available_dates(slug))
        for n in range(currents_bake.CURRENTS_HISTORY_DAYS, -1, -1):
            d = today - timedelta(days=n)
            if d.strftime("%Y-%m-%d") in have:
                continue
            try:
                await asyncio.to_thread(currents_bake.bake_depth, slug,
                                        datetime(d.year, d.month, d.day, tzinfo=timezone.utc))
                total += 1
                # Surface the growing date range to /meta during the long backfill —
                # otherwise the cache stays frozen until the very end of the run.
                if total % 20 == 0:
                    fields.currents.clear_caches()
            except Exception as exc:
                log.warning("currents backfill %s %s failed: %s", slug, d, exc)
            await asyncio.sleep(3)  # CMEMS politeness
        try:
            await asyncio.to_thread(currents_bake.prune_old, slug)
        except Exception as exc:
            log.warning("currents backfill: prune %s failed (non-fatal): %s", slug, exc)
        fields.currents.clear_caches()  # depth complete → expose its full range now
    fields.currents.clear_caches()
    await _log_sync("currents-backfill", total, total)
    log.info("currents backfill complete: %d depth-day textures baked", total)


# Ten field-family cache globals (_woa_meta_cache, _oxygen_meta_cache,
# _carbon_meta_cache, _co2_meta_cache, _seabed_meta_cache, _vme_meta_cache,
# _coral_exposure_cache, _acid_meta_cache, _chi_meta_cache, plus
# _currents_meta_cache above) and their eleven owning sync/bake functions
# (_sync_woa, _sync_glodap_carbon, _sync_acidification, _sync_chi_impact,
# _sync_coral_exposure, _sync_vme, _sync_socat_co2, _sync_seabed,
# _sync_oxygen_deox, plus _sync_currents/_bake_all_currents above) moved to
# domains/fields/{climatology,carbon,habitat,currents}.py (Task 5, Phase 3).
# The startup-bake wrappers below stay here (startup orchestration) and call
# fields.<module>.sync_*() instead.

async def _woa_startup_bake():
    """One-shot WOA bake. External-API tier (staggered startup delay). The 30-day
    sync_log guard inside fields.climatology.sync_woa makes restarts cheap."""
    await asyncio.sleep(_BAKE_STARTUP_DELAY["woa"])
    try:
        await fields.climatology.sync_woa()
    except Exception:
        log.exception("WOA startup bake failed")


async def _carbon_startup_bake():
    """One-shot GLODAP carbon bake. External-API tier (staggered startup delay). The 30-day
    sync_log guard inside fields.carbon.sync_glodap_carbon makes restarts cheap."""
    await asyncio.sleep(_BAKE_STARTUP_DELAY["carbon"])
    try:
        await fields.carbon.sync_glodap_carbon()
    except Exception:
        log.exception("GLODAP carbon startup bake failed")


async def _acidification_startup_bake():
    await asyncio.sleep(_BAKE_STARTUP_DELAY["acidification"])
    try: await fields.carbon.sync_acidification()
    except Exception: log.exception("acidification startup bake failed")


async def _chi_startup_bake():
    await asyncio.sleep(_BAKE_STARTUP_DELAY["chi"])
    try: await fields.habitat.sync_chi_impact()
    except Exception: log.exception("chi startup bake failed")


async def _coral_exposure_startup_bake():
    # Deliberately AFTER the acidification bake in the stagger: this consumes its horizon
    # grids. See _BAKE_STARTUP_DELAY["coral_exposure"] (2460 s) — do not give it a delay
    # that collides with a sibling.
    await asyncio.sleep(_BAKE_STARTUP_DELAY["coral_exposure"])
    try:
        await fields.carbon.sync_coral_exposure()
    except Exception:
        log.exception("coral-acid-exposure startup bake failed")


async def _socat_startup_bake():
    """One-shot SOCAT CO₂ bake. External-API tier (staggered startup delay). The 30-day
    sync_log guard inside fields.carbon.sync_socat_co2 makes restarts cheap."""
    await asyncio.sleep(_BAKE_STARTUP_DELAY["socat"])
    try:
        await fields.carbon.sync_socat_co2()
    except Exception:
        log.exception("SOCAT CO2 startup bake failed")


async def _seabed_startup_bake():
    """One-shot seabed lithology holdings check. Static dataset: 30-day sync_log
    guard makes restarts cheap."""
    await asyncio.sleep(_BAKE_STARTUP_DELAY["seabed"])
    try:
        await fields.habitat.sync_seabed()
    except Exception:
        log.exception("seabed startup holdings failed")


async def _cascade_startup_bake():
    """One-shot CASCADE Arctic sediment carbon grid holdings check."""
    await asyncio.sleep(_BAKE_STARTUP_DELAY["cascade"])
    try:
        await arctic.sync_cascade()
    except Exception as e:
        log.warning("cascade startup bake failed: %s", e)


async def _bathymetry_grid_bake_task():
    """One-shot GEBCO_2024 downsample bake for the bathymetry field-export sampler.
    External-API tier; skip-if-present makes restarts cheap. Runs LAST in the
    stagger — it reads the 7.5 GB GEBCO grid and is the memory-heaviest bake."""
    await asyncio.sleep(_BAKE_STARTUP_DELAY["bathymetry_grid"])
    try:
        from services.bathymetry_grid_export import bake_bathymetry_grid
        n = await asyncio.to_thread(bake_bathymetry_grid)
        if n:
            log.info("bathymetry-grid startup bake: %d cells", n)
    except Exception as exc:               # never block the listener
        log.warning("bathymetry-grid startup bake failed: %s", exc)


async def _oxygen_startup_bake():
    """One-shot startup bake (external-API tier, staggered delay). sync_log guard inside
    fields.climatology.sync_oxygen_deox."""
    await asyncio.sleep(_BAKE_STARTUP_DELAY["oxygen"])
    try:
        await fields.climatology.sync_oxygen_deox()
    except Exception:
        log.exception("oxygen startup bake failed")


async def _onc_sensor_sync_task():
    """Refresh ONC cached sensor readings daily — keeps map current without
    per-click API calls."""
    # Delay first run — no startup sync, so wait for weekly task to populate locations
    await asyncio.sleep(3600)
    while True:
        try:
            await onc.sync_onc_sensors()
        except Exception:
            log.exception("ONC daily sensor sync failed")
        await asyncio.sleep(ONC_SENSOR_SYNC_INTERVAL_SECONDS)


async def _onc_instruments_daily_task():
    """Run ONC instrument WFS sync + enrichment once per day at ~00:15 Europe/Warsaw.

    Uses zoneinfo so DST transitions (CET↔CEST) are handled automatically.
    Enrichment is batched to ~300 devices/run so it spreads across ~3 days on
    a cold DB and then settles into steady refresh.
    """
    tz = ZoneInfo("Europe/Warsaw")
    # Light startup delay so other heavy tasks settle first
    await asyncio.sleep(600)
    while True:
        now_local = datetime.now(tz)
        target = now_local.replace(hour=0, minute=15, second=0, microsecond=0)
        if target <= now_local:
            target = target + timedelta(days=1)
        wait_s = max(60, int((target - now_local).total_seconds()))
        log.info("onc_instruments daily: next run at %s (in %ds)", target.isoformat(), wait_s)
        await asyncio.sleep(wait_s)
        try:
            await onc.sync_onc_instruments(skip_guard_hours=20)
        except Exception:
            log.exception("onc_instruments daily WFS sync failed")
        try:
            await onc.enrich_onc_instruments(batch_limit=300)
        except Exception:
            log.exception("onc_instruments daily enrichment failed")


async def _onc_sparkline_task():
    """Refresh ONC 72-hour sparklines every 4 hours."""
    await asyncio.sleep(300)  # 5 min startup delay
    while True:
        try:
            await onc.sync_onc_sparklines()
        except Exception:
            log.exception("ONC sparkline sync failed")
        await asyncio.sleep(4 * 3600)


async def _onc_adcp_task():
    """Refresh ONC ADCP backscatter strips every 12 hours.

    Each run queues one RADCPTS job per location on ONC's side (17 of them), so a
    4-hourly cadence would be 102 jobs/day for a product that already covers 24 h.
    12 h keeps the strip fresh at a quarter of the load. Threshold in the monitor's
    thresholds.md must stay ≥ 30 h to match.
    """
    await asyncio.sleep(900)  # 15 min startup delay
    while True:
        try:
            await onc.sync_onc_adcp_strips()
        except Exception:
            log.exception("ONC ADCP strip sync failed")
        await asyncio.sleep(12 * 3600)


async def _onc_ctd_task():
    """Refresh ONC CTD profiles every 12 hours."""
    await asyncio.sleep(900)  # 15 min startup delay
    while True:
        try:
            await onc.sync_onc_ctd_profiles()
        except Exception:
            log.exception("ONC CTD profile sync failed")
        await asyncio.sleep(12 * 3600)


async def _usgs_earthquakes_task():
    """Refresh USGS earthquake catalog every 6 hours."""
    await asyncio.sleep(300)  # 5 min startup delay
    while True:
        try:
            await onc.sync_usgs_earthquakes()
        except Exception:
            log.exception("USGS earthquake sync failed")
        await asyncio.sleep(6 * 3600)


async def _ais_partition_maintenance_task():
    """Daily: create the upcoming ais_positions weekly partition and drop
    partitions older than AIS_RETENTION_DAYS. Idempotent. This is the disk cap."""
    await asyncio.sleep(1800)  # 30 min startup delay
    while True:
        try:
            await run_partition_maintenance()
        except Exception:
            log.exception("AIS partition maintenance failed")
        await asyncio.sleep(24 * 3600)


VESSEL_EVENTS_SYNC_INTERVAL_SECONDS = 6 * 3600  # every 6 hours


async def _vessel_events_sync_task():
    """Periodic SAR×AIS vessel-events sync. Sentinel-1 revisits mid-latitude
    AOIs every ~12h; 6h cadence catches each pass within one cycle. Run budgets
    in sar_detector keep CDSE PU usage bounded."""
    await asyncio.sleep(7200)  # 2h delay — let the AIS ingestor accumulate positions
    while True:
        try:
            await sync_vessel_events_stub()
        except Exception:
            log.exception("vessel-events auto-sync failed")
        await asyncio.sleep(VESSEL_EVENTS_SYNC_INTERVAL_SECONDS)


async def _usage_rollup_task():
    """Roll request_log into usage_rollup every 10 minutes."""
    from api_access.rollup import rollup_new_rows
    await asyncio.sleep(120)  # let startup settle
    while True:
        try:
            n = await rollup_new_rows(_pool)
            if n:
                log.info("usage rollup: advanced %d request_log rows", n)
        except Exception:
            log.exception("usage rollup failed")
        await asyncio.sleep(600)


async def _leak_detection_task():
    """Scan request_log hourly for key-leak signals; raise debounced flags + Telegram.

    20-min startup delay per background-task discipline (scans request_log with
    ST_-free aggregations but still a DB-heavy GROUP BY over a 24h/7d window).
    """
    from api_access.leak_detect import run_leak_detection
    await asyncio.sleep(20 * 60)
    while True:
        try:
            n = await run_leak_detection(_pool)
            if n:
                log.info("leak detection: raised %d new flag(s)", n)
        except Exception:
            log.exception("leak detection failed")
        await asyncio.sleep(3600)


async def _log_retention_task():
    """Ensure upcoming daily partitions exist and drop partitions older than 90 days. Daily."""
    from api_access.logstore import drop_expired_log_partitions, ensure_daily_partitions
    await asyncio.sleep(180)
    while True:
        try:
            async with _pool.acquire() as conn:
                await ensure_daily_partitions(conn)
                await conn.execute("DELETE FROM api_access.admin_sessions WHERE expires_at < now()")
            dropped = await drop_expired_log_partitions(_pool)
            if dropped:
                log.info("request_log retention: dropped %d expired partitions", dropped)
        except Exception:
            log.exception("request_log retention failed")
        await asyncio.sleep(24 * 3600)


async def _query_watchdog_task():
    """Periodic check for long-running queries on the abyssal DB.

    Two thresholds:
    - WARN (15 min): log.warning so Mac-side monitor / journalctl picks it up.
      Useful visibility into legitimately-slow queries.
    - KILL (60 min): pg_terminate_backend. Catches zombie backends left over
      from Python tasks that died (service restart, exception, etc.) but
      whose postgres queries kept running independently.

    Background context: 2026-05-15 night, the service restart left 3 orphan
    postgres backends running for 18h / 8h / 3.5h respectively (one
    claim-enrichment + two pre-refactor SEO concession queries). Total CPU
    ~254% sustained. Killing the python client doesn't kill the postgres
    backend; only pg_terminate_backend does. This watchdog is the
    catch-all so nothing burns CPU for hours unobserved.
    """
    WARN_MIN = 15
    KILL_MIN = 60
    POLL_SEC = 300  # every 5 min
    await asyncio.sleep(120)  # 2-min startup delay so service init can complete
    while True:
        try:
            async with _pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT pid,
                           EXTRACT(EPOCH FROM (NOW() - query_start))/60 AS dur_min,
                           LEFT(query, 120) AS q
                    FROM pg_stat_activity
                    WHERE datname = 'abyssal'
                      AND state = 'active'
                      AND backend_type = 'client backend'
                      AND pid <> pg_backend_pid()
                      AND query_start IS NOT NULL
                      AND NOW() - query_start > INTERVAL '15 minutes'
                """)
                for r in rows:
                    dur = float(r["dur_min"])
                    if dur > KILL_MIN:
                        log.warning(
                            "query_watchdog: KILLING zombie pid=%s dur=%.1fmin q=%r",
                            r["pid"], dur, r["q"],
                        )
                        try:
                            await conn.execute(
                                "SELECT pg_terminate_backend($1)", r["pid"]
                            )
                        except Exception:
                            log.exception("query_watchdog: terminate failed for pid=%s", r["pid"])
                    else:
                        log.warning(
                            "query_watchdog: long-running pid=%s dur=%.1fmin q=%r",
                            r["pid"], dur, r["q"],
                        )
        except Exception:
            log.exception("query_watchdog: poll failed")
        await asyncio.sleep(POLL_SEC)


OCEANSITES_OBS_SYNC_INTERVAL_SECONDS = 24 * 3600  # daily


async def _oceansites_obs_sync_task():
    """Refresh OceanSITES cached NDBC observations daily."""
    await asyncio.sleep(3600)  # delay — wait for weekly task to populate stations
    while True:
        try:
            await sensors.sync_oceansites_obs()
        except Exception:
            log.exception("OceanSITES daily obs sync failed")
        await asyncio.sleep(OCEANSITES_OBS_SYNC_INTERVAL_SECONDS)


AIR_QUALITY_READINGS_INTERVAL_SECONDS = 2 * 3600  # every 2 hours


async def _air_quality_readings_task():
    """Drip-fill air quality readings from OpenAQ v3 — 500 stations per run,
    sequential 1 req/1.2s to respect rate limits. Runs independently of
    the 6h land sync to populate all ~24k stations in ~4 days."""
    await asyncio.sleep(900)  # 15 min after boot
    while True:
        try:
            await _run_unless_paused("air-quality-readings", _sync_air_quality_readings, "air_quality_readings_2h")
        except Exception:
            log.exception("Air quality readings sync failed")
        await asyncio.sleep(AIR_QUALITY_READINGS_INTERVAL_SECONDS)


async def _acoustic_stations_task() -> None:
    """Weekly sync of acoustic_stations with a 30-min startup delay."""
    await asyncio.sleep(1800)
    while True:
        try:
            await acoustic.sync_acoustic_stations()
        except Exception as exc:
            log.exception("acoustic stations task error: %s", exc)
        await asyncio.sleep(7 * 24 * 3600)


async def _acoustic_soundscape_task() -> None:
    """Weekly sync of acoustic_soundscape with a 60-min startup delay."""
    await asyncio.sleep(3600)
    while True:
        try:
            await acoustic.sync_acoustic_soundscape()
        except Exception as exc:
            log.exception("acoustic soundscape task error: %s", exc)
        await asyncio.sleep(7 * 24 * 3600)


OFFSHORE_ACTIVITIES_INTERVAL = 7 * 24 * 3600  # weekly


async def _offshore_activities_sync_task():
    """Sync all 9 offshore-activity registries weekly. 45-min startup delay
    ensures the pool is settled and schema migrations are complete."""
    await asyncio.sleep(45 * 60)
    while True:
        for fn, label in [
            (offshore.sync_emodnet_offshore, "emodnet-offshore"),
            (offshore.sync_boem_offshore, "boem-offshore"),
            (offshore.sync_crown_estate_wind, "crown-estate-wind"),
            (offshore.sync_nopta_petroleum, "nopta-petroleum"),
            (offshore.sync_nzpam_offshore, "nzpam-offshore"),
            (offshore.sync_anp_brazil, "anp-brazil"),
            (offshore.sync_mra_png_dsm, "mra-png-dsm"),
            (offshore.sync_mme_nam_dsm, "mme-namibia-dsm"),
            (offshore.sync_sbma_ck, "sbma-cook-islands"),
            (offshore.sync_cnsopb_petroleum, "cnsopb"),
            (offshore.sync_cnlopb_petroleum, "cnlopb"),
            (offshore.sync_dea_dk_petroleum, "dea-dk"),
            (offshore.sync_sodir_petroleum, "sodir-petroleum"),
            (offshore.sync_sodir_co2, "sodir-co2"),
            (offshore.sync_nsta_petroleum, "nsta-petroleum"),
            (offshore.sync_nsta_co2, "nsta-co2"),
            (offshore.sync_anh_colombia, "anh-colombia"),
            (offshore.sync_meei_trinidad, "meei-trinidad"),
            (offshore.sync_pad_ireland, "pad-ireland"),
            (offshore.sync_perupetro, "perupetro"),
            (offshore.sync_petrocom_ghana, "petrocom-ghana"),
            (offshore.sync_pmp_guyana, "pmp-guyana"),
            (offshore.sync_pasa_sa, "pasa-sa"),
            (offshore.sync_esdm_indonesia, "esdm-indonesia"),
            (offshore.sync_cnh_mexico, "cnh-mexico"),
            (offshore.sync_crown_estate_scotland, "crown-estate-scotland"),
        ]:
            try:
                await _run_with_log(fn, label)
            except Exception:
                log.exception("%s failed", label)
            await asyncio.sleep(120)
        await asyncio.sleep(OFFSHORE_ACTIVITIES_INTERVAL)


# ── App lifecycle ─────────────────────────────────────────────────────────────

def _watch(task: asyncio.Task) -> None:
    if not task.cancelled() and (exc := task.exception()) is not None:
        log.error("Background task '%s' crashed", task.get_name(), exc_info=exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _pool
    # CPU budget: max_size capped at 4 so this app cannot spawn more than 4
    # concurrent postgres backends. Heavy spatial queries (ST_DWithin against
    # biodiversity_hotspots' 5.1M points) saturate one core each; without this
    # cap, SEO crawler bursts pegged 4+ cores. Combined with _sync_lock and
    # _heavy_query_sem (below) this keeps total project CPU under ~2 cores.
    _pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=2, max_size=4, max_inactive_connection_lifetime=300.0)
    _db.pool = _pool

    from api_access.logging_mw import batch_writer
    from api_access.rollup import rollup_new_rows
    from api_access.geoip import load_geoip
    from api_access.store import seed_internal_key
    from api_access.auth import init_key_cache
    from api_access.admin_auth import bootstrap_super_admin

    # The sixteen schema steps and the AOI seed now run in scripts/migrate.py,
    # before the deploy restart — see that script for what they do. Startup
    # only checks that they ran against the commit it is about to serve.
    global SCHEMA_STATE
    from schema_steps import SCHEMA_STEPS, resolve_git_sha
    running_sha = resolve_git_sha()
    SCHEMA_STATE, _schema_row = await _check_schema_state(_pool, running_sha)
    if SCHEMA_STATE == "ok":
        log.info("schema verified: %s, %d steps, applied %s",
                 running_sha[:12], len(SCHEMA_STEPS), _schema_row["applied_at"])
    elif SCHEMA_STATE == "stale":
        log.error("SCHEMA STALE — running %s but schema_migrations records %s. "
                  "Run backend/scripts/migrate.py. Serving anyway: refusing to "
                  "boot would crash-loop (Restart=always, RestartSec=5).",
                  (running_sha or "?")[:12],
                  (_schema_row["git_sha"][:12] if _schema_row and _schema_row.get("git_sha") else "nothing"))
    else:
        log.info("schema check unresolved: commit not knowable, or the check itself failed")

    # API-key subsystem: seed the frontend's env key into the DB (idempotent),
    # then point the in-memory key cache at the live pool. Must run after
    # ensure_api_access_schema so the tables exist. Runs even for a standby —
    # it still serves reads and needs a working key cache to authenticate them.
    try:
        await seed_internal_key(_pool, os.getenv("ABYSSAL_API_KEY"))
    except Exception as e:
        log.error("api_access seed_internal_key failed (env fallback still active): %s", e)
    init_key_cache(_pool)
    # Phase 3: bootstrap the operator super-admin from env (idempotent — no-op if one exists).
    try:
        created = await bootstrap_super_admin(
            _pool, os.getenv("ADMIN_BOOTSTRAP_USER"), os.getenv("ADMIN_BOOTSTRAP_PASSWORD")
        )
        if created:
            log.info("Bootstrapped super-admin %s", os.getenv("ADMIN_BOOTSTRAP_USER"))
    except Exception as e:
        log.error("super-admin bootstrap failed: %s", e)

    # A standby lives ~30 s, started only while a deploy is in flight (see
    # ABYSSAL_STANDBY in .env.example). Nothing below can fire in that window —
    # the shortest startup delay in this block is 15 min — so spawning every
    # one of these tasks would do nothing for the standby itself. But a standby that
    # someone forgot to kill would duplicate every sync, silently: the monitor
    # has no way to tell "ran twice" from "ran once", so the failure is invisible
    # exactly when it happens. Five lines closes that off.
    if os.environ.get("ABYSSAL_STANDBY") == "1":
        log.info("ABYSSAL_STANDBY=1 — serving reads only, no background tasks")
    else:
        # Contractor auto-discovery joins ais_positions × aois — 6+ min, CPU-heavy.
        # Delay 20 min after boot so cold-start traffic and SAR seeding get the pool first.
        async def _delayed_auto_discover():
            # 45 min, not the 20 it used to be. The engine rule asks for >=15 min for
            # anything scanning ais_positions, and 20 nominally cleared it — but on
            # 2026-09-02 this call still lost a race with the cold start and the SAR
            # seed and died on its statement_timeout, while the identical query took
            # 86 s once the box was quiet. The scan is ~52M rows; give the boot storm
            # room to finish first. The regular 6h task already waits 2h.
            await asyncio.sleep(2700)
            try:
                await auto_discover_contractors()
            except Exception:
                log.exception("contractor auto-discovery failed")
        asyncio.create_task(_delayed_auto_discover()).add_done_callback(_watch)
        # Phase 2: request logging writer + periodic rollup + retention.
        _geoip = load_geoip()
        asyncio.create_task(batch_writer(_pool, _log_pipe, _geoip)).add_done_callback(_watch)
        asyncio.create_task(_usage_rollup_task()).add_done_callback(_watch)
        asyncio.create_task(_leak_detection_task()).add_done_callback(_watch)
        asyncio.create_task(_log_retention_task()).add_done_callback(_watch)
        # Load paused syncs into memory cache before any sync tasks start
        await _load_paused_syncs()
        # Verify data exists on startup (fast) — no heavy syncs during dev restarts
        asyncio.create_task(_run_with_log(_startup_data_check, "Startup data check")).add_done_callback(_watch)
        # Scheduled syncs — actual data refresh happens here, not on boot
        asyncio.create_task(_weekly_sync_task()).add_done_callback(_watch)
        asyncio.create_task(_argo_sync_task()).add_done_callback(_watch)
        asyncio.create_task(_onc_sensor_sync_task()).add_done_callback(_watch)
        asyncio.create_task(_onc_instruments_daily_task()).add_done_callback(_watch)
        asyncio.create_task(_onc_sparkline_task()).add_done_callback(_watch)
        asyncio.create_task(_onc_adcp_task()).add_done_callback(_watch)
        asyncio.create_task(_onc_ctd_task()).add_done_callback(_watch)
        asyncio.create_task(_usgs_earthquakes_task()).add_done_callback(_watch)
        asyncio.create_task(_oceansites_obs_sync_task()).add_done_callback(_watch)
        asyncio.create_task(_land_sync_task()).add_done_callback(_watch)
        asyncio.create_task(_monitoring_density_refresh_task()).add_done_callback(_watch)
        asyncio.create_task(_sio_bic_sync_task()).add_done_callback(_watch)
        asyncio.create_task(_slow_sources_sync_task()).add_done_callback(_watch)
        asyncio.create_task(_air_quality_readings_task()).add_done_callback(_watch)
        asyncio.create_task(_ais_partition_maintenance_task()).add_done_callback(_watch)
        asyncio.create_task(_vessel_events_sync_task()).add_done_callback(_watch)
        asyncio.create_task(_acoustic_stations_task()).add_done_callback(_watch)
        asyncio.create_task(_acoustic_soundscape_task()).add_done_callback(_watch)
        asyncio.create_task(_offshore_activities_sync_task()).add_done_callback(_watch)
        asyncio.create_task(_currents_bake_task()).add_done_callback(_watch)
        asyncio.create_task(_currents_backfill_task()).add_done_callback(_watch)
        asyncio.create_task(_woa_startup_bake()).add_done_callback(_watch)
        asyncio.create_task(_woa_backfill_task()).add_done_callback(_watch)
        asyncio.create_task(_oxygen_startup_bake()).add_done_callback(_watch)
        asyncio.create_task(_carbon_startup_bake()).add_done_callback(_watch)
        asyncio.create_task(_acidification_startup_bake()).add_done_callback(_watch)
        asyncio.create_task(_chi_startup_bake()).add_done_callback(_watch)
        asyncio.create_task(_coral_exposure_startup_bake()).add_done_callback(_watch)
        asyncio.create_task(_socat_startup_bake()).add_done_callback(_watch)
        asyncio.create_task(_seabed_startup_bake()).add_done_callback(_watch)
        asyncio.create_task(_cascade_startup_bake()).add_done_callback(_watch)
        asyncio.create_task(_bathymetry_grid_bake_task()).add_done_callback(_watch)
        asyncio.create_task(_worms_sync_task()).add_done_callback(_watch)
        asyncio.create_task(_log_noise_risk_count_on_startup()).add_done_callback(_watch)
        # Watchdog: kill orphan postgres backends running > 60 min, warn > 15 min.
        # Catches zombie queries left behind by service restarts / Python crashes.
        asyncio.create_task(_query_watchdog_task()).add_done_callback(_watch)
        # Kick off tile pre-bake on startup so viewers don't hit cold on-demand tiles.
        # schedule_bake is debounced — safe to call even if syncs trigger it again soon.
        import offshore_tile_baker as _baker
        asyncio.create_task(_baker.schedule_bake(_pool)).add_done_callback(_watch)
    yield
    await _pool.close()

from api_access.logging_mw import LogPipe, RequestLogMiddleware
_log_pipe = LogPipe()

app = FastAPI(title="Abyssal Claims API", lifespan=lifespan)

app.add_middleware(RequestLogMiddleware, pipe=_log_pipe)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(spatial_v2_router)
app.include_router(reports_router)
app.include_router(reports_v2_router)  # v2 neutral reports
app.include_router(feedback_router)
app.include_router(land_layers_router)
app.include_router(vessel_events_router)
app.include_router(ais_router)
app.include_router(land_overlaps_router)
app.include_router(admin_api_router)
app.include_router(org_admin_api_router)
app.include_router(export_router)
app.include_router(admin_layers_api_router)
app.include_router(admin_profiles_api.router)
app.include_router(cables.router)
app.include_router(geo_context.router)
app.include_router(blog.router)
app.include_router(acoustic.router)
app.include_router(arctic.router)
app.include_router(biodiversity.router)
app.include_router(geochem.router)
app.include_router(isa.router)
app.include_router(onc.router)
app.include_router(seafloor.router)
app.include_router(sensors.router)
app.include_router(seo.router)
app.include_router(seo_hubs.router)
app.include_router(fields.router)

# Public API documentation: curated OpenAPI served at /openapi.json,
# rendered by Scalar at the frontend /api-docs route. See backend/api_docs.py.
app.openapi = lambda: build_openapi(app)

# ── API endpoints ─────────────────────────────────────────────────────────────


@app.get("/v1/map/layer-config")
async def get_layer_config():
    """Public endpoint — returns layer order + defaults. 60s in-memory cache."""
    global _layer_config_cache, _layer_config_cache_ts
    if _layer_config_cache and time.monotonic() - _layer_config_cache_ts < 60.0:
        return Response(_layer_config_cache, media_type="application/json")
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, order_idx, default_on, modes FROM layer_config "
            "WHERE status = 'enabled' ORDER BY order_idx"
        )
    data = json.dumps([
        {"id": r["id"], "order_idx": r["order_idx"],
         "default_on": r["default_on"], "modes": list(r["modes"])}
        for r in rows
    ])
    _layer_config_cache = data
    _layer_config_cache_ts = time.monotonic()
    return Response(data, media_type="application/json")


def serialize_profiles(rows) -> str:
    """asyncpg returns JSONB columns as str — decode label/description to dicts."""
    out = []
    for r in rows:
        label = r["label"]
        desc = r["description"]
        views = r["views"]
        out.append({
            "id": r["id"],
            "section": r["section"],
            "order_idx": r["order_idx"],
            "layers": list(r["layers"]),
            "label": json.loads(label) if isinstance(label, str) else (label or {}),
            "description": json.loads(desc) if isinstance(desc, str) else (desc or {}),
            "accent": r["accent"],
            "views": json.loads(views) if isinstance(views, str) else (views or {}),
        })
    return json.dumps(out)


def _bust_profiles_cache() -> None:
    global _startup_profiles_cache, _startup_profiles_cache_ts
    _startup_profiles_cache = None
    _startup_profiles_cache_ts = 0.0


@app.get("/v1/map/startup-profiles")
async def get_startup_profiles():
    """Public — enabled startup profiles, ordered (section, order_idx). 60s cache."""
    global _startup_profiles_cache, _startup_profiles_cache_ts
    if _startup_profiles_cache and time.monotonic() - _startup_profiles_cache_ts < 60.0:
        return Response(_startup_profiles_cache, media_type="application/json")
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, section, order_idx, layers, label, description, accent, views "
            "FROM startup_profiles WHERE status = 'enabled' "
            "ORDER BY section, order_idx")
    data = serialize_profiles(rows).encode()
    _startup_profiles_cache = data
    _startup_profiles_cache_ts = time.monotonic()
    return Response(data, media_type="application/json")


@app.get("/v1/conflicts/vent-mining", dependencies=[Depends(get_api_key)])
async def get_vent_mining_conflicts():
    cache_key = "vent_conflicts"
    if cache_key in _cache:
        fetched_at, data = _cache[cache_key]
        if time.monotonic() - fetched_at < CACHE_TTL:
            return Response(content=data, media_type="application/json")

    sql = """
        SELECT
          v.name            AS vent_name,
          v.status          AS vent_status,
          v.depth_m,
          mc.contractor_name,
          mc.isa_id,
          mc.resource_type,
          CASE
            WHEN v.status = 'Active' AND (
              EXISTS (
                SELECT 1 FROM argo_profiles ap
                WHERE ap.near_mining = TRUE
                  AND ST_DWithin(ap.geom::geography, mc.geom::geography, 200000)
              ) OR EXISTS (
                SELECT 1 FROM biodiversity_hotspots bh
                WHERE ST_Intersects(bh.geom::geometry, mc.geom::geometry)
              )
            ) THEN 'High Risk'
            WHEN v.status = 'Active'   THEN 'Active Conflict'
            WHEN v.status = 'Inactive' THEN 'Dormant Overlap'
            ELSE                            'Historical Overlap'
          END AS risk_level
        FROM hydrothermal_vents v
        JOIN mining_contracts mc
          ON ST_Intersects(v.geom::geometry, mc.geom::geometry)
        WHERE mc.resource_type = 'Polymetallic Sulphides'
        ORDER BY
          CASE
            WHEN v.status = 'Active' AND (
              EXISTS (
                SELECT 1 FROM argo_profiles ap
                WHERE ap.near_mining = TRUE
                  AND ST_DWithin(ap.geom::geography, mc.geom::geography, 200000)
              ) OR EXISTS (
                SELECT 1 FROM biodiversity_hotspots bh
                WHERE ST_Intersects(bh.geom::geometry, mc.geom::geometry)
              )
            ) THEN 1
            WHEN v.status = 'Active'   THEN 2
            WHEN v.status = 'Inactive' THEN 3
            ELSE 4
          END,
          mc.contractor_name
    """

    try:
        async with _pool.acquire() as conn:
            rows = await conn.fetch(sql)
    except Exception:
        raise HTTPException(status_code=503, detail="Database unavailable")

    result = [
        {
            "vent_name":       r["vent_name"],
            "vent_status":     r["vent_status"],
            "depth_m":         r["depth_m"],
            "contractor_name": r["contractor_name"],
            "isa_id":          r["isa_id"],
            "resource_type":   r["resource_type"],
            "risk_level":      r["risk_level"],
        }
        for r in rows
    ]

    data = json.dumps(result).encode()
    _cache[cache_key] = (time.monotonic(), data)
    return Response(content=data, media_type="application/json")


@app.get("/v1/sync/status", dependencies=[Depends(get_api_key)])
async def get_sync_status():
    """Return last sync timestamp per source — used by frontend for data freshness display."""
    async with _pool.acquire() as conn:
        rows = await conn.fetch("SELECT source, last_synced_at FROM sync_log ORDER BY source")
    return {r["source"]: r["last_synced_at"].date().isoformat() for r in rows}


@app.get("/v1/layers/temporal-coverage", dependencies=[Depends(get_api_key)])
async def get_layer_temporal_coverage():
    """WHEN each layer's data is from — the anchor needed before pooling it.

    ⛔ Not the same question as /v1/sync/status, and the two are routinely confused.
    That one reports when WE last refreshed our copy; this one reports the period the
    DATA covers. A layer synced this morning can be a 1955-2017 climatology, and a
    layer we last pulled a year ago can hold measurements taken last week.

    `kind` is the part that decides whether values may be merged with recent data:
    `observations` are dated rows a model may filter by period, while a `climatology`
    is a single averaged value per cell that cannot be filtered at all and must never
    be treated as contemporaneous with dated points.
    """
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT layer_id, start_year, end_year, kind, wording, source_url,
                      verified_on
                 FROM layer_temporal_coverage ORDER BY layer_id""")
    return {r["layer_id"]: {"start_year": r["start_year"], "end_year": r["end_year"],
                            "kind": r["kind"], "wording": r["wording"],
                            "source_url": r["source_url"],
                            "verified_on": r["verified_on"].isoformat()}
            for r in rows}


@app.get("/v1/plumes/history", dependencies=[Depends(get_api_key)])
async def get_plume_history(
    contractor_name: str = Query(..., description="Contractor name from mining_contracts"),
    limit: int = Query(default=50, ge=1, le=200),
):
    """
    Return pre-computed plume back-track paths for all Argo profiles
    near a given mining contractor, ordered most-recent first.

    Response: GeoJSON FeatureCollection where each Feature is a Point
    at the back-tracked origin, with the full path in properties.
    """
    cache_key = f"plume_history:{contractor_name}:{limit}"
    cached = _cache.get(cache_key)
    if cached:
        fetched_at, data = cached
        if time.monotonic() - fetched_at < CACHE_TTL:
            return Response(content=data, media_type="application/json")

    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                pp.profile_id,
                pp.platform_id,
                pp.profile_date,
                pp.origin_lon,
                pp.origin_lat,
                pp.path_coords,
                pp.speed_cms,
                pp.steps_completed,
                pp.source_dataset
            FROM plume_paths pp
            WHERE pp.contractor_name = $1
            ORDER BY pp.profile_date DESC
            LIMIT $2
            """,
            contractor_name,
            limit,
        )

    features = []
    for row in rows:
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [row["origin_lon"], row["origin_lat"]],
            },
            "properties": {
                "role": "plume_origin",
                "profile_id": row["profile_id"],
                "platform_id": row["platform_id"],
                "profile_date": row["profile_date"].isoformat(),
                "path_coords": json.loads(row["path_coords"]) if isinstance(row["path_coords"], str) else row["path_coords"],
                "speed_cms": row["speed_cms"],
                "steps_completed": row["steps_completed"],
                "source_dataset": row["source_dataset"],
            },
        })

    result = json.dumps({"type": "FeatureCollection", "features": features}).encode()
    _cache[cache_key] = (time.monotonic(), result)
    return Response(content=result, media_type="application/json")


@app.get("/v1/analysis/correlate-plume", dependencies=[Depends(get_api_key)])
async def correlate_plume(
    argo_id: str = Query(..., description="profile_id from argo_profiles"),
    hours: int = Query(default=168, ge=24, le=720, description="Back-track duration in hours"),
    depth: int = Query(default=1000, ge=100, le=3000, description="Integration depth in metres"),
):
    """Back-track ocean currents from an Argo float position to estimate plume source.
    Checks pre-computed plume_paths table first for instant results. Falls back to
    live CMEMS backtrack and stores the result for future requests."""
    cache_key = f"plume:{argo_id}:{hours}:{depth}"
    cached = _cache.get(cache_key)
    if cached:
        fetched_at, data = cached
        if time.monotonic() - fetched_at < CACHE_TTL:
            return Response(content=data, media_type="application/json")

    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT ST_X(geom::geometry) AS lon, ST_Y(geom::geometry) AS lat,
                      profile_date, platform_id, profile_id
               FROM argo_profiles WHERE profile_id = $1""",
            argo_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail={"detail": "Argo profile not found", "argo_id": argo_id})

    lon, lat, profile_date = row["lon"], row["lat"], row["profile_date"]

    # ── Check pre-computed plume_paths first ──────────────────────────────
    async with _pool.acquire() as conn:
        stored = await conn.fetchrow(
            """SELECT origin_lon, origin_lat, path_coords, speed_cms,
                      steps_completed, contractor_name
               FROM plume_paths WHERE profile_id = $1""",
            argo_id,
        )

    if stored and stored["path_coords"]:
        path_coords = json.loads(stored["path_coords"]) if isinstance(stored["path_coords"], str) else stored["path_coords"]
        origin_lon, origin_lat = stored["origin_lon"], stored["origin_lat"]

        features = [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "role": "argo_observation",
                    "platform_id": row["platform_id"],
                    "profile_id": row["profile_id"],
                    "profile_date": profile_date.isoformat(),
                    "integration_depth_m": depth,
                },
            },
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": path_coords},
                "properties": {
                    "role": "backtrack_path",
                    "hours": hours,
                    "integration_depth_m": depth,
                    "speed_cms": stored["speed_cms"],
                    "steps_completed": stored["steps_completed"],
                },
            },
        ]

        # Resolve source contract if stored
        if stored["contractor_name"]:
            async with _pool.acquire() as conn:
                source_row = await conn.fetchrow(
                    """SELECT isa_id, resource_type, ST_AsGeoJSON(geom)::text AS geom_json
                       FROM mining_contracts WHERE contractor_name = $1 LIMIT 1""",
                    stored["contractor_name"],
                )
            if source_row:
                features.append({
                    "type": "Feature",
                    "geometry": json.loads(source_row["geom_json"]),
                    "properties": {
                        "role": "source_contract",
                        "contractor_name": stored["contractor_name"],
                        "isa_id": source_row["isa_id"],
                        "resource_type": source_row["resource_type"],
                    },
                })

        geojson = json.dumps({"type": "FeatureCollection", "features": features})
        _cache[cache_key] = (time.monotonic(), geojson)
        return Response(content=geojson, media_type="application/json")

    # ── No pre-computed data — live CMEMS backtrack ───────────────────────
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _backtrack(lon, lat, profile_date, depth, hours)
        )
    except CMEMSUnavailableError as e:
        raise HTTPException(status_code=503, detail={"detail": "CMEMS service unavailable", "error": str(e)})

    # Build path WKT for PostGIS
    if len(result.path) >= 2:
        coords_wkt = ", ".join(f"{p[0]} {p[1]}" for p in result.path)
        path_wkt = f"LINESTRING({coords_wkt})"
    else:
        path_wkt = None

    # PostGIS intersection check
    source_contract = None
    async with _pool.acquire() as conn:
        if path_wkt:
            source_row = await conn.fetchrow(
                """SELECT contractor_name, isa_id, resource_type,
                          ST_AsGeoJSON(geom)::text AS geom_json
                   FROM mining_contracts
                   WHERE ST_Intersects(
                       ST_SetSRID(ST_GeomFromText($1), 4326),
                       geom
                   )
                   LIMIT 1""",
                path_wkt,
            )
        else:
            source_row = None

        # Fallback: proximity check at origin (50 km)
        if not source_row:
            origin_lon, origin_lat = result.origin
            source_row = await conn.fetchrow(
                """SELECT contractor_name, isa_id, resource_type,
                          ST_AsGeoJSON(geom)::text AS geom_json
                   FROM mining_contracts
                   WHERE ST_DWithin(
                       ST_SetSRID(ST_Point($1, $2), 4326)::geography,
                       geom::geography,
                       50000
                   )
                   ORDER BY geom::geography <-> ST_SetSRID(ST_Point($1,$2),4326)::geography
                   LIMIT 1""",
                origin_lon, origin_lat,
            )

        if source_row:
            source_contract = {
                "contractor_name": source_row["contractor_name"],
                "isa_id": source_row["isa_id"],
                "resource_type": source_row["resource_type"],
                "geom_json": json.loads(source_row["geom_json"]),
            }

        # Store result in plume_paths for future instant lookups
        if result.steps_completed >= 2:
            contractor_name = source_contract["contractor_name"] if source_contract else None
            await conn.execute(
                """INSERT INTO plume_paths
                       (profile_id, platform_id, profile_date, origin_lon, origin_lat,
                        path_coords, speed_cms, steps_completed, source_dataset, contractor_name)
                   VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9, $10)
                   ON CONFLICT (profile_id) DO NOTHING""",
                argo_id, row["platform_id"], profile_date,
                result.origin[0], result.origin[1],
                json.dumps(result.path), result.speed_cms, result.steps_completed,
                "nrt", contractor_name,
            )

    # Build GeoJSON response
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "role": "argo_observation",
                "platform_id": row["platform_id"],
                "profile_id": row["profile_id"],
                "profile_date": profile_date.isoformat(),
                "integration_depth_m": depth,
            },
        },
        {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": result.path},
            "properties": {
                "role": "backtrack_path",
                "hours": hours,
                "integration_depth_m": depth,
                "speed_cms": result.speed_cms,
                "u_mean": result.u_mean,
                "v_mean": result.v_mean,
                "steps_completed": result.steps_completed,
            },
        },
    ]

    if source_contract:
        features.append({
            "type": "Feature",
            "geometry": source_contract["geom_json"],
            "properties": {
                "role": "source_contract",
                "contractor_name": source_contract["contractor_name"],
                "isa_id": source_contract["isa_id"],
                "resource_type": source_contract["resource_type"],
            },
        })

    geojson = json.dumps({"type": "FeatureCollection", "features": features})
    _cache[cache_key] = (time.monotonic(), geojson)
    return Response(content=geojson, media_type="application/json")


# ── Admin dashboard ───────────────────────────────────────────────────────────
# Accessible via Tailscale at http://<tailscale-host>:8765/admin/dashboard?token=TOKEN
# ADMIN_DASHBOARD_TOKEN and require_admin_token now live in auth.py (Task 3 of
# the backend vertical-split refactor) — see that module for why the rotation
# hazard requires readers to go through `auth.ADMIN_DASHBOARD_TOKEN`, never a
# name imported into this module's namespace.


# Maps sync_log source names → _SYNC_SOURCES action keys for dashboard buttons
_SOURCE_TO_ACTION: dict[str, str] = {
    "mining_contracts":       "arcgis",
    "reserved_areas":         "arcgis",
    "apeis":                  "arcgis",
    "relinquished_areas":     "arcgis",
    "argo_profiles":          "argo",
    "biodiversity_hotspots":  "obis",
    "hydrothermal_vents":     "vents",
    "eez":                    "eez",
    "protected_marine_sites": "protected-sites",
    "hotspot_grid":           "hotspot-grid",
    "species_cache":          "species-cache",
    "plume_paths":            "plumes",
    "oceansites":             "oceansites",
    "oceansites-obs":         "oceansites-obs",
    "onc":                    "onc",
    "onc-sensors":            "onc-sensors",
    "noise_cells":            "noise-risk",
    "cetacean_cells":         "noise-risk",
    "noise_risk":             "noise-risk",
    "chess":                  "chess",
    "seamounts":              "seamounts",
    "submarine_cables":       "cables",
    "onc_cables":             "onc-cables",
    "ooi_cables":             "ooi-cables",
    "noaa_cables":            "noaa-cables",
    "nz_cables":              "nz-cables",
    "au_cables":              "au-cables",
    "onc_instruments":        "onc-instruments",
    "onc_instruments_enrich": "onc-instruments-enrich",
    "port_locations":         "ports",
    "mining_footprints":      "land-mining",
    # "kbas" removed 2026-09-03 alongside the withdrawal (WITHDRAWN_LAYER_IDS
    # in startup_seeds.py) — same treatment as "wdpa". land-kbas stays in _SYNC_SOURCES below
    # so the periodic sync keeps the table fresh; only the admin "sync now"
    # button loses its friendly log-source mapping for a retired layer.
    "tailings":               "land-tailings",
    "tailings_enrich":        "land-tailings-enrich",
    "active_fires":           "land-fires",
    "air_quality":            "land-air-quality",
    "landslides":             "land-landslides",
    "dams":                   "land-dams",
    "water_risk":             "land-water-risk",
    "air_quality_readings":   "air-quality-readings",
    "vessel_events":          "vessel-events",
    "contractor_vessels":     "contractor-vessels",
    "ais_aois":               "ais-aois",
    "onc-sparklines":         "onc-sparklines",
    "onc-adcp":               "onc-adcp",
    "onc-ctd":                "onc-ctd",
    "usgs-earthquakes":       "usgs-earthquakes",
    "wod_profiles":           "wod",
    "pangaea_records":        "pangaea",
    "bco_dmo_datasets":       "bco-dmo",
    "noaa_datasets":          "noaa",
    "obis_seamap_records":    "seamap",
    "ncei_icoads_files":      "ncei",
    "sio_bic_records":        "sio-bic",
    "deepdata_occurrences":   "deepdata",
    "deepdata_stations":      "deepdata-stations",
    "mbari_vars_records":     "mbari-vars",
    "noaa_corals_records":    "noaa-corals",
    "worms":                  "worms",
    "acoustic_stations":      "acoustic-stations",
    "acoustic_soundscape":    "acoustic-soundscape",
    "cchdo_stations":         "cchdo",
    "offshore_activities":    "emodnet-offshore",
    "esdm":                   "esdm-indonesia",
    "pasa":                   "pasa-sa",
    "sodir_co2":              "sodir-co2",
    "nsta_co2":               "nsta-co2",
    "anh_co":                 "anh-colombia",
    "meei_tt":                "meei-trinidad",
    "pad_ie":                 "pad-ireland",
    "perupetro_pe":           "perupetro",
    "petrocom_gh":            "petrocom-ghana",
    "pmp_gy":                 "pmp-guyana",
    "biodiversity_hotspots_inat_reset": "reset-inat-images",
    "currents-surface":       "currents-surface",
    "currents-1000m":         "currents-1000m",
    "currents-backfill":      "currents-backfill",
    "woa-climatology":        "woa-climatology",
    "glodap-carbon":          "glodap-carbon",
    "acidification":          "acidification",
    "chi":                    "chi",
    "socat-co2":              "socat-co2",
    "seabed":                 "seabed",
    "oxygen-deox":            "oxygen-deox",
    "wod-oxygen":             "wod-oxygen",
    "memento":                "memento",
    "memento-flags":          "memento-flags",
    "geotraces":              "geotraces",
    "arctic-rivers":          "arctic-rivers",
    "permafrost-thaw":        "permafrost-thaw",
    "seaflea":                "seaflea",
    "sios":                   "sios",
    "arcade":                 "arcade",
    "bathymetry-stats":       "bathymetry-stats",
    "cascade":                "cascade",
    "mosaic":                 "mosaic",
    "vme-sdm":                "vme-sdm",
    "coral-acid-exposure":    "coral-acid-exposure",
}


_SYNC_SOURCES = {
    "arcgis":           lambda: isa.sync_arcgis_group(),
    "obis":             lambda: biodiversity.sync_biodiversity_hotspots(),
    "argo":             lambda: sensors.sync_argo_profiles(),
    "vents":            lambda: seafloor.sync_hydrothermal_vents(),
    "eez":              lambda: geo_context.sync_eez(),
    "protected-sites":  lambda: geo_context.sync_protected_marine_sites(),
    "claim-enrichment": lambda: isa.enrich_claim_boundaries(),
    "species-images":   lambda: biodiversity.enrich_species_images(batch_size=2000),
    "iucn-backfill":    lambda: biodiversity.backfill_iucn_categories(),
    "hotspot-grid":     lambda: biodiversity.rebuild_hotspot_grid(),
    "species-cache":    lambda: biodiversity.refresh_species_cache_logged(),
    "plumes":           lambda: _compute_plume_paths(_pool, max_batch=500),
    "oceansites":       lambda: sensors.sync_oceansites(),
    "oceansites-obs":   lambda: sensors.sync_oceansites_obs(),
    "onc":              lambda: onc.sync_onc(),
    "onc-sensors":      lambda: onc.sync_onc_sensors(),
    "noise-risk":       lambda: acoustic.sync_noise_risk(),
    "chess":            lambda: biodiversity.sync_chess(),
    "seamounts":        lambda: seafloor.sync_seamounts(),
    "cables":           lambda: cables.sync_submarine_cables(force=True),
    "onc-cables":       lambda: cables.sync_onc_cables(),
    "ooi-cables":       lambda: cables.sync_ooi_cables(),
    "noaa-cables":      lambda: cables.sync_noaa_cables(force=True),
    "nz-cables":        lambda: cables.sync_nz_cables(force=True),
    "au-cables":        lambda: cables.sync_au_cables(force=True),
    "onc-instruments":  lambda: onc.sync_onc_instruments(skip_guard_hours=0),
    "onc-instruments-enrich": lambda: onc.enrich_onc_instruments(),
    "ports":            lambda: geo_context.sync_port_locations(force=True),
    "air-quality-readings": lambda: _sync_air_quality_readings(),
    # ⛔ force=True on every cadence-gated land sync. Without it these entries
    # hit the same cadence gate as the scheduler and returned 0, while the
    # admin panel and the Mac staleness monitor both reported success.
    # `force` never reaches a Blocked source — should_sync() checks Blocked
    # first — so land-wdpa still refuses, which is the intended answer.
    "land-mining":      lambda: _sync_mining_footprints(force=True),
    "land-kbas":        lambda: _sync_kbas(force=True),
    "land-wdpa":        lambda: _sync_wdpa(force=True),
    "land-tailings":    lambda: _sync_tailings(force=True),
    "land-tailings-enrich": lambda: _enrich_tailings_from_grid(force=True),
    "land-fires":       lambda: _sync_active_fires(),
    "land-air-quality": lambda: _sync_air_quality(),
    "land-landslides":  lambda: _sync_landslides(force=True),
    "land-dams":        lambda: _sync_dams(force=True),
    "land-water-risk":  lambda: _sync_water_risk(force=True),
    "land-all":         lambda: sync_all_land_sources(),
    "land-overlaps":    lambda: refresh_overlap_views(),
    "vessel-events":          lambda: sync_vessel_events_stub(),
    "contractor-vessels":     lambda: auto_discover_contractors(),
    "ais-aois":               lambda: run_aoi_seed(),
    "ais-partitions":         lambda: run_partition_maintenance(),
    "vessel-reclassify":      lambda: __import__("sar_correlator").reclassify_dark_events(),
    "onc-sparklines":         lambda: onc.sync_onc_sparklines(),
    "onc-adcp":               lambda: onc.sync_onc_adcp_strips(),
    "onc-ctd":                lambda: onc.sync_onc_ctd_profiles(),
    "usgs-earthquakes":       lambda: onc.sync_usgs_earthquakes(),
    "monitoring-density-grid": lambda: refresh_monitoring_density(),
    "wod":              lambda: _sync_wod_profiles(),
    "pangaea":          lambda: _sync_pangaea_records(),
    "bco-dmo":          lambda: _sync_bco_dmo(),
    "noaa":             lambda: _sync_noaa_datasets(),
    "seamap":           lambda: _sync_obis_seamap(),
    "ncei":             lambda: _sync_ncei_icoads(),
    "sio-bic":          lambda: biodiversity.sync_sio_bic(),
    "deepdata":         lambda: biodiversity.sync_deepdata(),
    "deepdata-stations": lambda: biodiversity.sync_deepdata_stations(),
    "mbari-vars":       lambda: biodiversity.sync_mbari_vars(),
    "noaa-corals":      lambda: biodiversity.sync_noaa_corals(),
    "worms":            lambda: biodiversity.sync_worms_taxa(force=True),
    "acoustic-stations":   lambda: acoustic.sync_acoustic_stations(force=True),
    "acoustic-soundscape": lambda: acoustic.sync_acoustic_soundscape(force=True),
    "cchdo":            lambda: _sync_cchdo_cruises(),
    "all":              lambda: _sync_all_sources(),
    "emodnet-offshore":         lambda: offshore.sync_emodnet_offshore(),
    "boem-offshore":            lambda: offshore.sync_boem_offshore(),
    "crown-estate-wind":        lambda: offshore.sync_crown_estate_wind(),
    "nopta-petroleum":          lambda: offshore.sync_nopta_petroleum(),
    "nzpam-offshore":           lambda: offshore.sync_nzpam_offshore(),
    "anp-brazil":               lambda: offshore.sync_anp_brazil(),
    "sodir-petroleum":          lambda: offshore.sync_sodir_petroleum(),
    "nsta-petroleum":           lambda: offshore.sync_nsta_petroleum(),
    "cnh-mexico":               lambda: offshore.sync_cnh_mexico(),
    "crown-estate-scotland":    lambda: offshore.sync_crown_estate_scotland(),
    "esdm-indonesia":           lambda: offshore.sync_esdm_indonesia(),
    "pasa-sa":                  lambda: offshore.sync_pasa_sa(),
    "mra-png-dsm":              lambda: offshore.sync_mra_png_dsm(),
    "mme-namibia-dsm":          lambda: offshore.sync_mme_nam_dsm(),
    "sbma-cook-islands":        lambda: offshore.sync_sbma_ck(),
    "cnsopb":                   lambda: offshore.sync_cnsopb_petroleum(),
    "cnlopb":                   lambda: offshore.sync_cnlopb_petroleum(),
    "dea-dk":                   lambda: offshore.sync_dea_dk_petroleum(),
    "sodir-co2":               lambda: offshore.sync_sodir_co2(),
    "nsta-co2":                lambda: offshore.sync_nsta_co2(),
    "anh-colombia":            lambda: offshore.sync_anh_colombia(),
    "meei-trinidad":           lambda: offshore.sync_meei_trinidad(),
    "pad-ireland":             lambda: offshore.sync_pad_ireland(),
    "perupetro":               lambda: offshore.sync_perupetro(),
    "petrocom-ghana":          lambda: offshore.sync_petrocom_ghana(),
    "pmp-guyana":              lambda: offshore.sync_pmp_guyana(),
    "reset-inat-images":       lambda: biodiversity.reset_inat_images_for_reverification(),
    "currents-surface": lambda: fields.currents.sync_currents("surface"),
    "currents-1000m":   lambda: fields.currents.sync_currents("1000m"),
    "currents-backfill": lambda: _currents_backfill_task(force=True),
    "woa-climatology": lambda: fields.climatology.sync_woa(force=True),
    "glodap-carbon": lambda: fields.carbon.sync_glodap_carbon(force=True),
    "acidification": lambda: fields.carbon.sync_acidification(force=True),
    "chi": lambda: fields.habitat.sync_chi_impact(force=True),
    "socat-co2": lambda: fields.carbon.sync_socat_co2(force=True),
    "seabed": lambda: fields.habitat.sync_seabed(force=True),
    "oxygen-deox": lambda: fields.climatology.sync_oxygen_deox(force=True),
    "wod-oxygen": lambda: geochem.sync_wod_oxygen(force=True),
    "memento": lambda: geochem.sync_memento(force=True),
    # Derived-only: no credentials, no scrape. Safe to re-run at any time.
    "memento-flags": lambda: geochem.recompute_memento_atmospheric(),
    "geotraces": lambda: geochem.sync_geotraces(force=True),
    "arctic-rivers": lambda: arctic.sync_arctic_rivers_logged(),
    "permafrost-thaw": lambda: arctic.sync_permafrost_thaw_logged(force=True),
    "seaflea": lambda: geochem.sync_seaflea(force=True),
    "sios":    lambda: arctic.sync_sios(force=True),
    "arcade":  lambda: arctic.sync_arcade(force=True),
    "bathymetry-stats": lambda: seafloor.sync_bathymetry_stats(force=True),
    "cascade": lambda: arctic.sync_cascade(force=True),
    "mosaic": lambda: geochem.sync_mosaic(force=True),
    "vme-sdm": lambda: fields.habitat.sync_vme(force=True),
    "coral-acid-exposure": lambda: fields.carbon.sync_coral_exposure(force=True),
}


_running_syncs: dict[str, float] = {}  # source → start timestamp (monotonic)

# Serialize ALL sync work — only one sync runs at a time across both the
# weekly-chain path (_run_unless_paused) and the admin force-sync path
# (_run_tracked). Prevents the CPU pile-up that happens when concurrent
# admin Force Syncs (or a manual sync racing the weekly chain) stack
# expensive spatial joins on top of each other.
_sync_lock = asyncio.Lock()

# Cap CPU-heavy read endpoints (e.g. /v1/seo/concession/{isa_id}, which runs
# 5 spatial subqueries including a 5M-row ST_DWithin against
# biodiversity_hotspots) to at most 1 concurrent execution. SEO crawlers
# can trigger these in bursts; without this gate, ~3 concurrent requests
# pegged 3+ postgres cores.
_heavy_query_sem = asyncio.Semaphore(1)


async def _run_tracked(source: str, fn):
    """Wrap a sync coroutine. Serialized via _sync_lock so only one sync
    runs at a time across admin force-sync and weekly-chain paths."""
    async with _sync_lock:
        _running_syncs[source] = time.monotonic()
        try:
            await fn
        finally:
            _running_syncs.pop(source, None)


@app.get("/admin/sync/running", dependencies=[Depends(_require_admin_token)])
async def admin_sync_running():
    import time
    return {
        source: round(time.monotonic() - started)
        for source, started in _running_syncs.items()
    }


@app.post("/admin/sync/{source}", dependencies=[Depends(_require_admin_token)])
async def admin_sync_source(source: str):
    fn = _SYNC_SOURCES.get(source)
    if not fn:
        raise HTTPException(status_code=404, detail=f"Unknown source '{source}'. Valid: {list(_SYNC_SOURCES)}")
    if await is_sync_paused(source):
        raise HTTPException(status_code=409, detail=f"Sync '{source}' is paused. Unpause it first.")
    asyncio.create_task(_run_tracked(source, fn()))
    return {"status": "started", "source": source}


@app.post("/admin/sync/{source}/pause", dependencies=[Depends(_require_admin_token)])
async def admin_sync_pause(source: str):
    async with _pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO paused_syncs (action) VALUES ($1) ON CONFLICT DO NOTHING",
            source,
        )
    invalidate_paused_cache()
    log.info("Sync paused: %s", source)
    return {"status": "paused", "source": source}


@app.post("/admin/sync/{source}/unpause", dependencies=[Depends(_require_admin_token)])
async def admin_sync_unpause(source: str):
    async with _pool.acquire() as conn:
        await conn.execute("DELETE FROM paused_syncs WHERE action = $1", source)
    invalidate_paused_cache()
    log.info("Sync unpaused: %s", source)
    return {"status": "unpaused", "source": source}


@app.get("/admin/sync/paused", dependencies=[Depends(_require_admin_token)])
async def admin_sync_paused():
    paused = await _load_paused_syncs()
    return list(paused)


@app.post("/admin/cache/clear", dependencies=[Depends(_require_admin_token)])
async def admin_cache_clear():
    _cache.clear()
    for _domain in domains.CACHE_CLEARING_DOMAINS:
        _domain.clear_caches()
    return {"status": "cleared"}


# ---------------------------------------------------------------------------
# Layer-config admin endpoints
# ---------------------------------------------------------------------------

class _LayerConfigEntry(BaseModel):
    id: str
    order_idx: int | None = None
    default_on: bool | None = None
    modes: list[str] | None = None

class _LayerConfigPatch(BaseModel):
    updates: list[_LayerConfigEntry]


@app.get("/admin/layer-config", dependencies=[Depends(_require_admin_token)])
async def admin_get_layer_config():
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, order_idx, default_on, modes, updated_at, updated_by "
            "FROM layer_config ORDER BY order_idx"
        )
    return [
        {
            "id": r["id"],
            "order_idx": r["order_idx"],
            "default_on": r["default_on"],
            "modes": list(r["modes"]),
            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
            "updated_by": r["updated_by"],
        }
        for r in rows
    ]


@app.post("/admin/layer-config", dependencies=[Depends(_require_admin_token)])
async def admin_post_layer_config(body: _LayerConfigPatch, request: Request):
    global _layer_config_cache, _layer_config_cache_ts
    token_prefix = request.headers.get("X-Admin-Token", "")[:20]
    async with _pool.acquire() as conn:
        async with conn.transaction():
            for u in body.updates:
                await conn.execute(
                    """UPDATE layer_config
                          SET order_idx  = COALESCE($2, order_idx),
                              default_on = COALESCE($3, default_on),
                              modes      = COALESCE($4::text[], modes),
                              updated_at = now(),
                              updated_by = $5
                        WHERE id = $1""",
                    u.id, u.order_idx, u.default_on, u.modes, token_prefix,
                )
    _layer_config_cache = None
    _layer_config_cache_ts = 0.0
    return {"ok": True, "updated": len(body.updates)}


@app.get("/admin/dashboard", response_class=HTMLResponse, dependencies=[Depends(_require_admin_token)])
async def admin_dashboard():
    return HTMLResponse(
        "<h1>Admin dashboard moved</h1>"
        "<p>The operator dashboard is now the React super-admin panel at "
        "<code>/admin-ui/</code> (Tailscale-only). Token action-endpoints "
        "(<code>/admin/sync/*</code>, <code>/admin/cache/clear</code>) remain available.</p>",
        status_code=410,
    )


# ── Cookieless page-view tracking ────────────────────────────────────────────
# No cookies, no IP, no user-agent stored — just (date, path, count).
# GDPR-exempt: purely aggregate data with no way to identify individuals.

class PageViewBody(BaseModel):
    path: str

@app.post("/v1/pageview")
async def record_pageview(body: PageViewBody):
    """Increment the cookieless visit counter for today + path. No auth required."""
    # Normalise dynamic segments so /concession/ABC-123 → /concession
    import re
    path = body.path.strip() or "/"
    path = re.sub(r"/[a-zA-Z0-9_\-]{6,}$", "", path) or "/"
    path = path[:120]  # cap length
    async with _pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO pageviews (date, path, count)
            VALUES (CURRENT_DATE, $1, 1)
            ON CONFLICT (date, path) DO UPDATE SET count = pageviews.count + 1
        """, path)
    return {"ok": True}


@app.get("/v1/stats/pageviews", dependencies=[Depends(get_api_key)])
async def get_pageview_stats(days: int = 30):
    """Return daily page-view totals for the last N days (admin, API key required)."""
    days = min(max(days, 1), 365)
    async with _pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT date, path, count
            FROM pageviews
            WHERE date >= CURRENT_DATE - ($1 - 1)
            ORDER BY date DESC, count DESC
        """, days)
    by_date: dict = {}
    for r in rows:
        d = r["date"].isoformat()
        by_date.setdefault(d, {"total": 0, "paths": {}})
        by_date[d]["total"] += r["count"]
        by_date[d]["paths"][r["path"]] = r["count"]
    return {"days": days, "data": by_date}


# ── Public dataset inventory ────────────────────────────────────────────────
# Powers the "Data Inventory" tab in the legend. One row per DB table that is
# rendered on the map (or aggregated into a visible layer like Baseline
# Monitoring Density). Internal tables (sync_log, pageviews, *_cache, partition
# children, derived overlap views) are deliberately excluded.
#
# Schema: (key, label, group, table, sync_log_key, source_org, source_url)
#   key            - stable id used by the frontend
#   label          - human-facing row label
#   group          - section header in the rendered table
#   table          - the actual postgres table name (counted with count(*))
#   sync_log_key   - source key in sync_log (or None for live/derived tables)
# ── source_org values that must be COUNTED, never typed ─────────────────────
# `"16 government registries"` sat in the table below until 2026-08-27. By then
# the ingest fed 26 source tags across 40 sovereigns, so the public site was
# understating its own coverage by ten — on the one layer that is the best
# evidence of what this platform does. The defect was not the number; it was
# that a number was typed at all. Replacing it with a fresher typed number
# would rot exactly the same way, just later.
#
# ⚠️ THREE different true numbers live here and they are NOT interchangeable:
#     26   distinct `source` tags in domains/offshore.py — FEEDS, not agencies
#          (`sodir`+`sodir_co2` and `nsta`+`nsta_co2` are one authority each)
#     ~24  distinct authorities — needs a dedup rule we do not store anywhere
#     40   distinct sovereigns in the live data — what the country filter offers
# We publish sovereigns. It is the only one of the three a visitor can read
# without knowing our schema, and it is the one the public API already returns.
#
# ⛔ The predicate MUST stay byte-identical to the one in
# routers/spatial_v2.py::offshore_activities_countries. Drop the
# name/operator clause and this label reads 41 while the filter offers 40 —
# a contradiction on the same screen.
_COUNTED = "\u0000counted\u0000"  # placeholder; resolved in get_dataset_counts

_COUNTED_ORG: dict[str, tuple[str, str]] = {
    "offshore": (
        """SELECT count(DISTINCT sovereign)::int AS n
             FROM offshore_activities
            WHERE sovereign IS NOT NULL
              AND (name IS NOT NULL OR operator IS NOT NULL)
              -- This table is deliberately multi-type. Counting without this
              -- filter mixes oil, gas, wind, mining and CCS into one figure.
              AND activity_type IN ('oil_gas', 'offshore_wind', 'seabed_mining', 'ccs_storage')""",
        "Government registries \u2014 {n} countries",
    ),
}
# Used when the count query fails. Less specific, still true — the one thing it
# must never do is fall back to a hardcoded number.
_COUNTED_ORG_FALLBACK = "Government registries"


_INVENTORY: list[tuple[str, str, str, str, str | None, str, str]] = [
    # ── Ocean — biodiversity & oceanography ─────────────────────────────────
    ("obis",           "OBIS deep-sea occurrences",     "ocean-bio", "biodiversity_hotspots",  "biodiversity_hotspots", "OBIS / UNESCO-IOC",                       "https://obis.org/"),
    ("chess",          "ChEssBase chemosynthetic sites","ocean-bio", "chess_occurrences",      "chess",                 "ChEssBase via GBIF",                      "https://doi.org/10.15468/6v6ug8"),
    ("vents",          "Hydrothermal vents",            "ocean-bio", "hydrothermal_vents",     "hydrothermal_vents",    "InterRidge / PANGAEA",                    "https://doi.org/10.1594/PANGAEA.917894"),
    ("seamounts",      "Seamounts",                     "ocean-bio", "seamounts",              "seamounts",             "Yesson et al. 2020 / PANGAEA",            "https://doi.org/10.1594/PANGAEA.921688"),
    ("argo",           "Argo profiling floats",         "ocean-bio", "argo_profiles",          "argo_profiles",         "Argo Programme via Argovis",              "https://argo.ucsd.edu/"),
    ("oceansites",     "OceanSITES moorings",           "ocean-bio", "oceansites_stations",    "oceansites",            "OceanSITES via OceanOPS",                 "https://www.ocean-ops.org/oceansites/"),
    ("onc-locations",  "ONC observatory locations",     "ocean-bio", "onc_locations",          "onc-sensors",           "Ocean Networks Canada",                   "https://www.oceannetworks.ca/"),
    ("onc-instruments","ONC instruments",               "ocean-bio", "onc_instruments",        "onc_instruments",       "Ocean Networks Canada",                   "https://www.oceannetworks.ca/"),

    # ── Ocean — Baseline Monitoring Density underlying sources ──────────────
    ("wod",            "World Ocean Database (WOD)",    "ocean-monitoring", "wod_profiles",        "wod_profiles",       "NOAA NCEI",                              "https://www.ncei.noaa.gov/products/world-ocean-database"),
    ("pangaea",        "PANGAEA research cruises",      "ocean-monitoring", "pangaea_records",     "pangaea_records",    "PANGAEA (AWI / MARUM)",                  "https://www.pangaea.de/"),
    ("bco-dmo",        "BCO-DMO ocean cruises",         "ocean-monitoring", "bco_dmo_datasets",    "bco_dmo_datasets",   "BCO-DMO (US NSF)",                       "https://www.bco-dmo.org/"),
    ("noaa-datasets",  "NOAA DataCite ocean surveys",   "ocean-monitoring", "noaa_datasets",       "noaa_datasets",      "NOAA via DataCite",                      "https://www.noaa.gov/"),
    ("obis-seamap",    "OBIS-SEAMAP cetaceans/pinnipeds","ocean-monitoring","obis_seamap_records", "obis_seamap_records","OBIS-SEAMAP (Duke University)",          "https://seamap.env.duke.edu/"),
    ("cchdo",          "CCHDO / GO-SHIP repeat hydrography","ocean-monitoring","cchdo_stations",   "cchdo_stations",     "CCHDO / GO-SHIP",                        "https://cchdo.ucsd.edu/"),
    ("sio-bic",        "SIO Benthic Invertebrate Collection","ocean-monitoring","sio_bic_records", "sio-bic",            "Scripps Institution of Oceanography",     "https://scripps.ucsd.edu/benthic-invertebrate-collection"),
    ("deepdata",       "ISA DeepData (contractor environmental reports)","ocean-monitoring","deepdata_occurrences","deepdata","International Seabed Authority via OBIS","https://data.isa.org.jm/"),
    ("deepdata-stations","DeepData sampling stations (platform analysis)","ocean-monitoring","deepdata_stations","deepdata-stations","Platform-derived from ISA DeepData via OBIS DwC archives","https://datasets.obis.org/hosted/isa/index.html"),
    ("mbari-vars",     "MBARI VARS deep-sea ROV observations","ocean-monitoring","mbari_vars_records","mbari-vars","Monterey Bay Aquarium Research Institute via OBIS","https://www.mbari.org/data/"),
    ("noaa-corals",    "NOAA Deep-Sea Coral & Sponge observations","ocean-monitoring","noaa_corals_records","noaa-corals","NOAA Deep Sea Coral Research & Technology Program","https://deepseacoraldata.noaa.gov/"),
    ("acoustic-stations", "Hydrophone stations from observatory networks", "ocean-monitoring",
     "acoustic_stations", "acoustic-stations",
     "OOI + IMOS + MBARI MARS",
     "https://oceanobservatories.org/"),

    # ── Ocean — regulatory & boundaries ─────────────────────────────────────
    ("isa-contracts",  "ISA exploration contracts",     "ocean-reg", "mining_contracts",       "mining_contracts",      "International Seabed Authority",          "https://www.isa.org.jm/exploration-contracts/"),
    ("isa-relinq",     "ISA relinquished areas",        "ocean-reg", "relinquished_areas",     "relinquished_areas",    "International Seabed Authority",          "https://isa.org.jm/exploration-contracts/exploration-areas/"),
    ("isa-reserved",   "ISA reserved areas",            "ocean-reg", "reserved_areas",         "reserved_areas",        "International Seabed Authority",          "https://www.isa.org.jm/exploration-contracts/reserved-areas/"),
    ("isa-apei",       "ISA APEIs (env. management)",   "ocean-reg", "isa_apeis",              "apeis",                 "International Seabed Authority",          "https://www.isa.org.jm/protection-of-the-marine-environment/"),
    ("offshore",       "Offshore activities (oil/gas/wind)","ocean-reg","offshore_activities", "offshore_activities",   _COUNTED,                                  "https://emodnet.ec.europa.eu/en/human-activities"),
    ("eez",            "EEZ boundaries",                "ocean-reg", "maritime_boundaries",    "eez",                   "MarineRegions.org (VLIZ)",                "https://www.marineregions.org/eez.php"),
    ("unesco-mab",     "UNESCO marine heritage sites",  "ocean-reg", "protected_marine_sites", "protected_marine_sites","UNESCO World Heritage Marine Programme",  "https://whc.unesco.org/en/marine-programme/"),
    ("cables-emodnet", "Submarine cables — EMODnet",    "ocean-reg", "submarine_cables",       "submarine_cables",      "EMODnet Human Activities",                "https://emodnet.ec.europa.eu/en/human-activities"),
    ("cables-onc",     "Submarine cables — ONC",        "ocean-reg", "onc_cables",             "onc_cables",            "Ocean Networks Canada",                   "https://www.oceannetworks.ca/observatories/"),
    ("cables-ooi",     "Submarine cables — OOI",        "ocean-reg", "ooi_cables",             "ooi_cables",            "OOI Regional Cabled Array",               "https://github.com/oceanobservatories/asset-management"),
    ("cables-noaa",    "Submarine cables — NOAA",       "ocean-reg", "noaa_cables",            "noaa_cables",           "NOAA Marine Cadastre (joint NOAA/BOEM)",  "https://marinecadastre.gov/"),
    ("cables-nz",      "Submarine cables — NZ LINZ",    "ocean-reg", "nz_cables",              "nz_cables",             "LINZ NZ Hydrographic",                    "https://data.linz.govt.nz/layer/51643"),
    ("cables-au",      "Submarine cables — AU ACMA",    "ocean-reg", "au_cables",              "au_cables",             "ACMA / Geoscience Australia (AODN)",      "https://www.cmar.csiro.au/geoserver/web/"),
    ("ports",          "Global ports",                  "ocean-reg", "port_locations",         "port_locations",        "tayljordan/ports",                        "https://github.com/tayljordan/ports"),

    # ── Land ────────────────────────────────────────────────────────────────
    ("mining-foot",    "Global mining footprints",      "land",      "mining_footprints",      "mining_footprints",     "Maus et al. 2022/2023 — PANGAEA",         "https://doi.org/10.1594/PANGAEA.942325"),
    ("tailings",       "Tailings dams",                 "land",      "tailings_dams",          "tailings",              "GRID-Arendal / UNEP",                     "https://tailing.grida.no/"),
    ("fires",          "Active fires (rolling 24h)",    "land",      "active_fires",           "active_fires",          "NASA FIRMS (MODIS / VIIRS)",              "https://firms.modaps.eosdis.nasa.gov/"),
    ("landslides",     "Landslides",                    "land",      "landslides",             "landslides",            "NASA COOLR / GSFC",                       "https://gpm.nasa.gov/landslides/"),
    ("openaq",         "Air quality stations",          "land",      "air_quality_stations",   "air_quality",           "OpenAQ v3",                               "https://openaq.org/"),
    ("water-risk",     "Water risk sub-basins",         "land",      "water_risk",             "water_risk",            "WRI Aqueduct 4.0",                        "https://www.wri.org/aqueduct"),
    ("dams",           "Global Dam Watch",              "land",      "dams",                   "dams",                  "Global Dam Watch",                        "https://www.globaldamwatch.org/"),
    ("earthquakes",    "Earthquakes (M≥3, 30 days)",    "land",      "usgs_earthquakes",       "usgs-earthquakes",      "USGS Earthquake Hazards Program",         "https://earthquake.usgs.gov/"),

    # ── Added 2026-07-08: standalone map layers previously missing from the inventory ──
    ("memento",         "MEMENTO (marine CH₄/N₂O)",          "ocean-bio", "memento_casts",           "memento",         "GEOMAR MEMENTO (Kock & Bange 2015)",              "https://portal.geomar.de/memento"),
    ("methane-seeps",   "Methane seeps (SEAFLEA)",           "ocean-bio", "seaflea_seeps",           "seaflea",         "SEAFLEA / NOAA NCEI (Phrampus et al. 2020)",      "https://doi.org/10.1029/2019GC008747"),
    ("geotraces",       "Trace metals (GEOTRACES IDP2025)",  "ocean-bio", "geotraces_stations",      "geotraces",       "GEOTRACES IDP2025 via BODC",                      "https://www.bodc.ac.uk/geotraces/"),
    ("wod-oxygen",      "Historical oxygen profiles (WOD)",  "ocean-bio", "wod_oxygen_profiles",     "wod-oxygen",      "NOAA NCEI — World Ocean Database 2023",           "https://www.ncei.noaa.gov/products/world-ocean-database"),
    ("cascade",         "Arctic sediment carbon (CASCADE)",  "ocean-bio", "cascade_stations",        "cascade",         "CASCADE v2 — Bolin Centre (Martens et al. 2021)", "https://doi.org/10.17043/cascade-2"),
    ("sios",            "SIOS Svalbard observing datasets",  "ocean-bio", "sios_datasets",           "sios",            "SIOS METSIS catalogue",                           "https://sios-svalbard.org/"),
    ("mosaic",          "Marine sediment carbon (MOSAIC)",   "ocean-bio", "mosaic_cores",            "mosaic",          "MOSAIC — ETH Zürich (Van der Voort et al. 2021)", "https://doi.org/10.5168/mosaic019.1"),
    ("arctic-rivers",   "Arctic river inputs",               "land",      "arctic_river_stations",   "arctic-rivers",   "ArcticGRO + PANGAEA",                             "https://arcticgreatrivers.org/data/"),
    ("arctic-catchments","Arctic catchments (ARCADE)",       "land",      "arctic_catchments",       "arcade",          "ARCADE v1 — DataVerse NL",                        "https://doi.org/10.34894/U9HSPV"),
    ("permafrost-thaw", "Permafrost thaw features",          "land",      "permafrost_thaw_features","permafrost-thaw", "Webb et al. 2026 + ARTS v6.0.0",                  "https://doi.org/10.5281/zenodo.16996415"),
]

_GROUP_LABELS: dict[str, str] = {
    "ocean-bio":        "Ocean — biodiversity & oceanography",
    "ocean-monitoring": "Ocean — monitoring density sources",
    "ocean-reg":        "Ocean — regulatory & boundaries",
    "land":             "Land",
}

_dataset_counts_cache: dict | None = None
_dataset_counts_cache_at: float = 0.0
_DATASET_COUNTS_TTL = 600  # 10 min


@app.get("/v1/stats/dataset-counts")
async def get_dataset_counts():
    """Public — per-table object counts for the Data Inventory legend tab.
    Single UNION ALL query, in-memory cached for 10 min so a cold load on the
    biodiversity_hotspots table (~26M rows, count(*) takes seconds) doesn't
    fire on every page open.
    """
    global _dataset_counts_cache, _dataset_counts_cache_at
    now = time.time()
    if _dataset_counts_cache and (now - _dataset_counts_cache_at) < _DATASET_COUNTS_TTL:
        return _dataset_counts_cache

    union_sql = " UNION ALL ".join(
        f"SELECT '{key}' AS k, count(*)::bigint AS c FROM {table}"
        for (key, _, _, table, *_rest) in _INVENTORY
    )
    async with _pool.acquire() as conn:
        count_rows = await conn.fetch(union_sql)
        sync_rows = await conn.fetch("SELECT source, last_synced_at FROM sync_log")
        # Resolved per request, on the same connection. A failure here must
        # degrade the one label, never the whole inventory tab.
        counted_orgs: dict[str, str] = {}
        for key, (sql, template) in _COUNTED_ORG.items():
            try:
                counted_orgs[key] = template.format(n=await conn.fetchval(sql))
            except Exception as exc:  # noqa: BLE001 — one label, not the page
                log.warning("dataset-counts: counted source_org for %s failed: %s", key, exc)
                counted_orgs[key] = _COUNTED_ORG_FALLBACK

    counts = {r["k"]: int(r["c"]) for r in count_rows}
    syncs = {r["source"]: r["last_synced_at"] for r in sync_rows}

    groups: dict[str, dict] = {}
    for (key, label, group, table, sync_key, source_org, source_url) in _INVENTORY:
        last = syncs.get(sync_key) if sync_key else None
        item = {
            "key": key,
            "label": label,
            "table": table,
            "count": counts.get(key, 0),
            "source_org": counted_orgs.get(key, source_org) if source_org is _COUNTED else source_org,
            "source_url": source_url,
            "last_synced_at": last.isoformat() if last else None,
        }
        groups.setdefault(group, {"id": group, "label": _GROUP_LABELS.get(group, group), "items": []})
        groups[group]["items"].append(item)

    total = sum(counts.values())
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_objects": total,
        "total_layers": len(_INVENTORY),
        "groups": list(groups.values()),
    }
    _dataset_counts_cache = result
    _dataset_counts_cache_at = now
    return result


@app.get("/health")
async def health():
    async with _pool.acquire() as conn:
        sources = await conn.fetch(
            "SELECT source, last_synced_at, records_added, total_records FROM sync_log ORDER BY source"
        )
    return {
        "status": "ok",
        "schema": SCHEMA_STATE,
        "sync": [
            {
                "source": r["source"],
                "last_synced_at": r["last_synced_at"].isoformat() if r["last_synced_at"] else None,
                "records_added": r["records_added"],
                "total_records": r["total_records"],
            }
            for r in sources
        ],
    }
