# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""The Davis Strait source (NSF Arctic Data Center): discovery, parsing, matching.

Everything here runs the real code on real data: the real Solr response for the dataset,
trimmed copies of real netCDF files (``fixtures/oceansites_gdac/adc_davis/``, see SOURCE.txt),
and register rows copied from the production database. HTTP is a ``MockTransport``.

⛔ What is protected: a station is never linked on its POSITION (the register has typos that
would drop exactly the wrong rows and keep neighbours), never to a file of another year, and
a fill value is never stored as a measurement.
"""
import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest

from ingestion import oceansites_adc as adc
from ingestion import oceansites_opendap as dap

FIX = Path(__file__).parent / "fixtures" / "oceansites_gdac" / "adc_davis"
LISTING = json.loads((FIX / "solr_listing.json").read_text(encoding="utf-8"))


def _parse(name, **kw):
    m = adc._NAME.match(name)
    return adc.parse_file((FIX / name).read_bytes(), m["mooring"], float(m["depth"]), **kw)


def _file(name, p, key=None):
    """The catalogue row ``match_adc_files`` reads, from a really parsed file."""
    return {"file": key or adc.file_key(name), "platform_code": p.mooring, "start_time": p.start,
            "end_time": p.end, "lat": p.lat, "lon": p.lon}


def _station(ref, name, when, lat=66.659, lon=-61.169):
    return {"ref": ref, "name": name, "deploy_date": when, "lat": lat, "lon": lon}


BI4_2010 = "Davis_MicroCAT_BI4_2010_96m_L2.nc"
BI4_2004 = "Davis_MicroCAT_BI4_2004_151m_L2.nc"
BI4_2015 = "Davis_MicroCAT_BI4_2015_28m_L2.nc"
C4_2013 = "Davis_RCM_velocity_C4_2013_500m_L2.nc"
C1_2015 = "Davis_RCM_velocity_C1_2015_234m_L2.nc"
C6_2013_EMPTY = "Davis_RCM_velocity_C6_2013_250m_L2.nc"


# ── the real listing ─────────────────────────────────────────────────────────

def test_the_real_listing_parses_to_446_netcdf_files_and_only_the_two_instruments_are_read():
    entries = adc.parse_listing(LISTING)
    assert LISTING["response"]["numFound"] == 447 and len(entries) == 446   # 447 = 446 .nc + the EML
    assert all(e["mooring"] and e["year"] and e["instrument"] for e in entries), "every real name parses"
    by = {}
    for e in entries:
        by[e["instrument"]] = by.get(e["instrument"], 0) + 1
    assert by == {"MicroCAT": 261, "ADCP": 100, "RCM": 85}
    read = [e for e in entries if adc.in_scope(e)]
    assert len(read) == 346 and not any(e["instrument"] == "ADCP" for e in read)


def test_keys_are_namespaced_so_they_can_never_equal_a_gdac_path():
    for e in adc.parse_listing(LISTING):
        assert e["key"].startswith("ADC/A2416T169/") and not e["key"].startswith("DATA/")
    rcm = next(e for e in adc.parse_listing(LISTING) if e["file_name"] == C4_2013)
    assert (rcm["mooring"], rcm["year"], rcm["depth"]) == ("C4", 2013, 500.0)   # "velocity" is not the mooring


def test_the_change_marker_is_the_checksum_and_moves_when_it_does():
    e = next(e for e in adc.parse_listing(LISTING) if e["file_name"] == BI4_2010)
    assert adc.change_marker(e) == f"adc:MD5:{e['checksum']}"
    assert adc.change_marker({**e, "checksum": "0" * 32}) != adc.change_marker(e)
    assert adc.change_marker({"date_modified": "2024-01-05T09:54:19Z"}) == "adc:mod:2024-01-05T09:54:19Z"


def _solr_transport(payload, seen=None):
    def handler(request: httpx.Request):
        if seen is not None:
            seen.append(dict(request.url.params))
        start, rows = int(request.url.params["start"]), int(request.url.params["rows"])
        docs = payload["response"]["docs"][start:start + rows]
        return httpx.Response(200, json={"response": {**payload["response"], "start": start, "docs": docs}})
    return httpx.MockTransport(handler)


async def test_the_listing_is_paged_to_the_end_and_asks_for_the_current_versions_of_this_doi(monkeypatch):
    monkeypatch.setattr(adc, "_PAGE", 100)
    seen = []
    async with httpx.AsyncClient(transport=_solr_transport(LISTING, seen)) as c:
        entries = await adc.fetch_listing(c)
    assert len(entries) == 446 and len(seen) == 5            # 447 docs, 100 per page
    assert "doi:10.18739/A2416T169" in seen[0]["q"] and "-obsoletedBy:*" in seen[0]["q"]


@pytest.mark.parametrize("how", ["503", "html", "short", "no_netcdf"])
async def test_a_listing_that_could_not_be_read_is_none_never_an_empty_catalogue(how):
    def handler(request):
        if how == "503":
            return httpx.Response(503)
        if how == "html":
            return httpx.Response(200, text="<html>maintenance</html>")
        docs = LISTING["response"]["docs"]
        if how == "short":     # the server says 447 but delivers 10 and then nothing
            return httpx.Response(200, json={"response": {"numFound": 447, "docs": docs[:10] if request.url.params["start"] == "0" else []}})
        return httpx.Response(200, json={"response": {"numFound": 1, "docs": [d for d in docs if not d["fileName"].endswith(".nc")]}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        assert await adc.fetch_listing(c) is None


async def test_a_dropped_connection_while_listing_is_none():
    def handler(request):
        raise httpx.ConnectError("refused")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        assert await adc.fetch_listing(c) is None


# ── names ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,want", [
    ("DS_BI4", "BI4"), ("DS_BI4\xa0", "BI4"), (" ds_c4 ", "C4"), ("DS_C6a", "C6A"),
    ("DS_WG1.5", "WG15"),                       # the register's WG1.5 is the ADC's WG15
    ("BI4", None),                              # no DS_ prefix: not ours
    ("59N_48W_DSOW3_03", None), ("DSOW3", None), ("", None), (None, None),
])
def test_station_name_to_mooring(name, want):
    assert adc.station_mooring(name) == want


# ── matching: name + date, never position ────────────────────────────────────

@pytest.fixture(scope="module")
def heads():
    return {n: _parse(n) for n in (BI4_2010, BI4_2004, BI4_2015, C4_2013)}


def test_the_exact_case_a_register_row_and_the_file_that_starts_the_same_day(heads):
    # DS_BI4 2010-09-15 <-> file BI4 starting 2010-09-15 13:00 (real register row, real file)
    files = [_file(BI4_2010, heads[BI4_2010])]
    links = adc.match_adc_files([_station("TMP-472585258", "DS_BI4", date(2010, 9, 15))], [], files)
    assert [(l["station_ref"], l["file"], l["rule"]) for l in links] == [
        ("TMP-472585258", "ADC/A2416T169/" + BI4_2010, "adc-name-date")]


def test_a_file_that_spans_two_seasons_covers_the_register_row_of_the_second_one(heads):
    # C4 2013-09-16 .. 2015-09-11: the 2013 row AND a row registered in 2014 are inside it
    p = heads[C4_2013]
    assert (p.start.date(), p.end.date()) == (date(2013, 9, 16), date(2015, 9, 11))
    files = [_file(C4_2013, p)]
    st = [_station("A", "DS_C4", date(2013, 9, 16)), _station("B", "DS_C4", date(2014, 9, 20))]
    assert {l["station_ref"] for l in adc.match_adc_files(st, [], files)} == {"A", "B"}


def test_a_register_row_with_a_typo_in_its_position_still_links_by_name_and_date(heads):
    # the documented typo: the 2007 BI rows carry longitude -66.2 where the site is at -61.2.
    # Real file position here is -61.1689; the row says -66.2 (~220 km away).
    files = [_file(BI4_2010, heads[BI4_2010])]
    st = [_station("T", "DS_BI4", date(2010, 9, 15), lat=66.659, lon=-66.2)]
    links = adc.match_adc_files(st, [], files)
    assert [l["station_ref"] for l in links] == ["T"]
    assert links[0]["distance_km"] > 100, "the distance is recorded, so the typo is visible, but never acted on"


def test_a_file_of_another_year_does_not_match(heads):
    files = [_file(BI4_2010, heads[BI4_2010])]
    for when in (date(2009, 10, 16), date(2007, 10, 17), date(2011, 10, 8), date(2012, 9, 9)):
        assert adc.match_adc_files([_station("X", "DS_BI4", when)], [], files) == [], when


def test_the_three_day_lead_and_the_end_day_are_the_edges_and_are_compared_as_days(heads):
    p = heads[BI4_2010]                      # starts 2010-09-15 13:00, ends 2011-10-07 12:00
    files = [_file(BI4_2010, p)]

    def n(when):
        return len(adc.match_adc_files([_station("X", "DS_BI4", when)], [], files))

    assert n(date(2010, 9, 12)) == 1         # 3 days before the start day: a row registered earlier
    assert n(date(2010, 9, 11)) == 0         # 4 days: no
    assert n(date(2011, 10, 7)) == 1         # the day the file ends (the row is a date, the file a time)
    assert n(date(2011, 10, 8)) == 0


def test_only_the_same_mooring_matches(heads):
    files = [_file(BI4_2010, heads[BI4_2010])]
    for name in ("DS_C4", "DS_BI3", "DS_BI40", "BI4", "59N_48W_DSOW3_03"):
        assert adc.match_adc_files([_station("X", name, date(2010, 9, 15))], [], files) == [], name


def test_a_no_break_space_in_either_name_does_not_stop_the_match(heads):
    p = heads[BI4_2010]
    files = [{**_file(BI4_2010, p), "platform_code": "BI4\xa0"}]
    assert len(adc.match_adc_files([_station("X", "DS_BI4\xa0", date(2010, 9, 15))], [], files)) == 1


def test_a_station_without_a_date_or_a_file_without_coverage_never_links(heads):
    p = heads[BI4_2010]
    assert adc.match_adc_files([_station("X", "DS_BI4", None)], [], [_file(BI4_2010, p)]) == []
    assert adc.match_adc_files([_station("X", "DS_BI4", date(2010, 9, 15))], [],
                               [{**_file(BI4_2010, p), "end_time": None}]) == []


def test_a_deployment_of_the_same_base_ref_can_carry_the_date(heads):
    files = [_file(BI4_2010, heads[BI4_2010])]
    st = [_station("R", "DS_BI4", date(2004, 9, 28))]
    deps = [{"base_ref": "R", "name": "DS_BI4", "deploy_date": date(2010, 9, 15), "lat": None, "lon": None}]
    links = adc.match_adc_files(st, deps, files)
    assert [l["station_ref"] for l in links] == ["R"]
    assert links[0]["distance_km"] == -1.0           # that deployment has no position: nothing to report


def test_one_link_per_station_and_file_even_when_two_dates_fit(heads):
    files = [_file(C4_2013, heads[C4_2013])]
    st = [_station("A", "DS_C4", date(2013, 9, 16))]
    deps = [{"base_ref": "A", "name": "DS_C4", "deploy_date": date(2014, 9, 20), "lat": 67.0, "lon": -57.7}]
    assert len(adc.match_adc_files(st, deps, files)) == 1


# ── parsing the real files ───────────────────────────────────────────────────

def test_a_clean_microcat_gives_strided_real_samples_with_the_files_own_units_and_depth():
    p = _parse(BI4_2010)
    assert (p.mooring, p.start, p.end) == ("BI4", datetime(2010, 9, 15, 13, tzinfo=timezone.utc),
                                           datetime(2011, 10, 7, 12, tzinfo=timezone.utc))
    assert p.parameters == ["sea_water_practical_salinity", "sea_water_temperature"]
    by = {r.variable: r for r in p.series}
    t = by["sea_water_temperature"]
    assert (t.units, t.depth_m, t.n_total, t.stride, len(t.vals)) == ("degree_C", 96.0, 300, 2, 150)
    assert by["sea_water_practical_salinity"].units == "1"           # passed through, not renamed
    assert t.standard_name == "sea_water_temperature" and t.long_name == "temperature"
    assert t.first_time == t.times[0] == datetime(2010, 9, 15, 13, tzinfo=timezone.utc)
    assert (p.min_depth, p.max_depth) == (96.0, 96.0) and (p.lat, p.lon) == (66.659423, -61.1689)


def test_the_stored_numbers_are_the_files_numbers_every_second_one_not_averages():
    import netCDF4
    ds = netCDF4.Dataset(FIX / BI4_2010)
    ds.set_auto_maskandscale(False)
    raw = ds["sea_water_temperature"][:].tolist()
    ds.close()
    t = next(r for r in _parse(BI4_2010).series if r.variable == "sea_water_temperature")
    assert t.vals == [raw[i] for i in range(0, 300, 2)]


def test_fill_values_are_null_never_data_and_the_flag_beside_each_is_kept():
    p = _parse(C4_2013)
    e = next(r for r in p.series if r.variable == "eastward_sea_water_velocity")
    # the real file: valid for the first 31 samples, then 1e+35 with flag 9 (missing)
    assert e.vals[:15] == [v for v in e.vals[:15] if v is not None] and None in e.vals
    assert all(v is None or abs(v) < 1e3 for v in e.vals), "1e+35 must never reach the store"
    assert sum(v is None for v in e.vals) == 27 and p.fills_nulled == 54       # both velocities
    for v, q in zip(e.vals, e.qc):
        assert (v is None) == (q == 9), "a sample is missing exactly where the file flags it missing"
    assert e.units == "m s-1" and e.depth_m == 500.0


def test_the_one_velocity_flag_variable_grades_both_velocities():
    # RCM files carry a single `velocity_QC`; there is no `eastward_sea_water_velocity_QC`
    p = _parse(C1_2015)
    by = {r.variable: r for r in p.series}
    assert set(by) == {"eastward_sea_water_velocity", "northward_sea_water_velocity"}
    assert by["eastward_sea_water_velocity"].qc == by["northward_sea_water_velocity"].qc
    assert {1, 4, 9} <= set(by["eastward_sea_water_velocity"].qc)      # real good, bad and missing flags


def test_a_variable_with_no_real_sample_stores_nothing():
    p = _parse(C6_2013_EMPTY)      # real file: every velocity is 1e+35, flag 9
    assert p.series == [] and p.fills_nulled > 0


def test_the_2004_file_with_a_numeric_mooring_id_is_placed_by_its_name_and_source_attribute():
    # mooring_number = 1535, station = 1535 (real): neither says BI4; the ADC name and the
    # `source` attribute (..._BI4_3308_1800.nc) do
    p = _parse(BI4_2004)
    assert p.mooring == "BI4" and (p.start.date(), p.end.date()) == (date(2004, 9, 28), date(2005, 9, 8))


def test_the_2015_layout_has_no_mooring_number_and_an_epoch_coverage_attribute():
    p = _parse(BI4_2015)     # platform_id = BI4.30; time_coverage_start is a number
    assert p.mooring == "BI4"
    assert p.start == min(p.series[0].times) and p.start.year == 2015   # the time axis, not the attribute
    assert p.series[0].depth_m == 28.0, "no sensor_depth anywhere: the depth of the ADC name"
    assert (p.lat, p.lon) == (66.6588, pytest.approx(-61.169216666666664))


def test_a_file_that_says_a_different_mooring_than_its_name_is_refused():
    raw = (FIX / BI4_2010).read_bytes()
    with pytest.raises(adc.MooringMismatch):
        adc.parse_file(raw, "C4", 96.0)               # mooring_number = BI4 contradicts the name C4
    with pytest.raises(adc.MooringMismatch):
        adc.parse_file((FIX / BI4_2004).read_bytes(), "C4", 151.0)   # nothing in it names C4 either
    with pytest.raises(adc.MooringMismatch):
        adc.parse_file((FIX / BI4_2015).read_bytes(), "WG1", 28.0)   # platform_id BI4.30 contradicts


def test_bytes_that_are_not_a_netcdf_are_unsupported_not_a_crash():
    with pytest.raises(dap.UnsupportedFile):
        adc.parse_file(b"<html>503</html>", "BI4", 96.0)


def test_the_depth_prefers_the_variable_then_instrument_depth_then_the_name():
    assert adc._depth_of({"sensor_depth": "96.0"}, {"instrument_depth": 5.0}, 7.0) == 96.0
    assert adc._depth_of({}, {"instrument_depth": [195.0], "geospatial_vertical_min": [202.0],
                              "geospatial_vertical_max": [202.0], "geospatial_vertical_units": "metres"}, 7.0) == 195.0
    assert adc._depth_of({}, {"geospatial_vertical_min": [23.9], "geospatial_vertical_max": [58.9],
                              "geospatial_vertical_units": "dbar"}, 28.0) == 28.0   # a pressure RANGE is no depth
    assert adc._depth_of({}, {}, None) is None
