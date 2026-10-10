# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""The reader against the REAL fixture (backend/tests/fixtures/argo_doxy, see SOURCE.txt)."""
import collections
import pathlib

import netCDF4
import pytest

from ingestion import argo_doxy_rules as r
from ingestion.argo_doxy_sprof import SprofSchemaError, open_sprof, read_sprof

FIX = pathlib.Path(__file__).parent / "fixtures" / "argo_doxy"


def _index():
    rows = {}
    for ln in (FIX / "argo_synthetic-profile_index.excerpt.txt").read_text().splitlines():
        if ln.startswith("#") or ln.startswith("file,"):
            continue
        row = r.parse_index_line(ln)
        rows[row.key] = row
    return rows


def _profile(key):
    dac, wmo, rest = key.split("_", 2)
    upd, raws = read_sprof(FIX / f"{dac}_{wmo}_Sprof.nc")
    cyc, desc = int(rest.rstrip("D")), rest.endswith("D")
    raw = next(x for x in raws if x["cycle"] == cyc and x["descending"] == desc)
    return raw, r.build_profile(raw, _index()[key], upd)


def test_fixture_index_lists_the_fourteen_profiles():
    assert len(_index()) == 14


def test_d_mode_profile_reads_raw_qc3_and_adjusted_qc1():
    raw, p = _profile("aoml_1900722_001")
    assert raw["doxy_mode"] == "D"
    assert collections.Counter(c for c, v in zip(raw["doxy_qc"], raw["doxy"]) if v < 9e4) == {"3": 70, "4": 1}
    # the QC-4 level carries a raw value but no adjusted one (adjusted fill with flag 4)
    assert collections.Counter(c for c, v in zip(raw["doxy_adj_qc"], raw["doxy_adj"]) if v < 9e4) == {"1": 70}
    assert p["n_good"] == 70 and p["drawable"] is True


def test_realtime_profile_with_raw_flag_1_or_2_is_not_drawn():
    raw, p = _profile("kiost_2900791_053")
    assert raw["doxy_mode"] == "R"
    assert collections.Counter(c for c, v in zip(raw["doxy_qc"], raw["doxy"]) if v < 9e4) == {"3": 20, "4": 3, "2": 1}
    assert p["drawable"] is False and p["n_good"] == 0 and all(v is None for v in p["at_depth"])
    assert all(v is None for v in p["doxy_adj"])                      # fill stays None, never 99999 or 0


def test_a_mode_adjusted_qc3_levels_are_stored_not_good():
    raw, p = _profile("coriolis_7902223_027")
    assert raw["doxy_mode"] == "A"
    assert collections.Counter(c for c, v in zip(raw["doxy_adj_qc"], raw["doxy_adj"]) if v < 9e4) == {"1": 217, "3": 9}
    assert p["n_good"] == 217                      # thinning may drop the QC-3 levels; n_good is counted before it


@pytest.mark.parametrize("key", ["bodc_3901580_002D", "coriolis_7902223_027"])
def test_negative_surface_pressure_becomes_depth_zero(key):
    raw, p = _profile(key)
    doxy_levels = [pa if pa < 9e4 else pr for pr, pa, d, a in
                   zip(raw["pres"], raw["pres_adj"], raw["doxy"], raw["doxy_adj"]) if d < 9e4 or a < 9e4]
    assert min(doxy_levels) < 0
    assert p["depth_m"][0] == 0.0 and all(d >= 0.0 for d in p["depth_m"])
    assert p["at_depth"][0] is not None             # the surface window (0-10 m) uses the level, it is not lost


@pytest.mark.parametrize("key", ["aoml_5906436_112", "coriolis_6901510_006"])
def test_bad_or_missing_position_is_stored_but_not_drawable(key):
    _, p = _profile(key)
    assert p is not None and p["drawable"] is False and p["position_qc"] in (4, 9)


