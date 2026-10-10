# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""Pure rules for the BGC-Argo DOXY points. Numbers measured on the real GDAC files (plan Phase 0)."""
from datetime import datetime, timezone

import pytest

from ingestion import argo_doxy_rules as r

UTC = timezone.utc
HDR = "file,date,latitude,longitude,ocean,profiler_type,institution,parameters,parameter_data_mode,date_update"


def _row(key="aoml_1900722_001", dac="aoml", wmo="1900722", cycle=1, desc=False,
         upd=datetime(2022, 6, 28, 8, 8, 1, tzinfo=UTC), mode="D"):
    return r.IndexRow(key, dac, wmo, cycle, desc, f"{dac}/{wmo}/profiles/SD{wmo}_{cycle:03d}{'D' if desc else ''}.nc",
                      upd, mode)


def _raw(**kw):
    base = dict(cycle=1, descending=False, juld=20748.09472, juld_qc="1", lat=-40.316, lon=73.389, position_qc="1",
                doxy_mode="D", pres=[6.0, 60.0, 500.0], pres_adj=[6.0, 60.0, 500.0],   # three different depth bins
                doxy=[230.9, 230.0, 180.0], doxy_qc="333", doxy_adj=[259.6, 259.0, 200.0], doxy_adj_qc="111")
    base.update(kw)
    return base


# ── keys ────────────────────────────────────────────────────────────────────────────────────────────
def test_profile_key_pads_to_three_and_keeps_four_digit_cycles():
    assert r.profile_key("aoml", "1901466", 0, False) == "aoml_1901466_000"
    assert r.profile_key("coriolis", "3902120", 2, True) == "coriolis_3902120_002D"
    assert r.profile_key("aoml", "5904479", 1000, False) == "aoml_5904479_1000"
    assert all(r.KEY_RE.match(k) for k in ("aoml_1901466_000", "coriolis_3902120_002D", "aoml_5904479_1000"))
    assert r.argo_profile_id("3902120", 2, True) == "3902120_002D"


def test_same_wmo_in_two_dacs_gives_two_keys():
    a = r.parse_index_line("aoml/1902751/profiles/SR1902751_001.nc,20260831024125,-21.489,-140.850,P,846,AO,"
                           "PRES TEMP PSAL DOXY CHLA,AAARA,20260914200204")
    b = r.parse_index_line("coriolis/1902751/profiles/SD1902751_001.nc,20250421174358,19.815,60.192,I,834,IF,"
                           "PRES TEMP PSAL DOXY CHLA,RRRDR,20260903111139")
    assert [a.key, b.key] == ["aoml_1902751_001", "coriolis_1902751_001"]
    assert a.doxy_mode == "R" and b.doxy_mode == "D"


def test_ascending_and_descending_cycles_have_distinct_keys():
    up = r.parse_index_line("coriolis/3902120/profiles/SD3902120_002.nc,20180315153800,1,1,A,1,IF,PRES DOXY,DD,20260624141732")
    down = r.parse_index_line("coriolis/3902120/profiles/SD3902120_002D.nc,20180315153800,1,1,A,1,IF,PRES DOXY,DD,20260624141732")
    assert up.key != down.key and down.descending and not up.descending


def test_sr_and_sd_files_of_one_profile_share_the_key():
    rt = r.parse_index_line("aoml/1900722/profiles/SR1900722_001.nc,20061022021624,-40.3,73.4,I,846,AO,PRES DOXY,RR,20061023000000")
    dm = r.parse_index_line("aoml/1900722/profiles/SD1900722_001.nc,20061022021624,-40.3,73.4,I,846,AO,PRES DOXY,DD,20220628080801")
    assert rt.key == dm.key == "aoml_1900722_001"


# ── index lines ─────────────────────────────────────────────────────────────────────────────────────
def test_index_header_must_match_exactly():
    r.check_index_header(HDR)
    with pytest.raises(ValueError):
        r.check_index_header(HDR.replace("date_update", "date_updated"))


def test_a_profile_without_doxy_is_out_of_scope_not_a_reject():
    assert r.parse_index_line("aoml/1/profiles/SD1234567_001.nc,2006,1,1,I,846,AO,PRES TEMP PSAL,DDD,20220628080801") is None


