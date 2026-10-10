# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Census of the WOD23 OSD + CTD + PFL files that fixes the constants of `ingestion/wod_casts_rules.py`
(POINT_MIN_ZOOM, LOD_LEVELS) and proves the cast ids are unique. Prints ONE JSON document to stdout;
progress goes to stderr.

Run on the VPS (flat copy of this script and `wod_casts_rules.py` in one directory):
    python -I /var/tmp/wod-measure/wod_casts_measure.py [--work-dir DIR] [--procs 4] > result.json

* The file list is re-derived from the year directories (`R.YEAR_DIR_RE` / `R.FILE_HREF_RE`), 225 files expected.
* Every file is opened remotely (`netCDF4.Dataset(url + "#mode=bytes")`, HTTP byte ranges, no download) and only
  the per-cast arrays are read: wod_unique_cast, lat, lon, time, date, z_row_size and the six <Var>_row_size.
* Up to 4 worker PROCESSES (not threads: netCDF4/HDF5 is not thread-safe). A file whose open or read fails
  (`NetCDF: HDF error` was seen on 3 of 225 opens) is retried 3 times. Each finished file is cached as a small
  .npz in --work-dir, so a re-run after a crash only redoes the missing files (resumable).
* Population for tiles / cells / the narrow-table estimate: "drawable candidates" = casts with z_row_size > 0, at
  least one <Var>_row_size > 0, finite in-range coordinates and a decodable date (R.decode_time).
No database. numpy + netCDF4 + the rules module only."""
from __future__ import annotations
import argparse
import json
import math
import multiprocessing as mp
import os
import resource
import socket
import sys
import time
import urllib.request

# `python -I` drops the script directory from sys.path: put it back so the flat copy of the rules imports.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(_HERE))           # repo layout: backend/ holds the `ingestion` package
try:
    from ingestion import wod_casts_rules as R
except ImportError:
    import wod_casts_rules as R

import numpy as np

# The VPS has no IPv6 route to NCEI: resolve IPv4 only for urllib (netCDF's libcurl is left alone).
_orig_getaddrinfo = socket.getaddrinfo


def _ipv4_only(host, port, family=0, type=0, proto=0, flags=0):
    return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)


socket.getaddrinfo = _ipv4_only

INST_ORDER = {"osd": 0, "ctd": 1, "pfl": 2}
OPEN_TRIES = 3
BYTES_PER_CELL_ROW = 210               # brief: bytes per (cell, year) row
BYTES_PER_CELL_ROW_HONEST = 300        # P21: honest figure until pg_column_size is measured on a real insert
BYTES_PER_NARROW_ROW = 104
CAT = {None: 0, "second": 1, "day": 2, "month": 3, "year": 4}
CAT_NAMES = ("none", "second", "day", "month", "year")
EXPECTED = {
    "casts_osd": 3_261_155, "casts_ctd": 1_164_910, "casts_pfl": 3_227_923,
    "with_any_variable": 7_434_846, "osd_z_row_size_0": 162_345,
}


def rss_mb(who=resource.RUSAGE_SELF) -> float:
    r = resource.getrusage(who).ru_maxrss
    return round(r / (1024 * 1024) if sys.platform == "darwin" else r / 1024, 1)


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def http_get(url: str, tries: int = 3) -> str:
    last = None
    for attempt in range(1, tries + 1):
        try:
            with urllib.request.urlopen(url, timeout=90) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:                                   # noqa: BLE001 - retried, then re-raised
            last = e
            time.sleep(2 * attempt)
    raise last


def list_files(base: str) -> list[dict]:
    root = http_get(base + "/")
    years = sorted(set(R.YEAR_DIR_RE.findall(root)))
    found: dict[str, dict] = {}
    for y in years:
        page = http_get(f"{base}/{y}/")
        for m in R.FILE_HREF_RE.finditer(page):
            name = m.group(1)
            found.setdefault(name, {"name": name, "inst": m.group(2), "year": int(m.group(3)),
                                    "url": f"{base}/{y}/{name}"})
    return sorted(found.values(), key=lambda f: (INST_ORDER[f["inst"]], f["year"], f["name"]))


# ---------------------------------------------------------------------------------------------- worker side

def decode_vec(t: np.ndarray, d: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Category code (CAT) and calendar year per cast, matching R.decode_time. Whole-day / fractional `time`
    values are vectorised; everything else (fills, huge values) goes through R.decode_time itself."""
    n = len(t)
    cat = np.zeros(n, dtype=np.int8)
    year = np.zeros(n, dtype=np.int16)
    ok = np.isfinite(t) & (t >= 1.0) & (t < 200000.0)
    if ok.any():
        tt = t[ok]
        whole = np.floor(tt)
        frac = tt - whole
        cat[ok] = np.where(frac > 0, CAT["second"], CAT["day"]).astype(np.int8)
        days = whole.astype(np.int64).astype("timedelta64[D]")
        yr = (np.datetime64("1770-01-01", "D") + days).astype("datetime64[Y]").astype(np.int64) + 1970
        year[ok] = yr.astype(np.int16)
    for i in np.flatnonzero(~ok).tolist():
        try:
            day, _ts, c = R.decode_time(float(t[i]), int(d[i]))
        except (OverflowError, ValueError):
            continue
        if c is not None and day is not None:
            cat[i] = CAT[c]
            year[i] = day.year
    return cat, year


