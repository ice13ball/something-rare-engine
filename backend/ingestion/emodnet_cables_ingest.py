# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""EMODnet Human Activities — multi-layer submarine cable fetcher.

Fetches 7 cable layers from EMODnet's WFS endpoint and normalizes them into
a common schema. Each layer comes from a different national contributor with
its own field naming convention (Norwegian, German, Dutch, English, Spanish).

Layers:
  pcablesnve        Norway NVE power cables (918) — rich attribution
  bshcontiscables   Germany BSH telecom cables (28) — German Baltic coast
  pcablesbshcontis  Germany BSH power cables (89) — incl. "Baltic Cable"
  rijkscables       Netherlands Rijkswaterstaat telecom (98)
  pcablesrijks      Netherlands Rijkswaterstaat power (37) — incl. NORNED
  ukfibrecables     UK fibre optic (30) — North Sea oil platform cables
  sigcables         Spain IGN + Atlantic terminations (60) — original layer

License: EMODnet — CC-BY 4.0. Endpoint: ows.emodnet-humanactivities.eu/wfs.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import AsyncGenerator, Callable

import httpx

log = logging.getLogger(__name__)

ENDPOINT = "https://ows.emodnet-humanactivities.eu/wfs"
TIMEOUT_S = 90.0

# Layer registry — order is fetch order (largest first to fail fast on bad keys)
# NOTE: the 6-of-7 success threshold for TRUNCATE lives in
# `sync_submarine_cables` in backend/domains/cables.py. If the count here
# changes, revisit that threshold (currently hardcoded to 6).
LAYERS = [
    "pcablesnve",
    "rijkscables",
    "pcablesbshcontis",
    "sigcables",
    "pcablesrijks",
    "ukfibrecables",
    "bshcontiscables",
]


async def fetch_all_layers() -> AsyncGenerator[tuple[str, list[dict]], None]:
    """Yield (layer_name, normalized_features) tuples for each of the 7 layers.

    Each yielded list contains dicts with normalized keys:
        source_layer, source_id, name, operator, cable_type, voltage_kv,
        inst_year (int|None), status, location, coordinates (GeoJSON
        MultiLineString coords)

    On per-layer failure: logs warning, yields (layer_name, []) for that layer.
    Caller decides whether to TRUNCATE based on whether ANY layer succeeded.
    """
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        for layer in LAYERS:
            try:
                feats = await _fetch_one_layer(client, layer)
            except httpx.HTTPError as exc:
                log.warning("emodnet[%s]: fetch failed — %s", layer, exc)
                yield layer, []
                continue
            except (ValueError, KeyError) as exc:
                log.warning("emodnet[%s]: response parse failed — %s", layer, exc)
                yield layer, []
                continue
            mapper = LAYER_MAPPERS.get(layer)
            if not mapper:
                log.warning("emodnet[%s]: no mapper registered, skipping", layer)
                yield layer, []
                continue
            normalized = []
            skipped = 0
            for feat in feats:
                norm = mapper(feat)
                if norm is None:
                    skipped += 1
                    continue
                normalized.append(_drop_zero_sentinels(norm))
            log.info("emodnet[%s]: fetched=%d normalized=%d skipped=%d",
                     layer, len(feats), len(normalized), skipped)
            yield layer, normalized


