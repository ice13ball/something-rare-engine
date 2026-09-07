# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

# backend/tests/test_geotraces_ingest.py
import os
from backend.ingestion import geotraces_ingest as g

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "geotraces", "seawater_real_subset.csv")

def _text():
    with open(FIX, encoding="utf-8") as f:
        return f.read()

def test_normalize_lon_wraps_0_360():
    assert round(g.normalize_lon(349.963989), 6) == round(349.963989 - 360, 6)
    assert g.normalize_lon(10.5) == 10.5
    assert g.normalize_lon(180.0) == 180.0

def test_station_id_stable_and_text_safe():
    a = g.station_id_for("GA02", "(101)")
    b = g.station_id_for("GA02", "(101)")
    c = g.station_id_for("GA02", "001")
    assert a == b and a != c and len(a) == 16

def test_build_samples_units_verbatim():
    samples, units = g.build_samples(_text())
    assert units["co_d"] == "pmol/kg"      # Co differs!
    assert units["fe_d"] == "nmol/kg"
    assert units["mn_d"] == "nmol/kg"
    assert set(units) == {"mn_d","fe_d","co_d","ni_d","cu_d"}

def test_build_samples_values_and_flags():
    samples, _ = g.build_samples(_text())
    # at least one Fe value with flag retained; flag 4/9 excluded; lon normalized negative
    fe = [s for s in samples if s["fe_d"] is not None]
    assert fe, "expected Fe samples"
    s0 = fe[0]
    assert s0["fe_d"] > 0 and isinstance(s0["fe_d_qc"], int)
    assert s0["lon"] < 0  # GA01 stations are ~-10 (normalized from 349.x)
    assert all(s["fe_d_qc"] not in (4, 9) for s in fe)
    # metals coverage present in fixture
    assert any(s["mn_d"] is not None for s in samples)
    assert any(s["co_d"] is not None for s in samples)
    assert any(s["cu_d"] is not None for s in samples)
    assert any(s["ni_d"] is not None for s in samples)

def test_derive_stations_rollup():
    samples, _ = g.build_samples(_text())
    stations = g.derive_stations(samples)
    by = {s["station_id"]: s for s in stations}
    assert len(stations) == len({s["station_id"] for s in samples})
    for st in stations:
        assert st["n_samples"] >= 1
        assert st["min_depth_m"] <= st["max_depth_m"]
        if st["has_fe"]:
            assert st["fe_max"] is not None
        assert isinstance(st["decade"], int) or st["decade"] is None

def test_sample_time_and_decade_populated():
    """Regression: parse_header must match the 'time' column (yyyy-mm-ddThh:mm:ss.sss).
    Before the fix, _base_name() truncated that header at the first ':', yielding
    'yyyy-mm-ddThh' which never matched, so sample_time and decade were always None."""
    import csv as _csv, io as _io

    # 1. parse_header must include the "time" key
    with open(FIX, encoding="utf-8") as f:
        header = next(_csv.reader(f))
    h = g.parse_header(header)
    assert "time" in h["meta"], (
        f"parse_header did not match the 'time' column; meta keys = {list(h['meta'].keys())}"
    )

    # 2. At least one sample must have a non-None sample_time
    samples, _ = g.build_samples(_text())
    assert any(s["sample_time"] is not None for s in samples), (
        "All sample_time values are None — time column not matched"
    )

    # 3. derive_stations must produce at least one station with an integer decade
    stations = g.derive_stations(samples)
    assert any(isinstance(st["decade"], int) for st in stations), (
        "All station decades are None — sample_time never populated"
    )
