# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""SEO — all fifteen `/v1/seo/*` endpoints: bot-facing pre-rendered data for
per-feature pages (concessions, vents, seamounts, OceanSITES moorings, ONC
observatories, Arctic river stations), sitemap generation, and the resource
type / contractor pSEO directory pages.

These endpoints feed **bot-facing SSR**, not the SPA: `frontend/server.js`
(bot-UA check, hardcodes the backend origin) fetches from here and
renders full HTML via `frontend/seo/render-page.js`; humans instead get the
React shell and client-side routing. Coverage is **deliberately selective** —
only layers with named, individually meaningful locations get SEO pages (ISA
concessions/contractors, hydrothermal vents, seamounts, OceanSITES moorings,
ONC observatories, Arctic river stations). Dots-on-a-globe layers — GBIF/OBIS
occurrences, fire detections, vessel events — have none by design.

`get_vent_report` (`/v1/seo/vent-report/{vent_id}`) is deliberately included
here despite reading like a vents route. Phase 2 Task 6 left it in main.py
rather than pulling it into `seafloor.py` specifically so this whole family
could move together in one piece — see `seafloor.py`'s "Two things that look
like they belong here but do NOT" section (now historical: at the time it was
written this module did not yet exist).

Moved verbatim out of backend/main.py (Task 1 of the backend vertical-split
refactor, Phase 3). Only permitted edits applied: `@app.get` -> `@router.get`,
`_pool.acquire()` -> `db.pool.acquire()`, leading underscore dropped from the
two moved top-level helper functions that are not `_sync_*`-shaped
(`_seo_env_counts` -> `seo_env_counts`, `_contractor_slug` -> `contractor_slug`
— same "drop the leading underscore from every moved top-level function name,
not just the sync_* ones" rule geochem.py and offshore.py already established;
both call sites of each function were updated to match), and imports/docstring.
Module-level *constants* (non-callables) keep their leading underscore,
matching that same precedent: `_RESOURCE_SLUGS`, `_RESOURCE_BY_SLUG`,
`_SEO_ENV_COUNTS_SQL`, `_SEO_ENV_COUNTS_LIVE_SQL`.

## Response models moved here too — they were never main.py's to keep

The eight Pydantic response models this family's endpoints return
(`SeoMeta`, `ConcessionSeo`, `VentSeo`, `SeamountSeo`, `OceanSitesSeo`,
`OncSeo`, `SitemapEntry`, `WidgetData`) lived at main.py lines 93-182 — well
outside the 8078-9121 endpoint span the task brief measured, grouped instead
with the handful of other top-level `BaseModel` classes near the top of the
file. Verified (`grep -rn` across `backend/`) that none of the eight is
referenced anywhere outside the moved endpoints, so leaving them in main.py
would have forced this module to `import main` — exactly the one-way-
dependency violation the refactor's global constraints call out as a
stop-and-escalate case. Since they are exclusively this family's, they moved
with it instead of being imported. `SitemapEntry` is carried along despite
being unused by any endpoint (verified: no `response_model=SitemapEntry` and
no in-body construction anywhere in main.py) — it sits between `OncSeo` and
`WidgetData` in the same contiguous response-model block, is unmistakably
SEO-shaped, and has no other home; it is not deleted because a refactor is
not the place to prune apparently-dead code.

## Interleaved helpers that came along, and why they belong here

`_RESOURCE_SLUGS` / `_RESOURCE_BY_SLUG` (resource-type <-> URL-slug maps),
`_SEO_ENV_COUNTS_SQL` / `_SEO_ENV_COUNTS_LIVE_SQL` (the cached-vs-live species/
vent count queries backing the resource and contractor pSEO pages) and
`seo_env_counts` / `contractor_slug` (helpers) all sat inside the endpoint
span, are used exclusively by `seo_resource`/`seo_resources_list` and
`seo_contractor`/`seo_contractors_list`/`seo_sitemap_entries`/
`seo_sitemap_core`, and are not referenced anywhere else in main.py (verified
by grep) — moved verbatim, in their original relative order.

## No cache globals — `clear_caches()` is a documented no-op

Unlike geochem/cables/acoustic, this family declares no `_xxx_cache` module
global. The only "caches" the SQL touches are Postgres tables
(`report_cache`, `claim_species_cache`) — not Python state — so there is
nothing here for `/admin/cache/clear` to sweep. Confirmed no line in
`admin_cache_clear()` needs to move or be deleted for this task: at the time
it swept `_cache`, `_grid_cache`, `_argo_float_cache`, `_argo_trail_cache` and
`_claims_risk_cache` directly, none of which belonged to SEO. Those four have
since moved into their own domains' `clear_caches()` (`_grid_cache` to
`biodiversity`, `_argo_float_cache`/`_argo_trail_cache` to `sensors`,
`_claims_risk_cache` to `isa`) and `admin_cache_clear()` now delegates to the
`CACHE_CLEARING_DOMAINS` loop instead of naming them itself; only `_cache`
is still main's own. `clear_caches()` is kept
anyway (and this module still registered in `CACHE_CLEARING_DOMAINS`) purely
to satisfy the uniform per-domain contract `backend/tests/test_domain_cache_
clear.py` enforces via `pkgutil.iter_modules`.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

import db
import ocean_basin
from auth import get_api_key
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

log = logging.getLogger(__name__)
router = APIRouter()

# Largest value a Postgres `integer` (int4) column can hold.
#
# ⚠️ FastAPI's `int` validates "is this an integer", NOT "does this fit in the
# column". `seamounts.peak_id` and `hydrothermal_vents.id` are int4, so
# `/v1/seo/seamount/2147483648` passed validation, reached asyncpg, and raised
# a range error that nothing caught — **HTTP 500**. Exactly at the boundary:
# 2147483647 → 404, 2147483648 → 500 (measured live 2026-08-19).
#
# That 500 is worse than it looks. The frontend maps 5xx to a 503 +
# `Retry-After`, correctly, because a 5xx is supposed to mean "ask again". So
# an id that can never exist told Google to keep coming back forever, and made
# a typo indistinguishable from a real outage. The id is out of range for the
# column; that is a statement about the id, so it is a 404.
_INT4_MAX = 2_147_483_647


def _int4_or_404(value: int, what: str) -> int:
    """Reject an id no int4 column could hold, before it reaches the driver."""
    if not -_INT4_MAX - 1 <= value <= _INT4_MAX:
        raise HTTPException(status_code=404, detail=f"{what} {value} not found")
    return value

# The self-referencing `Dataset` node every SSR entity page hangs off `isPartOf`.
#
# This was six hand-copied literals until 2026-08-11, and every one of them was
# missing `description` — a *required* property for `Dataset` in Google's
# structured-data spec, so Search Console rejected 2,028 items across all six
# page types at once (validation run failed 06.08). One constant, six call
# sites: a seventh entity route cannot reintroduce the defect by copy-paste,
# and `backend/tests/test_seo_dataset_node.py` fails if one tries.
#
# `description` is deliberately the SAME STRING as the `WebApplication` node in
# `frontend/seo/site-graph.json` (`@graph[1]`). Both appear in the *same*
# rendered document — `frontend/seo/render-page.js` emits this JSON-LD at line
# 63 and the whole site graph at line 302 — so a second, freshly-worded
# sentence would have the site describing itself two different ways in one
# page. The test asserts the two stay byte-identical rather than trusting
# anyone to remember. Do not edit one without the other.
ABYSSAL_DATASET = {
    "@type": "Dataset",
    "name": "Abyssal Claims",
    "description": (
        "Interactive 3D map tracking 50+ environmental data layers across "
        "ocean and land. Deep-sea mining concessions, global mining "
        "footprints, deforestation, active fires, air quality, biodiversity "
        "hotspots, hydrothermal vents, and real-time monitoring — powered by "
        "ISA, OBIS, NASA FIRMS, OpenAQ, WRI, and more."
    ),
    "url": "https://something-rare.com",
    "license": "https://creativecommons.org/licenses/by/4.0/",
    "creator": {
        "@type": "Person",
        "name": "Michal Mazurowski",
        "identifier": "https://orcid.org/0009-0007-3786-0310",
        "url": "https://orcid.org/0009-0007-3786-0310",
    },
}


def clear_caches() -> None:
    """No-op: this domain declares no cache globals. See module docstring."""
    return None


