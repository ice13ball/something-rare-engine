# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Operational metadata per map layer: which sync drives it and which table(s)
hold its data. Pure module (no DB import) so it is unit-testable. KEEP IN SYNC
with LAYER_DEFAULTS_PY in startup_seeds.py and the add-a-layer checklist — a
new layer with no entry here shows 'unknown' health and cannot be purged.

sync_source = the `_SYNC_SOURCES` action key (what Force Sync triggers).
log_source  = the `sync_log.source` key used for last-sync-time lookup.
For most kebab-cased layers these are equal; for the ArcGIS group
(mining_contracts/reserved_areas/apeis/relinquished_areas) log_source is the
DB table-ish key from `_SOURCE_TO_ACTION` while sync_source is "arcgis".

`tables=None` marks genuinely tableless layers that cannot be purged: baked
PNG/raster field layers with no DB table at all (marine-carbon, ocean-carbon,
ocean-co2-surface, woa-climatology, oxygen-deox, ocean-acidification,
ocean-currents, seabed-substrate) and layers with no backend ingest at all
(bathymetry, tectonic-plates, surface-water, forest-loss, carbon-flux,
soil-carbon). Layers baked by an out-of-process worker but with a real table
(vme-suitability -> vme_cells, coral-acid-exposure -> vme_exposure_cells) DO
get a table + row-count + purge: their _SYNC_SOURCES force-sync re-bakes the
table, so a purge is recoverable. See task-2-report.md for the verification trail.
"""
from __future__ import annotations

from typing import TypedDict


class LayerOps(TypedDict):
    sync_source: str | None   # _SYNC_SOURCES action key (force-sync + pause), None if no sync
    log_source: str | None    # sync_log.source key for last-sync lookup
    tables: tuple[str, ...] | None   # data table(s); None for baked field/raster layers
    count_sql: str | None            # row-count query; None when tables is None


LAYER_OPS: dict[str, LayerOps] = {
    # --- no backend ingest at all (external tiles / client-side static data) ---
    "bathymetry":          {"sync_source": None, "log_source": None,
                             "tables": None, "count_sql": None},
    "tectonic-plates":     {"sync_source": None, "log_source": None,
                             "tables": None, "count_sql": None},
    "surface-water":       {"sync_source": None, "log_source": None,
                             "tables": None, "count_sql": None},
    "forest-loss":         {"sync_source": None, "log_source": None,
                             "tables": None, "count_sql": None},
    "carbon-flux":         {"sync_source": None, "log_source": None,
                             "tables": None, "count_sql": None},
    "soil-carbon":         {"sync_source": None, "log_source": None,
                             "tables": None, "count_sql": None},

    # --- ArcGIS group (log_source = table-ish key, sync_source = "arcgis") ---
    "contracts":           {"sync_source": "arcgis", "log_source": "mining_contracts",
                             "tables": ("mining_contracts",),
                             "count_sql": "SELECT count(*) FROM mining_contracts"},
    "reserved-areas":      {"sync_source": "arcgis", "log_source": "reserved_areas",
                             "tables": ("reserved_areas",),
                             "count_sql": "SELECT count(*) FROM reserved_areas"},
    "apeis":               {"sync_source": "arcgis", "log_source": "apeis",
                             "tables": ("isa_apeis",),
                             "count_sql": "SELECT count(*) FROM isa_apeis"},
    "relinquished-areas":  {"sync_source": "arcgis", "log_source": "relinquished_areas",
                             "tables": ("relinquished_areas",),
                             "count_sql": "SELECT count(*) FROM relinquished_areas"},

    # --- offshore / ISA-adjacent vector layers ---
    "offshore-activities": {"sync_source": "emodnet-offshore", "log_source": "offshore_activities",
                             "tables": ("offshore_activities",),
                             "count_sql": "SELECT count(*) FROM offshore_activities"},
    "eez":                 {"sync_source": "eez", "log_source": "eez",
                             "tables": ("maritime_boundaries",),
                             "count_sql": "SELECT count(*) FROM maritime_boundaries"},
    "protected-marine-sites": {"sync_source": "protected-sites", "log_source": "protected_marine_sites",
                             "tables": ("protected_marine_sites",),
                             "count_sql": "SELECT count(*) FROM protected_marine_sites"},
    "seamounts":           {"sync_source": "seamounts", "log_source": "seamounts",
                             "tables": ("seamounts",),
                             "count_sql": "SELECT count(*) FROM seamounts"},
    "hydrothermal-vents":  {"sync_source": "vents", "log_source": "hydrothermal_vents",
                             "tables": ("hydrothermal_vents",),
                             "count_sql": "SELECT count(*) FROM hydrothermal_vents"},
    "biodiversity-hotspots": {"sync_source": "obis", "log_source": "biodiversity_hotspots",
                             "tables": ("biodiversity_hotspots",),
                             "count_sql": "SELECT count(*) FROM biodiversity_hotspots"},

    # --- derived rollup: refreshed matview, no own sync_log row ---
    "monitoring-density":  {"sync_source": "monitoring-density-grid", "log_source": None,
                             "tables": None, "count_sql": None},

    # --- noise / cetacean risk grid (3 tables, grid is the primary) ---
    "noise-risk":          {"sync_source": "noise-risk", "log_source": "noise_risk",
                             "tables": ("noise_risk_grid", "noise_cells", "cetacean_cells"),
                             "count_sql": "SELECT count(*) FROM noise_risk_grid"},

    # --- sensor / station networks ---
    "argo":                {"sync_source": "argo", "log_source": "argo_profiles",
                             "tables": ("argo_profiles",),
                             "count_sql": "SELECT count(*) FROM argo_profiles"},
    "oceansites":          {"sync_source": "oceansites", "log_source": "oceansites",
                             "tables": ("oceansites_stations",),
                             "count_sql": "SELECT count(*) FROM oceansites_stations"},
    "onc":                 {"sync_source": "onc", "log_source": "onc",
                             "tables": ("onc_locations",),
                             "count_sql": "SELECT count(*) FROM onc_locations"},
    "onc-instruments":     {"sync_source": "onc-instruments", "log_source": "onc_instruments",
                             "tables": ("onc_instruments",),
                             "count_sql": "SELECT count(*) FROM onc_instruments"},
    "chess":               {"sync_source": "chess", "log_source": "chess",
                             "tables": ("chess_occurrences",),
                             "count_sql": "SELECT count(*) FROM chess_occurrences"},
    "ports":               {"sync_source": "ports", "log_source": "port_locations",
                             "tables": ("port_locations",),
                             "count_sql": "SELECT count(*) FROM port_locations"},
    "hydrophone-stations": {"sync_source": "acoustic-stations", "log_source": "acoustic-stations",
                             "tables": ("acoustic_stations",),
                             "count_sql": "SELECT count(*) FROM acoustic_stations"},
    "deepdata-stations":   {"sync_source": "deepdata-stations", "log_source": "deepdata-stations",
                             "tables": ("deepdata_stations",),
                             "count_sql": "SELECT count(*) FROM deepdata_stations"},

    # --- submarine cables: 6 sub-tables under one toggle, EMODnet is primary ---
    "submarine-cables":    {"sync_source": "cables", "log_source": "submarine_cables",
                             "tables": ("submarine_cables", "noaa_cables", "nz_cables",
                                        "au_cables", "onc_cables", "ooi_cables"),
                             "count_sql": "SELECT count(*) FROM submarine_cables"},

    # --- baked field / raster layers (NO table -> not purgeable) ---
    "marine-carbon":       {"sync_source": "glodap-carbon", "log_source": "glodap-carbon",
                             "tables": None, "count_sql": None},
    "ocean-carbon":        {"sync_source": "glodap-carbon", "log_source": "glodap-carbon",
                             "tables": None, "count_sql": None},
    "ocean-co2-surface":   {"sync_source": "socat-co2", "log_source": "socat-co2",
                             "tables": None, "count_sql": None},
    "woa-climatology":     {"sync_source": "woa-climatology", "log_source": "woa-climatology",
                             "tables": None, "count_sql": None},
    "oxygen-deox":         {"sync_source": "oxygen-deox", "log_source": "oxygen-deox",
                             "tables": None, "count_sql": None},
    "ocean-acidification": {"sync_source": "acidification", "log_source": "acidification",
                             "tables": None, "count_sql": None},
    "cumulative-human-impact": {"sync_source": "chi", "log_source": "chi",
                             "tables": None, "count_sql": None},
    "ocean-currents":      {"sync_source": "currents-surface", "log_source": "currents-surface",
                             "tables": None, "count_sql": None},
    "seabed-substrate":    {"sync_source": "seabed", "log_source": "seabed",
                             "tables": None, "count_sql": None},
    # vme-suitability / coral-acid-exposure have real tables (vme_cells,
    # vme_exposure_cells). They are baked by an out-of-process worker, but their
    # _SYNC_SOURCES force-sync (vme-sdm / coral-acid-exposure) re-bakes them, so a
    # purge is recoverable — they get a live row-count + purge like any table-backed
    # layer (NOT baked-field layers; those have no table at all).
    "vme-suitability":     {"sync_source": "vme-sdm", "log_source": "vme-sdm",
                             "tables": ("vme_cells",),
                             "count_sql": "SELECT count(*) FROM vme_cells"},
    "coral-acid-exposure": {"sync_source": "coral-acid-exposure", "log_source": "coral-acid-exposure",
                             "tables": ("vme_exposure_cells",),
                             "count_sql": "SELECT count(*) FROM vme_exposure_cells"},

    # --- ocean carbon / gas chemistry vector layers ---
    "geotraces":           {"sync_source": "geotraces", "log_source": "geotraces",
                             "tables": ("geotraces_stations", "geotraces_samples"),
                             "count_sql": "SELECT count(*) FROM geotraces_stations"},
    "wod-oxygen":          {"sync_source": "wod-oxygen", "log_source": "wod-oxygen",
                             "tables": ("wod_oxygen_profiles",),
                             "count_sql": "SELECT count(*) FROM wod_oxygen_profiles"},
    "memento":             {"sync_source": "memento", "log_source": "memento",
                             "tables": ("memento_casts", "memento_samples"),
                             "count_sql": "SELECT count(*) FROM memento_casts"},
    "methane-seeps":       {"sync_source": "seaflea", "log_source": "seaflea",
                             "tables": ("seaflea_seeps",),
                             "count_sql": "SELECT count(*) FROM seaflea_seeps"},

    # --- Arctic land->ocean layers ---
    "sios-svalbard":       {"sync_source": "sios", "log_source": "sios",
                             "tables": ("sios_datasets",),
                             "count_sql": "SELECT count(*) FROM sios_datasets"},
    "arctic-catchments":   {"sync_source": "arcade", "log_source": "arcade",
                             "tables": ("arctic_catchments",),
                             "count_sql": "SELECT count(*) FROM arctic_catchments"},
    "arctic-sediment-carbon": {"sync_source": "cascade", "log_source": "cascade",
                             "tables": ("cascade_stations",),
                             "count_sql": "SELECT count(*) FROM cascade_stations"},
    "permafrost-thaw":     {"sync_source": "permafrost-thaw", "log_source": "permafrost-thaw",
                             "tables": ("permafrost_thaw_features",),
                             "count_sql": "SELECT count(*) FROM permafrost_thaw_features"},
    "arctic-rivers":       {"sync_source": "arctic-rivers", "log_source": "arctic-rivers",
                             "tables": ("arctic_river_stations",),
                             "count_sql": "SELECT count(*) FROM arctic_river_stations"},

    # --- sediment core layer ---
    "mosaic-sediment":     {"sync_source": "mosaic", "log_source": "mosaic",
                             "tables": ("mosaic_cores", "mosaic_samples"),
                             "count_sql": "SELECT count(*) FROM mosaic_cores"},

    # --- land layers ---
    "water-risk":          {"sync_source": "land-water-risk", "log_source": "water_risk",
                             "tables": ("water_risk",),
                             "count_sql": "SELECT count(*) FROM water_risk"},
    "mining-footprints":   {"sync_source": "land-mining", "log_source": "mining_footprints",
                             "tables": ("mining_footprints",),
                             "count_sql": "SELECT count(*) FROM mining_footprints"},
    "tailings":            {"sync_source": "land-tailings", "log_source": "tailings",
                             "tables": ("tailings_dams",),
                             "count_sql": "SELECT count(*) FROM tailings_dams"},
    "fires":               {"sync_source": "land-fires", "log_source": "active_fires",
                             "tables": ("active_fires",),
                             "count_sql": "SELECT count(*) FROM active_fires"},
    "air-quality":         {"sync_source": "land-air-quality", "log_source": "air_quality",
                             "tables": ("air_quality_stations",),
                             "count_sql": "SELECT count(*) FROM air_quality_stations"},
    "landslides":          {"sync_source": "land-landslides", "log_source": "landslides",
                             "tables": ("landslides",),
                             "count_sql": "SELECT count(*) FROM landslides"},
    "dams":                {"sync_source": "land-dams", "log_source": "dams",
                             "tables": ("dams",),
                             "count_sql": "SELECT count(*) FROM dams"},

    # --- AIS / vessel stack: NOT wired into _SYNC_SOURCES / _SOURCE_TO_ACTION.
    # ais_positions is written continuously by the separate ais-ingestor
    # systemd service (not this app's own sync loop) — no force-sync action
    # exists for it here, by design. vessel_events.py (the vessel-events
    # module) is present in the repo but is NOT imported by main.py in the
    # current codebase — verified via grep, no wiring found — so it likewise
    # has no reachable sync_source/log_source today. See task-2-report.md.
    "ais-live":            {"sync_source": None, "log_source": None,
                             "tables": ("ais_positions",),
                             "count_sql": "SELECT count(*) FROM ais_positions"},
    "vessel-events":       {"sync_source": None, "log_source": None,
                             "tables": ("vessel_events",),
                             "count_sql": "SELECT count(*) FROM vessel_events"},
}


def resolve_ops(layer_id: str) -> LayerOps | None:
    return LAYER_OPS.get(layer_id)


def has_table(layer_id: str) -> bool:
    ops = LAYER_OPS.get(layer_id)
    return bool(ops and ops["tables"])


def age_bucket(age_seconds: float | None, stale_after_s: int = 7 * 86400) -> dict:
    return {
        "age_seconds": age_seconds,
        "stale": age_seconds is not None and age_seconds > stale_after_s,
    }
