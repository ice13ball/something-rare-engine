# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Cuts the WOD23 test fixture out of the ORIGINAL NCEI files by HTTP byte range (nothing is downloaded whole)
and writes the oracle `expected.json` computed from those same originals with plain Python.

Run on the VPS (flat copy of this script and `wod_casts_rules.py` in one directory):
    python -I /var/tmp/wod-measure/wod_cut_fixture.py --out /var/tmp/wod-measure/fixture

Writes into --out: wod_osd_1975_cut.nc, wod_osd_2015_cut.nc, wod_ctd_2015_cut.nc, wod_pfl_2024_cut.nc,
(wod_osd_1970_cut.nc when a 1970-01-01 or a no-time-no-date cast exists), expected.json, listing_root.html,
listing_1800.html. The oracle schema is documented in the fixture README.

The oracle deliberately does NOT use numpy cumsum for ragged offsets (a plain `sum()` of the preceding row
sizes) and does NOT call any parser / pick function of `ingestion.wod_casts_*`: from the rules module it takes
only constants (DEPTHS, WINDOWS, VARS, NSTAR_K, BASE_URL)."""
from __future__ import annotations
import argparse
import json
import math
import os
import re
import socket
import sys
import time
import urllib.request
from datetime import date, timedelta

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(_HERE))           # repo layout: backend/ holds the `ingestion` package
try:
    from ingestion import wod_casts_rules as R
except ImportError:
    import wod_casts_rules as R

import numpy as np
import netCDF4

_orig_getaddrinfo = socket.getaddrinfo


def _ipv4_only(host, port, family=0, type=0, proto=0, flags=0):
    return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)


socket.getaddrinfo = _ipv4_only                      # the VPS has no IPv6 route to NCEI (urllib only)

TRIES = 3
FILL_LIMIT = -1.0e9                                  # WOD fill is -1e10; anything not above this is a fill
MAX_TOTAL_BYTES = 1_000_000
DAYS_1970 = (date(1970, 1, 1) - date(1770, 1, 1)).days
PER_CAST_VARS = ("lat", "lon", "time", "date", "wod_unique_cast", "Access_no", "WOD_cruise_identifier",
                 "originators_cruise_identifier", "Platform", "Ocean_Vehicle", "WMO_ID", "Institute", "Project",
                 "country", "dataset", "Temperature_Instrument", "Oxygen_Instrument", "real_time")
NC_VARS = tuple(v[1] for v in R.VARS)                # Temperature Salinity Oxygen Phosphate Silicate Nitrate
WOA_OF = {v[1]: v[2] for v in R.VARS}

SPECS = [
    {"cut": "wod_osd_1975_cut.nc", "src": "wod_osd_1975.nc", "year_dir": "1975",
     "ids": [8044758, 13485047, 11115466],
     "rules": ["zero_zrs", "time_lt1", "zero_frac", "lon_edge", "no_time_no_date", "no_oxygen_before_oxygen"]},
    {"cut": "wod_osd_2015_cut.nc", "src": "wod_osd_2015.nc", "year_dir": "2015",
     "ids": [17813889, 18954244],
     "rules": ["profile_flag_nonzero", "no_time_no_date", "no_oxygen_before_oxygen"]},
    {"cut": "wod_ctd_2015_cut.nc", "src": "wod_ctd_2015.nc", "year_dir": "2015",
     "ids": [17729190, 17384990],
     "rules": ["xctd", "lat_polar", "no_oxygen_before_oxygen"]},
    {"cut": "wod_pfl_2024_cut.nc", "src": "wod_pfl_2024.nc", "year_dir": "2024",
     "ids": [22708857, 22710905, 22705470],
     "rules": ["real_time_adjusted", "no_oxygen_before_oxygen"]},
    {"cut": "wod_osd_1970_cut.nc", "src": "wod_osd_1970.nc", "year_dir": "1970",
     "ids": [], "optional": True, "trap_exempt": True,
     "rules": ["time_1970", "no_time_no_date"]},
]


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def http_get(url: str) -> str:
    last = None
    for attempt in range(1, TRIES + 1):
        try:
            with urllib.request.urlopen(url, timeout=90) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:                                   # noqa: BLE001 - retried, then re-raised
            last = e
            time.sleep(2 * attempt)
    raise last


def write_listing(base: str, sub: str, path: str) -> int:
    """Keep only the `<a href=...>` lines of the NCEI directory page, otherwise unedited."""
    page = http_get(f"{base}/{sub}" if sub else f"{base}/")
    lines = [ln for ln in page.splitlines() if re.search(r"<a\s+href=", ln, re.I)]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return len(lines)


# ------------------------------------------------------------------------------------------ reading a file

def read_texts(var) -> list[str]:
    """Strings of a per-cast text variable (char matrix or vlen string), raw: auto chartostring is off."""
    a = var[:]
    out: list[str] = []
    kind = getattr(getattr(a, "dtype", None), "kind", "O")
    if kind in ("S", "U") and getattr(a, "ndim", 1) == 2:
        for row in a:
            if kind == "S":
                out.append(row.tobytes().split(b"\x00")[0].decode("utf-8", "replace").strip())
            else:
                out.append("".join(row.tolist()).split("\x00")[0].strip())
    else:
        for x in a:
            out.append(x.decode("utf-8", "replace").strip() if isinstance(x, bytes) else str(x).strip())
    return out


class Source:
    """One WOD file (remote or local) with the casts-sized arrays in memory. Ragged arrays stay in the file."""

    def __init__(self, ds):
        self.ds = ds
        ds.set_auto_mask(False)
        ds.set_auto_chartostring(False)
        v = ds.variables
        self.v = v
        self.wuc = np.asarray(v["wod_unique_cast"][:]).astype(np.int64)
        self.n = int(self.wuc.shape[0])
        self.lat = np.asarray(v["lat"][:], dtype=np.float64)
        self.lon = np.asarray(v["lon"][:], dtype=np.float64)
        self.time = np.asarray(v["time"][:], dtype=np.float64)
        self.date = np.asarray(v["date"][:]).astype(np.int64) if "date" in v else None
        self.zrs = np.asarray(v["z_row_size"][:]).astype(np.int64)
        self.zrs_list = self.zrs.tolist()
        self.rs: dict[str, np.ndarray] = {}
        self.rs_list: dict[str, list] = {}
        self.pf: dict[str, np.ndarray] = {}
        for nc in NC_VARS:
            if nc + "_row_size" in v and nc in v:
                a = np.asarray(v[nc + "_row_size"][:]).astype(np.int64)
                self.rs[nc] = a
                self.rs_list[nc] = a.tolist()
                self.pf[nc] = (np.asarray(v[nc + "_WODprofileflag"][:]).astype(np.int64)
                               if nc + "_WODprofileflag" in v else np.zeros(self.n, dtype=np.int64))
        self.dataset = read_texts(v["dataset"]) if "dataset" in v else None
        self.real_time = read_texts(v["real_time"]) if "real_time" in v else None
        self.has_zflag = "z_WODflag" in v


def plain_decode(t: float, d):
    """(date, precision, second_of_day) from WOD time / date with plain Python; (None, None, None) = no date."""
    if math.isfinite(t) and t >= 1.0:
        whole = math.floor(t)
        frac = t - whole
        try:
            day = date(1770, 1, 1) + timedelta(days=whole)
        except OverflowError:
            return None, None, None
        if frac > 0:
            return day, "second", min(round(frac * 86400), 86399)
        return day, "day", None
    if d is None or d <= 0:
        return None, None, None
    y, m, dd = d // 10000, (d // 100) % 100, d % 100
    if not (1770 <= y <= 2100) or m > 12:
        return None, None, None
    if m == 0:
        return date(y, 1, 1), "year", None
    if dd == 0:
        return date(y, m, 1), "month", None
    try:
        return date(y, m, dd), "day", None
    except ValueError:
        return None, None, None


def is_fill(x: float) -> bool:
    return not (x > FILL_LIMIT)                       # also true for NaN


def offset_of(rs_list: list, i: int) -> int:
    return sum(rs_list[:i])                           # plain sum of the preceding row sizes, no cumsum


# ------------------------------------------------------------------------------------------ the oracle

def pick_nearest(cands: list) -> list:
    """cands: tuples (j, z, ...). Per display depth the nearest candidate inside the R1 window
    (ties -> shallower, then lower j), or None. Own loop, not R.pick_levels."""
    out = []
    for target, (lo, hi) in zip(R.DEPTHS, R.WINDOWS):
        best = None
        best_key = None
        for c in cands:
            z = c[1]
            if z < lo or z > hi:
                continue
            key = (abs(z - target), z, c[0])
            if best_key is None or key < best_key:
                best, best_key = c, key
        out.append(best)
    return out


def build_cast(src: Source, i: int, file_name: str, reasons: list) -> dict:
    ds = src.ds
    zrs = src.zrs_list[i]
    zoff = offset_of(src.zrs_list, i)
    z_all = ds.variables["z"][zoff:zoff + zrs].tolist() if zrs > 0 else []
    zf_all = (ds.variables["z_WODflag"][zoff:zoff + zrs].tolist() if (zrs > 0 and src.has_zflag)
              else [0] * zrs)
    raw_t = float(src.time[i])
    raw_d = int(src.date[i]) if src.date is not None else None
    day, precision, sod = plain_decode(raw_t, raw_d)
    rec = {
        "wod_unique_cast": int(src.wuc[i]), "file": file_name,
        "lat": float(src.lat[i]), "lon": float(src.lon[i]),
        "raw_time": raw_t if math.isfinite(raw_t) else None, "raw_date": raw_d,
        "dataset": src.dataset[i] if src.dataset is not None else None,
        "z_row_size": zrs,
        "time": {"date": day.isoformat() if day else None, "precision": precision, "second_of_day": sod},
        "reasons": list(reasons),
        "vars": {},
    }
    good_levels: dict[str, list] = {}                 # WOA var key -> [(j, z, value)] good levels
    stored = False
    n_good_total = 0
    for nc in NC_VARS:
        if nc not in src.rs:
            continue
        rs = src.rs_list[nc][i]
        pf = int(src.pf[nc][i])
        block = {"row_size": rs, "profile_flag": pf, "row_size_mismatch": False, "n_valid": 0, "n_good": 0,
                 "levels": []}
        if rs > 0 and rs != zrs:
            block["row_size_mismatch"] = True          # unusable by definition; none seen in Phase 0
        elif rs > 0:
            off = offset_of(src.rs_list[nc], i)        # the variable's OWN offset, never z's
            vals = ds.variables[nc][off:off + rs].tolist()
            flags = ds.variables[nc + "_WODflag"][off:off + rs].tolist()
            cands = []
            for j in range(rs):
                if is_fill(vals[j]):
                    continue
                block["levels"].append([j, z_all[j], vals[j], int(flags[j]), int(zf_all[j])])
                block["n_valid"] += 1
                if flags[j] == 0 and zf_all[j] == 0 and pf == 0 and not is_fill(z_all[j]):
                    cands.append((j, z_all[j], vals[j]))
            block["n_good"] = len(cands)
            good_levels[WOA_OF[nc]] = cands
        if block["n_valid"] > 0:
            stored = True
        n_good_total += block["n_good"]
        rec["vars"][nc] = block
    picks = {}
    for nc in NC_VARS:
        if nc in src.rs:
            picks[WOA_OF[nc]] = [None if p is None else [p[0], p[1], p[2]]
                                 for p in pick_nearest(good_levels.get(WOA_OF[nc], []))]
    # N* = NO3 - 16 * PO4 at the SAME level j (both are stored on z's grid), both good
    no3 = {c[0]: c for c in good_levels.get("nitrate", [])}
    po4 = {c[0]: c for c in good_levels.get("phosphate", [])}
    ncands = [(j, no3[j][1], no3[j][2] - R.NSTAR_K * po4[j][2], no3[j][2], po4[j][2]) for j in sorted(no3) if j in po4]
    picks["nstar"] = [None if p is None else [p[0], p[1], p[2], p[3], p[4]] for p in pick_nearest(ncands)]
    rec["picks"] = picks
    if zrs == 0:
        rec["status"] = "no_depth_levels"
    elif not stored:
        rec["status"] = "no_values"
    elif n_good_total == 0:
        rec["status"] = "no_good"
    elif day is None:
        rec["status"] = "no_date"
    else:
        rec["status"] = "drawn"
    return rec


def build_casts(src: Source, idxs: list, file_name: str, reasons_by_id: dict) -> dict:
    out = {}
    for i in idxs:
        cid = int(src.wuc[i])
        out[str(cid)] = build_cast(src, int(i), file_name, reasons_by_id.get(cid, []))
    return out


def counts_of(casts: dict) -> dict:
    st = [c["status"] for c in casts.values()]
    c = {k: st.count(k) for k in ("no_depth_levels", "no_values", "no_good", "no_date", "drawn")}
    c["source"] = len(st)
    c["stored"] = c["no_good"] + c["no_date"] + c["drawn"]
    if c["source"] != c["no_depth_levels"] + c["no_values"] + c["stored"]:
        raise AssertionError("counts do not add up")
    if c["drawn"] != c["stored"] - c["no_good"] - c["no_date"]:
        raise AssertionError("drawn identity broken")
    return c


def divergent_casts(src: Source) -> dict:
    """Per variable: number of casts that HAVE the variable whose own offset differs from z's offset."""
    out = {}
    for nc in src.rs:
        out[nc] = sum(1 for i in range(src.n)
                      if src.rs_list[nc][i] > 0 and offset_of(src.rs_list[nc], i) != offset_of(src.zrs_list, i))
    return out