@pytest.mark.parametrize("line", [
    "aoml/1900722/profiles/SD1900722_001.nc,20061022021624,-40.3,73.4,I,846,AO,PRES DOXY,DD",          # 9 fields
    "aoml/1900722/profiles/SD1900723_001.nc,20061022021624,-40.3,73.4,I,846,AO,PRES DOXY,DD,20220628080801",  # dir != file wmo
    "aoml/1900722/profiles/SD1900722_001.nc,20061022021624,-40.3,73.4,I,846,AO,PRES DOXY,D,20220628080801",   # mode too short
    "aoml/1900722/profiles/SD1900722_001.nc,20061022021624,-40.3,73.4,I,846,AO,PRES DOXY,DD,",                 # no date_update
])
def test_malformed_index_lines_are_rejected_by_name(line):
    assert r.parse_index_line(line) == "index_malformed"


# ── cleaning ────────────────────────────────────────────────────────────────────────────────────────
def test_fill_99999_and_blank_qc_become_none_never_values():
    assert r.clean(99999.0) is None and r.clean(float("nan")) is None and r.clean(float("inf")) is None
    assert r.clean(0.0) == 0.0
    assert r.qc_int(" ") is None and r.qc_int("3") == 3 and r.qc_int(b"1") == 1


def test_qc_flags_are_compared_numerically_whatever_their_spelling():
    assert r.qc_int("2.0") == 2 and r.qc_int(b"1.0") == 1 and r.qc_int(0) == 0 and r.qc_int(2.0) == 2
    assert r.qc_int("\x00") is None and r.qc_int(b"") is None and r.qc_int(None) is None
    assert r.qc_int("x") is None and r.qc_int("12") is None and r.qc_int(float("nan")) is None


def test_longitude_above_180_is_wrapped_into_minus_180_180():
    assert r.lon180(190.0) == pytest.approx(-170.0)
    assert r.lon180(180.0) == 180.0 and r.lon180(-180.0) == -180.0
    assert r.lon180(99999.0) is None and r.lon180(400.0) is None


def test_juld_fill_is_no_time():
    assert r.juld_to_time(999999.0) is None
    assert r.juld_to_time(0.0) == datetime(1950, 1, 1, tzinfo=UTC)


# ── pressure -> depth ───────────────────────────────────────────────────────────────────────────────
def test_depth_comes_from_pressure_by_unesco_1983():
    assert r.depth_from_pressure(10000.0, 30.0) == pytest.approx(9712.653, abs=1e-3)   # Fofonoff & Millard check value
    assert r.depth_from_pressure(2000.0, 45.0) == pytest.approx(1974.326, abs=1e-3)
    assert r.depth_from_pressure(-0.1, 45.0) == 0.0


def test_window_bounds_are_depth_not_pressure():
    # 2105 dbar at 45 deg is 2077.5 m: inside the 2000 m window (1900-2100) although the PRESSURE is outside it
    raw = _raw(lat=45.0, pres=[2105.0], pres_adj=[2105.0], doxy=[170.0], doxy_qc="3", doxy_adj=[180.0], doxy_adj_qc="1")
    p = r.build_profile(raw, _row(), None)
    i = r.DISPLAY_DEPTHS.index(2000)
    assert p["at_depth"][i] == pytest.approx(180.0) and p["at_depth_m"][i] == pytest.approx(2077.467, abs=1e-2)
    # 1910 dbar at 10 deg is 1890.6 m: OUTSIDE the window although the pressure is inside it
    raw = _raw(lat=10.0, pres=[1910.0], pres_adj=[1910.0], doxy=[170.0], doxy_qc="3", doxy_adj=[180.0], doxy_adj_qc="1")
    assert r.build_profile(raw, _row(), None)["at_depth"][i] is None


def test_adjusted_pressure_is_used_where_present():
    raw = _raw(lat=0.0, pres=[495.0], pres_adj=[505.0], doxy=[1.0], doxy_qc="3", doxy_adj=[150.0], doxy_adj_qc="1")
    p = r.build_profile(raw, _row(), None)
    assert p["pres_dbar"] == [pytest.approx(505.0)] and p["pres_source"] == "adjusted"
    raw = _raw(lat=0.0, pres=[495.0], pres_adj=[99999.0], doxy=[1.0], doxy_qc="3", doxy_adj=[150.0], doxy_adj_qc="1")
    assert r.build_profile(raw, _row(), None)["pres_source"] == "raw"


def test_pressure_below_minus_5_dbar_is_dropped():
    raw = _raw(pres=[-6.0, 10.0], pres_adj=[-6.0, 10.0], doxy=[200.0, 201.0], doxy_qc="33",
               doxy_adj=[210.0, 211.0], doxy_adj_qc="11")
    assert r.build_profile(raw, _row(), None)["n_levels_source"] == 1


