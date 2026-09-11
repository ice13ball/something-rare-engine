# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Single source of truth for the Area Export feature.

Pass-through, not authority: each entry points at the RAWEST form we hold and
carries provenance so users verify against the upstream source, not us.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Provenance:
    source: str
    source_url: str
    license: str | None = None
    citation: str | None = None
    note: str | None = None


@dataclass(frozen=True)
class VectorExport:
    id: str
    label: str
    table: str
    geom_col: str            # geometry column on `table` OR on the joined parent
    id_col: str
    fields: tuple[str, ...]  # explicit source columns; NO SELECT *
    geom_kind: str           # "point" | "polygon" | "line"
    cap: int
    prov: Provenance
    join_sql: str | None = None  # e.g. "JOIN memento_casts c ON c.cast_id = t.cast_id"


@dataclass(frozen=True)
class FieldSource:
    id: str
    label: str
    sampler: str             # service module name under backend/services/
    vars: tuple[str, ...]    # source variable keys emitted as columns
    has_depth: bool
    has_decade: bool
    cap: int
    prov: Provenance


@dataclass(frozen=True)
class CompositeExport:
    id: str
    label: str
    members: tuple[str, ...]  # FieldSource ids


def kind_of(entry) -> str:
    if isinstance(entry, VectorExport):
        return "vector"
    if isinstance(entry, FieldSource):
        return "field"
    if isinstance(entry, CompositeExport):
        return "composite"
    raise TypeError(type(entry))


# --- field sources (marine-carbon members) ---------------------------------
_FIELDS: dict[str, FieldSource] = {
    "socat-co2": FieldSource(
        id="socat-co2", label="Surface CO₂ (SOCAT v2026)", sampler="socat_co2",
        vars=("fco2", "sst", "salinity", "density"), has_depth=False, has_decade=True,
        cap=20_000,
        prov=Provenance(
            source="SOCAT v2026 (decadal gridded)",
            source_url="https://www.socat.info/",
            license="CC-BY 4.0",
            citation="Bakker et al. 2026 (NCEI Accession 0315110, doi:10.25921/8dba-fr90)",
            note="Sparse / non-gap-filled; ~21% of cells have data.",
        ),
    ),
    "glodap-carbon": FieldSource(
        id="glodap-carbon", label="Interior carbon (GLODAP v2.2016b)", sampler="glodap_carbon",
        vars=("dic", "talk", "ph", "cant"), has_depth=True, has_decade=False,
        cap=20_000,
        prov=Provenance(
            source="GLODAP v2.2016b Mapped Climatology",
            source_url="https://www.glodap.info/",
            license="CC-BY 4.0",
            citation="Lauvset et al. 2016 (ESSD 8:325) + Key et al. 2015 (NDP-093)",
        ),
    ),
    "isas20-oxygen": FieldSource(
        id="isas20-oxygen", label="Dissolved oxygen (ISAS20)", sampler="oxygen_deox",
        vars=("o2",), has_depth=True, has_decade=False, cap=20_000,
        prov=Provenance(
            source="ISAS20 (BGC-Argo 2014–2018 mean)",
            source_url="https://www.seanoe.org/data/00412/52367/",
            citation="ISAS20 release",
        ),
    ),
    "woa23": FieldSource(
        id="woa23", label="Physical & nutrients (WOA23)", sampler="woa_climatology",
        vars=("temperature", "salinity", "oxygen", "aou", "o2sat",
              "phosphate", "silicate", "nitrate"),
        has_depth=True, has_decade=False, cap=20_000,
        prov=Provenance(
            source="NOAA World Ocean Atlas 2023 (WOA23)",
            source_url="https://www.ncei.noaa.gov/products/world-ocean-atlas",
            citation="WOA23 release",
        ),
    ),
    "seabed-substrate": FieldSource(
        id="seabed-substrate",
        label="Seabed Substrate (Dutkiewicz 2015)",
        sampler="seabed_lithology",
        vars=("class",),
        has_depth=False,
        has_decade=False,
        cap=50_000,
        prov=Provenance(
            source="Dutkiewicz et al. 2015 seafloor lithology (EarthByte)",
            source_url="https://www.earthbyte.org/seafloor-lithology-of-the-ocean-basins/",
            license="CC-BY-NC 4.0",
            citation="Dutkiewicz, A. et al. 2015, Geology, doi:10.1130/G36883.1",
            note="Non-commercial use only. 0.1° categorical model, not a per-site assay.",
        ),
    ),
    "bathymetry": FieldSource(
        id="bathymetry", label="Bathymetry (GEBCO 2024)",
        sampler="bathymetry_grid_export", vars=("depth_m",),
        has_depth=False, has_decade=False, cap=50_000,
        prov=Provenance(
            source="GEBCO 2024 Grid", source_url="https://www.gebco.net/",
            license="GEBCO public-domain (acknowledgement requested)",
            note="Elevation/depth in metres (negative = below sea level). Exported downsampled "
                 "to ~0.05° (~5.5 km); full 15-arcsec grid at GEBCO/BODC. Large areas of interest "
                 "are truncated at 50,000 cells; narrow the AOI for full coverage.",
        ),
    ),
    "ocean-acidification": FieldSource(
        id="ocean-acidification", label="Ocean Acidification (GLODAP ΩA/ΩC)",
        sampler="acidification", vars=("aragonite", "calcite"),
        has_depth=True, has_decade=False, cap=20_000,
        prov=Provenance(
            source="GLODAP v2.2016b Mapped Climatology (OmegaA/OmegaC)",
            source_url="https://www.glodap.info/",
            license="CC-BY 4.0",
            citation="Lauvset et al. 2016 (ESSD 8:325, doi:10.5194/essd-8-325-2016) + "
                     "Key et al. 2015 (NDP-093)",
            note="Exports GLODAP's raw aragonite/calcite saturation (ΩA/ΩC), read directly "
                 "(never recomputed via PyCO2SYS). The aragonite saturation-horizon depth is "
                 "platform-derived and depth-invariant, so it is exported separately as "
                 "`ocean-acidification-horizon` (kept out of this depth-resolved source to "
                 "avoid duplicating it across every depth level).",
        ),
    ),
    "ocean-acidification-horizon": FieldSource(
        id="ocean-acidification-horizon", label="Aragonite saturation-horizon depth",
        sampler="acidification", vars=("horizon",),
        has_depth=False, has_decade=False, cap=50_000,
        prov=Provenance(
            source="Platform-derived from GLODAP v2.2016b OmegaA",
            source_url="https://www.glodap.info/",
            license="CC-BY 4.0",
            citation="Derived from GLODAP OmegaA — Lauvset et al. 2016 (ESSD 8:325, "
                     "doi:10.5194/essd-8-325-2016) + Key et al. 2015 (NDP-093)",
            note="PLATFORM-DERIVED, not a GLODAP variable: the shallowest depth (metres) at "
                 "which aragonite saturation ΩA crosses below 1.0, linearly interpolated across "
                 "GLODAP's 33 standard levels. A 2-D field (no depth axis). Cells with no "
                 "aragonite saturation horizon — always-supersaturated water columns (ΩA never "
                 "drops below 1) and land — are omitted; an absent cell is not corrosive at any "
                 "depth. ΩA itself is GLODAP's, read directly (never recomputed via PyCO2SYS).",
        ),
    ),
    "ocean-acidification-horizon-shift": FieldSource(
        id="ocean-acidification-horizon-shift",
        label="Aragonite horizon shift since preindustrial (modeled)",
        sampler="acidification", vars=("horizon_shift",),
        has_depth=False, has_decade=False, cap=50_000,
        prov=Provenance(
            source="GLODAP v2.2016b Mapped Climatology (TCO2, PI_TCO2, TAlk, nutrients)",
            source_url="https://glodap.info/",
            license="Released without restrictions (NDP-093 §6); citation requested",
            citation=("Lauvset et al. 2016 (ESSD 8:325, doi:10.5194/essd-8-325-2016); "
                      "Key et al. 2015 (NDP-093); "
                      "PyCO2SYS: Humphreys et al. 2022 (GMD 15:15)"),
            note=("Platform-derived. Aragonite saturation reconstructed with PyCO2SYS from "
                  "GLODAP's present-day (TCO2) and preindustrial (PI_TCO2) dissolved "
                  "inorganic carbon through one identical CO2SYS configuration "
                  "(opt_k_carbonic=10); the value is horizon_PI - horizon_today in metres, "
                  "positive meaning the horizon has shoaled. 'Today' is the GLODAP mapped "
                  "reference year, nominally ~2002 — this is a comparison of two climatology "
                  "snapshots, NOT a rate or trend. Cells where either horizon is absent or "
                  "the column never crosses omega=1 are omitted. The reconstruction was "
                  "validated against GLODAP's published OmegaA (median difference +0.0017)."),
        ),
    ),
    "cumulative-human-impact": FieldSource(
        id="cumulative-human-impact",
        label="Cumulative Human Impact (modelled)",
        # chi_impact.sample(lat, lon) has no var/depth; chi_impact_export shims it onto
        # the _load_grid(var)/sample(var,lat,lon,lev) contract _field_rows expects.
        sampler="chi_impact_export", vars=("impact",),
        has_depth=False, has_decade=False, cap=50_000,
        prov=Provenance(
            source="NCEAS / Halpern et al. 2025",
            source_url="https://doi.org/10.1126/science.adv2906",
            license="CC0 1.0 Public Domain",
            citation=("Halpern et al. 2025, 'Cumulative impacts to global marine ecosystems' "
                      "(Science, doi:10.1126/science.adv2906); data archive "
                      "doi:10.5063/F18K77KZ"),
            note=("Modelled dimensionless index of total human pressure — the present-state "
                  "sum of ~10 anthropogenic stressors across six categories; NOT a measurement "
                  "and NOT a per-year rate. Seabed mining is only a minor component. A "
                  "concession polygon is not a causal source of this impact; a value over an "
                  "ISA claim is not evidence about mining. Present-state only."),
        ),
    ),
    "ocean-currents": FieldSource(
        id="ocean-currents", label="Ocean Currents (CMEMS surface + 1000 m)",
        sampler="currents_grid_export", vars=("u", "v"),
        has_depth=True, has_decade=False, cap=50_000,
        prov=Provenance(
            source="CMEMS Global Ocean Physics (u/v velocity)",
            source_url="https://data.marine.copernicus.eu/",
            license="Copernicus Marine Service licence",
            note="Eastward (u) / northward (v) velocity in m/s at surface and 1000 m. Exported "
                 "from the platform's baked ~0.5° field; native CMEMS resolution at source. "
                 "Values come from the model's float grid. Where that grid is missing for a "
                 "depth the sampler falls back to the 8-bit rendering texture, whose step is "
                 "6/255 = 0.0235 m/s across a ±3 m/s span — at 1000 m, where the median speed "
                 "is about 0.037 m/s, that fallback resolves most of the ocean to one or two "
                 "steps. Measured 2026-09-10.",
        ),
    ),
}

