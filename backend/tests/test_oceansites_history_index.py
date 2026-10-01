# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""The OceanSITES GDAC index parser and the mooring↔file matcher.

Every row below is a line of the REAL index
(``ftp://ftp.ifremer.fr/ifremer/oceansites/oceansites_index.txt``, captured
2026-10-01, copied verbatim into ``fixtures/oceansites_gdac/oceansites_index_sample.txt``),
and every station is a real ``oceansites_stations`` / ``oceansites_deployments``
row read from production the same day (``production_moorings.json``). A parser
test over invented rows would pass on the format its author imagined; the traps
here are the ones the server actually ships.

⛔ What these tests protect: precision. An unlinked mooring is correct; a
mooring shown with its neighbour's record is not. Each "must NOT link" case is a
station that sits within 25 km of a file that is not its own.
"""
import json
from pathlib import Path

import pytest

from ingestion import oceansites_history as h

FIX = Path(__file__).parent / "fixtures" / "oceansites_gdac"
INDEX_TEXT = (FIX / "oceansites_index_sample.txt").read_text(encoding="utf-8")
_MOORINGS_FILE = FIX / "production_moorings.json"


def _moorings() -> dict:
    """OceanOPS register rows. ⛔ Withheld from the public mirror (all rights reserved,
    non-commercial; scripts/export-public.sh NEVER_RULES), so a test that needs them
    skips there instead of erroring."""
    if not _MOORINGS_FILE.exists():
        pytest.skip("production_moorings.json is withheld from the public mirror (OceanOPS terms)")
    return json.loads(_MOORINGS_FILE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def rows():
    return {r["file"].rsplit("/", 1)[-1]: r for r in h.parse_index(INDEX_TEXT)}


@pytest.fixture(scope="module")
def all_rows():
    return h.parse_index(INDEX_TEXT)


def _stations():
    return [dict(s) for s in _moorings()["stations"]]


def _deployments():
    return [
        {"base_ref": ref, **d}
        for ref, ds in _moorings()["deployments"].items() for d in ds
    ]


@pytest.fixture(scope="module")
def matched(all_rows):
    links, rejected = h.match_files(_stations(), _deployments(), all_rows)
    by_station: dict[str, set[str]] = {}
    for l in links:
        by_station.setdefault(l["station_ref"], set()).add(l["file"].rsplit("/", 1)[-1])
    rej_by_station: dict[str, set[str]] = {}
    for r in rejected:
        rej_by_station.setdefault(r["station_ref"], set()).add(r["file"].rsplit("/", 1)[-1])
    return by_station, rej_by_station, links, rejected


# ─────────────────────────────────────────────────────────────────────────────
# parse_index — one test per trap in the real file
# ─────────────────────────────────────────────────────────────────────────────

def test_comments_fragment_and_gridded_are_not_rows(all_rows):
    # the fixture has 8 comment lines, 1 continuation fragment, 1 DATA_GRIDDED.
    assert len(all_rows) == 54
    assert not any(r["file"].startswith("DATA_GRIDDED/") for r in all_rows)
    assert not any("values surface_partial" in r["file"] for r in all_rows)


def test_unknown_date_update_is_null_not_a_crash(rows):
    r = rows["OS_ACO_20110613-08-16_P_CTD3-4726m.nc"]
    assert r["date_update"] is None  # "unknown"
    # GDAC_UPDATE_DATE is "50" on ALOHA (the columns are shifted there): not a date.
    assert r["gdac_update_date"] is None
    assert r["start_time"].isoformat() == "2011-06-13T08:00:00+00:00"


def test_t24_midnight_is_the_next_day(rows):
    r = rows["OS_ACO_20110613-16-24_P_CTD3-4726m.nc"]
    assert r["end_time"].isoformat() == "2011-06-14T00:00:00+00:00"


def test_seconds_sixty_and_trailing_junk_in_timestamps(rows):
    r = rows["OS_WHOTS_200507_D_NGVM-010m.nc"]  # 03:42:0000Z .. 18:29:60Z
    assert r["start_time"].isoformat() == "2005-07-28T03:42:00+00:00"
    assert r["end_time"].isoformat() == "2006-06-24T18:30:00+00:00"
    r = rows["OS_WHOTS_200806_D_NGVM-030m.nc"]  # 18:20:00000Z
    assert r["end_time"].isoformat() == "2009-04-16T18:20:00+00:00"


def test_whots_latitude_repeated_in_longitude_columns_is_not_a_position(rows):
    # Real row: 22.70 four times. WHOTS sits at -158; reading it as lon +22.7
    # would put a Hawaiian mooring in the Sahara.
    r = rows["OS_WHOTS_200408-202108_D_MLTS-1H.nc"]
    assert r["position_source"] == "site_median"
    assert r["lat"] == pytest.approx(22.77, abs=0.1)
    assert r["lon"] == pytest.approx(-157.9, abs=0.1)
    ok = rows["OS_WHOTS_200408-202308_D_MLTS-1H.nc"]  # its neighbour with a real box
    assert ok["position_source"] == "index"
    assert ok["lon"] < -157


def test_fill_corner_and_zero_corner_boxes_fall_back_to_the_moorings_median(rows):
    # E1M3A 2007: S=0, W=0 beside N=35.8, E=24.96 — a 35-degree "box".
    r = rows["OS_E1M3A_2007_R.nc"]
    assert r["position_source"] == "site_median"
    assert 35.7 < r["lat"] < 35.8 and 24.9 < r["lon"] < 25.5
    # SATS: N and E columns hold 10000.00.
    s = rows["OS_SATS_201811_P_AGLBuoy.nc"]
    assert s["position_source"] == "site_median"
    assert s["lat"] == pytest.approx(43.885, abs=0.05)
    assert s["lon"] == pytest.approx(-3.795, abs=0.05)


def test_a_row_with_no_valid_sibling_gets_no_position_rather_than_a_guess():
    # Parsed alone, so its directory holds no valid position to borrow.
    line = next(l for l in INDEX_TEXT.splitlines() if "OS_FRAM_F1-15_D.nc" in l)
    (r,) = h.parse_index(line)  # unknown everywhere, empty start/end/parameters
    assert r["lat"] is None and r["lon"] is None and r["position_source"] is None
    assert r["start_time"] is None and r["end_time"] is None
    assert r["parameters"] == []
    assert r["data_mode"] == "D"


def test_a_median_is_refused_when_the_moorings_in_a_directory_disagree():
    # LINE-W holds W1..W5, ~135 km apart. A position-less row of a mooring that
    # has no valid row of its own (W7 here — the row is the real FRAM "unknown"
    # line with its path renamed) must not get a median between W1 and W4.
    w = [l for l in INDEX_TEXT.splitlines()
         if "OS_LINE-W1_" in l or "OS_LINE-W4_" in l]
    blank = next(l for l in INDEX_TEXT.splitlines() if "OS_FRAM_F1-15_D.nc" in l)
    blank = blank.replace("DATA/FRAM/OS_FRAM_F1-15_D.nc", "DATA/LINE-W/OS_LINE-W7_D.nc")
    rows = h.parse_index("\n".join(w + [blank]))
    assert len(rows) == 3
    assert next(r for r in rows if "W7" in r["file"])["lat"] is None


def test_pap_two_degree_box_is_a_position_not_a_track(rows):
    r = rows["OS_PAP-1_200307_D_Chl.nc"]  # 48-50 N, -17..-16 E
    assert (r["lat"], r["lon"]) == (49.0, -16.5)
    assert r["position_source"] == "index"


def test_depth_fill_99999_is_null(rows):
    assert rows["OS_CIS-1_200809_Chl.nc"]["max_depth"] is None  # "99999"
    assert rows["OS_CIS-1_200809_Chl.nc"]["min_depth"] == 45.8


def test_r_only_five_token_filename(rows):
    r = rows["OS_MBARI-M1_20260619_R_TS.nc"]
    assert r["platform_code"] == "MBARI-M1"
    assert r["data_mode"] == "R"
    assert r["site_dir"] == "MBARI"
    assert r["size_bytes"] == 124584


def test_missing_data_mode_is_null(rows):
    assert rows["OS_E2M3A_2006-2008_D_CTD.nc"]["data_mode"] is None  # empty column
    assert rows["OS_E2M3A_2006-2008_D_CTD.nc"]["lat"] == 41.8355


def test_free_text_in_parameters_is_not_kept_as_a_standard_name(rows):
    p = rows["OS_PAP-1_201006_R_PCO2.nc"]["parameters"]
    # The real cell ends "... Standard deviation of" and wraps onto a fragment
    # line. Only CF-shaped names and the bare coordinates survive.
    assert "surface_partial_pressure_of_carbon_dioxide_in_sea_water" in p
    assert "sea_water_pressure" in p and "time" in p
    for junk in ("Standard", "deviation", "of"):
        assert junk not in p


def test_every_row_is_keyed_by_a_data_path(all_rows):
    for r in all_rows:
        assert r["file"].startswith("DATA/") and r["file"].endswith(".nc")
        assert r["site_dir"] == r["file"].split("/")[1]


@pytest.mark.parametrize("path,expected", [
    ("DATA/CCE1/OS_CCE1_01_D_AQUADOPP.nc", "CCE1"),
    ("DATA/MBARI/OS_MBARI-M1_20260619_R_TS.nc", "MBARI-M1"),
    ("DATA/E1M3A/OS_E1M3A_2007_R.nc", "E1M3A"),
    ("DATA/T0N140W/OS_T0N140W_CA020-20160228_D_ADCP.nc", "T0N140W"),
    ("DATA/LINE-W/OS_LINE-W3_200110_D_PART1.nc", "LINE-W3"),
    ("DATA/ALOHA/OS_ACO_20110613-08-16_P_CTD3-4726m.nc", "ACO"),
    ("DATA/X/notOS_thing.nc", None),
])
def test_platform_from_filename(path, expected):
    assert h.platform_from_filename(path) == expected


# ─────────────────────────────────────────────────────────────────────────────
# names_compatible
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,platform,site_dir,expected", [
    # TAO grid: OceanOPS drops the leading T of the directory.
    ("0N140W", "T0N140W", "T0N140W", True),
    ("0N140W", "T2N140W", "T2N140W", False),
    ("2N140W", "T2N140W", "T2N140W", True),
    # PIRATA / the trailing \xa0 OceanOPS puts on some names (3100006 is real).
    ("12N23W", "P12N23W", "P12N23W", True),
    ("4N23W\xa0", "P4N23W", "P4N23W", True),
    # exact / prefix either way, shorter side >= 3
    ("PAP-1", "PAP-1", "PAP", True),
    ("IMOS-EAC0500", "IMOS-EAC", "IMOS-EAC", True),
    ("MOVE2P", "MOVE2", "MOVE2", True),
    ("AB", "ABC", "X", False),                     # shorter side under 3 chars
    # siblings in one directory are NOT the same mooring
    ("PAP-1", "PAP-2", "PAP", False),
    ("PAP-2", "PAP-3", "PAP", False),
    ("MBARI-M1", "MBARI-M0", "MBARI", False),
    ("LINE-W2", "LINE-W3", "LINE-W", False),
    ("ESTOC-1", "ESTOC-C", "ESTOC", False),
    # CCE1 is not CCE17 even though one is a string prefix of the other
    ("CCE1", "CCE17", "CCE17", False),
    # deployment suffix after the platform
    ("CCE1-17", "CCE1", "CCE1", True),
    ("CCE2-19", "CCE1", "CCE1", False),
    ("EC1_23", "EC1", "EC1", True),
    # directory name inside the station name
    ("60N_40W_CIS_14", "CIS-1", "CIS", True),
    ("60N_40W_CIS_14", "CIS-2", "CIS", True),
    ("60N_40W_CIS_14", "PAP-1", "PAP", False),
    # nothing in common
    ("CALCOFI-080-055", "CCE2", "CCE2", False),
    ("OFP", "BATS-1", "BATS", False),
    ("ADCP1", "T2N165E", "T2N165E", False),
    ("2100210", "JKEO", "JKEO", False),
    ("", "JKEO", "JKEO", False),
    ("PAP-1", None, None, False),
])
def test_names_compatible(name, platform, site_dir, expected):
    assert h.names_compatible(name, platform, site_dir) is expected


def test_id_conflict_vetoes_another_mooring_of_the_same_array():
    # Platform FRAM for every mooring; the mooring id sits in the deployment token.
    assert h.names_compatible("FRAM_F3-18", "FRAM", "FRAM", "DATA/FRAM/OS_FRAM_F3-1_D.nc")
    assert not h.names_compatible("FRAM_F3-18", "FRAM", "FRAM", "DATA/FRAM/OS_FRAM_F4-1_D.nc")
    assert not h.names_compatible("FRAM_F3-18", "FRAM", "FRAM", "DATA/FRAM/OS_FRAM_FEVI15_D.nc")
    assert not h.names_compatible(
        "IMOS-EAC4700", "IMOS-EAC", "IMOS-EAC",
        "DATA/IMOS-EAC/OS_IMOS-EAC_EAC4800-2015-2016_D_AQUADOPP.nc",
    )
    # A file that carries no comparable id says nothing: not vetoed.
    assert h.names_compatible("CCE1-17", "CCE1", "CCE1", "DATA/CCE1/OS_CCE1_01_D_AQUADOPP.nc")


# ─────────────────────────────────────────────────────────────────────────────
# match_files — real index rows against real production moorings
# ─────────────────────────────────────────────────────────────────────────────

def test_tao_grid_0n140w_links_t0n140w(matched):
    by, _rej, links, _ = matched
    assert by["5100311"] == {"OS_T0N140W_CA020-20160228_D_ADCP.nc"}
    link = next(l for l in links if l["station_ref"] == "5100311")
    assert link["rule"] == "tao-prefix" and link["distance_km"] < 1


def test_pirata_p12n23w_links_through_its_directory_prefix(matched):
    by, *_ = matched
    assert by["1300001"] == {"OS_P12N23W_200606_M_TVSM_dy.nc"}


def test_pap_siblings_each_get_only_their_own_files(matched):
    by, rej, *_ = matched
    # PAP-1, PAP-2 and PAP-3 all sit at ~49N 16.5W, within 6 km of each other.
    assert by["6801011"] == {"OS_PAP-1_201006_R_PCO2.nc", "OS_PAP-1_200307_D_Chl.nc"}
    # PAP-2_200210's box is 48.5-50.5 N: its midpoint (49.5) is 55 km from the
    # PAP-2 mooring at 49.0, but the mooring is INSIDE the box.
    assert by["TMP236332161"] == {"OS_PAP-2_200311_D_CTD.nc", "OS_PAP-2_200210_D_CTD.nc"}
    assert by["TMP24FHQDSDQ8"] == {"OS_PAP-3_201205_P_deepTS.nc"}
    # and the siblings' files are what the position check alone would have taken
    assert "OS_PAP-3_201205_P_deepTS.nc" in rej["6801011"]
    assert {"OS_PAP-1_200307_D_Chl.nc", "OS_PAP-3_201205_P_deepTS.nc"} <= rej["TMP236332161"]


def test_cce_deployment_station_links_its_array_file(matched):
    by, *_ = matched
    assert by["4801002"] == {"OS_CCE1_01_D_AQUADOPP.nc"}
    assert by["4801003"] == {"OS_CCE2_01_D_AQUADOPP.nc"}


def test_calcofi_station_beside_cce2_must_not_link(matched):
    by, rej, *_ = matched
    # CALCOFI 080-055 is a ship CTD station 1.4 km from the CCE2 mooring.
    assert "TMPWKF6YRWPMI" not in by
    assert rej["TMPWKF6YRWPMI"] == {"OS_CCE2_01_D_AQUADOPP.nc"}


def test_station_m_links_station_m_1(matched):
    by, *_ = matched
    assert by["6301862"] == {"OS_STATION-M-1_194810_D_CTD.nc"}


def test_cis_directory_token_inside_the_station_name(matched):
    by, _rej, links, _ = matched
    assert by["4400478"] == {
        "OS_CIS-1_200608_Chl.nc", "OS_CIS-1_200809_Chl.nc", "OS_CIS-2_200208_D_CTD.nc",
    }
    assert {l["rule"] for l in links if l["station_ref"] == "4400478"} == {"site-token"}


def test_imos_eac0500_links_its_array_file(matched):
    by, *_ = matched
    assert by["5801008"] == {"OS_IMOS-EAC_EAC0500-2015-2016_D_AQUADOPP-CURRENT-METER-462-m.nc"}


def test_line_w_stations_link_only_their_own_w_number(matched):
    by, rej, *_ = matched
    assert by["TMP153499973"] == {"OS_LINE-W3_200110_D_PART1.nc"}   # LINE-W3
    assert by["TMP389461662"] == {"OS_LINE-W5_200404_D_PART1.nc"}   # LINE-W5, not W4 23 km away
    assert "OS_LINE-W4_200404_D_PART1.nc" in rej["TMP389461662"]
    # LINE-W2 has no W2 file in this slice; W1 is 16 km away and must not be taken.
    assert "TMP864727592" not in by
    assert rej["TMP864727592"] == {"OS_LINE-W1_200405_D_PART1.nc"}


def test_unnamed_reference_number_is_not_linked(matched):
    by, *_ = matched
    assert "2100210" not in by  # named by its own ref; the JKEO files are not in this slice either


def test_bats_ofp_ctd_station_does_not_take_a_bats_file(matched):
    by, rej, *_ = matched
    assert "TMPMCBDA2PKST" not in by
    assert rej["TMPMCBDA2PKST"] == {"OS_BATS-1_BATSBLMA-0016-1_D_BTL.nc"}
    assert by["TMP241361341"] == {"OS_BHYDROS_HYDROS-1204-1_D_CTD.nc"}   # BHYDROS, same name


def test_adcp_station_on_a_tao_site_does_not_take_the_tao_file(matched):
    by, rej, *_ = matched
    assert "TMP9GOSI0LW8M" not in by
    assert rej["TMP9GOSI0LW8M"] == {"OS_T2N165E_DM054A-20130814_D_AIRT_10min.nc"}


def test_whots_does_not_take_the_aloha_chunks_8_km_away(matched):
    by, rej, *_ = matched
    assert by["5100400"] == {
        "OS_WHOTS_200408-202108_D_MLTS-1H.nc", "OS_WHOTS_200408-202308_D_MLTS-1H.nc",
        "OS_WHOTS_200507_D_NGVM-010m.nc", "OS_WHOTS_200806_D_NGVM-030m.nc",
    }
    assert {"OS_ACO_20110613-08-16_P_CTD3-4726m.nc",
            "OS_ACO_20110613-16-24_P_CTD3-4726m.nc"} <= rej["5100400"]


def test_median_repaired_row_still_has_to_pass_the_name_check(matched):
    by, *_ = matched
    # E1M3A 2007/2008 carry a site_median position; the station links them
    # because the name matches, not because the position happens to be near.
    assert {"OS_E1M3A_2007_R.nc", "OS_E1M3A_2008_R.nc"} <= by["6100277"]


def test_deployment_position_far_from_the_station_row_still_links(matched):
    # Stratus23's station row sits 269 km from the 2000 Stratus file; one of its
    # deployments sits 24 km away. 31 real base refs have deployments >1 deg apart.
    by, _rej, links, _ = matched
    assert by["3800400"] == {"OS_Stratus_2000_D_M.nc"}
    assert next(l for l in links if l["station_ref"] == "3800400")["distance_km"] < 25


def test_fram_array_moorings_do_not_share_files(matched):
    by, *_ = matched
    assert by["6801022"] == {"OS_FRAM_F3-1_D.nc"}   # FRAM_F3-18: not F4-1, not FEVI15
    assert by["6801023"] == {"OS_FRAM_F4-1_D.nc"}   # FRAM_F4-19


def test_mbari_m0_and_m1_stay_apart(matched):
    by, *_ = matched
    assert "TMP138929924" not in by                   # M0: no M0 file in the slice
    assert by["TMP199424151"] == {"OS_MBARI-M1_20260619_R_TS.nc"}


def test_every_link_is_within_25_km_and_carries_a_rule(matched):
    *_, links, _ = matched
    assert links
    for l in links:
        assert 0 <= l["distance_km"] <= h.MAX_LINK_KM
        assert l["rule"] in {"exact", "tao-prefix", "token-prefix", "prefix", "alias", "site-token"}


def test_no_station_row_means_no_link_not_an_error(all_rows):
    links, rejected = h.match_files([], [], all_rows)
    assert links == [] and rejected == []
    links, rejected = h.match_files(_stations(), _deployments(), [])
    assert links == [] and rejected == []


def test_a_file_without_a_position_never_links():
    files = [{"file": "DATA/PAP/OS_PAP-1_x.nc", "site_dir": "PAP", "platform_code": "PAP-1",
              "lat": None, "lon": None}]
    st = [{"ref": "1", "name": "PAP-1", "lat": 49.0, "lon": -16.5}]
    assert h.match_files(st, [], files) == ([], [])


def test_the_dateline_does_not_hide_a_neighbour():
    files = [{"file": "DATA/T0N180W/OS_T0N180W_x_D_y.nc", "site_dir": "T0N180W",
              "platform_code": "T0N180W", "lat": 0.0, "lon": 179.9}]
    st = [{"ref": "1", "name": "0N180W", "lat": 0.0, "lon": -179.9}]  # 22 km east of it
    links, _ = h.match_files(st, [], files)
    assert [l["file"] for l in links] == [files[0]["file"]]


# ─────────────────────────────────────────────────────────────────────────────
# Distance to the file's bounding box
# ─────────────────────────────────────────────────────────────────────────────

def test_parse_keeps_the_box_and_borrowed_positions_are_points(rows):
    r = rows["OS_PAP-2_200210_D_CTD.nc"]  # real: 48.5-50.5 N, -17..-16 E
    assert (r["bbox_south"], r["bbox_north"], r["bbox_west"], r["bbox_east"]) == (48.5, 50.5, -17.0, -16.0)
    assert (r["lat"], r["lon"]) == (49.5, -16.5)                     # midpoint, kept for display
    m = rows["OS_WHOTS_200408-202108_D_MLTS-1H.nc"]                  # site_median: a point
    assert m["bbox_south"] == m["bbox_north"] == m["lat"]
    assert m["bbox_west"] == m["bbox_east"] == m["lon"]
    bad = h.parse_index(next(l for l in INDEX_TEXT.splitlines() if "OS_FRAM_F1-15_D.nc" in l))[0]
    assert bad["bbox_south"] is None and bad["bbox_west"] is None


def test_pap_2_station_links_the_file_whose_midpoint_is_55_km_away(matched):
    by, _rej, links, _ = matched
    assert "OS_PAP-2_200210_D_CTD.nc" in by["TMP236332161"]
    link = next(l for l in links if l["station_ref"] == "TMP236332161"
                and l["file"].endswith("OS_PAP-2_200210_D_CTD.nc"))
    assert link["distance_km"] == 0.0 and link["rule"] == "exact"


def test_distance_to_box_inside_edge_corner_and_dateline():
    box = (48.5, 50.5, -17.0, 1.0)            # south, north, west, width in degrees
    assert h.distance_to_box_km(49.0, -16.5, box) == 0.0              # inside
    assert h.distance_to_box_km(49.0, -17.0, box) == 0.0              # on the edge
    # 0.1 degree of latitude north of the box is 11.1 km, straight to the edge
    assert h.distance_to_box_km(50.6, -16.5, box) == pytest.approx(11.1, abs=0.1)
    # beyond the NE corner: the corner is the nearest point
    assert h.distance_to_box_km(50.6, -15.9, box) == pytest.approx(
        h.haversine_km(50.6, -15.9, 50.5, -16.0), abs=1e-6)
    # a box straddling the dateline (179.9 .. -179.9) contains 180
    wrap = (0.0, 0.2, 179.9, 0.2)
    assert h.distance_to_box_km(0.1, 180.0, wrap) == 0.0
    assert h.distance_to_box_km(0.1, -179.5, wrap) == pytest.approx(
        h.haversine_km(0.1, -179.5, 0.1, -179.9), abs=1e-6)  # east edge = -179.9


def test_a_box_wider_than_25_km_from_the_station_still_does_not_link():
    f = {"file": "DATA/PAP/OS_PAP-2_x.nc", "site_dir": "PAP", "platform_code": "PAP-2",
         "lat": 49.5, "lon": -16.5, "bbox_south": 49.5, "bbox_north": 50.5,
         "bbox_west": -17.0, "bbox_east": -16.0}
    near = [{"ref": "1", "name": "PAP-2", "lat": 49.4, "lon": -16.5}]    # 11 km south of the box
    far = [{"ref": "2", "name": "PAP-2", "lat": 49.0, "lon": -16.5}]     # 55 km south of it
    assert len(h.match_files(near, [], [f])[0]) == 1
    assert h.match_files(far, [], [f])[0] == []


# ─────────────────────────────────────────────────────────────────────────────
# Alias table: SOFS-* -> SOTS, KE### -> KEO/KEOK7, PA### -> PAPA
# ─────────────────────────────────────────────────────────────────────────────

def test_sofs_station_links_sofs_files_only_by_deployment_number(matched):
    by, rej, links, _ = matched
    # Real station 5800450 ("SOFS-12", 14 deployments SOFS-1..SOFS-12).
    got = by["5800450"]
    assert {"OS_SOTS_SOFS09_D_ASIMET.nc", "OS_SOTS_SOFS11_D_ASIMET.nc"} <= got
    assert {l["rule"] for l in links if l["station_ref"] == "5800450"} == {"alias"}
    # the SAZ47 sediment trap 20-40 km away is a different series, not SOFS
    assert "OS_SOTS_SAZ47-12_PARFLUX-1000m_D.nc" not in got


def test_sofs_alias_rejects_a_neighbouring_deployment_number():
    f = "DATA/SOTS/OS_SOTS_SOFS11_D_ASIMET.nc"
    assert h.names_compatible("SOFS-11", "SOTS", "SOTS", f)
    assert not h.names_compatible("SOFS-12", "SOTS", "SOTS", f)         # 24 km away in reality
    assert not h.names_compatible("SOFS-11", "SOTS", "SOTS", "DATA/SOTS/OS_SOTS_SAZ47-12_PARFLUX-1000m_D.nc")
    assert not h.names_compatible("SOFS-11", "SOTS", "SOTS")           # no file named: SOFS needs one


def test_ke_station_links_keo_and_keok7_platforms(matched):
    by, *_ = matched
    # Real 2800401 (KE019, deployments KE001..KE019): the KEO files in the slice.
    assert "OS_KEO_2018KE016_D_TEMP-10min.nc" in by["2800401"]                # names KE016
    assert "OS_KEO_200406_D_SW_LW_32N145E_2m.nc" in by["2800401"]             # names no deployment
    assert "OS_KEOK7_2004Y1_D_ADCP-1day.nc" in by["2800401"]                  # KEOK7 platform
    assert h.names_compatible("KE003", "KEO", "KEO", "DATA/KEO/OS_KEO_200406_D_SW_LW_32N145E_2m.nc")
    assert h.names_compatible("KE003", "KEOK7", "KEO", "DATA/KEO/OS_KEOK7_2004Y1_D_ADCP-1day.nc")
    assert h.names_compatible("KE015a", "KEO", "KEO", None)
    # a different deployment number, another platform, another directory
    assert not h.names_compatible("KE003", "KEO", "KEO", "DATA/KEO/OS_KEO_2018KE016_D_TEMP-10min.nc")
    assert h.names_compatible("KE016", "KEO", "KEO", "DATA/KEO/OS_KEO_2018KE016_D_TEMP-10min.nc")
    assert not h.names_compatible("KE003", "KEOSED", "KEO", None)
    assert not h.names_compatible("KE003", "PAPA", "PAPA", None)


def test_pa_station_links_papa_files_by_deployment_number(matched):
    by, *_ = matched
    # Real 4800400 (PA018, deployments PA001..PA018) beside real PAPA files.
    assert "OS_PAPA_2017PA011_D_ADCP-1day.nc" in by["4800400"]
    assert "OS_PAPA_2007PA001_D_MET-10min.nc" in by["4800400"]
    assert h.names_compatible("PA011", "PAPA", "PAPA", "DATA/PAPA/OS_PAPA_2017PA011_D_ADCP-1day.nc")
    assert not h.names_compatible("PA010", "PAPA", "PAPA", "DATA/PAPA/OS_PAPA_2017PA011_D_ADCP-1day.nc")


def test_pa_station_far_from_papa_does_not_link(all_rows):
    # Real station 4800400 / PA018, moved 2 degrees north (synthetic position)
    # against the real PAPA files: the alias fixes the name, never the distance.
    st = [{"ref": "4800400", "name": "PA018", "lat": 52.05, "lon": -144.9}]
    links, rejected = h.match_files(st, [], all_rows)
    assert [l for l in links if "PAPA" in l["file"]] == []
    assert rejected == []      # not even "nearby"


def test_alias_names_do_not_swallow_lookalikes():
    for name in ("PAP-1", "PAPA", "KEO017", "KEOSED", "PA", "KE", "SAZ47-12", "FLUXPULSE-1"):
        assert h.name_rule(name, "SOTS", "SOTS", "DATA/SOTS/OS_SOTS_SOFS11_D_ASIMET.nc") != "alias"