# ── Response models ──────────────────────────────────────────────────────────

class SeoMeta(BaseModel):
    title: str
    description: str
    canonical_url: str
    og_image: Optional[str] = None
    json_ld: dict


class ConcessionSeo(BaseModel):
    meta: SeoMeta
    contractor_name: str
    isa_id: str
    resource_type: Optional[str]
    area_km2: Optional[float]
    act_date: Optional[str]
    expiry_date: Optional[str]
    is_high_risk: bool
    jurisdiction_text: Optional[str]
    nearest_eez_country: Optional[str]
    nearest_eez_dist_km: Optional[float]
    nearest_unesco_site: Optional[str]
    nearest_unesco_dist_km: Optional[float]
    vent_conflicts: int
    nearby_species: int
    nearby_argo_floats: int
    nearby_onc_stations: int
    nearby_oceansites_moorings: int
    centroid_lon: Optional[float]
    centroid_lat: Optional[float]


class VentSeo(BaseModel):
    meta: SeoMeta
    name: str
    status: str
    depth_m: Optional[float]
    latitude: float
    longitude: float
    nearby_concessions: list[str]


class SeamountSeo(BaseModel):
    meta: SeoMeta
    peak_id: int
    height_m: Optional[float]
    summit_depth_m: Optional[float]
    area_km2: Optional[float]
    in_concession: bool
    latitude: float
    longitude: float
    # Related links. Default to empty/None so an older caller — or a response
    # replayed from a cache written before this field existed — still validates.
    nearby_seamounts: list[dict] = []
    nearby_concession: Optional[dict] = None


class OceanSitesSeo(BaseModel):
    meta: SeoMeta
    ref: str
    name: str
    network: str
    status: str
    lat: float
    lon: float
    deploy_date: Optional[str]
    nearby_concessions: list[str]


class OncSeo(BaseModel):
    meta: SeoMeta
    location_code: str
    name: str
    depth_m: Optional[float]
    description: str
    lat: float
    lon: float
    nearby_concessions: list[str]


class SitemapEntry(BaseModel):
    loc: str
    lastmod: str
    changefreq: str
    priority: float


class WidgetData(BaseModel):
    entity_type: str
    entity_id: str
    name: str
    risk_score: Optional[float]
    summary: str
    canonical_url: str
    data: dict


# A float report with neither a narrative nor any key_stats renders every figure
# as an em dash — ~399 characters of visible text under a 200. Google files that
# as a soft 404, and did so on 2026-08-23. Such a URL must not be advertised in
# the sitemap; `/report/{id}` answers 410 for it (frontend/seo/render-page.js,
# `reportHasStatistics` — keep the two predicates in step).
#
# ⚠️ The test is on what the PAGE renders, not on the record's own counters:
# `chess:Snake Pit` has claim_count = 16 with an empty executive summary, so
# filtering on the counters would keep exactly the URLs this is meant to drop.
REPORT_SITEMAP_SQL = """
    SELECT platform_id,
           generated_at,
           (
               COALESCE(report_json -> 'executive_summary' ->> 'narrative', '') <> ''
               OR COALESCE(report_json -> 'executive_summary' -> 'key_stats', '{}'::jsonb) <> '{}'::jsonb
           ) AS has_statistics
      FROM report_cache
     ORDER BY generated_at DESC
"""

# ── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/v1/seo/concession/{isa_id}", response_model=ConcessionSeo, dependencies=[Depends(get_api_key)])
async def seo_concession(isa_id: str):
    # All counts are pre-computed by isa.enrich_claim_boundaries() (weekly chain
    # via _SYNC_SOURCES["claim-enrichment"]) and stored on mining_contracts.
    # This endpoint is now a sub-millisecond row fetch — no spatial subqueries.
    # COALESCE returns 0 if the cache is unpopulated (fresh DB pre-enrichment).
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT mc.contractor_name, mc.isa_id, mc.resource_type,
                   mc.area_km2, mc.act_date, mc.expiry_date,
                   mc.is_high_risk, mc.jurisdiction_text,
                   mc.nearest_eez_country, mc.nearest_eez_dist_km,
                   mc.nearest_unesco_site, mc.nearest_unesco_dist_km,
                   ST_X(ST_Centroid(mc.geom::geometry)) AS centroid_lon,
                   ST_Y(ST_Centroid(mc.geom::geometry)) AS centroid_lat,
                   COALESCE(mc.vent_conflicts, 0)             AS vent_conflicts,
                   COALESCE(mc.nearby_species, 0)             AS nearby_species,
                   COALESCE(mc.nearby_argo_floats, 0)         AS nearby_argo_floats,
                   COALESCE(mc.nearby_onc_stations, 0)        AS nearby_onc_stations,
                   COALESCE(mc.nearby_oceansites_moorings, 0) AS nearby_oceansites_moorings
            FROM mining_contracts mc
            WHERE mc.isa_id = $1
        """, isa_id)

    if not row:
        raise HTTPException(status_code=404, detail=f"Concession {isa_id} not found")

    contractor = row["contractor_name"]
    resource = row["resource_type"] or "Deep-Sea Minerals"
    area = row["area_km2"]
    risk = "High-Risk" if row["is_high_risk"] else "Active"

    title = f"{contractor} — {risk} ISA Mining Concession | Abyssal Claims"
    description = (
        f"{contractor} holds ISA concession {isa_id} for {resource} exploration"
        f"{f', covering {area:,.0f} km²' if area else ''}. "
        f"{row['vent_conflicts']} hydrothermal vents and "
        f"{row['nearby_species']:,} biodiversity records "
        f"documented within 50 km (OBIS). "
        f"Monitored by {row['nearby_argo_floats']} Argo floats, "
        f"{row['nearby_onc_stations']} ONC observatories, "
        f"and {row['nearby_oceansites_moorings']} OceanSITES moorings."
    )

    return ConcessionSeo(
        meta=SeoMeta(
            title=title,
            description=description[:160],
            canonical_url=f"https://something-rare.com/concession/{isa_id}",
            json_ld={
                "@context": "https://schema.org",
                "@type": "Place",
                "name": f"ISA Concession {isa_id} — {contractor}",
                "description": description,
                "url": f"https://something-rare.com/concession/{isa_id}",
                "geo": {
                    "@type": "GeoCoordinates",
                    "latitude": row["centroid_lat"],
                    "longitude": row["centroid_lon"],
                },
                "isPartOf": ABYSSAL_DATASET,
            },
        ),
        contractor_name=contractor,
        isa_id=isa_id,
        resource_type=row["resource_type"],
        area_km2=area,
        act_date=str(row["act_date"]) if row["act_date"] else None,
        expiry_date=str(row["expiry_date"]) if row["expiry_date"] else None,
        is_high_risk=row["is_high_risk"],
        jurisdiction_text=row["jurisdiction_text"],
        nearest_eez_country=row["nearest_eez_country"],
        nearest_eez_dist_km=row["nearest_eez_dist_km"],
        nearest_unesco_site=row["nearest_unesco_site"],
        nearest_unesco_dist_km=row["nearest_unesco_dist_km"],
        vent_conflicts=row["vent_conflicts"],
        nearby_species=row["nearby_species"],
        nearby_argo_floats=row["nearby_argo_floats"],
        nearby_onc_stations=row["nearby_onc_stations"],
        nearby_oceansites_moorings=row["nearby_oceansites_moorings"],
        centroid_lon=row["centroid_lon"],
        centroid_lat=row["centroid_lat"],
    )


@router.get("/v1/seo/vent/{vent_id}", response_model=VentSeo, dependencies=[Depends(get_api_key)])
async def seo_vent(vent_id: int):
    _int4_or_404(vent_id, "Vent")
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT hv.id, hv.name, hv.status, hv.depth_m, hv.latitude, hv.longitude,
                   coalesce(
                       (SELECT array_agg(DISTINCT mc.contractor_name)
                        FROM mining_contracts mc
                        WHERE ST_DWithin(mc.geom::geography, hv.geom, 50000)),
                       ARRAY[]::text[]
                   ) AS nearby_concessions
            FROM hydrothermal_vents hv
            WHERE hv.id = $1
        """, vent_id)

    if not row:
        raise HTTPException(status_code=404, detail=f"Vent {vent_id} not found")

    name = row["name"]
    status = row["status"]
    depth = row["depth_m"]
    concessions = row["nearby_concessions"] or []

    title = f"{name} — {status} Hydrothermal Vent | Abyssal Claims"
    description = (
        f"{name} is {'an' if status == 'Active' else 'a'} {status.lower()} hydrothermal vent"
        f"{f' at {depth:,.0f}m depth' if depth else ''}. "
        f"{'Threatened by ' + str(len(concessions)) + ' nearby mining concession(s).' if concessions else 'No nearby mining concessions.'} "
        f"InterRidge Database v3.4."
    )

    return VentSeo(
        meta=SeoMeta(
            title=title,
            description=description[:160],
            canonical_url=f"https://something-rare.com/vent/{vent_id}",
            json_ld={
                "@context": "https://schema.org",
                "@type": "Place",
                "name": name,
                "description": description,
                "url": f"https://something-rare.com/vent/{vent_id}",
                "geo": {
                    "@type": "GeoCoordinates",
                    "latitude": row["latitude"],
                    "longitude": row["longitude"],
                },
                "isPartOf": ABYSSAL_DATASET,
            },
        ),
        name=name,
        status=status,
        depth_m=depth,
        latitude=row["latitude"],
        longitude=row["longitude"],
        nearby_concessions=concessions,
    )