# ── QC ──────────────────────────────────────────────────────────────────────────────────────────────
def test_raw_realtime_doxy_is_never_good_even_when_flagged_1_or_2():
    raw = _raw(doxy_mode="R", doxy_qc="12" + "1", doxy_adj=[99999.0] * 3, doxy_adj_qc="   ")
    p = r.build_profile(raw, _row(mode="R"), None)
    assert p["n_good"] == 0 and p["drawable"] is False and all(v is None for v in p["at_depth"])
    assert p["doxy_raw_qc"] == [1, 2, 1] and all(v is None for v in p["doxy_adj"])


def test_adjusted_qc3_in_A_mode_is_not_good():
    raw = _raw(doxy_mode="A", doxy_adj_qc="133")
    p = r.build_profile(raw, _row(mode="A"), None)
    assert p["n_good"] == 1 and p["doxy_adj_qc"] == [1, 3, 3]


@pytest.mark.parametrize("q", ["3", "4", "5", "8"])
def test_only_adjusted_qc_1_and_2_are_good(q):
    raw = _raw(doxy_adj_qc=q * 3)
    assert r.build_profile(raw, _row(), None)["n_good"] == 0


# ── windows, picks, thinning ────────────────────────────────────────────────────────────────────────
def test_depth_windows_match_the_field_display_depths():
    from services.woa_climatology import DISPLAY_DEPTHS as FIELD_DEPTHS
    assert list(r.DISPLAY_DEPTHS) == list(FIELD_DEPTHS) == list(r.DEPTH_WINDOWS)
    assert all(lo <= d <= hi for d, (lo, hi) in r.DEPTH_WINDOWS.items())


def test_pick_is_nearest_good_inside_the_window_shallower_on_ties():
    depths = [480.0, 495.0, 505.0, 560.0]
    vals = [1.0, 2.0, 3.0, 4.0]
    good = [True, True, True, True]
    assert r.pick_index(depths, vals, good, 500) == 1          # 495 and 505 tie -> shallower
    assert r.pick_index(depths, vals, [True, False, False, True], 500) == 0
    assert r.pick_index([560.0], [4.0], [True], 500) is None    # outside the window: no value, never interpolated


