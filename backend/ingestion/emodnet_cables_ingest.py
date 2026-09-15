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
  sigcables         FR SIGCables telecom (60) — ⚠️ NOT Spain. This file called
                    it "Spain IGN" until 2026-09-15; the publisher's own title
                    is "Telecommunication Cables - FR SIGCables". The Spanish
                    layer is `cicacables`, which we were not fetching at all.
  shomcables        FR SHOM telecom (603) — added 2026-09-15
  pcablesshom       FR SHOM power (142) — added 2026-09-15
  cicacables        ES CICA telecom (29) — added 2026-09-15
  maltacables       MT IOI-MOC telecom (6) — added 2026-09-15

EMODnet publishes 11 cable layers; this module fetched 7. ⚠️ The other four
were not forgotten — `rules/layers/submarine-cables.md` records the decision
and its reasons: SHOM "skipped at design time" for thin S-57 attribution
(codes, no names), CICA and Malta as "outside Baltic focus this iteration".
Both reasons are true. They are overruled by the project rule that we fetch
everything a provider publishes and choose afterwards what to show: at the
source on 2026-09-15 the four hold 780 features against the 1,255 we had, and
a layer nobody fetches cannot be chosen from later.

License: EMODnet — CC-BY 4.0. Endpoint: ows.emodnet-humanactivities.eu/wfs.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import date
from typing import AsyncGenerator, Callable

import httpx

log = logging.getLogger(__name__)

ENDPOINT = "https://ows.emodnet-humanactivities.eu/wfs"
TIMEOUT_S = 90.0

# Layer registry — order is fetch order (largest first to fail fast on bad keys)
# ⛔ The TRUNCATE success threshold in `sync_submarine_cables`
# (backend/domains/cables.py) is now DERIVED from this list, not typed. It used
# to be a hardcoded 6 with a note saying "revisit if the count changes" — and
# the count changed from 7 to 11 on 2026-09-15. Six of eleven layers would have
# been enough to TRUNCATE the table and re-fill it with 45% of the data, which
# does not come back.
LAYERS = [
    "pcablesnve",
    "shomcables",       # 603 — the biggest single layer, added 2026-09-15
    "pcablesshom",      # 142 — added 2026-09-15
    "rijkscables",
    "pcablesbshcontis",
    "sigcables",
    "pcablesrijks",
    "ukfibrecables",
    "cicacables",       # 29 — added 2026-09-15
    "bshcontiscables",
    "maltacables",      # 6 — added 2026-09-15
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
            normalized, merged = _merge_segments(normalized, layer)
            log.info("emodnet[%s]: fetched=%d normalized=%d skipped=%d merged=%d",
                     layer, len(feats), len(normalized), skipped, merged)
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


def _merge_segments(rows: list[dict], layer: str) -> tuple[list[dict], int]:
    """Fold rows that share a `source_id` into one multi-line row.

    ⛔ The table's key is (source_layer, source_id) and the INSERT says
    `ON CONFLICT DO NOTHING`, so before this existed a repeated id meant the
    later rows were dropped in silence — no error, no count, nothing to notice.

    Measured against the live WFS 2026-09-15: Rijkswaterstaat publishes
    `KB0039` as FIVE separate line features (15, 41, 15, 4 and 21 vertices) and
    `KB0048` as two. They are segments of one cable — same `naam`, same
    `eigenaar` — so production held 93 rows against the source's 98 and drew
    two cables from one segment each. ⚠️ Not five lost cables: two truncated
    routes, which looks like a complete cable and is worse.

    Merging is right because `submarine_cables.geom` is already a
    MultiLineString: one cable, one row, the whole route. The first row wins on
    the scalar fields; the rest contribute their geometry.
    """
    by_id: dict[str, dict] = {}
    merged = 0
    for r in rows:
        key = r["source_id"]
        first = by_id.get(key)
        if first is None:
            by_id[key] = r
            continue
        first["coordinates"] = list(first["coordinates"]) + list(r["coordinates"])
        merged += 1
    if merged:
        log.info("emodnet[%s]: merged %d segment(s) into cables that share an id "
                 "— these were silently dropped before", layer, merged)
    return list(by_id.values()), merged


def _parse_slash_date(v) -> date | None:
    """Parse dd/mm/yyyy → date. Returns None on anything else.

    ⚠️ SIGCables fills every one of its 60 features, but the blank marker in
    its sibling column `dism_year` is a single SPACE, not an empty string — so
    a `if v:` test would call it present. `.strip()` first, always.
    """
    if v is None:
        return None
    s = str(v).strip()
    if len(s) != 10 or s[2] != "/" or s[5] != "/":
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
    """FR SIGCables telecom — ⚠️ France, not Spain (see the module header)."""
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
        "cable_type": "Telecommunication",   # from the publisher's layer title
        "voltage_kv": None,
        # ⛔ This was hardcoded None while the layer publishes the value on all
        # 60 of 60 features. And the column name lies: `inst_year` holds a DATE
        # in dd/mm/yyyy ("01/05/1995"), not a year, so an int cast would have
        # produced None just as silently.
        "inst_year": _date_year(_parse_slash_date(p.get("inst_year"))),
        # ⛔ NOT the raw value. This layer's `status` is "1" or "2" — a code
        # whose vocabulary we have not found published anywhere. Writing it
        # into the same column that holds "ACTIVE", "inUse" and "Permanent"
        # for every other layer puts a number where readers expect a word, and
        # a panel rendering "Status: 2" states something we cannot support.
        # ⚠️ The meaning is nieustalone; the code is one re-sync away if we
        # ever find the list.
        "status": None,
        "location": _coerce_str(p.get("location")) or "Offshore",
        "coordinates": coords,
    }