# --- vector layers (6 IO-PAN + 5 ISA/seabed) --------------------------------
# NOTE TO IMPLEMENTER: confirm each `fields` tuple against the live CREATE TABLE
# in backend/land_layers.py / backend/schema.py (ensure_schema/ensure_land_schema).
_VECTORS: dict[str, VectorExport] = {
    "arctic-rivers": VectorExport(
        id="arctic-rivers", label="Arctic River Inputs", table="arctic_river_stations",
        geom_col="t.geom", id_col="station_id", geom_kind="point", cap=10_000,
        fields=("station_id", "source", "river_name", "site_label", "lat", "lon",
                "record_start", "record_end", "mean_annual_discharge_km3",
                "summary_stats", "citation", "units"),
        prov=Provenance(
            source="ArcticGRO + PANGAEA", source_url="https://arcticgreatrivers.org/data/",
            note="Series are monthly-downsampled at ingest; full-resolution data at source_url.",
        ),
    ),
    "arctic-catchments": VectorExport(
        id="arctic-catchments", label="Arctic Catchments (ARCADE)", table="arctic_catchments",
        geom_col="t.geom", id_col="gid", geom_kind="polygon", cap=5_000,
        fields=("gid", "name", "stream_order", "continent", "area_km2",
                "center_lat", "center_lon", "ocs_mean", "oc_tot", "runoff_mean",
                "pf_frac", "t_2m_mean", "params"),
        prov=Provenance(
            source="ARCADE v1 (DataVerse)",
            source_url="https://doi.org/10.34894/U9HSPV",
            note="Verbatim source values; t_2m_mean is in KELVIN; runoff unit unspecified upstream.",
        ),
    ),
    "permafrost-thaw": VectorExport(
        id="permafrost-thaw", label="Permafrost Thaw", table="permafrost_thaw_features",
        geom_col="t.geom", id_col="unique_id", geom_kind="point", cap=60_000,
        fields=("unique_id", "source", "feature_name", "feature_type", "feature_category",
                "thaw_type", "data_source_type", "authors", "source_doi", "imagery",
                "lat", "lon"),
        prov=Provenance(
            source="Alaska Permafrost Thaw DB v2.0.0 (Webb et al. 2026) + ARTS v6.0.0 (whrc)",
            source_url="https://doi.org/10.5281/zenodo.16996415",
            license="alaska_webb: CC-BY 4.0; arts_panarctic: CC0",
            citation="Webb et al. 2026 (ESSD 18:3147); Yang, Rodenhizer, Rogers et al. 2025 (Sci. Data 12:18, doi:10.1038/s41597-025-04372-7, Zenodo doi:10.5281/zenodo.10535025)",
            note="Two sub-sources distinguished by the 'source' column. ARTS points are centroids of digitised polygons (source geometry is EPSG:3413); only TrainClass=Positive slumps included.",
        ),
    ),
    "arctic-sediment-carbon": VectorExport(
        id="arctic-sediment-carbon", label="Arctic Sediment Carbon (CASCADE stations)",
        table="cascade_stations",
        geom_col="t.geom", id_col="id", geom_kind="point", cap=10_000,
        fields=("id", "station", "lat", "lon", "water_depth_m", "expedition",
                "year", "decade", "oc_pct", "tn_pct", "oc_tn", "d13c", "d14c",
                "hmw_alkanes", "hmw_acids", "lignin", "params"),
        prov=Provenance(
            source="CASCADE v2 (Circum-Arctic Sediment CArbon DatabasE), Bolin Centre for Climate Research",
            source_url="https://doi.org/10.17043/cascade-2",
            license="CC-BY 4.0",
            citation="CASCADE v2, Bolin Centre for Climate Research, doi:10.17043/cascade-2",
            note="Raw sediment-core station values (surface OC/TN/isotopes). The interpolated "
                 "raster field (baked from separate ESRI-ASCII polar-stereographic grids) is not "
                 "exportable in v1 — only the raw station table is.",
        ),
    ),
    # "noise-risk" removed 2026-09-04. The grid blends OBIS-SEAMAP cetacean
    # sightings, and OBIS-SEAMAP's terms forbid redistributing data obtained
    # from the portal. The index is derived rather than raw, but it is computed
    # per cell from those sightings and shipped with cetacean_count and
    # max_species alongside it — enough that "derived" stops being a defence.
    # This layer was never in the frontend export menu, only in this registry,
    # which made it downloadable by API alone and easy to miss.
    "sios-svalbard": VectorExport(
        id="sios-svalbard", label="SIOS Svalbard Observing", table="sios_datasets",
        geom_col="t.geom", id_col="metadata_id", geom_kind="point", cap=10_000,
        fields=("metadata_id", "title", "abstract", "is_core_data", "activity_type",
                "iso_topic", "institution", "pi_name", "time_start", "time_end",
                "license", "license_url", "url_http", "url_opendap", "url_wms",
                "url_landing", "lat", "lon"),
        prov=Provenance(
            source="SIOS Station REST catalogue",
            source_url="https://sios-svalbard.org/metadata_search",
            note="Discovery metadata; centroid (not GPS); follow url_* to the upstream dataset.",
        ),
    ),
    # vme_cells holds no geometry of its own — the hexes live on the shared grid, so the
    # spatial filter runs on density_hex_cells.geom (plain geometry(4326), no ::geometry
    # cast). Unlike the WOA/marine-carbon hex views — which are excluded because a rawer
    # source is already exportable — vme_cells IS the rawest form of this layer; there is
    # no VME field behind it. Excluding it would make the output unobtainable. Closest
    # precedent is arctic-catchments: also modeled per-polygon values, also exported.
    "vme-suitability": VectorExport(
        id="vme-suitability", label="VME coral suitability (modeled)", table="vme_cells",
        geom_col="h.geom", id_col="cell_id", geom_kind="polygon", cap=60_000,
        fields=("cell_id", "taxon_set", "suitability", "uncertainty",
                "extrapolated", "top_predictors"),
        join_sql="JOIN density_hex_cells h ON h.cell_id = t.cell_id",
        prov=Provenance(
            source="Abyssal Claims MaxEnt SDM (elapid) — platform-derived",
            source_url="https://deepseacoraldata.noaa.gov/",
            license="Occurrences public domain (US Govt); predictors per their own licences "
                    "(GLODAP CC-BY, WOA23, GEBCO, Dutkiewicz et al. 2015 CC-BY-NC).",
            citation="Occurrences: NOAA DSCRTP. Predictors: GEBCO 2024; Dutkiewicz et al. "
                     "2015; WOA23; ISAS20; GLODAPv2 (Lauvset et al. 2016 ESSD 8:325; Key "
                     "et al. 2015 NDP-093), aragonite saturation via PyCO2SYS.",
            note="MODELED, NOT OBSERVED — every value here is platform-derived, not an "
                 "upstream measurement. `suitability` is a relative environmental-similarity "
                 "index in 0..1, NOT a probability of presence and NOT evidence a vulnerable "
                 "marine ecosystem exists there; do not use it for causal or impact "
                 "inference. Training occurrences come from DSCRTP survey effort, which is "
                 "geographically uneven (concentrated in US and NE Atlantic waters), and the "
                 "target-group background does not fully correct for that bias. "
                 "`extrapolated` marks cells whose environment falls outside the range the "
                 "model was fitted on (univariate envelope — it does not catch novel "
                 "combinations of individually in-range predictors); `uncertainty` is the "
                 "ensemble spread and is the better guide to those. Predictors are sampled "
                 "at seafloor depth per cell, not a true 3-D water-column match.",
        ),
    ),
    "coral-acid-exposure": VectorExport(
        id="coral-acid-exposure", label="Coral acidification exposure (modeled)",
        table="vme_exposure_cells",
        geom_col="t.geom", id_col="cell_id", geom_kind="polygon", cap=60_000,
        fields=("cell_id", "taxon_set", "suitability", "uncertainty", "lat", "lon",
                "seafloor_m", "horizon_today_m", "horizon_pi_m", "state"),
        prov=Provenance(
            source="Platform-derived: VME MaxEnt suitability x reconstructed aragonite horizons x GEBCO 2024",
            source_url="https://something-rare.com/",
            license="Derived product. Inherits CC-BY-NC from one VME predictor (Dutkiewicz et al. 2015).",
            citation=("VME model: this platform (MaxEnt/elapid; occurrences NOAA DSCRTP, CC0; "
                      "predictors GEBCO 2024, seabed substrate Dutkiewicz et al. 2015 (CC-BY-NC), "
                      "WOA23, ISAS, GLODAPv2). Horizons: GLODAP v2.2016b (Lauvset et al. 2016; "
                      "Key et al. 2015) via PyCO2SYS (Humphreys et al. 2022)."),
            note=("EXPOSURE, NOT LOSS. state=corrosive means the seafloor sits in water "
                  "undersaturated with respect to aragonite; cold-water corals are documented "
                  "living below the saturation horizon at metabolic cost, so this is not a "
                  "prediction of habitat loss. Both inputs are modeled: VME suitability "
                  "(MaxEnt, AUC 0.875 / Boyce 0.518) and a 1x1 degree Omega climatology. "
                  "'Today' is GLODAP's mapped reference year, nominally ~2002; this compares "
                  "two climatology snapshots and is NOT a rate or trend. horizon_*_m is NULL "
                  "where the column never crosses omega=1 (state is then supersaturated)."),
        ),
    ),
    "memento": VectorExport(
        id="memento", label="MEMENTO CH₄/N₂O samples", table="memento_samples",
        geom_col="c.geom", id_col="id", geom_kind="point", cap=10_000,
        fields=("id", "cast_id", "depth_m", "sample_time", "ch4", "n2o",
                "n2o_perc", "o2", "temp", "sal", "params",
                "ch4_is_atmospheric", "n2o_is_atmospheric"),
        join_sql="JOIN memento_casts c ON c.cast_id = t.cast_id",
        prov=Provenance(
            source="GEOMAR MEMENTO",
            source_url="https://memento.geomar.de/",
            # MEMENTO's terms of use name Kock & Bange 2015 as the DATABASE citation;
        # Bange et al. 2009 is the project proposal paper. Both kept — the terms
        # also ask that original publications be cited for small extracts.
        citation=(
            "Kock, A. and Bange, H. W. (2015) Counting the ocean's greenhouse gas "
            "emissions, Eos 96(3), 10-13, doi:10.1029/2015EO023665. Project paper: "
            "Bange et al. 2009, Environ. Chem. doi:10.1071/en09033"
        ),
            note="Raw depth samples (not the cast rollup). Values are verbatim. MEMENTO "
                 "publishes dissolved and atmospheric gas under one column name (CH4 is "
                 "both Methane_Ocean [nmol/l] and Methane_Atmosphere [ppb]); "
                 "ch4_is_atmospheric / n2o_is_atmospheric are PLATFORM-DERIVED flags, not "
                 "MEMENTO's. Every row is exported, including flagged ones. May include "
                 "unpublished data — contact the contributing scientist before publishing.",
        ),
    ),
    "methane-seeps": VectorExport(
        id="methane-seeps", label="Methane Seeps (SEAFLEA)", table="seaflea_seeps",
        geom_col="t.geom", id_col="ext_id", geom_kind="point", cap=10_000,
        fields=("ext_id", "primary_type", "feature_types", "type_raw", "obs_year",
                "depth_m", "loc_uncert_m", "source_ref", "source_url"),
        prov=Provenance(
            source="SEAFLEA Observed Database (NRL / NOAA NCEI), frozen Feb-2019",
            source_url="https://www.ncei.noaa.gov/",
            citation="Phrampus, B.J. et al. (2020) A Global Probabilistic Prediction of Cold "
                     "Seeps and Associated SEAfloor FLuid Expulsion Anomalies (SEAFLEAs). "
                     "G-cubed 21. doi:10.1029/2019GC008747",
            license="US Government work (NRL / NOAA NCEI) — public domain.",
            note="COVERAGE IS SURVEY-BIASED. A compilation of 32 published studies, not a "
                 "systematic global survey: one BOEM Gulf of Mexico seismic survey supplies "
                 "6,126 of the 10,385 records (59%). The central North Sea has zero mapped "
                 "seeps; the nearest lies 418 km away. Absence of a record means absence of a "
                 "survey, NOT absence of a seep — do not use this layer to exclude a natural "
                 "methane source. 72% of records carry no obs_year. Values are verbatim.",
        ),
    ),
    "geotraces": VectorExport(
        id="geotraces", label="GEOTRACES trace metals (samples)", table="geotraces_samples",
        geom_col="t.geom", id_col="sample_id", geom_kind="point", cap=10_000,
        fields=("sample_id", "station_id", "depth_m", "mn_d", "fe_d", "co_d",
                "ni_d", "cu_d", "mn_d_qc", "fe_d_qc", "co_d_qc", "ni_d_qc",
                "cu_d_qc", "params"),
        prov=Provenance(
            source="GEOTRACES IDP2025 (BODC)",
            source_url="https://www.bodc.ac.uk/geotraces/",
            license="CC-BY 4.0",
            note="Raw depth samples (not the station rollup). Units: Co pmol/kg, others nmol/kg.",
        ),
    ),
    "geotraces-values": VectorExport(
        id="geotraces-values", label="GEOTRACES all parameters (per-sample values)",
        table="geotraces_values",
        geom_col="s.geom", id_col="sample_id", geom_kind="point", cap=60_000,
        # geotraces_values.sample_id is keyed on csv_row (CSV row ordinal), NOT
        # geotraces_sample_id — see DEFECT 1, 2026-09-08 audit.
        join_sql="JOIN geotraces_samples s ON s.csv_row = t.sample_id",
        fields=("t.sample_id", "s.station_id", "s.depth_m", "t.param_code",
                "t.value", "t.stddev", "t.qc_flag"),
        prov=Provenance(
            source="GEOTRACES IDP2025 (BODC)",
            source_url="https://www.bodc.ac.uk/geotraces/",
            license="CC-BY 4.0",
            note="Every measured parameter (not just the 5 dissolved-metal columns of the "
                 "'geotraces' layer), one row per sample x parameter. Units vary by parameter "
                 "— see /v2/spatial/geotraces/params for the catalogue. Values are verbatim.",
        ),
    ),
    "mosaic": VectorExport(
        id="mosaic", label="Marine Sediment Carbon (MOSAIC)", table="mosaic_samples",
        geom_col="t.geom", id_col="sample_id", geom_kind="point", cap=60_000,
        join_sql="JOIN mosaic_cores c ON c.core_id = t.core_id",
        fields=("t.sample_id", "t.core_id", "c.core_name", "c.latitude", "c.longitude",
                "c.water_depth_m", "c.sampling_year", "t.depth_upper_cm", "t.depth_bottom_cm",
                "t.depth_avg_cm", "t.material_analyzed", "t.toc", "t.tn", "t.d13c",
                "t.d14c", "t.fm14c", "t.provenance"),
        prov=Provenance(
            source="MOSAIC (Modern Ocean Sediment Archive and Inventory of Carbon), ETH Zürich",
            source_url="https://mosaic.ethz.ch/",
            license="CC-BY 4.0",
            citation="Van der Voort et al. 2021 (ESSD 13:2135) · MOSAIC DOI 10.5168/mosaic019.1",
            note="Literature-compiled; each value's original-paper DOI is in the provenance column.",
        ),
    ),
    # --- ISA & seabed registries ---
    # Fields verified against live DB via `\d <table>` on 2026-06-29.
    # Excludes: geom, geom_3857 (generated stored column on offshore_activities).
    "contracts": VectorExport(
        id="contracts", label="Mining contracts (ISA)", table="mining_contracts",
        geom_col="t.geom", id_col="isa_id", geom_kind="polygon", cap=5_000,
        fields=("id", "isa_id", "contractor_name", "resource_type", "area_km2",
                "expiry_date", "region", "is_high_risk", "created_at", "act_date",
                "jurisdiction_text", "nearest_eez_country", "nearest_eez_dist_km",
                "nearest_unesco_site", "nearest_unesco_dist_km", "vent_conflicts",
                "nearby_species", "nearby_argo_floats", "nearby_onc_stations",
                "nearby_oceansites_moorings", "seo_enriched_at"),
        prov=Provenance(
            source="International Seabed Authority (ISA)",
            source_url="https://www.isa.org.jm/exploration-areas",
            note="Includes enrichment columns computed at ingest (nearest EEZ/UNESCO, vent conflicts).",
        ),
    ),
    "reserved-areas": VectorExport(
        id="reserved-areas", label="Reserved areas (ISA)", table="reserved_areas",
        geom_col="t.geom", id_col="arcgis_id", geom_kind="polygon", cap=5_000,
        fields=("arcgis_id", "contract_id", "area_type", "area_km2",
                "status", "remarks", "synced_at"),
        prov=Provenance(
            source="International Seabed Authority (ISA)",
            source_url="https://www.isa.org.jm/exploration-areas",
        ),
    ),
    "apeis": VectorExport(
        id="apeis", label="APEIs (ISA)", table="isa_apeis",
        geom_col="t.geom", id_col="arcgis_id", geom_kind="polygon", cap=5_000,
        fields=("arcgis_id", "area_km2", "status", "remarks", "synced_at"),
        prov=Provenance(
            source="International Seabed Authority (ISA)",
            source_url="https://www.isa.org.jm/exploration-areas",
            note="Areas of Particular Environmental Interest designated by the ISA.",
        ),
    ),
    "relinquished-areas": VectorExport(
        id="relinquished-areas", label="Relinquished areas (ISA)", table="relinquished_areas",
        geom_col="t.geom", id_col="arcgis_id", geom_kind="polygon", cap=5_000,
        fields=("arcgis_id", "contract_id", "area_type", "area_km2",
                "act_date", "status", "synced_at"),
        prov=Provenance(
            source="International Seabed Authority (ISA)",
            source_url="https://www.isa.org.jm/exploration-areas",
        ),
    ),
    "offshore-activities": VectorExport(
        id="offshore-activities", label="Offshore activities", table="offshore_activities",
        geom_col="t.geom", id_col="id", geom_kind="polygon", cap=5_000,
        fields=("id", "source", "source_id", "activity_type", "name", "operator",
                "country", "sovereign", "status", "awarded_date", "expires_date",
                "jurisdiction", "portal_url", "attributes", "updated_at"),
        prov=Provenance(
            source="National government offshore registries",
            source_url="https://www.boem.gov/",
            note="Multi-source: BOEM, NSTA, Sodir, EMODnet, NOPTA, ANH, MEEI, PASA, ANCAP et al. "
                 "Follow portal_url per-feature for the authoritative upstream record. "
                 "geom_3857 (generated column) excluded. EU EEZ blocks are sourced from "
                 "EMODnet Human Activities, funded by the European Commission (DG MARE), CC BY 4.0.",
        ),
    ),
    # --- Task 5: Life & geology batch ---
    # geom types verified via \d <table> on live DB 2026-06-29:
    #   geography -> ::geometry cast required; geometry -> no cast.
    "seamounts": VectorExport(
        id="seamounts", label="Seamounts", table="seamounts",
        geom_col="t.geom::geometry", id_col="peak_id", geom_kind="point", cap=10_000,
        fields=("id", "peak_id", "summit_depth_m", "height_m", "longitude", "latitude",
                "area_km2", "in_2011", "overlapping_base", "in_concession"),
        prov=Provenance(
            source="Yesson et al. 2020 (PANGAEA v2)",
            source_url="https://doi.pangaea.de/10.1594/PANGAEA.921688",
            license="CC-BY 4.0",
            citation="Yesson et al. 2020, doi:10.1594/PANGAEA.921688",
        ),
    ),
    "hydrothermal-vents": VectorExport(
        id="hydrothermal-vents", label="Hydrothermal vents", table="hydrothermal_vents",
        geom_col="t.geom::geometry", id_col="id", geom_kind="point", cap=10_000,
        fields=("id", "name", "status", "depth_m", "latitude", "longitude",
                "source_url", "created_at", "chess_count", "chess_species",
                "max_temp_c", "temp_category", "min_depth_m", "ocean", "region",
                "jurisdiction", "tectonic_setting", "discovery_year",
                "discovery_year_num", "date_precision",
                "biology_notes", "description_notes"),
        prov=Provenance(
            source="InterRidge Vents Database v3.4",
            source_url="https://vents-data.interridge.org/",
            note="Coordinates are the best-available published position; "
                 "status Active/Inactive/Extinct per InterRidge registry.",
        ),
    ),
    "biodiversity-hotspots": VectorExport(
        id="biodiversity-hotspots", label="Biodiversity (OBIS)", table="biodiversity_hotspots",
        geom_col="t.geom", id_col="obis_id", geom_kind="point", cap=10_000,
        fields=("id", "obis_id", "scientific_name", "vernacular_name", "category",
                "is_endangered", "created_at", "phylum", "class_name", "order_name",
                "family", "depth", "description", "image_url", "iucn_category"),
        prov=Provenance(
            source="OBIS",
            source_url="https://obis.org/",
            note="Per-record dataset licences vary; see source_url. "
                 "IUCN status from OBIS-hosted records.",
        ),
    ),
    "chess": VectorExport(
        id="chess", label="Chemosynthetic life (ChEssBase)", table="chess_occurrences",
        geom_col="t.geom", id_col="occurrence_id", geom_kind="point", cap=10_000,
        fields=("id", "occurrence_id", "species", "phylum", "class_name", "family",
                "depth_m", "lat", "lon", "locality", "institution_code", "habitat_type"),
        prov=Provenance(
            source="ChEssBase (OBIS)",
            source_url="https://obis.org/dataset/471a8de8-80f8-43f9-9443-88a45712feba",
            note="Chemosynthetic ecosystem occurrences (hydrothermal vents, cold seeps, "
                 "whale falls, wood falls, etc.).",
        ),
    ),
    # "eez" removed 2026-09-04. CC-BY 4.0 permits this, and VLIZ only *asks*:
    # "We kindly request our users not to make our products available for
    # download elsewhere." An export endpoint is exactly that. Honouring a
    # request costs one endpoint; the layer still renders and the boundaries are
    # still visible. Note this is a courtesy, not a licence obligation — it can
    # be reversed without asking anyone.
    "protected-marine-sites": VectorExport(
        id="protected-marine-sites", label="Marine protected sites (UNESCO)",
        table="protected_marine_sites",
        geom_col="t.geom", id_col="site_id", geom_kind="polygon", cap=5_000,
        fields=("site_id", "name", "country", "lat_whc", "lon_whc", "area_km2", "synced_at"),
        prov=Provenance(
            source="UNESCO World Heritage Marine + MarineRegions.org",
            source_url="https://whc.unesco.org/en/marine/",
        ),
    ),
    "deepdata-stations": VectorExport(
        id="deepdata-stations", label="DeepData stations (ISA)", table="deepdata_stations",
        geom_col="t.geom::geometry", id_col="station_id", geom_kind="point", cap=10_000,
        fields=("station_id", "archive_slug", "contractor_code", "event_id_raw",
                "location_id", "sampling_protocol", "lat", "lon",
                "depth_m_min", "depth_m_max", "coord_uncertainty_m",
                "first_event_date", "last_event_date", "occurrence_count",
                "species_count", "sediment_horizons", "derived_at",
                "top_species", "top_phyla"),
        prov=Provenance(
            source="ISA contractor DwC archives (via OBIS)",
            source_url="https://www.isa.org.jm/",
            note="Platform-derived station rollups; not the contractor's own analysis. "
                 "Aggregated from ISA contractor submissions to OBIS.",
        ),
    ),
    # --- Task 6: Sensors registry batch ---
    # geom types verified via live `\d <table>` on apiv2 DB 2026-06-29:
    #   argo_profiles, oceansites_stations, onc_locations, onc_instruments,
    #   wod_oxygen_profiles → geometry(Point,4326) → t.geom (no cast).
    #   acoustic_stations → geography(Point,4326) → t.geom::geometry cast required.
    # wod table: an older doc said "wod_oxygen"; the live DB has "wod_oxygen_profiles";
    #   id col is "wod_cast_id" (UNIQUE TEXT), not "wod_unique_cast" as the doc stated.
    "argo": VectorExport(
        id="argo", label="Argo floats", table="argo_profiles",
        geom_col="t.geom", id_col="profile_id", geom_kind="point", cap=10_000,
        fields=("profile_id", "platform_id", "profile_date", "max_depth_m",
                "surface_temp_c", "surface_salinity", "deep_temp_c", "deep_salinity",
                "deep_pressure_m", "oxygen_umol_kg", "ph",
                "temp_qc", "sal_qc", "oxygen_qc", "ph_qc",
                "near_mining", "mining_zone", "mining_dist_km",
                "nearest_contract_lon", "nearest_contract_lat", "mining_zones",
                "woa_surface_temp_c", "woa_surface_sal",
                "woa_deep_temp_c", "woa_deep_sal", "woa_deep_oxygen_umol_kg",
                "woa_deep_aou", "woa_deep_o2sat", "woa_deep_phosphate",
                "woa_deep_silicate", "woa_deep_nitrate"),
        prov=Provenance(
            source="Argo (GDAC / Euro-Argo)",
            source_url="https://argo.ucsd.edu/",
            license="CC-BY 4.0",
            note="Delayed-mode QC profiles; woa_* columns are WOA23 climatology enrichment "
                 "added at ingest (not original Argo fields).",
        ),
    ),
    "oceansites": VectorExport(
        id="oceansites", label="OceanSITES moorings", table="oceansites_stations",
        geom_col="t.geom", id_col="ref", geom_kind="point", cap=10_000,
        fields=("ref", "name", "lat", "lon", "status", "network", "deploy_date",
                "updated_at", "latest_obs", "obs_fetched_at", "age_days", "model",
                "obs_source"),
        prov=Provenance(
            source="OceanSITES / OceanOPS",
            source_url="https://www.oceansites.org/",
            license="CC-BY 4.0",
        ),
    ),
    "onc": VectorExport(
        id="onc", label="ONC observatories", table="onc_locations",
        geom_col="t.geom", id_col="location_code", geom_kind="point", cap=10_000,
        fields=("location_code", "name", "lat", "lon", "depth_m", "description",
                "updated_at", "latest_sensors", "sensors_fetched_at"),
        prov=Provenance(
            source="Ocean Networks Canada (ONC)",
            source_url="https://data.oceannetworks.ca/",
            license="CC-BY 4.0",
        ),
    ),
    "onc-instruments": VectorExport(
        id="onc-instruments", label="ONC instruments", table="onc_instruments",
        geom_col="t.geom", id_col="id", geom_kind="point", cap=10_000,
        fields=("id", "device_id", "device_code", "device_name", "device_category",
                "location_code", "location_name", "site_name", "depth_m",
                "image_url", "updated_at", "deployment_start", "deployment_end",
                "status", "description", "data_products", "device_link",
                "location_link", "enriched_at", "latest_readings"),
        prov=Provenance(
            source="Ocean Networks Canada (ONC)",
            source_url="https://data.oceannetworks.ca/",
            license="CC-BY 4.0",
        ),
    ),
    # "hydrophone-stations" removed 2026-09-04. The aggregate covers 22 passive-
    # acoustic networks, one of which is MBARI MARS, released for "internal
    # research activities only". That clause binds USE, not just redistribution,
    # so it is the sharper of the two: a bulk download of the aggregate carries
    # the MARS rows out under terms that never permitted them to travel.
    # Per-source filtering would be the finer answer; withdrawing the export is
    # the honest one until someone has read all 22 policies.
    "wod-oxygen": VectorExport(
        id="wod-oxygen", label="WOD oxygen profiles", table="wod_oxygen_profiles",
        geom_col="t.geom", id_col="wod_cast_id", geom_kind="point", cap=50_000,
        fields=("id", "wod_cast_id", "lat", "lon", "profile_date", "profile_time",
                "time_precision", "decade",
                "cruise", "dataset", "country", "probe_type",
                "max_depth_m", "n_levels", "o2_profile", "o2_units",
                "qc_flag", "qc_note"),
        prov=Provenance(
            source="NOAA World Ocean Database 2023 (WOD23)",
            source_url="https://www.ncei.noaa.gov/products/world-ocean-database",
            citation="doi:10.7289/V5H70CVX",
            note="o2_profile is a JSONB array of {depth_m, o2} level pairs. "
                 "Admin-seeded; table may be empty until seeded via Force Sync.",
        ),
    ),
    # --- Task 7: Infrastructure — cable composite members ---
    # All six tables have geometry(MultiLineString,4326) except noaa_cables which is
    # geometry(MultiPolygon,4326) (corridor polygons, not centrelines).
    # Columns verified via live `\d <table>` on apiv2 DB 2026-06-29.
    "cables-emodnet": VectorExport(
        id="cables-emodnet", label="Submarine cables — EMODnet",
        table="submarine_cables",
        geom_col="t.geom", id_col="id", geom_kind="line", cap=10_000,
        fields=("id", "name", "status", "inst_year", "length_km", "location",
                "operator", "cable_type", "voltage_kv", "source_layer", "source_id"),
        prov=Provenance(
            source="EMODnet Human Activities (7 contributors: NVE, Rijkswaterstaat, BSH, "
                   "SIG, UK NSTA, Spanish MITECO)",
            source_url="https://emodnet.ec.europa.eu/en/human-activities",
            license="CC BY 4.0",
            citation="EMODnet Human Activities, funded by the European Commission "
                     "Directorate-General for Maritime Affairs and Fisheries (DG MARE). "
                     "https://emodnet.ec.europa.eu",
            note="Aggregates 7 national contributor layers (~1,255 features). "
                 "voltage_kv populated for Norwegian NVE cables only.",
        ),
    ),
    "cables-noaa": VectorExport(
        id="cables-noaa", label="Submarine cables — NOAA Marine Cadastre",
        table="noaa_cables",
        geom_col="t.geom", id_col="id", geom_kind="polygon", cap=10_000,
        fields=("id", "object_id", "short_name", "cable_system", "owner",
                "status", "region", "shape_length"),
        prov=Provenance(
            source="NOAA Marine Cadastre (joint NOAA/BOEM)",
            source_url="https://marinecadastre.gov/",
            note="2,816 US cable protection zone CORRIDORS (polygon footprints), "
                 "not cable centrelines. Includes Great Lakes freshwater cables.",
        ),
    ),
    "cables-nz": VectorExport(
        id="cables-nz", label="Submarine cables — NZ LINZ",
        table="nz_cables",
        geom_col="t.geom", id_col="id", geom_kind="line", cap=10_000,
        fields=("id", "fidn", "catcbl", "catcbl_raw", "status", "status_raw",
                "condtn", "condtn_raw", "objnam", "inform", "txtdsc",
                "burdep", "datsta", "datend"),
        prov=Provenance(
            source="LINZ NZ Hydrographic (S-57 chart layer 51643)",
            source_url="https://data.linz.govt.nz/layer/51643",
            note="Geometry-only chart symbology; cable operator names (objnam) are never "
                 "populated. catcbl/status/condtn decoded from S-57 codes.",
        ),
    ),
    "cables-au": VectorExport(
        id="cables-au", label="Submarine cables — AU ACMA",
        table="au_cables",
        geom_col="t.geom", id_col="id", geom_kind="line", cap=10_000,
        fields=("id", "object_id", "cable", "abbrev"),
        prov=Provenance(
            source="ACMA / Geoscience Australia (AODN)",
            source_url="https://www.cmar.csiro.au/geoserver/web/",
            note="16 cable protection zone polylines (Perth + Northern/Southern Sydney). "
                 "Dataset frozen at 2021.",
        ),
    ),
    "cables-onc": VectorExport(
        id="cables-onc", label="Submarine cables — ONC",
        table="onc_cables",
        geom_col="t.geom", id_col="id", geom_kind="line", cap=10_000,
        fields=("id", "ext_id", "status", "length_m", "comments"),
        prov=Provenance(
            source="Ocean Networks Canada (NEPTUNE + VENUS observatory cables)",
            source_url="https://www.oceannetworks.ca/observatories/",
        ),
    ),
    "cables-ooi": VectorExport(
        id="cables-ooi", label="Submarine cables — OOI",
        table="ooi_cables",
        geom_col="t.geom", id_col="id", geom_kind="line", cap=10_000,
        fields=("id", "ext_id", "line_name", "length_m", "node_count",
                "deepest_node_m", "shallowest_node_m", "comments"),
        prov=Provenance(
            source="OOI Regional Cabled Array (off Oregon)",
            source_url="https://github.com/oceanobservatories/asset-management",
            note="Approximate straight-line routes between published Primary Node "
                 "coordinates; actual cable follows seafloor bathymetry.",
        ),
    ),
    # --- Task 8: Land registry batch ---
    # Columns verified via live `\d <table>` on apiv2 DB 2026-06-29.
    # Generated geo helper columns excluded per-table:
    #   mining_footprints: centroid_geog (generated always as geography) → excluded.
    #   tailings_dams: geog (generated always as geography) → excluded.
    #   landslides: geog (generated always as geography) → excluded.
    # All geom columns are geometry(…,4326) → t.geom (no ::geometry cast needed).
    "mining-footprints": VectorExport(
        id="mining-footprints", label="Mining footprints",
        table="mining_footprints",
        geom_col="t.geom", id_col="id", geom_kind="polygon", cap=5_000,
        fields=("id", "country", "area_km2", "ftype", "source", "created_at"),
        prov=Provenance(
            source="Maus et al. 2022/2023 — PANGAEA",
            source_url="https://doi.org/10.1594/PANGAEA.942325",
            citation="Maus et al. 2022/2023 (PANGAEA, doi:10.1594/PANGAEA.942325)",
            note="Sentinel-2 derived mine polygons (pits, tailings, waste dumps, processing sites) "
                 "at 10 m resolution. centroid_geog (generated column) excluded.",
        ),
    ),
    # "kbas" removed 2026-09-03. BirdLife's KBA terms forbid redistribution
    # "through interactive web maps ... that grant users download access"
    # without prior written permission from the KBA Secretariat, plus a
    # separate no-commercial-use clause. This registry IS the download access;
    # the map was the interactive web map. Both had to go.
    # "wdpa" removed 2026-09-03. Protected Planet forbids redistribution
    # "through interactive web maps ... that grant users download access"
    # without prior written permission from UNEP-WCMC. This registry IS the
    # download access; the map was the interactive web map. Both had to go.
    "tailings": VectorExport(
        id="tailings", label="Tailings dams",
        table="tailings_dams",
        geom_col="t.geom", id_col="id", geom_kind="point", cap=10_000,
        fields=("id", "dam_name", "mine_name", "country", "dam_type", "height_m",
                "volume_m3", "risk_class", "status", "owner_company", "operator",
                "construction_year", "hazard_raw", "raise_type", "data_source",
                "created_at"),
        prov=Provenance(
            source="Hudson-Edwards, K. et al. (2023) WAPHA global metal mines database "
                   "(doi:10.5061/dryad.j3tx95xmg) + GRID-Arendal / UNEP (Global Tailings Portal)",
            source_url="https://doi.org/10.5061/dryad.j3tx95xmg",
            license="WAPHA: CC0 (Dryad). GRID-Arendal: company-disclosed, see tailing.grida.no.",
            citation="Macklin, M.G. et al. (2023) Impacts of metal mining on river systems. "
                     "Science 381:1345. doi:10.1126/science.adg6704",
            note="Rows carry data_source: 'wapha' (base compilation, name + point only), "
                 "'grid' (Global Tailings Portal, unmatched) or 'grid-enriched' (WAPHA dam "
                 "matched to a GTP disclosure within 5 km). The WAPHA source shapefile "
                 "publishes ONE attribute (Name) — every other column on a 'wapha' row is "
                 "NULL or platform-derived; `country` in particular is platform-derived. "
                 "WAPHA is a literature/registry compilation and inherits a handful of "
                 "non-mining dams from national registers. Values are otherwise verbatim. "
                 "geog (generated geography column) excluded.",
        ),
    ),
    "fires": VectorExport(
        id="fires", label="Active fires",
        table="active_fires",
        geom_col="t.geom", id_col="id", geom_kind="point", cap=10_000,
        fields=("id", "latitude", "longitude", "brightness", "confidence",
                "frp", "instrument", "acq_date", "created_at"),
        prov=Provenance(
            source="NASA FIRMS (VIIRS: Suomi-NPP, NOAA-20, NOAA-21)",
            source_url="https://firms.modaps.eosdis.nasa.gov/",
            note="Near-real-time fire detection (NRT). Rolling window; older detections may be pruned.",
        ),
    ),
    "air-quality": VectorExport(
        id="air-quality", label="Air quality stations",
        table="air_quality_stations",
        geom_col="t.geom", id_col="id", geom_kind="point", cap=10_000,
        fields=("id", "location_id", "name", "city", "country", "locality",
                "timezone", "is_mobile", "is_monitor", "provider", "owner",
                "pm25", "pm10", "pm4", "so2", "no2", "o3", "co", "ch4", "ufp",
                "coverage_pct", "last_updated", "datetime_first", "datetime_last",
                "created_at"),
        prov=Provenance(
            source="OpenAQ v3",
            source_url="https://openaq.org/",
            note="Latest reading per station at time of sync. "
                 "Units: μg/m³ (PM) or ppb (gases) depending on station reporting.",
        ),
    ),
    "landslides": VectorExport(
        id="landslides", label="Landslides",
        table="landslides",
        geom_col="t.geom", id_col="id", geom_kind="point", cap=10_000,
        fields=("id", "event_date", "event_type", "country", "location",
                "fatalities", "trigger", "source", "created_at"),
        prov=Provenance(
            source="NASA COOLR / GSFC",
            source_url="https://gpm.nasa.gov/landslides/",
            note="NASA Global Landslide Catalog. Rainfall-triggered events since 2007. "
                 "geog (generated geography column) excluded.",
        ),
    ),
    "dams": VectorExport(
        id="dams", label="Dams",
        table="dams",
        geom_col="t.geom", id_col="id", geom_kind="point", cap=10_000,
        fields=("id", "dam_name", "river", "country", "height_m", "purpose",
                "year_built", "volume_mcm", "created_at"),
        prov=Provenance(
            source="Global Dam Watch — GOODD v2 (dam locations only)",
            source_url="https://www.globaldamwatch.org/",
            note="Major dam infrastructure. volume_mcm = storage capacity in million cubic metres.",
        ),
    ),
    "water-risk": VectorExport(
        id="water-risk", label="Water risk (Aqueduct)",
        table="water_risk",
        geom_col="t.geom", id_col="id", geom_kind="polygon", cap=5_000,
        fields=("id", "string_id", "pfaf_id", "gid_0", "name_0", "name_1",
                "area_km2", "bws_score", "bws_label", "bwd_score", "drr_score",
                "rfr_score", "w_awr_min_tot_score", "w_awr_min_tot_cat",
                "w_awr_min_tot_label", "created_at"),
        prov=Provenance(
            source="WRI Aqueduct 4.0",
            source_url="https://www.wri.org/aqueduct",
            citation="WRI Aqueduct 4.0 (2023)",
            note="68,494 sub-basin polygons. w_awr_min_tot_cat: -9999=No data, "
                 "0=Low, 1=Low-Medium, 2=Medium-High, 3=High, 4=Extremely High.",
        ),
    ),
}

EXPORT_LAYERS: dict[str, object] = {
    **_VECTORS,
    **_FIELDS,
    "marine-carbon": CompositeExport(
        id="marine-carbon", label="Marine Carbon (raw sources)",
        members=("socat-co2", "glodap-carbon", "isas20-oxygen", "woa23"),
    ),
    "submarine-cables": CompositeExport(
        id="submarine-cables", label="Submarine Cables",
        members=("cables-emodnet", "cables-noaa", "cables-nz",
                 "cables-au", "cables-onc", "cables-ooi"),
    ),
}
