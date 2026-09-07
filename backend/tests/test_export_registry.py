# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import json
import math

from services.export_registry import (
    EXPORT_LAYERS, VectorExport, FieldSource, CompositeExport, kind_of,
)

IO_PAN_VECTORS = {
    "arctic-rivers", "arctic-catchments", "sios-svalbard",
    "memento", "methane-seeps", "geotraces",
}
FIELD_SOURCES = {"socat-co2", "glodap-carbon", "isas20-oxygen", "woa23"}

def test_six_vector_layers_present():
    for k in IO_PAN_VECTORS:
        assert isinstance(EXPORT_LAYERS[k], VectorExport), k

def test_marine_carbon_is_composite_over_four_field_sources():
    mc = EXPORT_LAYERS["marine-carbon"]
    assert isinstance(mc, CompositeExport)
    assert set(mc.members) == FIELD_SOURCES
    for m in mc.members:
        assert isinstance(EXPORT_LAYERS[m], FieldSource), m

def test_no_derived_layers_present():
    for forbidden in ("monitoring-density", "ocean-carbon-hexes", "marine-carbon-hexes"):
        assert forbidden not in EXPORT_LAYERS

def test_every_entry_has_unique_id_and_caps_positive():
    ids = list(EXPORT_LAYERS.keys())
    assert len(ids) == len(set(ids))
    for k, v in EXPORT_LAYERS.items():
        if isinstance(v, (VectorExport, FieldSource)):
            assert v.cap > 0, k
            assert v.prov.source and v.prov.source_url, k

def test_memento_joins_casts_for_geom_geotraces_does_not():
    assert EXPORT_LAYERS["memento"].join_sql is not None
    assert EXPORT_LAYERS["geotraces"].join_sql is None

def test_kind_of():
    assert kind_of(EXPORT_LAYERS["geotraces"]) == "vector"
    assert kind_of(EXPORT_LAYERS["socat-co2"]) == "field"
    assert kind_of(EXPORT_LAYERS["marine-carbon"]) == "composite"


# --- Task 4: ISA & seabed batch ---

ISA_SEABED_VECTORS = {
    "contracts", "reserved-areas", "apeis", "relinquished-areas", "offshore-activities",
}

def test_five_isa_seabed_layers_present():
    for k in ISA_SEABED_VECTORS:
        assert k in EXPORT_LAYERS, f"missing: {k}"
        assert isinstance(EXPORT_LAYERS[k], VectorExport), f"wrong type: {k}"

def test_isa_seabed_caps_positive():
    for k in ISA_SEABED_VECTORS:
        assert EXPORT_LAYERS[k].cap > 0, k

def test_isa_seabed_fields_nonempty_no_geom():
    for k in ISA_SEABED_VECTORS:
        v = EXPORT_LAYERS[k]
        assert len(v.fields) > 0, f"empty fields: {k}"
        for f in v.fields:
            assert f not in ("geom", "geom_3857", "geog", "centroid_geog"), f"geometry/internal column in fields for {k}: {f}"

def test_isa_seabed_provenance_set():
    for k in ISA_SEABED_VECTORS:
        prov = EXPORT_LAYERS[k].prov
        assert prov.source, f"missing prov.source: {k}"
        assert prov.source_url, f"missing prov.source_url: {k}"

def test_isa_seabed_geom_kind_polygon():
    for k in ISA_SEABED_VECTORS:
        assert EXPORT_LAYERS[k].geom_kind == "polygon", k

def test_isa_seabed_geom_col():
    for k in ISA_SEABED_VECTORS:
        assert EXPORT_LAYERS[k].geom_col == "t.geom", k

def test_isa_id_cols():
    assert EXPORT_LAYERS["contracts"].id_col == "isa_id"
    assert EXPORT_LAYERS["reserved-areas"].id_col == "arcgis_id"
    assert EXPORT_LAYERS["apeis"].id_col == "arcgis_id"
    assert EXPORT_LAYERS["relinquished-areas"].id_col == "arcgis_id"
    assert EXPORT_LAYERS["offshore-activities"].id_col == "id"