# ------------------------------------------------------------------------------------------ selection

def any_var_mask(src: Source) -> np.ndarray:
    m = np.zeros(src.n, dtype=bool)
    for nc in src.rs:
        m |= src.rs[nc] > 0
    return m


def select(src: Source, spec: dict, state: dict) -> tuple[dict, list]:
    chosen: dict[int, list] = {}
    notes: list[str] = []

    def add(i, why):
        chosen.setdefault(int(i), []).append(why)

    for cid in spec["ids"]:
        hits = np.flatnonzero(src.wuc == cid)
        if hits.size != 1:
            raise SystemExit(f"{spec['src']}: wod_unique_cast {cid} matched {hits.size} casts")
        add(hits[0], f"explicit:{cid}")
    for rule in spec["rules"]:
        if rule == "no_oxygen_before_oxygen":
            continue                                    # needs the final selection, below
        if rule == "zero_zrs":
            m = src.zrs == 0
        elif rule == "time_lt1":
            m = ~(src.time >= 1.0)
        elif rule == "zero_frac":
            m = (src.time >= 1.0) & (src.time == np.floor(src.time))
        elif rule == "lon_edge":
            m = np.abs(src.lon) >= 180.0
        elif rule == "profile_flag_nonzero":
            m = np.zeros(src.n, dtype=bool)
            for nc in src.rs:
                m |= (src.rs[nc] > 0) & (src.pf[nc] != 0)
        elif rule == "xctd":
            m = np.array([s == "XCTD" for s in (src.dataset or [])], dtype=bool)
        elif rule == "lat_polar":
            m = src.lat >= 89.9
        elif rule == "real_time_adjusted":
            m = np.array([s == "real-time adjusted data" for s in (src.real_time or [])], dtype=bool)
        elif rule == "time_1970":
            m = (src.time >= 1.0) & (np.floor(src.time) == DAYS_1970)
        elif rule == "no_time_no_date":
            if state.get("no_time_no_date") is not None:
                continue                                # one such cast in the whole fixture is enough
            m = np.zeros(src.n, dtype=bool)
            for i in np.flatnonzero(~(src.time >= 1.0)).tolist():
                if plain_decode(float(src.time[i]), int(src.date[i]) if src.date is not None else None)[0] is None:
                    m[i] = True
                    break
        else:
            raise SystemExit(f"unknown rule {rule}")
        if m.size == src.n and m.any():
            i = int(np.flatnonzero(m)[0])
            add(i, rule)
            if rule == "no_time_no_date":
                state["no_time_no_date"] = {"file": spec["src"], "wod_unique_cast": int(src.wuc[i])}
        else:
            notes.append(f"rule {rule}: no matching cast in {spec['src']}")
    if "no_oxygen_before_oxygen" in spec["rules"] and "Oxygen" in src.rs:
        ox = src.rs["Oxygen"]
        sel = sorted(chosen)
        with_ox = [i for i in sel if ox[i] > 0]
        if with_ox:
            nox = (ox == 0) & (src.zrs > 0) & any_var_mask(src)       # real casts that lack oxygen
            idx_all = np.arange(src.n)
            target = None
            for t in with_ox:                                         # first oxygen cast that CAN be preceded
                have_n = sum(1 for i in sel if i < t and ox[i] == 0 and src.zrs[i] > 0)
                avail_n = sum(1 for i in np.flatnonzero(nox & (idx_all < t)).tolist() if i not in chosen)
                if have_n + avail_n >= 2:
                    target = t
                    break
            if target is None:
                target = with_ox[-1]
                notes.append("fewer than 2 no-oxygen casts precede any selected oxygen cast; padded as far as possible")
            elif target != with_ox[0]:
                notes.append(f"no room before the first selected oxygen cast (index {with_ox[0]}); "
                             f"no-oxygen casts were placed before the oxygen cast at index {target}")
            have = [i for i in sel if i < target and ox[i] == 0 and src.zrs[i] > 0]
            need = 2 - len(have)
            if need > 0:
                pool = [i for i in np.flatnonzero(nox & (idx_all < target)).tolist()[:300] if i not in chosen]
                pool.sort(key=lambda i: (int(src.zrs[i]), i))         # short casts keep the fixture small
                extra = sorted(pool[:need])
                for i in extra:
                    add(i, "no_oxygen_before_oxygen")
                if len(extra) < need:
                    notes.append(f"only {len(extra) + len(have)} casts without oxygen precede the oxygen cast at "
                                 f"index {target}")
    return chosen, notes