def test_thinning_keeps_one_level_per_bin_and_every_pick():
    depths = [float(d) for d in range(0, 2000, 1)]               # 2,000 one-metre levels
    adj = [200.0] * len(depths)
    good = [True] * len(depths)
    keep = [1003]
    idx = r.thin_levels(depths, adj, good, [None] * len(depths), keep)
    assert 1003 in idx and len(idx) <= r.MAX_STORED_LEVELS
    assert idx == sorted(idx, key=lambda i: depths[i])
    assert len({int(depths[i] // 5) for i in idx if depths[i] < 100}) == 20


def test_thinning_prefers_a_good_adjusted_level_in_its_bin():
    depths = [10.0, 11.0, 12.0]
    idx = r.thin_levels(depths, [None, 200.0, 201.0], [False, False, True], [190.0, 191.0, 192.0], [])
    assert idx == [2]


# ── whole profile ───────────────────────────────────────────────────────────────────────────────────
def test_a_profile_with_no_doxy_value_is_none():
    raw = _raw(doxy=[99999.0] * 3, doxy_adj=[99999.0] * 3, doxy_qc="   ", doxy_adj_qc="   ")
    assert r.build_profile(raw, _row(), None) is None


@pytest.mark.parametrize("change,drawable", [
    ({}, True),
    ({"position_qc": "4"}, False), ({"position_qc": "9", "lat": 99999.0}, False), ({"position_qc": "8"}, True),
    ({"juld": 999999.0}, False), ({"juld_qc": "4"}, False), ({"doxy_mode": "R"}, False),
])
def test_drawable_needs_adjusted_good_values_position_and_time(change, drawable):
    p = r.build_profile(_raw(**change), _row(), None)
    assert p["drawable"] is drawable


def test_stamp_waits_for_a_sprof_that_lags_its_index():
    row = _row(upd=datetime(2026, 10, 1, 6, 2, 1, tzinfo=UTC))
    later = datetime(2026, 10, 1, 6, 2, 11, tzinfo=UTC)
    earlier = datetime(2026, 9, 1, tzinfo=UTC)
    assert r.build_profile(_raw(), row, later)["gdac_date_update"] == row.date_update
    assert r.build_profile(_raw(), row, earlier)["gdac_date_update"] == earlier


def test_build_profile_returns_every_column_and_aligned_arrays():
    p = r.build_profile(_raw(), _row(), None)
    assert tuple(p) == r.PROFILE_COLUMNS
    n = p["n_levels"]
    assert all(len(p[c]) == n for c in ("pres_dbar", "depth_m", "doxy_adj", "doxy_adj_qc", "doxy_raw", "doxy_raw_qc"))
    assert len(p["at_depth"]) == len(p["at_depth_m"]) == len(r.DISPLAY_DEPTHS)
    assert p["year"] == 2006 and p["profile_key"] == "aoml_1900722_001" and p["argo_profile_id"] == "1900722_001"


def test_a_flag_string_shorter_than_the_levels_is_no_flag_not_a_crash():
    p = r.build_profile(_raw(doxy_adj_qc="1"), _row(), None)
    assert p["n_good"] == 1 and p["doxy_adj_qc"][1:] == [None, None]


# ── size cap and pressure QC ────────────────────────────────────────────────────────────────────────
def _profile_on(pres, lat=0.0, **kw):
    n = len(pres)
    return _raw(lat=lat, pres=list(pres), pres_adj=[99999.0] * n, doxy=[200.0] * n, doxy_qc="3" * n,
                doxy_adj=[210.0] * n, doxy_adj_qc="1" * n, **kw)


def _picks_survive(p):
    got = [d for d in p["at_depth_m"] if d is not None]
    assert len(got) == len(r.DISPLAY_DEPTHS)                       # a one-dbar profile has a good level in every window
    assert all(d in p["depth_m"] for d in got)                      # every window pick survives thinning


def test_a_real_shaped_6000_dbar_profile_stays_within_the_cap_with_every_pick():
    p = r.build_profile(_profile_on([float(x) for x in range(0, 6001)]), _row(), None)
    assert p["n_levels_source"] == 6001 and p["n_levels"] <= r.MAX_STORED_LEVELS
    assert max(p["pres_dbar"]) > 5900                               # the deepest bins are kept when they fit
    _picks_survive(p)


def test_a_12000_dbar_pressure_spike_does_not_raise_and_is_dropped():
    pres = [float(x) for x in range(0, 6001)] + [float(x) for x in range(7100, 12001, 100)] + [12000.0, 15000.0]
    p = r.build_profile(_profile_on(pres), _row(), None)
    assert p["n_levels_source"] == 6001                             # everything past 7000 dbar is out of range
    assert p["n_levels"] <= r.MAX_STORED_LEVELS and max(p["pres_dbar"]) <= 6000.0
    _picks_survive(p)


def test_the_cap_drops_the_deepest_bins_first_and_never_a_pick():
    depths = [float(d) for d in range(0, 11000)]                    # 1 m levels to 11000 m: 181 bins + picks
    adj = [200.0] * len(depths)
    keep = [0, 50, 100, 200, 500, 1000, 1500, 1950]
    idx = r.thin_levels(depths, adj, [True] * len(depths), [None] * len(depths), keep)
    assert len(idx) == r.MAX_STORED_LEVELS and set(keep) <= set(idx)
    assert idx == sorted(idx, key=lambda i: depths[i])
    assert max(depths[i] for i in idx) < 8000                       # the 11000 m end went first


def test_levels_with_bad_pressure_qc_are_excluded():
    raw = _profile_on([10.0, 20.0, 30.0, 40.0], pres_qc="1341", pres_adj_qc="    ")
    p = r.build_profile(raw, _row(), None)
    assert p["pres_dbar"] == [10.0, 40.0] and p["n_levels_source"] == 2     # QC 3 and 4 gone, 1 kept


def test_adjusted_pressure_is_judged_by_its_own_flag_not_the_raw_one():
    raw = _raw(lat=0.0, pres=[10.0, 20.0], pres_adj=[11.0, 21.0], doxy=[1.0, 1.0], doxy_qc="33",
               doxy_adj=[200.0, 201.0], doxy_adj_qc="11", pres_qc="44", pres_adj_qc="14")
    p = r.build_profile(raw, _row(), None)
    assert p["pres_dbar"] == [11.0] and p["pres_source"] == "adjusted"      # raw flag 4 is irrelevant here


def test_missing_pressure_flags_keep_the_level():
    p = r.build_profile(_raw(), _row(), None)                                # _raw() carries no pressure flags at all
    assert p["n_levels_source"] == 3
