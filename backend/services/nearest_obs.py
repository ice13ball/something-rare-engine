# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Nearest in-situ observations — pure registry + result shaper for the marine-carbon
co-location panel. Given a clicked point, the endpoint (`carbon_nearest_obs` in
domains/fields/carbon.py) runs one KNN query per source; this module declares the
sources and shapes the combined result.

HONESTY: a nearest measurement is NOT representative of the clicked point. Every row carries
its distance in km and the panel always shows it. A source with no data is omitted, never
shown as 0 km. Nothing here fuses or scores across sources.
"""
from __future__ import annotations

# Ocean-chemistry sources only (deliberately scoped — no biodiversity/infrastructure).
# `summary_cols` feed a one-line label built in the endpoint; `geog` marks a geography geom
# column (needs ::geometry for the <-> KNN operator). `deck_layer_id` is the map layer the
# panel flies to on row click (fly-to, not open-panel — see plan Task 5 click-through note).
OBS_SOURCES: list[dict] = [
    {"key": "argo",             "label": "Argo float",          "table": "argo_profiles",       "geom_col": "geom", "id_col": "profile_id",  "geog": False, "summary_cols": ["platform_id", "profile_date", "max_depth_m"],              "deck_layer_id": "argo-floats-3d"},
    {"key": "geotraces",        "label": "GEOTRACES station",   "table": "geotraces_stations",  "geom_col": "geom", "id_col": "station_id",  "geog": False, "summary_cols": ["cruise", "station", "max_depth_m"],                        "deck_layer_id": "geotraces"},
    {"key": "memento",          "label": "MEMENTO cast",        "table": "memento_casts",       "geom_col": "geom", "id_col": "cast_id",     "geog": False, "summary_cols": ["set_name", "station", "sample_time"],                      "deck_layer_id": "memento"},
    {"key": "wod-oxygen",       "label": "WOD O₂ profile",      "table": "wod_oxygen_profiles", "geom_col": "geom", "id_col": "wod_cast_id", "geog": False, "summary_cols": ["dataset", "profile_date", "max_depth_m"],                  "deck_layer_id": "wod-oxygen"},
    {"key": "cascade",          "label": "CASCADE sediment",    "table": "cascade_stations",    "geom_col": "geom", "id_col": "id",          "geog": False, "summary_cols": ["station", "expedition", "year", "oc_pct"],                "deck_layer_id": "arctic-sediment-carbon-stations"},
    {"key": "methane-seeps",    "label": "Methane seep",        "table": "seaflea_seeps",       "geom_col": "geom", "id_col": "ext_id",      "geog": False, "summary_cols": ["primary_type", "depth_m", "obs_year"],                     "deck_layer_id": "methane-seeps"},
    {"key": "vents",            "label": "Hydrothermal vent",   "table": "hydrothermal_vents",  "geom_col": "geom", "id_col": "id",          "geog": True,  "summary_cols": ["name", "status", "depth_m", "region"],                    "deck_layer_id": "hydrothermal-vents-active"},
    {"key": "deepdata-stations","label": "ISA DeepData station","table": "deepdata_stations",   "geom_col": "geom", "id_col": "station_id",  "geog": True,  "summary_cols": ["contractor_code", "occurrence_count", "species_count"],     "deck_layer_id": "deepdata-stations"},
]


def shape_rows(raw: list[dict]) -> list[dict]:
    """Round distance to 1 dp, drop rows with no feature (id None), sort nearest-first.

    A None id means the KNN query found no row for that source — it must be omitted, not
    shown as 0 km (that would read as 'a measurement is right here' when there is none).
    """
    kept = [r for r in raw if r.get("id") is not None]
    for r in kept:
        d = r.get("distance_km")
        r["distance_km"] = round(float(d), 1) if d is not None else None
    kept.sort(key=lambda r: (r["distance_km"] is None, r["distance_km"] or 0.0))
    return kept