@router.get("/v1/seo/vent-report/{vent_id}", dependencies=[Depends(get_api_key)])
async def get_vent_report(vent_id: int):
    """Aggregated vent report data: metadata, ChEssBase species, nearby mining claims."""
    _int4_or_404(vent_id, "Vent")
    async with db.pool.acquire() as conn:
        vent = await conn.fetchrow("""
            SELECT name, status, depth_m, latitude, longitude, source_url,
                   COALESCE(chess_count, 0) AS chess_count,
                   COALESCE(chess_species::text, '[]') AS chess_species,
                   max_temp_c, temp_category, min_depth_m, ocean, region,
                   jurisdiction, tectonic_setting, discovery_year,
                   discovery_year_num, date_precision, biology_notes
            FROM hydrothermal_vents
            WHERE id = $1
        """, vent_id)
        if not vent:
            raise HTTPException(status_code=404, detail="Vent not found")

        nearby = await conn.fetch("""
            SELECT contractor_name, isa_id, resource_type,
                   ST_Distance(
                       geom::geography,
                       ST_MakePoint($1, $2)::geography
                   ) / 1000.0 AS distance_km
            FROM mining_contracts
            WHERE ST_DWithin(
                geom::geography,
                ST_MakePoint($1, $2)::geography,
                100000
            )
            ORDER BY distance_km
        """, vent["longitude"], vent["latitude"])

    return {
        "name":           vent["name"],
        "status":         vent["status"],
        "depth_m":        vent["depth_m"],
        "min_depth_m":    vent["min_depth_m"],
        "max_temp_c":     vent["max_temp_c"],
        "temp_category":  vent["temp_category"],
        "ocean":          vent["ocean"],
        "region":         vent["region"],
        "jurisdiction":   vent["jurisdiction"],
        "tectonic_setting": vent["tectonic_setting"],
        "discovery_year": vent["discovery_year"],
        "discovery_year_num": vent["discovery_year_num"],
        "date_precision": vent["date_precision"],
        "biology_notes":  vent["biology_notes"],
        "latitude":       vent["latitude"],
        "longitude":      vent["longitude"],
        "source_url":     vent["source_url"],
        "chess_count":    vent["chess_count"],
        "chess_species":  json.loads(vent["chess_species"]),
        "nearby_claims":  [
            {
                "isa_id":           r["isa_id"],
                "contractor_name":  r["contractor_name"],
                "resource_type":    r["resource_type"],
                "distance_km":      round(float(r["distance_km"]), 1),
            }
            for r in nearby
        ],
    }


# ── Seamount snippet copy ────────────────────────────────────────────────────
# Rewritten 2026-08-17. The previous title was "Seamount #N | Abyssal Claims"
# and the description was ONE template across all 594 indexed pages, varying
# only in digits the searcher had already typed. Measured CTR 0.8 % at average
# position 7.9, against 13.9 % for /about at 5.7 — position does not explain a
# 17× gap, the snippet does.
#
# Two things the old copy asserted that we could not support:
#   * "Biodiversity hotspot and potential cobalt-crust mining target" was
#     printed for EVERY seamount with no per-feature evidence for either claim.
#     Removed outright. This project does not render a finding where no study
#     exists, and Google discounts boilerplate anyway.
#   * "Located WITHIN an active ISA mining concession" — `in_concession` is
#     `ST_DWithin(..., 10000)`, i.e. within 10 km OF one. A feature 9 km outside
#     a claim boundary was being told it sat inside it. Now worded as proximity,
#     which is what the query measures.
#
# ⛔ Never add a seamount NAME here. Yesson et al. (2011) is a morphology-derived
# census; most of these features are unnamed. Basin comes from coordinates and
# is a derivation; a name would be fabrication.
#
# Both builders assemble clauses in priority order and drop the lowest-priority
# ones until the string fits its budget, so a long basin name or a seven-digit
# id degrades the copy instead of getting truncated mid-word by Google.

_TITLE_BUDGET = 60      # ~580 px, where Google truncates
_DESCRIPTION_BUDGET = 160


def _fit(prefix: str, clauses: list[str], suffix: str, budget: int, sep: str = ", ") -> str:
    """Longest prefix+clauses+suffix that fits the budget, dropping from the end."""
    for n in range(len(clauses), -1, -1):
        candidate = prefix + sep.join(clauses[:n]) + suffix
        if len(candidate) <= budget or n == 0:
            return candidate
    return prefix + suffix


def _seamount_title(peak_id: int, height, basin: str | None, in_conc: bool) -> str:
    # Basin BEFORE height, because `_fit` drops from the end and the basin is
    # the whole point of the rewrite — it is what makes the result recognisable,
    # whereas the height is another number beside the id. Caught on real data:
    # with height first, "Seamount #2930483 — 2,544 m, Mediterranean Sea" came
    # to 63 chars and degraded to a bare "2,544 m", spending 44 of a 60-char
    # budget to say nothing, when "— Mediterranean Sea" fits in 54.
    clauses: list[str] = []
    if basin:
        clauses.append(basin)
    if height:
        clauses.append(f"{height:,.0f} m")
    if in_conc:
        clauses.append("near ISA claim")
    if not clauses:
        return f"Seamount #{peak_id} | Abyssal Claims"
    return _fit(f"Seamount #{peak_id} — ", clauses, " | Abyssal Claims", _TITLE_BUDGET)


def _seamount_description(height, summit_depth, area_km2, basin: str | None, in_conc: bool) -> str:
    lead = f"A {height:,.0f} m seamount" if height else "A seamount"
    if basin:
        lead += f" in the {basin}"

    clauses: list[str] = []
    if summit_depth:
        clauses.append(f"rising to {summit_depth:,.0f} m below the surface")
    if area_km2:
        clauses.append(f"covering {area_km2:,.0f} km²")

    # Join as prose ("A, B and C"), not as a spec sheet ("A, B, C"). Built from
    # the surviving clauses AFTER the budget has had its say, so a dropped
    # clause can never leave a dangling "and".
    for n in range(len(clauses), -1, -1):
        kept = clauses[:n]
        if not kept:
            body = lead + "."
        elif len(kept) == 1:
            body = f"{lead}, {kept[0]}."
        else:
            body = f"{lead}, {', '.join(kept[:-1])} and {kept[-1]}."
        if len(body) <= _DESCRIPTION_BUDGET or n == 0:
            break

    # Lowest-priority sentences, appended only while they still fit whole. The
    # citation goes last: it is the least useful thing to a searcher, and it is
    # already on the page itself.
    for extra in (
        " Within 10 km of an ISA mining concession." if in_conc else "",
        " Mapped from global bathymetry (Yesson et al. 2011).",
    ):
        if extra and len(body) + len(extra) <= _DESCRIPTION_BUDGET:
            body += extra
    return body


