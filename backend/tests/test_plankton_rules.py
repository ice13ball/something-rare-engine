# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Pure rules of the OBIS plankton import — DuckDB over the real-OBIS fixture, no Postgres."""
import datetime as dt
import pathlib

import duckdb
import pytest

from ingestion import plankton_obis as p

FIXDIR = pathlib.Path(__file__).parent / "fixtures" / "plankton_obis"
FIX = FIXDIR / "occurrences.parquet"
CPR = "5c4667b8-8d93-4768-bc7e-3c31cde1cf18"
AUSMICRO = "b508f7bc-8708-43d5-b940-e44f2765d1af"
NC_DUP = "10134dbd-457e-4a97-9a89-b4e9f81482ca"


@pytest.mark.parametrize("text,expected", [
    ("This work is licensed under a  Creative Commons Attribution (CC-BY) 4.0 License", "cc-by"),
    ("To the extent possible under law, the publisher has waived all rights to these data and has "
     "dedicated them to the  Public Domain (CC0 1.0)", "cc0"),
    ("http://creativecommons.org/licenses/by/4.0/legalcode", "cc-by"),
    ("CC-BY-NC 4.0", "cc-by-nc"),
    ("Creative Commons Attribution Non Commercial (CC-BY-NC) 4.0", "cc-by-nc"),
    ("Public Domain (CC0 1.0)", "cc0"),
    ("CC-BY-SA 4.0", "cc-by-sa"),
    ("restricted", "restricted"),
    ("Restricted", "restricted"),
    ("unrestricted", "unknown"),
    ("Unrestricted", "unknown"),
    ("Unknown", "unknown"),
    ("CC-BY NC 4.0", "cc-by-nc"),
    ("cc-by_nc", "cc-by-nc"),
    ("Creative Commons Attribution NC", "cc-by-nc"),
    ("https://creativecommons.org/licenses/by-nc/4.0/legalcode", "cc-by-nc"),
    ("https://creativecommons.org/licenses/by/4.0/", "cc-by"),
    ("CC-BY-NC-SA 4.0", "cc-by-nc"),
    ("CC BY 4.0", "cc-by"),
    ("CC BY SA 4.0", "cc-by-sa"),
    ("Creative Commons Zero", "cc0"),
    ("CC0 1.0", "cc0"),
    ("Public Domain Dedication (CC0)", "cc0"),
    ("Public Domain", "unknown"),
    ("CC-BY-ND 4.0", "unknown"),
    ("Creative Commons Attribution No Derivatives", "unknown"),
    ("CC BY noderivs", "unknown"),
    ("CC-BY-NC-ND 4.0", "cc-by-nc"),
    ("Restricted - contact owner", "restricted"),
    ("Unrestricted - open", "unknown"),
    ("", "unknown"),
    (None, "unknown"),
])
def test_normalise_licence(text, expected):
    assert p.normalise_licence(text) == expected


def test_fixture_dataset_licences_normalise_to_open_classes():
    import json
    meta = json.loads((FIXDIR / "datasets.json").read_text())
    items = meta if isinstance(meta, list) else list(meta.values())
    seen = {}
    for d in items:
        d = d.get("results", [d])[0] if "results" in d else d
        seen[d["id"]] = p.normalise_licence(d.get("intellectualrights"))
    assert seen[CPR] == "cc-by" and seen[AUSMICRO] == "cc0"
    assert set(seen.values()) <= {"cc-by", "cc0"}


@pytest.mark.parametrize("depth,dmin,dmax,expected", [
    (10.0, None, None, 10.0),
    (None, 0.0, 200.0, 100.0),
    (None, 50.0, None, 50.0),
    (None, None, 80.0, 80.0),
    (None, None, None, None),
    (-5.0, None, None, None),
    (12000.0, None, None, None),
    (11000.0, None, None, 11000.0),
    (0.0, None, None, 0.0),
    ("deep", None, None, None),
    (None, "x", "y", None),
    (None, "x", None, None),
])
def test_parse_depth(depth, dmin, dmax, expected):
    assert p.parse_depth(depth, dmin, dmax) == expected


@pytest.mark.parametrize("value,expected", [
    ("07", 7), (7, 7), ("13", None), (13, None), (0, None), ("", None), (None, None), ("x", None)])
def test_parse_month(value, expected):
    assert p.parse_month(value) == expected


