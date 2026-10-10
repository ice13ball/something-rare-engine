# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Curated public OpenAPI schema for the Abyssal Claims API.

Single source of truth for the public API docs (rendered by Scalar at the
frontend /api-docs route). build_openapi() overrides app.openapi() so the
published schema is generated from the live routes but curated: internal
routes excluded, an X-API-Key security scheme applied, a real servers entry,
tag groups, summaries, and a Getting-Started preface. curate_schema() is the
pure transform (unit-tested without importing the app).
"""
from __future__ import annotations

import copy

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

API_VERSION = "1.0.0"
PUBLIC_SERVER_URL = "https://apiv2.something-rare.com"

# Path prefixes hidden from the public schema (admin / auth / sync / internal).
EXCLUDED_PREFIXES: tuple[str, ...] = (
    "/v1/admin",
    "/admin",
    "/org-admin",
    "/v1/feedback",
    "/v1/blog",
    "/v1/seo",
    "/v1/reports/refresh",  # cache-rebuild maintenance endpoint, not public read data
    "/sitemap",
    "/docs",
    "/redoc",
    "/openapi.json",
)

_METHODS = ("get", "post", "put", "delete", "patch")

# First matching prefix wins — order from most specific to least.
_TAG_RULES: list[tuple[str, str]] = [
    ("/v2/spatial/tiles", "Tiles"),
    ("/v2/map/tiles", "Tiles"),
    ("/v2/spatial", "Detail lookups"),   # /by-id enrichment routes (offshore, wod-oxygen, memento)
    ("/v1/vessels", "Vessels & AIS"),
    ("/v1/map/argo", "Ocean fields"),
    ("/v1/currents", "Ocean fields"),
    ("/v1/bgc-model", "Ocean fields"),
    ("/v1/ocean-colour", "Ocean fields"),
    ("/v1/woa", "Ocean fields"),
    ("/v1/oxygen", "Ocean fields"),
    ("/v1/carbon", "Ocean fields"),
    ("/v1/acidification", "Ocean fields"),  # ocean acidification / aragonite-calcite saturation
    ("/v1/co2", "Ocean fields"),
    ("/v1/seabed", "Ocean fields"),      # seabed-substrate raster/hex/point/meta field layer
    ("/v1/cascade", "Ocean fields"),     # CASCADE Arctic sediment carbon raster/point/meta
    ("/v1/vme", "Ocean fields"),         # VME coral suitability meta/hexes/point
    ("/v1/coral-exposure", "Ocean fields"),  # coral acidification exposure meta/hexes/point/summary
    ("/v1/chi", "Ocean fields"),         # NCEAS/Halpern cumulative human impact raster/hexes/point/meta
    ("/v1/bathymetry", "Detail lookups"),  # per-feature confidence/gmrt/lookup enrichment
    ("/v1/live", "Detail lookups"),
    ("/v1/oceansites", "Detail lookups"),  # per-mooring deployments / GDAC historical record
    ("/v1/glodap/cast/", "Detail lookups"),  # one bottle cast by key (before the "/v1/glodap" prefix below)
    ("/v1/glodap", "Sea layers"),            # casts document / cruises / meta of the GLODAPv3 points layer
    ("/v1/argo-oxygen/profile/", "Detail lookups"),  # one BGC-Argo DOXY profile by key (before the prefix below)
    ("/v1/argo-oxygen/tiles", "Tiles"),      # BGC-Argo O2 points map MVT (before the prefix below)
    ("/v1/argo-oxygen", "Sea layers"),       # per-depth points documents / floats / meta of the Argo O2 points layer
    ("/v1/socat/tiles", "Tiles"),            # SOCAT v2026 points map MVT
    ("/v1/socat/obs/", "Detail lookups"),    # one observation by key (before the "/v1/socat" prefix below)
    ("/v1/socat/cell/", "Detail lookups"),   # what one point feature stands for
    ("/v1/socat", "Sea layers"),             # meta of the SOCAT v2026 points layer
    ("/v1/wod/tiles", "Tiles"),              # WOD23 casts map MVT
    ("/v1/wod/cell/", "Detail lookups"),     # which casts one dot stands for (before the "/v1/wod" prefix below)
    ("/v1/wod/cast/", "Detail lookups"),     # one cast by id
    ("/v1/wod", "Sea layers"),               # meta of the WOD23 casts layer
    ("/v1/plankton/tiles", "Tiles"),          # plankton map MVT (stage 2)
    ("/v1/plankton/site/", "Detail lookups"),  # one plankton place (click panel)
    ("/v1/map/hydrophones/by-id/", "Detail lookups"),  # one station by id, retired included (before "/v1/map" below)
    ("/v1/map", "Sea layers"),
    ("/v2/map", "Land layers"),
    ("/v2/export", "Export"),            # area-export download + count endpoints
    ("/v1", "Meta"),
    ("/v2", "Land layers"),
]

TAG_ORDER = [
    "Sea layers", "Land layers", "Ocean fields",
    "Vessels & AIS", "Tiles", "Detail lookups", "Export", "Meta",
]

GETTING_STARTED = """\
# Abyssal Claims API

