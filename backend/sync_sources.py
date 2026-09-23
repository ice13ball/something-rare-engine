# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""`source name -> the coroutine a Force Sync runs`, for BOTH processes.

This dict lived in `main.py` until 2026-09-18. It had to move for one reason:
after the web/worker split, the process that RUNS a forced sync is the worker,
and `worker.py` must never import `main` (importing it constructs the FastAPI
`app` as a module-level side effect — see `worker.py`'s docstring). The worker
reaches this table through `scheduling.py`; `main.py` imports it from here and
still exposes it as `main._SYNC_SOURCES`, so every existing caller
(`routers/admin_layers_api.py`, `scripts/refactor_gate.py`, the tests) is
unchanged.

⛔ Nothing was reordered, renamed or dropped in the move. The only edit to the
dict body is `_pool` -> `db.pool` in the `plumes` entry: `_pool` was main.py's
module-level pool object, and `db.pool` is the same object, set by whichever
process built it (main.lifespan or worker.main).

⛔ This module must never import `main` or `fastapi` — it is on the worker's
import path. Every callable below is *imported* from a domain/service module,
never defined here, which is why the move was mechanical.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

import db
from domains import acoustic, arctic, biodiversity, cables, fields
from domains import geo_context, geochem, isa, offshore, onc, seafloor, sensors
from land_layers import (
    sync_all_land_sources,
    _sync_air_quality_readings, _sync_mining_footprints, _sync_kbas, _sync_wdpa,
    _sync_tailings, _enrich_tailings_from_grid, _sync_active_fires,
    _sync_air_quality, _sync_landslides, _sync_dams, _sync_water_risk,
    refresh_monitoring_density,
    _sync_wod_profiles, _sync_pangaea_records,
    _sync_bco_dmo, _sync_noaa_datasets, _sync_obis_seamap,
    _sync_ncei_icoads, _sync_cchdo_cruises,
)
from land_overlaps import refresh_overlap_views
from vessel_events import auto_discover_contractors, sync_vessel_events_stub
from ais_sync import run_aoi_seed, run_partition_maintenance
from services.plume_history import compute_pending_plume_paths as _compute_plume_paths
from scheduling import (
    _run_argo_history_backfill, _currents_backfill_task, _sync_all_sources,
)


SYNC_SOURCES: dict[str, Callable[[], Awaitable[Any]]] = {
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
    "plumes":           lambda: _compute_plume_paths(db.pool, max_batch=500),
    "oceansites":       lambda: sensors.sync_oceansites(),
    "oceansites-obs":   lambda: sensors.sync_oceansites_obs(),
    "argo-recent-history": lambda: sensors.sync_argo_recent_history(),
    # ⛔ Registered so the action can be un-paused. _argo_history_backfill_task
    # calls _run_unless_paused("argo-backfill", …); an action absent from this
    # registry can still be paused, but has no force-sync button — so an
    # operator who stopped the walk would have no way to start it again.
    "argo-backfill":    lambda: _run_argo_history_backfill(),
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
    "land-fires":       lambda: _sync_active_fires(force=True),
    "land-air-quality": lambda: _sync_air_quality(force=True),
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
    "onc-ctd-series":         lambda: onc.sync_onc_ctd_series(),
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
    "marhys": lambda: geochem.sync_marhys(force=True),
    "sios":    lambda: arctic.sync_sios(force=True),
    "arcade":  lambda: arctic.sync_arcade(force=True),
    "bathymetry-stats": lambda: seafloor.sync_bathymetry_stats(force=True),
    "cascade": lambda: arctic.sync_cascade(force=True),
    "mosaic": lambda: geochem.sync_mosaic(force=True),
    "vme-sdm": lambda: fields.habitat.sync_vme(force=True),
    "coral-acid-exposure": lambda: fields.carbon.sync_coral_exposure(force=True),
}
