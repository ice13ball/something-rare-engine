# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Arctic River Inputs ingest — pure parsers + helpers (no DB code).

Sub-sources (verified against the real files, 2026-06):
  • ArcticGRO — the 6 great rivers. ONE Google Sheet, ONE TAB PER RIVER (gid).
    Each tab: 8-row preamble, a param-name header row (first cell "Phase"),
    a units row, then data. Every parameter is a PAIRED (value, flag) column;
    discharge (m³/s) is embedded in the same sheet at each sampling date.
  • PANGAEA.945702 — Canadian Arctic Archipelago Rivers (Brown et al. 2022).
    Tab-delimited textfile with a `/* … */` metadata block before the table.

NOT ingested in v1 (documented follow-ups, deliberately not faked):
  • PANGAEA.913197 (Lena/Samoylov) is a PANGAEA *collection* — no single
    machine-readable textfile (TEXTFILE format unavailable for collections).
    Needs a specific child-dataset DOI; deferred.
  • Annual carbon/nutrient LOAD fluxes + true mean annual discharge need the
    full daily-discharge series (separate per-river files at different gauge
    sites). v1 ships the directly-observed concentrations + sampling-date
    discharge only; flux integration is a follow-up.

DB writes live in land_layers.py::_sync_arctic_rivers.
"""
from __future__ import annotations

import datetime as dt
import math
import re
from collections import defaultdict

SECONDS_PER_YEAR = 31_557_600  # 365.25 d


def _slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.strip().lower())).strip("-")


def _station_id(source: str, key: str) -> str:
    return f"{source}:{_slug(key)}"


def _is_num(v) -> bool:
    return (
        isinstance(v, (int, float))
        and not isinstance(v, bool)
        and not (isinstance(v, float) and math.isnan(v))
    )


def _parse_date(s) -> dt.date | None:
    """Parse a date or ISO datetime (takes the leading YYYY-MM-DD)."""
    s = (str(s) if s is not None else "").strip()
    if not s:
        return None
    head = s[:10]
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d.%m.%Y"):
        try:
            return dt.datetime.strptime(head, fmt).date()
        except ValueError:
            continue
    return None


def _parse_float(s) -> float | None:
    if s is None:
        return None
    s = str(s).strip()
    if s == "" or s.lower() in ("na", "n/a", "nan", "bdl", "nd"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _monthly_downsample(series: list[tuple[dt.date, float]]) -> list[list]:
    """[(date, value)] → [["YYYY-MM", mean], ...] ascending; None/NaN dropped."""
    buckets: dict[str, list[float]] = defaultdict(list)
    for d, v in series:
        if d is None or not _is_num(v):
            continue
        buckets[f"{d.year:04d}-{d.month:02d}"].append(float(v))
    return [[k, sum(vs) / len(vs)] for k, vs in sorted(buckets.items())]


def _mean(series: list[tuple[dt.date, float]]) -> float | None:
    vals = [v for _, v in series if _is_num(v)]
    return sum(vals) / len(vals) if vals else None


# ── ArcticGRO ────────────────────────────────────────────────────────────────
# One Google Sheet, one tab (gid) per river. Verified gid→river map 2026-06.
ARCTICGRO_SHEET_ID = "1zPVbl0sbqt-c5UJPbHqzV143LG72b5AZKAbay4Alv6M"
ARCTICGRO_TABS: dict[str, dict] = {
    # river → tab gid + sampling-site coordinates (approximate WQ station)
    "Ob":        {"gid": "0",          "lat": 66.63, "lon": 66.60,   "site": "Salekhard"},
    "Yenisey":   {"gid": "33954102",   "lat": 69.40, "lon": 86.18,   "site": "Dudinka"},
    "Lena":      {"gid": "1178174644", "lat": 66.77, "lon": 123.37,  "site": "Zhigansk"},
    "Kolyma":    {"gid": "1198328004", "lat": 68.75, "lon": 161.30,  "site": "Cherskiy"},
    "Mackenzie": {"gid": "1833453157", "lat": 67.45, "lon": -133.74, "site": "Tsiigehtchic"},
    "Yukon":     {"gid": "726217032",  "lat": 61.93, "lon": -162.88, "site": "Pilot Station"},
}

# Real WQ-sheet param-name (header row) → canonical key. Discharge is handled
# separately. Names are the exact strings in the sheet's "Phase" header row.
ARCTICGRO_PARAM_MAP: dict[str, str] = {
    "DOC": "doc",
    "TDN": "tdn",
    "NO3": "no3",
    "NH4": "nh4",
    "TDP": "tdp",
    "SRP": "srp",
    "SiO2": "sio2",
    "Alkalinity": "alkalinity",
}
_ARCTICGRO_SKIP_FLAGS = {"DV", "NC", "NA", "BD"}  # deleted / not collected / n.a. / below detection

ARCTICGRO_CITATION = (
    "The Arctic Great Rivers Observatory. Water Quality Dataset. "
    "https://www.arcticgreatrivers.org/data (free to use; please credit ArcticGRO)."
)


def _arctic_river_key(raw: str) -> str | None:
    """Map a sheet river label ("Ob'", "Yenisey", …) to an ARCTICGRO_TABS key."""
    name = raw.strip().rstrip("'").strip()
    return name if name in ARCTICGRO_TABS else None


def _parse_arcticgro_sheet(text: str) -> list[dict]:
    """Parse one river tab's CSV → list of events
    {river, date, discharge (m³/s|None), params: {canonical: value}}.

    Robust to the variable-length preamble: locates the header row whose first
    cell is "Phase". Selects value columns via the units row (a column is a
    value column when its unit cell is not "flag"); each value column's flag is
    the immediately following column.
    """
    import csv
    import io

    rows = list(csv.reader(io.StringIO(text)))
    hdr_i = next((i for i, r in enumerate(rows) if r and r[0].strip() == "Phase"), None)
    if hdr_i is None or hdr_i + 2 >= len(rows):
        return []
    names = rows[hdr_i]
    units = rows[hdr_i + 1]

    disch_col: int | None = None
    val_cols: dict[str, int] = {}  # canonical → column index
    val_units: dict[str, str] = {}  # canonical → source unit string (verbatim)
    for i in range(4, len(names)):
        raw_unit = (units[i] if i < len(units) else "").strip()
        if raw_unit.lower() == "flag":
            continue
        nm = names[i].strip()
        if nm == "Discharge":
            disch_col = i
        elif nm in ARCTICGRO_PARAM_MAP:
            canon = ARCTICGRO_PARAM_MAP[nm]
            val_cols[canon] = i
            val_units[canon] = raw_unit  # e.g. "mg/L", "ug/L as N", "mg CaCO3/L"

    def _ok(row: list[str], col: int) -> bool:
        flag = row[col + 1].strip().upper() if col + 1 < len(row) else ""
        return flag not in _ARCTICGRO_SKIP_FLAGS

    events: list[dict] = []
    for r in rows[hdr_i + 2:]:
        if len(r) < 5 or not r[1].strip():
            continue
        d = _parse_date(r[2])
        if d is None:
            continue
        discharge = None
        if disch_col is not None and disch_col < len(r) and _ok(r, disch_col):
            discharge = _parse_float(r[disch_col])
        params: dict[str, float] = {}
        for canon, ci in val_cols.items():
            if ci < len(r) and _ok(r, ci):
                v = _parse_float(r[ci])
                if v is not None:
                    params[canon] = v
        events.append({"river": r[1].strip(), "date": d, "discharge": discharge,
                       "params": params, "units": val_units})
    return events


def build_arcticgro_stations(sheet_texts: list[str]) -> list[dict]:
    """Each text is one river tab's CSV (river self-identified in column 2)."""
    by_river: dict[str, list[dict]] = defaultdict(list)
    for text in sheet_texts:
        for ev in _parse_arcticgro_sheet(text):
            key = _arctic_river_key(ev["river"])
            if key:
                by_river[key].append(ev)

    out: list[dict] = []
    for river, events in by_river.items():
        meta = ARCTICGRO_TABS[river]
        bio: dict[str, list] = defaultdict(list)
        disch: list[tuple[dt.date, float]] = []
        units_map: dict[str, str] = {}
        for ev in events:
            if ev["discharge"] is not None:
                disch.append((ev["date"], ev["discharge"]))
            for p, v in ev["params"].items():
                bio[p].append((ev["date"], v))
            if ev.get("units"):
                units_map.update(ev["units"])
        if not bio and not disch:
            continue
        summary = {p: _mean(s) for p, s in bio.items() if s}
        mean_disch = _mean(disch)
        if mean_disch is not None:
            summary["discharge_m3s"] = mean_disch
        all_dates = [d for s in bio.values() for d, _ in s] + [d for d, _ in disch]
        out.append({
            "station_id": _station_id("arcticgro", river),
            "source": "arcticgro",
            "river_name": river,
            "site_label": meta["site"],
            "lat": meta["lat"], "lon": meta["lon"],
            "geom_wkt": f"POINT({meta['lon']} {meta['lat']})",
            "record_start": min(all_dates) if all_dates else None,
            "record_end": max(all_dates) if all_dates else None,
            # Annual discharge volume + nutrient loads need the daily-discharge
            # series (separate files); deferred. Sampling-date discharge mean is
            # in summary_stats["discharge_m3s"], full series in discharge_monthly.
            "mean_annual_discharge_km3": None,
            "summary_stats": summary,
            # Units captured verbatim from the source sheet's units row, per param
            # (e.g. tdn→"mg/L", no3→"ug/L as N", alkalinity→"mg CaCO3/L"). The
            # panel reads these instead of guessing; ArcticGRO posts mass, not molar.
            "units": {p: u for p, u in units_map.items() if p in bio} or None,
            "discharge_monthly": _monthly_downsample(disch) if disch else None,
            "biogeochem_monthly": {p: _monthly_downsample(s) for p, s in bio.items() if s},
            "annual_fluxes": None,
            "citation": ARCTICGRO_CITATION,
        })
    return out