@pytest.mark.parametrize("value,expected", [
    ("2003-05-17", dt.date(2003, 5, 17)),
    ("2003-05-17T10:00:00Z", dt.date(2003, 5, 17)),
    ("2016-11-07 19:30:00+00", dt.date(2016, 11, 7)),
    ("2003-05/2003-06", None),
    ("2003-02-30", None),
    ("", None), (None, None), ("garbage", None),
])
def test_parse_event_date(value, expected):
    assert p.parse_event_date(value) == expected


def _classify(where_extra: str = "") -> list[tuple]:
    return duckdb.sql(
        f"SELECT {p.GROUP_SQL} AS g, {p.KEEP_SQL} AS keep, interpreted.\"order\" AS ord, "
        f"interpreted.genus AS genus, absence, dropped FROM read_parquet('{FIX}') {where_extra}").fetchall()


def _synthetic(**kw) -> tuple:
    """One in-memory row in the raw layout; returns (group, keep, is_edna)."""
    row = dict(dataset_id="x", lat=10.0, lon=10.0, klass="NULL", subclass="NULL", order="NULL",
               genus="NULL", flags="[]::VARCHAR[]", absence="false", dropped="false", dna="[]")
    row.update(kw)
    def q(v):
        return v if v == "NULL" or str(v).startswith(("[", "false", "true")) else "'" + v + "'"
    duckdb.sql(f"""CREATE OR REPLACE TABLE t AS SELECT '{row['dataset_id']}' AS dataset_id,
      {{'decimalLatitude': {row['lat']}::DOUBLE, 'decimalLongitude': {row['lon']}::DOUBLE,
        'class': {q(row['klass'])}::VARCHAR, 'subclass': {q(row['subclass'])}::VARCHAR,
        'order': {q(row['order'])}::VARCHAR, 'genus': {q(row['genus'])}::VARCHAR,
        'phylum': NULL::VARCHAR, 'division': NULL::VARCHAR, 'subphylum': NULL::VARCHAR,
        'infraphylum': NULL::VARCHAR}} AS interpreted,
      {row['flags']} AS flags, {row['absence']} AS absence, {row['dropped']} AS dropped,
      {{'http://rs.gbif.org/terms/1.0/DNADerivedData': {row['dna']}::INTEGER[]}} AS extensions""")
    return duckdb.sql(f"SELECT {p.GROUP_SQL}, {p.KEEP_SQL}, {p.EDNA_SQL} FROM t").fetchone()


def test_absence_and_dropped_rows_are_never_kept():
    rows = _classify("WHERE absence OR dropped")
    assert rows, "fixture must contain absence/dropped rows"
    assert all(keep is False for _, keep, *_ in rows)


def test_non_copepod_absence_row_is_not_kept():
    assert _synthetic(klass="Bacillariophyceae", absence="true")[1] is False
    assert _synthetic(klass="Bacillariophyceae", dropped="true")[1] is False


def test_excluded_copepod_orders_are_dropped_except_planktonic_genera():
    rows = _classify("WHERE interpreted.\"order\" = 'Harpacticoida' "
                     "AND NOT coalesce(absence,false) AND NOT coalesce(dropped,false) "
                     "AND NOT list_contains(flags,'ON_LAND')")
    assert rows, "fixture must contain Harpacticoida rows"
    for g, keep, ord_, genus, *_ in rows:
        assert g == "copepoda"
        assert keep is (genus in p.PLANKTONIC_HARPACTICOID_GENERA)


@pytest.mark.parametrize("order", ["Harpacticoida", "Siphonostomatoida", "Monstrilloida"])
@pytest.mark.parametrize("genus,kept", [("Microsetella", True), ("Clytemnestra", True), ("Aegisthus", True),
                                        ("Tigriopus", False)])
def test_copepod_order_exclusion_with_genus_exception(order, genus, kept):
    assert _synthetic(klass="Copepoda", order=order, genus=genus)[1] is kept


def test_null_order_copepods_are_kept():
    rows = _classify("WHERE interpreted.\"order\" IS NULL AND interpreted.\"class\" = 'Copepoda' "
                     "AND NOT coalesce(absence,false) AND NOT coalesce(dropped,false) "
                     "AND NOT list_contains(flags,'ON_LAND')")
    assert rows, "fixture has NULL-order copepods"
    assert all(g == "copepoda" and keep is True for g, keep, *_ in rows)