def test_offshore_activities_excludes_geom_3857():
    fields = EXPORT_LAYERS["offshore-activities"].fields
    assert "geom_3857" not in fields
    assert "geom" not in fields


# --- Task 5: Life & geology batch ---

# "eez" left this set on 2026-09-04 when the layer was taken out of the export
# registry — see NOT_EXPORTABLE at the foot of this file for why.
LIFE_GEO_VECTORS = {
    "seamounts", "hydrothermal-vents", "biodiversity-hotspots",
    "chess", "protected-marine-sites", "deepdata-stations",
}
# These three tables have geography(Point,4326) geom columns → require ::geometry cast.
LIFE_GEO_GEOGRAPHY_CAST = {"seamounts", "hydrothermal-vents", "deepdata-stations"}


def test_six_life_geo_layers_present():
    for k in LIFE_GEO_VECTORS:
        assert k in EXPORT_LAYERS, f"missing: {k}"
        assert isinstance(EXPORT_LAYERS[k], VectorExport), f"wrong type: {k}"


def test_life_geo_caps_positive():
    for k in LIFE_GEO_VECTORS:
        assert EXPORT_LAYERS[k].cap > 0, k


def test_life_geo_fields_nonempty_no_geom():
    for k in LIFE_GEO_VECTORS:
        v = EXPORT_LAYERS[k]
        assert len(v.fields) > 0, f"empty fields: {k}"
        for f in v.fields:
            assert f not in ("geom", "geom_3857", "geog", "centroid_geog"), f"geometry/internal column in fields for {k}: {f}"


def test_life_geo_provenance_set():
    for k in LIFE_GEO_VECTORS:
        prov = EXPORT_LAYERS[k].prov
        assert prov.source, f"missing prov.source: {k}"
        assert prov.source_url, f"missing prov.source_url: {k}"


def test_life_geo_geography_cast_layers_have_cast():
    """Tables with geography(Point,4326) must cast ::geometry for ST_* ops."""
    for k in LIFE_GEO_GEOGRAPHY_CAST:
        assert "::geometry" in EXPORT_LAYERS[k].geom_col, (
            f"{k} is geography but geom_col missing ::geometry cast"
        )


def test_life_geo_non_geography_layers_no_cast():
    non_cast = LIFE_GEO_VECTORS - LIFE_GEO_GEOGRAPHY_CAST
    for k in non_cast:
        assert "::geometry" not in EXPORT_LAYERS[k].geom_col, (
            f"{k} is not geography but has unexpected ::geometry cast"
        )


def test_life_geo_geom_kinds():
    points = {"seamounts", "hydrothermal-vents", "biodiversity-hotspots",
               "chess", "deepdata-stations"}
    polygons = {"protected-marine-sites"}
    for k in points:
        assert EXPORT_LAYERS[k].geom_kind == "point", k
    for k in polygons:
        assert EXPORT_LAYERS[k].geom_kind == "polygon", k


def test_life_geo_id_cols():
    assert EXPORT_LAYERS["seamounts"].id_col == "peak_id"
    assert EXPORT_LAYERS["hydrothermal-vents"].id_col == "id"
    assert EXPORT_LAYERS["biodiversity-hotspots"].id_col == "obis_id"
    assert EXPORT_LAYERS["chess"].id_col == "occurrence_id"
    assert EXPORT_LAYERS["protected-marine-sites"].id_col == "site_id"
    assert EXPORT_LAYERS["deepdata-stations"].id_col == "station_id"


def test_obis_licences_vary_note():
    note = EXPORT_LAYERS["biodiversity-hotspots"].prov.note or ""
    assert "licences vary" in note.lower(), (
        "biodiversity-hotspots must note per-record licence variation"
    )


def test_deepdata_stations_platform_derived_note():
    note = EXPORT_LAYERS["deepdata-stations"].prov.note or ""
    assert "platform-derived" in note.lower(), (
        "deepdata-stations must include platform-derived caveat in note"
    )


# --- Task 6: Sensors registry batch ---
# Tables verified via live \d on apiv2 DB 2026-06-29.
# acoustic_stations is geography(Point,4326) → ::geometry cast required.
# All others are geometry(Point,4326) → no cast.
# wod table name is wod_oxygen_profiles (not wod_oxygen); id col is wod_cast_id.