@router.get("/v1/seo/seamount/{peak_id}", response_model=SeamountSeo, dependencies=[Depends(get_api_key)])
async def seo_seamount(peak_id: int):
    _int4_or_404(peak_id, "Seamount")
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT s.peak_id, s.height_m, s.summit_depth_m, s.area_km2,
                   ST_Y(s.geom::geometry) AS latitude,
                   ST_X(s.geom::geometry) AS longitude,
                   EXISTS(
                       SELECT 1 FROM mining_contracts mc
                       WHERE ST_DWithin(mc.geom::geography, s.geom::geography, 10000)
                   ) AS in_concession
            FROM seamounts s
            WHERE s.peak_id = $1
        """, peak_id)

        if not row:
            raise HTTPException(status_code=404, detail=f"Seamount {peak_id} not found")

        # ── Genuinely nearby features, for the page's related links ──────────
        # A seamount page linked only to "/" (measured 2026-08-17), so 37,889
        # pages formed no graph at all. The cure is links to real neighbours —
        # and ONLY to real ones: the brief for this work is explicit that a
        # "related" list which is really a random sample is a link farm with
        # extra steps.
        #
        # 100 km is measured, not chosen for looks. Nearest-neighbour distance
        # over a 400-seamount sample: p50 6.1 km, p90 44.6 km, p99 138.5 km.
        # At 100 km, 2.2 % of seamounts (11 of a 500 sample) have no neighbour
        # at all and correctly render no block — they are genuinely isolated.
        neighbours = await conn.fetch("""
            SELECT o.peak_id, o.height_m, o.latitude, o.longitude,
                   ST_Distance(o.geom::geography, s.geom::geography) / 1000.0 AS dist_km
            FROM seamounts o, seamounts s
            WHERE s.peak_id = $1
              AND o.peak_id <> s.peak_id
              AND ST_DWithin(o.geom::geography, s.geom::geography, 100000)
            ORDER BY o.geom <-> s.geom
            LIMIT 6
        """, peak_id)
        # The concession behind the existing in_concession flag — same predicate
        # (ST_DWithin 10 km), so the boolean cannot disagree with the link.
        concession = await conn.fetchrow("""
            SELECT mc.isa_id, mc.contractor_name,
                   ST_Distance(mc.geom::geography, s.geom::geography) / 1000.0 AS dist_km
            FROM mining_contracts mc, seamounts s
            WHERE s.peak_id = $1
              AND ST_DWithin(mc.geom::geography, s.geom::geography, 10000)
            ORDER BY mc.geom <-> s.geom
            LIMIT 1
        """, peak_id)

    height = row["height_m"]
    in_conc = row["in_concession"]
    summit_depth = row["summit_depth_m"]
    basin = ocean_basin.basin_for(row["latitude"], row["longitude"])

    title = _seamount_title(peak_id, height, basin, in_conc)
    description = _seamount_description(height, summit_depth, row["area_km2"], basin, in_conc)

    return SeamountSeo(
        meta=SeoMeta(
            title=title,
            description=description[:160],
            canonical_url=f"https://something-rare.com/seamount/{peak_id}",
            json_ld={
                "@context": "https://schema.org",
                "@type": "Place",
                "name": f"Seamount #{peak_id}",
                "description": description,
                "url": f"https://something-rare.com/seamount/{peak_id}",
                "geo": {
                    "@type": "GeoCoordinates",
                    "latitude": row["latitude"],
                    "longitude": row["longitude"],
                },
                "isPartOf": ABYSSAL_DATASET,
            },
        ),
        peak_id=peak_id,
        height_m=height,
        summit_depth_m=row["summit_depth_m"],
        area_km2=row["area_km2"],
        in_concession=in_conc,
        latitude=row["latitude"],
        longitude=row["longitude"],
        nearby_seamounts=[
            {
                "peak_id": n["peak_id"],
                "height_m": n["height_m"],
                "dist_km": round(n["dist_km"], 1),
                "basin": ocean_basin.basin_for(n["latitude"], n["longitude"]),
            }
            for n in neighbours
        ],
        nearby_concession=(
            {
                "isa_id": concession["isa_id"],
                "contractor_name": concession["contractor_name"],
                "dist_km": round(concession["dist_km"], 1),
            }
            if concession else None
        ),
    )


@router.get("/v1/seo/oceansites/{ref}", response_model=OceanSitesSeo, dependencies=[Depends(get_api_key)])
async def seo_oceansites(ref: str):
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT ref, name, network, status, lat, lon, deploy_date
            FROM oceansites_stations WHERE ref = $1
        """, ref)
    if not row:
        raise HTTPException(status_code=404, detail=f"OceanSITES station {ref} not found")

    async with db.pool.acquire() as conn:
        nearby = await conn.fetch("""
            SELECT mc.contractor_name
            FROM mining_contracts mc, oceansites_stations os
            WHERE os.ref = $1
            AND ST_DWithin(os.geom::geography, mc.geom::geography, 500000)
        """, ref)

    nearby_names = [r["contractor_name"] for r in nearby]
    title = f"{row['name']} ({row['ref']}) — OceanSITES Mooring Station | Abyssal Claims"
    description = (
        f"{row['name']} is an OceanSITES mooring station in the {row['network']} network, "
        f"located at {row['lat']:.3f}°, {row['lon']:.3f}°. "
        f"Status: {row['status']}. "
        + (f"Within 500 km of {len(nearby_names)} active mining concession(s)." if nearby_names else "No active mining concessions within 500 km.")
    )
    return OceanSitesSeo(
        meta=SeoMeta(
            title=title,
            description=description[:160],
            canonical_url=f"https://something-rare.com/oceansites/{ref}",
            json_ld={
                "@context": "https://schema.org",
                "@type": "Place",
                "name": row["name"],
                "description": description,
                "url": f"https://something-rare.com/oceansites/{ref}",
                "geo": {"@type": "GeoCoordinates", "latitude": row["lat"], "longitude": row["lon"]},
                "isPartOf": ABYSSAL_DATASET,
            },
        ),
        ref=row["ref"],
        name=row["name"],
        network=row["network"],
        status=row["status"],
        lat=row["lat"],
        lon=row["lon"],
        deploy_date=str(row["deploy_date"]) if row["deploy_date"] else None,
        nearby_concessions=nearby_names,
    )


@router.get("/v1/seo/river/{station_id}", dependencies=[Depends(get_api_key)])
async def seo_river(station_id: str):
    async with db.pool.acquire() as conn:
        r = await conn.fetchrow("""
            SELECT station_id, river_name, site_label, lat, lon, record_start,
                   record_end, mean_annual_discharge_km3, annual_fluxes, citation
            FROM arctic_river_stations WHERE station_id = $1 AND source = 'arcticgro'
        """, station_id)
    if not r:
        raise HTTPException(status_code=404, detail="River not found")
    return dict(r)