Programmatic access to the deep-sea and land-mining transparency data behind
[something-rare.com](https://something-rare.com): ISA concessions, biodiversity,
ocean monitoring, vessels, submarine cables, and terrestrial mining impacts.

## Getting a key

Access is granted to **approved organizations**. Keys are issued and managed by
your **organization administrator** through the org portal — there is no public
self-signup. If you need access, ask your org admin to create a key for you.

## Authenticating

Send your key in the **`X-API-Key`** header on every request:

```bash
curl -H "X-API-Key: ak_live_xxx" \\
  https://apiv2.something-rare.com/v1/map/claims
```

## Errors

| Status | Meaning |
|--------|---------|
| `403`  | Missing, invalid, expired, or revoked key |
| `429`  | Rate limit or quota exceeded (per-minute and per-day windows set by your org) |

## Data formats

- Responses are **GeoJSON** (`EPSG:4326` / WGS84) unless a specific endpoint notes otherwise.
- Endpoints ending in `.../tiles/{z}/{x}/{y}` emit **Mapbox Vector Tiles** intended for
  map clients (deck.gl / MapLibre), not for direct human browsing.
- Data freshness varies by layer; see the platform legend for per-source cadence.

## Stability

`v1` and `v2` paths are stable. Breaking changes ship under a new path. This
document is generated from the live API, so it always reflects the deployed routes.
"""

# Curated descriptions + response examples for headline endpoints. Add more
# entries here using the same shape; the rest of the API is documented from
# the live schemas + auto summaries.
_CLAIMS_EXAMPLE = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [0, 0]]]},
            "properties": {
                "isa_id": "BGR-1",
                "contractor": "Example Contractor",
                "resource_type": "Polymetallic Nodules",
                "status": "active",
            },
        }
    ],
}

_EXPORT_EXAMPLE = {
    "type": "FeatureCollection",
    "metadata": {
        "layer": "geotraces",
        "source": "GEOTRACES IDP2025 (BODC)",
        "feature_count": 41,
        "capped": False,
    },
    "features": [],
}

_OCEANSITES_HISTORY_EXAMPLE = {
    # Real values (PAP-2, a closed OceanSITES mooring in the NE Atlantic), trimmed.
    "ref": "TMP236332161",
    "start": "2002-10-06T20:00:00Z",
    "end": "2005-07-08T09:45:00Z",
    "n_catalogue_files": 3,
    "n_files_read": 3,
    "citation": (
        "These data were collected and made freely available by the international "
        "OceanSITES project and the national programs that contribute to it."
    ),
    "citations": [
        "These data were collected and made freely available by the international "
        "OceanSITES project and the national programs that contribute to it."
    ],
    "files": [
        {
            "file": "DATA/PAP/OS_PAP-2_200210_D_CTD.nc",
            "source": "gdac",
            "data_mode": "D",
            "start": "2002-10-06T20:00:00Z",
            "end": "2003-07-08T12:00:00Z",
            "min_depth": 10.0,
            "max_depth": 800.0,
            "url": (
                "https://tds0.ifremer.fr/thredds/dodsC/CORIOLIS-OCEANSITES-GDAC-OBS/"
                "DATA/PAP/OS_PAP-2_200210_D_CTD.nc.html"
            ),
            "url_opendap_html": (
                "https://tds0.ifremer.fr/thredds/dodsC/CORIOLIS-OCEANSITES-GDAC-OBS/"
                "DATA/PAP/OS_PAP-2_200210_D_CTD.nc.html"
            ),
        }
    ],
    "series": [
        {
            "variable": "TEMP",
            "standard_name": "sea_water_temperature",
            "long_name": "Temperature",
            "units": "degree_Celsius",
            "depth_m": 40,
            "depths_available": [10, 25, 40, 60, 80, 150, 400, 600, 800],
            "points": [["2002-10-08T16:00:00Z", 14.415147], ["2002-10-10T12:00:00Z", 16.390738]],
            "n_total_measurements": 6593,
            "stride_max": 44,
            "qc_withheld": 1,
            "range_withheld": 0,
            "missing": 115,
            "duplicates_dropped": 0,
        }
    ],
}

CURATED: dict[str, dict] = {
    "/v1/glodap/casts": {
        "description": (
            "Every GLODAPv3 (2026) bottle cast with at least one WOCE-flag-2 value, as columnar arrays "
            "(`keys`, `lon`, `lat`, `year`) plus, per ocean-carbon variable (`dic`, `talk`, `ph`) and display depth, "
            "the nearest acceptable bottle value inside that depth's window, or null. Units match the ocean-carbon "
            "field (µmol/kg; pH total scale, in-situ). ~11 MB raw, served gzip. "
            "The example holds one cast and two depths. "
            "503 + Retry-After while the layer has not loaded or the database is unavailable. "
            "CC BY 4.0 — cite GLODAPv3."),
        "example": {
            "product": "GLODAPv3 (2026)", "n": 1, "keys": ["49UF20150620_4511_1"],
            "lon": [137.0087], "lat": [9.9897], "year": [2015],
            "values": {"dic": {"0": [1894.4], "4000": [2320.3]},
                       "talk": {"0": [2220.6], "4000": [2412.8]},
                       "ph": {"0": [8.056], "4000": [7.7694]}},
        },
    },
    "/v1/glodap/cast/{cast_key}": {
        "description": (
            "One GLODAPv3 cast by its stable key EXPOCODE_station_cast (where the source gives no cast number, "
            "`cast_no` is null and the key ends in `_nc`): every bottle's depth, pressure and values "
            "with the WOCE flag beside each value (2 acceptable, 0 interpolated/calculated, 9 no data) and the "
            "secondary-QC flag, cruise DOI and ship, plus the GLODAPv2.2016b field value at this spot. "
            "`citations` carries the GLODAPv3 dataset, the ESSD paper and the ship-name (NVS, CC BY 4.0) credits. "
            "The example is abbreviated to three bottles, one variable and one level; its `field` number is illustrative. "
            "404 if the key is unknown; 503 + Retry-After if the database is unavailable."),
        "example": {
            "cast_key": "49UF20150620_4511_1", "expocode": "49UF20150620", "station": "4511", "cast_no": 1,
            "ship_name": "Keifu Maru", "platform_code": "49UF", "lat": 9.9897, "lon": 137.0087,
            "obs_date": "2015-06-30", "obs_time": "2015-06-30T10:51:00+00:00", "time_precision": "minute",
            "year": 2015, "region": 8, "doi": "https://doi.org/10.25921/9y9k-z931",
            "bottom_depth_m": 5081.4, "pos_spread_km": 0.0,
            "depth_m": [0.0, 10.0, 4984.0], "pressure_dbar": [0.0, 10.5, 5071.4], "bottle": [99.0, 21995.0, 21960.0],
            "variables": {"tco2": {"values": [1894.4, 1895.1, 2315.0], "flags": [2, 2, 2], "qc": 1,
                                   "units": "µmol/kg"}},
            "levels": {"dic": {"0": [1894.4, 0.0]}},
            "field": {"dic": {"0": 1890.0}},
            "citation": "Lange, N., Lauvset, S. K., Carter, B. R., et al. (2026). The Global Ocean Data Analysis "
                        "Project version 3 (GLODAPv3) … https://doi.org/10.25921/m6tp-mj50",
            "source_url": "https://doi.org/10.25921/m6tp-mj50", "product": "GLODAPv3 (2026)",
            "field_product": "GLODAPv2.2016b mapped climatology (TCO2 and pH normalised to 2002)",
        },
    },
    "/v1/glodap/cruises": {
        "description": (
            "GLODAPv3 cruises (1,181) as a GeoJSON FeatureCollection: expocode, ship, cruise DOI, date span, "
            "cast count. 503 + Retry-After while the layer has not loaded or the database is unavailable."),
        "example": {"type": "FeatureCollection", "features": [{
            "type": "Feature", "geometry": {"type": "Point", "coordinates": [137.0087, 9.9897]},
            "properties": {"expocode": "49UF20150620", "ship_name": "Keifu Maru", "platform_code": "49UF",
                           "doi": "https://doi.org/10.25921/9y9k-z931", "first_date": "2015-06-30",
                           "last_date": "2015-06-30", "n_casts": 1, "first_cast_key": "49UF20150620_4511_1"}}]},
    },
    "/v1/glodap/meta": {
        "description": (
            "Product, citations, licence, counts, year span, depth windows and the variable mapping used to "
            "colour points, plus `health` (status ok / running / failing / not_loaded, the last failure, the "
            "last load's rejected rows). The example is abbreviated."),
        "example": {
            "product": "GLODAPv3 (2026)", "licence": "CC BY 4.0", "n_casts": 1, "n_casts_drawn": 1,
            "n_samples": 37, "year_min": 2015, "year_max": 2015, "loaded_at": "2026-10-06T12:00:00+00:00",
            "depth_windows": {"0": [0.0, 10.0], "4000": [3750.0, 4250.0]},
            "field_to_bottle": {"dic": "tco2", "talk": "talk", "ph": "phtsinsitutp", "cant": None},
            "health": {"status": "ok", "failure": None, "failed_at": None, "deferred": None,
                       "last_run_at": "2026-10-06T03:00:00+00:00", "last_decision": "unchanged",
                       "last_rejects": {}, "last_rejects_at": "2026-10-06T12:00:00+00:00", "swap_note": None},
        },
    },
    "/v1/socat/obs/{obs_key}": {
        "description": (
            "One SOCAT v2026 underway fCO2 observation by its key EXPOCODE~N (N = 0-based row ordinal within the "
            "cruise): time (UTC), position, fCO2rec, SST, salinity, the fCO2rec algorithm code and WOCE flag, its "
            "track segment (up to 512 observations, as arrays, to draw the highlighted track and a value-vs-time "
            "curve), the cruise (platform, PIs, dataset QC flag A-D, DOIs) and the gridded decadal fCO2 of the "
            "field layer at that spot. `citations` and `acknowledgement` carry the SOCAT credit "
            "(Bakker et al. 2026, https://doi.org/10.25921/8dba-fr90; CC BY 4.0). Longitudes are folded to -180..180. The example is abbreviated to "
            "three segment rows. 404 if the key is unknown; 400 if malformed; 503 + Retry-After if the database "
            "is unavailable or the layer is not built."),
        "example": {
            "obs_key": "76XL20160724~1", "expocode": "76XL20160724", "ordinal": 1,
            "time": "2016-08-26T02:52:00Z", "lon": -159.52907, "lat": 74.72898,
            "fco2_uatm": 368.343, "sst_c": 0.7, "sal_pss78": None, "fco2_src": 1, "fco2_flag": 2,
            "segment": {"ord0": 0, "n_obs": 3, "index": 1,
                        "time": ["2016-08-26T02:50:00Z", "2016-08-26T02:52:00Z", "2016-08-26T02:56:00Z"],
                        "lon": [-159.52788, -159.52907, -159.53086], "lat": [74.72843, 74.72898, 74.73018],
                        "fco2_uatm": [367.794, 368.343, 367.835], "sst_c": [0.7, 0.7, 0.7],
                        "sal_pss78": [None, None, None], "fco2_flag": [2, 2, 2]},
            "field": {"fco2_decadal_uatm": 362.1},
            "cruise": {"expocode": "76XL20160724", "platform_name": "Xue Long", "qc_flag": "D",
                       "source_doi": "https://doi.org/10.25921/76ms-xp32", "n_obs": 3},
            "source_url": "https://doi.org/10.25921/8dba-fr90", "licence": "CC BY 4.0",
        },
    },
    "/v1/socat/cell/{z}/{x}/{y}/{q}": {
        "description": (
            "What one SOCAT v2026 map dot stands for. From zoom 9 a dot is all observations of one UTC `year` "
            "inside one cell `q` (0-65535, counted from the tile's north-west corner, 256 x 256 per tile) of tile "
            "z/x/y. Returns exact totals (`n_obs`, `n_cruises`, mean fCO2 / SST / salinity), the cell's bounds, "
            "the field layer's decadal fCO2 at the cell centre, the cruises (capped at 100 by observation count) "
            "and the observations ordered by time (capped at 1,000; `*_truncated` says when a cap applied), each "
            "with an `obs_key` for /v1/socat/obs. Immutable when `v` is the live tile version. The example is "
            "abbreviated. 400 if the address is malformed (z must be 9-12, q 0-65535, `year` four digits); 404 "
            "if the cell holds no drawable observation in that year; 503 + Retry-After if the database is "
            "unavailable, the layer is not built, or the lookup timed out. CC BY 4.0 - cite Bakker et al. 2026, "
            "https://doi.org/10.25921/8dba-fr90 (SOCAT v2026) and Bakker et al. 2016, "
            "https://doi.org/10.5194/essd-8-383-2016."),
        "example": {
            "z": 9, "x": 262, "y": 171, "q": 7715, "year": 2002, "version": "20261009120000-010941",
            "cell": {"west": 4.3149, "south": 51.1259, "east": 4.3176, "north": 51.1277},
            "n_obs": 2, "n_cruises": 1, "mean": {"fco2_uatm": 7300.5, "sst_c": 11.2, "sal_pss78": 30.1},
            "first_time": "2002-11-04T08:00:00Z", "last_time": "2002-11-04T08:02:00Z",
            "field": {"fco2_decadal_uatm": 360.4},
            "cruises": [{"expocode": "11BE20021104", "platform_name": "Belgica", "qc_flag": "D", "n_obs": 2,
                         "obs_key": "11BE20021104~10", "first_time": "2002-11-04T08:00:00Z",
                         "last_time": "2002-11-04T08:02:00Z"}],
            "cruises_truncated": False,
            "observations": [{"obs_key": "11BE20021104~10", "time": "2002-11-04T08:00:00Z", "lon": 4.3151,
                              "lat": 51.1276, "fco2_uatm": 7290.1, "sst_c": 11.2, "sal_pss78": 30.1}],
            "observations_truncated": False,
            "source_url": "https://doi.org/10.25921/8dba-fr90", "licence": "CC BY 4.0",
        },
    },
    "/v1/socat/meta": {
        "description": (
            "SOCAT v2026 points layer: product, release, licence (CC BY 4.0), citations and the SOCAT "
            "acknowledgement sentence, observation / cruise / segment counts, year span, tile version and load "
            "time, plus `health` (status ok / failing / not_loaded, the last failure, the last load's rejected "
            "rows). CC BY 4.0 - cite Bakker et al. 2026, https://doi.org/10.25921/8dba-fr90 (SOCAT v2026) and "
            "Bakker et al. 2016, https://doi.org/10.5194/essd-8-383-2016. The example is abbreviated."),
        "example": {
            "product": "SOCAT v2026 (Surface Ocean CO2 Atlas)", "release": "v2026", "licence": "CC BY 4.0",
            "source_url": "https://doi.org/10.25921/8dba-fr90", "n_observations": 44018204, "n_rejected": 0,
            "n_cruises": 8310, "year_min": 1957, "year_max": 2026, "loaded_at": "2026-10-09T12:00:00+00:00",
            "tile_version": "20261009120000-010941", "point_min_zoom": 9,
            "health": {"status": "ok", "failure": None, "failed_at": None, "last_run_at": "2026-10-09T12:00:00+00:00",
                       "last_decision": "swapped", "last_rejects": {}, "last_rejects_at": "2026-10-09T12:00:00+00:00",
                       "swap_note": None},
        },
    },
    "/v1/wod/cell/{z}/{x}/{y}/{q}": {
        "description": (
            "Which WOD23 casts one map dot stands for. Below zoom 6 a dot is all casts of the selected years in one "
            "cell of a coarse grid, from zoom 6 in one cell `q` of the tile's 256 x 256 grid (both counted from the "
            "tile's north-west corner; `q` runs 0 to cells-per-tile minus 1). Returns the exact number of casts "
            "(`n_casts`, matching the dot's `k`), their year span, the cell's bounds and the casts newest first "
            "(capped at 1,000; `truncated` says when the cap applied), each with the `cast_id` that opens "
            "/v1/wod/cast. `y0`/`y1` (four-digit years, both or neither) must be the ones the tile was drawn "
            "with. Immutable when `v` is the live tile version. The example is abbreviated and sits at zoom 0 over "
            "the fixture cast 22708857. 400 if the address or the years are malformed; 404 if the address is "
            "outside the pyramid or the cell holds no drawable cast; 503 + Retry-After if the database is "
            "unavailable, the layer is not built, or the lookup timed out. Public use without restriction (NOAA "
            "NCEI) - cite Mishonov et al. (2024), https://doi.org/10.25923/z885-h264."),
        "example": {
            "z": 0, "x": 0, "y": 0, "q": 2307, "version": "20261009120000-010941", "years": None,
            "cell": {"west": -84.375, "south": -11.178402, "east": -78.75, "north": -5.615986},
            "n_casts": 1, "year_min": 2024, "year_max": 2024,
            "casts": [{"cast_id": 22708857, "instrument": "pfl", "dataset": "profiling float",
                       "date": "2024-07-15", "time_precision": "second", "year": 2024, "cruise": "FR017070",
                       "wmo_id": "6902961", "platform": None,
                       "vehicle": "PROVOR (free-drifting hydrographic profiler, IFREMER/MARTEC, France)",
                       "lat": -10.776062, "lon": -82.912605}],
            "truncated": False,
            "source_url": "https://www.ncei.noaa.gov/products/world-ocean-database",
            "licence": "Public use without restriction (NOAA NCEI)",
        },
    },
    "/v1/wod/cast/{cast_id}": {
        "description": (
            "One WOD23 cast (OSD bottle/net, CTD or profiling float) by its WOD unique cast id: instrument, dataset, "
            "cruise, platform, vehicle, WMO id, institute, project, country, date and (only when the source recorded "
            "one, `time_precision` = second) UTC time, position, the NCEI accession of the originator's data and the "
            "source file, `levels` (per variable code t, s, o, p, i, n: [depth m, value, WOD flag] for every "
            "stored non-missing level, at most 100 per variable; flag 0 = accepted), `picks` (the accepted value "
            "nearest each of the 8 display depths inside its window, null where none; nstar = nitrate - 16 "
            "phosphate), `field` (the World Ocean Atlas 2023 annual climatology of `var` at the cast's position at "
            "the same 8 depths, null where the grid has no value) and `flag_meanings`. Units are those of the "
            "source: degree_C, practical salinity (WOD declares no unit), umol/kg for oxygen and nutrients. `var` "
            "(default temperature) and `depth` (one of the display depths) only select what the response marks as "
            "the field of interest. The example is abbreviated to three levels of temperature; its `field` numbers are illustrative. "
            "404 if the cast is unknown; 400 if the id, `var` or `depth` is malformed; 503 + Retry-After if the "
            "database is unavailable or the layer is not built. Public use without restriction (NOAA NCEI) - cite "
            "Mishonov et al. (2024), https://doi.org/10.25923/z885-h264."),
        "example": {
            "cast_id": 22708857, "instrument": "pfl", "dataset": "profiling float", "cruise": "FR017070",
            "orig_cruise": None, "platform": None,
            "vehicle": "PROVOR (free-drifting hydrographic profiler, IFREMER/MARTEC, France)",
            "wmo_id": "6902961", "institute": "MERCATOR-CORIOLIS MISSION GROUP (GMMC)", "project": None,
            "country": "FRANCE", "date": "2024-07-15", "time": "14:12:11", "time_precision": "second",
            "lat": -10.776062, "lon": -82.912605, "access_no": 42682,
            "accession_url": "https://www.ncei.noaa.gov/archive/accession/42682",
            "levels": {"t": [[0.0, 19.418, 0], [50.00835, 19.42, 0], [99.80574, 14.772, 0]]},
            "picks": {"temperature": [19.418, 19.42, 14.772, 13.096, 8.337, 4.567, 3.102, 2.346],
                      "oxygen": [209.38072, 186.56409, 3.581871, 1.856771, 3.71315, 49.953197, 77.962616, 97.57389],
                      "nitrate": [None] * 8, "nstar": [None] * 8},
            "field": {"variable": "oxygen", "selected_depth": 0,
                      "values": {"0": 241.2, "50": 238.9, "100": 160.4, "200": 40.1, "500": 12.3, "1000": 38.7,
                                 "1500": 80.2, "2000": 114.6}},
            "flag_meanings": {"Temperature": {"0": "accepted"}},
            "source_url": "https://www.ncei.noaa.gov/products/world-ocean-database",
            "licence": "Public use without restriction (NOAA NCEI)",
        },
    },
    "/v1/wod/meta": {
        "description": (
            "WOD23 casts layer: product, licence (public use without restriction, NOAA NCEI), citation, the "
            "variables and display depths with their windows and integer scales, the first zoom drawn from "
            "individual casts, tile version and load time, the cast arithmetic per instrument (casts in the source, "
            "stored, drawn and the reject counters that account for the difference) and `health` (status ok / "
            "failing / not_loaded, the last failure, the files that failed, are blocked or have gone missing). "
            "`health` is read live; the rest changes only with a load. The example is abbreviated."),
        "example": {
            "product": "World Ocean Database 2023 (WOD23) — OSD, CTD, PFL", "release": "WOD23",
            "licence": "Public use without restriction (NOAA NCEI)",
            "n_stored": 21, "n_drawn": 21, "year_min": 1970, "year_max": 2024,
            "loaded_at": "2026-10-09T12:00:00+00:00", "tile_version": "20261009120000-010941", "point_min_zoom": 6,
            "variables": ["temperature", "salinity", "oxygen", "phosphate", "silicate", "nitrate", "nstar"],
            "depths": [0, 50, 100, 200, 500, 1000, 1500, 2000],
            "windows": [[0.0, 10.0], [40.0, 60.0], [90.0, 110.0], [175.0, 225.0], [450.0, 550.0],
                        [950.0, 1050.0], [1425.0, 1575.0], [1900.0, 2100.0]],
            "scales": {"temperature": 100, "salinity": 100, "oxygen": 10, "phosphate": 100, "silicate": 10,
                       "nitrate": 10, "nstar": 10},
            "lod_counts": {"0": 21, "1": 21, "2": 21},
            "arithmetic": {"pfl": {"files": 1, "source": 4, "stored": 4, "drawn": 4, "rejects": {}}},
            "health": {"status": "ok", "failure": None, "failed_at": None, "last_run_at": "2026-10-09T12:00:00+00:00",
                       "last_decision": "complete", "last_rejects": {}, "last_rejects_at": "2026-10-09T12:00:00+00:00",
                       "failed_files": 0, "blocked_files": 0, "missing_files": 0, "files": []},
        },
    },
    "/v1/argo-oxygen/points/{depth}": {
        "description": (
            "Every BGC-Argo profile drawn by the argo-oxygen-points layer at one display depth of the oxygen-deox "
            "field (0, 50, 100, 200, 500, 1000, 1500, 2000 m), as columnar arrays: `floats` holds "
            "`<dac>_<wmo>` prefixes, `fi` indexes them, `cycle` and the row indices in `descending` complete "
            "the profile key `<dac>_<wmo>_<cycle:03d>[D]`. Only profiles in delayed or adjusted data mode with a "
            "good level (DOXY_ADJUSTED, Argo QC 1 or 2) are listed; `value` is the one nearest to the depth inside "
            "`window` (metres, from pressure by UNESCO 1983), rounded to 1 µmol/kg, or null when the profile has "
            "no good level in that window. ~12 MB raw per depth, served gzip. The example holds two of the "
            "profiles. 404 for another depth; 503 + Retry-After while not loaded or the database is unavailable. "
            "CC BY 4.0 — acknowledge Argo, doi:10.17882/42182."),
        "example": {"product": "BGC-Argo DOXY, Argo GDAC synthetic profiles (current)", "depth": 500,
                    "window": [450.0, 550.0], "units": "µmol/kg", "n": 2, "floats": ["aoml_1900722"],
                    "fi": [0, 0], "cycle": [1, 2], "descending": [], "lon": [73.389, 73.528],
                    "lat": [-40.316, -40.39], "year": [2006, 2006], "value": [218, 220]},
    },
    "/v1/argo-oxygen/profile/{profile_key}": {
        "description": (
            "One BGC-Argo DOXY profile by its stable key `<dac>_<wmo>_<cycle:03d>[D]`: thinned levels (one per "
            "depth bin, at most 150) with pressure, depth, adjusted and raw DOXY and the Argo QC flag beside each "
            "value, the data mode, the value picked at every display depth, the ISAS20 2014–2018 field value at "
            "this spot (recent only; no change is computed for one profile), the GDAC file and float links, and "
            "the Argo acknowledgement. Profiles that are stored but not drawn (real-time mode, no good level, bad "
            "position or time) are served too, with `drawable` false. 404 if the key is malformed or unknown; "
            "503 + Retry-After if the database is unavailable. The example is abbreviated to three levels "
            "(first, 500 m, last of 70); its `field_recent` number is illustrative."),
        "example": {"profile_key": "aoml_1900722_001", "argo_profile_id": "1900722_001", "dac": "aoml",
                    "platform_number": "1900722", "cycle_number": 1, "direction": "A", "doxy_mode": "D",
                    "lat": -40.316, "lon": 73.389, "position_qc": 1, "profile_time": "2006-10-22T02:16:24+00:00",
                    "drawable": True, "units": "µmol/kg", "n_levels_source": 71, "n_levels": 70, "n_good": 70,
                    "levels": {"pres_dbar": [6.0, 500.2, 2000.0], "depth_m": [5.953771, 495.7539, 1975.176],
                               "doxy_adj": [259.6237, 218.1551, 179.9346], "doxy_adj_qc": [1, 1, 1],
                               "doxy_raw": [230.894, 189.939, 151.541], "doxy_raw_qc": [3, 3, 3]},
                    "at_depth": {"0": [259.6237, 5.953771], "500": [218.1551, 495.7539]},
                    "field_recent": {"500": 205.0},
                    "source_url": "https://data-argo.ifremer.fr/dac/aoml/1900722/profiles/SD1900722_001.nc",
                    "float_url": "https://fleetmonitoring.euro-argo.eu/float/1900722"},
    },
    "/v1/argo-oxygen/floats": {
        "description": ("BGC-Argo floats with at least one drawn DOXY profile, as a GeoJSON FeatureCollection at "
                        "the latest profile's position: WMO, DAC, latest profile key and date, profile count. "
                        "503 + Retry-After while not loaded or the database is unavailable."),
        "example": {"type": "FeatureCollection", "features": [{"type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [73.528, -40.39]},
                    "properties": {"wmo": "1900722", "dac": "aoml", "last_profile_key": "aoml_1900722_002",
                                   "last_date": "2006-11-01", "n_profiles": 2}}]},
    },
    "/v1/argo-oxygen/meta": {
        "description": ("Product, licence, citations (the Argo acknowledgement and the GDAC dataset), GDAC state date, "
                        "year span, depth windows, QC notes, the count arithmetic (indexed → stored → not drawn by "
                        "reason → drawn), the rules version, and `health` (status ok / running / failing / "
                        "not_loaded, the last failure, the last run's rejected rows, deletions held back), and for the "
                        "map tiles `tile_version` (the `v` of /v1/argo-oxygen/tiles; null while nothing is built), "
                        "`tile_built_at`, `point_min_zoom`, `tile_max_zoom` and `years` (drawable profiles per year "
                        "in the tiles). The example is abbreviated."),
        "example": {"product": "BGC-Argo DOXY, Argo GDAC synthetic profiles (current)", "licence": "CC BY 4.0",
                    "tile_version": "20261010174042-d41ce0", "tile_built_at": "2026-10-10T17:40:42+00:00",
                    "point_min_zoom": 5, "tile_max_zoom": 8, "years": {"2006": 2, "2007": 6},
                    "arithmetic": {"index_doxy": 14, "rejected": {"no_doxy_values": 1}, "failed_floats": 0,
                                   "no_usable_doxy": 1, "stored": 13, "not_yet_stored": 0,
                                   "not_drawn": {"realtime_only": 2, "no_good_adjusted": 2,
                                                 "bad_position": 1, "bad_time": 0}, "drawn": 8},
                    "rules_version": {"code": 1, "last_complete_run": 1, "profiles_on_other_version": 0},
                    "health": {"status": "ok", "failure": None, "deletions_held": None}},
    },
    "/v1/oceansites/{ref}/history": {
        "description": (
            "Historical record of one OceanSITES mooring, read from the files linked to it: "
            "the OceanSITES GDAC (Ifremer) for most moorings, the NSF Arctic Data Center's "
            "Davis Strait dataset (CC0, doi:10.18739/A2416T169) for the `DS_*` moorings. "
            "Every entry of `files` says which archive it came from (`source`: `gdac` or "
            "`adc_davis`) and carries a `url` (the OPeNDAP page for a GDAC file, the DOI for an "
            "ADC file; `url_opendap_html` is null for an ADC file). `ref` is the station ref the map serves. "
            "Each series is a set of **every k-th real measurement** (`stride_max` says how "
            "sparse), merged across the mooring's files by CF standard name, whole-metre "
            "depth and declared units — never averages, and units are never converted "
            "(two units for one quantity stay two series). Values the file flags bad "
            "(QC 3, 4 or 9) are withheld and counted in `qc_withheld`; fill values are "
            "dropped and counted in `missing`; the two counts are separate. A value that is neither "
            "missing nor flagged but lies outside the physical range of its quantity "
            "(temperature -2.5 to 40 degC and salinity 2 to 41, the Argo global range test; "
            "currents beyond 5 m/s) is withheld and counted in `range_withheld`, a third, "
            "separate count; it applies only where the declared unit is a known one, and the "
            "stored data are not altered. Two samples "
            "with the same timestamp are one instant: the file with the better data mode "
            "(D, M, P, R) wins, then the later GDAC update, and the others are counted in "
            "`duplicates_dropped`. Thinning always keeps the first and the last real point. "
            "By default each quantity (standard name and units) returns only its shallowest, "
            "deepest and median-depth series at up to 200 points; `depths_available` lists "
            "all of its depths so a client can say \"3 of 14 depths shown\". "
            "`all_depths=true` returns every depth at up to 600 points. A file that declares no "
            "depth gives a series with `depth_m: null`; it is listed only with `all_depths=true` "
            "unless the quantity has no numeric depth at all. `n_total_measurements` counts the "
            "measurements in the source files once per instant (a measurement present in two "
            "overlapping files is not counted twice; with a stride above 1 an overlap is only "
            "seen where sampled instants coincide, so it is then an upper bound). Variables "
            "stored packed (`scale_factor` / `add_offset`) are left out rather than served "
            "unscaled. "
            "`n_catalogue_files` counts every file linked to the mooring, from either archive; "
            "`n_files_read` and `files` are the files stored series were read from. `citations` "
            "starts with the OceanSITES data-policy citation whenever a GDAC file contributes "
            "(and when nothing does), is followed by the Arctic Data Center dataset citation "
            "whenever an ADC file contributes, then by the files' own; a mooring whose record "
            "is only from the Arctic Data Center is not credited to OceanSITES. "
            "404 = no such station; 200 with empty `files` and `series` = a known mooring "
            "with no stored history."
        ),
        "example": _OCEANSITES_HISTORY_EXAMPLE,
    },
    "/v1/map/claims": {
        "description": (
            "ISA exploration contract areas as a GeoJSON FeatureCollection. "
            "Each feature carries the contractor, resource type, sponsoring "
            "state, and status."
        ),
        "example": _CLAIMS_EXAMPLE,
    },
    "/v2/export/{layer}": {
        "description": (
            "Download raw upstream records inside an area of interest "
            "(bounding box, polygon, or hex-cell selection) as GeoJSON or CSV. "
            "Each export carries provenance metadata so values can be verified "
            "against the upstream source. Values are verbatim upstream values — "
            "the platform does not alter or derive them. "
            "Requires `X-API-Key`. Per-layer hard caps apply (see the `count` "
            "endpoint to preview the record count before downloading). "
            "The `marine-carbon` composite layer returns a ZIP archive containing "
            "one file per constituent source (GLODAP, SOCAT, ISAS, WOA)."
        ),
        "example": _EXPORT_EXAMPLE,
    },
    "/v2/export/bundle": {
        "description": (
            "Download a ZIP archive containing one file per selected layer "
            "(`format=geojson` or `format=csv`, default `geojson`). "
            "Pass a comma-separated `layers=` list (e.g. `layers=geotraces,memento`). "
            "Composite layers expand to sub-folders — `marine-carbon` produces four "
            "files (GLODAP, SOCAT, ISAS, WOA); `submarine-cables` produces one file "
            "per cable sub-source (EMODnet, NOAA, NZ LINZ, AU ACMA, ONC, OOI). "
            "A `MANIFEST.txt` at the archive root lists every included file with its "
            "layer id, upstream source name, and record count. "
            "Requires `X-API-Key`. Your per-key quota applies across all constituent "
            "layer queries."
        ),
        "example": {"note": "Returns application/zip — not JSON. Save the response body as a .zip file."},
    },
}


def _tag_for(path: str) -> str:
    for prefix, tag in _TAG_RULES:
        if path.startswith(prefix):
            return tag
    return "Meta"


def _fallback_summary(path: str, method: str) -> str:
    segs = [s for s in path.split("/") if s and not s.startswith("{")]
    name = segs[-1].replace("-", " ").replace("_", " ") if segs else "endpoint"
    verb = {"get": "Get", "post": "Create", "put": "Update",
            "delete": "Delete", "patch": "Update"}.get(method, method.title())
    return f"{verb} {name}"


def curate_schema(base: dict) -> dict:
    """Pure transform: raw OpenAPI dict -> curated public schema."""
    schema = copy.deepcopy(base)

    info = schema.setdefault("info", {})
    info["title"] = "Abyssal Claims API"
    info["version"] = API_VERSION
    info["description"] = GETTING_STARTED

    schema["paths"] = {
        p: ops
        for p, ops in schema.get("paths", {}).items()
        if not any(p.startswith(pre) for pre in EXCLUDED_PREFIXES)
    }

    schema["servers"] = [{"url": PUBLIC_SERVER_URL, "description": "Production"}]

    comps = schema.setdefault("components", {})
    comps.setdefault("securitySchemes", {})["ApiKeyAuth"] = {
        "type": "apiKey", "in": "header", "name": "X-API-Key",
    }
    schema["security"] = [{"ApiKeyAuth": []}]

    for p, ops in schema["paths"].items():
        tag = _tag_for(p)
        for method, op in ops.items():
            if method not in _METHODS:
                continue
            op["tags"] = [tag]
            if not op.get("summary"):
                op["summary"] = _fallback_summary(p, method)
        curated = CURATED.get(p)
        if curated and "get" in ops:
            get_op = ops["get"]
            get_op["description"] = curated["description"]
            resp_200 = get_op.setdefault("responses", {}).setdefault("200", {})
            resp_200.setdefault("description", "Successful Response")
            content = resp_200.setdefault("content", {})
            content.setdefault("application/json", {})["example"] = curated["example"]

    schema["tags"] = [{"name": t} for t in TAG_ORDER]
    return schema


def build_openapi(app: FastAPI) -> dict:
    """Cached app.openapi() replacement: live routes -> curated schema."""
    if getattr(app, "openapi_schema", None):
        return app.openapi_schema
    base = get_openapi(title=app.title, version=API_VERSION, routes=app.routes)
    schema = curate_schema(base)
    app.openapi_schema = schema
    return schema
