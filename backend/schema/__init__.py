# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Database schema DDL package — table/index creation and migrations.

Split from the former monolithic backend/schema.py (~1,900 lines) into
domain-grouped modules under this package, one `ensure_<name>(conn)` per
CONTIGUOUS RUN of DDL statements from the original file. `ensure_schema()`
below calls every run-function in the ORIGINAL TOP-TO-BOTTOM ORDER of the
file -- that ordering is load-bearing (an ALTER or INDEX can run before its
CREATE TABLE and fail at boot), and it is exactly what
`backend/tests/test_ensure_schema_ddl.py` snapshots.

Imports only `db` + stdlib + `domains.blog`, so this package never creates an
import cycle back into main.py.
"""

from __future__ import annotations

import logging

import db
from domains.blog import seed_blog_if_empty

from schema.acoustic import ensure_acoustic_stations
from schema.arctic import ensure_mosaic, ensure_cascade, ensure_sios, ensure_arctic_catchments
from schema.biodiversity import ensure_biodiversity_enrichment, ensure_hotspot_grid, ensure_noise_cetacean_grids, ensure_vents_and_chess, ensure_sio_bic, ensure_deepdata, ensure_mbari, ensure_noaa_corals, ensure_worms
from schema.blog import ensure_blog
from schema.cables import ensure_cables
from schema.core import ensure_core, ensure_argo_long_form, ensure_core_tables, ensure_ownership_grants, ensure_pageviews, ensure_feedback
from schema.fields import ensure_vme
from schema.geochem import ensure_memento, ensure_geotraces, ensure_seaflea
from schema.isa import ensure_mining_contracts_columns, ensure_isa_seed, ISA_CONTRACT_SEED
from schema.offshore import ensure_ports, ensure_offshore_activities
from schema.onc import ensure_onc_core, ensure_onc_ctd_series, ensure_usgs_earthquakes
from schema.reports import ensure_reports
from schema.seafloor import ensure_bathymetry_cache, ensure_bathymetry_stats
from schema.sensors import ensure_plume_paths, ensure_wod_oxygen, ensure_oceansites

log = logging.getLogger(__name__)

async def ensure_schema() -> None:
    async with db.pool.acquire() as conn:
        # Prevent startup from hanging if long-running queries hold locks
        await conn.execute("SET lock_timeout = '10s'")

        await ensure_core(conn)  # isa_contract_lookup, sync_log, paused_syncs, admin_audit, reserved_areas, isa_apeis, argo_profiles, hydrothermal_vents, relinquished_areas, maritime_boundaries, protected_marine_sites
        await ensure_argo_long_form(conn)  # argo_profile_values, argo_params, argo_backfill_state (additive, alongside argo_profiles)
        await ensure_core_tables(conn)  # mining_contracts + biodiversity_hotspots (the two original core tables)
        await ensure_mining_contracts_columns(conn)  # mining_contracts enrichment ALTER columns
        await ensure_isa_seed(conn)  # isa_contract_lookup seed upsert (ISA_CONTRACT_SEED)
        await ensure_ownership_grants(conn)  # OWNER TO abyssal_user sweep for the early core tables
        await ensure_plume_paths(conn)  # plume_paths
        await ensure_wod_oxygen(conn)  # wod_oxygen_profiles
        await ensure_memento(conn)  # memento_samples, memento_casts
        await ensure_geotraces(conn)  # geotraces_stations, geotraces_samples, geotraces_param_units
        await ensure_mosaic(conn)  # mosaic_cores, mosaic_samples
        await ensure_seaflea(conn)  # seaflea_seeps
        await ensure_cascade(conn)  # cascade_stations
        await ensure_sios(conn)  # sios_datasets
        await ensure_reports(conn)  # report_cache, report_cache_v2, report_jobs_v2, report_cache_v2_concession, report_jobs_v2_concession
        await ensure_biodiversity_enrichment(conn)  # biodiversity_hotspots iucn/enrichment + obis_species_check
        await ensure_hotspot_grid(conn)  # hotspot_grid
        await ensure_noise_cetacean_grids(conn)  # noise_cells, cetacean_cells, noise_risk_grid
        await ensure_pageviews(conn)  # pageviews
        await ensure_feedback(conn)  # feedback_submissions
        await ensure_blog(conn)  # blog_articles
        await ensure_oceansites(conn)  # oceansites_stations
        await ensure_onc_core(conn)  # onc_locations, onc_location_categories, onc_sparklines, onc_adcp_strips, onc_ctd_profiles
        await ensure_onc_ctd_series(conn)  # onc_ctd_series, onc_deployment_citations
        await ensure_usgs_earthquakes(conn)  # usgs_earthquakes
        await ensure_acoustic_stations(conn)  # acoustic_stations, acoustic_soundscape
        await ensure_vents_and_chess(conn)  # drop deprecated GBIF table; chess_occurrences; hydrothermal_vents InterRidge/ChEssBase enrichment
        await ensure_sio_bic(conn)  # sio_bic_records
        await ensure_deepdata(conn)  # deepdata_occurrences, deepdata_dwc_archives, deepdata_stations
        await ensure_mbari(conn)  # mbari_vars_records
        await ensure_noaa_corals(conn)  # noaa_corals_records
        await ensure_cables(conn)  # submarine_cables, onc_cables, ooi_cables, noaa_cables, nz_cables, au_cables, onc_instruments
        await ensure_ports(conn)  # port_locations
        await ensure_offshore_activities(conn)  # offshore_activities
        await ensure_bathymetry_cache(conn)  # bathymetry_cache
        await ensure_worms(conn)  # worms_taxa, taxon_name_map
        await ensure_arctic_catchments(conn)  # arctic_catchments
        await ensure_bathymetry_stats(conn)  # bathymetry_stats, gmrt_area_cache
        await ensure_vme(conn)  # vme_cells, vme_models, vme_bake_control, vme_exposure_cells

    log.info("Schema ready")