# ------------------------------------------------------------------------------------------ writing the cut

def clone_variable(src_ds, dst, name: str, sizes_ok: dict):
    sv = src_ds.variables[name]
    for d in sv.dimensions:
        if d not in dst.dimensions:
            dst.createDimension(d, len(src_ds.dimensions[d]))
    dt = sv.dtype
    textual = dt is str or getattr(dt, "kind", "O") in ("S", "U")
    attrs = sv.ncattrs()
    fill = None
    if not textual:
        fill = sv.getncattr("_FillValue") if "_FillValue" in attrs else False
    dv = dst.createVariable(name, dt, sv.dimensions, zlib=(dt is not str), complevel=4, fill_value=fill)
    for a in attrs:
        if a != "_FillValue":
            dv.setncattr(a, sv.getncattr(a))
    return sv, dv


def write_cut(src: Source, idxs: list, out_path: str, source_name: str) -> None:
    sds = src.ds
    dst = netCDF4.Dataset(out_path, "w", format="NETCDF4")
    dst.set_auto_mask(False)
    dst.set_auto_chartostring(False)
    for a in sds.ncattrs():
        try:
            dst.setncattr(a, sds.getncattr(a))
        except Exception:                                   # noqa: BLE001 - an unwritable global attribute is not data
            pass
    dst.setncattr("fixture_source_file", source_name)
    dst.setncattr("fixture_wod_unique_casts", np.array([int(src.wuc[i]) for i in idxs], dtype=np.int64))
    casts_dim = sds.variables["z_row_size"].dimensions[0]
    dst.createDimension(casts_dim, len(idxs))
    groups = [("z", "z_row_size", src.zrs_list, ["z", "z_WODflag"])]
    for nc in src.rs:
        groups.append((nc, nc + "_row_size", src.rs_list[nc], [nc, nc + "_WODflag"]))
    # 1. ragged groups: re-pack every variable by its OWN row sizes
    for primary, rs_name, rs_list, members in groups:
        members = [m for m in members if m in sds.variables]
        obs_dim = sds.variables[primary].dimensions[0]
        for m in members:
            if sds.variables[m].dimensions != (obs_dim,):
                raise SystemExit(f"{m} is not on the observation dimension {obs_dim} of {primary}")
        if obs_dim in dst.dimensions:
            raise SystemExit(f"observation dimension {obs_dim} is shared between groups")
        total = sum(rs_list[i] for i in idxs)
        dst.createDimension(obs_dim, total if total > 0 else None)
        for m in members:
            sv, dv = clone_variable(sds, dst, m, {})
            if total > 0:
                parts = []
                for i in idxs:
                    r = rs_list[i]
                    if r > 0:
                        off = offset_of(rs_list, i)
                        parts.append(np.asarray(sv[off:off + r]))
                dv[:] = np.concatenate(parts)
    # 2. per-cast variables
    per_cast = list(PER_CAST_VARS) + [nc + "_WODprofileflag" for nc in src.rs] + ["z_row_size"] + \
               [nc + "_row_size" for nc in src.rs]
    for name in per_cast:
        if name not in sds.variables:
            continue
        sv = sds.variables[name]
        if not sv.dimensions or sv.dimensions[0] != casts_dim:
            log(f"skip {name}: first dimension is not {casts_dim}")
            continue
        sv, dv = clone_variable(sds, dst, name, {})
        textual = sv.dtype is str or getattr(sv.dtype, "kind", "O") in ("S", "U")
        if sv.ndim == 1 and not textual:
            full = np.asarray(sv[:])
            dv[:] = full[np.array(idxs, dtype=np.int64)]
        else:
            for k, i in enumerate(idxs):
                dv[k] = sv[int(i)]
    dst.close()


