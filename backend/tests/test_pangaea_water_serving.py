# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""What leaves the API. Every stored column is in exactly one of SERVED / HIDDEN;
pi_email is stored and never served; units are the source's header strings."""
import json

import pytest
from fastapi import HTTPException

from domains import pangaea_water as pw
from ingestion import coastdom, greenland_pp
from pangaea_water_helpers import (  # noqa: F401  (conn is a fixture)
    PP_TSV, coastdom_jsonld, coastdom_tsv, conn, fake_fetch, needs_db, pp_jsonld,
)

STRUCTURAL = ("version_id", "row_no", "raw", "geom")


@pytest.mark.parametrize("fields, served, hidden", [
    (coastdom.FIELDS, pw.COASTDOM_SERVED_FIELDS, pw.COASTDOM_HIDDEN_FIELDS),
    (greenland_pp.FIELDS, pw.GREENLAND_PP_SERVED_FIELDS, pw.GREENLAND_PP_HIDDEN_FIELDS),
], ids=["coastdom", "greenland-pp"])
def test_every_stored_column_is_in_exactly_one_list(fields, served, hidden):
    stored = set(STRUCTURAL) | set(fields)
    assert len(served) == len(set(served)), "duplicate in SERVED"
    assert not set(served) & set(hidden), f"in both lists: {set(served) & set(hidden)}"
    assert set(served) | set(hidden) == stored, (
        f"in neither list: {stored - set(served) - set(hidden)}; "
        f"not stored at all: {(set(served) | set(hidden)) - stored}")
    assert all(isinstance(r, str) and r.strip() for r in hidden.values()), "every hidden field needs its reason"


def test_pi_email_is_a_hidden_field():
    assert "pi_email" in pw.COASTDOM_HIDDEN_FIELDS
    assert "pi_email" not in pw.COASTDOM_SERVED_FIELDS
    assert "raw" in pw.COASTDOM_HIDDEN_FIELDS           # raw carries the pi_email cell


@pytest.fixture
async def seeded(conn, monkeypatch):
    monkeypatch.setattr(pw, "_fetch_bytes", fake_fetch({
        coastdom.TEXTFILE_URL: coastdom_tsv(), coastdom.JSONLD_URL: coastdom_jsonld(),
        greenland_pp.TEXTFILE_URL: PP_TSV, greenland_pp.JSONLD_URL: pp_jsonld(),
    }))
    await pw.sync_coastdom()
    await pw.sync_greenland_pp()
    pw.clear_caches()
    yield conn
    pw.clear_caches()


@needs_db
async def test_stored_columns_in_the_database_match_the_lists(seeded):
    for table, served, hidden in (("coastdom_samples", pw.COASTDOM_SERVED_FIELDS, pw.COASTDOM_HIDDEN_FIELDS),
                                  ("greenland_pp_stations", pw.GREENLAND_PP_SERVED_FIELDS, pw.GREENLAND_PP_HIDDEN_FIELDS)):
        cols = {r["column_name"] for r in await seeded.fetch(
            "SELECT column_name FROM information_schema.columns WHERE table_name = $1", table)}
        assert cols == set(served) | set(hidden), table


@needs_db
async def test_locations_count_every_mappable_sample(seeded):
    fc = json.loads((await pw.coastdom_locations()).body)
    feats = fc["features"]
    assert len(feats) == 9
    assert sum(f["properties"]["n_samples"] for f in feats) == 10
    [jiulong] = [f for f in feats if f["properties"]["site_id"] == "24.393,117.929"]
    p = jiulong["properties"]
    assert (p["n_samples"], p["depth_min_m"], p["depth_max_m"]) == (2, 1.0, 4.0)
    assert (p["date_min"], p["date_max"], p["location"]) == ("2011-08-14", "2011-08-14", "Jiulong estuary")
    assert jiulong["geometry"] == {"type": "Point", "coordinates": [117.929, 24.393]}


@needs_db
async def test_locations_year_counts_partition_the_samples(seeded):
    """year_counts holds DATED samples by calendar year (string keys); undated rows
    are only in n_undated, so the two always add up to n_samples."""
    feats = json.loads((await pw.coastdom_locations()).body)["features"]
    for f in feats:
        p = f["properties"]
        yc = p["year_counts"]
        assert isinstance(yc, dict)
        assert all(k.isdigit() and len(k) == 4 and isinstance(v, int) and v > 0 for k, v in yc.items())
        assert sum(yc.values()) + p["n_undated"] == p["n_samples"]
    [jiulong] = [f for f in feats if f["properties"]["site_id"] == "24.393,117.929"]
    assert jiulong["properties"]["year_counts"] == {"2011": 2}


