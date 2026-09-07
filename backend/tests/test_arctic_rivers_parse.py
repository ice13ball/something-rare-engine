# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Unit tests for the Arctic River Inputs pure parsers.

ArcticGRO + PANGAEA-CAA tests run against REAL sample files saved under
fixtures/arctic_rivers/ (a real ArcticGRO 'Ob' tab CSV export and a real
PANGAEA.945702 textfile slice), so they verify parsing of the actual schemas
— not invented formats.
"""
import os
import datetime as dt

import pytest

from backend.ingestion.arctic_rivers import (
    _station_id, _monthly_downsample, _is_num, _read_pangaea_tab,
    build_arcticgro_stations, build_pangaea_caa_stations,
)

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "arctic_rivers")

skip_no_fixture = pytest.mark.skipif(
    not os.path.exists(os.path.join(FIX, "arcticgro_ob_real.csv")),
    reason="fixture licence is not stated by the upstream (arctic-rivers) and it is excluded "
           "from the public repository — see DATA-LICENCES.md",
)


# ── helpers ──────────────────────────────────────────────────────────────────
def test_station_id_slugifies():
    assert _station_id("arcticgro", "Lena") == "arcticgro:lena"
    assert _station_id("pangaea_caa", "Cunningham Inlet") == "pangaea_caa:cunningham-inlet"


def test_is_num_rejects_bool_and_nan():
    assert _is_num(3) and _is_num(2.5)
    assert not _is_num(True) and not _is_num(False)
    assert not _is_num(float("nan")) and not _is_num(None)


def test_monthly_downsample_means_and_sorts():
    series = [
        (dt.date(2010, 1, 5), 10.0),
        (dt.date(2010, 1, 20), 20.0),   # same month → mean 15
        (dt.date(2009, 12, 1), 4.0),
        (dt.date(2010, 1, 9), None),    # skipped
    ]
    assert _monthly_downsample(series) == [["2009-12", 4.0], ["2010-01", 15.0]]


def test_monthly_downsample_skips_nan_and_empty():
    assert _monthly_downsample([]) == []
    assert _monthly_downsample([(dt.date(2010, 1, 1), float("nan"))]) == []


# ── ArcticGRO (real 'Ob' tab fixture) ────────────────────────────────────────
@skip_no_fixture
def test_build_arcticgro_ob_real():
    with open(os.path.join(FIX, "arcticgro_ob_real.csv"), encoding="utf-8") as f:
        text = f.read()
    stations = {s["station_id"]: s for s in build_arcticgro_stations([text])}

    ob = stations["arcticgro:ob"]
    assert ob["source"] == "arcticgro"
    assert ob["river_name"] == "Ob"            # sheet label "Ob'" normalised
    assert ob["site_label"] == "Salekhard"
    assert abs(ob["lat"] - 66.63) < 1e-9 and abs(ob["lon"] - 66.60) < 1e-9
    assert ob["geom_wkt"].startswith("POINT(66.6 66.63")
    # real first row: 2003-07-16 → DOC 11.0, discharge 31200 (month is unique in fixture)
    assert ["2003-07", 11.0] in ob["biogeochem_monthly"]["doc"]
    assert ["2003-07", 31200.0] in ob["discharge_monthly"]
    assert ob["summary_stats"]["doc"] is not None
    assert ob["summary_stats"]["discharge_m3s"] is not None
    # v1 does not fake annual integration
    assert ob["mean_annual_discharge_km3"] is None
    assert ob["annual_fluxes"] is None
    assert "ArcticGRO" in ob["citation"] or "Arctic Great Rivers" in ob["citation"]


def test_build_arcticgro_unknown_river_skipped():
    text = (
        "ArcticGRO Water Quality Data,,,,,\n"
        "Phase,River,Date,ID,Discharge,Discharge\n"
        "project,name,YYYY-MM-DD,code,m3/sec,flag\n"
        "PARTNERS,Thames,2011-01-01,,100,AV\n"
    )
    assert build_arcticgro_stations([text]) == []


def test_build_arcticgro_skips_deleted_flag():
    text = (
        "x,,,,,,,\n"
        "Phase,River,Date,ID,Discharge,Discharge,DOC,DOC\n"
        "project,name,YYYY-MM-DD,code,m3/sec,flag,mg/L,flag\n"
        "PARTNERS,Ob',2011-06-15,,500,AV,9.9,DV\n"   # DOC flagged DV (deleted) → dropped
    )
    ob = build_arcticgro_stations([text])[0]
    assert ob["discharge_monthly"] == [["2011-06", 500.0]]
    assert "doc" not in ob["biogeochem_monthly"]      # the only DOC value was deleted


# ── PANGAEA CAA (real 945702 fixture) ────────────────────────────────────────
@skip_no_fixture
def test_build_pangaea_caa_real():
    rows = _read_pangaea_tab(os.path.join(FIX, "pangaea_caa_real.tab"))
    stations = {s["station_id"]: s for s in build_pangaea_caa_stations(rows)}

    bay = stations["pangaea_caa:baychimo-river"]
    assert bay["source"] == "pangaea_caa"
    assert bay["river_name"] == "Baychimo River"
    assert abs(bay["lat"] - 67.6964) < 1e-6 and abs(bay["lon"] - (-107.9133)) < 1e-6
    assert bay["biogeochem_monthly"]["doc"] == [["2016-08", 5.0]]
    assert bay["discharge_monthly"] is None and bay["annual_fluxes"] is None
    assert "PANGAEA" in bay["citation"]
    # a site with no DOC/nutrient data (groundwater seep) is skipped entirely
    assert "pangaea_caa:groundwater-seeps-on-rocky-island" not in stations

    # physical / water-isotope columns (δ18O, δD) are now captured alongside
    # biogeochemistry. Back River, Sept 2017: DOC 7.5/3.2, δ18O -18.8/-18.8,
    # δD -149/-148 → means 5.35 / -18.8 / -148.5.
    back = stations["pangaea_caa:back-river"]
    assert abs(back["summary_stats"]["doc"] - 5.35) < 1e-9
    assert abs(back["summary_stats"]["d18o"] - (-18.8)) < 1e-9
    assert abs(back["summary_stats"]["dd"] - (-148.5)) < 1e-9
    d18o_series = back["biogeochem_monthly"]["d18o"]
    assert d18o_series[0][0] == "2017-09" and abs(d18o_series[0][1] - (-18.8)) < 1e-9
