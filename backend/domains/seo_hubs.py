# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Hub (index) pages — the crawl path from the home page to 40,300 entity pages.

## Why this module exists

Measured on live production 2026-08-17 with a Googlebot UA: the home page served
crawlers **zero** `<a>` elements, and every entity page carried exactly one link,
back to `/`. For a crawler the site was a star with a dead centre — 40,300 URLs
asserted by sitemap and **not one** corroborated by a link. A sitemap says a URL
*exists*; a link says it *matters*. With only the former, Google had nothing to
rank its crawl queue by, and 29,241 URLs sat in "Discovered – currently not
indexed" (GSC, 2026-08-17): found, not judged worth fetching.

`/seamount`, `/concession`, `/vent` and `/layer` all returned **404** — Google
asks for the parent path when it sees `/seamount/12345`, and got nothing.

## What a hub is here

One registry entry per entity family, rendered by ONE express route
(`frontend/server.js`) against ONE endpoint. Nine families, nine near-identical
list pages: a registry is the same amount of code as three hand-written ones and
cannot drift between them.

## Two things that are deliberate, not oversights

**Every item carries a `meta` line, not just a link.** The temptation is to emit
500 bare `Seamount #N` anchors. That is the *same* defect the 2026-08-17 CTR work
just removed from the seamount pages themselves — a page whose only varying
content is a digit. `row_to_item` therefore derives a real descriptor (ocean
basin from coordinates, contractor name, depth) exactly as the per-entity
snippets do, reusing `ocean_basin.basin_for`, which **abstains** rather than
guess.

**Pagination is honest.** Page N is self-canonical and links to its siblings.
Canonicalising page 2..N to page 1 would hide the very links this module exists
to expose — see the DoD in `docs/seo-discovered-not-indexed-2026-08-17.md`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable

from fastapi import Depends, HTTPException, Query

import db
import ocean_basin
from auth import get_api_key
from fastapi import APIRouter

from domains.seo import LAYER_PAGE_IDS

router = APIRouter()

SITE = "https://something-rare.com"


def _num(v: float | int | None, unit: str = "", digits: int = 0) -> str | None:
    """Format a measurement, or return None so the caller can drop the clause.

    Returning None rather than "—" is load-bearing: `_meta` joins only the
    clauses that exist, so a row with no height renders a shorter line instead
    of a line full of placeholders.
    """
    if v is None:
        return None
    try:
        return f"{float(v):,.{digits}f}{unit}"
    except (TypeError, ValueError):
        return None


def _meta(*clauses: str | None) -> str:
    return " · ".join(c for c in clauses if c)


def _u(segment) -> str:
    """Percent-encode one path segment, keeping ':' literal.

    Ids in this corpus are not all URL-safe: `report_cache` holds
    `chess:10°N - EPR` (a degree sign and two spaces). But `safe=':'` is not
    cosmetic — `arctic_river_stations.station_id` is `arcticgro:kolyma`, and the
    sitemap emits it with a literal colon (`encodeLoc` runs `new URL(loc).href`,
    which leaves ':' alone). Encoding it here would make the hub link and the
    sitemap two different URLs for one page, i.e. manufacture the duplicate
    problem this work exists to remove.
    """
    from urllib.parse import quote
    return quote(str(segment), safe=":")


@dataclass(frozen=True)
class Hub:
    """One entity family's index.

    `kind` is the URL segment of the CHILD pages (`/seamount/12345`), so the hub
    lives at `/{kind}` — which is exactly the parent path Google probes.
    """

    kind: str
    title: str
    heading: str
    intro: str
    per_page: int
    count_sql: str
    rows_sql: str            # must end with LIMIT $1 OFFSET $2
    row_to_item: Callable[[Any], dict]
    priority: str = "0.6"


# ── row → item builders ──────────────────────────────────────────────────────
# Each returns {url, label, meta}. `url` is absolute: these pages are also read
# by the sitemap builder and by bots that never resolve relative hrefs the way a
# browser does.