def process(spec: dict, base: str, out_dir: str, state: dict) -> dict | None:
    url = f"{base}/{spec['year_dir']}/{spec['src']}"
    ds = netCDF4.Dataset(url + "#mode=bytes")
    try:
        src = Source(ds)
        chosen, notes = select(src, spec, state)
        if spec.get("optional") and not chosen:
            return {"cut": spec["cut"], "written": False, "notes": notes + ["no matching cast: cut not written"]}
        idxs = sorted(chosen)
        reasons_by_id = {int(src.wuc[i]): chosen[i] for i in idxs}
        log(f"{spec['src']}: {src.n} casts, selecting {len(idxs)}: " +
            ", ".join(f"{int(src.wuc[i])}({'/'.join(chosen[i])})" for i in idxs))
        oracle = build_casts(src, idxs, spec["src"], reasons_by_id)
        out_path = os.path.join(out_dir, spec["cut"])
        write_cut(src, idxs, out_path, spec["src"])
    finally:
        ds.close()
    # verify on the CUT file: same oracle code, run over every cast of the cut, must equal the original's
    cut_ds = netCDF4.Dataset(out_path)
    try:
        cut = Source(cut_ds)
        again = build_casts(cut, list(range(cut.n)), spec["src"], reasons_by_id)
        if again != oracle:
            bad = [k for k in oracle if oracle[k] != again.get(k)]
            raise AssertionError(f"{spec['cut']}: cut file does not reproduce the oracle for casts {bad}")
        trap = divergent_casts(cut)
        if (not spec.get("trap_exempt") and "Oxygen" in cut.rs and any(cut.rs["Oxygen"] > 0)
                and trap.get("Oxygen", 0) < 1):
            raise AssertionError(f"{spec['cut']}: oxygen offsets do not diverge from z's - the trap did not survive")
    finally:
        cut_ds.close()
    if spec.get("trap_exempt"):
        notes = notes + ["single-purpose time fixture: exempt from the oxygen offset-divergence assertion"]
    return {"cut": spec["cut"], "written": True, "source_file": spec["src"], "notes": notes,
            "counts": counts_of(oracle), "trap_divergent_casts": trap, "casts": oracle,
            "bytes": os.path.getsize(out_path)}


