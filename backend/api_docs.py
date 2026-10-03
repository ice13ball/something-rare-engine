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