@router.get("/v1/seo/onc/{code}", response_model=OncSeo, dependencies=[Depends(get_api_key)])
async def seo_onc(code: str):
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT location_code, name, depth_m, description, lat, lon
            FROM onc_locations WHERE location_code = $1
        """, code)
    if not row:
        raise HTTPException(status_code=404, detail=f"ONC station {code} not found")

    async with db.pool.acquire() as conn:
        nearby = await conn.fetch("""
            SELECT mc.contractor_name
            FROM mining_contracts mc, onc_locations ol
            WHERE ol.location_code = $1
            AND ST_DWithin(ol.geom::geography, mc.geom::geography, 200000)
        """, code)

    nearby_names = [r["contractor_name"] for r in nearby]
    title = f"{row['name']} — ONC Seafloor Observatory | Abyssal Claims"
    depth_str = f" at {row['depth_m']:.0f} m depth" if row["depth_m"] else ""
    description = (
        f"{row['name']} is an Ocean Networks Canada observatory node{depth_str}, "
        f"providing real-time seismic, pressure, and chemistry data. "
        + (f"Within 200 km of {len(nearby_names)} active mining concession(s)." if nearby_names else "No active mining concessions within 200 km.")
    )
    return OncSeo(
        meta=SeoMeta(
            title=title,
            description=description[:160],
            canonical_url=f"https://something-rare.com/onc/{code}",
            json_ld={
                "@context": "https://schema.org",
                "@type": "Place",
                "name": row["name"],
                "description": description,
                "url": f"https://something-rare.com/onc/{code}",
                "geo": {"@type": "GeoCoordinates", "latitude": row["lat"], "longitude": row["lon"]},
                "isPartOf": ABYSSAL_DATASET,
            },
        ),
        location_code=row["location_code"],
        name=row["name"],
        depth_m=row["depth_m"],
        description=row["description"] or "",
        lat=row["lat"],
        lon=row["lon"],
        nearby_concessions=nearby_names,
    )


@router.get("/v1/seo/sitemap-entries", dependencies=[Depends(get_api_key)])
async def seo_sitemap_entries():
    async with db.pool.acquire() as conn:
        concessions = await conn.fetch("""
            SELECT isa_id, COALESCE(act_date, created_at, NOW()) AS lastmod
            FROM mining_contracts
            ORDER BY isa_id
        """)
        vents = await conn.fetch("""
            SELECT id, COALESCE(created_at, NOW()) AS lastmod
            FROM hydrothermal_vents
            ORDER BY id
        """)
        seamounts = await conn.fetch("""
            SELECT peak_id FROM seamounts ORDER BY peak_id
        """)
        sync = await conn.fetch("SELECT source, last_synced_at FROM sync_log")
        reports = await conn.fetch(REPORT_SITEMAP_SQL)
        oceansites = await conn.fetch("""
            SELECT ref, updated_at FROM oceansites_stations ORDER BY ref
        """)
        # Gated on latest_sensors IS NOT NULL: with onc_ingest.py now pulling
        # every ONC device category, onc_locations holds ~1,993 rows (most
        # junction boxes, power supplies, cameras with nothing to show on a
        # page). Same marker sync_onc_sensors() uses to know "has data" and
        # isa.py::enrich_claim_boundaries() now uses for nearby_onc_stations.
        # seo_onc() below stays UNGATED — every location still resolves at
        # /v1/seo/onc/{code}, it just isn't advertised in the sitemap.
        onc_locs = await conn.fetch("""
            SELECT location_code, updated_at FROM onc_locations
            WHERE latest_sensors IS NOT NULL
            ORDER BY location_code
        """)
        rivers = await conn.fetch(
            "SELECT station_id FROM arctic_river_stations WHERE source='arcticgro' ORDER BY station_id"
        )

    sync_map = {r["source"]: r["last_synced_at"] for r in sync}
    seamount_sync = sync_map.get("seamounts")
    seamount_lastmod = str(seamount_sync.date()) if seamount_sync else "2026-04-01"

    entries: list[dict] = [
        {"loc": "https://something-rare.com/", "lastmod": str(max(sync_map.values()).date()) if sync_map else "2026-04-01", "changefreq": "weekly", "priority": 1.0},
        {"loc": "https://something-rare.com/about", "lastmod": "2026-04-01", "changefreq": "monthly", "priority": 0.5},
        {"loc": "https://something-rare.com/privacy", "lastmod": "2026-03-27", "changefreq": "yearly", "priority": 0.3},
        {"loc": "https://something-rare.com/terms", "lastmod": "2026-03-27", "changefreq": "yearly", "priority": 0.3},
    ]

    for r in concessions:
        entries.append({
            "loc": f"https://something-rare.com/concession/{r['isa_id']}",
            "lastmod": str(r["lastmod"].date()) if r["lastmod"] else "2026-04-01",
            "changefreq": "weekly",
            "priority": 0.8,
        })
    for r in vents:
        entries.append({
            "loc": f"https://something-rare.com/vent/{r['id']}",
            "lastmod": str(r["lastmod"].date()) if r["lastmod"] else "2026-04-01",
            "changefreq": "monthly",
            "priority": 0.6,
        })
    for r in seamounts:
        entries.append({
            "loc": f"https://something-rare.com/seamount/{r['peak_id']}",
            "lastmod": seamount_lastmod,
            "changefreq": "yearly",
            "priority": 0.4,
        })
    for r in oceansites:
        lastmod = str(r["updated_at"].date()) if r.get("updated_at") else "2026-04-01"
        entries.append({
            "loc": f"https://something-rare.com/oceansites/{r['ref']}",
            "lastmod": lastmod,
            "changefreq": "monthly",
            "priority": 0.5,
        })
    for r in onc_locs:
        lastmod = str(r["updated_at"].date()) if r.get("updated_at") else "2026-04-01"
        entries.append({
            "loc": f"https://something-rare.com/onc/{r['location_code']}",
            "lastmod": lastmod,
            "changefreq": "monthly",
            "priority": 0.5,
        })

    # Cached impact reports (float reports)
    for r in reports:
        if r["platform_id"].startswith("claim:"):
            continue  # handled below
        if not r["has_statistics"]:
            continue  # renders as em dashes only — a soft 404, see REPORT_SITEMAP_SQL
        entries.append({
            "loc": f"https://something-rare.com/report/{r['platform_id']}",
            "lastmod": str(r["generated_at"].date()),
            "changefreq": "weekly",
            "priority": 0.7,
        })

    # Claim reports
    for r in reports:
        if not r["platform_id"].startswith("claim:"):
            continue
        isa_id = r["platform_id"].replace("claim:", "")
        entries.append({
            "loc": f"https://something-rare.com/claim-report/{isa_id}",
            "lastmod": str(r["generated_at"].date()),
            "changefreq": "weekly",
            "priority": 0.7,
        })

    # Contractor list (reused for the /contractor/* profile pages below).
    # /claim-report/company/* is intentionally NOT emitted — it soft-404'd
    # (302 → /); /contractor/{slug} is the canonical page for the same companies.
    async with db.pool.acquire() as conn2:
        contractors = await conn2.fetch(
            "SELECT DISTINCT contractor_name FROM mining_contracts "
            "WHERE contractor_name IS NOT NULL ORDER BY contractor_name"
        )

    # Resource type pages
    for slug in _RESOURCE_SLUGS.values():
        entries.append({
            "loc": f"https://something-rare.com/resource/{slug}",
            "lastmod": str(max(sync_map.values()).date()) if sync_map else "2026-04-01",
            "changefreq": "monthly",
            "priority": 0.8,
        })

    # Contractor profile pages — one per unique contractor
    for c in contractors:
        slug = contractor_slug(c["contractor_name"])
        entries.append({
            "loc": f"https://something-rare.com/contractor/{slug}",
            "lastmod": str(max(sync_map.values()).date()) if sync_map else "2026-04-01",
            "changefreq": "monthly",
            "priority": 0.7,
        })

    # Arctic river station pages
    river_lastmod = str(sync_map["arctic-rivers"].date()) if sync_map.get("arctic-rivers") else "2026-04-01"
    for r in rivers:
        entries.append({
            "loc": f"https://something-rare.com/river/{r['station_id']}",
            "lastmod": river_lastmod,
            "changefreq": "weekly",
            "priority": 0.6,
        })

    return {"entries": entries, "total": len(entries)}


# ── Per-category sitemap endpoints (for sitemap index) ────────────────────

@router.get("/v1/seo/sitemap/seamounts", dependencies=[Depends(get_api_key)])
async def seo_sitemap_seamounts():
    async with db.pool.acquire() as conn:
        seamounts = await conn.fetch("SELECT peak_id FROM seamounts ORDER BY peak_id")
        sync = await conn.fetchrow("SELECT last_synced_at FROM sync_log WHERE source = 'seamounts'")
    lastmod = str(sync["last_synced_at"].date()) if sync else "2026-04-01"
    entries = [{"loc": f"https://something-rare.com/seamount/{r['peak_id']}", "lastmod": lastmod, "changefreq": "yearly", "priority": "0.4"} for r in seamounts]
    return {"entries": entries}


# ── Which layers get a /layer/{id} SEO page ──────────────────────────────────
# Extracted from the body of `seo_sitemap_core` (values unchanged) so the hub at
# /layer can list exactly the pages the sitemap declares. Two hand-maintained
# copies of this list would drift silently: the sitemap would keep advertising a
# layer page the hub no longer links to, which is the very
# asserted-but-unlinked state that put 29,241 URLs into "Discovered – currently
# not indexed". `backend/tests/test_seo_hubs.py` asserts the two agree.
_LAYER_PAGE_TABLES: list[tuple[str, str]] = [
    ("mining_contracts", "contracts"), ("hydrothermal_vents", "hydrothermal-vents"),
    ("seamounts", "seamounts"), ("biodiversity_hotspots", "biodiversity-hotspots"),
    ("reserved_areas", "reserved-areas"), ("apeis", "apeis"),
    ("relinquished_areas", "relinquished-areas"), ("argo_profiles", "argo"),
    ("eez", "eez"), ("protected_marine_sites", "protected-marine-sites"),
    ("noise_risk_cells", "noise-risk"), ("oceansites_stations", "oceansites"),
    ("onc_locations", "onc"),
    ("chess_sites", "chess"), ("submarine_cables", "submarine-cables"),
    ("port_locations", "ports"),
    ("mining_footprints", "mining-footprints"),
    # ("wdpa", "wdpa") removed 2026-09-03 — frontend/server.js answers
    # /layer/wdpa with 410 Gone. A sitemap that submits a withdrawn URL
    # reports as a crawl error against the whole sitemap, and the /layer
    # hub linked to it from a page Google does index.
    # ("key_biodiversity_areas", "kbas") removed 2026-09-03 — same reason,
    # server.js now answers /layer/kbas with 410 Gone too.
    ("tailings_dams", "tailings"), ("active_fires", "fires"),
    ("air_quality_stations", "air-quality"), ("landslides", "landslides"),
    ("dams", "dams"), ("water_risk", "water-risk"),
]
# Raster/frontend-only layers — no DB table, but they have /layer/ SEO pages
_LAYER_PAGE_TABLELESS: list[str] = [
    "tectonic-plates", "forest-loss", "surface-water", "carbon-flux", "soil-carbon",
]
LAYER_PAGE_IDS: list[str] = [k for _, k in _LAYER_PAGE_TABLES] + _LAYER_PAGE_TABLELESS


@router.get("/v1/seo/sitemap/core", dependencies=[Depends(get_api_key)])
async def seo_sitemap_core():
    """Static pages, blog, concessions, vents, stations, reports, contractors, layers."""
    async with db.pool.acquire() as conn:
        concessions = await conn.fetch("SELECT isa_id, COALESCE(act_date, created_at, NOW()) AS lastmod FROM mining_contracts ORDER BY isa_id")
        vents = await conn.fetch("SELECT id, COALESCE(created_at, NOW()) AS lastmod FROM hydrothermal_vents ORDER BY id")
        oceansites = await conn.fetch("SELECT ref, updated_at FROM oceansites_stations ORDER BY ref")
        # Gated on latest_sensors IS NOT NULL — this is the function server.js
        # actually calls for sitemap.xml (frontend/server.js:881, :1126), unlike
        # seo_sitemap_entries() below which nothing in production fetches.
        # Same marker used by seo_hubs.py's "onc" Hub and nearby_onc_stations.
        onc_locs = await conn.fetch(
            "SELECT location_code, updated_at FROM onc_locations "
            "WHERE latest_sensors IS NOT NULL ORDER BY location_code"
        )
        reports = await conn.fetch(REPORT_SITEMAP_SQL)
        sync = await conn.fetch("SELECT source, last_synced_at FROM sync_log")
        contractors = await conn.fetch("SELECT DISTINCT contractor_name FROM mining_contracts WHERE contractor_name IS NOT NULL ORDER BY contractor_name")
        rivers = await conn.fetch("SELECT station_id FROM arctic_river_stations WHERE source='arcticgro' ORDER BY station_id")
        # Feature counts for layer pages
        layer_counts = {}
        for tbl, key in _LAYER_PAGE_TABLES:
            try:
                cnt = await conn.fetchval(f"SELECT COUNT(*) FROM {tbl}")  # noqa: S608
                layer_counts[key] = cnt
            except Exception:
                layer_counts[key] = 0
        # Raster/frontend-only layers — no DB table, but they have /layer/ SEO pages
        for key in _LAYER_PAGE_TABLELESS:
            layer_counts[key] = 0

    sync_map = {r["source"]: r["last_synced_at"] for r in sync}
    latest = str(max(sync_map.values()).date()) if sync_map else "2026-04-01"

    entries: list[dict] = [
        {"loc": "https://something-rare.com/", "lastmod": latest, "changefreq": "weekly", "priority": "1.0"},
        {"loc": "https://something-rare.com/about", "lastmod": "2026-04-01", "changefreq": "monthly", "priority": "0.5"},
        # /api-docs was ranking (12 impressions, avg position 14.9 over 90 days,
        # measured in GSC 2026-08-16) while listed in no sitemap at all — Google
        # found it through the footer link alone. It is a real public page, so
        # it belongs here. lastmod is its ship date: 2026-06-22, when the
        # Scalar /api-docs page shipped.
        # NOTE: unlike its neighbours it has no SSR route — the Scalar reference
        # and its Helmet title/description/canonical only exist after JS runs.
        {"loc": "https://something-rare.com/api-docs", "lastmod": "2026-06-22", "changefreq": "monthly", "priority": "0.5"},
        {"loc": "https://something-rare.com/privacy", "lastmod": "2026-03-27", "changefreq": "yearly", "priority": "0.3"},
        {"loc": "https://something-rare.com/terms", "lastmod": "2026-03-27", "changefreq": "yearly", "priority": "0.3"},
    ]
    # Concessions
    for r in concessions:
        entries.append({"loc": f"https://something-rare.com/concession/{r['isa_id']}", "lastmod": str(r["lastmod"].date()) if r["lastmod"] else "2026-04-01", "changefreq": "weekly", "priority": "0.8"})
    # Vents
    for r in vents:
        entries.append({"loc": f"https://something-rare.com/vent/{r['id']}", "lastmod": str(r["lastmod"].date()) if r["lastmod"] else "2026-04-01", "changefreq": "monthly", "priority": "0.6"})
    # OceanSITES + ONC
    for r in oceansites:
        lm = str(r["updated_at"].date()) if r.get("updated_at") else "2026-04-01"
        entries.append({"loc": f"https://something-rare.com/oceansites/{r['ref']}", "lastmod": lm, "changefreq": "monthly", "priority": "0.5"})
    for r in onc_locs:
        lm = str(r["updated_at"].date()) if r.get("updated_at") else "2026-04-01"
        entries.append({"loc": f"https://something-rare.com/onc/{r['location_code']}", "lastmod": lm, "changefreq": "monthly", "priority": "0.5"})
    # Arctic Rivers
    river_lastmod = str(sync_map["arctic-rivers"].date()) if sync_map.get("arctic-rivers") else "2026-04-01"
    for r in rivers:
        entries.append({"loc": f"https://something-rare.com/river/{r['station_id']}", "lastmod": river_lastmod, "changefreq": "weekly", "priority": "0.6"})
    # Reports
    for r in reports:
        if r["platform_id"].startswith("claim:"):
            isa_id = r["platform_id"].replace("claim:", "")
            entries.append({"loc": f"https://something-rare.com/claim-report/{isa_id}", "lastmod": str(r["generated_at"].date()), "changefreq": "weekly", "priority": "0.7"})
        elif r["has_statistics"]:  # see REPORT_SITEMAP_SQL — empty ones are soft 404s
            entries.append({"loc": f"https://something-rare.com/report/{r['platform_id']}", "lastmod": str(r["generated_at"].date()), "changefreq": "weekly", "priority": "0.7"})
    # Contractors — /contractor/{slug} is the canonical 200 page.
    # /claim-report/company/{slug} was removed: it 302-redirected to / (soft-404,
    # wasted crawl budget) and /contractor/* already covers the same companies.
    for c in contractors:
        entries.append({"loc": f"https://something-rare.com/contractor/{contractor_slug(c['contractor_name'])}", "lastmod": latest, "changefreq": "monthly", "priority": "0.7"})
    # Resources
    for slug in _RESOURCE_SLUGS.values():
        entries.append({"loc": f"https://something-rare.com/resource/{slug}", "lastmod": latest, "changefreq": "monthly", "priority": "0.8"})
    # Layer pages
    for layer_id, count in layer_counts.items():
        entries.append({"loc": f"https://something-rare.com/layer/{layer_id}", "lastmod": latest, "changefreq": "weekly", "priority": "0.7"})

    return {"entries": entries, "layer_counts": layer_counts}


# Resource type slug mapping — canonical names to URL slugs
_RESOURCE_SLUGS: dict[str, str] = {
    "Polymetallic Manganese Nodules":      "polymetallic-nodules",
    "Cobalt-Rich Ferromanganese Crusts":   "cobalt-rich-ferromanganese-crusts",
    "Polymetallic Sulphides":              "polymetallic-sulphides",
}
_RESOURCE_BY_SLUG: dict[str, str] = {v: k for k, v in _RESOURCE_SLUGS.items()}


@router.get("/v1/seo/resources", dependencies=[Depends(get_api_key)])
async def seo_resources_list():
    """List all resource types with slugs — used by sitemap and directory."""
    async with db.pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT resource_type,
                   COUNT(*) AS claim_count,
                   ROUND(SUM(area_km2)::numeric, 0) AS total_area_km2,
                   COUNT(DISTINCT contractor_name) AS contractor_count,
                   SUM(CASE WHEN is_high_risk THEN 1 ELSE 0 END) AS high_risk_count
            FROM mining_contracts
            WHERE resource_type IS NOT NULL
            GROUP BY resource_type
            ORDER BY claim_count DESC
        """)
    import json as _json
    result = [
        {
            "slug": _RESOURCE_SLUGS.get(r["resource_type"], r["resource_type"].lower().replace(" ", "-")),
            "resource_type": r["resource_type"],
            "claim_count": r["claim_count"],
            "total_area_km2": float(r["total_area_km2"]) if r["total_area_km2"] else None,
            "contractor_count": r["contractor_count"],
            "high_risk_count": r["high_risk_count"],
        }
        for r in rows
    ]
    return Response(content=_json.dumps(result), media_type="application/json")


