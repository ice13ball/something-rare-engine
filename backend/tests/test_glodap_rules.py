# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import csv, math, pathlib, re
from collections import defaultdict
import pytest
from ingestion import glodap_bottles_rules as R
from services import glodap_carbon

FIXCSV = pathlib.Path(__file__).parent / "fixtures" / "glodap_v3" / "glodapv3_excerpt.csv"

def _casts():
    by = defaultdict(list)
    with FIXCSV.open(newline="") as f:
        for row in csv.DictReader(f):
            by[(row["expocode"], row["station"], row["cast"])].append(row)
    return by

def test_fixture_header_satisfies_the_column_contract():
    with FIXCSV.open(newline="") as f:
        header = next(csv.reader(f))
    assert not set(R.REQUIRED_COLUMNS) - set(header)

def test_fill_and_nan_are_none_never_zero():
    assert R.clean("-9999") is None and R.clean(-9999.0) is None
    assert R.clean("nan") is None and R.clean(float("nan")) is None and R.clean("") is None
    assert R.clean("0") == 0.0 and R.clean("-1.27") == -1.27

def test_cast_key_is_stable_text_and_drops_the_float_suffix():
    assert R.cast_key("49UF20150620", "4511", 1.0) == "49UF20150620_4511_1"
    assert R.cast_key("IcelandSea", "2", "1.0") == "IcelandSea_2_1"

@pytest.mark.parametrize("cast", ["-9999", "-9999.0", "NaN", "nan", "", None, "inf", "junk"])
def test_a_missing_cast_number_is_its_own_stable_key_component(cast):
    key = R.cast_key("77DN20050730", "12", cast)
    assert key == "77DN20050730_12_nc" and R.cast_number(cast) is None
    assert re.fullmatch(r"[A-Za-z0-9._-]+", key)


def test_the_no_cast_key_never_collides_with_a_real_cast_number():
    real = {R.cast_key("X", "5", n) for n in ("0", "1.0", 2, "99", "-1")}
    assert R.cast_key("X", "5", "-9999") not in real
    assert R.cast_key("X", "5", "0") == "X_5_0"          # 0 is a real number, not "missing"


def test_a_cast_without_a_number_builds_with_cast_no_none():
    row = dict(_first_row(), cast="-9999")
    c = R.build_cast([row])
    assert c["cast_key"] == f"{row['expocode']}_{row['station']}_nc" and c["cast_no"] is None


def test_platform_code_only_for_standard_expocodes():
    assert R.platform_code("06AQ19890906") == "06AQ"
    assert R.platform_code("IcelandSea") is None and R.platform_code("OMEX2") is None

def test_depth_windows_cover_exactly_the_fields_display_depths():
    assert sorted(R.DEPTH_WINDOWS) == list(glodap_carbon.DISPLAY_DEPTHS)
    for d, (lo, hi) in R.DEPTH_WINDOWS.items():
        assert lo <= d <= hi

def test_bottle_variables_share_the_fields_units():
    # unit/scale mismatch guard: the colour scale is the field's, so the units must be too
    for field_key, col in R.FIELD_TO_BOTTLE.items():
        if col is None:
            continue
        assert R.BOTTLE_UNITS[col] == glodap_carbon.CARBON_VARS[field_key]["units"]
    assert R.FIELD_TO_BOTTLE["ph"] == "phtsinsitutp"     # in-situ, total scale — never phts25p0
    assert R.FIELD_TO_BOTTLE["cant"] is None

def test_pick_level_nearest_good_bottle_inside_the_window():
    depths  = [5.0, 190.0, 205.0, 260.0]
    values  = [2000.0, 2150.0, 2160.0, 2200.0]
    flags   = [2, 2, 2, 2]
    bottles = [1.0, 2.0, 3.0, 4.0]
    assert R.pick_level(depths, values, flags, bottles, 200) == (2160.0, 205.0)

def test_pick_level_never_reaches_outside_the_window():
    # the only good bottle near 200 m is at 260 m: 35 m beyond the 225 m edge → no value
    assert R.pick_level([5.0, 260.0], [2000.0, 2200.0], [2, 2], [1.0, 2.0], 200) is None

def test_flag_zero_in_window_and_good_outside_window_gives_none():
    # Review Focus 1
    assert R.pick_level([200.0, 300.0], [2150.0, 2200.0], [0, 2], [1.0, 2.0], 200) is None