def _seamount_item(r) -> dict:
    basin = ocean_basin.basin_for(r["latitude"], r["longitude"])
    return {
        "url": f"{SITE}/seamount/{_u(r['peak_id'])}",
        "label": f"Seamount #{r['peak_id']}",
        "meta": _meta(basin, _num(r["height_m"], " m tall")),
    }


def _concession_item(r) -> dict:
    return {
        "url": f"{SITE}/concession/{_u(r['isa_id'])}",
        "label": r["isa_id"],
        "meta": _meta(r["contractor_name"], r["resource_type"], _num(r["area_km2"], " km²")),
    }


def _vent_item(r) -> dict:
    return {
        "url": f"{SITE}/vent/{_u(r['id'])}",
        "label": r["name"] or f"Vent #{r['id']}",
        "meta": _meta(r["region"] or r["ocean"], _num(r["depth_m"], " m depth")),
    }


def _onc_item(r) -> dict:
    return {
        "url": f"{SITE}/onc/{_u(r['location_code'])}",
        "label": r["name"] or r["location_code"],
        "meta": _meta(r["location_code"], _num(r["depth_m"], " m depth")),
    }


def _oceansites_item(r) -> dict:
    return {
        "url": f"{SITE}/oceansites/{_u(r['ref'])}",
        "label": r["name"] or r["ref"],
        "meta": _meta(r["network"], r["status"]),
    }


def _river_item(r) -> dict:
    return {
        "url": f"{SITE}/river/{_u(r['station_id'])}",
        "label": r["river_name"] or r["station_id"],
        "meta": _meta(r["site_label"]),
    }


def _report_item(r) -> dict:
    """`report_cache` holds THREE kinds of report under one primary key.

    `claim:` is an ISA-concession dossier served at /claim-report/{isa_id};
    `chess:` is a ChESS vent-locality report; everything else is an Argo float.
    `seo_sitemap_core` only ever split off `claim:`, so the seven `chess:` rows
    have always been advertised as `/report/chess:Snake Pit` — which *renders*,
    but titles a hydrothermal locality "Impact Report — Float chess:Snake Pit".
    The URL is left alone deliberately: it is the one that works and the one
    already in the sitemap, and inventing a prettier link that 404s would be
    strictly worse. Only the label is corrected here. (/chess-report/{locality}
    exists but serves the SPA shell — a separate defect, recorded in the report.)

    Two of those ids carry a degree sign and spaces (`chess:10°N - EPR`), which
    is why every URL here goes through `_u`.
    """
    pid = r["platform_id"]
    if pid.startswith("claim:"):
        isa_id = pid[len("claim:"):]
        return {"url": f"{SITE}/claim-report/{_u(isa_id)}", "label": isa_id,
                "meta": "ISA concession dossier"}
    if pid.startswith("chess:"):
        locality = pid[len("chess:"):]
        return {"url": f"{SITE}/report/{_u(pid)}", "label": locality,
                "meta": "ChESS vent-locality report"}
    return {"url": f"{SITE}/report/{_u(pid)}", "label": f"Argo float {pid}",
            "meta": "Measurement report"}


