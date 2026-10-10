# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""WOD23 casts parser against the REAL fixture (backend/tests/fixtures/wod_casts, oracle = expected.json, schema in
the README beside it). The oracle was computed from the original files with plain Python and its own offsets."""
import collections
import functools
import json
import math
import pathlib
import shutil
from datetime import date

import netCDF4
import numpy as np
import pytest

from ingestion import wod_casts_rules as R
from ingestion.wod_casts_parse import META_FIELDS, SchemaError, iter_casts, read_file_info

FIX = pathlib.Path(__file__).parent / "fixtures" / "wod_casts"
EXP = json.loads((FIX / "expected.json").read_text())
CUTS = sorted(p.name for p in FIX.glob("wod_*_cut.nc"))
NAME_TO_CODE = {name: code for code, name, _, _ in R.VARS}
STORED_STATUSES = ("no_good", "no_date", "drawn")


@functools.lru_cache(maxsize=None)
def _parsed(name):
    stats = collections.Counter()
    casts = {c.cast_id: c for c in iter_casts(FIX / name, name.split("_")[1], stats)}
    return casts, stats


def _parse_path(path):
    stats = collections.Counter()
    casts = {c.cast_id: c for c in iter_casts(path, path.name.split("_")[1], stats)}
    return casts, stats


def _oracle_casts(name):
    return {int(cid): e for cid, e in EXP["files"][name]["casts"].items()}


def _same(a, b):
    return (math.isclose(a[0], b[0], rel_tol=1e-6, abs_tol=1e-9) and math.isclose(a[1], b[1], rel_tol=1e-6, abs_tol=1e-9)
            and a[2] == b[2] and a[3] == b[3])


def test_every_cut_file_has_an_oracle_entry():           # an empty glob must not parametrize into silence
    assert len(CUTS) == 5 and CUTS == sorted(EXP["files"])


@pytest.mark.parametrize("name", CUTS)
def test_values_match_the_source_oracle(name):           # own cumsum per variable, never z's; P7
    casts, _ = _parsed(name)
    for cid, e in _oracle_casts(name).items():
        if e["status"] in ("no_depth_levels", "no_values"):
            assert cid not in casts
            continue
        assert cid in casts, cid
        c = casts[cid]
        assert len(c.depth) == len(c.depth_flag)
        for nc, v in e["vars"].items():
            code = NAME_TO_CODE[nc]
            idx = R.VAR_CODE_TO_INDEX[code]
            levels = v["levels"]
            assert c.n_src[idx] == v["n_valid"], (cid, nc)
            assert c.pflag[idx] == (v["profile_flag"] if v["row_size"] > 0 else None), (cid, nc)
            if not levels:
                assert c.values[code] is None and c.flags[code] is None, (cid, nc)
                continue
            assert c.values[code] is not None, (cid, nc)             # P7: a variable of the oracle exists
            assert len(c.values[code]) == len(c.depth) == len(c.flags[code]), (cid, nc)
            stored = [(c.depth[k], x, c.flags[code][k], c.depth_flag[k])
                      for k, x in enumerate(c.values[code]) if x is not None]
            want = [(l[1], l[2], l[3], l[4]) for l in levels]
            if len(want) <= R.MAX_LEVELS:                            # P7: nothing thinned -> every level exact
                assert len(stored) == len(want), (cid, nc)
                for s, w in zip(stored, want):
                    assert _same(s, w), (cid, nc, s, w)
            else:                                                    # thinned levels are absent, never different
                assert len(stored) <= R.MAX_LEVELS, (cid, nc)
                it = iter(want)
                for s in stored:
                    assert any(_same(s, w) for w in it), (cid, nc, s)
        assert c.n_good == sum(v["n_good"] for v in e["vars"].values()), cid


@pytest.mark.parametrize("name", CUTS)
def test_picks_match_the_oracle_and_survive_thinning(name):
    casts, _ = _parsed(name)
    for cid, e in _oracle_casts(name).items():
        if cid not in casts:
            continue
        c = casts[cid]
        assert set(e["picks"]) <= set(R.PICK_VARS)
        for var in R.PICK_VARS:
            want = e["picks"].get(var, [None] * len(R.DEPTHS))
            assert len(want) == len(R.DEPTHS)
            for d, p in enumerate(want):
                expect = None if p is None else R.scaled(p[2], var)   # [j, z, value] / [j, z, nstar, no3, po4]
                assert c.picks[R.slot(var, d)] == expect, (cid, var, R.DEPTHS[d])
        z = np.array(c.depth, dtype=np.float32)                       # re-picking from the STORED arrays
        depth_good = np.frombuffer(c.depth_flag, dtype=np.uint8) == 0
        stored_good = {}
        for code, vals in c.values.items():
            if vals is None:
                continue
            vi = R.VAR_CODE_TO_INDEX[code]
            flags = np.frombuffer(c.flags[code], dtype=np.uint8)
            good = np.array([x is not None for x in vals]) & (flags == 0) & depth_good & (c.pflag[vi] == 0)
            stored_good[code] = good
            var = R.VARS[vi][2]
            for d, j in enumerate(R.pick_levels(z, good)):
                assert c.picks[R.slot(var, d)] == (None if j is None else R.scaled(vals[j], var)), (cid, var, d)
        if "n" in stored_good and "p" in stored_good:
            for d, j in enumerate(R.pick_levels(z, stored_good["n"] & stored_good["p"])):
                got = c.picks[R.slot("nstar", d)]
                if j is None:
                    assert got is None
                else:
                    ns = c.values["n"][j] - R.NSTAR_K * c.values["p"][j]
                    assert got == R.scaled(ns, "nstar"), (cid, d)


def test_float_oxygen_fills_dropped_first():             # 22708857: 1,960 slots, 979 valid O2 (about 50 % fill)
    casts, _ = _parsed("wod_pfl_2024_cut.nc")
    c = casts[22708857]
    o = [v for v in c.values["o"] if v is not None]
    assert 0 < len(o) <= R.MAX_LEVELS
    assert len(o) > R.MAX_LEVELS // 2                    # P6: thinned from the valid values, not from the fill grid
    assert all(v > -1e9 for v in o)
    assert len(c.depth) <= 6 * R.MAX_LEVELS
    assert c.n_src[R.VAR_CODE_TO_INDEX["o"]] == EXP["files"]["wod_pfl_2024_cut.nc"]["casts"]["22708857"]["vars"]["Oxygen"]["n_valid"]
    assert c.values["n"] is None and c.flags["n"] is None          # Nitrate has no rows in this cast


@pytest.mark.parametrize("name", CUTS)
def test_counts_per_file_equal_the_oracle(name):         # R11 arithmetic on real casts, P5
    casts, stats = _parsed(name)
    want = EXP["files"][name]["counts"]
    assert stats["source"] == want["source"] and len(casts) == want["stored"]
    assert stats["no_depth_levels"] == want["no_depth_levels"] and stats["no_values"] == want["no_values"]
    assert stats["no_good"] == want["no_good"] and stats["no_date"] == want["no_date"]
    assert stats["bad_coords"] == 0 and not [k for k in stats if k.startswith(("rowsize_mismatch", "all_fill"))]
    drawn = sum(1 for c in casts.values() if c.n_good > 0 and c.year is not None)
    assert drawn == want["drawn"] == len(casts) - stats["no_good"] - stats["no_date"]
    assert stats["source"] == stats["no_depth_levels"] + stats["no_values"] + len(casts)


@pytest.mark.parametrize("name", CUTS)
def test_time_categories_on_real_casts(name):            # month / day / second precision, fill time, 1970-01-01
    casts, _ = _parsed(name)
    for cid, e in _oracle_casts(name).items():
        if cid not in casts:
            continue
        c, t = casts[cid], e["time"]
        assert (c.cast_date.isoformat() if c.cast_date else None) == t["date"], cid
        assert c.time_precision == t["precision"], cid
        assert c.year == (int(t["date"][:4]) if t["date"] else None), cid
        if t["second_of_day"] is None:
            assert c.cast_time is None, cid
        else:
            ct = c.cast_time
            assert ct.tzinfo is not None and ct.date() == c.cast_date
            assert ct.hour * 3600 + ct.minute * 60 + ct.second == t["second_of_day"], cid


def test_xctd_dataset_and_metadata():
    casts, _ = _parsed("wod_ctd_2015_cut.nc")
    assert casts[17467111].dataset == "XCTD" and casts[17443609].dataset == "CTD"
    c = _parsed("wod_osd_2015_cut.nc")[0][22386903]
    assert c.dataset == "bottle/rosette/net" and c.access_no == 248064
    assert c.meta["cruise"] == "AU006994" and c.meta["country"] == "AUSTRALIA"
    assert c.meta["platform"].startswith("AURORA AUSTRALIS") and c.meta["t_instrument"] == "CTD: TYPE UNKNOWN"
    assert c.meta["o2_instrument"] is None and c.meta["wmo_id"] is None and c.meta["vehicle"] is None
    c = _parsed("wod_osd_2015_cut.nc")[0][18954244]                  # empty strings are None
    assert c.meta["cruise"] is None and c.meta["platform"] is None and c.meta["country"] == "IRELAND"
    c = _parsed("wod_pfl_2024_cut.nc")[0][22708857]
    assert c.meta["wmo_id"] == "6902961" and c.meta["orig_cruise"] == "6902961" and c.meta["cruise"] == "FR017070"
    assert c.meta["vehicle"].startswith("PROVOR") and c.meta["platform"] is None
    assert c.meta["institute"] == "MERCATOR-CORIOLIS MISSION GROUP (GMMC)" and c.meta["real_time"] is None
    assert set(c.meta) == set(META_FIELDS) and len(c.meta) == 11
    assert _parsed("wod_pfl_2024_cut.nc")[0][22432373].meta["real_time"] == "real-time adjusted data"


def test_file_info_and_flag_meanings():
    info = read_file_info(FIX / "wod_osd_1975_cut.nc")
    assert (info.instrument, info.year, info.n_casts) == ("osd", 1975, EXP["files"]["wod_osd_1975_cut.nc"]["counts"]["source"])
    assert set(info.flag_meanings) == {"z", "Temperature", "Salinity", "Oxygen", "Phosphate", "Silicate", "Nitrate"}
    assert info.flag_meanings["z"] == {0: "accepted", 1: "duplicate_or_inversion", 2: "density_inversion"}
    assert info.flag_meanings["Oxygen"][0] == "accepted" and info.flag_meanings["Oxygen"][1] == "range_out"
    pfl = read_file_info(FIX / "wod_pfl_2024_cut.nc")
    assert set(pfl.flag_meanings) == {"z", "Temperature", "Salinity", "Oxygen", "Nitrate"} and pfl.year == 2024


def _edited(tmp_path, source, edit):
    dst = tmp_path / source.replace("_cut", "_edit")
    shutil.copy(FIX / source, dst)
    with netCDF4.Dataset(dst, "a") as ds:
        ds.set_auto_mask(False)
        edit(ds)
    return dst


def test_synthetic_no_time_no_date_nan_coords_and_absurd_time(tmp_path):
    """P24: the sources hold no cast with neither time nor date, so one is built from a real cast (time -> fill,
    date -> 0). Ids of wod_osd_2015_cut.nc in file order: 22386903, 17815565, 17815566, 18954244, 17813889."""
    assert "none found" in EXP["no_time_no_date_cast"]

    def edit(ds):
        for i in (0, 1):                                  # cast 0: good value, no time, no date -> no_date
            ds["time"][i] = -1e10                         # cast 1: the same, but every profile flag bad -> no_good only
            ds["date"][i] = 0
        for i in (1, 2):                                  # cast 2: all profile flags bad, date intact -> no_good
            for _, name, _, _ in R.VARS:
                ds[name + "_WODprofileflag"][i] = 1
        ds["lat"][3] = np.nan                             # cast 3: NaN latitude -> dropped, counted, no Morton key
        ds["time"][4] = 1e12                              # cast 4: absurd time -> OverflowError inside decode -> date used

    casts, stats = _parse_path(_edited(tmp_path, "wod_osd_2015_cut.nc", edit))
    assert 18954244 not in casts and len(casts) == 4
    assert stats["source"] == 5 and stats["bad_coords"] == 1
    assert stats["no_good"] == 2 and stats["no_date"] == 1 and stats["no_depth_levels"] == 0 and stats["no_values"] == 0
    c0, c1, c2, c4 = casts[22386903], casts[17815565], casts[17815566], casts[17813889]
    assert c0.n_good > 0 and (c0.cast_date, c0.cast_time, c0.time_precision, c0.year) == (None, None, None, None)
    assert c1.n_good == 0 and c1.year is None            # no_good only: a cast with neither is not ALSO no_date
    assert c2.n_good == 0 and c2.cast_date == date(2015, 1, 7)
    assert c4.n_good > 0 and c4.cast_date == date(2015, 7, 1) and c4.time_precision == "day" and c4.cast_time is None
    drawn = sum(1 for c in casts.values() if c.n_good > 0 and c.year is not None)
    assert drawn == len(casts) - stats["no_good"] - stats["no_date"] == 1


def test_xctd_file_reads_and_a_unit_change_stops_the_load(tmp_path):
    casts, _ = _parsed("wod_ctd_2015_cut.nc")
    assert any(c.dataset == "XCTD" for c in casts.values())

    def edit(ds):                                          # a units change must stop the load, never be converted
        ds["Temperature"].units = "degree_F"

    bad = _edited(tmp_path, "wod_ctd_2015_cut.nc", edit)
    with pytest.raises(SchemaError):
        list(iter_casts(bad, "ctd", collections.Counter()))
    with pytest.raises(SchemaError):
        read_file_info(bad)



def test_nstar_uses_one_level_where_both_nitrate_and_phosphate_are_good(tmp_path):
    """R8. Cast 22386903 (first cast of the 2015 OSD cut; Phosphate and Nitrate offsets are 0) has both nutrients at
    j = 0, 2, 3, 6, 11, 18 (z 5.4, 15.4, 50.19, 174, 471, 905 m). Only j = 3 lies in the 50 m window (40-60 m), so
    on the real data all three picks sit at j = 3. Edit: z[2] -> 55.0 m (a second level in the window, nitrate and
    phosphate good there: NO3 30.82, PO4 2.13) and Phosphate_WODflag[3] -> 1. Then the nitrate pick stays at j = 3
    (30.87, 0.19 m from 50), the phosphate pick moves to j = 2, and N* must come from j = 2:
    30.82 - 16 * 2.13 = -3.26 -> -33, NOT the independent combination n[3] - 16 * p[2] = -3.21 -> -32."""
    def edit(ds):
        ds["z"][2] = 55.0
        ds["Phosphate_WODflag"][3] = 1

    casts, _ = _parse_path(_edited(tmp_path, "wod_osd_2015_cut.nc", edit))
    c = casts[22386903]
    levels = EXP["files"]["wod_osd_2015_cut.nc"]["casts"]["22386903"]["vars"]
    n = {l[0]: l[2] for l in levels["Nitrate"]["levels"]}
    p = {l[0]: l[2] for l in levels["Phosphate"]["levels"]}
    assert [l[0] for l in levels["Phosphate"]["levels"]] == [0, 2, 3, 6, 11, 18]      # offsets as read from the file
    d = R.DEPTHS.index(50)
    assert c.picks[R.slot("nitrate", d)] == R.scaled(n[3], "nitrate")
    assert c.picks[R.slot("phosphate", d)] == R.scaled(p[2], "phosphate")
    both = n[2] - R.NSTAR_K * p[2]
    wrong = n[3] - R.NSTAR_K * p[2]
    assert R.scaled(both, "nstar") != R.scaled(wrong, "nstar")                         # the test can tell them apart
    assert c.picks[R.slot("nstar", d)] == R.scaled(both, "nstar") == -33