# ── Upstream encodes "unknown" as 0, not as null ────────────────────────────
# Verified against the raw WFS on 2026-08-27, NOT inferred from our own tables:
#
#   GET emodnet:pcablesnve → 918 features, and NOT ONE null in either field.
#   `driftsatta` (commissioning year) is 0 on 228 of them; `spenning_k`
#   (voltage, kV) is 0.0 on 14, NorNed's three segments among them. NorNed is
#   really 450 kV, commissioned 2008; the layer's own maximum is 420 kV, so 0
#   is a sentinel, not a rounding.
#
# ➡️ The zero is THEIRS. Our `_coerce_float`/`_coerce_int` pass it through
# faithfully — which is the right behaviour for a mirror and the wrong one for
# a value nobody can hold: no cable was commissioned in year 0, and a cable at
# 0 kV carries nothing.
#
# ⚠️ The frontend cannot catch this. `CablePanel.tsx` hides missing values with
# `p.voltage_kv != null`, and 0 is not null — it renders, and reads as measured.
#
# 📌 Applied at the ONE point every mapper's output passes through, deliberately:
# seven mappers exist and only one needed it today. Patch the mapper instead and
# the next layer that ships this encoding arrives unguarded.
_ZERO_IS_MISSING = ("voltage_kv", "inst_year")


def _drop_zero_sentinels(norm: dict) -> dict:
    """Turn upstream's 0-means-unknown into a real null, in place."""
    for field in _ZERO_IS_MISSING:
        if norm.get(field) == 0:
            norm[field] = None
    return norm


async def _fetch_one_layer(client: httpx.AsyncClient, layer: str) -> list[dict]:
    url = (
        f"{ENDPOINT}?service=WFS&version=2.0.0&request=GetFeature"
        f"&typeName=emodnet:{layer}&outputFormat=application/json"
        f"&SRSName=EPSG:4326"
    )
    r = await client.get(url)
    r.raise_for_status()
    data = r.json()
    return data.get("features", []) or []


# ────────── Per-layer attribute mappers ──────────
# Each takes a raw GeoJSON feature, returns a normalized dict or None to skip.


