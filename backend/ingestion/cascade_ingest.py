# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Pure parser for the CASCADE v2 surface-sediment station table.

Source: bolin.su.se/data/uploads/cascade-surface-sediment-2.zip -> CASCADEsurfsed_v2.txt
Tab-separated, latin-1 encoded (the per-mil symbol is not utf-8). 28 columns.
"""
from __future__ import annotations

# canonical field -> substring that uniquely identifies its header cell
_COLS = {
    "id": "ID",
    "station": "STATION",
    "lat": "LAT",
    "lon": "LON",
    "water_depth_m": "WATERDEPTH",
    "expedition": "EXPEDITION",
    "year": "YEAR",
    "oc_pct": "OC (%)",
    "tn_pct": "TN (%)",
    "oc_tn": "OC_TN",
    "d13c": "d13C",
    "d14c": "D14C",
    "hmw_alkanes": "HMWALK (",
    "hmw_acids": "HMWACID",
    "lignin": "LIGNIN",
}
_PARAM_COLS = ("CN_CITATION", "d13C_CITATION", "D14C_CITATION", "BM_CITATION",
               "SAMPLER", "STORAGE", "CN_METHOD", "d13C_METHOD", "D14C_LABEL")


def _f(s: str | None) -> float | None:
    if s is None:
        return None
    s = s.strip().strip('"')
    if s == "" or s.upper() in ("NA", "N/A", "NAN"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _i(s: str | None) -> int | None:
    f = _f(s)
    return int(f) if f is not None else None


def _resolve(header: list[str]) -> dict[str, int]:
    idx: dict[str, int] = {}
    for field, needle in _COLS.items():
        for j, h in enumerate(header):
            # Citation/method/label columns share a name prefix with their
            # corresponding value column (e.g. "d13C_CITATION" vs "d13C (...)");
            # never let them win a value-column match.
            if "CITATION" in h or "METHOD" in h or "LABEL" in h:
                continue
            if h.strip().startswith(needle):
                idx[field] = j
                break
    return idx


def build_station_rows(text: str) -> list[dict]:
    lines = [ln for ln in text.splitlines() if ln != ""]
    if not lines:
        return []
    header = lines[0].split("\t")
    idx = _resolve(header)
    param_idx = {name: header.index(name) for name in _PARAM_COLS if name in header}
    rows: list[dict] = []
    for ln in lines[1:]:
        cells = ln.split("\t")

        def cell(field: str) -> str | None:
            j = idx.get(field)
            return cells[j] if (j is not None and j < len(cells)) else None

        lat, lon = _f(cell("lat")), _f(cell("lon"))
        if lat is None or lon is None:
            continue
        year = _i(cell("year"))
        params = {}
        for name, j in param_idx.items():
            v = cells[j].strip().strip('"') if j < len(cells) else ""
            if v and v.upper() not in ("NA", "N/A"):
                params[name] = v
        station = (cell("station") or "").strip().strip('"') or None
        rows.append({
            "id": _i(cell("id")),
            "station": station,
            "lat": lat, "lon": lon,
            "water_depth_m": _f(cell("water_depth_m")),
            "expedition": ((cell("expedition") or "").strip().strip('"') or None),
            "year": year,
            "decade": (year // 10 * 10) if year is not None else None,
            "oc_pct": _f(cell("oc_pct")),
            "tn_pct": _f(cell("tn_pct")),
            "oc_tn": _f(cell("oc_tn")),
            "d13c": _f(cell("d13c")),
            "d14c": _f(cell("d14c")),
            "hmw_alkanes": _f(cell("hmw_alkanes")),
            "hmw_acids": _f(cell("hmw_acids")),
            "lignin": _f(cell("lignin")),
            "params": params,
        })
    return rows
