# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""GET /v1/plankton/site/{site_key} — the click panel of one place (real PostGIS)."""
import pytest
from decimal import Decimal

from ingestion import plankton_obis as p
from plankton_helpers import DS_NC, DS_T, api_get as _get, conn, needs_db, row, seed_live  # noqa: F401

K1 = "10.200000,50.200000"


def _rows():
    return ([row("copepoda", 10.2, 50.2, year=1995, depth=50.0, name="Calanus finmarchicus")] * 3
            + [row("diatoms", 10.2, 50.2, year=2015, depth=None, name="Chaetoceros", ds=DS_NC,
                   licence="cc-by-nc")] * 2
            + [row("dinoflagellates", 10.2, 50.2, year=None, depth=1500.0, edna=True)]
            + [row("copepoda", 10.7, 50.2, year=2012, depth=50.0, name="Calanus helgolandicus")])


@needs_db
async def test_the_panel_counts_exactly_the_observations_of_the_place(conn):
    await seed_live(conn, _rows())
    body = (await _get(f"/v1/plankton/site/{K1}")).json()
    facet_total = await conn.fetchval(
        "SELECT sum(f.n) FROM plankton_site_facets f JOIN plankton_sites s USING (site_id) WHERE s.site_key = $1", K1)
    assert body["total"] == facet_total == 6
    assert (body["site_key"], body["lon"], body["lat"]) == (K1, 10.2, 50.2)
    assert body["groups"] == [{"taxon_group": "copepoda", "n": 3}, {"taxon_group": "diatoms", "n": 2},
                              {"taxon_group": "dinoflagellates", "n": 1}]
    assert body["top_species"] == [
        {"scientific_name": "Calanus finmarchicus", "taxon_group": "copepoda", "n": 3},
        {"scientific_name": "Chaetoceros", "taxon_group": "diatoms", "n": 2}]
    assert body["years"] == {"min": 1995, "max": 2015, "undated": 1}
    assert body["depth"] == {"min_m": 50.0, "max_m": 1500.0, "no_depth": 2}
    assert body["edna"] == {"n": 1, "share": round(1 / 6, 4)}


@needs_db
async def test_every_licence_is_shown_with_its_datasets(conn):
    await seed_live(conn, _rows())
    body = (await _get(f"/v1/plankton/site/{K1}")).json()
    assert body["licences"] == [{"licence": "cc-by", "n": 4}, {"licence": "cc-by-nc", "n": 2}]
    nc = next(d for d in body["datasets"] if d["licence"] == "cc-by-nc")
    assert nc == {"dataset_id": DS_NC, "title": "Synthetic CC-BY-NC dataset", "citation": "Synthetic citation B",
                  "url": "https://example.org/b", "licence": "cc-by-nc", "n": 2,
                  "obis_url": f"https://obis.org/dataset/{DS_NC}"}
    assert body["datasets_total"] == 2


@needs_db
async def test_the_panel_honours_the_active_filters(conn):
    await seed_live(conn, _rows())
    body = (await _get(f"/v1/plankton/site/{K1}?g=copepoda&d=2010")).json()
    assert body["total"] == 0 and body["groups"] == [] and body["datasets"] == [] and body["datasets_total"] == 0
    body = (await _get(f"/v1/plankton/site/{K1}?d=-1")).json()
    assert body["total"] == 1 and body["groups"] == [{"taxon_group": "dinoflagellates", "n": 1}]
    body = (await _get(f"/v1/plankton/site/{K1}?b=3&e=0")).json()
    assert body["total"] == 2 and body["groups"] == [{"taxon_group": "diatoms", "n": 2}]


@needs_db
@pytest.mark.parametrize("path,status", [
    ("/v1/plankton/site/11.000000,51.000000", 404),
    ("/v1/plankton/site/10.2,50.2", 400),
    ("/v1/plankton/site/10.200000;50.200000", 400),
    (f"/v1/plankton/site/{K1}?g=jellyfish", 400),
])
async def test_unknown_and_malformed_requests(conn, path, status):
    await seed_live(conn, _rows())
    assert (await _get(path)).status_code == status


@needs_db
async def test_a_site_key_link_survives_a_reimport_that_renumbers_the_places(conn):
    await seed_live(conn, _rows())
    before = await conn.fetchval("SELECT site_id FROM plankton_sites WHERE site_key = $1", K1)
    await conn.execute("INSERT INTO plankton_occurrences (taxon_group, dataset_id, licence, is_edna, lon, lat) "
                       "VALUES ('copepoda', $1::uuid, 'cc-by', false, -50.0, 10.0)", DS_T)
    await p.rebuild_aggregates_from_live(conn, backoff=())
    after = await conn.fetchval("SELECT site_id FROM plankton_sites WHERE site_key = $1", K1)
    assert after != before                                                  # the internal id moved…
    assert (await _get(f"/v1/plankton/site/{K1}")).json()["total"] == 6     # …the link did not


@needs_db
@pytest.mark.parametrize("key", [
    "%2e%2e", "..%5C..%5Cetc", "10.200000,50.200000%27%20OR%201=1--", "10.200000,50.200000,1",
    "10.200000, 50.200000", "1" * 400 + ".000000,50.200000", "%D9%A1%D9%A0.200000,50.200000", "NaN,NaN", "-,-",
])
async def test_a_malformed_site_key_is_a_400_never_a_500(conn, key):
    await seed_live(conn, _rows())
    assert (await _get(f"/v1/plankton/site/{key}")).status_code == 400