def test_the_2000_m_pick_is_a_depth_below_its_pressure():
    _, p = _profile("aoml_5900421_005")
    i = r.DISPLAY_DEPTHS.index(2000)
    assert p["at_depth"][i] is not None
    j = p["depth_m"].index(p["at_depth_m"][i])
    assert p["at_depth_m"][i] < p["pres_dbar"][j]                      # converted, not pressure taken as depth


def test_profile_without_any_doxy_value_is_rejected():
    _, p = _profile("aoml_5904670_038")
    assert p is None


def test_thinning_on_the_2211_level_descending_profile():
    raw, p = _profile("coriolis_3902120_002D")
    assert sum(1 for v in raw["doxy_adj"] if v < 9e4) == 2211
    assert p["n_levels_source"] >= 2211 and p["n_levels"] <= r.MAX_STORED_LEVELS
    for i, v in enumerate(p["at_depth"]):
        if v is not None:
            assert p["at_depth_m"][i] in p["depth_m"]                  # every pick survives thinning
    assert "8" in raw["doxy_adj_qc"] and p["n_good"] == 2086           # QC 8 (estimated) is stored, never good


def test_descending_profile_without_adjusted_values_is_stored_not_drawable():
    _, p = _profile("coriolis_3902120_001D")
    assert p is not None and p["n_good"] == 0 and p["drawable"] is False and p["direction"] == "D"


def test_two_dacs_same_wmo_read_as_two_profiles():
    _, a = _profile("aoml_1902751_001")
    _, b = _profile("coriolis_1902751_001")
    assert a["profile_key"] != b["profile_key"] and a["argo_profile_id"] == b["argo_profile_id"] == "1902751_001"
    assert (a["lat"], a["lon"]) != (b["lat"], b["lon"])


def test_cycle_zero_key():
    _, p = _profile("aoml_1901466_000")
    assert p["profile_key"] == "aoml_1901466_000"


def test_a_file_without_doxy_variables_is_a_schema_error(tmp_path):
    src = FIX / "aoml_1900722_Sprof.nc"
    dst = tmp_path / "broken.nc"
    with netCDF4.Dataset(src) as s, netCDF4.Dataset(dst, "w", format=s.data_model) as d:
        s.set_auto_mask(False)
        for n, dim in s.dimensions.items():
            d.createDimension(n, len(dim))
        for n, v in s.variables.items():
            if n.startswith("DOXY"):
                continue
            o = d.createVariable(n, v.dtype, v.dimensions)
            o[:] = v[:]
    with pytest.raises(SprofSchemaError):
        read_sprof(dst)


def test_a_truncated_file_raises(tmp_path):
    dst = tmp_path / "cut.nc"
    data = (FIX / "aoml_1900722_Sprof.nc").read_bytes()
    dst.write_bytes(data[: len(data) // 2])
    with pytest.raises(OSError):
        read_sprof(dst)


def test_reader_hands_over_both_pressure_flag_strings_aligned_with_the_levels():
    raw, _ = _profile("aoml_1900722_001")
    assert len(raw["pres_qc"]) == len(raw["pres_adj_qc"]) == len(raw["pres"])
    assert set(raw["pres_qc"]) <= set("0123456789 \x00") and set(raw["pres_adj_qc"]) <= set("0123456789 \x00")


def test_open_sprof_is_lazy_and_reads_only_the_wanted_profiles():
    """Memory bound: a float's profiles are produced one at a time, and unwanted ones are never read."""
    import inspect
    path = FIX / "coriolis_3902120_Sprof.nc"
    with open_sprof(path) as (upd, it):
        assert upd is not None and inspect.isgenerator(it)
        first = next(it)
        assert inspect.getgeneratorstate(it) == inspect.GEN_SUSPENDED          # the second profile is not read yet
        assert first["cycle"] == 1 and first["descending"]
    with open_sprof(path, want={(2, True)}) as (_, it):
        got = list(it)
    assert [(g["cycle"], g["descending"]) for g in got] == [(2, True)]
    with open_sprof(path, want={(99, False)}) as (_, it):
        assert list(it) == []
    assert [x["cycle"] for x in read_sprof(path)[1]] == [1, 2]                  # the list wrapper still agrees
