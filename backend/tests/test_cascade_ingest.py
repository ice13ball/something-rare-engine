# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import os
from backend.ingestion import cascade_ingest as c

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "cascade", "CASCADEsurfsed_v2_sample.txt")

def _text():
    with open(FIX, encoding="latin-1") as f:
        return f.read()

def test_parses_all_rows_with_coords():
    rows = c.build_station_rows(_text())
    assert len(rows) >= 25          # 30 sample rows, minus any lacking coords
    for r in rows:
        assert -90 <= r["lat"] <= 90 and -180 <= r["lon"] <= 180

def test_first_station_fields():
    rows = c.build_station_rows(_text())
    r0 = next(r for r in rows if r["station"] == "YS-4")
    assert abs(r0["lat"] - 75.987) < 1e-3
    assert abs(r0["lon"] - 129.984) < 1e-3
    assert abs(r0["oc_pct"] - 1.34) < 1e-3
    assert r0["year"] == 2008
    assert r0["decade"] == 2000

def test_blank_cells_become_none():
    rows = c.build_station_rows(_text())
    # at least one measured column is None somewhere in the sample
    assert any(r["d14c"] is None for r in rows)

def test_params_holds_citation_text():
    rows = c.build_station_rows(_text())
    assert any(isinstance(r["params"], dict) for r in rows)

def test_resolve_ignores_citation_and_method_columns():
    # Synthetic header with citation/method columns for d13c/d14c placed
    # BEFORE their value columns, to prove _resolve doesn't just get lucky
    # from real-header column order (first-match-wins would otherwise pick
    # the citation/method column here).
    header = [
        "ID", "STATION", "LAT", "LON", "WATERDEPTH (mbsl)", "EXPEDITION", "YEAR",
        "d13C_CITATION", "d13C_METHOD", "D14C_CITATION", "D14C_LABEL",
        "OC (%)", "TN (%)", "OC_TN",
        "d13C (permil)", "D14C (permil)",
        "HMWALK (ug g-1 OC)", "HMWACID (ug g-1 OC)", "LIGNIN",
    ]
    idx = c._resolve(header)
    assert idx["d13c"] == header.index("d13C (permil)")
    assert idx["d14c"] == header.index("D14C (permil)")