# "hydrophone-stations" left this set on 2026-09-04 — see NOT_EXPORTABLE below.
SENSOR_VECTORS = {
    "argo", "oceansites", "onc", "onc-instruments", "wod-oxygen",
}
# Only acoustic_stations has geography(Point,4326) among the six.
# Empty since 2026-09-04: acoustic_stations (hydrophone-stations) was the only
# geography-typed sensor export, and it left the download surface. Kept as a set
# rather than deleted because the next geography-typed sensor layer needs the
# cast, and the rule is easier to find here than to rediscover.
SENSOR_GEOGRAPHY_CAST: set[str] = set()


def test_five_sensor_layers_present():
    for k in SENSOR_VECTORS:
        assert k in EXPORT_LAYERS, f"missing: {k}"
        assert isinstance(EXPORT_LAYERS[k], VectorExport), f"wrong type: {k}"


def test_sensor_caps_positive():
    for k in SENSOR_VECTORS:
        assert EXPORT_LAYERS[k].cap > 0, k


def test_sensor_fields_nonempty_no_geom():
    for k in SENSOR_VECTORS:
        v = EXPORT_LAYERS[k]
        assert len(v.fields) > 0, f"empty fields: {k}"
        for f in v.fields:
            assert f not in ("geom", "geom_3857", "geog", "centroid_geog"), f"geometry/internal column in fields for {k}: {f}"


def test_sensor_provenance_set():
    for k in SENSOR_VECTORS:
        prov = EXPORT_LAYERS[k].prov
        assert prov.source, f"missing prov.source: {k}"
        assert prov.source_url, f"missing prov.source_url: {k}"


def test_sensor_geom_kind_all_point():
    for k in SENSOR_VECTORS:
        assert EXPORT_LAYERS[k].geom_kind == "point", k


def test_sensor_geography_cast_layers_have_cast():
    """A geography(Point,4326) table needs geom_col to cast ::geometry.

    ⛔ SENSOR_GEOGRAPHY_CAST is currently empty, so this loop asserts nothing.
    That is stated rather than hidden: a test iterating an empty set passes for
    the same reason a broken one would. The explicit check below fails loudly if
    someone adds a geography layer to SENSOR_VECTORS without listing it here.
    """
    for k in SENSOR_GEOGRAPHY_CAST:
        assert "::geometry" in EXPORT_LAYERS[k].geom_col, (
            f"{k} is geography but geom_col missing ::geometry cast"
        )
    stray = {k for k in SENSOR_VECTORS
             if "::geometry" in EXPORT_LAYERS[k].geom_col} - SENSOR_GEOGRAPHY_CAST
    assert not stray, (
        f"{sorted(stray)} cast ::geometry but are not in SENSOR_GEOGRAPHY_CAST — "
        "add them there so the rule above actually covers them"
    )


def test_sensor_non_geography_layers_no_cast():
    non_cast = SENSOR_VECTORS - SENSOR_GEOGRAPHY_CAST
    for k in non_cast:
        assert "::geometry" not in EXPORT_LAYERS[k].geom_col, (
            f"{k} is geometry not geography but has unexpected ::geometry cast"
        )


def test_sensor_id_cols():
    assert EXPORT_LAYERS["argo"].id_col == "profile_id"
    assert EXPORT_LAYERS["oceansites"].id_col == "ref"
    assert EXPORT_LAYERS["onc"].id_col == "location_code"
    assert EXPORT_LAYERS["onc-instruments"].id_col == "id"
    assert EXPORT_LAYERS["wod-oxygen"].id_col == "wod_cast_id"


def test_wod_oxygen_real_table_name():
    """Live DB has wod_oxygen_profiles, not wod_oxygen."""
    assert EXPORT_LAYERS["wod-oxygen"].table == "wod_oxygen_profiles"


def test_wod_oxygen_cap_fifty_k():
    assert EXPORT_LAYERS["wod-oxygen"].cap == 50_000


