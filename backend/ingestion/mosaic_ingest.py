# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Pure parsers for the MOSAIC (ETH Zürich) marine sediment carbon layer.

Source API (verified 2026-07-04): mosaicprd.ethz.ch/api/mosaic_app/{geopoints,samples}.
Values + coordinates may arrive as native JSON types (float/int/null) OR as strings
(e.g. epoch-ms sampling_date as a float-string); the coercers (`_f`/`_s`/`_i`) handle
both. "nan"/"" (string) and real float NaN are all placeholder nulls. One analysis per
/samples request (multi-analysis 500s); merge sections across analyses on sample_id.
Every value carries <analysis>_DOI/_title/_method."""
from __future__ import annotations

import datetime as _dt
import math

MOSAIC_ANALYSES = [
    ("total_organic_carbon_%", "toc"),
    ("total_nitrogen_%", "tn"),
    ("Delta_13C", "d13c"),
    ("Delta_14C", "d14c"),
    ("Fm_14C", "fm14c"),
]
COLOR_VARS = ("toc", "tn", "d13c", "d14c")   # fm14c is panel-only
_NA = {"nan", "NaN", "NA", "N/A", "", "none", "None", None}


def _f(v):
    if v in _NA:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) else x


def _s(v):
    if v in _NA:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    s = str(v).strip()
    return s or None


def _i(v):
    f = _f(v)
    return int(f) if f is not None else None


def _epoch_ms_to_date(v) -> "_dt.date | None":
    """MOSAIC ships dates as epoch milliseconds, not ISO strings."""
    if v is None:
        return None
    try:
        return _dt.datetime.utcfromtimestamp(float(v) / 1000.0).date()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _date_precision(day, month, year, campaign_start) -> str:
    """Records how precisely the SOURCE dated this core. The only derived field
    on this path, and it describes the source, not the sample."""
    if day is not None:
        return "day"
    if month is not None:
        return "month"
    if year is not None:
        return "year"
    if campaign_start is not None:
        return "campaign"
    return "none"


def parse_geopoints(rows):
    out = []
    for r in rows:
        cid = _i(r.get("core_id"))
        lat, lon = _f(r.get("latitude")), _f(r.get("longitude"))
        if cid is None or lat is None or lon is None:
            continue
        yr = _i(r.get("sampling_year"))
        mo = _i(r.get("sampling_month"))
        dy = _i(r.get("sampling_day"))
        sdate = _epoch_ms_to_date(r.get("sampling_date"))
        # The source sometimes ships a compound sampling_date but leaves the
        # separate month/day fields blank. sampling_date is itself a
        # source-given value (not something we derive), so reading month/day
        # off it is using the precision the source already gave us, not
        # inventing precision (see docs/methods/data-passthrough.md).
        if sdate is not None:
            if mo is None:
                mo = sdate.month
            if dy is None:
                dy = sdate.day
        # ...and the mirror case, which the 2026-09-04 fix left open: the source
        # gives year, month AND day as separate fields but no compound
        # sampling_date. 1,913 live cores were in exactly that state — dated to the
        # day, with an empty date column. They rendered fine (the panel reads the
        # parts) and were invisible to every query and export that filters on
        # sampling_date, which is the worst shape for a defect to take.
        #
        # Composing y+m+d is assembling what the source gave, not inventing
        # precision — the same argument as the branch above, run backwards.
        elif None not in (yr, mo, dy):
            try:
                sdate = _dt.date(yr, mo, dy)
            except ValueError:
                # A source day that is not a real calendar date (2011-02-30 and the
                # like). Leave sdate None and let the parts stand on their own
                # rather than snapping to a neighbouring day nobody sampled.
                pass
        cs = _epoch_ms_to_date(r.get("sampling_campaign_date_start"))
        ce = _epoch_ms_to_date(r.get("sampling_campaign_date_end"))
        out.append({
            "core_id": cid,
            "core_name": _s(r.get("core_name")),
            "latitude": lat,
            "longitude": lon,
            "water_depth_m": _f(r.get("water_depth_m")),
            "sampling_year": yr,
            "decade": (yr // 10 * 10) if yr is not None else None,
            "sampling_date":   sdate,
            "sampling_month":  mo,
            "sampling_day":    dy,
            "campaign_name":   _s(r.get("sampling_campaign_name")),
            "campaign_start":  cs,
            "campaign_end":    ce,
            "core_comment":    _s(r.get("core_comment")),
            "date_precision":  _date_precision(dy, mo, yr, cs),
            "sampling_method": _s(r.get("sampling_method_type")),
            "research_vessel": _s(r.get("research_vessel")),
            "seas": _s(r.get("seas")),
            "eez": _s(r.get("exclusive_economics_zone")),
            "longhurst": _s(r.get("longhurst_provinces_full")),
        })
    return out


def parse_samples(rows, var_key, api_name):
    frags = {}
    for r in rows:
        sid = _i(r.get("sample_id"))
        cid = _i(r.get("core_id"))
        if sid is None or cid is None:
            continue
        prov = {}
        doi = _s(r.get(f"{api_name}_DOI"))
        if doi or _s(r.get(f"{api_name}_title")) or _s(r.get(f"{api_name}_method")):
            prov[var_key] = {"doi": doi, "title": _s(r.get(f"{api_name}_title")), "method": _s(r.get(f"{api_name}_method"))}
        frags[sid] = {
            "sample_id": sid,
            "core_id": cid,
            "depth_upper_cm": _f(r.get("sample_depth_upper_cm")),
            "depth_bottom_cm": _f(r.get("sample_depth_bottom_cm")),
            "depth_avg_cm": _f(r.get("sample_depth_average_cm")),
            "material_analyzed": _s(r.get("material_analyzed")),
            "replicate": _i(r.get("replicate")),
            var_key: _f(r.get(api_name)),
            "prov": prov,
        }
    return frags


def merge_sections(by_analysis):
    merged = {}
    for var_key, frags in by_analysis.items():
        for sid, frag in frags.items():
            m = merged.get(sid)
            if m is None:
                m = merged[sid] = {
                    "sample_id": sid, "core_id": frag["core_id"],
                    "depth_upper_cm": frag["depth_upper_cm"], "depth_bottom_cm": frag["depth_bottom_cm"],
                    "depth_avg_cm": frag["depth_avg_cm"], "material_analyzed": frag["material_analyzed"],
                    "replicate": frag["replicate"], "prov": {},
                }
            m[var_key] = frag.get(var_key)
            m["prov"].update(frag.get("prov", {}))
            # fill depth/material if this fragment has it and the base didn't
            for k in ("depth_upper_cm", "depth_bottom_cm", "depth_avg_cm", "material_analyzed"):
                if m.get(k) is None and frag.get(k) is not None:
                    m[k] = frag[k]
    return list(merged.values())


def core_rollups(sections):
    by_core = {}
    for s in sections:
        by_core.setdefault(s["core_id"], []).append(s)
    roll = {}
    for cid, secs in by_core.items():
        r = {}
        for vk in COLOR_VARS:
            withval = [x for x in secs if x.get(vk) is not None]
            r[f"has_{vk}"] = bool(withval)
            if withval:
                shallow = min(withval, key=lambda x: (x["depth_avg_cm"] if x["depth_avg_cm"] is not None else 1e9))
                r[f"{vk}_surf"] = shallow[vk]
            else:
                r[f"{vk}_surf"] = None
        roll[cid] = r
    return roll