def fetch_arcticgro() -> list[str]:
    """Download every ArcticGRO river tab as CSV text (one string per river)."""
    import httpx

    base = f"https://docs.google.com/spreadsheets/d/{ARCTICGRO_SHEET_ID}/export"
    texts: list[str] = []
    with httpx.Client(timeout=60, follow_redirects=True) as c:
        for meta in ARCTICGRO_TABS.values():
            r = c.get(base, params={"format": "csv", "gid": meta["gid"]})
            r.raise_for_status()
            texts.append(r.text)
    return texts


# ── PANGAEA ──────────────────────────────────────────────────────────────────
PANGAEA_CAA_CITATION = (
    "Brown, K. A. et al. (2022): Canadian Arctic Archipelago Rivers Program: Nutrient, "
    "Dissolved Organic Carbon, and Water Isotope Data 2016-2019. PANGAEA, "
    "https://doi.org/10.1594/PANGAEA.945702 (CC-BY-4.0)."
)
# PANGAEA column-header prefix → canonical key (verified against 945702 headers).
PANGAEA_PARAM_MAP: dict[str, str] = {
    "DOC": "doc",
    "[NO3]": "no3",
    "[PO4]": "po4",
    "Si(OH)4": "dsi",
}
# Physical / water-isotope columns in 945702 (δ18O H2O, δD H2O, Temp, EC).
# Matched by a unique CASE-SENSITIVE substring of the header rather than the
# leading δ glyph, so a Greek-delta codepoint mismatch can't silently drop them.
# Surfaced in the panel's "Water Properties" section, separate from biogeochem.
PANGAEA_PHYS_TOKENS: list[tuple[str, str]] = [
    ("18O",   "d18o"),  # δ18O H2O [‰ SMOW]
    ("D H2O", "dd"),    # δD H2O [‰ SMOW]
    ("Temp",  "temp"),  # Temp [°C]
    ("EC [",  "ec"),    # EC [µS/cm]
]
# Canonical biogeochem keys — a site must have ≥1 of these to qualify as a
# river-input station (isotope/physical data alone doesn't, e.g. groundwater
# seeps), but is captured once the site qualifies.
_PANGAEA_BIOGEO_KEYS = set(PANGAEA_PARAM_MAP.values())


