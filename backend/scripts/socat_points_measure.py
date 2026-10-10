# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""One streaming pass over the SOCATv2026 zip that measures what the constants of
`ingestion/socat_points_rules.py` depend on. Prints ONE JSON document to stdout; progress goes to stderr.

Run (VPS, flat copy of the two ingestion modules next to this script):
    python -I /var/tmp/socat-measure/socat_points_measure.py <zip> [--base-zoom 10] [--piece-caps 8,8,8,8]

* Tiles are counted at the BASE zoom (default 10) per cruise, merged into the global dicts at each cruise
  change, and rolled up to z7..base. Base 11 or 12 is possible but its dicts may not fit MemoryMax=1.2G.
* "distinct positions" = distinct (expocode, round(lon*1e4), round(lat*1e4), UTC year); one dict per cruise,
  cleared at the cruise change (the file is one contiguous block per cruise).
No database, no network. Stdlib + the two ingestion modules only."""
from __future__ import annotations
import argparse
import json
import math
import os
import resource
import sys
import time
import types
from datetime import timedelta

# `python -I` drops the script directory from sys.path: put it back so the flat copies import.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from ingestion import socat_points_parse as P
    from ingestion import socat_points_rules as R
except ImportError:
    # flat layout (no package): socat_points_parse does `from ingestion import socat_points_rules as R`,
    # so give it a stand-in `ingestion` whose attribute is the flat rules module.
    import socat_points_rules as R
    _pkg = types.ModuleType("ingestion")
    _pkg.socat_points_rules = R
    sys.modules["ingestion"] = _pkg
    sys.modules["ingestion.socat_points_rules"] = R
    import socat_points_parse as P

PROGRESS_EVERY = 1_000_000
MIN_ZOOM = 7
# A contributor (cruise) is remembered for a tile only when it is a heavy one: keeps the dict small.
CONTRIB_MIN_OBS = 2000
CONTRIB_MIN_POS = 500
EXPECTED = {
    "rows": 44_018_204, "cruises": 8_310,
    "qc_rows": {"A": 5_847_993, "B": 22_280_448, "C": 9_336_714, "D": 6_553_049},
    "woce_2_rows": 44_018_204, "nan_fco2": 0, "nan_sst": 5_224, "nan_sal": 2_287_508,
}
_NAN = float("nan")


def rss_mb() -> float:
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(r / (1024 * 1024) if sys.platform == "darwin" else r / 1024, 1)


def roll(d: dict, from_z: int, to_z: int) -> dict:
    """Tile counts keyed (x << from_z) | y, summed up to zoom `to_z`."""
    if from_z == to_z:
        return d
    shift = from_z - to_z
    mask = (1 << from_z) - 1
    out: dict = {}
    get = out.get
    for k, v in d.items():
        nk = (((k >> from_z) >> shift) << to_z) | ((k & mask) >> shift)
        out[nk] = get(nk, 0) + v
    return out


def pct(sorted_vals: list, p: float):
    if not sorted_vals:
        return None
    i = max(0, min(len(sorted_vals) - 1, math.ceil(p * len(sorted_vals)) - 1))
    return sorted_vals[i]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("zip_path")
    ap.add_argument("--base-zoom", type=int, default=10, choices=(10, 11, 12))
    ap.add_argument("--piece-caps", default=None, help="override PIECE_MAX_VERTICES, e.g. 64,8,8,8")
    args = ap.parse_args()
    BZ = args.base_zoom
    if args.piece_caps:
        caps = tuple(int(c) for c in args.piece_caps.split(","))
        if len(caps) != len(R.LOD_CELLS):
            raise SystemExit("--piece-caps needs one value per LOD level")
        R.PIECE_MAX_VERTICES = caps          # the parser reads R.PIECE_MAX_VERTICES at call time
    caps_used = list(R.PIECE_MAX_VERTICES)

    t_start = time.time()
    n_tiles = 1 << BZ
    kx = n_tiles / 360.0
    inv4pi = 1.0 / (4.0 * math.pi)
    rad = math.pi / 180.0
    merc = R.MERC_LAT
    last = n_tiles - 1
    sin, log = math.sin, math.log

    # global counters
    rows = 0
    segments = 0
    seg_at_cap = 0
    cruises_summaries = 0
    expocodes: set = set()
    qc_rows: dict = {}
    woce_rows: dict = {}
    src_rows: dict = {}
    nan = {"fco2": 0, "sst": 0, "sal": 0}
    frac_rows = 0
    lon_min, lon_max, lat_min, lat_max = 1e9, -1e9, 1e9, -1e9
    lat_pm90 = 0
    year_min, year_max = 9999, 0
    summary_cruise_obs_max = (0, None)      # (n_obs, expocode) from CruiseSummary
    summary_rejected = 0
    multi_year_segments = 0

    # tiles at the base zoom: key -> count
    g_obs: dict = {}
    g_pos: dict = {}
    contrib: dict = {z: {} for z in range(MIN_ZOOM, BZ + 1)}

    # per-cruise state
    cur = None
    l_obs: dict = {}
    l_pos: dict = {}
    posd: dict = {}
    best_positions: list = []       # (count, expocode, lon, lat, year), top 5
    max_cruise_distinct = (0, None)

    lod = [{"pieces": 0, "vertices": 0, "obs": 0, "at_cap": 0, "max_vertices": 0}
           for _ in R.LOD_CELLS]

    def finish_cruise() -> None:
        nonlocal l_obs, l_pos, posd, max_cruise_distinct
        if cur is None:
            return
        if posd:
            m = max(posd.values())
            if len(posd) > max_cruise_distinct[0]:
                max_cruise_distinct = (len(posd), cur)
            if len(best_positions) < 5 or m > best_positions[-1][0]:
                pk = max(posd, key=posd.get)
                yo = pk % 128
                rest = pk // 128
                ly = rest % 2_000_000
                lx = rest // 2_000_000
                best_positions.append((m, cur, (lx - 1_800_000) / 1e4, (ly - 900_000) / 1e4, yo + 1900))
                best_positions.sort(key=lambda t: -t[0])
                del best_positions[5:]
        for k, v in l_obs.items():
            g_obs[k] = g_obs.get(k, 0) + v
        for k, v in l_pos.items():
            g_pos[k] = g_pos.get(k, 0) + v
        for z in range(MIN_ZOOM, BZ + 1):
            ro, rp = roll(l_obs, BZ, z), roll(l_pos, BZ, z)
            cz = contrib[z]
            for k, v in ro.items():
                p = rp.get(k, 0)
                if v >= CONTRIB_MIN_OBS or p >= CONTRIB_MIN_POS:
                    cz.setdefault(k, []).append((cur, v, p))
        l_obs = {}
        l_pos = {}
        posd = {}

    next_report = PROGRESS_EVERY
    stream = P.open_member(args.zip_path)
    for rec in P.iter_records(stream):
        if isinstance(rec, P.Segment):
            if rec.expocode != cur:
                finish_cruise()
                cur = rec.expocode
                expocodes.add(cur)
            n = len(rec.lon)
            rows += n
            segments += 1
            if n >= R.SEG_MAX_OBS:
                seg_at_cap += 1
            qc_rows[rec.qc_flag] = qc_rows.get(rec.qc_flag, 0) + n
            known = 0
            for v in (-1, 0, 1, 2, 3, 4, 9):
                c = rec.fco2_flag.count(v)
                if c:
                    woce_rows[v] = woce_rows.get(v, 0) + c
                    known += c
            if known != n:
                woce_rows["other"] = woce_rows.get("other", 0) + (n - known)
            known = 0
            for v in range(-1, 15):
                c = rec.fco2_src.count(v)
                if c:
                    src_rows[v] = src_rows.get(v, 0) + c
                    known += c
            if known != n:
                src_rows["other"] = src_rows.get("other", 0) + (n - known)
            nan["fco2"] += sum(1 for v in rec.fco2 if v != v)
            nan["sst"] += sum(1 for v in rec.sst if v != v)
            nan["sal"] += sum(1 for v in rec.sal if v != v)

            # fractional seconds: a row's time has a sub-second part
            us0 = rec.t0.microsecond
            if us0 == 0:
                frac_rows += sum(1 for d in rec.dt_s if d != int(d))
            else:
                frac_rows += sum(1 for d in rec.dt_s if (us0 + round(d * 1e6)) % 1_000_000)

            lon_min = min(lon_min, min(rec.lon))
            lon_max = max(lon_max, max(rec.lon))
            lat_min = min(lat_min, min(rec.lat))
            lat_max = max(lat_max, max(rec.lat))
            lat_pm90 += rec.lat.count(90.0) + rec.lat.count(-90.0)

            # UTC year per row: fast path when the whole segment is inside the first row's year
            y0 = rec.t0.year
            t_last = rec.t0 + timedelta(seconds=max(rec.dt_s))
            t_first = rec.t0 + timedelta(seconds=min(rec.dt_s))
            if t_last.year == y0 and t_first.year == y0:
                years = None
            else:
                multi_year_segments += 1
                years = [(rec.t0 + timedelta(seconds=d)).year for d in rec.dt_s]
            year_min = min(year_min, t_first.year)
            year_max = max(year_max, t_last.year)

            lo_arr, la_arr = rec.lon, rec.lat
            for i in range(n):
                lo = lo_arr[i]
                la = la_arr[i]
                x = int((lo + 180.0) * kx)
                if x > last:
                    x = last
                elif x < 0:
                    x = 0
                lc = merc if la > merc else (-merc if la < -merc else la)
                s = sin(lc * rad)
                y = int((0.5 - log((1.0 + s) / (1.0 - s)) * inv4pi) * n_tiles)
                if y > last:
                    y = last
                elif y < 0:
                    y = 0
                tk = (x << BZ) | y
                l_obs[tk] = l_obs.get(tk, 0) + 1
                yr = y0 if years is None else years[i]
                yo = yr - 1900
                if yo < 0:
                    yo = 0
                elif yo > 127:
                    yo = 127
                pk = ((round(lo * 1e4) + 1_800_000) * 2_000_000 + (round(la * 1e4) + 900_000)) * 128 + yo
                c = posd.get(pk)
                if c is None:
                    posd[pk] = 1
                    l_pos[tk] = l_pos.get(tk, 0) + 1
                else:
                    posd[pk] = c + 1

            if rows >= next_report:
                print(f"[progress] rows={rows:,} cruises={len(expocodes):,} elapsed={time.time() - t_start:.0f}s "
                      f"rss_mb={rss_mb()} z{BZ}_tiles={len(g_obs):,} cruise_distinct={len(posd):,}",
                      file=sys.stderr, flush=True)
                next_report += PROGRESS_EVERY
        elif isinstance(rec, P.LodPiece):
            d = lod[rec.level]
            d["pieces"] += 1
            nv = len(rec.vertices)
            d["vertices"] += nv
            d["obs"] += rec.n_obs
            if nv >= R.PIECE_MAX_VERTICES[rec.level]:
                d["at_cap"] += 1
            if nv > d["max_vertices"]:
                d["max_vertices"] = nv
        else:   # CruiseSummary
            cruises_summaries += 1
            summary_rejected += rec.n_rejected
            if rec.n_obs > summary_cruise_obs_max[0]:
                summary_cruise_obs_max = (rec.n_obs, rec.expocode)
    finish_cruise()
    print(f"[progress] done rows={rows:,} elapsed={time.time() - t_start:.0f}s rss_mb={rss_mb()}",
          file=sys.stderr, flush=True)

    # ── per-zoom tile statistics
    tiles_out: dict = {}
    for z in range(MIN_ZOOM, BZ + 1):
        to = roll(g_obs, BZ, z)
        tp = roll(g_pos, BZ, z)
        ov = sorted(to.values())
        pv = sorted(tp.values())
        cz = contrib[z]

        def top(d, other):
            out = []
            for k in sorted(d, key=d.get, reverse=True)[:10]:
                cs = sorted(cz.get(k, []), key=lambda t: -t[1])[:5]
                out.append({"z": z, "x": k >> z, "y": k & ((1 << z) - 1),
                            "obs": to.get(k, 0), "positions": tp.get(k, 0),
                            "est_bytes_28B_per_obs": 28 * to.get(k, 0),
                            "heavy_contributors_obs_pos": [[e, o, p] for e, o, p in cs]})
            return out

        tiles_out[f"z{z}"] = {
            "tiles": len(to),
            "obs_per_tile": {"p50": pct(ov, .5), "p99": pct(ov, .99), "p99.9": pct(ov, .999), "max": ov[-1] if ov else None},
            "positions_per_tile": {"p50": pct(pv, .5), "p99": pct(pv, .99), "p99.9": pct(pv, .999), "max": pv[-1] if pv else None},
            "top10_by_obs": top(to, tp),
            "top10_by_positions": top(tp, to),
        }

    # ── estimated bytes
    seg_bytes = 28 * rows + 100 * segments
    lod_out = []
    for lv, d in enumerate(lod):
        lod_out.append({"level": lv, "cell_deg": R.LOD_CELLS[lv], "max_vertices_cap": caps_used[lv], **d,
                        "est_bytes": 16 * d["vertices"] + 80 * d["pieces"]})

    exp = sorted(expocodes)
    charset = sorted(set("".join(exp)))
    lens: dict = {}
    for e in exp:
        lens[len(e)] = lens.get(len(e), 0) + 1
    qc_ok = all(qc_rows.get(k, 0) == v for k, v in EXPECTED["qc_rows"].items()) and \
        set(qc_rows) <= set(EXPECTED["qc_rows"])
    result = {
        "script": "socat_points_measure.py", "zip": os.path.basename(args.zip_path), "base_zoom": BZ,
        "rows": rows, "cruises": len(expocodes), "cruise_summaries": cruises_summaries,
        "qc_flag_rows": qc_rows, "fco2_flag_rows": {str(k): v for k, v in woce_rows.items()},
        "fco2_src_rows": {str(k): v for k, v in sorted(src_rows.items(), key=lambda kv: str(kv[0]))},
        "nan_counts": nan, "rows_with_fractional_seconds": frac_rows,
        "rows_rejected_by_parser_rules": summary_rejected,
        "max_obs_per_cruise": {"n_obs": summary_cruise_obs_max[0], "expocode": summary_cruise_obs_max[1]},
        "expocode_charset": "".join(charset), "expocode_length_histogram": {str(k): v for k, v in sorted(lens.items())},
        "expocode_examples": exp[:3] + exp[-3:],
        "lon_range": [lon_min, lon_max], "lat_range": [lat_min, lat_max], "rows_at_lat_pm90": lat_pm90,
        "utc_year_range": [year_min, year_max], "segments_spanning_a_year_boundary": multi_year_segments,
        "segments": {"count": segments, "at_SEG_MAX_OBS": seg_at_cap, "mean_rows": round(rows / max(1, segments), 2)},
        "max_obs_at_one_position": [{"count": c, "expocode": e, "lon": lo, "lat": la, "year": yr}
                                    for c, e, lo, la, yr in best_positions],
        "max_distinct_positions_in_one_cruise": {"n": max_cruise_distinct[0], "expocode": max_cruise_distinct[1]},
        "lod": lod_out,
        "tiles": tiles_out,
        "estimated_bytes": {
            "point_level_total_28B_per_row_plus_100B_per_segment": seg_bytes,
            "lod_per_level_16B_per_vertex_plus_80B_per_piece": [l["est_bytes"] for l in lod_out],
            "L0_z0_tile_estimate_bytes": lod_out[0]["est_bytes"],
        },
        "acceptance_vs_SCHEMA_NOTES": {
            "rows_ok": rows == EXPECTED["rows"], "cruises_ok": len(expocodes) == EXPECTED["cruises"],
            "qc_rows_ok": qc_ok,
            "woce_2_rows_ok": woce_rows.get(2, 0) == EXPECTED["woce_2_rows"] and len(woce_rows) == 1,
            "nan_fco2_ok": nan["fco2"] == EXPECTED["nan_fco2"], "nan_sst_ok": nan["sst"] == EXPECTED["nan_sst"],
            "nan_sal_ok": nan["sal"] == EXPECTED["nan_sal"],
        },
        "elapsed_s": round(time.time() - t_start, 1), "ru_maxrss_mb": rss_mb(),
    }
    json.dump(result, sys.stdout, indent=1, sort_keys=False, allow_nan=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