HUBS: dict[str, Hub] = {
    "seamount": Hub(
        kind="seamount",
        title="Seamounts — global index | Abyssal Claims",
        heading="Seamounts",
        intro=(
            "Every seamount in the Yesson et al. (2011) global morphology-derived census, "
            "with its ocean basin and height above the surrounding seafloor. Most are unnamed: "
            "the census identifies features from bathymetry, not from a gazetteer."
        ),
        per_page=500,
        count_sql="SELECT COUNT(*) FROM seamounts",
        rows_sql=(
            "SELECT peak_id, height_m, latitude, longitude FROM seamounts "
            "ORDER BY peak_id LIMIT $1 OFFSET $2"
        ),
        row_to_item=_seamount_item,
        priority="0.5",
    ),
    "concession": Hub(
        kind="concession",
        title="ISA mining concessions — full index | Abyssal Claims",
        heading="ISA mining concessions",
        intro=(
            "Every exploration area in the International Seabed Authority register, "
            "with the contractor holding it and the mineral resource it targets."
        ),
        per_page=250,
        count_sql="SELECT COUNT(*) FROM mining_contracts",
        rows_sql=(
            "SELECT isa_id, contractor_name, resource_type, area_km2 FROM mining_contracts "
            "ORDER BY isa_id LIMIT $1 OFFSET $2"
        ),
        row_to_item=_concession_item,
        priority="0.8",
    ),
    "vent": Hub(
        kind="vent",
        title="Hydrothermal vents — global index | Abyssal Claims",
        heading="Hydrothermal vent fields",
        intro=(
            "Named hydrothermal vent fields from the InterRidge global database, "
            "with their region and water depth."
        ),
        per_page=250,
        count_sql="SELECT COUNT(*) FROM hydrothermal_vents",
        rows_sql=(
            "SELECT id, name, region, ocean, depth_m FROM hydrothermal_vents "
            "ORDER BY id LIMIT $1 OFFSET $2"
        ),
        row_to_item=_vent_item,
        priority="0.6",
    ),
    "onc": Hub(
        kind="onc",
        title="Ocean Networks Canada observatories | Abyssal Claims",
        heading="Ocean Networks Canada observatories",
        intro="Cabled observatory locations on the NEPTUNE and VENUS arrays off British Columbia.",
        per_page=250,
        # Gated on latest_sensors IS NOT NULL — same marker used by
        # seo_sitemap_core() and nearby_onc_stations. Most of onc_locations
        # (junction boxes, power supplies, cameras) has nothing to show on a
        # hub row; only stations with real sensor data get listed here.
        count_sql="SELECT COUNT(*) FROM onc_locations WHERE latest_sensors IS NOT NULL",
        rows_sql=(
            "SELECT location_code, name, depth_m FROM onc_locations "
            "WHERE latest_sensors IS NOT NULL "
            "ORDER BY location_code LIMIT $1 OFFSET $2"
        ),
        row_to_item=_onc_item,
        priority="0.5",
    ),
    "oceansites": Hub(
        kind="oceansites",
        title="OceanSITES moorings | Abyssal Claims",
        heading="OceanSITES moorings",
        intro="Long-term open-ocean reference moorings in the OceanSITES network.",
        per_page=250,
        # 2026-09-08: widened to every OceanOPS status (~5,795 rows). Gated on
        # latest_obs IS NOT NULL, same marker as the "onc" hub above — only
        # platforms with an actual rendered data page are listed here.
        count_sql="SELECT COUNT(*) FROM oceansites_stations WHERE latest_obs IS NOT NULL",
        rows_sql=(
            "SELECT ref, name, network, status FROM oceansites_stations "
            "WHERE latest_obs IS NOT NULL "
            "ORDER BY ref LIMIT $1 OFFSET $2"
        ),
        row_to_item=_oceansites_item,
        priority="0.5",
    ),
    "river": Hub(
        kind="river",
        title="Arctic river monitoring stations | Abyssal Claims",
        heading="Arctic river monitoring stations",
        intro=(
            "ArcticGRO stations at the mouths of the six great Arctic rivers — "
            "the land-to-ocean input of freshwater, carbon and nutrients."
        ),
        per_page=250,
        count_sql="SELECT COUNT(*) FROM arctic_river_stations WHERE source = 'arcticgro'",
        rows_sql=(
            "SELECT station_id, river_name, site_label FROM arctic_river_stations "
            "WHERE source = 'arcticgro' ORDER BY station_id LIMIT $1 OFFSET $2"
        ),
        row_to_item=_river_item,
        priority="0.6",
    ),
    "report": Hub(
        kind="report",
        title="Measurement reports | Abyssal Claims",
        heading="Measurement reports",
        intro=(
            "Generated dossiers: per-float Argo measurement reports and per-concession "
            "ISA claim dossiers."
        ),
        per_page=250,
        count_sql="SELECT COUNT(*) FROM report_cache",
        rows_sql=(
            "SELECT platform_id FROM report_cache ORDER BY generated_at DESC LIMIT $1 OFFSET $2"
        ),
        row_to_item=_report_item,
        priority="0.7",
    ),
}

# ── Hubs with no SQL behind them ─────────────────────────────────────────────
# `/layer` and `/resource` list a fixed set of pages, not table rows. They still
# need to exist: both are parent paths Google probes, and /layer 404'd.

