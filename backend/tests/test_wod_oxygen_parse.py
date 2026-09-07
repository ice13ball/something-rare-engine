# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import datetime
import numpy as np
from ingestion.wod_oxygen_ingest import build_oxygen_rows


def _args():
    # cast0: Arctic (lat 60), 3 z-levels, middle oxygen NaN (flag -127 = missing)
    # cast1: lat 10 -> filtered out by min_lat
    return dict(
        wod_cast_id=np.array([111, 222]),
        lat=np.array([60.0, 10.0]), lon=np.array([-20.0, -20.0]),
        time_days=np.array([89536.0, 89536.0]),
        country=np.array(["US", "US"]),
        z=np.array([5.0, 50.0, 100.0, 5.0, 50.0]),
        z_row_size=np.array([3, 2]),
        oxygen=np.array([300.0, np.nan, 280.0, 250.0, 240.0]),
        oxygen_flag=np.array([0, -127, 0, 0, 0]),
        # Both casts measured oxygen at every z level, so here (and ONLY here)
        # the oxygen offsets coincide with the z offsets. Real WOD files do not
        # have this property — see test_wod_oxygen_ragged.py.
        oxygen_row_size=np.array([3, 2]),
        oxygen_units="umol/kg", dataset="OSD",
    )


def test_arctic_only_and_drops_nan_levels():
    rows = build_oxygen_rows(min_lat=50.0, **_args())
    assert len(rows) == 1                       # cast1 (lat 10) excluded
    r = rows[0]
    assert r["wod_cast_id"] == "111"
    assert r["o2_profile"] == [[5.0, 300.0], [100.0, 280.0]]   # NaN level dropped, ascending
    assert r["n_levels"] == 2 and r["max_depth_m"] == 100.0
    assert r["decade"] % 10 == 0
    assert "mol/kg" in r["o2_units"]
    assert isinstance(r["profile_date"], datetime.date)
    assert r["dataset"] == "OSD"


def test_min_lat_excludes_all():
    assert build_oxygen_rows(min_lat=90.0, **_args()) == []


def test_decade_matches_date():
    r = build_oxygen_rows(min_lat=50.0, **_args())[0]
    assert r["decade"] == (r["profile_date"].year // 10) * 10
