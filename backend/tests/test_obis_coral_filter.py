# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Semantics of the OBIS coral selection, executed against a real DuckDB.

The filter is a SQL string interpolated into a query over remote parquet, so
asserting on its text would prove nothing about what it selects. These tests
build a table with the same shape as the OBIS `interpreted` struct and run the
production predicate over it.

What is being protected: corals must arrive at ANY depth (reef-building
Scleractinia live almost entirely above the 50 m floor), everything else must
still obey the floor, and matching hydrozoan corals by family must not drag in
their overwhelmingly non-coral order.
"""
import duckdb
import pytest

from backend.ingestion.obis_parquet import _IS_CORAL, _WHERE_QUALITY, _sql_str_list

_STRUCT = (
    'STRUCT("decimalLatitude" DOUBLE, "decimalLongitude" DOUBLE, '
    '"minimumDepthInMeters" DOUBLE, "order" VARCHAR, family VARCHAR, '
    '"scientificName" VARCHAR)'
)

CURATED = "Deep curated species"


def _sql_val(v):
    if v is None:
        return "NULL"
    if isinstance(v, str):
        return "'" + v.replace("'", "''") + "'"
    return repr(v)


def _row(name, *, order=None, family=None, depth=None, lat=1.0, lon=2.0,
         dropped=False, absence=False):
    fields = ", ".join([
        f"'decimalLatitude': {_sql_val(lat)}",
        f"'decimalLongitude': {_sql_val(lon)}",
        f"'minimumDepthInMeters': {_sql_val(depth)}",
        f"'order': {_sql_val(order)}",
        f"'family': {_sql_val(family)}",
        f"'scientificName': {_sql_val(name)}",
    ])
    return f"({str(dropped).lower()}, {str(absence).lower()}, CAST({{{fields}}} AS {_STRUCT}))"


def _select(rows: list[str]) -> set[str]:
    """Run the production predicate over the given rows; return surviving names."""
    con = duckdb.connect()
    con.execute(f"CREATE TABLE t (dropped BOOLEAN, absence BOOLEAN, interpreted {_STRUCT})")
    con.execute("INSERT INTO t VALUES " + ", ".join(rows))
    con.execute("CREATE TABLE curated (scientificName VARCHAR)")
    con.execute("INSERT INTO curated VALUES (?)", [CURATED])
    got = con.execute(f"""
        SELECT interpreted."scientificName" FROM t
         WHERE {_WHERE_QUALITY}
           AND (interpreted."scientificName" IN (SELECT scientificName FROM curated)
                OR {_IS_CORAL})
    """).fetchall()
    return {r[0] for r in got}


def test_shallow_coral_is_kept_this_is_the_whole_point():
    """A 5 m reef coral is exactly what the old filter could never reach."""
    assert _select([_row("Acropora palmata", order="Scleractinia",
                         family="Acroporidae", depth=5.0)]) == {"Acropora palmata"}


def test_coral_without_any_recorded_depth_is_kept():
    """~19% of Scleractinia records carry no depth; `NULL >= 50` is NULL, i.e. dropped."""
    assert _select([_row("Porites lobata", order="Scleractinia", depth=None)]) \
        == {"Porites lobata"}


def test_shallow_non_coral_is_still_excluded():
    """The depth floor must keep doing its job for everything that is not a coral."""
    assert _select([_row("Some littoral snail", order="Littorinimorpha", depth=5.0)]) == set()


def test_curated_species_still_obeys_the_depth_floor():
    """Being on the curated list does not exempt a non-coral from the floor."""
    rows = [_row(CURATED, order="Somethingidae", depth=5.0)]
    assert _select(rows) == set()
    rows = [_row(CURATED, order="Somethingidae", depth=500.0)]
    assert _select(rows) == {CURATED}


def test_hydrocoral_matched_by_family_not_order():
    """Stylasteridae/Milleporidae are corals; their order Anthoathecata mostly is not."""
    kept = _select([
        _row("Stylaster roseus", order="Anthoathecata", family="Stylasteridae", depth=10.0),
        _row("Millepora alcicornis", order="Anthoathecata", family="Milleporidae", depth=3.0),
        _row("Some hydroid", order="Anthoathecata", family="Bougainvilliidae", depth=3.0),
    ])
    assert kept == {"Stylaster roseus", "Millepora alcicornis"}


def test_pre_and_post_2022_octocoral_order_names_both_match():
    """WoRMS split Alcyonacea in 2022; OBIS carries records under either name."""
    kept = _select([
        _row("Old naming", order="Alcyonacea", depth=8.0),
        _row("New naming", order="Malacalcyonacea", depth=8.0),
        _row("New naming 2", order="Scleralcyonacea", depth=8.0),
    ])
    assert kept == {"Old naming", "New naming", "New naming 2"}


@pytest.mark.parametrize("kwargs", [
    {"dropped": True},
    {"absence": True},
    {"lat": None},
    {"lon": None},
])
def test_quality_filters_still_apply_to_corals(kwargs):
    """The coral exemption is from the DEPTH floor only, not from quality control."""
    assert _select([_row("Acropora sp.", order="Scleractinia", depth=5.0, **kwargs)]) == set()


def test_sql_str_list_escapes_quotes():
    """Values are our own constants, but an apostrophe must never break the query."""
    assert _sql_str_list(("O'Brien",)) == "'O''Brien'"
    duckdb.connect().execute(f"SELECT 'x' IN ({_sql_str_list(('O\'Brien', 'b'))})")