def read_file(ds) -> dict:
    ds.set_auto_mask(False)
    v = ds.variables
    wuc = np.asarray(v["wod_unique_cast"][:]).astype(np.int64)
    n = int(wuc.shape[0])
    lat = np.asarray(v["lat"][:], dtype=np.float64)
    lon = np.asarray(v["lon"][:], dtype=np.float64)
    tm = np.asarray(v["time"][:], dtype=np.float64)
    date = (np.asarray(v["date"][:]).astype(np.int64) if "date" in v else np.zeros(n, dtype=np.int64))
    zrs = np.asarray(v["z_row_size"][:]).astype(np.int64)
    if not (len(lat) == len(lon) == len(tm) == len(date) == len(zrs) == n):
        raise ValueError("per-cast arrays differ in length")
    any_var = np.zeros(n, dtype=bool)
    per_var = {}
    for _code, nc, _woa, _scale in R.VARS:
        name = nc + "_row_size"
        if name in v:
            rs = np.asarray(v[name][:]).astype(np.int64)
            if len(rs) != n:
                raise ValueError(f"{name} length {len(rs)} != casts {n}")
            per_var[nc] = int((rs > 0).sum())
            any_var |= rs > 0
        else:
            per_var[nc] = None
    valid_xy = (np.isfinite(lat) & np.isfinite(lon) & (np.abs(lat) <= 90.0) & (np.abs(lon) <= 180.0))
    cat, year = decode_vec(tm, date)
    cand = any_var & (zrs > 0) & valid_xy & (cat > 0)
    keys = np.zeros(0, dtype=np.int64)
    if cand.any():
        x, y = R.to_3857(lon[cand], lat[cand])
        keys = R.morton_key(x, y).astype(np.int64)
    yrs = year[cand].astype(np.int16)
    meta = {
        "casts": n, "with_any_var": int(any_var.sum()), "z_row_size_0": int((zrs == 0).sum()),
        "any_var_and_z": int((any_var & (zrs > 0)).sum()), "candidates": int(cand.sum()),
        "invalid_coords": int((~valid_xy).sum()), "per_var_casts": per_var,
        "time_categories": [int((cat == k).sum()) for k in range(5)],
        "year_min": int(year[cat > 0].min()) if (cat > 0).any() else None,
        "year_max": int(year[cat > 0].max()) if (cat > 0).any() else None,
    }
    return {"wuc": wuc.astype(np.int32), "keys": keys, "years": yrs, "meta": meta}


def measure_file(job: tuple) -> dict:
    idx, name, url, work_dir = job
    out = os.path.join(work_dir, name[:-3] + ".npz")
    if os.path.exists(out):
        return {"idx": idx, "name": name, "cached": True}
    import netCDF4                                                # imported late: each process owns its HDF5
    t0 = time.time()
    last = "unknown"
    for attempt in range(1, OPEN_TRIES + 1):
        try:
            ds = netCDF4.Dataset(url + "#mode=bytes")
            try:
                res = read_file(ds)
            finally:
                ds.close()
            tmp = out[:-4] + ".tmp.npz"
            np.savez(tmp, wuc=res["wuc"], keys=res["keys"], years=res["years"],
                     meta=np.array(json.dumps(res["meta"])))
            os.replace(tmp, out)
            return {"idx": idx, "name": name, "cached": False, "seconds": round(time.time() - t0, 1),
                    "attempts": attempt, "casts": res["meta"]["casts"]}
        except Exception as e:                                    # noqa: BLE001 - retried, then reported
            last = f"{type(e).__name__}: {e}"
            time.sleep(3 * attempt)
    return {"idx": idx, "name": name, "error": last}


# ---------------------------------------------------------------------------------------------- parent side

def pct(sorted_vals: np.ndarray, p: float):
    n = len(sorted_vals)
    if n == 0:
        return None
    return int(sorted_vals[max(0, min(n - 1, math.ceil(p * n) - 1))])


