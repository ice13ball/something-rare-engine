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
# The background-task registry (43 tasks, each labelled web/worker/both) and
# its shared helpers now live in scheduling.py — backend/worker.py imports
# that module directly, never this one, so starting the worker process
# cannot construct the FastAPI `app` below. See scheduling.py's docstring.
# _held_sync_lock is NOT imported here any more: nothing in main.py takes the
# sync lock since /admin/sync/{source} stopped running syncs in this process.
from scheduling import (
    _watch, TaskContext, tasks_for_role,
    _run_argo_history_backfill, _currents_backfill_task, _sync_all_sources,
)
import sync_queue
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
from fastapi.middleware.gzip import GZipMiddleware
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

_hotspot_grid_lock = asyncio.Lock()  # prevents concurrent rebuilds stacking up
_layer_config_cache:   str | None = None
_layer_config_cache_ts: float = 0.0
_startup_profiles_cache: bytes | None = None
_startup_profiles_cache_ts: float = 0.0

GBIF_SPECIES_URL = "https://api.gbif.org/v1/species/{key}"


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


# ── App lifecycle ─────────────────────────────────────────────────────────────

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
    # Record the DSN next to the pool, so anything needing a connection
    # outside the pool reaches the same database rather than re-reading the
    # environment on its own. See db.dsn.
    _db.dsn = os.environ["DATABASE_URL"]

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
        # Load paused syncs into memory cache before any sync tasks start
        await _load_paused_syncs()
        # ── Registry-driven task startup ──────────────────────────────────
        # ABYSSAL_ROLE ("web" | "worker" | "all", default "all") decides which
        # of the tasks in scheduling.TASK_REGISTRY actually start. "all" is
        # today's behaviour (every task below started, unconditionally) —
        # the default, so local dev and the pre-split test suite are
        # unaffected by this switch's existence. See scheduling.py's module
        # docstring for how this relates to ABYSSAL_STANDBY above (a fourth,
        # orthogonal axis: "run zero tasks", not a fourth role) and for the
        # per-task web/worker/both rationale — that IS the wiring; this loop
        # only asks it "for this role, what should start".
        _geoip = load_geoip()
        role = os.environ.get("ABYSSAL_ROLE", "all")
        ctx = TaskContext(log_pipe=_log_pipe, geoip=_geoip)
        wanted = tasks_for_role(role)
        for spec in wanted:
            asyncio.create_task(spec.factory(ctx), name=spec.name).add_done_callback(_watch)
        log.info("ABYSSAL_ROLE=%s — started %d background task(s): %s",
                 role, len(wanted), ", ".join(t.name for t in wanted))
    yield
    await _pool.close()

from api_access.logging_mw import LogPipe, RequestLogMiddleware
_log_pipe = LogPipe()

app = FastAPI(title="Abyssal Claims API", lifespan=lifespan)

# ⛔ Compress before the response leaves this box. Added 2026-09-09, after
# /v1/map/argo/trails started returning 500 in the browser while this backend
# logged 200:
#
#     backend  -> HTTP 200, 42,029,422 bytes (40.1 MB), 44,780 points
#     browser  -> HTTP 500, 0 bytes
#
# Cloud Run caps a response at 32 MiB and enforces it on the bytes it receives
# from the origin, BEFORE the BFF's Express compression() runs. So the cap bites
# on the uncompressed payload — a question an earlier comment in
# domains/sensors.py explicitly left unverified; this incident answered it.
#
# The trigger was filling the six-month history floor: the 90-day map window
# went from 14,870 points (13.98 MB) to 44,780 (40.1 MB) in one afternoon. The
# same growth is coming for every layer whose coverage improves, which is why
# this belongs on the app rather than on one endpoint.
#
# GeoJSON compresses ~7x (repeated keys), so 40 MB leaves here as ~6 MB.
# minimum_size skips the small responses, where the CPU is not worth it.
app.add_middleware(GZipMiddleware, minimum_size=1024)
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


def prune_dead_profile_layers(
    profiles: list[dict], live: set[str]
) -> tuple[list[dict], list[str]]:
    """Drop layers a profile names that are no longer enabled, and hide a profile
    left with none.

    A startup profile is the first thing a new visitor clicks. Nothing kept its
    layer list in step with `layer_config`: switching a layer off left every
    profile still offering it, so the visitor got a mode that turns two layers
    on and shows an empty map. That is exactly the failure this codebase treats
    as worse than no feature — it looks like it worked.

    ⛔ An EMPTY `live` set is refused, not obeyed. If the layer_config read
    returns nothing — a failed query, a fresh database, a typo in the status
    filter — then "no layer is alive" is indistinguishable from "every layer is
    dead", and obeying it would hide every profile and blank the welcome screen
    for everyone. Non-empty is asserted before any set difference is taken.

    Returns the profiles to serve plus a list of notes naming what was removed,
    so the caller can log it. A silent prune would swap one invisible problem
    for another.
    """
    if not live:
        return profiles, ["layer_config yielded no enabled layers — prune skipped"]

    kept: list[dict] = []
    notes: list[str] = []
    for p in profiles:
        gone = [l for l in p["layers"] if l not in live]
        if not gone:
            kept.append(p)
            continue
        alive = [l for l in p["layers"] if l in live]
        notes.append(f"{p['id']}: dropped {', '.join(gone)}")
        if alive:
            kept.append({**p, "layers": alive})
        else:
            notes.append(f"{p['id']}: hidden — no enabled layer left")
    return kept, notes


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
        live = {r["id"] for r in await conn.fetch(
            "SELECT id FROM layer_config WHERE status = 'enabled'")}
    profiles_out, notes = prune_dead_profile_layers(json.loads(serialize_profiles(rows)), live)
    for n in notes:
        log.warning("startup-profiles: %s", n)
    data = json.dumps(profiles_out).encode()
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