# Species counts for the two SEO claim-aggregate pages (resource, contractor).
#
# These used to run a live spatial join against biodiversity_hotspots on
# `ST_DWithin(bh.geom::geography, mc.geom::geography, 50000)`. Casting the indexed
# column to geography makes the GIST index on `bh.geom` unusable, so the planner
# fell back to evaluating every one of the 34M rows per claim — estimated cost
# 20.9 BILLION, 30-60+ minutes per request, and crawlers request several at once.
# (The vent join in the same query kept using its index precisely because `hv.geom`
# is not cast — that contrast is what identified the cause.)
#
# `claim_species_cache` already holds the per-claim species rollup, so these read
# it instead. **Two semantic notes before changing anything here:**
#
# * The cache is built at an exact 10 km (`services/species_cache.py`), and 10 km
#   is the project-wide rule for "species near a claim" — it comes from the
#   spacing between claims and protected zones, not from a provider (OBIS ships
#   occurrence points and defines no radius). Reading the cache here therefore
#   also CORRECTED these pages, which had been searching 50 km. Do not widen it
#   back. The vent count beside it stays at 50 km on purpose: you cast a wide net
#   for rare features, a narrow one for common occurrence records (the 10 km
#   rule was set 2026-05-20, tightening the radius from an earlier 55 km).
# * `threatened_count` now counts SPECIES via the cache's purpose-built
#   `is_endangered` flag (`bool_or(iucn IN CR/EN/VU)` per claim+species). The old
#   expression summed 1 per occurrence *record* under a label reading "Threatened
#   Species (CR/EN/VU)". In practice the published figure does not change: no
#   CR/EN/VU species occurs within 1 degree (~110 km) of ANY ISA claim — verified
#   against biodiversity_hotspots, which holds 129 such species, all of them
#   coastal or pelagic while the claims sit on the abyssal plain. Both the old and
#   the new expression therefore return 0; the new one is merely honest about
#   counting species rather than records if that ever ceases to be true.
_SEO_ENV_COUNTS_SQL = """
    SELECT
        (SELECT COUNT(DISTINCT csc.scientific_name)
           FROM mining_contracts mc
           JOIN claim_species_cache csc ON csc.isa_id = mc.isa_id
          WHERE mc.{col} = $1) AS species_count,
        (SELECT COUNT(DISTINCT csc.scientific_name)
           FROM mining_contracts mc
           JOIN claim_species_cache csc ON csc.isa_id = mc.isa_id
          WHERE mc.{col} = $1
            AND csc.is_endangered) AS threatened_count,
        (SELECT COUNT(DISTINCT hv.id)
           FROM mining_contracts mc
           JOIN hydrothermal_vents hv
             ON ST_DWithin(hv.geom, mc.geom::geography, 50000)
          WHERE mc.{col} = $1) AS vent_count
"""