@needs_db
async def test_year_counts_split_years_and_keep_undated_out(seeded):
    await seeded.execute(
        """UPDATE coastdom_samples SET sample_date = DATE '2015-03-01'
             WHERE lat = 24.393 AND lon = 117.929 AND depth_m = 4.0""")
    await seeded.execute(
        """UPDATE coastdom_samples SET lat = 24.393, lon = 117.929, sample_date = NULL,
               geom = ST_SetSRID(ST_MakePoint(117.929, 24.393), 4326) WHERE row_no = 2""")
    pw.clear_caches()
    feats = json.loads((await pw.coastdom_locations()).body)["features"]
    [f] = [x for x in feats if x["properties"]["site_id"] == "24.393,117.929"]
    p = f["properties"]
    assert p["year_counts"] == {"2011": 1, "2015": 1}
    assert p["n_undated"] == 1 and p["n_samples"] == 3


@needs_db
async def test_two_depths_come_back_as_two_samples_in_depth_order(seeded):
    body = await pw.coastdom_samples(lat=24.393, lon=117.929)
    assert body["n_samples"] == 2
    assert [s["depth_m"] for s in body["samples"]] == [1.0, 4.0]
    assert [s["doc_umol_l"] for s in body["samples"]] == [171.0, 195.0]
    assert set(body["samples"][0]) == set(pw.COASTDOM_SERVED_FIELDS)


@needs_db
async def test_pi_email_is_stored_but_never_served(seeded):
    assert await seeded.fetchval("SELECT pi_email FROM coastdom_samples WHERE row_no = 1") == "pi1@example.org"
    samples = await pw.coastdom_samples(lat=26.145, lon=119.109)
    locations = (await pw.coastdom_locations()).body.decode()
    meta = await pw.pangaea_water_meta()
    for payload in (json.dumps(samples), locations, json.dumps(meta, default=str)):
        assert "pi1@example.org" not in payload
        assert "pi_email" not in payload


@needs_db
async def test_one_position_with_two_names_is_one_feature(seeded):
    await seeded.execute(
        """UPDATE coastdom_samples SET lat = 26.145, lon = 119.109, location = 'Second name',
               geom = ST_SetSRID(ST_MakePoint(119.109, 26.145), 4326) WHERE row_no = 2""")
    pw.clear_caches()
    feats = json.loads((await pw.coastdom_locations()).body)["features"]
    [f] = [x for x in feats if x["properties"]["site_id"] == "26.145,119.109"]
    assert f["properties"]["n_samples"] == 2
    assert f["properties"]["location"] == "Minjiang estuary / Second name"


@needs_db
async def test_a_position_only_in_an_old_version_is_404(seeded, monkeypatch):
    moved = coastdom_tsv().replace(b"26.145000\t119.109000", b"26.145001\t119.109000", 1)
    monkeypatch.setattr(pw, "_fetch_bytes", fake_fetch({
        coastdom.TEXTFILE_URL: moved, coastdom.JSONLD_URL: coastdom_jsonld("2024-06-01")}))
    assert await pw.sync_coastdom() == 12
    assert await seeded.fetchval("SELECT count(*) FROM coastdom_samples WHERE lat = 26.145") == 1  # old row kept
    with pytest.raises(HTTPException) as exc:
        await pw.coastdom_samples(lat=26.145, lon=119.109)
    assert exc.value.status_code == 404


@needs_db
async def test_meta_serves_counts_citation_and_exact_units(seeded):
    meta = await pw.pangaea_water_meta()
    cur = {v["layer_id"]: v for v in meta["versions"] if v["is_current"]}
    c, g = cur["coastdom"], cur["greenland-primary-production"]
    assert (c["rows_in_source"], c["rows_unmappable"], c["data_points"]) == (12, 2, 207)
    assert c["date_published"] == "2023-12-12"
    assert c["citation"].endswith("https://doi.org/10.1594/PANGAEA.964012")
    assert c["units"]["doc_umol_l"] == "DOC [µmol/l]"
    assert c["units"]["dic_umol_kg"] == "DIC [µmol/kg]"
    assert c["units"]["depth_m"] == "Depth water [m]"
    assert "pi_email" not in c["units"]
    assert g["units"]["gpp_c_mg_m2_day"] == "GPP C [mg/m**2/day]"


@needs_db
async def test_greenland_stations_serve_all_twelve(seeded):
    fc = json.loads((await pw.greenland_pp_stations()).body)
    assert len(fc["features"]) == 12
    first = min(fc["features"], key=lambda f: f["properties"]["row_no"])["properties"]
    assert (first["event"], first["sample_date"], first["gpp_c_mg_m2_day"]) == ("FS21_06E", "2021-08-02", 2234.38)
    assert set(first) == set(pw.GREENLAND_PP_SERVED_FIELDS)