def _sync_dates(rows) -> dict[str, str]:
    """source → the DATE we last completed a sync, for the freshness display.

    ⛔ `last_synced_at` is NULL for a source that has never completed one.
    `log_sync_skipped` records the attempt and its reason WITHOUT stamping a
    time, on purpose: a missing-credential skip that stamped NOW() would read
    as freshly synced forever, which is worse than silence because silence at
    least ages.

    Calling `.date()` on that NULL raised AttributeError and took the WHOLE
    endpoint down with it — so one never-completed source (sbma-cook-islands)
    blanked the freshness date of every OTHER layer in the legend. Seen in
    production 2026-09-14.

    A source with no date is omitted rather than given a placeholder; the
    frontend renders a missing key as "no date known", which is what it is.
    """
    return {r["source"]: r["last_synced_at"].date().isoformat()
            for r in rows if r["last_synced_at"] is not None}


@app.get("/v1/sync/status", dependencies=[Depends(get_api_key)])
async def get_sync_status():
    """Return last sync timestamp per source — used by frontend for data freshness display."""
    async with _pool.acquire() as conn:
        rows = await conn.fetch("SELECT source, last_synced_at FROM sync_log ORDER BY source")
    return _sync_dates(rows)


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
    "onc-ctd-series":         "onc-ctd-series",
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


# The force-sync source table moved to sync_sources.py so the WORKER process
# can reach it without importing main.py (which would construct the FastAPI
# app). Re-exported under the original private name: routers/admin_layers_api.py
# and scripts/refactor_gate.py both read `main._SYNC_SOURCES`.
from sync_sources import SYNC_SOURCES as _SYNC_SOURCES


# ⛔ There is no `_running_syncs` dict any more, and reintroducing one would
# undo this whole change. It was process-local; after the web/worker split the
# forced sync runs in the worker while this endpoint is served by web, so a dict
# in either process can only describe half the system. The state lives in the
# `running_syncs` table, written by scheduling._held_sync_lock.
#
# _sync_lock (and the _held_sync_lock helper in scheduling.py) still serializes
# syncs WITHIN a process — see that module's comment on _sync_lock.

# Cap CPU-heavy read endpoints (e.g. /v1/seo/concession/{isa_id}, which runs
# 5 spatial subqueries including a 5M-row ST_DWithin against
# biodiversity_hotspots) to at most 1 concurrent execution. SEO crawlers
# can trigger these in bursts; without this gate, ~3 concurrent requests
# pegged 3+ postgres cores.
_heavy_query_sem = asyncio.Semaphore(1)


@app.get("/admin/sync/running", dependencies=[Depends(_require_admin_token)])
async def admin_sync_running():
    """Running, queued and stale syncs — across BOTH processes.

    ⚠️ Shape contract, kept on purpose: the top level is still
    `{source: seconds}` for syncs that are demonstrably running, because the
    staleness monitor on Michal's Mac polls this endpoint every 30 s for up to
    20 minutes and parses exactly that. The two new facts arrive as sibling
    keys, `_queued` and `_stale` — chosen over a second endpoint precisely
    because the monitor polls THIS one, and a queued-but-never-claimed request
    that only showed up somewhere else would still be invisible to it. No sync
    source name begins with an underscore, so the keys cannot collide.

    See sync_queue.running_snapshot for why a stale row is reported rather than
    trusted or deleted.
    """
    return await sync_queue.running_snapshot()


@app.post("/admin/sync/{source}", dependencies=[Depends(_require_admin_token)])
async def admin_sync_source(source: str):
    """Queue a force-sync for the worker. ⛔ Does NOT run it here.

    This used to be `asyncio.create_task(_run_tracked(source, fn()))`, which
    after the web/worker split would run a multi-gigabyte bake inside the
    process that serves tiles — the exact starvation the split exists to
    remove. Restoring that line re-breaks it; the guard is
    tests/test_sync_queue.py.

    ⛔ The answer is `queued`, not `started`. On 2026-09-17 this endpoint
    replied `{"status":"started"}` for sio-bic, nothing ever appeared in
    /admin/sync/running, and the data never moved — the operator had no way to
    tell "queued" from "lost". A web process that has not started anything must
    not claim it has.
    """
    fn = _SYNC_SOURCES.get(source)
    if not fn:
        raise HTTPException(status_code=404, detail=f"Unknown source '{source}'. Valid: {list(_SYNC_SOURCES)}")
    if await is_sync_paused(source):
        raise HTTPException(status_code=409, detail=f"Sync '{source}' is paused. Unpause it first.")
    request_id = await sync_queue.enqueue(source)
    return {"status": "queued", "source": source, "request_id": request_id}


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
    ("fires",          "Active fires (rolling 24h)",    "land",      "active_fires",           "active_fires",          "NASA FIRMS (VIIRS: Suomi-NPP, NOAA-20, NOAA-21)",              "https://firms.modaps.eosdis.nasa.gov/"),
    ("landslides",     "Landslides",                    "land",      "landslides",             "landslides",            "NASA COOLR / GSFC",                       "https://gpm.nasa.gov/landslides/"),
    ("openaq",         "Air quality stations",          "land",      "air_quality_stations",   "air_quality",           "OpenAQ v3",                               "https://openaq.org/"),
    ("water-risk",     "Water risk sub-basins",         "land",      "water_risk",             "water_risk",            "WRI Aqueduct 4.0",                        "https://www.wri.org/aqueduct"),
    ("dams",           "Global Dam Watch",              "land",      "dams",                   "dams",                  "Global Dam Watch — GOODD v2 (locations only)", "https://www.globaldamwatch.org/"),
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