def test_non_calcifying_haptophytes_are_not_coccolithophores():
    rows = _classify("WHERE interpreted.\"order\" IN ('Prymnesiales','Phaeocystales')")
    assert rows, "fixture must contain Prymnesiales rows"
    assert all(g is None for g, *_ in rows)


@pytest.mark.parametrize("group", p.GROUPS)
def test_each_group_has_kept_fixture_rows(group):
    kept = [r for r in _classify() if r[1] and r[0] == group]
    assert kept, f"no kept fixture row for {group}"


def test_group_labels_are_correct_on_fixture():
    sql = (f"SELECT {p.GROUP_SQL} g, interpreted.\"class\", interpreted.\"order\", interpreted.phylum, "
           f"interpreted.division, interpreted.subphylum, interpreted.infraphylum "
           f"FROM read_parquet('{FIX}') WHERE {p.KEEP_SQL}")
    for g, klass, order, phylum, div, subphylum, infra in duckdb.sql(sql).fetchall():
        if g == "copepoda":
            assert klass == "Copepoda"
        elif g == "euphausiacea":
            assert order == "Euphausiacea"
        elif g == "diatoms":
            assert "Bacillariophyta" in (phylum, div) or klass in (
                "Bacillariophyceae", "Coscinodiscophyceae", "Mediophyceae")
        elif g == "coccolithophores":
            assert klass in ("Coccolithophyceae", "Prymnesiophyceae")
            assert order not in ("Prymnesiales", "Phaeocystales")
        elif g == "dinoflagellates":
            assert klass == "Dinophyceae" or "Dinoflagellata" in (phylum, div, subphylum, infra)


def test_copepoda_ranked_as_subclass_maps_to_copepoda():
    g, keep, _ = _synthetic(subclass="Copepoda")
    assert g == "copepoda" and keep is True


def test_coordinates_are_filtered():
    assert _synthetic(klass="Copepoda", lat=0.0, lon=0.0)[1] is False
    assert _synthetic(klass="Copepoda", lat=0.0, lon=5.0)[1] is True
    assert _synthetic(klass="Copepoda", lat=91.0, lon=5.0)[1] is False
    assert _synthetic(klass="Copepoda", lat=5.0, lon=181.0)[1] is False
    assert _synthetic(klass="Copepoda", lat="NULL", lon=5.0)[1] is False


def test_on_land_rows_are_dropped():
    assert p.LAND_FLAG == "ON_LAND"
    rows = duckdb.sql(f"SELECT {p.KEEP_SQL} FROM read_parquet('{FIX}') "
                      f"WHERE list_contains(flags, 'ON_LAND')").fetchall()
    assert len(rows) == 31 and all(k is False for (k,) in rows)
    assert _synthetic(klass="Copepoda", flags="['ON_LAND']::VARCHAR[]")[1] is False
    assert _synthetic(klass="Copepoda", flags="['NO_DEPTH']::VARCHAR[]")[1] is True


def test_excluded_dataset_is_dropped_whole():
    assert NC_DUP in p.EXCLUDED_DATASETS
    assert _synthetic(klass="Copepoda", dataset_id=NC_DUP)[1] is False
    assert _synthetic(klass="Copepoda", dataset_id=CPR)[1] is True


def test_edna_uses_non_empty_dna_extension_not_null_check():
    rows = duckdb.sql(f"SELECT dataset_id, {p.EDNA_SQL} FROM read_parquet('{FIX}')").fetchall()
    cpr = [e for d, e in rows if d == CPR]
    aus = [e for d, e in rows if d == AUSMICRO]
    assert cpr and all(e is False for e in cpr)
    assert aus and all(e is True for e in aus)
    assert _synthetic(klass="Copepoda", dna="[]")[2] is False
    assert _synthetic(klass="Copepoda", dna="[1]")[2] is True


def test_edna_falls_back_to_title_when_extensions_column_missing():
    assert p.edna_sql(["dataset_id"], "title") != p.EDNA_SQL
    assert p.edna_sql(["extensions"]) == p.EDNA_SQL
    q = p.edna_sql(["dataset_id"], "title")
    assert duckdb.sql(f"SELECT {q} FROM (SELECT 'Australian Microbiome 18S' AS title)").fetchone()[0] is True
    assert duckdb.sql(f"SELECT {q} FROM (SELECT 'The CPR Survey' AS title)").fetchone()[0] is False
