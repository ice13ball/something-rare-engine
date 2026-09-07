# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""
Land-layer data: sync functions, DB tables, and API endpoints.
All endpoints live under /v2/map/* to avoid touching existing /v1/ routes.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import os
import shutil
import subprocess
import tempfile
import urllib.parse
import zipfile
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import Response

import db
from auth import get_api_key
from sync_log import is_sync_paused
from domains.land.common import (
    _log_land_sync,
    _pg_conn_string,
    _datacite_extract_coords,
    _datacite_paginate,
)
from domains.land import density as _density
from domains.land.density import (  # noqa: F401 — re-exported for main.py's `from land_layers import ...`
    ensure_monitoring_density_matview,
    ensure_density_hex_cells,
    ensure_density_source_indexes,
    refresh_monitoring_density,
    _sync_wod_profiles,
    _sync_pangaea_records,
    _sync_bco_dmo,
    _sync_noaa_datasets,
    _sync_obis_seamap,
    _sync_ncei_icoads,
    _sync_cchdo_cruises,
)
from domains.land import extractive as _extractive
from domains.land.extractive import (  # noqa: F401 — re-exported for main.py's `from land_layers import ...`
    _sync_mining_footprints,
    _sync_kbas,
    _sync_wdpa,
    _sync_tailings,
    _enrich_tailings_from_grid,
    _sync_dams,
)
from domains.land import hazards as _hazards
from domains.land.hazards import (  # noqa: F401 — re-exported for main.py's `from land_layers import ...`
    _sync_active_fires,
    _sync_air_quality,
    _sync_air_quality_readings,
    _sync_landslides,
    _sync_water_risk,
)
from domains.land import arctic as _arctic
from domains.land.arctic import (  # noqa: F401 — re-exported for main.py's `from land_layers import ...`
    _sync_arctic_rivers,
    _sync_permafrost_thaw,
)
from domains.land.schema_orchestrator import (  # noqa: F401 — re-exported for main.py's `from land_layers import ...`
    ensure_land_schema,
    sync_all_land_sources,
)

log = logging.getLogger("land_layers")
OGR2OGR = shutil.which("ogr2ogr") or "/usr/bin/ogr2ogr"
router = APIRouter(prefix="/v2/map", tags=["land-layers"], dependencies=[Depends(get_api_key)])
router.include_router(_density.router)
router.include_router(_extractive.router)
router.include_router(_hazards.router)
router.include_router(_arctic.router)

# land_layers.py owns no caches of its own since the domains/land split —
# all 13 land-layer caches now live in domains/land/{density,extractive,
# hazards,arctic}.py, each of which registers in domains.CACHE_CLEARING_DOMAINS
# and exposes its own clear_caches(). This function is a delegating hook, kept
# so land_layers stays a valid, harmless entry in CACHE_CLEARING_DOMAINS and
# so a future cache added directly to this file would still be swept by the
# same call.
def clear_caches() -> None:
    """Delegate to every land-layer domain submodule's clear_caches().
    land_layers itself declares no cache globals."""
    _density.clear_caches()
    _extractive.clear_caches()
    _hazards.clear_caches()
    _arctic.clear_caches()


# ensure_land_schema and sync_all_land_sources now live in
# domains/land/schema_orchestrator.py — re-imported above.