_RESOURCE_ITEMS = [
    ("polymetallic-nodules", "Polymetallic manganese nodules",
     "Abyssal plain nodule fields — the largest class of ISA exploration contract"),
    ("cobalt-rich-ferromanganese-crusts", "Cobalt-rich ferromanganese crusts",
     "Seamount flank crusts"),
    ("polymetallic-sulphides", "Polymetallic sulphides",
     "Hydrothermally formed massive sulphide deposits"),
]


def _static_items(kind: str) -> list[dict]:
    if kind == "layer":
        return [
            {"url": f"{SITE}/layer/{lid}", "label": lid.replace("-", " ").capitalize(),
             "meta": ""}
            for lid in LAYER_PAGE_IDS
        ]
    return [
        {"url": f"{SITE}/resource/{slug}", "label": label, "meta": meta}
        for slug, label, meta in _RESOURCE_ITEMS
    ]


_STATIC_HUBS: dict[str, Hub] = {
    "layer": Hub(
        kind="layer",
        title="Data layers | Abyssal Claims",
        heading="Data layers",
        intro="Every mapped data layer, its source, and what it can and cannot show.",
        per_page=1000,
        count_sql="",
        rows_sql="",
        row_to_item=lambda r: r,
        priority="0.7",
    ),
    "resource": Hub(
        kind="resource",
        title="Seabed mineral resources | Abyssal Claims",
        heading="Seabed mineral resources",
        intro="The three mineral resource classes ISA issues exploration contracts for.",
        per_page=1000,
        count_sql="",
        rows_sql="",
        row_to_item=lambda r: r,
        priority="0.8",
    ),
}

ALL_HUBS: dict[str, Hub] = {**HUBS, **_STATIC_HUBS}


def page_count(total: int, per_page: int) -> int:
    """Always at least 1 — an empty hub still has a page 1 that says so.

    Returning 0 would make `/seamount` a 404 the moment a table is empty, which
    is precisely the failure this module exists to remove.
    """
    return max(1, math.ceil(total / per_page)) if per_page > 0 else 1


@router.get("/v1/seo/hubs", dependencies=[Depends(get_api_key)])
async def seo_hub_index():
    """Every hub with its live total — the home page's link list, and the sitemap's.

    One call, so the bot-facing home page costs one round trip rather than nine.
    """
    out = []
    async with db.pool.acquire() as conn:
        for hub in ALL_HUBS.values():
            if hub.count_sql:
                total = await conn.fetchval(hub.count_sql)
            else:
                total = len(_static_items(hub.kind))
            out.append({
                "kind": hub.kind,
                "url": f"{SITE}/{hub.kind}",
                "heading": hub.heading,
                "intro": hub.intro,
                "total": total,
                "pages": page_count(total, hub.per_page),
                "priority": hub.priority,
            })
    return {"hubs": out}


@router.get("/v1/seo/hub/{kind}", dependencies=[Depends(get_api_key)])
async def seo_hub(kind: str, page: int = Query(1, ge=1)):
    hub = ALL_HUBS.get(kind)
    if hub is None:
        raise HTTPException(status_code=404, detail=f"No hub for {kind!r}")

    if hub.count_sql:
        async with db.pool.acquire() as conn:
            total = await conn.fetchval(hub.count_sql)
            pages = page_count(total, hub.per_page)
            if page > pages:
                raise HTTPException(status_code=404, detail=f"Page {page} of {pages}")
            rows = await conn.fetch(hub.rows_sql, hub.per_page, (page - 1) * hub.per_page)
        items = [hub.row_to_item(r) for r in rows]
    else:
        all_items = _static_items(hub.kind)
        total = len(all_items)
        pages = page_count(total, hub.per_page)
        if page > pages:
            raise HTTPException(status_code=404, detail=f"Page {page} of {pages}")
        items = all_items[(page - 1) * hub.per_page: page * hub.per_page]

    return {
        "kind": hub.kind,
        "title": hub.title,
        "heading": hub.heading,
        "intro": hub.intro,
        "page": page,
        "pages": pages,
        "total": total,
        "per_page": hub.per_page,
        "items": items,
    }