def aggregate(files: list[dict], work_dir: str, t_start: float) -> dict:
    per_inst: dict[str, dict] = {}
    wl, fl, kl, yl = [], [], [], []
    cat_total = {i: [0] * 5 for i in INST_ORDER}
    year_min = year_max = None
    per_file = []
    for fi, f in enumerate(files):
        z = np.load(os.path.join(work_dir, f["name"][:-3] + ".npz"), allow_pickle=False)
        meta = json.loads(str(z["meta"]))
        inst = f["inst"]
        a = per_inst.setdefault(inst, {"files": 0, "casts": 0, "with_any_var": 0, "z_row_size_0": 0,
                                       "any_var_and_z": 0, "candidates": 0, "invalid_coords": 0,
                                       "per_var_casts": {}})
        a["files"] += 1
        for k in ("casts", "with_any_var", "z_row_size_0", "any_var_and_z", "candidates", "invalid_coords"):
            a[k] += meta[k]
        for nc, c in meta["per_var_casts"].items():
            if c is not None:
                a["per_var_casts"][nc] = a["per_var_casts"].get(nc, 0) + c
        for k in range(5):
            cat_total[inst][k] += meta["time_categories"][k]
        if meta["year_min"] is not None:
            year_min = meta["year_min"] if year_min is None else min(year_min, meta["year_min"])
            year_max = meta["year_max"] if year_max is None else max(year_max, meta["year_max"])
        wl.append(z["wuc"])
        fl.append(np.full(len(z["wuc"]), fi, dtype=np.int16))
        kl.append(z["keys"])
        yl.append(z["years"])
        per_file.append([f["name"], meta["casts"], meta["with_any_var"], meta["z_row_size_0"], meta["candidates"]])

    # --- duplicate wod_unique_cast across ALL files -------------------------------------------------------
    allw = np.concatenate(wl)
    fidx = np.concatenate(fl)
    del wl, fl
    order = np.argsort(allw, kind="stable")
    sw = allw[order]
    same = sw[1:] == sw[:-1]
    dup_ids = np.unique(sw[np.flatnonzero(same)])
    examples = []
    for cid in dup_ids[:10].tolist():
        lo = int(np.searchsorted(sw, cid, "left"))
        hi = int(np.searchsorted(sw, cid, "right"))
        examples.append({"wod_unique_cast": cid, "files": [files[int(fidx[order[p]])]["name"]
                                                          for p in range(lo, hi)]})
    duplicates = {"total_casts": int(allw.shape[0]), "distinct_ids": int(allw.shape[0] - same.sum()),
                  "duplicate_ids": int(dup_ids.shape[0]), "extra_rows": int(same.sum()), "examples": examples}
    del allw, fidx, order, sw, same

    # --- tiles and (cell, year) rows over the drawable candidates -----------------------------------------
    keys = np.concatenate(kl)
    yrs = np.concatenate(yl).astype(np.int64)
    del kl, yl
    tiles = {}
    for zz in range(4, 13):
        t = keys >> (2 * (R.GRID_BITS - zz))
        u, c = np.unique(t, return_counts=True)
        sc = np.sort(c)
        top = []
        for k in np.argsort(-c, kind="stable")[:10].tolist():
            p = int(u[k])
            top.append({"z": zz, "x": int(R._compact(p)), "y": int(R._compact(p >> 1)), "casts": int(c[k])})
        tiles[f"z{zz}"] = {"occupied": int(u.shape[0]), "p50": pct(sc, 0.50), "p99": pct(sc, 0.99),
                           "p99_9": pct(sc, 0.999), "max": int(sc[-1]) if len(sc) else None, "top10": top}
        del t, u, c, sc
    ymin = int(yrs.min()) if len(yrs) else 1770
    ymax = int(yrs.max()) if len(yrs) else 1770
    if ymin < 1770 or ymax - 1770 >= 512:
        raise ValueError(f"year range {ymin}..{ymax} does not fit the 9-bit packing")
    cells = {}
    for bits in (6, 8, 10, 12):
        cell = keys >> (2 * (R.GRID_BITS - bits))
        rows = int(np.unique((cell << 9) | (yrs - 1770)).shape[0])
        cells[f"level_bits_{bits}"] = {"rows": rows, "bytes_at_210": rows * BYTES_PER_CELL_ROW,
                                       "bytes_at_300": rows * BYTES_PER_CELL_ROW_HONEST}
        del cell
    lod_by_min_zoom = {}
    for pmz in (6, 8):
        bits_list = [R.level_bits(lv) for lv in range(pmz // 2)]
        r = sum(cells[f"level_bits_{b}"]["rows"] for b in bits_list)
        lod_by_min_zoom[str(pmz)] = {"level_bits": bits_list, "rows": r, "bytes_at_210": r * BYTES_PER_CELL_ROW,
                                     "bytes_at_300": r * BYTES_PER_CELL_ROW_HONEST,
                                     "within_1_2GB_at_300": r * BYTES_PER_CELL_ROW_HONEST <= 1.2e9}
    candidates = int(keys.shape[0])

    inst_casts = {i: per_inst.get(i, {}).get("casts", 0) for i in INST_ORDER}
    with_any = sum(a["with_any_var"] for a in per_inst.values())
    got = {"casts_osd": inst_casts["osd"], "casts_ctd": inst_casts["ctd"], "casts_pfl": inst_casts["pfl"],
           "with_any_variable": with_any, "osd_z_row_size_0": per_inst.get("osd", {}).get("z_row_size_0", 0)}
    acceptance = {k: {"expected": EXPECTED[k], "got": got[k], "ok": EXPECTED[k] == got[k]} for k in EXPECTED}
    return {
        "files": len(files),
        "files_expected": 225,
        "acceptance": acceptance,
        "acceptance_all_ok": all(x["ok"] for x in acceptance.values()),
        "per_instrument": per_inst,
        "time_categories": {i: dict(zip(CAT_NAMES, cat_total[i])) for i in cat_total},
        "year_min": year_min, "year_max": year_max,
        "duplicates": duplicates,
        "drawable_candidates": candidates,
        "narrow_table_estimate": {"bytes_per_row": BYTES_PER_NARROW_ROW,
                                  "bytes": candidates * BYTES_PER_NARROW_ROW},
        "casts_per_tile": tiles,
        "cell_year_rows": cells,
        "lod_by_point_min_zoom": lod_by_min_zoom,
        "population_note": "tiles, cells and the narrow table count drawable candidates: z_row_size>0, any "
                           "<Var>_row_size>0, finite in-range lat/lon, decodable date",
        "per_file": per_file,
        "elapsed_s": round(time.time() - t_start, 1),
        "rss_mb_parent": rss_mb(),
        "rss_mb_largest_child": rss_mb(resource.RUSAGE_CHILDREN),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=R.BASE_URL)
    ap.add_argument("--work-dir", default=os.path.join(_HERE, "work"))
    ap.add_argument("--procs", type=int, default=4, help="worker processes, capped at 4")
    ap.add_argument("--only", default="", help="comma list of file names (smoke test); skips the 225 check")
    ap.add_argument("--list-only", action="store_true", help="print the derived file list and exit")
    args = ap.parse_args()
    t_start = time.time()
    base = args.base_url.rstrip("/")
    files = list_files(base)
    log(f"derived {len(files)} files from {base}")
    if args.list_only:
        print(json.dumps([[f["name"], f["url"]] for f in files], indent=0))
        return
    if args.only:
        wanted = set(args.only.split(","))
        files = [f for f in files if f["name"] in wanted]
    os.makedirs(args.work_dir, exist_ok=True)
    procs = max(1, min(4, args.procs))
    # big PFL files first so the tail of the run is not one slow file
    jobs = [(i, f["name"], f["url"], args.work_dir) for i, f in enumerate(files)]
    jobs.sort(key=lambda j: (-INST_ORDER[files[j[0]]["inst"]], j[0]))
    errors = []
    done = 0
    ctx = mp.get_context("fork")
    with ctx.Pool(procs, maxtasksperchild=6) as pool:
        for res in pool.imap_unordered(measure_file, jobs, chunksize=1):
            done += 1
            if "error" in res:
                errors.append(res)
                log(f"[{done}/{len(jobs)}] FAILED {res['name']}: {res['error']}")
            else:
                log(f"[{done}/{len(jobs)}] {res['name']} "
                    f"{'cached' if res.get('cached') else str(res['seconds']) + 's x' + str(res['attempts'])} "
                    f"| elapsed {round(time.time() - t_start)}s | parent rss {rss_mb()} MB "
                    f"| largest child {rss_mb(resource.RUSAGE_CHILDREN)} MB")
    if errors:
        print(json.dumps({"failed_files": errors, "hint": "re-run the same command: finished files are cached"},
                         indent=1))
        sys.exit(3)
    doc = aggregate(files, args.work_dir, t_start)
    print(json.dumps(doc, indent=1, allow_nan=False))
    if not args.only and not doc["acceptance_all_ok"]:
        log("ACCEPTANCE MISMATCH - the plan stops here")
        sys.exit(4)


if __name__ == "__main__":
    main()
