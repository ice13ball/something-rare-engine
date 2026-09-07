# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

from domains.geochem_sql import GEOTRACES_HEX_SQL, MEMENTO_HEX_SQL


def test_memento_hexes_aggregate_time():
    """A hex spans 1971-2016. Returning only a count makes a cell holding one
    1971 cast look like a cell holding fifty from 2016."""
    for token in ("jsonb_object_agg", "year_min", "year_max", "n_undated"):
        assert token in MEMENTO_HEX_SQL, f"MEMENTO_HEX_SQL is missing {token}"


def test_geotraces_hexes_aggregate_time():
    for token in ("jsonb_object_agg", "year_min", "year_max", "n_undated"):
        assert token in GEOTRACES_HEX_SQL, f"GEOTRACES_HEX_SQL is missing {token}"


def test_neither_query_leaves_by_decade_unfiltered():
    """FILTER (WHERE decade IS NOT NULL) keeps NULL decades out of the by_decade
    histogram; the executing test (test_hex_hist_sql_exec.py) proves the actual
    JSONB-as-str decoding, since that can only be proven by running the query."""
    for sql in (MEMENTO_HEX_SQL, GEOTRACES_HEX_SQL):
        assert "FILTER (WHERE decade IS NOT NULL)" in sql


def test_by_decade_is_decoded_not_passed_through_raw():
    """asyncpg hands a JSONB column back as `str`. Feed the helper exactly what
    the driver produces and require a dict out the other side.

    This runs the code rather than grepping it, and needs no database — so the
    one trap that has actually shipped here stays covered even on a machine
    where test_hex_hist_sql_exec.py skips for want of TEST_DATABASE_URL.
    """
    from domains.geochem_sql import hex_feature_collection

    row = {
        "gj": '{"type":"Polygon","coordinates":[]}',
        "n": 6, "lat": 60.0, "lon": 10.0,
        "year_min": 1983, "year_max": 1996, "n_undated": 1,
        "by_decade": '{"1980": 3, "1990": 2}',   # a str, as asyncpg returns it
    }
    props = hex_feature_collection([row])["features"][0]["properties"]

    assert props["by_decade"] == {"1980": 3, "1990": 2}
    assert isinstance(props["by_decade"], dict), (
        "by_decade reached the client as a JSON string; Object.entries() throws on it"
    )


def test_a_hex_with_no_dated_points_gets_an_empty_histogram_not_none():
    """jsonb_object_agg(...) FILTER (...) returns SQL NULL when every point in
    the cell is undated. The client iterates by_decade unconditionally, so None
    must become {} here, not reach the browser."""
    from domains.geochem_sql import hex_feature_collection

    row = {
        "gj": '{"type":"Polygon","coordinates":[]}',
        "n": 2, "lat": 60.0, "lon": 20.0,
        "year_min": None, "year_max": None, "n_undated": 2,
        "by_decade": None,
    }
    props = hex_feature_collection([row])["features"][0]["properties"]
    assert props["by_decade"] == {}