def test_flag_nine_and_null_values_are_never_picked():
    assert R.pick_level([200.0, 201.0], [None, 2150.0], [9, 9], [1.0, 2.0], 200) is None

def test_tie_breaks_are_deterministic_shallower_then_bottle_then_value():
    # 195 and 205 are equidistant from 200 → shallower (195) wins
    assert R.pick_level([195.0, 205.0], [1.0, 2.0], [2, 2], [9.0, 1.0], 200) == (1.0, 195.0)
    # duplicate (bottle, depth) with different values → lower value wins
    assert R.pick_level([200.0, 200.0], [2.0, 1.0], [2, 2], [5.0, 5.0], 200) == (1.0, 200.0)

def test_every_fixture_cast_builds_with_flags_beside_every_value():
    built = {k: R.build_cast(rows) for k, rows in _casts().items()}
    assert len(built) == 16
    mixed_rows = _casts()[("06AQ19890906", "213", "1.0")]          # 21 real rows, 4 with depth = -9999
    assert built[("06AQ19890906", "213", "1.0")]["n_samples"] == 17
    assert R.build_cast([r for r in mixed_rows if r["depth"] == "-9999"]) is None   # an all-depth-less cast is not stored
    for c in filter(None, built.values()):
        n = len(c["depth_m"])
        assert all(d is not None for d in c["depth_m"])            # depth-less rows dropped
        for v in R.VARIABLES:
            assert len(c[v]) == n and len(c[f"{v}_f"]) == n
            for val, fl in zip(c[v], c[f"{v}_f"]):
                assert (val is None) == (fl == 9)                   # fill ⇔ flag 9, never drawn
                assert val is None or not math.isnan(val)

def test_levels_hold_only_good_values_inside_their_window():
    for rows in _casts().values():
        c = R.build_cast(rows)
        if c is None:
            continue
        for field_key, per_depth in c["levels"].items():
            col = R.FIELD_TO_BOTTLE[field_key]
            for d, (val, sample_depth) in per_depth.items():
                lo, hi = R.DEPTH_WINDOWS[int(d)]
                assert lo <= sample_depth <= hi
                i = next(i for i, (dd, vv, ff) in enumerate(zip(c["depth_m"], c[col], c[f"{col}_f"]))
                         if dd == sample_depth and round(vv, R.LEVEL_DECIMALS[col]) == val and ff == R.GOOD_FLAG)
                assert i >= 0

def test_cant_never_gets_a_level():
    for rows in _casts().values():
        c = R.build_cast(rows)
        assert c is None or "cant" not in c["levels"]

def test_day_precision_and_minute_precision_are_both_kept():
    cs = _casts()
    day = R.build_cast(cs[("74AB19900528", "1", "1.0")])
    assert day["time_precision"] == "day" and day["obs_time"] is None and day["obs_date"].year == 1990
    deep = R.build_cast(cs[("49UF20150620", "4511", "1.0")])
    assert deep["time_precision"] == "minute" and deep["obs_time"].tzinfo is not None

def test_position_is_the_shallowest_bottle_and_spread_is_recorded():
    c = R.build_cast(_casts()[("58P320011031", "18", "1.0")])
    assert c["pos_spread_km"] > 10
    assert -180 <= c["lon"] <= 180 and -90 <= c["lat"] <= 90

def test_qc_is_one_scalar_per_cast_and_pH_has_none():
    c = R.build_cast(_casts()[("06MT20060712", "257", "3.0")])
    assert c["tco2_qc"] == 0
    assert "phtsinsitutp_qc" not in c and "fco2_qc" not in c

def _row(**over):
    base = {k: "-9999" for k in R.REQUIRED_COLUMNS}
    base.update(expocode="06AQ19890906", station="1", cast="1.0", year="1989", month="9", day="6",
                hour="-9999", minute="-9999", latitude="-60.0", longitude="10.0", region="1.0", doi="",
                bottle="1.0", depth="200.0", pressure="202.0")
    base.update(over)
    return base

