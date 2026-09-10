# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Real-data regressions for MEMENTO air/water disambiguation.

Every constant below is taken verbatim from the live database:
  EGAMES_Air        depth 6 m,  ch4 1972.3, n2o 310.1  (poisons ch4_surf today)
  ACSOE (DI234)     depth 1.8/9/29.7 m, ch4 2.05/2.35/2.17  (real seawater)
  ARABESQUE         cruise median 1658.0, value 1678.0      (atmospheric)
  P348              cruise median 1664.0, value    6.2      (real seawater, mixed cruise)
  PV58              cruise median  < 100, value 15602.5     (real seep)
  BLAST II          cruise median  311.8, value  310.0      (atmospheric N2O)
  Goa transect      cruise median  108.5, value  397.7      (real OMZ N2O)

MEMENTO publishes Methane_Ocean [nmol/l] and Methane_Atmosphere [ppb] under the
same column name; the CSV export omits the parameterType discriminator.
"""
import pytest

from backend.ingestion.memento_ingest import (
    GAS_THRESHOLD,
    derive_casts,
    is_atmospheric,
)


def test_thresholds_are_the_specified_values():
    assert GAS_THRESHOLD == {"ch4": 500.0, "n2o": 200.0}


def test_air_label_flags_both_gases_regardless_of_value():
    assert is_atmospheric("ch4", "EGAMES_Air", None, 1972.3) is True
    assert is_atmospheric("n2o", "EGAMES_Air", None, 310.1) is True
    # even an implausibly low value on an air row is still an air row
    assert is_atmospheric("ch4", "FPN-92_Air", 2.0, 1.0) is True


def test_arabesque_atmospheric_ch4_is_flagged():
    assert is_atmospheric("ch4", "DISC 210_103", 1658.0, 1678.0) is True


def test_p348_real_seawater_in_a_mixed_cruise_is_kept():
    # cruise median is atmospheric, but this value is seawater-range
    assert is_atmospheric("ch4", "P348_12", 1664.0, 6.2) is False


def test_pv58_real_seep_is_kept():
    # huge value, but the cruise median is low -> genuine seep, not air
    assert is_atmospheric("ch4", "PV58_7", 42.0, 15602.5) is False


def test_blast_ii_atmospheric_n2o_is_flagged():
    assert is_atmospheric("n2o", "BLAST II  1", 311.8, 310.0) is True


def test_goa_real_omz_n2o_is_kept():
    # 397.7 nM is real Arabian Sea OMZ N2O; a flat 250 threshold would delete it
    assert is_atmospheric("n2o", "Shallow Transect off Goa_15", 108.5, 397.7) is False


def test_per_gas_independence():
    """A row flagged atmospheric for CH4 keeps its ocean-plausible N2O."""
    assert is_atmospheric("ch4", "P348_1", 1664.0, 1673.0) is True
    assert is_atmospheric("n2o", "P348_1", 12.0, 12.4) is False


def test_null_value_or_median_is_never_flagged():
    assert is_atmospheric("ch4", "x", 1658.0, None) is False
    assert is_atmospheric("ch4", "x", None, 1678.0) is False


@pytest.mark.parametrize("gas,median,value", [("ch4", 1658.0, 499.9), ("n2o", 311.8, 99.9)])
def test_values_below_threshold_are_never_flagged(gas, median, value):
    assert is_atmospheric(gas, "no-air-suffix", median, value) is False


# ── derive_casts ────────────────────────────────────────────────────────────

def _sample(depth, ch4=None, n2o=None, label=None, ch4_flag=None):
    return {
        "cast_id": "c1", "set_name": "EGAMES", "station": None,
        "sample_time": None, "time_precision": None, "lat": 54.0, "lon": 10.0, "decade": 2000,
        "depth_m": depth, "label": label, "ch4": ch4, "n2o": n2o,
        "params": {} if ch4_flag is None else {"ch4_flag": ch4_flag},
    }


def test_surf_skips_air_row_and_uses_next_water_sample():
    """Today ch4_surf = 1972.3 (the EGAMES_Air value). It must become 2.05."""
    casts = derive_casts([
        _sample(6.0, ch4=1972.3, n2o=310.1, label="EGAMES_Air"),
        _sample(9.0, ch4=2.35, n2o=8.59, label="6101701"),
        _sample(1.8, ch4=2.05, n2o=8.60, label="6101702"),
    ])
    assert len(casts) == 1
    assert casts[0]["ch4_surf"] == 2.05
    assert casts[0]["n2o_surf"] == 8.60


def test_surf_skips_flag9_missing_as_zero():
    """ch4_flag == 9 means missing; 1,558 such rows hold exactly 0.00."""
    casts = derive_casts([
        _sample(1.0, ch4=0.0, label="a", ch4_flag=9),
        _sample(5.0, ch4=2.17, label="b"),
    ])
    assert casts[0]["ch4_surf"] == 2.17


def test_surf_skips_non_positive_values():
    casts = derive_casts([
        _sample(1.0, ch4=0.0, label="a"),
        _sample(5.0, ch4=2.11, label="b"),
    ])
    assert casts[0]["ch4_surf"] == 2.11


def test_surf_is_none_when_every_sample_is_air():
    """EGAMES has no non-air CH4 rows at all."""
    casts = derive_casts([_sample(6.0, ch4=1972.3, label="EGAMES_Air")])
    assert casts[0]["ch4_surf"] is None


def test_has_ch4_still_reflects_raw_presence():
    """has_* describes what the archive contains; it is not a water-only claim."""
    casts = derive_casts([_sample(6.0, ch4=1972.3, label="EGAMES_Air")])
    assert casts[0]["has_ch4"] is True