def _coerce_str(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s if s and s.upper() not in {"NA", "N/A", "NULL", "-"} else None


def _coerce_float(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _coerce_int(v) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(float(v))  # handles "1982.0" strings
    except (TypeError, ValueError):
        return None


def _parse_iso_date(v) -> date | None:
    """Parse YYYY-MM-DD or YYYY-MM-DDTHH... → date. Returns None on invalid."""
    if v is None:
        return None
    s = str(v).strip()
    if len(s) < 10:
        return None
    try:
        return date(int(s[:4]), int(s[5:7]), int(s[8:10]))
    except (ValueError, TypeError):
        return None


def _parse_dutch_date(v) -> date | None:
    """Parse Dutch dd-mm-yyyy → date. Returns None on invalid."""
    if v is None:
        return None
    s = str(v).strip()
    if len(s) < 10 or s[2] != "-" or s[5] != "-":
        return None
    try:
        return date(int(s[6:10]), int(s[3:5]), int(s[0:2]))
    except (ValueError, TypeError):
        return None


def _coords(feat: dict) -> list | None:
    g = feat.get("geometry") or {}
    gtype = g.get("type")
    c = g.get("coordinates")
    if not c:
        return None
    if gtype == "LineString":
        return [c]
    if gtype == "MultiLineString":
        return c
    return None  # skip Polygon/Point/etc


def _date_year(d: date | None) -> int | None:
    return d.year if d else None


def _map_pcablesnve(feat: dict) -> dict | None:
    """Norway NVE power cables — rich Norwegian schema."""
    p = feat.get("properties", {}) or {}
    coords = _coords(feat)
    if not coords:
        return None
    sid = _coerce_str(p.get("lokalid"))
    if not sid:
        return None
    year_v = _coerce_int(p.get("driftsatta"))
    return {
        "source_layer": "pcablesnve",
        "source_id": sid,
        "name": _coerce_str(p.get("navn")),
        "operator": _coerce_str(p.get("eier")),
        "cable_type": "Power",
        "voltage_kv": _coerce_float(p.get("spenning_k")),
        "inst_year": year_v,
        "status": "Permanent",
        "location": _coerce_str(p.get("location")) or "Offshore",
        "coordinates": coords,
    }


def _map_bsh_pair(layer_name: str):
    """Factory for the 2 BSH layers (telecom + power) — same schema, different layer_name tag."""
    def _map(feat: dict) -> dict | None:
        p = feat.get("properties", {}) or {}
        coords = _coords(feat)
        if not coords:
            return None
        sid = _coerce_str(p.get("uuid")) or _coerce_str(p.get("featureid"))
        if not sid:
            return None
        return {
            "source_layer": layer_name,
            "source_id": sid,
            "name": _coerce_str(p.get("name_")),
            "operator": None,
            "cable_type": _coerce_str(p.get("featuretyp")),
            "voltage_kv": None,
            "inst_year": None,
            "status": _coerce_str(p.get("status")),
            "location": "Offshore",
            "coordinates": coords,
        }
    return _map


def _map_rijks_pair(layer_name: str):
    """Factory for the 2 Rijkswaterstaat layers (telecom + power) — Dutch schema."""
    def _map(feat: dict) -> dict | None:
        p = feat.get("properties", {}) or {}
        coords = _coords(feat)
        if not coords:
            return None
        sid = _coerce_str(p.get("kabel_nr"))
        if not sid:
            return None
        return {
            "source_layer": layer_name,
            "source_id": sid,
            "name": _coerce_str(p.get("naam")),
            "operator": _coerce_str(p.get("eigenaar")),
            "cable_type": _coerce_str(p.get("kabelsoort")),
            "voltage_kv": None,
            "inst_year": _date_year(_parse_dutch_date(p.get("aanleg_dd"))),
            "status": _coerce_str(p.get("rpl_status")) or _coerce_str(p.get("status")),
            "location": "Offshore",
            "coordinates": coords,
        }
    return _map


def _map_ukfibrecables(feat: dict) -> dict | None:
    """UK fibre optic cables (North Sea oil platform context)."""
    p = feat.get("properties", {}) or {}
    coords = _coords(feat)
    if not coords:
        return None
    sid = _coerce_str(p.get("id"))
    if not sid:
        return None
    return {
        "source_layer": "ukfibrecables",
        "source_id": sid,
        "name": _coerce_str(p.get("pipe_name")),
        "operator": _coerce_str(p.get("operator")),
        "cable_type": _coerce_str(p.get("fluid")),
        "voltage_kv": None,
        "inst_year": _date_year(_parse_iso_date(p.get("start_date"))),
        "status": _coerce_str(p.get("status")),
        "location": _coerce_str(p.get("location")) or "Offshore",
        "coordinates": coords,
    }


def _map_sigcables(feat: dict) -> dict | None:
    """Spain IGN + Atlantic terminations — original layer, generic schema."""
    p = feat.get("properties", {}) or {}
    coords = _coords(feat)
    if not coords:
        return None
    # SIG features often have name as primary identifier; use it for source_id too
    name = _coerce_str(p.get("name"))
    sid = name or _coerce_str(p.get("inspireid"))
    if not sid:
        return None
    return {
        "source_layer": "sigcables",
        "source_id": sid,
        "name": name,
        "operator": None,
        "cable_type": None,
        "voltage_kv": None,
        "inst_year": None,
        "status": _coerce_str(p.get("status")),
        "location": _coerce_str(p.get("location")) or "Offshore",
        "coordinates": coords,
    }


# Registry — bind layer names to mappers
LAYER_MAPPERS: dict[str, Callable[[dict], dict | None]] = {
    "pcablesnve":        _map_pcablesnve,
    "bshcontiscables":   _map_bsh_pair("bshcontiscables"),
    "pcablesbshcontis":  _map_bsh_pair("pcablesbshcontis"),
    "rijkscables":       _map_rijks_pair("rijkscables"),
    "pcablesrijks":      _map_rijks_pair("pcablesrijks"),
    "ukfibrecables":     _map_ukfibrecables,
    "sigcables":         _map_sigcables,
}


def coords_to_geojson_multilinestring(coords: list) -> dict:
    return {"type": "MultiLineString", "coordinates": coords}