def collapse_json(text: str) -> str:
    """indent=1 JSON with every list of plain scalars on one line (a level row stays one line)."""
    return re.sub(r"\[\n\s*([^\[\]{}]*?)\n\s*\]",
                  lambda m: "[" + re.sub(r"\s*\n\s*", " ", m.group(1)) + "]", text)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--base-url", default=R.BASE_URL)
    ap.add_argument("--only", default="", help="comma list of cut names (debug)")
    args = ap.parse_args()
    base = args.base_url.rstrip("/")
    os.makedirs(args.out, exist_ok=True)
    n_root = write_listing(base, "", os.path.join(args.out, "listing_root.html"))
    n_1800 = write_listing(base, "1800/", os.path.join(args.out, "listing_1800.html"))
    log(f"listings: root {n_root} href lines, 1800/ {n_1800} href lines")
    state: dict = {"no_time_no_date": None}
    files: dict = {}
    notes: dict = {}
    wanted = set(filter(None, args.only.split(",")))
    for spec in SPECS:
        if wanted and spec["cut"] not in wanted:
            continue
        res = None
        for attempt in range(1, TRIES + 1):
            snapshot = dict(state)
            try:
                res = process(spec, base, args.out, state)
                break
            except (OSError, RuntimeError) as e:            # includes "NetCDF: HDF error"
                state.clear()
                state.update(snapshot)
                log(f"{spec['src']}: attempt {attempt} failed: {type(e).__name__}: {e}")
                time.sleep(3 * attempt)
        if res is None:
            raise SystemExit(f"{spec['src']}: failed {TRIES} times")
        if not res["written"]:
            notes[spec["cut"]] = res["notes"]
            continue
        files[res["cut"]] = {"source_file": res["source_file"], "counts": res["counts"],
                             "trap_divergent_casts": res["trap_divergent_casts"], "notes": res["notes"],
                             "casts": res["casts"]}
        log(f"{res['cut']}: {res['bytes']} bytes, counts {res['counts']}, trap {res['trap_divergent_casts']}")
    total = sum(os.path.getsize(os.path.join(args.out, c)) for c in files)
    if total >= MAX_TOTAL_BYTES:
        raise AssertionError(f"cut files total {total} bytes, limit {MAX_TOTAL_BYTES}")
    doc = {
        "schema_version": 1,
        "constants": {"depths": list(R.DEPTHS), "windows": [list(w) for w in R.WINDOWS], "nstar_k": R.NSTAR_K,
                      "fill_limit": FILL_LIMIT},
        "no_time_no_date_cast": state["no_time_no_date"] or "none found in the cut sources "
                                                           "(build one synthetically from a real cast)",
        "time_1970_cast": ("found" if "wod_osd_1970_cut.nc" in files else "none found"),
        "notes": notes,
        "cut_bytes_total": total,
        "files": files,
    }
    with open(os.path.join(args.out, "expected.json"), "w", encoding="utf-8") as fh:
        fh.write(collapse_json(json.dumps(doc, indent=1, allow_nan=False)) + "\n")
    log(f"done: {len(files)} cut files, {total} bytes in total")
    print(json.dumps({"cut_files": sorted(files), "bytes_total": total,
                      "counts": {k: v["counts"] for k, v in files.items()},
                      "no_time_no_date_cast": doc["no_time_no_date_cast"],
                      "time_1970_cast": doc["time_1970_cast"]}, indent=1))


if __name__ == "__main__":
    main()