def _strip_pangaea_header(text: str) -> str:
    """Drop the leading `/* … */` metadata block, leaving the data table."""
    if "*/" in text:
        text = text.split("*/", 1)[1].lstrip("\n")
    return text


def _read_pangaea_tab(path: str) -> list[dict]:
    import csv
    import io
    with open(path, encoding="utf-8") as f:
        text = _strip_pangaea_header(f.read())
    return list(csv.DictReader(io.StringIO(text), delimiter="\t"))


def _pangaea_col(row: dict, *candidates: str):
    for c in candidates:
        cl = c.lower()
        for k in row:
            if k.strip().lower().startswith(cl):
                return row[k]
    return None


def _pangaea_phys_col(row: dict, token: str):
    """Match a physical/isotope column by a unique case-sensitive substring."""
    for k, v in row.items():
        if token in k:
            return v
    return None


def _pangaea_biogeochem(rows: list[dict]):
    series: dict[str, list] = defaultdict(list)
    for row in rows:
        d = _parse_date(_pangaea_col(row, "Date/Time", "Date"))
        if d is None:
            continue
        for prefix, param in PANGAEA_PARAM_MAP.items():
            v = _parse_float(_pangaea_col(row, prefix))
            if v is not None:
                series[param].append((d, v))
        for token, param in PANGAEA_PHYS_TOKENS:
            v = _parse_float(_pangaea_phys_col(row, token))
            if v is not None:
                series[param].append((d, v))
    monthly = {p: _monthly_downsample(s) for p, s in series.items() if s}
    summary = {p: _mean(s) for p, s in series.items() if s}
    dates = [d for s in series.values() for d, _ in s]
    return monthly, summary, dates


