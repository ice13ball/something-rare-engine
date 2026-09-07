# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""NZ LINZ — Submarine cable polyline fetcher (Hydrographic chart-derived).

Source: data.linz.govt.nz layer 51643 (1:1.5M scale and smaller).
WFS endpoint requires LDS API key (env var LINZ_API_KEY). Licence: CC-BY 4.0.
Schema is S-57-derived; CATCBL/STATUS/CONDTN codes decoded via ingestion.s57_codes.
"""

from __future__ import annotations

import logging
import os
from datetime import date
from typing import AsyncGenerator

import httpx

from ingestion import s57_codes

log = logging.getLogger(__name__)

LAYER_ID = 51643
TIMEOUT_S = 90.0


def _wfs_url() -> str | None:
    key = os.environ.get("LINZ_API_KEY", "").strip()
    if not key:
        return None
    return (
        f"https://data.linz.govt.nz/services;key={key}/wfs"
        f"?service=WFS&version=2.0.0&request=GetFeature"
        f"&typeNames=layer-{LAYER_ID}&outputFormat=application/json"
        f"&SRSName=EPSG:4326"
    )


async def fetch_nz_cables_features() -> AsyncGenerator[list[dict], None]:
    """Yield NZ cable features in one batch (LINZ returns the full layer).

    Each yielded dict has the keys (already coerced + S-57 decoded):
        fidn        str
        catcbl      str | None  (decoded label, e.g. "Fibre-optic cable")
        catcbl_raw  int | None
        status      str | None
        status_raw  int | None
        condtn      str | None
        condtn_raw  int | None
        objnam      str | None
        inform      str | None
        txtdsc      str | None
        burdep      float | None
        datsta      date | None
        datend      date | None
        coordinates list (GeoJSON MultiLineString coords)

    Yields nothing if LINZ_API_KEY is missing or fetch fails.
    """
    url = _wfs_url()
    if not url:
        log.error("nz_cables: LINZ_API_KEY missing — skipping fetch")
        return

    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        try:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
        except httpx.HTTPError as exc:
            log.warning("nz_cables: WFS fetch failed — %s", exc)
            return
        except ValueError as exc:
            log.warning("nz_cables: response not JSON — %s", exc)
            return

    features_in = data.get("features", []) or []
    if not features_in:
        log.warning("nz_cables: WFS returned 0 features")
        return

    page: list[dict] = []
    for feat in features_in:
        props = feat.get("properties", {}) or {}
        geom = feat.get("geometry") or {}
        gtype = geom.get("type")
        coords = geom.get("coordinates")
        if not coords:
            continue
        # Normalise to MultiLineString coords (always wrap LineString)
        if gtype == "LineString":
            coords = [coords]
        elif gtype != "MultiLineString":
            log.debug("nz_cables: skipping fidn=%s — unexpected geometry type %s", feat.get("id", "?"), gtype)
            continue  # skip unexpected geometry

        fidn = _coerce_str(props.get("fidn"))
        if not fidn:
            continue  # primary key required

        catcbl_label, catcbl_raw = s57_codes.decode_catcbl(props.get("catcbl"))
        status_label, status_raw = s57_codes.decode_status(props.get("status"))
        condtn_label, condtn_raw = s57_codes.decode_condtn(props.get("condtn"))

        page.append({
            "fidn":        fidn,
            "catcbl":      catcbl_label,
            "catcbl_raw":  catcbl_raw,
            "status":      status_label,
            "status_raw":  status_raw,
            "condtn":      condtn_label,
            "condtn_raw":  condtn_raw,
            "objnam":      _coerce_str(props.get("objnam")),
            "inform":      _coerce_str(props.get("inform")),
            "txtdsc":      _coerce_str(props.get("txtdsc")),
            "burdep":      _coerce_float(props.get("burdep")),
            "datsta":      _parse_s57_date(props.get("datsta")),
            "datend":      _parse_s57_date(props.get("datend")),
            "coordinates": coords,
        })

    yield page


def _coerce_str(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _coerce_float(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_s57_date(v) -> date | None:
    """Parse S-57 date string (YYYYMMDD) to date. Returns None on invalid."""
    if v is None:
        return None
    s = str(v).strip()
    if not s or len(s) != 8 or not s.isdigit():
        return None
    try:
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except ValueError:
        return None


def coords_to_geojson_multilinestring(coords: list) -> dict:
    """Build a GeoJSON MultiLineString from coordinates."""
    return {"type": "MultiLineString", "coordinates": coords}