@pytest.mark.parametrize("good", ["2.0", "2", "2.00"])
def test_float_text_flag_two_counts_as_good(good):
    # the source writes flags as float text ("2.0", "9.0"), never "2": the comparison must be numeric
    c = R.build_cast([_row(tco2="2150.0", tco2f=good)])
    assert c["tco2_f"] == [2]
    assert c["levels"]["dic"]["200"] == [2150.0, 200.0]
    assert c["n_good"] == 1

def test_float_text_flags_zero_and_nine_are_not_good():
    for bad in ["0.0", "9.0", "-9999"]:
        c = R.build_cast([_row(tco2="2150.0", tco2f=bad)])
        assert "dic" not in c["levels"]
    assert R.build_cast([_row(tco2="-9999", tco2f="9.0")])["tco2_f"] == [9]

def test_fixture_flags_are_float_text_and_still_yield_good_levels():
    # real-data guard: the fixture really carries "2.0"-style text, and levels come out of it
    all_rows = [r for rows in _casts().values() for r in rows]
    assert {r["tco2f"] for r in all_rows} == {"2.0", "9.0"}
    built = [c for c in map(R.build_cast, _casts().values()) if c]
    assert any(c["levels"].get("dic") for c in built)
    assert sum(c["n_good"] for c in built) > 0


# --- fill / NaN policy for the loader (decision 2026-10-06) -----------------------------------------

def _first_row(expocode="49UF20150620"):
    return next(r for r in csv.DictReader(FIXCSV.open(newline="")) if r["expocode"] == expocode)


def test_a_real_fixture_row_has_no_problem():
    assert R.row_problem(_first_row()) is None


@pytest.mark.parametrize("field,value,why", [
    ("latitude", "-9999", "position"), ("longitude", "NaN", "position"), ("latitude", "", "position"),
    ("latitude", "91.0", "position"), ("longitude", "-181", "position"), ("latitude", "n/a", "position"),
    ("year", "-9999", "date"), ("month", "nan", "date"), ("day", "", "date"),
    ("month", "13.0", "date"), ("day", "31.0", None),     # 31 is fine in a 31-day month (fixture: October)
    ("station", "", "key"), ("expocode", "", "key"),
    # a missing CAST number is not a reason to drop measured rows (decision 2026-10-06)
    ("cast", "-9999", None), ("cast", "NaN", None), ("cast", "", None),
])
def test_row_problem_names_the_reason_instead_of_raising(field, value, why):
    row = dict(_first_row("316N19831007"), **{field: value})
    row = dict(row, month="10.0", day="7.0") if field not in ("month", "day") else row
    assert R.row_problem(row) == why


def test_february_30_is_a_date_problem_not_a_crash():
    assert R.row_problem(dict(_first_row(), month="2.0", day="30.0")) == "date"


def test_fill_or_nan_qc_is_null_never_minus_9999():
    rows = [dict(r) for r in _casts()[("49UF20150620", "4511", "1.0")]]
    for r in rows:
        r["tco2qc"] = "-9999"
        r["talkqc"] = "NaN"
    c = R.build_cast(rows)
    assert c["tco2_qc"] is None and c["talk_qc"] is None
    assert any(v is not None for v in c["tco2"])          # the values themselves are untouched


def test_a_qc_fill_beside_a_real_qc_does_not_change_the_cast_qc():
    rows = [dict(r) for r in _casts()[("06MT20060712", "257", "3.0")]]
    real = R.build_cast([dict(r) for r in rows])["tco2_qc"]
    rows[0]["tco2qc"] = "-9999"
    assert R.build_cast(rows)["tco2_qc"] == real


@pytest.mark.parametrize("hour,minute", [("-9999", "5.0"), ("NaN", "NaN"), ("25.0", "10.0"), ("12.0", "60.0"), ("", "")])
def test_unusable_clock_means_date_only_precision(hour, minute):
    rows = [dict(r, hour=hour, minute=minute) for r in _casts()[("49UF20150620", "4511", "1.0")]]
    c = R.build_cast(rows)
    assert c["time_precision"] == "day" and c["obs_time"] is None and c["obs_date"].year == 2015


def test_the_real_fixture_has_date_only_casts_and_minute_casts():
    by = {k: R.build_cast([dict(r) for r in v]) for k, v in _casts().items()}
    assert by[("74AB19900528", "1", "1.0")]["time_precision"] == "day"
    assert by[("49UF20150620", "4511", "1.0")]["time_precision"] == "minute"