def test_wod_oxygen_includes_o2_profile_jsonb():
    assert "o2_profile" in EXPORT_LAYERS["wod-oxygen"].fields


# --- Task 7: Infrastructure — cable composite ---
# Tables verified via live `\d <table>` on apiv2 DB 2026-06-29.
# noaa_cables is geometry(MultiPolygon) → geom_kind="polygon"; all others MultiLineString → "line".
# ports / tectonic-plates: no DB tables found → skipped (client-side GeoJSON layers).

CABLE_MEMBER_IDS = {
    "cables-emodnet", "cables-noaa", "cables-nz",
    "cables-au", "cables-onc", "cables-ooi",
}


def test_six_cable_member_vectors_present():
    for k in CABLE_MEMBER_IDS:
        assert k in EXPORT_LAYERS, f"missing cable member: {k}"
        assert isinstance(EXPORT_LAYERS[k], VectorExport), f"wrong type: {k}"


def test_submarine_cables_is_composite():
    sc = EXPORT_LAYERS["submarine-cables"]
    assert isinstance(sc, CompositeExport)
    assert sc.id == "submarine-cables"


def test_submarine_cables_composite_has_six_members():
    sc = EXPORT_LAYERS["submarine-cables"]
    assert isinstance(sc, CompositeExport)
    assert set(sc.members) == CABLE_MEMBER_IDS


def test_cable_member_ids_resolve_to_vector_exports():
    sc = EXPORT_LAYERS["submarine-cables"]
    for m in sc.members:
        assert isinstance(EXPORT_LAYERS[m], VectorExport), f"member {m!r} not a VectorExport"


def test_cable_members_caps_positive():
    for k in CABLE_MEMBER_IDS:
        assert EXPORT_LAYERS[k].cap > 0, k


def test_cable_members_fields_nonempty_no_geom():
    for k in CABLE_MEMBER_IDS:
        v = EXPORT_LAYERS[k]
        assert len(v.fields) > 0, f"empty fields: {k}"
        for f in v.fields:
            assert f not in ("geom", "geom_3857", "geog", "centroid_geog"), f"geometry/internal column leaked into fields for {k}: {f}"


def test_cable_members_provenance_set():
    for k in CABLE_MEMBER_IDS:
        prov = EXPORT_LAYERS[k].prov
        assert prov.source, f"missing prov.source: {k}"
        assert prov.source_url, f"missing prov.source_url: {k}"


def test_noaa_cables_geom_kind_polygon():
    """noaa_cables stores polygon corridors (MultiPolygon), not centrelines."""
    assert EXPORT_LAYERS["cables-noaa"].geom_kind == "polygon"


def test_non_noaa_cables_geom_kind_line():
    line_members = CABLE_MEMBER_IDS - {"cables-noaa"}
    for k in line_members:
        assert EXPORT_LAYERS[k].geom_kind == "line", k


def test_cable_members_no_geometry_cast():
    """Cable tables are geometry(MultiLine/MultiPolygon,4326) — no ::geometry cast needed."""
    for k in CABLE_MEMBER_IDS:
        assert "::geometry" not in EXPORT_LAYERS[k].geom_col, k


def test_cable_member_id_cols():
    for k in CABLE_MEMBER_IDS:
        assert EXPORT_LAYERS[k].id_col == "id", f"{k} expected id_col='id'"


def test_cable_member_tables():
    assert EXPORT_LAYERS["cables-emodnet"].table == "submarine_cables"
    assert EXPORT_LAYERS["cables-noaa"].table == "noaa_cables"
    assert EXPORT_LAYERS["cables-nz"].table == "nz_cables"
    assert EXPORT_LAYERS["cables-au"].table == "au_cables"
    assert EXPORT_LAYERS["cables-onc"].table == "onc_cables"
    assert EXPORT_LAYERS["cables-ooi"].table == "ooi_cables"


# --- Task 8: Land registry batch ---
# Tables verified via live `\d <table>` on apiv2 DB 2026-06-29.
# Generated geo helper columns excluded:
#   mining_footprints: centroid_geog (generated geography)
#   tailings_dams: geog (generated geography)
#   landslides: geog (generated geography)
# All geom columns are geometry(...,4326) → no ::geometry cast needed.

