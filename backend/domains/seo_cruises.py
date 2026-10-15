# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Research cruise pages — /cruise/{EXPOCODE}, the /cruises index, sitemap-cruises.xml.

One page per EXPOCODE in glodap_cruises ∪ socat_cruises (spec docs/specs/2026-10-11-cruise-pages-and-point-export-
design.md). ⛔ Missing and broken never share a path: an unknown key is 404; an empty table, a DB error or a payload
we cannot build is 503 + Retry-After (frontend/seo/upstream-fetch.js turns that into the page's 503).
⛔ The redirect target is always an EXACT stored spelling, so the follow-up request is an exact hit — no loop.
"""
from __future__ import annotations

import logging
import math
import re
from datetime import timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException

import db
from auth import get_api_key
from domains import glodap_points as G
from domains import socat_points as S
from domains.seo import _DESCRIPTION_BUDGET, _TITLE_BUDGET, _fit
from ingestion.glodap_bottles_rules import BOTTLE_UNITS, GOOD_FLAG, VARIABLES
from services import cruise_sketch as sketch

log = logging.getLogger(__name__)
router = APIRouter()

SITE = "https://something-rare.com"
CRUISE_KEY_RE = re.compile(r"[A-Za-z0-9_-]{4,32}", re.ASCII)
CRUISE_KEY_SQL_RE = "^[A-Za-z0-9_-]{4,32}$"
RETRY_HEADERS = {"Retry-After": "300", "Cache-Control": "no-store"}
STATEMENT_TIMEOUT = "5s"
SOCAT_TRACK_MAX_VERTICES = 3000
LICENCE_URL = "https://creativecommons.org/licenses/by/4.0/"
_PI_SPLIT = re.compile(r"\s*;\s*|\s+:\s+")   # measured: 3,795 rows use ";", 78 use " : " ("Berghoff, C. : Lutz, V.")

# isPartOf targets: named constants, never inline literals (the defect test_seo_dataset_node.py guards in seo.py).
GLODAP_V3_DATASET = {
    "@type": "Dataset", "name": "GLODAPv3 (2026) — Global Ocean Data Analysis Project, version 3",
    "description": ("Quality-controlled interior-ocean bottle data (carbon, oxygen, nutrients, temperature, salinity) "
                    "from research cruises, NCEI Accession 0315582."),
    "url": G.SOURCE_URL, "identifier": G.SOURCE_URL, "license": LICENCE_URL,
}
SOCAT_V2026_DATASET = {
    "@type": "Dataset", "name": "SOCAT v2026 — Surface Ocean CO₂ Atlas",
    "description": ("Quality-controlled surface-ocean fCO2 observations from research vessels, ships of opportunity, "
                    "moorings and drifters, NCEI Accession 0315110."),
    "url": S.SOURCE_URL, "identifier": S.SOURCE_URL, "license": LICENCE_URL,
}

VARIABLE_LABELS = {
    "temperature": "Temperature", "salinity": "Salinity", "oxygen": "Dissolved oxygen", "nitrate": "Nitrate",
    "silicate": "Silicate", "phosphate": "Phosphate", "tco2": "Dissolved inorganic carbon (TCO₂)",
    "talk": "Total alkalinity", "phts25p0": "pH, total scale, 25 °C and 0 dbar",
    "phtsinsitutp": "pH, total scale, in situ", "fco2": "fCO₂",
}
# A–D copied from frontend/public/locales/en/panels.json socatObs.qcMeaning; E from the NCEI 0315110 sentence quoted
# in SocatObsPanel.tsx. ⛔ Do not paraphrase.
SOCAT_QC_MEANING = {
    "A": "estimated accuracy better than 2 µatm", "B": "estimated accuracy better than 2 µatm",
    "C": "estimated accuracy better than 5 µatm", "D": "estimated accuracy better than 5 µatm",
    "E": "estimated accuracy better than 10 µatm (stored, not drawn on the map)",
}

READY_SQL = "SELECT EXISTS (SELECT 1 FROM glodap_cruises) AND EXISTS (SELECT 1 FROM socat_cruises)"

# A GLODAP cruise row with no stored cast has no page (same rule as the sitemap's _UNION): missing → 404, not 503.
_RESOLVE_SQL = ("SELECT expocode FROM glodap_cruises g WHERE upper(expocode) = upper($1) "
                "AND EXISTS (SELECT 1 FROM glodap_casts c WHERE c.expocode = g.expocode) "
                "UNION SELECT expocode FROM socat_cruises WHERE upper(expocode) = upper($1)")

_HAS_GOOD = ", ".join(f"bool_or({GOOD_FLAG} = ANY(c.{v}_f)) AS has_{v}" for v in VARIABLES)
GLODAP_SQL = f"""
SELECT cr.expocode, cr.platform_code, cr.ship_name, cr.doi, cr.first_date, cr.last_date, cr.n_casts,
       count(*) AS n_casts_stored, min(d.lo) AS depth_min_m, max(d.hi) AS depth_max_m, {_HAS_GOOD}
FROM glodap_cruises cr
JOIN glodap_casts c ON c.expocode = cr.expocode
CROSS JOIN LATERAL (SELECT min(x) AS lo, max(x) AS hi FROM unnest(c.depth_m) AS x) d
WHERE cr.expocode = $1
GROUP BY cr.expocode"""
GLODAP_POINTS_SQL = ("SELECT lon, lat FROM glodap_casts WHERE expocode = $1 "
                     "ORDER BY obs_date, station, cast_no NULLS LAST")
SOCAT_SQL = "SELECT * FROM socat_cruises WHERE expocode = $1"
# Every k-th observation by its cruise ordinal (ord0 + i - 1), k = ceil(n_obs / SOCAT_TRACK_MAX_VERTICES); uses the
# (expocode, ord0) index. Rejected rows are positions too, so they stay in the sketch.
SOCAT_TRACK_SQL = """
SELECT u.lon, u.lat
FROM socat_segments s
CROSS JOIN LATERAL unnest(s.lon, s.lat) WITH ORDINALITY AS u(lon, lat, i)
WHERE s.expocode = $1 AND (s.ord0 + u.i - 1) % $2 = 0
ORDER BY s.ord0, u.i"""


def cruise_url(expocode: str) -> str:
    return f"{SITE}/cruise/{quote(expocode, safe='')}"


def _doi_url(doi: str | None) -> str | None:
    """Same rule as sourceDoiUrl()/doiUrl() in the two panels."""
    d = (doi or "").strip()
    if not d or re.fullmatch(r"n/?a", d, re.I):
        return None
    if re.match(r"https?://", d, re.I):
        return d
    return "https://doi.org/" + re.sub(r"^doi:\s*", "", d, flags=re.I)


def _http_url(ref: str | None) -> str | None:
    r = (ref or "").strip()
    return r if re.match(r"https?://", r, re.I) else None


async def resolve_expocode(conn, requested: str) -> str | None:
    spellings = sorted({r["expocode"] for r in await conn.fetch(_RESOLVE_SQL, requested)})
    if requested in spellings:
        return requested
    if len(spellings) == 1:
        return spellings[0]
    if spellings:
        log.warning("cruise key %r matches %d stored spellings case-insensitively: %s", requested, len(spellings),
                    spellings)
    return None


async def _rows(conn, expocode: str):
    g = await conn.fetchrow(GLODAP_SQL, expocode)
    g_pts = [(float(r["lon"]), float(r["lat"])) for r in await conn.fetch(GLODAP_POINTS_SQL, expocode)] if g else []
    s = await conn.fetchrow(SOCAT_SQL, expocode)
    track: list[tuple[float, float]] = []
    if s:
        step = max(1, math.ceil(s["n_obs"] / SOCAT_TRACK_MAX_VERTICES))
        track = [(float(r["lon"]), float(r["lat"])) for r in await conn.fetch(SOCAT_TRACK_SQL, expocode, step)]
    return g, g_pts, s, track


def _utc_date(ts):
    return ts.astimezone(timezone.utc).date()


def build_payload(expocode: str, g, g_pts, s, track) -> dict:
    points = g_pts + track
    frame = sketch.frame_for(points)
    region = sketch.region_label(frame, points)
    name = (g["ship_name"] if g else None) or (s["platform_name"] if s else None)
    firsts = [d for d in ((g["first_date"] if g else None), (_utc_date(s["first_time"]) if s else None)) if d]
    lasts = [d for d in ((g["last_date"] if g else None), (_utc_date(s["last_time"]) if s else None)) if d]
    first, last = min(firsts), max(lasts)
    datasets = [d for d, on in (("GLODAPv3", g is not None), ("SOCAT v2026", s is not None)) if on]
    pis = [p for p in _PI_SPLIT.split(s["pis"] or "") if p] if s else []
    n_drawn = s["n_obs"] - s["n_rejected"] if s else 0

    glodap = None
    if g:
        glodap = {"ship_name": g["ship_name"], "platform_code": g["platform_code"], "doi": g["doi"],
                  "doi_url": _doi_url(g["doi"]), "first_date": g["first_date"], "last_date": g["last_date"],
                  # rows actually stored in glodap_casts (what the map can show), not glodap_cruises.n_casts
                  "n_casts": g["n_casts_stored"], "depth_min_m": g["depth_min_m"], "depth_max_m": g["depth_max_m"],
                  "variables": [{"key": v, "label": VARIABLE_LABELS[v], "units": BOTTLE_UNITS[v]}
                                for v in VARIABLES if g[f"has_{v}"]]}
    socat = None
    if s:
        socat = {"platform_name": s["platform_name"], "pis": pis, "qc_flag": s["qc_flag"],
                 "qc_meaning": SOCAT_QC_MEANING.get(s["qc_flag"]), "version": s["version"],
                 "dataset_name": s["dataset_name"], "source_doi": s["source_doi"],
                 "source_doi_url": _doi_url(s["source_doi"]), "source_reference": s["source_reference"],
                 "accession_url": _http_url(s["source_reference"]),
                 "first_time": s["first_time"].astimezone(timezone.utc).isoformat(),
                 "last_time": s["last_time"].astimezone(timezone.utc).isoformat(),
                 "n_obs": s["n_obs"], "n_drawn": n_drawn, "n_segments": s["n_segments"]}

    span = str(first.year) if first.year == last.year else f"{first.year}–{last.year}"
    # name before span: _fit drops from the end, and the ship is what makes the title recognisable
    title = _fit(f"Cruise {expocode} — ", [c for c in (name, span) if c], " | Abyssal Claims", _TITLE_BUDGET)
    clauses = [f"{first} to {last}", region]
    if glodap:
        clauses.append(f"{glodap['n_casts']:,} GLODAPv3 bottle casts")
    if socat:
        clauses.append(f"{socat['n_obs']:,} SOCAT v2026 fCO₂ observations")
    lead = f"{name} cruise {expocode}: " if name else f"Research cruise {expocode}: "
    description = _fit(lead, clauses, ".", _DESCRIPTION_BUDGET, sep="; ")
    long_description = (f"{lead}{'; '.join(clauses)}. Data from "
                        f"{' and '.join(datasets)}, passed through unmodified from the published datasets.")

    b = frame.bbox()
    dois = [d for d in ((glodap or {}).get("doi_url"), (socat or {}).get("source_doi_url")) if d]
    variables = [v["label"] for v in (glodap or {}).get("variables", [])]
    if socat:
        variables += ["fCO₂ (SOCAT recomputed, fCO2rec)", "Sea surface temperature", "Salinity"]
    canonical = cruise_url(expocode)
    json_ld = {
        "@context": "https://schema.org", "@type": "Dataset",
        "name": f"Cruise {expocode}" + (f" — {name}" if name else ""),
        "description": long_description, "url": canonical,
        "identifier": [expocode, *dois],
        "spatialCoverage": {"@type": "Place", "geo": {"@type": "GeoShape",
                            "box": f"{b['south']} {b['west']} {b['north']} {b['east']}"}},
        "temporalCoverage": f"{first}/{last}",
        "license": LICENCE_URL, "isAccessibleForFree": True,
        "isPartOf": [d for d, on in ((GLODAP_V3_DATASET, glodap), (SOCAT_V2026_DATASET, socat)) if on],
        "variableMeasured": list(dict.fromkeys(variables)),
    }
    if pis:
        json_ld["creator"] = [{"@type": "Person", "name": p} for p in pis]

    if glodap:
        map_state = {"layers": ["ocean-carbon", "glodap-points"], "display": {"carbonDisplayMode": "points"}}
    else:
        map_state = {"layers": ["ocean-co2-surface", "socat-points"], "display": {"co2DisplayMode": "points"}}
    map_state["camera"] = sketch.camera(frame)
    alt = f"Track of cruise {expocode}" + (f" ({name})" if name else "") + f" — {region}"
    return {
        "expocode": expocode,
        "meta": {"title": title, "description": description, "canonical_url": canonical, "json_ld": json_ld},
        "header": {"name": name, "first_date": first, "last_date": last, "region": region, "datasets": datasets},
        "bbox": b, "sketch_svg": sketch.render_svg(frame, g_pts, track, alt), "sketch_alt": alt,
        "glodap": glodap, "socat": socat,
        "citations": {"glodap": (list(G.CITATIONS[:2]) + ([G.CITATIONS[2]] if glodap and glodap["ship_name"] else []))
                      if glodap else None,
                      "socat": list(S.CITATIONS) if socat else None,
                      "socat_acknowledgement": S.ACKNOWLEDGEMENT if socat else None,
                      "licence": "CC BY 4.0"},
        "map": map_state,
    }


@router.get("/v1/seo/cruise/{expocode}", dependencies=[Depends(get_api_key)])
async def seo_cruise(expocode: str):
    if not CRUISE_KEY_RE.fullmatch(expocode):
        raise HTTPException(404, "not a cruise key")
    try:
        async with db.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'")
                if not await conn.fetchval(READY_SQL):
                    raise HTTPException(503, "cruise tables not loaded yet", headers=RETRY_HEADERS)
                stored = await resolve_expocode(conn, expocode)
                if stored is None:
                    raise HTTPException(404, f"cruise {expocode} not found")
                if stored != expocode:
                    return {"redirect_to": stored}
                g, g_pts, s, track = await _rows(conn, stored)
        if g is None and s is None:
            raise RuntimeError(f"{stored} resolved but neither table returned a row")
        return build_payload(stored, g, g_pts, s, track)
    except HTTPException:
        raise
    except Exception:
        log.exception("seo cruise %s", expocode)
        raise HTTPException(503, "cruise page temporarily unavailable", headers=RETRY_HEADERS)


# ── /cruises index and sitemap ───────────────────────────────────────────────────────────────────────────────
# A glodap_cruises row with no cast is not listed: its page would answer 503 for good (seo_cruise needs a cast or a
# SOCAT row), and a listed URL that never resolves is worse than a missing one. Listing and page share this rule.
_UNION = """
  SELECT expocode, ship_name AS ship, first_date AS d0, last_date AS d1, true AS g, false AS s
  FROM glodap_cruises gc WHERE EXISTS (SELECT 1 FROM glodap_casts c WHERE c.expocode = gc.expocode)
  UNION ALL
  SELECT expocode, platform_name, (first_time AT TIME ZONE 'UTC')::date, (last_time AT TIME ZONE 'UTC')::date,
         false, true FROM socat_cruises"""
# GROUP BY expocode = one row per cruise: the 290 shared cruises appear once.
CRUISES_COUNT_SQL = (f"SELECT count(DISTINCT expocode) FROM ({_UNION}) x "
                     f"WHERE expocode ~ '{CRUISE_KEY_SQL_RE}'")
CRUISES_ROWS_SQL = f"""
WITH u AS (
  SELECT expocode, coalesce(max(ship) FILTER (WHERE g), max(ship) FILTER (WHERE s)) AS ship,
         min(d0) AS first_date, max(d1) AS last_date, bool_or(g) AS in_glodap, bool_or(s) AS in_socat
  FROM ({_UNION}) x WHERE expocode ~ '{CRUISE_KEY_SQL_RE}' GROUP BY expocode)
SELECT * FROM u ORDER BY first_date DESC NULLS LAST, expocode LIMIT $1 OFFSET $2"""
SITEMAP_SQL = f"""
SELECT expocode, bool_or(g) AS in_glodap, bool_or(s) AS in_socat
FROM ({_UNION}) x WHERE expocode ~ '{CRUISE_KEY_SQL_RE}' GROUP BY expocode ORDER BY expocode"""
_LOADED_AT_SQL = ("SELECT (SELECT loaded_at FROM glodap_bottle_source WHERE id = 1) AS g, "
                  "(SELECT loaded_at FROM socat_points_source WHERE id = 1) AS s")


def cruise_hub_item(r) -> dict:
    badges = " + ".join(b for b, on in (("GLODAPv3", r["in_glodap"]), ("SOCAT v2026", r["in_socat"])) if on)
    dates = (str(r["first_date"]) if r["first_date"] == r["last_date"]
             else f"{r['first_date']} → {r['last_date']}")
    return {"url": cruise_url(r["expocode"]), "label": r["expocode"],
            "meta": " · ".join(c for c in (r["ship"], dates, badges) if c)}


@router.get("/v1/seo/sitemap/cruises", dependencies=[Depends(get_api_key)])
async def seo_sitemap_cruises():
    """⛔ Never an empty list: not loaded / DB error / zero rows are all 503 (server.js answers 503 + Retry-After)."""
    try:
        async with db.pool.acquire() as conn:
            if not await conn.fetchval(READY_SQL):
                raise HTTPException(503, "cruise tables not loaded yet", headers=RETRY_HEADERS)
            rows = await conn.fetch(SITEMAP_SQL)
            stamps = await conn.fetchrow(_LOADED_AT_SQL)
    except HTTPException:
        raise
    except Exception:
        log.exception("cruise sitemap")
        raise HTTPException(503, "cruise sitemap temporarily unavailable", headers=RETRY_HEADERS)
    entries = []
    for r in rows:
        at = [t for t, on in ((stamps["g"], r["in_glodap"]), (stamps["s"], r["in_socat"])) if on and t]
        e = {"loc": cruise_url(r["expocode"]), "changefreq": "yearly", "priority": "0.5"}
        if at:
            e["lastmod"] = str(max(at).astimezone(timezone.utc).date())
        entries.append(e)
    if not entries:
        raise HTTPException(503, "cruise sitemap empty", headers=RETRY_HEADERS)
    return {"entries": entries, "count": len(entries)}
