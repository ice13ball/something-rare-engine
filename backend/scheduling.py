# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""The background-task registry.

Every periodic/one-shot job that used to live inline in `main.py`'s
`lifespan()` `else` branch lives here instead, together with an explicit
`TASK_REGISTRY` that labels each one `web`, `worker`, or `both`.

⛔ This module must NEVER import `fastapi` or `main` — `backend/worker.py`
imports this module directly (never `main`) precisely so that starting the
worker process cannot construct the FastAPI `app` or bind a port. `main.py`
imports from here too, for `lifespan()`.

## Why three roles, and why they are not the same as ABYSSAL_STANDBY

`ABYSSAL_ROLE` (`web` | `worker` | `all`, default `all`) decides which of the
tasks below actually start. `ABYSSAL_STANDBY=1` is a DIFFERENT axis — it is
"serve reads, run NOTHING", used only for the ~30s window an old process
overlaps a new one during a deploy. The three states relate like this:

    ABYSSAL_STANDBY=1                 → run zero tasks (regardless of ROLE)
    ABYSSAL_STANDBY unset, ROLE=web    → run only `web`/`both` tasks
    ABYSSAL_STANDBY unset, ROLE=worker → run only `worker`/`both` tasks
    ABYSSAL_STANDBY unset, ROLE=all    → run every task (today's behaviour;
                                          the default, so local dev and the
                                          existing test suite are unaffected)

`main.py` still owns the ABYSSAL_STANDBY check; this module only answers
"given a role, which tasks does that role want".

## The classification rule

- Fills or drains a per-process object (`_log_pipe`'s `asyncio.Queue`, a
  module-level `str | None` response cache, an in-process `asyncio.Lock`)
  that ALSO matters to the web process → `web` (or `both` if the worker
  needs it too).
- Talks only to Postgres or an external HTTP API, with no per-process state
  another process must see → `worker`.
- Cheap, read-only, and harmless to run twice → `both`, called out why.

