# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""What sync_oceansites_history leaves in the database, against real PostGIS.

Input is the real index slice and the real production moorings used by
test_oceansites_history_index.py; only ``fetch_index`` is replaced.

⛔ "Missing" and "broken" must not share a code path. On 2026-10-01 the GDAC
answered 503 to everything for about an hour. A run that could not fetch the
index must leave the catalogue, the links and the per-station summary exactly
as they were — and must not stamp the layer as freshly synced.
"""
import json
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)

FIX = Path(__file__).parent / "fixtures" / "oceansites_gdac"
INDEX_TEXT = (FIX / "oceansites_index_sample.txt").read_text(encoding="utf-8")
_MOORINGS_FILE = FIX / "production_moorings.json"
N_FILES = 54  # DATA/ lines of the slice; the gridded line and the fragment are not rows

_TABLES = ("oceansites_station_files", "oceansites_gdac_files",
           "oceansites_deployments", "oceansites_stations")


async def _clean(c):
    for t in _TABLES:
        await c.execute(f"DELETE FROM {t}")
    await c.execute("DELETE FROM sync_log WHERE source = 'oceansites-history'")


@pytest.fixture
async def pool():
    import asyncpg
    import db as _db
    import schema

    # ⛔ OceanOPS register rows: all rights reserved, withheld from the public mirror
    # (scripts/export-public.sh NEVER_RULES) — skip there, never error.
    if not _MOORINGS_FILE.exists():
        pytest.skip("production_moorings.json is withheld from the public mirror (OceanOPS terms)")
    MOORINGS = json.loads(_MOORINGS_FILE.read_text(encoding="utf-8"))

    _db.pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    await schema.ensure_schema()
    async with _db.pool.acquire() as c:
        await _clean(c)
        for s in MOORINGS["stations"]:
            await c.execute(
                """INSERT INTO oceansites_stations (ref, name, status, lat, lon, geom)
                   VALUES ($1, $2, 'CLOSED', $3, $4, ST_SetSRID(ST_MakePoint($4, $3), 4326))""",
                s["ref"], s["name"], s["lat"], s["lon"],
            )
        for ref, ds in MOORINGS["deployments"].items():
            for i, d in enumerate(ds):
                await c.execute(
                    """INSERT INTO oceansites_deployments (ref, base_ref, deploy_num, name, lat, lon)
                       VALUES ($1, $2, $3, $4, $5, $6)""",
                    f"{ref}_{i:03d}", ref, i, d["name"], d["lat"], d["lon"],
                )
    yield _db.pool
    async with _db.pool.acquire() as c:
        await _clean(c)
    await _db.pool.close()


def _index(monkeypatch, text):
    from ingestion import oceansites_history as ingest

    async def fake_fetch_index(*a, **k):
        return text

    monkeypatch.setattr(ingest, "fetch_index", fake_fetch_index)

    # These tests are about the catalogue and the links; the OPeNDAP series step
    # has its own tests (test_oceansites_history_series_db.py) and must not
    # reach the real server from here.
    from domains import oceansites_history as dom

    async def no_series(*a, **k):
        return None

    monkeypatch.setattr(dom, "fetch_series", no_series)


async def _snapshot(pool):
    async with pool.acquire() as c:
        return {
            "files": [dict(r) for r in await c.fetch("SELECT * FROM oceansites_gdac_files ORDER BY file")],
            "links": [dict(r) for r in await c.fetch(
                "SELECT * FROM oceansites_station_files ORDER BY station_ref, file")],
            "summary": [dict(r) for r in await c.fetch(
                "SELECT ref, history_start, history_end, history_files "
                "FROM oceansites_stations ORDER BY ref")],
        }


async def _sync_log(pool):
    async with pool.acquire() as c:
        r = await c.fetchrow("SELECT * FROM sync_log WHERE source = 'oceansites-history'")
    return dict(r) if r else None


async def test_first_run_writes_catalogue_links_and_summary(pool, monkeypatch):
    from domains import oceansites_history as dom

    _index(monkeypatch, INDEX_TEXT)
    linked = await dom.sync_oceansites_history()

    snap = await _snapshot(pool)
    assert len(snap["files"]) == N_FILES
    assert linked == len({l["station_ref"] for l in snap["links"]}) > 10

    by_file = {r["file"].rsplit("/", 1)[-1]: r for r in snap["files"]}
    assert by_file["OS_WHOTS_200408-202108_D_MLTS-1H.nc"]["position_source"] == "site_median"
    assert by_file["OS_MBARI-M1_20260619_R_TS.nc"]["parameters"][:3] == ["longitude", "latitude", "depth"]
    assert by_file["OS_ACO_20110613-16-24_P_CTD3-4726m.nc"]["end_time"].isoformat() == "2011-06-14T00:00:00+00:00"

    summary = {r["ref"]: r for r in snap["summary"]}
    tao = summary["5100311"]                      # 0N140W: one ADCP file
    assert tao["history_files"] == 1
    assert tao["history_start"].isoformat() == "2016-02-28T01:00:00+00:00"
    assert tao["history_end"].isoformat() == "2016-04-05T08:00:00+00:00"
    pap = summary["6801011"]                      # PAP-1: two files, span = min start .. max end
    assert pap["history_files"] == 2
    assert pap["history_start"].isoformat() == "2003-07-12T14:15:06+00:00"
    assert pap["history_end"].isoformat() == "2010-09-09T18:50:08+00:00"
    # unlinked stations carry 0 and no span, never NULL files
    for ref in ("TMPWKF6YRWPMI", "2100210", "TMPMCBDA2PKST"):   # CALCOFI, unnamed, OFP
        assert summary[ref]["history_files"] == 0
        assert summary[ref]["history_start"] is None and summary[ref]["history_end"] is None
    assert sum(r["history_files"] for r in snap["summary"]) == len(snap["links"])

    log = await _sync_log(pool)
    assert log["total_records"] == N_FILES and log["records_added"] == linked
    assert log["last_synced_at"] is not None and log["skipped_reason"] is None


async def test_unreachable_index_changes_nothing_and_is_not_a_success(pool, monkeypatch):
    from domains import oceansites_history as dom

    _index(monkeypatch, INDEX_TEXT)
    await dom.sync_oceansites_history()
    before = await _snapshot(pool)
    log_before = await _sync_log(pool)

    _index(monkeypatch, None)                     # 503 / timeout / not the index
    assert await dom.sync_oceansites_history() == 0

    assert await _snapshot(pool) == before        # seen_at included: not a row was touched
    log_after = await _sync_log(pool)
    assert log_after["skipped_reason"] and "unreachable" in log_after["skipped_reason"]
    assert log_after["last_synced_at"] == log_before["last_synced_at"]   # not stamped fresh
    assert log_after["total_records"] == N_FILES                         # still describes what is stored


async def test_first_ever_run_with_unreachable_index_leaves_a_trace_and_no_rows(pool, monkeypatch):
    from domains import oceansites_history as dom

    _index(monkeypatch, None)
    assert await dom.sync_oceansites_history() == 0
    snap = await _snapshot(pool)
    assert snap["files"] == [] and snap["links"] == []
    log = await _sync_log(pool)
    assert log["skipped_reason"] and log["last_synced_at"] is None


async def test_refresh_is_an_upsert_that_never_deletes(pool, monkeypatch):
    from domains import oceansites_history as dom

    _index(monkeypatch, INDEX_TEXT)
    assert await dom.refresh_catalogue() == N_FILES
    assert await dom.refresh_catalogue() == N_FILES        # same index again: no duplicates
    async with pool.acquire() as c:
        assert await c.fetchval("SELECT COUNT(*) FROM oceansites_gdac_files") == N_FILES

    # The index changes: one file vanishes, one file's END_DATE moves.
    lines = INDEX_TEXT.splitlines()
    gone = next(l for l in lines if "OS_PAP-3_201205_P_deepTS.nc" in l)
    moved = next(l for l in lines if "OS_CCE1_01_D_AQUADOPP.nc" in l)
    new_moved = moved.replace("2009-02-07T00:00:00Z", "2031-01-01T00:00:00Z")
    assert new_moved != moved
    edited = [new_moved if l == moved else l for l in lines if l != gone]
    _index(monkeypatch, "\n".join(edited) + "\n")
    assert await dom.refresh_catalogue() == N_FILES - 1

    async with pool.acquire() as c:
        assert await c.fetchval("SELECT COUNT(*) FROM oceansites_gdac_files") == N_FILES   # kept
        end = await c.fetchval(
            "SELECT end_time FROM oceansites_gdac_files WHERE file = 'DATA/CCE1/OS_CCE1_01_D_AQUADOPP.nc'")
    assert end.isoformat() == "2031-01-01T00:00:00+00:00"                                   # updated


async def test_rebuild_links_is_repeatable_and_an_empty_catalogue_is_not_a_reset(pool, monkeypatch):
    from domains import oceansites_history as dom

    _index(monkeypatch, INDEX_TEXT)
    await dom.refresh_catalogue()
    first = await dom.rebuild_links()
    again = await dom.rebuild_links()
    assert first["links"] == again["links"] > 0
    assert first["rejected_nearby"] > 0 and first["rejected_sample"]
    snap = await _snapshot(pool)

    async with pool.acquire() as c:                # (test-only) simulate a never-filled catalogue
        await c.execute("DELETE FROM oceansites_gdac_files")
    assert await dom.rebuild_links() is None
    async with pool.acquire() as c:
        assert await c.fetchval("SELECT COUNT(*) FROM oceansites_station_files") == len(snap["links"])
        assert await c.fetchval(
            "SELECT COALESCE(SUM(history_files), 0) FROM oceansites_stations") == len(snap["links"])


async def test_relink_follows_the_stations_table(pool, monkeypatch):
    from domains import oceansites_history as dom

    _index(monkeypatch, INDEX_TEXT)
    await dom.sync_oceansites_history()
    async with pool.acquire() as c:                # a mooring moves 300 km: its link must go
        await c.execute(
            "UPDATE oceansites_stations SET lat = lat + 3 WHERE ref = '6301862'")  # STATION-M-1
        await c.execute(
            "DELETE FROM oceansites_deployments WHERE base_ref = '6301862'")
    await dom.rebuild_links()
    async with pool.acquire() as c:
        n = await c.fetchval("SELECT history_files FROM oceansites_stations WHERE ref = '6301862'")
        links = await c.fetchval("SELECT COUNT(*) FROM oceansites_station_files WHERE station_ref = '6301862'")
    assert n == 0 and links == 0


async def test_a_sync_drops_the_cached_map_and_history_responses(pool, monkeypatch):
    """The map carries history_* and the endpoint caches its body: both must be
    rebuilt after the sync has written, not served stale for hours."""
    import json

    from auth import get_api_key
    from domains import oceansites_history as dom
    from domains import sensors
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    _index(monkeypatch, INDEX_TEXT)
    app = FastAPI()
    app.include_router(dom.router)
    app.include_router(sensors.router)
    app.dependency_overrides[get_api_key] = lambda: None
    ref = "TMP236332161"  # PAP-2
    sensors.clear_oceansites_map_cache()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        async def hist():
            return (await client.get(f"/v1/oceansites/{ref}/history")).json()

        async def map_props():
            feats = json.loads((await client.get("/v1/map/oceansites")).content)["features"]
            return {f["properties"]["ref"]: f["properties"] for f in feats}[ref]

        assert (await hist())["n_catalogue_files"] == 0                   # cached: nothing linked yet
        assert not (await map_props())["history_files"]         # cached

        await dom.sync_oceansites_history()

        assert (await map_props())["history_files"] >= 1, "the map still serves the pre-sync payload"
        assert (await map_props())["history_start"] is not None
        assert (await hist())["n_catalogue_files"] >= 1, "the history endpoint still serves its pre-sync body"