LAND_REGISTRY_VECTORS = {
    # "wdpa" withdrawn 2026-09-03 — see tests/test_wdpa_withdrawn.py, which
    # asserts its ABSENCE from EXPORT_LAYERS. Do not re-add it here.
    # "kbas" withdrawn 2026-09-03 — see tests/test_kba_withdrawn.py, same
    # treatment. Do not re-add it here.
    "mining-footprints", "tailings",
    "fires", "air-quality", "landslides", "dams", "water-risk",
}

# Exact geometry/internal column names that must never appear in fields
_BANNED_FIELD_EXACT = frozenset(("geom", "geom_3857", "geog", "centroid_geog"))


def test_seven_land_registry_layers_present():
    for k in LAND_REGISTRY_VECTORS:
        assert k in EXPORT_LAYERS, f"missing: {k}"
        assert isinstance(EXPORT_LAYERS[k], VectorExport), f"wrong type: {k}"


def test_land_registry_caps_positive():
    for k in LAND_REGISTRY_VECTORS:
        assert EXPORT_LAYERS[k].cap > 0, k


def test_land_registry_fields_nonempty_no_generated_geo_cols():
    """No geom, geog, centroid_geog, or geom_3857 in fields (exact-match exclusion)."""
    for k in LAND_REGISTRY_VECTORS:
        v = EXPORT_LAYERS[k]
        assert len(v.fields) > 0, f"empty fields: {k}"
        for f in v.fields:
            assert f not in _BANNED_FIELD_EXACT, (
                f"geometry/internal column '{f}' found in fields['{k}']"
            )


def test_land_registry_provenance_set():
    for k in LAND_REGISTRY_VECTORS:
        prov = EXPORT_LAYERS[k].prov
        assert prov.source, f"missing prov.source: {k}"
        assert prov.source_url, f"missing prov.source_url: {k}"


def test_land_registry_no_geometry_cast():
    """All land tables store geometry(…,4326) — no ::geometry cast needed."""
    for k in LAND_REGISTRY_VECTORS:
        assert "::geometry" not in EXPORT_LAYERS[k].geom_col, k


def test_land_registry_geom_kinds():
    polygons = {"mining-footprints", "water-risk"}
    points = {"tailings", "fires", "air-quality", "landslides", "dams"}
    for k in polygons:
        assert EXPORT_LAYERS[k].geom_kind == "polygon", k
    for k in points:
        assert EXPORT_LAYERS[k].geom_kind == "point", k


def test_land_registry_id_cols():
    for k in LAND_REGISTRY_VECTORS:
        assert EXPORT_LAYERS[k].id_col == "id", f"{k}: expected id_col='id'"


def test_land_registry_tables():
    assert EXPORT_LAYERS["mining-footprints"].table == "mining_footprints"
    assert EXPORT_LAYERS["tailings"].table == "tailings_dams"
    assert EXPORT_LAYERS["fires"].table == "active_fires"
    assert EXPORT_LAYERS["air-quality"].table == "air_quality_stations"
    assert EXPORT_LAYERS["landslides"].table == "landslides"
    assert EXPORT_LAYERS["dams"].table == "dams"
    assert EXPORT_LAYERS["water-risk"].table == "water_risk"


def test_water_risk_includes_aqueduct_cat_columns():
    fields = EXPORT_LAYERS["water-risk"].fields
    assert "w_awr_min_tot_cat" in fields
    assert "w_awr_min_tot_score" in fields
    assert "w_awr_min_tot_label" in fields


def test_tailings_excludes_generated_geog():
    fields = EXPORT_LAYERS["tailings"].fields
    assert "geog" not in fields


def test_mining_footprints_excludes_centroid_geog():
    fields = EXPORT_LAYERS["mining-footprints"].fields
    assert "centroid_geog" not in fields


def test_landslides_excludes_generated_geog():
    fields = EXPORT_LAYERS["landslides"].fields
    assert "geog" not in fields