# Fallback used ONLY when claim_species_cache is empty (never populated, or a
# rebuild that failed). Same 10 km definition as services/species_cache.py, run
# live against biodiversity_hotspots — slow, but correct, and far better than
# baking a false "0 deep-sea species" into a bot-facing page for the whole site.
# `species_count == 0` is a legitimate answer for many claims, so it can NOT be
# used to detect a miss; global cache emptiness is the honest signal.
_SEO_ENV_COUNTS_LIVE_SQL = """
    SELECT
        (SELECT COUNT(DISTINCT bh.scientific_name)
           FROM mining_contracts mc
           JOIN biodiversity_hotspots bh
             ON ST_DWithin(bh.geom, mc.geom, 0.12)
            AND ST_DWithin(bh.geom::geography, mc.geom::geography, 10000)
          WHERE mc.{col} = $1) AS species_count,
        (SELECT COUNT(DISTINCT bh.scientific_name)
           FROM mining_contracts mc
           JOIN biodiversity_hotspots bh
             ON ST_DWithin(bh.geom, mc.geom, 0.12)
            AND ST_DWithin(bh.geom::geography, mc.geom::geography, 10000)
          WHERE mc.{col} = $1
            AND bh.iucn_category IN ('CR','EN','VU')) AS threatened_count,
        (SELECT COUNT(DISTINCT hv.id)
           FROM mining_contracts mc
           JOIN hydrothermal_vents hv
             ON ST_DWithin(hv.geom, mc.geom::geography, 50000)
          WHERE mc.{col} = $1) AS vent_count
"""


async def seo_env_counts(conn, col: str, value: str):
    """Species / threatened / vent counts for a resource-type or contractor SEO
    page. Reads the fast claim_species_cache, but falls back to the live spatial
    join when that cache is empty — so a public page never silently reports
    "0 species" just because the cache has not been (re)built yet."""
    cache_populated = await conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM claim_species_cache)"
    )
    sql = _SEO_ENV_COUNTS_SQL if cache_populated else _SEO_ENV_COUNTS_LIVE_SQL
    if not cache_populated:
        log.warning(
            "seo: claim_species_cache empty — falling back to live species join "
            "for %s=%s (run the species-cache rebuild)", col, value,
        )
    return await conn.fetchrow(sql.format(col=col), value)


@router.get("/v1/seo/resource/{slug}", dependencies=[Depends(get_api_key)])
async def seo_resource(slug: str):
    """Full resource type profile for pSEO pages."""
    resource_type = _RESOURCE_BY_SLUG.get(slug)
    if not resource_type:
        raise HTTPException(status_code=404, detail=f"Resource type '{slug}' not found")

    async with db.pool.acquire() as conn:
        stats = await conn.fetchrow("""
            SELECT COUNT(*) AS claim_count,
                   ROUND(SUM(area_km2)::numeric, 0) AS total_area_km2,
                   COUNT(DISTINCT contractor_name) AS contractor_count,
                   SUM(CASE WHEN is_high_risk THEN 1 ELSE 0 END) AS high_risk_count,
                   MIN(act_date) AS earliest_contract,
                   array_agg(DISTINCT contractor_name ORDER BY contractor_name) FILTER (WHERE contractor_name IS NOT NULL) AS contractors
            FROM mining_contracts
            WHERE resource_type = $1
        """, resource_type)

        env = await seo_env_counts(conn, "resource_type", resource_type)

        claims = await conn.fetch("""
            SELECT isa_id, contractor_name, area_km2, act_date::text, expiry_date::text,
                   is_high_risk, jurisdiction_text
            FROM mining_contracts
            WHERE resource_type = $1
            ORDER BY is_high_risk DESC, area_km2 DESC NULLS LAST
            LIMIT 100
        """, resource_type)

    claim_count = stats["claim_count"]
    total_area = float(stats["total_area_km2"]) if stats["total_area_km2"] else None
    contractor_count = stats["contractor_count"]
    species_count = env["species_count"] or 0
    threatened_count = env["threatened_count"] or 0
    vent_count = env["vent_count"] or 0
    contractors = list(stats["contractors"] or [])

    area_str = f"{total_area:,.0f} km²" if total_area else "unknown area"
    title = f"{resource_type} — ISA Deep-Sea Mining | Abyssal Claims"
    description = (
        f"{claim_count} ISA exploration contracts target {resource_type} across {area_str}, "
        f"held by {contractor_count} contractors. "
        f"{species_count:,} deep-sea species and {vent_count:,} hydrothermal vents within 50 km of active concessions."
    )

    import json as _json
    return Response(content=_json.dumps({
        "slug": slug,
        "resource_type": resource_type,
        "claim_count": claim_count,
        "total_area_km2": total_area,
        "contractor_count": contractor_count,
        "high_risk_count": stats["high_risk_count"] or 0,
        "earliest_contract": stats["earliest_contract"] and str(stats["earliest_contract"]),
        "contractors": contractors,
        "species_count": species_count,
        "threatened_count": threatened_count,
        "vent_count": vent_count,
        "claims": [
            {
                "isa_id": r["isa_id"],
                "contractor_name": r["contractor_name"],
                "area_km2": r["area_km2"],
                "act_date": r["act_date"],
                "expiry_date": r["expiry_date"],
                "is_high_risk": r["is_high_risk"],
            }
            for r in claims
        ],
        "meta": {
            "title": title,
            "description": description[:160],
            "canonical_url": f"https://something-rare.com/resource/{slug}",
            "json_ld": {
                "@context": "https://schema.org",
                "@type": "Thing",
                "name": resource_type,
                "description": description,
                "url": f"https://something-rare.com/resource/{slug}",
                "isPartOf": ABYSSAL_DATASET,
            },
        },
    }), media_type="application/json")