def _map_shom_pair(layer_name: str, cable_type: str):
    """Factory for the two FR SHOM layers — telecom (603) and power (142).

    They share a schema: `inspireid`, `catcbl`, `status`.

    ⛔ `catcbl` is NOT mapped to a cable type. It is an S-57 category code
    (0.0/4.0 in the telecom layer, 1.0 in the power one) and we have not
    verified the code list, so `cable_type` comes from the publisher's own
    layer title instead — a fact we can point at. ⛔ `status` is likewise a
    bare "4" on some features and blank on the rest; see _map_sigcables for
    why a code does not go in the words column.
    """
    def _map(feat: dict) -> dict | None:
        p = feat.get("properties", {}) or {}
        coords = _coords(feat)
        if not coords:
            return None
        sid = _coerce_str(p.get("inspireid"))
        if not sid:
            return None
        return {
            "source_layer": layer_name,
            "source_id": sid,
            # The layer publishes no name at all — every feature is identified
            # by its INSPIRE id. ⛔ None, not the id repeated as a name: a
            # panel showing "FR 0000165900 00001" as a cable's NAME would be
            # asserting that someone calls it that.
            "name": None,
            "operator": None,
            "cable_type": cable_type,
            "voltage_kv": None,
            "inst_year": None,
            "status": None,
            "location": "Offshore",
            "coordinates": coords,
        }
    return _map


def _map_cicacables(feat: dict) -> dict | None:
    """ES CICA telecom (29).

    ⛔ The `name` field is not a name. All 29 features carry one of exactly two
    values — "CABLES DE TELEFONO ABANDONADOS" (17) and "CABLES DE TELEFONO
    OPERATIVOS" (12) — which is a condition, not an identity. Following the
    sigcables pattern and using it as `source_id` would have collapsed 29 rows
    into 2 on upsert, quietly, with the sync still reporting success.
    """
    p = feat.get("properties", {}) or {}
    coords = _coords(feat)
    if not coords:
        return None
    label = _coerce_str(p.get("name"))
    # A stable id derived from the whole route. ⛔ NOT the first vertex, which
    # was the first attempt: 9 of the 29 features share theirs, so 9 rows would
    # have been swallowed by ON CONFLICT DO NOTHING. ⚠️ If CICA redraws a line
    # its id moves, which shows up as a changed row rather than a silent merge;
    # two features that hash the same really are the same geometry.
    sid = "cica-" + hashlib.sha1(
        repr(coords).encode(), usedforsecurity=False
    ).hexdigest()[:16]
    return {
        "source_layer": "cicacables",
        "source_id": sid,
        "name": None,
        "operator": None,
        "cable_type": "Telecommunication",   # from the publisher's layer title
        "voltage_kv": None,
        "inst_year": None,
        # The two labels ARE words, and they say condition — so here the words
        # column is exactly where they belong.
        "status": "Abandoned" if label and "ABANDONADO" in label.upper()
                  else ("Operational" if label else None),
        "location": _coerce_str(p.get("location")) or "Offshore",
        "coordinates": coords,
    }


def _map_maltacables(feat: dict) -> dict | None:
    """MT IOI-MOC telecom (6). Names only, and all six are distinct."""
    p = feat.get("properties", {}) or {}
    coords = _coords(feat)
    if not coords:
        return None
    name = _coerce_str(p.get("name"))
    if not name:
        return None
    return {
        "source_layer": "maltacables",
        "source_id": name,
        "name": name,
        "operator": None,
        "cable_type": "Telecommunication",   # from the publisher's layer title
        "voltage_kv": None,
        "inst_year": None,
        "status": None,
        "location": "Offshore",
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
    "shomcables":        _map_shom_pair("shomcables", "Telecommunication"),
    "pcablesshom":       _map_shom_pair("pcablesshom", "Power"),
    "cicacables":        _map_cicacables,
    "maltacables":       _map_maltacables,
}


def coords_to_geojson_multilinestring(coords: list) -> dict:
    return {"type": "MultiLineString", "coordinates": coords}