@needs_db
async def test_before_the_first_build_the_panel_is_a_503_not_a_404(conn):
    from plankton_helpers import reset_plankton
    await reset_plankton(conn)
    await conn.execute("DELETE FROM plankton_tile_version")
    await conn.execute("INSERT INTO plankton_sites (site_id, site_key, lon, lat, geom, geom_3857) VALUES "
                       "(1, $1, 10.2, 50.2, ST_SetSRID(ST_MakePoint(10.2, 50.2), 4326), "
                       "ST_Transform(ST_SetSRID(ST_MakePoint(10.2, 50.2), 4326), 3857))", K1)
    r = await _get(f"/v1/plankton/site/{K1}")
    assert r.status_code == 503 and r.headers["retry-after"] == "300"


@needs_db
async def test_the_site_query_uses_the_geometry_index_and_the_timeout_is_set(conn):
    from domains import plankton as pl
    await seed_live(conn, _rows())
    where = pl._site_where(2026)
    await conn.execute("SET LOCAL enable_seqscan = off")
    plan = "\n".join(r[0] for r in await conn.fetch(
        f"EXPLAIN SELECT 1 FROM plankton_occurrences o WHERE {where}", 10.2, 50.2, Decimal("10.200000"), Decimal("50.200000"), ["copepoda"], [-1, 1990], [0, 3], True))
    assert "plankton_occurrences_geom_gix" in plan
    assert pl.SITE_STATEMENT_TIMEOUT == "10s"


@needs_db
async def test_a_slow_site_query_is_a_503_with_a_short_retry(conn, monkeypatch):
    from domains import plankton as pl
    await seed_live(conn, _rows())
    monkeypatch.setattr(pl, "SITE_STATEMENT_TIMEOUT", "1ms")
    monkeypatch.setattr(pl, "_site_where", lambda c: (
        "pg_sleep(0.2) IS NOT NULL AND $1::float8 IS NOT NULL AND $2::float8 IS NOT NULL AND $3::numeric IS NOT NULL "
        "AND $4::numeric IS NOT NULL AND $5::text[] IS NOT NULL AND $6::smallint[] IS NOT NULL "
        "AND $7::smallint[] IS NOT NULL AND $8::boolean IS NOT NULL"))
    r = await _get(f"/v1/plankton/site/{K1}")
    assert r.status_code == 503 and r.headers["retry-after"] == "5"


@needs_db
async def test_a_slash_in_the_site_key_never_reaches_the_query(conn):
    await seed_live(conn, _rows())
    assert (await _get("/v1/plankton/site/..%2F..%2Fetc%2Fpasswd")).status_code in (400, 404)   # router-level, never 500


class _RecordingPool:
    """db.pool stand-in around the test connection that records every statement the endpoint runs, in order."""
    def __init__(self, conn, raise_on=None, exc=None):
        self.conn, self.sql, self.raise_on, self.exc = conn, [], raise_on, exc

    def acquire(self):
        pool = self

        class _C:
            def __getattr__(self, name):
                attr = getattr(pool.conn, name)
                if name not in ("fetch", "fetchrow", "fetchval", "execute"):
                    return attr

                async def run(sql, *a, **k):
                    pool.sql.append(sql)
                    if pool.raise_on and pool.raise_on in sql:
                        raise pool.exc("simulated")
                    return await attr(sql, *a, **k)
                return run

        class _Ctx:
            async def __aenter__(self):
                return _C()

            async def __aexit__(self, *exc):
                return False
        return _Ctx()


@needs_db
async def test_the_panel_locks_in_the_swap_order_version_first(conn, monkeypatch):
    """The deadlock guard for the panel: the statements it ACTUALLY runs (recorded, not rebuilt by hand) name
    the lock-ordered plankton tables in a subsequence of SWAP_LOCK_ORDER, so the version table comes first."""
    import re
    import db
    await seed_live(conn, _rows())
    rec = _RecordingPool(conn)
    monkeypatch.setattr(db, "pool", rec)
    assert (await _get(f"/v1/plankton/site/{K1}")).status_code == 200
    order = {t: i for i, t in enumerate(p.SWAP_LOCK_ORDER)}
    named = [t for sql in rec.sql for t in re.findall(r"\b(plankton_[a-z_]+)\b", sql) if t in order]
    firsts = list(dict.fromkeys(named))
    assert firsts[0] == "plankton_tile_version" and firsts == sorted(firsts, key=order.get), firsts


@needs_db
@pytest.mark.parametrize("exc_name", ["DeadlockDetectedError", "LockNotAvailableError"])
async def test_a_deadlock_victim_panel_is_a_503_with_a_short_retry_never_a_500(conn, monkeypatch, exc_name):
    import asyncpg
    import db
    await seed_live(conn, _rows())
    monkeypatch.setattr(db, "pool", _RecordingPool(conn, raise_on="FROM plankton_sites", exc=getattr(asyncpg, exc_name)))
    r = await _get(f"/v1/plankton/site/{K1}")
    assert r.status_code == 503 and r.headers["retry-after"] == "5"
    assert "simulated" not in r.text