def contractor_slug(name: str) -> str:
    """Deterministic URL slug from a contractor name."""
    import re as _re
    s = _re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s[:80]


@router.get("/v1/seo/contractors", dependencies=[Depends(get_api_key)])
async def seo_contractors_list():
    """List all contractors with their slugs — used by sitemap and directory page."""
    async with db.pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT contractor_name,
                   COUNT(*) AS claim_count,
                   ROUND(SUM(area_km2)::numeric, 0) AS total_area_km2,
                   SUM(CASE WHEN is_high_risk THEN 1 ELSE 0 END) AS high_risk_count,
                   array_agg(DISTINCT resource_type ORDER BY resource_type) FILTER (WHERE resource_type IS NOT NULL) AS resource_types,
                   array_agg(DISTINCT region ORDER BY region) FILTER (WHERE region IS NOT NULL) AS regions
            FROM mining_contracts
            WHERE contractor_name IS NOT NULL
            GROUP BY contractor_name
            ORDER BY claim_count DESC
        """)
    import json as _json
    result = [
        {
            "slug": contractor_slug(r["contractor_name"]),
            "contractor_name": r["contractor_name"],
            "claim_count": r["claim_count"],
            "total_area_km2": float(r["total_area_km2"]) if r["total_area_km2"] else None,
            "high_risk_count": r["high_risk_count"],
            "resource_types": list(r["resource_types"] or []),
            "regions": list(r["regions"] or []),
        }
        for r in rows
    ]
    return Response(content=_json.dumps(result), media_type="application/json")


@router.get("/v1/seo/contractor/{slug}", dependencies=[Depends(get_api_key)])
async def seo_contractor(slug: str):
    """Full contractor profile for pSEO pages."""
    async with db.pool.acquire() as conn:
        # Find contractor by matching slug
        all_names = await conn.fetch(
            "SELECT DISTINCT contractor_name FROM mining_contracts WHERE contractor_name IS NOT NULL"
        )
        contractor_name = next(
            (r["contractor_name"] for r in all_names if contractor_slug(r["contractor_name"]) == slug),
            None,
        )
        if not contractor_name:
            raise HTTPException(status_code=404, detail=f"Contractor '{slug}' not found")

        # Aggregate stats
        stats = await conn.fetchrow("""
            SELECT COUNT(*) AS claim_count,
                   ROUND(SUM(area_km2)::numeric, 0) AS total_area_km2,
                   SUM(CASE WHEN is_high_risk THEN 1 ELSE 0 END) AS high_risk_count,
                   array_agg(DISTINCT resource_type ORDER BY resource_type) FILTER (WHERE resource_type IS NOT NULL) AS resource_types,
                   array_agg(DISTINCT region ORDER BY region) FILTER (WHERE region IS NOT NULL) AS regions,
                   MIN(act_date) AS earliest_contract,
                   MAX(expiry_date) AS latest_expiry
            FROM mining_contracts
            WHERE contractor_name = $1
        """, contractor_name)

        # Species and vent counts across all claims
        env = await seo_env_counts(conn, "contractor_name", contractor_name)

        # Individual claims list
        claims = await conn.fetch("""
            SELECT isa_id, resource_type, area_km2, act_date::text, expiry_date::text,
                   is_high_risk, region, jurisdiction_text
            FROM mining_contracts
            WHERE contractor_name = $1
            ORDER BY is_high_risk DESC, area_km2 DESC NULLS LAST
        """, contractor_name)

    claim_count = stats["claim_count"]
    total_area = float(stats["total_area_km2"]) if stats["total_area_km2"] else None
    high_risk = stats["high_risk_count"] or 0
    resource_types = list(stats["resource_types"] or [])
    species_count = env["species_count"] or 0
    threatened_count = env["threatened_count"] or 0
    vent_count = env["vent_count"] or 0

    resource_str = " and ".join(resource_types) if resource_types else "deep-sea minerals"
    area_str = f"{total_area:,.0f} km²" if total_area else "unknown area"

    title = f"{contractor_name} — ISA Deep-Sea Mining Profile | Abyssal Claims"
    description = (
        f"{contractor_name} holds {claim_count} ISA deep-sea mining concession{'s' if claim_count != 1 else ''} "
        f"covering {area_str}, targeting {resource_str}. "
        f"{species_count} deep-sea species and {vent_count} hydrothermal vents within concession areas."
    )

    import json as _json
    return Response(content=_json.dumps({
        "slug": slug,
        "contractor_name": contractor_name,
        "claim_count": claim_count,
        "total_area_km2": total_area,
        "high_risk_count": high_risk,
        "resource_types": resource_types,
        "regions": list(stats["regions"] or []),
        "earliest_contract": stats["earliest_contract"] and str(stats["earliest_contract"]),
        "latest_expiry": stats["latest_expiry"] and str(stats["latest_expiry"]),
        "species_count": species_count,
        "threatened_count": threatened_count,
        "vent_count": vent_count,
        "claims": [
            {
                "isa_id": r["isa_id"],
                "resource_type": r["resource_type"],
                "area_km2": r["area_km2"],
                "act_date": r["act_date"],
                "expiry_date": r["expiry_date"],
                "is_high_risk": r["is_high_risk"],
                "region": r["region"],
            }
            for r in claims
        ],
        "meta": {
            "title": title,
            "description": description[:160],
            "canonical_url": f"https://something-rare.com/contractor/{slug}",
            "json_ld": {
                "@context": "https://schema.org",
                "@type": "Organization",
                "name": contractor_name,
                "description": description,
                "url": f"https://something-rare.com/contractor/{slug}",
                "knowsAbout": resource_types,
            },
        },
    }), media_type="application/json")


@router.get("/v1/seo/widget/{entity_type}/{entity_id}", response_model=WidgetData, dependencies=[Depends(get_api_key)])
async def seo_widget(entity_type: str, entity_id: str):
    if entity_type == "concession":
        data = await seo_concession(entity_id)
        risk_score = min(1.0, (
            data.vent_conflicts * 0.3
            + data.nearby_species * 0.005
            + (1 if data.is_high_risk else 0) * 0.3
        ))
        return WidgetData(
            entity_type="concession",
            entity_id=entity_id,
            name=data.contractor_name,
            risk_score=round(risk_score, 2),
            summary=data.meta.description,
            canonical_url=data.meta.canonical_url,
            data={
                "isa_id": data.isa_id,
                "resource_type": data.resource_type,
                "area_km2": data.area_km2,
                "vent_conflicts": data.vent_conflicts,
                "nearby_species": data.nearby_species,
                "is_high_risk": data.is_high_risk,
                "nearby_argo_floats": data.nearby_argo_floats,
                "nearby_onc_stations": data.nearby_onc_stations,
                "nearby_oceansites_moorings": data.nearby_oceansites_moorings,
            },
        )
    raise HTTPException(status_code=400, detail=f"Widget type '{entity_type}' not supported yet")