⚠️ **Known gap this split introduces, NOT fixed here** (out of scope: fixing
either needs a cross-process invalidation signal or removing a cache layer,
both changes to files this task must not touch): several `worker` tasks
below call a sync/bake function that also does
`global _xxx_cache; _xxx_cache = None` to invalidate an in-process cache read
by a **web-only** GET endpoint (`/v1/woa/meta`, `/v1/carbon/meta`,
`/v1/co2/meta`, `/v1/seabed/meta`, `/v1/vme/meta`, the coral-acid-exposure
response cache, the bathymetry-grid sampler's `_cache["grid"]`, and
`vessel_events._vessel_events_cache`). Today, invalidator and reader share a
process, so this works. Once the worker runs these bakes alone, the
invalidation clears the WORKER's copy of that module global — which nothing
ever reads — while the WEB process's copy (the one `GET` actually serves)
keeps the pre-bake payload until the web process itself restarts. This is
staleness, not corruption (the underlying DB/disk state is correct), but it
is a real behaviour change from single-process life. Every task below that
carries this caveat says so in its own comment.
"""

from __future__ import annotations

import asyncio
import logging
import os
import resource
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

import db
import sync_queue
from ingestion.cadence import should_sync
from sync_log import is_sync_paused, log_sync as _log_sync

from domains import acoustic, arctic, biodiversity, cables, fields
from domains import geo_context, geochem, isa, offshore, onc, seafloor, sensors

from land_layers import (
    _sync_air_quality_readings,
    refresh_monitoring_density,
    sync_all_land_sources,
)
from vessel_events import auto_discover_contractors
import services.currents_bake as currents_bake
from services import woa_climatology
from services.bathymetry_grid_export import bake_bathymetry_grid
from services.plume_history import compute_pending_plume_paths as _compute_plume_paths
from services.species_cache import refresh_species_cache
from offshore_tile_baker import schedule_bake as _schedule_offshore_tile_bake
from api_access.logging_mw import batch_writer

log = logging.getLogger(__name__)


# ── Shared context passed to every factory ────────────────────────────────────
# Only `web` tasks (batch_writer) actually read `log_pipe`/`geoip`. Every other
# factory ignores `ctx` and reaches `db.pool` directly — `db.pool` is set by
# whichever process (web's lifespan() or worker.py's main()) starts first, and
# is guaranteed set before any task in this registry is created.
@dataclass
class TaskContext:
    log_pipe: Any = None
    geoip: Any = None


def _watch(task: asyncio.Task) -> None:
    if not task.cancelled() and (exc := task.exception()) is not None:
        log.error("Background task '%s' crashed", task.get_name(), exc_info=exc)


# ── Cadence constants (moved verbatim from main.py) ───────────────────────────

SYNC_INTERVAL_SECONDS = 7 * 24 * 3600  # weekly

# Argo sync cadence — used only by _argo_sync_task (the sync body it calls
# lives in domains/sensors.py).
ARGO_SYNC_INTERVAL_SECONDS = 12 * 3600   # 12 hours
# The six-month floor is repair work, not freshness — a settled window returns
# nothing and the pass is cheap. Six-hourly so a gap closes within a day.
ARGO_HISTORY_FLOOR_INTERVAL_SECONDS = 6 * 3600

# The full-history walk (1997..today) had no cadence at all until 2026-09-15.
# Measured on production that day: argo_profiles held 1999..2007 and 2026, and
# NOTHING in between — eighteen years missing — while
# argo_backfill_state.done_through sat at 2007-08-01, where a hand-run had left
# it five days earlier. The walk works; nobody was asking it to run.
#
# ⚠️ The budget is only checked at MONTH boundaries (see _argo_backfill_walk),
# so a pass runs to the end of whichever month it is in: the real hold is this
# budget plus one month, and a dense 2020s month is not cheap.
# _run_unless_paused holds _sync_lock for the whole call, so every other sync
# queues behind it — 15 minutes keeps that worst case bounded. Four-hourly
# because this is repair work, not freshness, and ~216 months remain.
ARGO_HISTORY_BACKFILL_INTERVAL_SECONDS = 4 * 3600
ARGO_HISTORY_BACKFILL_BUDGET_SECONDS = 900

LAND_SYNC_INTERVAL_SECONDS = 6 * 3600  # 6 hours — fires need frequent updates
MONITORING_DENSITY_REFRESH_INTERVAL_SECONDS = 12 * 3600
SIO_BIC_SYNC_INTERVAL_SECONDS = 7 * 24 * 3600  # weekly
ONC_SENSOR_SYNC_INTERVAL_SECONDS = 24 * 3600  # daily
OCEANSITES_OBS_SYNC_INTERVAL_SECONDS = 24 * 3600  # daily
AIR_QUALITY_READINGS_INTERVAL_SECONDS = 2 * 3600  # every 2 hours
OFFSHORE_ACTIVITIES_INTERVAL = 7 * 24 * 3600  # weekly

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

# ── Sync serialization ────────────────────────────────────────────────────────
# ⚠️ This is an in-process asyncio.Lock — it can only serialize sync work
# WITHIN one process. Before the web/worker split, every sync (scheduled AND
# admin-triggered "Force Sync") ran in the same process and shared this lock,
# so nothing could ever race against a scheduled sync. After the split,
# `main.py`'s admin force-sync endpoint (`/admin/sync/{source}`, `_run_tracked`)
# runs in the WEB process, while every task below that calls
# `_run_unless_paused` runs in the WORKER process — each process gets its own
# `asyncio.Lock` object. An operator hitting "Force Sync" in the admin panel
# can now run concurrently with a worker-scheduled sync against the same
# tables, which the pre-split code made structurally impossible. No task in
# this file doubles itself (each has its own DB-level or sync_log guard,
# documented per task below), but this specific web-vs-worker race is a new
# gap this split opens and does not close — flagged, not fixed, here.
_sync_lock = asyncio.Lock()

# ── Lock-holder attribution (for the memory-peak sampler below) ─────────────
# Set to the sync's label for exactly as long as it holds _sync_lock; cleared
# in `finally` even when the sync raises — a name that survives a crash would
# blame the wrong sync forever. This is a HINT for _memory_peak_sampler, not a
# second lock and not proof of causation: see that function's docstring.
_lock_holder: str | None = None


@asynccontextmanager
async def _held_sync_lock(name: str):
    """Acquire _sync_lock and record `name` as the current holder.

    Used by every caller of _sync_lock — _run_unless_paused below, and the
    force-sync listener's runner — so _lock_holder means the same thing
    regardless of which one is running. Still process-local: see the module
    docstring's note on what the web/worker split does to _sync_lock's
    cross-process guarantee.

    It ALSO writes a `running_syncs` row for the whole time the lock is held,
    which is what `GET /admin/sync/running` reads. Two consequences worth
    stating:

    * The state is now in Postgres, so the WEB process can answer truthfully
      about a sync running in the WORKER. A process-local dict could only ever
      describe half of a two-process system.
    * ⚠️ Deliberate behaviour CHANGE: every SCHEDULED sync now shows up there
      too, not only operator-forced ones. Before this, `/admin/sync/running`
      answered `{}` while the weekly chain was ten minutes into OBIS, which
      made "nothing is running" and "something big is running" identical.

    A failure to write the row is logged and swallowed. Losing the admin view
    is bad; refusing to run the sync because the admin view is unavailable is
    worse.
    """
    global _lock_holder
    async with _sync_lock:
        _lock_holder = name
        row_id = await sync_queue.register_running(name)
        beat: asyncio.Task | None = None
        if row_id is not None:
            # The heartbeat is what separates "still working" from "the process
            # died mid-sync". Elapsed time cannot: the GEBCO bake legitimately
            # runs for tens of minutes.
            beat = asyncio.create_task(
                sync_queue.heartbeat_loop(row_id), name=f"sync-heartbeat:{name}")
        try:
            yield
        finally:
            _lock_holder = None
            if beat is not None:
                beat.cancel()
            await sync_queue.unregister_running(row_id)


async def _run_unless_paused(action: str, fn, label: str | None = None):
    """Run a sync function unless its action is paused. Serialized via
    _sync_lock (shared with _run_tracked) so weekly-chain and admin
    force-sync paths cannot overlap — WITHIN a process; see the comment on
    _sync_lock above for what changed after the web/worker split."""
    if await is_sync_paused(action):
        log.info("%s: skipped (paused)", label or action)
        return False
    async with _held_sync_lock(label or action):
        await fn()
    return True


# ── Memory-peak sampler ───────────────────────────────────────────────────────
# Built 2026-09-18 to find the still-unowned 6 GB RSS / 3.3 GB swap peak that
# systemd reported on the pre-split monolith. Three suspects already ruled
# out with measurements (Argo, deepdata/mbari, acidification's NetCDF reads —
# 265 MB, not the 1.4 GB the cache directory suggested); guessing further is
# not working, so the process reports its own peaks instead.
#
# Does NOT wrap each of the 43 tasks with a before/after measurement — most
# are infinite loops that sleep between runs, so "around the task" would
# measure the whole process lifetime and credit it to whichever task
# happened to start first. Instead: _sync_lock already serializes at most one
# sync body at a time (_held_sync_lock above), so a periodic sampler that
# logs only when the OS-reported peak RSS rises, tagged with whichever sync
# currently holds the lock, is a real (if imperfect) attribution signal.


def _normalize_maxrss_kb(raw_maxrss: int, platform: str = sys.platform) -> int:
    """getrusage(RUSAGE_SELF).ru_maxrss units differ by platform: KILOBYTES
    on Linux, BYTES on macOS/Darwin (see getrusage(2) — glibc vs. the BSD
    heritage of Darwin's libc disagree on this and always have). Normalize
    to KB here, explicitly, so the number is never wrong by 1024x depending
    on which OS happened to run the process. `platform` is a parameter
    (default `sys.platform`) so tests can assert both branches without
    needing to run on both a Linux CI box and a Mac.
    """
    if platform == "darwin":
        return raw_maxrss // 1024
    return raw_maxrss


def _current_rss_kb() -> int:
    """The process's peak RSS so far, in KB. ru_maxrss is already a
    monotonic high-water mark maintained by the kernel since process start —
    there is no separate 'current RSS' needed for a HIGH-WATER-MARK sampler;
    successive readings of ru_maxrss only ever hold steady or increase."""
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return _normalize_maxrss_kb(raw)


def _observe_rss(rss_kb: int, prev_peak_kb: int) -> tuple[int, int | None]:
    """Pure comparison, split out of the loop below so it's unit-testable
    without asyncio. Returns (new_peak_kb, delta_kb_or_None) — delta is None
    when this sample did NOT raise the high-water mark (the falling/flat
    case that must NOT log)."""
    if rss_kb > prev_peak_kb:
        return rss_kb, rss_kb - prev_peak_kb
    return prev_peak_kb, None


_peak_rss_kb: int = 0


async def _memory_peak_sampler(read_rss: Callable[[], int] | None = None,
                                interval: float = 30.0) -> None:
    """Poll RSS every ~30s; log ONE line ONLY when the high-water mark rises,
    naming whichever sync holds _sync_lock at that moment (or "none").

    ⚠️ Attribution is a HINT, not proof, and the log line says so:
    - A task that allocates while NOT holding _sync_lock gets blamed on
      whoever happens to hold the lock at the next rising sample, if anyone.
    - Memory freed after a peak still counts toward that peak forever — this
      finds who was running when the ceiling moved, not who is using the
      memory right now.
    `read_rss` is injectable for tests (real callers get `_current_rss_kb`).
    """
    global _peak_rss_kb
    reader = read_rss or _current_rss_kb
    while True:
        rss = reader()
        _peak_rss_kb, delta = _observe_rss(rss, _peak_rss_kb)
        if delta is not None:
            log.warning(
                "memory watermark: new peak RSS %d KB (+%d KB) — sync holding "
                "_sync_lock at sample time: %s (attribution hint, not proof — "
                "see _memory_peak_sampler docstring)",
                _peak_rss_kb, delta, _lock_holder or "none",
            )
        await asyncio.sleep(interval)


async def _run_with_log(fn, label: str):
    """Run an async function, logging any exception without crashing the service."""
    try:
        await fn()
    except Exception:
        log.exception("%s failed", label)


# ── Startup diagnostics ───────────────────────────────────────────────────────

async def _startup_data_check():
    """Light check on startup: log table counts, no heavy network calls."""
    tables = [
        "mining_contracts", "reserved_areas", "isa_apeis", "relinquished_areas",
        "biodiversity_hotspots", "seamounts", "argo_profiles",
        "hydrothermal_vents", "maritime_boundaries", "protected_marine_sites",
        "submarine_cables", "onc_cables", "ooi_cables", "noaa_cables", "nz_cables", "au_cables", "port_locations", "oceansites_stations", "onc_locations",
        "chess_occurrences",
    ]
    async with db.pool.acquire() as conn:
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


async def _log_noise_risk_count_on_startup():
    """Log current noise_risk_grid row count to sync_log so the dashboard shows it."""
    try:
        async with db.pool.acquire() as conn:
            count = await conn.fetchval("SELECT COUNT(*) FROM noise_risk_grid")
            if count:
                await _log_sync("noise_risk", 0, count)
                log.info("noise_risk: %d grid cells (static — use Force Sync to refresh)", count)
    except Exception:
        pass  # table may not exist yet on first deploy


# ── Contractor auto-discovery ─────────────────────────────────────────────────

async def _delayed_auto_discover():
    # 45 min, not the 20 it used to be. The engine rule asks for >=15 min for
    # anything scanning ais_positions, and 20 nominally cleared it — but on
    # 2026-09-02 this call still lost a race with the cold start and the SAR
    # seed and died on its statement_timeout, while the identical query took
    # 86 s once the box was quiet. The scan is ~52M rows; give the boot storm
    # room to finish first. The regular 6h task already waits 2h.
    #
    # ⚠️ auto_discover_contractors() also does `global _vessel_events_cache;
    # _vessel_events_cache = None` (vessel_events.py) to invalidate the cached
    # GET /vessel-events GeoJSON response. That invalidation only clears
    # THIS process's copy of that module global. GET /vessel-events is served
    # by the web process's own copy, populated/invalidated independently on
    # its own requests — so running this task in the worker does not go stale
    # the read path any more than it already would (the web process's cache
    # is only ever touched by the web process), but it means this worker-side
    # invalidation is a no-op nobody reads. Not fixed here — see the module
    # docstring's "known gap" section.
    await asyncio.sleep(2700)
    try:
        await auto_discover_contractors()
    except Exception:
        log.exception("contractor auto-discovery failed")


# ── Weekly full sync chain ─────────────────────────────────────────────────────

async def _sync_all_sources():
    """Weekly sync: pull new records from every external source into DB."""
    log.info("Weekly sync starting…")

    # ArcGIS layers + mining contracts
    if not await is_sync_paused("arcgis"):
        async with db.pool.acquire() as conn:
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
        plume_count = await _compute_plume_paths(db.pool, max_batch=500)
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
        cnt = await refresh_species_cache()
        await _log_sync("species-cache", cnt, cnt)
    except Exception as exc:
        log.warning("species_cache: refresh failed — %s", exc)
        try:
            await _log_sync("species-cache", 0, 0)
        except Exception:
            pass

    log.info("Weekly sync complete")


async def _weekly_sync_task():
    # First sync delayed 1 hour after boot — gives VPS time to settle
    await asyncio.sleep(3600)
    while True:
        try:
            await _sync_all_sources()
        except Exception:
            log.exception("Weekly sync failed")
        await asyncio.sleep(SYNC_INTERVAL_SECONDS)


# ── Argo ───────────────────────────────────────────────────────────────────────

async def _argo_sync_task():
    """Sync Argo floats every 12h — independent of the weekly full sync."""
    await asyncio.sleep(1800)  # 30 min delay after boot
    while True:
        try:
            await _run_unless_paused("argo", sensors.sync_argo_profiles, "argo_12h")
        except Exception:
            log.exception("Argo 12h sync failed")
        await asyncio.sleep(ARGO_SYNC_INTERVAL_SECONDS)


async def _argo_history_floor_task():
    """Keep the last six months dense in our own database.

    ⛔ Without a cadence, ARGO_HISTORY_FLOOR_DAYS is a number in a constant, not
    a guarantee: the window was filled once by hand on 2026-09-09 and nothing
    would have kept it filled. sync_argo_profiles only ever refreshes the last
    30 days, so any month that falls out of that window is never revisited —
    which is exactly how March..July 2026 ended up at ~4% coverage.

    Each pass resumes from argo_topup_state and walks one month-chunk at a
    time within its budget, so a settled window costs one cheap pass and a
    gap gets filled a couple of months per run. Runs on a long delay after
    boot: it is repair work, not something to fight the cold start over.
    """
    await asyncio.sleep(2700)  # 45 min after boot — behind every live sync
    while True:
        try:
            await _run_unless_paused(
                "argo-recent-history", sensors.sync_argo_recent_history, "argo_history_floor")
        except Exception:
            log.exception("Argo history-floor top-up failed")
        await asyncio.sleep(ARGO_HISTORY_FLOOR_INTERVAL_SECONDS)


async def _argo_history_backfill_task():
    """Walk the full Argo history until it reaches today, then go quiet.

    ⛔ A resumable walk with no caller is a walk that does not happen. Every
    piece of this machinery already existed on 2026-09-09 — cursor, month
    chunking, advisory lock, rate-limit backoff — and the only way to advance
    it was POST /v1/admin/argo-backfill, by hand, roughly forty times. It was
    pressed twice. Eighteen years stayed missing and no dashboard said so,
    because this path writes no sync_log row: the gap was invisible until
    somebody counted profiles per year.

    A completed history makes the pass free — the walk reads its cursor, sees
    it has reached today, and returns without one request. So this task needs
    no end condition. It needs only to keep asking.

    Protected against double-run (this task or the admin backfill endpoint)
    by a real Postgres `pg_try_advisory_lock` inside
    sensors.sync_argo_profiles_backfill — a second concurrent walk simply
    fails to acquire the lock and returns "skipped", cross-process, not just
    cross-coroutine. This is the one task in this file whose guard already
    survives the web/worker split unmodified.
    """
    await asyncio.sleep(3600)  # 60 min after boot — behind the floor top-up
    while True:
        try:
            await _run_unless_paused(
                "argo-backfill", _run_argo_history_backfill, "argo_history_backfill")
        except Exception:
            log.exception("Argo full-history backfill failed")
        await asyncio.sleep(ARGO_HISTORY_BACKFILL_INTERVAL_SECONDS)


async def _run_argo_history_backfill():
    """One bounded pass, with its outcome said out loud.

    ⛔ Four outcomes return months_done == 0 and only one of them is a problem:
    the history finished, the single-walk lock refused a second runner, the
    vocabulary fetch failed, or the walk tried and got nowhere. Collapsing them
    into one log line is how a stalled backfill hides inside a healthy cadence
    for weeks — which is exactly what an operator reading "0 months" would
    have concluded before this existed.
    """
    result = await sensors.sync_argo_profiles_backfill(
        budget_seconds=ARGO_HISTORY_BACKFILL_BUDGET_SECONDS)
    if result.get("complete"):
        log.info("argo backfill: history complete through %s — nothing to walk",
                 result.get("done_through"))
    elif result.get("skipped_reason"):
        log.info("argo backfill: %s", result["skipped_reason"])
    elif result.get("stalled"):
        log.warning(
            "argo backfill: STALLED at %s — walked no month this pass (%s)",
            result.get("done_through"),
            result.get("failed_chunk") or result.get("error") or "no reason given")
    else:
        log.info("argo backfill: %s month(s), %s row(s), now through %s",
                 result.get("months_done"), result.get("inserted"), result.get("done_through"))
    return result


async def _backfill_woa_anomalies(batch_size: int = 1000) -> int:
    """One-shot: fill woa_* for argo_profiles rows that don't have them yet."""
    async with db.pool.acquire() as conn:
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
        async with db.pool.acquire() as conn:
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
        if w["woa_surface_temp_c"] is not None or w["woa_deep_temp_c"] is not None:
            enriched += 1
    async with db.pool.acquire() as conn:
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


# ── WoRMS ──────────────────────────────────────────────────────────────────────

async def _worms_sync_task():
    await asyncio.sleep(300)  # 5 min — external-API tier, no heavy DB scan
    while True:
        try:
            await _run_unless_paused("worms", biodiversity.sync_worms_taxa, "worms")
        except Exception:
            log.exception("worms sync failed")
        await asyncio.sleep(SYNC_INTERVAL_SECONDS)  # weekly cadence


# ── SIO-BIC / slow sources / density ────────────────────────────────────────────

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


# ── Field-layer bakes ────────────────────────────────────────────────────────
# ⚠️ Every bake below shares the cross-process meta-cache staleness caveat
# described in this module's docstring ("known gap this split introduces").
# Not repeated per-function; see the docstring for the mechanism.

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
        async with db.pool.acquire() as conn:
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


# ── ONC ────────────────────────────────────────────────────────────────────────

async def _onc_sensor_sync_task():
    """Refresh ONC cached sensor readings daily — keeps map current without
    per-click API calls."""
    await asyncio.sleep(3600)
    while True:
        try:
            await onc.sync_onc_sensors()
        except Exception:
            log.exception("ONC daily sensor sync failed")
        await asyncio.sleep(ONC_SENSOR_SYNC_INTERVAL_SECONDS)


async def _onc_instruments_daily_task():
    """Run ONC instrument WFS sync + enrichment once per day at ~00:15 Europe/Warsaw."""
    tz = ZoneInfo("Europe/Warsaw")
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
    await asyncio.sleep(300)
    while True:
        try:
            await onc.sync_onc_sparklines()
        except Exception:
            log.exception("ONC sparkline sync failed")
        await asyncio.sleep(4 * 3600)


async def _onc_adcp_task():
    """Refresh ONC ADCP backscatter strips every 12 hours."""
    await asyncio.sleep(900)
    while True:
        try:
            await onc.sync_onc_adcp_strips()
        except Exception:
            log.exception("ONC ADCP strip sync failed")
        await asyncio.sleep(12 * 3600)


async def _onc_ctd_task():
    """Refresh ONC CTD profiles every 12 hours."""
    await asyncio.sleep(900)
    while True:
        try:
            await onc.sync_onc_ctd_profiles()
        except Exception:
            log.exception("ONC CTD profile sync failed")
        await asyncio.sleep(12 * 3600)


async def _onc_ctd_series_task():
    """Grow our archive of ONC's own 10-minute CTD series, every 12 hours."""
    await asyncio.sleep(2700)
    while True:
        try:
            await onc.sync_onc_ctd_series()
        except Exception:
            log.exception("ONC CTD series archive sync failed")
        await asyncio.sleep(12 * 3600)


async def _usgs_earthquakes_task():
    """Refresh USGS earthquake catalog every 6 hours."""
    await asyncio.sleep(300)
    while True:
        try:
            await onc.sync_usgs_earthquakes()
        except Exception:
            log.exception("USGS earthquake sync failed")
        await asyncio.sleep(6 * 3600)


async def _oceansites_obs_sync_task():
    """Refresh OceanSITES cached NDBC observations daily."""
    await asyncio.sleep(3600)
    while True:
        try:
            await sensors.sync_oceansites_obs()
        except Exception:
            log.exception("OceanSITES daily obs sync failed")
        await asyncio.sleep(OCEANSITES_OBS_SYNC_INTERVAL_SECONDS)


async def _air_quality_readings_task():
    """Drip-fill air quality readings from OpenAQ v3 — 500 stations per run,
    sequential 1 req/1.2s to respect rate limits. Runs independently of
    the 6h land sync to populate all ~24k stations in ~4 days."""
    await asyncio.sleep(900)
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


OFFSHORE_ACTIVITIES_SOURCES = [
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
]


async def _offshore_activities_sync_task():
    """Sync all offshore-activity registries weekly. 45-min startup delay
    ensures the pool is settled and schema migrations are complete."""
    await asyncio.sleep(45 * 60)
    while True:
        for fn, label in OFFSHORE_ACTIVITIES_SOURCES:
            try:
                await _run_with_log(fn, label)
            except Exception:
                log.exception("%s failed", label)
            await asyncio.sleep(120)
        await asyncio.sleep(OFFSHORE_ACTIVITIES_INTERVAL)


# ── Request-log pipeline (web-only: drains the per-process _log_pipe) ────────

async def _usage_rollup_task():
    """Roll request_log into usage_rollup every 10 minutes."""
    from api_access.rollup import rollup_new_rows
    await asyncio.sleep(120)  # let startup settle
    while True:
        try:
            n = await rollup_new_rows(db.pool)
            if n:
                log.info("usage rollup: advanced %d request_log rows", n)
        except Exception:
            log.exception("usage rollup failed")
        await asyncio.sleep(600)


async def _leak_detection_task():
    """Scan request_log hourly for key-leak signals; raise debounced flags + Telegram."""
    from api_access.leak_detect import run_leak_detection
    await asyncio.sleep(20 * 60)
    while True:
        try:
            n = await run_leak_detection(db.pool)
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
            async with db.pool.acquire() as conn:
                await ensure_daily_partitions(conn)
                await conn.execute("DELETE FROM api_access.admin_sessions WHERE expires_at < now()")
            dropped = await drop_expired_log_partitions(db.pool)
            if dropped:
                log.info("request_log retention: dropped %d expired partitions", dropped)
        except Exception:
            log.exception("request_log retention failed")
        await asyncio.sleep(24 * 3600)


async def _query_watchdog_task():
    """Periodic check for long-running queries on the abyssal DB.

    Polls pg_stat_activity, which is cluster-wide — it sees every backend
    opened by ANY process (web's request-serving connections included), not
    just the worker's own. Running this once, in the worker, still protects
    the web process's connections.
    """
    WARN_MIN = 15
    KILL_MIN = 60
    POLL_SEC = 300
    await asyncio.sleep(120)
    while True:
        try:
            async with db.pool.acquire() as conn:
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


# ── Tile pre-bake ──────────────────────────────────────────────────────────────

async def _offshore_tile_prebake(ctx: "TaskContext"):
    # schedule_bake is debounced — safe to call even if syncs trigger it again soon.
    await _schedule_offshore_tile_bake(db.pool)


async def _forced_sync_runner(source: str, fn: Callable[[], Awaitable[Any]]) -> None:
    """Run one operator-forced sync, through exactly the same gate every
    scheduled sync goes through.

    ⛔ `_held_sync_lock` and not a bare `await fn()`: before the split, the
    admin force-sync path shared this process's `_sync_lock` with the weekly
    chain, so the two could never overlap. Bypassing it here would hand back
    that guarantee for nothing — the sync now runs in the same process as the
    chain again, which is precisely what makes the lock meaningful.
    """
    async with _held_sync_lock(source):
        await fn()


async def _sync_request_listener_task() -> None:
    """Claim and run force-sync requests posted by `POST /admin/sync/{source}`.

    The source table is imported HERE rather than at module scope because
    `sync_sources` imports this module (for `_sync_all_sources` and the two
    backfill entry points); a module-level import would be a cycle.
    """
    from sync_sources import SYNC_SOURCES

    await sync_queue.sync_request_listener(
        SYNC_SOURCES.get, _forced_sync_runner,
        role=os.environ.get("ABYSSAL_ROLE", "all"),
    )


# ── The registry ──────────────────────────────────────────────────────────────

ROLE_WEB = "web"
ROLE_WORKER = "worker"
ROLE_BOTH = "both"
_VALID_ROLES = {ROLE_WEB, ROLE_WORKER, ROLE_BOTH}


@dataclass(frozen=True)
class TaskSpec:
    name: str
    role: str  # "web" | "worker" | "both"
    reason: str
    factory: Callable[["TaskContext"], Awaitable[Any]]

    def __post_init__(self):
        if self.role not in _VALID_ROLES:
            raise ValueError(f"task {self.name!r} has invalid role {self.role!r}")


def _f(coro_fn: Callable[[], Awaitable[Any]]) -> Callable[["TaskContext"], Awaitable[Any]]:
    """Wrap a zero-arg task coroutine function as a ctx-accepting factory."""
    return lambda ctx: coro_fn()


TASK_REGISTRY: list[TaskSpec] = [
    TaskSpec(
        "sync-request-listener", ROLE_WORKER,
        "Holds the LISTEN connection for operator-forced syncs and runs them. "
        "⛔ Must be the ONLY process doing so: role `worker` means "
        "ABYSSAL_ROLE=all (today's production, one process) still starts it, "
        "while a split web+worker pair starts it exactly once, in the worker. "
        "If it were `both`, the web process would run the very bakes the split "
        "exists to keep out of it. Double-claiming is impossible anyway — "
        "claim_next() is a single atomic UPDATE with FOR UPDATE SKIP LOCKED — "
        "but 'cannot corrupt' is not 'should run here'.",
        _f(_sync_request_listener_task),
    ),
    TaskSpec(
        "contractor-auto-discovery", ROLE_WORKER,
        "CPU-heavy spatial join against Postgres only (ais_positions × aois); "
        "no per-process state a web request needs synchronously. Guarded "
        "against double-run by a 4h sync_log('contractor_vessels') check.",
        _f(_delayed_auto_discover),
    ),
    TaskSpec(
        "request-log-batch-writer", ROLE_WEB,
        "Drains _log_pipe, an in-process asyncio.Queue filled per-request by "
        "RequestLogMiddleware — that middleware only runs in the process "
        "serving HTTP, so this MUST run there too or every record is lost "
        "silently (the trap this whole task exists to avoid).",
        lambda ctx: batch_writer(db.pool, ctx.log_pipe, ctx.geoip),
    ),
    TaskSpec(
        "usage-rollup", ROLE_WORKER,
        "Reads/writes request_log → usage_rollup via Postgres only (no "
        "in-process state); the rows it rolls up were already durably "
        "written to Postgres by the web process's batch_writer.",
        _f(_usage_rollup_task),
    ),
    TaskSpec(
        "leak-detection", ROLE_WORKER,
        "DB-only scan of request_log for leak signals + Telegram alert. No "
        "per-process state.",
        _f(_leak_detection_task),
    ),
    TaskSpec(
        "log-retention", ROLE_WORKER,
        "DB-only partition maintenance + admin_sessions cleanup.",
        _f(_log_retention_task),
    ),
    TaskSpec(
        "startup-data-check", ROLE_BOTH,
        "Read-only table-count diagnostic, no writes, no per-process cache. "
        "Cheap and harmless to run in both — each process gets its own "
        "confirmation in its own log that the DB it just connected to has data.",
        _f(_startup_data_check),
    ),
    TaskSpec(
        "weekly-sync-chain", ROLE_WORKER,
        "Orchestrates ~25 external-source syncs, all Postgres/HTTP, no "
        "per-process state. Serialized internally via _sync_lock/_run_unless_paused "
        "(see that lock's comment for the one cross-process gap this doesn't close).",
        _f(_weekly_sync_task),
    ),
    TaskSpec(
        "argo-12h-sync", ROLE_WORKER, "Postgres/HTTP only.",
        _f(_argo_sync_task),
    ),
    TaskSpec(
        "argo-history-floor", ROLE_WORKER, "Postgres/HTTP only.",
        _f(_argo_history_floor_task),
    ),
    TaskSpec(
        "argo-history-backfill", ROLE_WORKER,
        "Postgres/HTTP only. Protected against double-run (this task, the "
        "admin backfill endpoint, or a second worker replica) by a real "
        "pg_try_advisory_lock inside sensors.sync_argo_profiles_backfill — "
        "the one guard in this registry that already survives the process split.",
        _f(_argo_history_backfill_task),
    ),
    TaskSpec(
        "worms-taxonomy-sync", ROLE_WORKER,
        "Postgres + WoRMS REST API only, ≤50 calls/run.",
        _f(_worms_sync_task),
    ),
    TaskSpec(
        "sio-bic-catalogue-sync", ROLE_WORKER, "Postgres/HTTP only.",
        _f(_sio_bic_sync_task),
    ),
    TaskSpec(
        "slow-sources-daily-tick", ROLE_WORKER,
        "Postgres/HTTP only; the cadence check itself is a single SELECT.",
        _f(_slow_sources_sync_task),
    ),
    TaskSpec(
        "monitoring-density-refresh", ROLE_WORKER,
        "Rebuilds a materialized grid table in Postgres only.",
        _f(_monitoring_density_refresh_task),
    ),
    TaskSpec(
        "land-layers-sync", ROLE_WORKER, "Postgres/HTTP only, ~12 land sources.",
        _f(_land_sync_task),
    ),
    TaskSpec(
        "currents-daily-bake", ROLE_WORKER,
        "CMEMS fetch + disk texture bake; see module docstring for the "
        "meta-cache staleness caveat shared by every bake in this file.",
        _f(_currents_bake_task),
    ),
    TaskSpec(
        "currents-history-backfill", ROLE_WORKER,
        "One-shot disk bake, ~20h sync_log idempotence guard (not atomic, "
        "but this only runs once at startup and the window is small).",
        _f(_currents_backfill_task),
    ),
    TaskSpec(
        "woa-startup-bake", ROLE_WORKER, "External API + disk bake; 30-day sync_log guard.",
        _f(_woa_startup_bake),
    ),
    TaskSpec(
        "carbon-startup-bake", ROLE_WORKER, "External API + disk bake; 30-day sync_log guard.",
        _f(_carbon_startup_bake),
    ),
    TaskSpec(
        "acidification-startup-bake", ROLE_WORKER, "External API + disk bake; 30-day sync_log guard.",
        _f(_acidification_startup_bake),
    ),
    TaskSpec(
        "chi-startup-bake", ROLE_WORKER, "Own GeoTIFF fetch + disk bake.",
        _f(_chi_startup_bake),
    ),
    TaskSpec(
        "coral-exposure-startup-bake", ROLE_WORKER,
        "Consumes the acidification + bathymetry bakes' disk output; Postgres/disk only.",
        _f(_coral_exposure_startup_bake),
    ),
    TaskSpec(
        "socat-startup-bake", ROLE_WORKER, "External API + disk bake; 30-day sync_log guard.",
        _f(_socat_startup_bake),
    ),
    TaskSpec(
        "seabed-startup-bake", ROLE_WORKER, "Static-dataset holdings check; 30-day sync_log guard.",
        _f(_seabed_startup_bake),
    ),
    TaskSpec(
        "cascade-startup-bake", ROLE_WORKER, "Static-dataset holdings check.",
        _f(_cascade_startup_bake),
    ),
    TaskSpec(
        "bathymetry-grid-startup-bake", ROLE_WORKER,
        "Reads the 7.5 GB GEBCO grid and writes a downsampled .npy to disk; "
        "skip-if-present guard. See module docstring — this bake's "
        "reset_cache() has the same cross-process staleness caveat as the "
        "field meta-caches, against services/bathymetry_grid_export.py's "
        "in-process _cache dict.",
        _f(_bathymetry_grid_bake_task),
    ),
    TaskSpec(
        "woa-anomaly-backfill", ROLE_WORKER,
        "One-shot: fills woa_* columns on existing argo_profiles rows using "
        "the WOA grids the startup bake just wrote to disk, plus Postgres "
        "UPDATEs. No per-process state; waits on the startup bake by sleep, "
        "not by reading its in-process cache.",
        _f(_woa_backfill_task),
    ),
    TaskSpec(
        "oxygen-startup-bake", ROLE_WORKER, "External API + disk bake; 30-day sync_log guard.",
        _f(_oxygen_startup_bake),
    ),
    TaskSpec(
        "onc-sensor-daily-sync", ROLE_WORKER, "Postgres/HTTP only.",
        _f(_onc_sensor_sync_task),
    ),
    TaskSpec(
        "onc-instruments-daily", ROLE_WORKER, "Postgres/HTTP only.",
        _f(_onc_instruments_daily_task),
    ),
    TaskSpec(
        "onc-sparkline-refresh", ROLE_WORKER, "Postgres/HTTP only.",
        _f(_onc_sparkline_task),
    ),
    TaskSpec(
        "onc-adcp-refresh", ROLE_WORKER, "Postgres/HTTP only.",
        _f(_onc_adcp_task),
    ),
    TaskSpec(
        "onc-ctd-refresh", ROLE_WORKER,
        "Postgres/HTTP only; deliberately offset from onc-ctd-series to avoid "
        "doubling the ONC API burst for the same 28 locations.",
        _f(_onc_ctd_task),
    ),
    TaskSpec(
        "onc-ctd-series-archive", ROLE_WORKER, "Postgres/HTTP only.",
        _f(_onc_ctd_series_task),
    ),
    TaskSpec(
        "usgs-earthquakes-sync", ROLE_WORKER, "Postgres/HTTP only.",
        _f(_usgs_earthquakes_task),
    ),
    TaskSpec(
        "oceansites-obs-daily-sync", ROLE_WORKER, "Postgres/HTTP only.",
        _f(_oceansites_obs_sync_task),
    ),
    TaskSpec(
        "air-quality-readings-drip", ROLE_WORKER, "Postgres/HTTP only (OpenAQ v3).",
        _f(_air_quality_readings_task),
    ),
    TaskSpec(
        "acoustic-stations-weekly-sync", ROLE_WORKER, "Postgres/HTTP only.",
        _f(_acoustic_stations_task),
    ),
    TaskSpec(
        "acoustic-soundscape-weekly-sync", ROLE_WORKER, "Postgres/HTTP only.",
        _f(_acoustic_soundscape_task),
    ),
    TaskSpec(
        "offshore-activities-weekly-sync", ROLE_WORKER,
        "26 external registries, Postgres/HTTP only. ⚠️ None of these "
        "individual syncs is verified here to hold its own idempotence guard "
        "against a second concurrent runner (e.g. two worker replicas) — "
        "each does its own DELETE/UPSERT pattern in domains/offshore.py. "
        "Not doubled by this registry (one worker), but flagged: don't scale "
        "the worker unit to >1 replica without checking these first.",
        _f(_offshore_activities_sync_task),
    ),
    TaskSpec(
        "noise-risk-count-startup-log", ROLE_WORKER,
        "Static dataset row-count logged to sync_log for the dashboard; Postgres only.",
        _f(_log_noise_risk_count_on_startup),
    ),
    TaskSpec(
        "query-watchdog", ROLE_WORKER,
        "Polls pg_stat_activity cluster-wide and issues pg_terminate_backend; "
        "not process-scoped (protects web's connections too, see the "
        "function's own docstring). Safe if accidentally doubled — "
        "pid <> pg_backend_pid() plus a terminate on an already-dead pid "
        "just raises, and that's caught.",
        _f(_query_watchdog_task),
    ),
    TaskSpec(
        "offshore-tile-prebake", ROLE_WORKER,
        "Debounced disk tile bake keyed off Postgres data; schedule_bake() "
        "is safe to call repeatedly.",
        _offshore_tile_prebake,
    ),
    TaskSpec(
        "memory-peak-sampler", ROLE_WORKER,
        "Reads only this process's own RSS (getrusage) and _lock_holder (an "
        "in-process name, not Postgres) — no cross-process state either way, "
        "so 'web or worker' is a real choice, not a correctness constraint. "
        "Chose worker: _sync_lock is only ever taken by _run_unless_paused's "
        "callers, and after the split those all run in the worker — a copy "
        "of this sampler in web would only ever log holder='none' for its "
        "own (different, not-yet-asked-about) memory growth. Keeps the "
        "diagnostic's output meaningful for the question actually asked: "
        "which SYNC owns the unexplained peak.",
        _f(_memory_peak_sampler),
    ),
]


def tasks_for_role(role: str) -> list[TaskSpec]:
    """Which registry entries a process with this ABYSSAL_ROLE should start.

    `role="all"` (the default) returns every task — today's behaviour,
    unchanged, so local dev and the existing test suite keep working without
    setting anything. ABYSSAL_STANDBY is handled by the caller (main.py),
    not here: standby means "call this with an empty list", not a fourth role.
    """
    if role == ROLE_WEB:
        wanted = {ROLE_WEB, ROLE_BOTH}
    elif role == ROLE_WORKER:
        wanted = {ROLE_WORKER, ROLE_BOTH}
    elif role == "all":
        wanted = {ROLE_WEB, ROLE_WORKER, ROLE_BOTH}
    else:
        raise ValueError(f"unknown ABYSSAL_ROLE {role!r} (expected web/worker/all)")
    return [t for t in TASK_REGISTRY if t.role in wanted]
