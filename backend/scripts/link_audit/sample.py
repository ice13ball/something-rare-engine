# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Build per-feature URLs from sampled features.

Stored URLs are unbounded — seaflea_seeps alone holds 10,386 source_url values —
so they are grouped by host and sampled. The real failure mode is a whole host
retiring, not one row's typo, and the report prints the true group size so a
green group of 6,126 rows is never mistaken for a green group of 3.
"""
from __future__ import annotations

import re
from urllib.parse import quote, urlparse

from .models import DeepLinkTemplate, DetailTemplate, LinkRow
from .normalize import classify_kind, normalize_url

_PLACEHOLDER = re.compile(r"\$\{[^}]*\}")

# Rendered by DetailPanel as links to information about the object.
STORED_URL_PROPS = (
    "source_url", "portal_url", "worms_url", "platform_url",
    "license_url", "help_url",
    "url_http", "url_opendap", "url_wms", "url_landing",
)
# Deliberately excluded: image_url (imagery, not information).


def build_deep_link(tpl: DeepLinkTemplate, props: dict) -> str | None:
    """Substitute the first present property into the template, or return None."""
    for name in tpl.props:
        if name in props and props[name] not in (None, ""):
            value = quote(str(props[name]), safe="")
            return _PLACEHOLDER.sub(value, tpl.template)
    return None


def group_stored_urls(
    features: list[dict], layer_id: str, path: str, cap: int = 3
) -> tuple[list[LinkRow], dict[str, int]]:
    """Group stored per-row URLs by host; sample up to `cap` per host."""
    sampled: dict[str, list[LinkRow]] = {}
    sizes: dict[str, int] = {}

    for feat in features:
        props = feat.get("properties") or {}
        for prop in STORED_URL_PROPS:
            raw = props.get(prop)
            if not isinstance(raw, str) or not raw.strip():
                continue
            norm = normalize_url(raw)
            host = urlparse(norm).netloc
            if not host:
                continue
            sizes[host] = sizes.get(host, 0) + 1
            bucket = sampled.setdefault(host, [])
            if len(bucket) < cap:
                bucket.append(LinkRow(
                    layer_id=layer_id, surface="stored", url_raw=raw,
                    url_normalized=norm, kind=classify_kind(norm),
                    file=path, line=0,
                ))

    return [row for bucket in sampled.values() for row in bucket], sizes


import httpx

APIV2 = "https://apiv2.something-rare.com"

# Sampling endpoint per deep-link key. Every key returned by
# extract_deep_link_templates must appear here or its links can never be
# sampled — a test enforces that, so adding a 13th builder fails loudly.
#
# Verified against the live route decorators (2026-07-24 audit):
#   - "obis-occurrence": biodiversity_hotspots is served at
#     /v1/map/biodiversity/hotspots (main.py ~10040), NOT
#     /v1/map/biodiversity-hotspots as originally drafted.
#   - "sio-bic": sio_bic_records has NO public GeoJSON/list endpoint anywhere
#     in main.py or land_layers.py — it is read only inside the monitoring-
#     density-grid SQL (land_layers.py ~461/2285/2379), never surfaced as its
#     own feature collection. Left as "" (unresolved) rather than reusing the
#     biodiversity/hotspots response, whose properties never carry sio-bic's
#     own id fields — that would silently sample the wrong schema.
#   - "onc-location": ONC observatory locations are served at /v1/map/onc
#     (main.py ~10803, `get_onc()`, returns `location_code` per feature), NOT
#     /v1/map/onc-stations as originally drafted (no such route exists).
#   - "tailings": served at /v2/map/tailings (land_layers.py ~1193,
#     `get_tailings()`), NOT /v2/map/tailings-dams as originally drafted (no
#     such route exists).
#   - "usgs-earthquake": there is no generic GeoJSON/list endpoint for
#     usgs_earthquakes. The only route touching that table,
#     /v1/onc/earthquakes-near/{location_code} (main.py ~11119), requires a
#     path parameter, returns a bare JSON array (not `{"features": [...]}`),
#     and its objects are not GeoJSON Features with a `properties` dict — it
#     is structurally incompatible with fetch_layer_features. Left as ""
#     (unresolved) rather than inventing a shape that doesn't exist.
# Query params some deep-link endpoints need before they return anything.
# /v1/map/biodiversity/hotspots defaults to zoom=2 and silently returns an EMPTY
# feature list at that zoom — so a correct endpoint path still yielded no sample
# and the layer reported "endpoint returned no features". Params live here rather
# than being baked into the URL so the endpoint string stays comparable to the
# route decorator it was verified against.
LAYER_ENDPOINT_PARAMS: dict[str, dict] = {
    "obis-occurrence": {"zoom": 5},
}

LAYER_ENDPOINTS: dict[str, str] = {
    "obis-occurrence":    f"{APIV2}/v1/map/biodiversity/hotspots",
    "sio-bic":            "",
    "marineregions-eez":  f"{APIV2}/v1/map/eez",
    "unesco-mab":         f"{APIV2}/v1/map/protected-marine-sites",
    "argo-float":         f"{APIV2}/v1/map/argo",
    "onc-location":       f"{APIV2}/v1/map/onc",
    "onc-instrument":     f"{APIV2}/v1/map/onc-instruments",
    "tailings":           f"{APIV2}/v2/map/tailings",
    "openaq":             f"{APIV2}/v2/map/air-quality",
    "usgs-earthquake":    "",
}

# Layers that carry STORED_URL_PROPS on their own rows, verified by a real
# fetch (2026-07-24 audit). Distinct from LAYER_ENDPOINTS above:
# these are visited purely for their per-row stored URLs (B2), independent of
# whether they also have a perFeature deep-link template. Some entries are
# genuinely new endpoint discoveries; where one overlaps a LAYER_ENDPOINTS key
# (biodiversity/hotspots == "obis-occurrence"), a DIFFERENT layer_id is used
# here so the two group_sizes entries never collide/overwrite each other.
#
#   - "methane-seeps" (/v1/map/methane-seeps, table seaflea_seeps): every one
#     of 10,385 rows carries `source_url` = the single literal
#     https://www.nature.com/articles/ngeo2232 (Phrampus et al. 2020 citation,
#     not a per-row variable link) — confirmed via a real fetch.
#   - "sios" (/v1/map/sios, table sios_datasets): rows carry `platform_url`
#     (e.g. https://hornsund.igf.edu.pl/...) and `license_url`
#     (https://spdx.org/licenses/CC-BY-SA-4.0) on every one of 25 rows, plus
#     `url_opendap` on some rows (per-dataset OPeNDAP endpoint on
#     hyrax.igf.edu.pl). `url_http`/`url_wms`/`url_landing` are also stored
#     columns but happened to be empty on every sampled row.
#   - "hydrophone-stations" (/v1/map/hydrophones, table acoustic_stations):
#     `portal_url` is genuinely per-station and highly diverse — imos-data
#     S3 buckets, doi.org, ds.iris.edu, boem.gov, jasco.com, km3net.org,
#     ooinet.oceanobservatories.org, ncei.noaa.gov, navfac.navy.mil, and more
#     across the 640 rows. THE WRONG PATH ("hydrophone-stations") was tried
#     first and returned nothing — the real route is `/v1/map/hydrophones`
#     (main.py, `get_hydrophones`), not a slug match on the toggle id.
#   - "biodiversity-hotspots" (/v1/map/biodiversity/hotspots, joined
#     worms_taxa): `worms_url` (e.g. marinespecies.org/aphia.php?...) is
#     present on every returned row once the endpoint actually returns data.
#     The endpoint silently returns `{"features": []}` at its default
#     `zoom=2` (see main.py `get_biodiversity_hotspots`: `if zoom < 3: return
#     [] `) — it needs `zoom=5` (or any value >= 3) to yield features at all,
#     which is why `fetch_layer_features` below gained a `params` argument.
#
# Verified NOT to carry any STORED_URL_PROPS value (checked via real fetch,
# so absence is stated, not assumed): /v2/map/deepdata-stations,
# /v1/map/cascade/stations, /v1/map/chess, /v2/map/arctic-rivers,
# /v1/map/oceansites, /v1/map/onc, /v1/map/eez,
# /v1/map/protected-marine-sites, /v1/map/vents, /v1/map/seamounts,
# /v2/map/permafrost-thaw, /v1/map/cables, /v1/map/argo,
# /v2/map/mining-footprints, /v2/map/tailings,
# /v2/map/fires, /v2/map/air-quality, /v2/map/landslides, /v2/map/dams,
# /v1/map/noise/stations.
#
# Deliberately excluded despite a real `portal_url` column: `offshore_activities`
# (table backing the offshore-activities-mvt layer) does carry a per-row
# `portal_url`, but the layer has NO GeoJSON list endpoint — only MVT tiles
# (`/v2/spatial/tiles/offshore-activities/...`, not JSON) and two single-row
# lookups (`/at/offshore-activities?lat=&lon=`, `/offshore-activities/by-id/
# {id}`), neither of which returns a `{"features": [...]}` collection.
# Structurally incompatible with `fetch_layer_features`, same class of gap as
# the pre-existing "usgs-earthquake" / "sio-bic" entries above — left
# unresolved rather than faking a shape that doesn't exist.
#
# Also excluded: ONC `help_url` (main.py ~4055, nested inside a per-station
# `data_products[]` array returned only by the single-location detail route
# `/v1/live/onc/{location_code}`, not any list endpoint) — same structural
# mismatch.
STORED_URL_LAYERS: dict[str, tuple[str, dict | None]] = {
    "methane-seeps":        (f"{APIV2}/v1/map/methane-seeps", None),
    "sios":                 (f"{APIV2}/v1/map/sios", None),
    "hydrophone-stations":  (f"{APIV2}/v1/map/hydrophones", None),
    "biodiversity-hotspots": (f"{APIV2}/v1/map/biodiversity/hotspots", {"zoom": 5}),
}


# ── DetailPanel.tsx templates (plane B) ──────────────────────────────────────
# Keyed by the template's static prefix, mapping to the endpoint + feature
# property that can supply a REAL value for its placeholder.
#
# Every entry below was verified against a live response on 2026-07-25 — both
# halves of it: the JSX local variable was traced to the property it reads
# (`const locId = p.location_id`, DetailPanel.tsx:3138) AND that property was
# confirmed present in the endpoint's actual feature payload. Guessing either
# half produces a confidently wrong deep link, the same failure the perFeature
# body-bounding fix exists to prevent.
#
#   prefix -> (layer_id, endpoint, params, feature_property)
#
# Deliberately unmapped, and checked at `prefix` only:
#   - the bbox/area search builders (mapper.obis.org, seamap.env.duke.edu,
#     pangaea.de, ncei global-marine, argovis) take four coordinate placeholders,
#     not an id — there is no single feature property to substitute.
#   - `https://doi.org/${doi}` and `${id}` resolve a DOI carried by many
#     different layers; no one endpoint owns them.
#   - the google.com / en.wikipedia.org / firms.modaps builders are generic
#     web-search convenience links, not source citations — their prefix is the
#     only meaningful thing to check.
DETAIL_TEMPLATE_LAYERS: dict[str, tuple[str, str, dict | None, str]] = {
    "https://obis.org/occurrence/": (
        "detail-obis-occurrence", f"{APIV2}/v1/map/biodiversity/hotspots",
        {"zoom": 5}, "obis_id"),
    "https://data.oceannetworks.ca/DataSearch?locationCode=": (
        "detail-onc-location", f"{APIV2}/v1/map/onc", None, "location_code"),
    "https://datasets.obis.org/hosted/isa/": (
        "detail-deepdata-archive", f"{APIV2}/v2/map/deepdata-stations",
        None, "archive_slug"),
    "https://explore.openaq.org/locations/": (
        "detail-openaq", f"{APIV2}/v2/map/air-quality", None, "location_id"),
}


def build_detail_link(tpl: DetailTemplate, props: dict) -> str | None:
    """Substitute a real feature property into a DetailPanel template.

    Returns None when the template is unmapped or the property is absent —
    the caller then falls back to the static prefix rather than inventing a URL.
    """
    entry = DETAIL_TEMPLATE_LAYERS.get(tpl.prefix)
    if entry is None:
        return None
    value = props.get(entry[3])
    if value in (None, ""):
        return None
    # Every placeholder in a mapped template reads the same variable
    # (`…/${slug}/${slug}.zip`), so one substitution fills them all.
    return _PLACEHOLDER.sub(quote(str(value), safe=""), tpl.template)


def prefix_row(tpl: DetailTemplate) -> LinkRow:
    """Fallback check: the template's static prefix.

    Detects a dead host or a moved path root — NOT a bad id. That limit is real
    and is reported as such; a prefix-checked template must never be presented
    as a verified deep link.
    """
    norm = normalize_url(tpl.prefix)
    return LinkRow(
        layer_id="(detail-template)", surface="detail-prefix",
        url_raw=tpl.prefix, url_normalized=norm, kind=classify_kind(norm),
        file=tpl.file, line=tpl.line,
    )


async def fetch_layer_features(
    url: str, api_key: str, limit: int = 5,
    transport: httpx.BaseTransport | None = None,
    params: dict | None = None,
) -> list[dict]:
    """Fetch a few real features. Returns [] on any failure — one unreachable
    layer degrades that layer's coverage, it does not abort the audit.

    `params` carries any extra query params a layer needs to return non-empty
    results (e.g. biodiversity/hotspots requires `zoom>=3`); `limit` is always
    sent alongside them, same as before."""
    query = {"limit": limit, **(params or {})}
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30.0), transport=transport,
            headers={"X-API-Key": api_key},
        ) as client:
            resp = await client.get(url, params=query)
            if resp.status_code != 200:
                return []
            payload = resp.json()
    except Exception:  # noqa: BLE001 — any failure is degraded coverage
        return []
    feats = payload.get("features") if isinstance(payload, dict) else None
    return list(feats)[:limit] if isinstance(feats, list) else []