def test_air_quality_includes_key_pollutant_columns():
    fields = EXPORT_LAYERS["air-quality"].fields
    for col in ("pm25", "no2", "o3", "so2"):
        assert col in fields, f"air-quality missing column: {col}"


# --- Task 8 fix: ocean-acidification horizon excluded from raw export ---
# horizon returns math.inf (always-supersaturated) -> invalid JSON; excluded from raw export

def test_ocean_acidification_vars_exclude_horizon():
    vars_ = EXPORT_LAYERS["ocean-acidification"].vars
    assert vars_ == ("aragonite", "calcite")
    assert "horizon" not in vars_


def test_ocean_acidification_exported_vars_are_json_safe():
    # aragonite/calcite are raw GLODAP fields: missing -> None -> valid JSON null,
    # never Infinity/NaN, so a representative exported record always serializes safely.
    rec = {"aragonite": None, "calcite": 2.34}
    json.dumps(rec, allow_nan=False)  # must not raise

    # horizon, by contrast, can be math.inf for always-supersaturated cells, which is
    # exactly why it was removed from the export vars — this documents the failure mode.
    try:
        json.dumps({"horizon": math.inf}, allow_nan=False)
        assert False, "expected ValueError for non-finite float with allow_nan=False"
    except ValueError:
        pass


# --- Task 9: Coral acidification exposure ---

def test_coral_acid_exposure_present():
    assert "coral-acid-exposure" in EXPORT_LAYERS
    assert isinstance(EXPORT_LAYERS["coral-acid-exposure"], VectorExport)


def test_coral_acid_exposure_cap_positive():
    assert EXPORT_LAYERS["coral-acid-exposure"].cap > 0


def test_coral_acid_exposure_fields_nonempty_no_geom():
    v = EXPORT_LAYERS["coral-acid-exposure"]
    assert len(v.fields) > 0, "empty fields"
    for f in v.fields:
        assert f not in ("geom", "geom_3857", "geog", "centroid_geog"), (
            f"geometry/internal column in fields: {f}"
        )


def test_coral_acid_exposure_provenance_set():
    prov = EXPORT_LAYERS["coral-acid-exposure"].prov
    assert prov.source, "missing prov.source"
    assert prov.source_url, "missing prov.source_url"


def test_coral_acid_exposure_geom_kind_polygon():
    assert EXPORT_LAYERS["coral-acid-exposure"].geom_kind == "polygon"


# ── Layers deliberately absent from the download surface ──────────────────────
#
# ⛔ This registry IS the download access. A layer whose upstream terms restrict
# redistribution — or, in one case, use — must not be reachable through it, and
# an accidental re-add is exactly the kind of change that looks harmless in a
# diff. The reason travels with the id so the next person deciding has it.
NOT_EXPORTABLE = {
    "wdpa":  "UNEP-WCMC forbids redistribution through an interactive web map "
             "granting download access, without prior written permission",
    "kbas":  "BirdLife's KBA terms carry the same clause, plus no-commercial-use",
    "noise-risk": "blends OBIS-SEAMAP cetacean sightings; OBIS-SEAMAP forbids "
                  "redistributing data obtained from the portal",
    "hydrophone-stations": "aggregates MBARI MARS, released for internal research "
                           "activities only — a clause on use, not just redistribution",
    "eez": "VLIZ asks that their products not be made available for download "
           "elsewhere; a courtesy rather than a licence obligation",
}


def test_restricted_layers_are_not_reachable_through_the_export_registry():
    present = sorted(k for k in NOT_EXPORTABLE if k in EXPORT_LAYERS)
    assert not present, (
        "these layers must not be downloadable: "
        + "; ".join(f"{k} ({NOT_EXPORTABLE[k]})" for k in present)
    )


def test_the_frontend_export_menu_does_not_offer_them_either():
    """The registry and the menu are two doors into the same room.

    `noise-risk` was in the registry but never in the menu, so the UI looked
    clean while the API served it. Checking only the visible half is how that
    survived.
    """
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2]
           / "frontend" / "src" / "utils" / "exportLayers.ts").read_text()
    for layer_id in NOT_EXPORTABLE:
        assert f'id: "{layer_id}"' not in src, f"{layer_id} still offered in the export menu"
