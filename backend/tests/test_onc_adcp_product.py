# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""RADCPTS parsing. Values below are verbatim from the real ONC product —
see backend/tests/fixtures/onc_adcp/SCHEMA_NOTES.md for provenance.
"""
import os

import pytest

from backend.ingestion.onc_adcp_product import (
    BACKSCATTER_UNITS,
    ENSEMBLE_PERIOD_S,
    build_backscatter_strip,
)

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "onc_adcp", "radcpts_rcne5_real.nc")

# Real RCNE5 values. `depth` is DESCENDING in the product, exactly as shipped.
DEPTHS_DESC = [1885.5605, 1877.5608, 1869.5610, 1861.5613, 1853.5616]
TIMES = ["2026-07-08T00:07:30", "2026-07-08T00:22:30", "2026-07-08T00:37:30"]
# values[depthIdx][timeIdx]
VALUES = [
    [86.458, 86.581, 86.366],   # deepest bin
    [84.100, 84.200, 84.300],
    [82.719, float("nan"), 79.875],
    [80.000, 80.100, 80.200],
    [78.500, 78.600, 78.700],   # shallowest bin
]


def test_ensemble_period_yields_96_buckets_per_day():
    assert 86400 // ENSEMBLE_PERIOD_S == 96


def test_strip_is_transposed_to_time_major():
    out = build_backscatter_strip(VALUES, DEPTHS_DESC, TIMES)
    assert len(out["strip"]) == len(TIMES)          # rows = time
    assert len(out["strip"][0]) == len(DEPTHS_DESC)  # cols = depth bins


def test_bins_are_sorted_shallow_to_deep():
    """AdcpHeatmap paints binIdx 0 at the top under a 'surface' label, but ONC
    ships depth descending. Unsorted, the heatmap renders upside down."""
    out = build_backscatter_strip(VALUES, DEPTHS_DESC, TIMES)
    assert out["depths"] == sorted(out["depths"])
    assert out["depths"][0] == pytest.approx(1853.5616)   # shallowest first
    assert out["depths"][-1] == pytest.approx(1885.5605)  # deepest last


def test_values_follow_the_depth_sort_not_the_source_order():
    """The whole point: cell [t][0] must be the SHALLOWEST bin's value."""
    out = build_backscatter_strip(VALUES, DEPTHS_DESC, TIMES)
    assert out["strip"][0][0] == pytest.approx(78.5)    # shallowest, t=0
    assert out["strip"][0][-1] == pytest.approx(86.458)  # deepest, t=0


def test_nan_becomes_none_at_its_reordered_position():
    out = build_backscatter_strip(VALUES, DEPTHS_DESC, TIMES)
    # NaN was source [2][1]; depth idx 2 sorts to position 2 from the deep end,
    # i.e. column 2 of 5 after the ascending sort.
    assert out["strip"][1][2] is None
    assert out["strip"][0][2] == pytest.approx(82.719)


def test_zero_db_is_kept_as_a_real_value():
    out = build_backscatter_strip([[0.0]], [100.0], TIMES[:1])
    assert out["strip"][0][0] == 0.0  # not None — 0 dB is a measurement


def test_empty_inputs_yield_empty_strip():
    assert build_backscatter_strip([], [], []) == {"depths": [], "times": [], "strip": []}
    assert build_backscatter_strip([[]], [1.0], []) == {"depths": [], "times": [], "strip": []}


def test_times_are_second_resolution_iso():
    out = build_backscatter_strip(VALUES, DEPTHS_DESC, TIMES)
    assert out["times"][0] == "2026-07-08T00:07:30"


def test_strip_is_strict_json_serialisable():
    import json
    out = build_backscatter_strip(VALUES, DEPTHS_DESC, TIMES)
    encoded = json.dumps(out["strip"], allow_nan=False)  # must not raise
    assert "NaN" not in encoded


def test_units_are_decibels():
    assert BACKSCATTER_UNITS == "dB"


def test_python_json_round_trip_really_does_admit_nan():
    """Pins the upstream trap this parser defends against: ONC's JSON carries bare
    `NaN` tokens (RFC 8259 has none), Python accepts AND re-emits them, so the bug
    is invisible until Postgres rejects the jsonb."""
    import json
    import math

    parsed = json.loads('{"values": [NaN]}')
    assert math.isnan(parsed["values"][0])
    assert "NaN" in json.dumps(parsed)
    with pytest.raises(ValueError):
        json.dumps(parsed, allow_nan=False)


@pytest.mark.skipif(not os.path.exists(FIXTURE), reason="fixture missing")
def test_load_real_radcpts_netcdf():
    """End-to-end against the real (truncated) ONC product. Skipped where xarray
    is absent — the pure builder above is the always-run guard."""
    pytest.importorskip("xarray")
    pytest.importorskip("netCDF4")
    from backend.ingestion.onc_adcp_product import load_adcp_timeseries

    out = load_adcp_timeseries(FIXTURE)
    assert len(out["depths"]) == 8
    assert len(out["times"]) == 6
    assert len(out["strip"]) == 6 and len(out["strip"][0]) == 8
    assert out["depths"] == sorted(out["depths"])
    assert out["strip"][1][5] is None          # the injected NaN, after reorder
    assert out["strip"][0][7] == pytest.approx(86.458, abs=1e-3)  # deepest bin