def build_pangaea_caa_stations(rows: list[dict]) -> list[dict]:
    """One station per distinct River label; skips sites with no DOC/nutrient data."""
    by_river: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        rv = (_pangaea_col(row, "River") or "").strip()
        if rv:
            by_river[rv].append(row)

    out: list[dict] = []
    for rv, srows in by_river.items():
        lat = _parse_float(_pangaea_col(srows[0], "Latitude"))
        lon = _parse_float(_pangaea_col(srows[0], "Longitude"))
        if lat is None or lon is None:
            continue
        monthly, summary, dates = _pangaea_biogeochem(srows)
        if not (set(monthly) & _PANGAEA_BIOGEO_KEYS):
            continue
        out.append({
            "station_id": _station_id("pangaea_caa", rv),
            "source": "pangaea_caa", "river_name": rv, "site_label": rv,
            "lat": lat, "lon": lon, "geom_wkt": f"POINT({lon} {lat})",
            "record_start": min(dates) if dates else None,
            "record_end": max(dates) if dates else None,
            "mean_annual_discharge_km3": None,
            "summary_stats": summary, "discharge_monthly": None,
            "biogeochem_monthly": monthly, "annual_fluxes": None,
            "citation": PANGAEA_CAA_CITATION,
        })
    return out


def fetch_pangaea(doi_suffix: str) -> list[dict]:
    """Download a PANGAEA tab-delimited dataset export → list of row dicts."""
    import csv
    import io
    import httpx

    url = f"https://doi.pangaea.de/10.1594/PANGAEA.{doi_suffix}?format=textfile"
    with httpx.Client(timeout=60, follow_redirects=True) as c:
        r = c.get(url)
        r.raise_for_status()
        text = _strip_pangaea_header(r.text)
    return list(csv.DictReader(io.StringIO(text), delimiter="\t"))
