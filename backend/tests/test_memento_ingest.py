# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import pathlib
import pytest
from backend.ingestion.memento_ingest import build_samples, derive_casts, NO_VALUE

FIX = pathlib.Path(__file__).parent / "fixtures" / "memento"

pytestmark = pytest.mark.skipif(
    not (FIX / "leg_300_baltic.csv").exists(),
    reason="fixture is licence-restricted (MEMENTO terms of use — contributing scientist must "
           "be contacted before publishing results) and excluded from the public repository — "
           "see DATA-LICENCES.md",
)

def _read(name):
    return (FIX / name).read_text()

def test_baltic_ch4_only():
    rows = build_samples(_read("leg_300_baltic.csv"), "Baltic Sea CH4 profiles (2011 to 2013)")
    assert len(rows) > 900
    r = rows[0]
    assert r["set_name"].startswith("Baltic")
    assert r["depth_m"] == 10.0
    assert abs(r["lat"] - 57.116667) < 1e-5 and abs(r["lon"] - 17.666667) < 1e-5
    assert r["sample_time"].year == 2011
    # CH4 stored in params (ch4_kg), not first-class ch4 (nmol/l); flag captured
    assert r["params"]["ch4_kg"] is not None
    assert r["params"]["ch4_kg_flag"] == -1
    assert r["ch4"] is None and r["n2o"] is None  # this leg has neither nmol/l col

def test_sfb754_multiparam_and_sentinel():
    rows = build_samples(_read("leg_166_sfb754.csv"), "SFB754  (M77/3)")
    r = rows[0]
    assert r["n2o"] is not None                     # first-class n2o (nmol/l)
    assert r["temp"] is not None and r["sal"] is not None
    # -999.0 sentinel -> None (no3/no2/po4 were -999 in row 1)
    assert r["params"]["no3"] is None
    assert r["station"] == "022-1"
    # first-class values NOT duplicated in params; their flags remain
    assert "n2o" not in r["params"]                 # first-class value lives top-level only
    assert "n2o_flag" in r["params"]                # its flag stays in params

def test_derive_casts_groups_depths():
    rows = build_samples(_read("leg_166_sfb754.csv"), "SFB754  (M77/3)")
    casts = derive_casts(rows)
    assert len(casts) < len(rows)                   # multiple depths collapse to casts
    c = casts[0]
    assert c["n_samples"] >= 1
    assert c["has_n2o"] is True
    assert c["max_depth_m"] >= c["min_depth_m"]
    assert len(c["cast_id"]) == 16
    # surface representative value = shallowest non-null sample's gas
    assert "n2o_surf" in c
