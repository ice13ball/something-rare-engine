# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""The Davis Strait source against real PostGIS: what a run stores, what an outage leaves,
how links and the per-station summary count both archives, what the endpoint says.

The ADC is a ``MockTransport`` serving the REAL Solr documents of the dataset (id, file name,
dates) for the trimmed real netCDF files of ``fixtures/oceansites_gdac/adc_davis/`` — the only
thing changed is ``size`` / ``checksum``, recomputed from the trimmed bytes the mock serves, so
the download's integrity check has something true to compare. Register rows are copied from
production (``DS_*``).

⛔ What is protected: an unreachable ADC never blanks what is stored ("could not look" is not
"nothing there"); a changed file replaces its old series; a file is downloaded once; a
mooring's record is never credited to an archive it did not come from.
"""
import hashlib
import json
import os
import urllib.parse
from datetime import date
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)

FIX = Path(__file__).parent / "fixtures" / "oceansites_gdac" / "adc_davis"
GDAC_FIX = FIX.parent
LISTING = json.loads((FIX / "solr_listing.json").read_text(encoding="utf-8"))
REAL_DOCS = {d["fileName"]: d for d in LISTING["response"]["docs"] if d.get("fileName")}

BI4_2010 = "Davis_MicroCAT_BI4_2010_96m_L2.nc"
BI4_2004 = "Davis_MicroCAT_BI4_2004_151m_L2.nc"
BI4_2015 = "Davis_MicroCAT_BI4_2015_28m_L2.nc"
C4_2013 = "Davis_RCM_velocity_C4_2013_500m_L2.nc"
C6_EMPTY = "Davis_RCM_velocity_C6_2013_250m_L2.nc"
SERVED = (BI4_2010, BI4_2004, BI4_2015, C4_2013, C6_EMPTY)

# Register rows copied from production (OceanOPS: withheld from the public mirror, so these
# tests skip there, like the other tests that read production_moorings.json).
_REGISTER_FILE = GDAC_FIX / "adc_davis_register.json"
if not _REGISTER_FILE.exists():
    pytest.skip("adc_davis_register.json is withheld from the public mirror (OceanOPS terms)",
                allow_module_level=True)
REGISTER = [
    (r["ref"], r["name"], r["lat"], r["lon"], date.fromisoformat(r["deploy_date"]))
    for r in json.loads(_REGISTER_FILE.read_text(encoding="utf-8"))["stations"]
]
REF = {(n, d): r for r, n, _, _, d in REGISTER}
C4_ROW = "TMP-1036802018"

_TABLES = ("oceansites_gdac_series", "oceansites_gdac_fetched", "oceansites_station_files",
           "oceansites_gdac_files", "oceansites_deployments", "oceansites_stations")


def _md5(b: bytes) -> str:
    return hashlib.md5(b).hexdigest()


class FakeAdc:
    """The ADC as the code sees it: a Solr listing and an object endpoint."""

    def __init__(self, names=SERVED, extra_names=("Davis_ADCP_BI4_2010_96m_L2.nc",
                                                 "Davis_MicroCAT_C2_2011_92m_L2.nc")):
        self.bytes = {n: (FIX / n).read_bytes() for n in names}
        self.extra = list(extra_names)          # real docs we list but never have bytes for
        self.requested: list[str] = []          # file names whose object was asked for
        self.listing_status = 200
        self.fail: dict[str, object] = {}       # file name -> "503" | 404 | "truncate" | bytes override

    def docs(self):
        out = []
        for n, b in self.bytes.items():
            d = dict(REAL_DOCS[n])
            d["size"], d["checksum"] = len(b), _md5(b)
            out.append(d)
        out += [REAL_DOCS[n] for n in self.extra]
        return out

    def handler(self, request: httpx.Request):
        url = urllib.parse.unquote(str(request.url))
        if "/query/solr/" in url:
            if self.listing_status != 200:
                return httpx.Response(self.listing_status)
            docs = self.docs()
            start, rows = int(request.url.params["start"]), int(request.url.params["rows"])
            return httpx.Response(200, json={"response": {
                "numFound": len(docs), "start": start, "docs": docs[start:start + rows]}})
        for d in self.docs():
            if url.endswith(d["id"]):
                name = d["fileName"]
                self.requested.append(name)
                mode = self.fail.get(name)
                if mode == "503":
                    return httpx.Response(503)
                if mode == 404:
                    return httpx.Response(404)
                body = self.bytes.get(name)
                if body is None:
                    return httpx.Response(404)
                if mode == "truncate":
                    body = body[: len(body) // 2]
                if mode == "corrupt":        # same length, one flipped byte: only the checksum can tell
                    body = body[:-1] + bytes([body[-1] ^ 0xFF])
                return httpx.Response(200, content=body)
        return httpx.Response(404)

    def client(self):
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))

    def republish(self, name, new_bytes):
        """The ADC replaced the file: new bytes, hence a new checksum in the listing."""
        self.bytes[name] = new_bytes


@pytest.fixture
async def pool(monkeypatch):
    import asyncpg
    import db as _db
    import response_cache
    import schema
    from domains import sensors
    from ingestion import oceansites_adc as adc

    monkeypatch.setattr(adc, "_RETRY_DELAY", 0)
    _db.pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    await schema.ensure_schema()

    async def clean(c):
        for t in _TABLES:
            await c.execute(f"DELETE FROM {t}")
        await c.execute("DELETE FROM sync_log WHERE source = 'oceansites-history'")

    async with _db.pool.acquire() as c:
        await clean(c)
        for ref, name, lat, lon, when in REGISTER:
            await c.execute(
                """INSERT INTO oceansites_stations (ref, name, status, lat, lon, geom, deploy_date)
                   VALUES ($1, $2, 'CLOSED', $3, $4, ST_SetSRID(ST_MakePoint($4, $3), 4326), $5)""",
                ref, name, lat, lon, when)
            await c.execute(
                """INSERT INTO oceansites_deployments (ref, base_ref, deploy_num, name, lat, lon, deploy_date)
                   VALUES ($1, $1, 0, $2, $3, $4, $5)""", ref, name, lat, lon, when)
    response_cache.store.clear()
    sensors.clear_oceansites_map_cache()
    yield _db.pool
    async with _db.pool.acquire() as c:
        await clean(c)
    response_cache.store.clear()
    sensors.clear_oceansites_map_cache()
    await _db.pool.close()


@pytest.fixture
async def client(pool):
    from auth import get_api_key
    from domains import oceansites_history, sensors
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    app = FastAPI()
    app.include_router(oceansites_history.router)
    app.include_router(sensors.router)
    app.dependency_overrides[get_api_key] = lambda: None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


def _key(name):
    return "ADC/A2416T169/" + name


async def _snapshot(pool):
    async with pool.acquire() as c:
        return {
            "files": [dict(r) for r in await c.fetch("SELECT * FROM oceansites_gdac_files ORDER BY file")],
            "series": [dict(r) for r in await c.fetch(
                "SELECT * FROM oceansites_gdac_series ORDER BY file, variable, depth_index")],
            "fetched": [dict(r) for r in await c.fetch("SELECT * FROM oceansites_gdac_fetched ORDER BY file")],
            "links": [dict(r) for r in await c.fetch("SELECT * FROM oceansites_station_files ORDER BY 1, 2")],
        }


def _real_refresh():
    from domains import oceansites_history as dom
    return _REAL.setdefault("refresh_adc", dom.refresh_adc)   # captured before any test patches it


_REAL: dict = {}


async def _run(fake, **kw):
    async with fake.client() as c:
        return await _real_refresh()(client=c, **kw)


# ── a first run ──────────────────────────────────────────────────────────────

async def test_a_first_run_stores_the_catalogue_the_series_and_the_read_log_and_asks_only_for_what_can_matter(pool):
    fake = FakeAdc()
    s = await _run(fake)

    assert s["listed"] == len(SERVED) + 2 and s["failed"] == 0
    assert s["ok"] == 4 and s["empty"] == 1                       # C6 2013 is all fill: read fine, nothing to store
    assert sorted(fake.requested) == sorted(SERVED), "the ADCP file and the mooring with no register row are never fetched"
    assert s["not_read_instrument"] == 1 and s["no_register_row"] == 1

    snap = await _snapshot(pool)
    f = {r["file"]: r for r in snap["files"]}
    assert set(f) == {_key(n) for n in SERVED}
    r = f[_key(BI4_2010)]
    assert (r["source"], r["site_dir"], r["platform_code"], r["data_mode"]) == ("adc_davis", "ADC/A2416T169", "BI4", None)
    assert r["landing_url"] == "https://doi.org/10.18739/A2416T169"
    assert r["size_bytes"] == len((FIX / BI4_2010).read_bytes())
    assert str(r["start_time"].date()) == "2010-09-15" and str(r["end_time"].date()) == "2011-10-07"
    assert r["gdac_update_date"] is not None and r["min_depth"] == r["max_depth"] == 96.0
    assert r["parameters"] == ["sea_water_practical_salinity", "sea_water_temperature"]
    assert f[_key(C6_EMPTY)]["start_time"] is not None, "an all-fill file is still a catalogued record"

    series = snap["series"]
    assert len(series) == 3 * 2 + 2                                 # three MicroCATs x (T, S) + the RCM (u, v)
    assert {r["file"] for r in series} == {_key(n) for n in SERVED if n != C6_EMPTY}
    fetched = {r["file"]: r for r in snap["fetched"]}
    assert fetched[_key(BI4_2010)]["outcome"] == "ok" and fetched[_key(C6_EMPTY)]["outcome"] == "empty"
    assert fetched[_key(BI4_2010)]["change_marker"].startswith("adc:MD5:")
    assert fetched[_key(BI4_2010)]["citation"].startswith("Lee, C. (2024). Davis Strait")


async def test_fill_values_are_null_in_the_database_and_units_are_the_files(pool):
    await _run(FakeAdc())
    async with pool.acquire() as c:
        rows = await c.fetch("SELECT variable, units, vals, qc, depth_m, stride, n_total "
                             "FROM oceansites_gdac_series WHERE file = $1 ORDER BY variable", _key(C4_2013))
    east = next(r for r in rows if r["variable"] == "eastward_sea_water_velocity")
    assert east["units"] == "m s-1" and east["depth_m"] == 500.0 and (east["stride"], east["n_total"]) == (2, 300)
    assert east["vals"].count(None) == 27 and all(v is None or abs(v) < 1e3 for v in east["vals"])
    async with pool.acquire() as c:
        t = await c.fetchrow("SELECT units FROM oceansites_gdac_series WHERE file = $1 AND variable = 'sea_water_temperature'",
                             _key(BI4_2010))
    assert t["units"] == "degree_C"


# ── incremental ──────────────────────────────────────────────────────────────

async def test_a_file_read_before_and_unchanged_is_not_downloaded_again(pool):
    fake = FakeAdc()
    await _run(fake)
    first = await _snapshot(pool)
    fake.requested.clear()

    s = await _run(fake)

    assert fake.requested == [] and s["due"] == 0 and s["attempted"] == 0
    assert await _snapshot(pool) == first                           # not even fetched_at moved


async def test_a_republished_file_is_read_again_and_replaces_the_old_series(pool):
    fake = FakeAdc()
    await _run(fake)
    async with pool.acquire() as c:
        before = await c.fetchval("SELECT vals FROM oceansites_gdac_series WHERE file = $1 AND variable = 'sea_water_temperature'",
                                  _key(BI4_2010))
        marker = await c.fetchval("SELECT change_marker FROM oceansites_gdac_fetched WHERE file = $1", _key(BI4_2010))
    # the ADC replaces the 2010 file by another real BI4 file (different numbers, one depth)
    fake.republish(BI4_2010, (FIX / BI4_2004).read_bytes())
    fake.requested.clear()

    s = await _run(fake)

    assert fake.requested == [BI4_2010] and s["ok"] == 1
    async with pool.acquire() as c:
        after = await c.fetchval("SELECT vals FROM oceansites_gdac_series WHERE file = $1 AND variable = 'sea_water_temperature'",
                                 _key(BI4_2010))
        n = await c.fetchval("SELECT COUNT(*) FROM oceansites_gdac_series WHERE file = $1", _key(BI4_2010))
        new_marker = await c.fetchval("SELECT change_marker FROM oceansites_gdac_fetched WHERE file = $1", _key(BI4_2010))
    assert after != before and n == 2, "the file's series are replaced, not appended to"
    assert new_marker != marker


# ── an outage leaves what is stored alone ────────────────────────────────────

async def test_an_unreachable_listing_changes_nothing_and_says_so(pool):
    fake = FakeAdc()
    await _run(fake)
    stored = await _snapshot(pool)
    fake.listing_status = 503

    assert await _run(fake) is None
    assert await _snapshot(pool) == stored


async def test_a_download_outage_writes_nothing_and_the_file_stays_due(pool):
    fake = FakeAdc()
    await _run(fake)
    stored = await _snapshot(pool)
    fake.republish(BI4_2010, (FIX / BI4_2004).read_bytes())     # a new version is waiting ...
    fake.fail[BI4_2010] = "503"                                   # ... but the server cannot serve it

    s = await _run(fake)

    assert s["failed"] == 1 and s["failed_unavailable"] == 1 and s["ok"] == 0
    assert await _snapshot(pool) == stored, "stored rows, read log and links are exactly as they were"
    del fake.fail[BI4_2010]
    assert (await _run(fake))["ok"] == 1, "once the server is back the file is read"


async def test_a_truncated_download_is_an_outage_not_a_file(pool):
    fake = FakeAdc()
    fake.fail[BI4_2010] = "truncate"
    s = await _run(fake)
    assert s["failed_unavailable"] == 1
    async with pool.acquire() as c:
        assert await c.fetchval("SELECT COUNT(*) FROM oceansites_gdac_files WHERE file = $1", _key(BI4_2010)) == 0
        assert await c.fetchval("SELECT COUNT(*) FROM oceansites_gdac_fetched WHERE file = $1", _key(BI4_2010)) == 0


async def test_a_download_with_the_right_length_but_the_wrong_checksum_is_an_outage_not_a_file(pool):
    fake = FakeAdc()
    fake.fail[BI4_2010] = "corrupt"
    s = await _run(fake)
    assert s["failed_unavailable"] == 1
    async with pool.acquire() as c:
        assert await c.fetchval("SELECT COUNT(*) FROM oceansites_gdac_files WHERE file = $1", _key(BI4_2010)) == 0
        assert await c.fetchval("SELECT COUNT(*) FROM oceansites_gdac_fetched WHERE file = $1", _key(BI4_2010)) == 0


async def test_a_run_whose_server_keeps_failing_stops_early(pool, monkeypatch):
    from ingestion import oceansites_adc as adc
    monkeypatch.setattr(adc, "ABORT_AFTER_UNAVAILABLE", 2)
    monkeypatch.setattr(adc, "CONCURRENCY", 1)
    fake = FakeAdc()
    for n in SERVED:
        fake.fail[n] = "503"
    s = await _run(fake)
    assert s["aborted"] is True and s["failed_unavailable"] == 2
    assert len(fake.requested) == 2 * adc._RETRIES                  # two files, retried, then it stops
    assert (await _snapshot(pool))["files"] == []


# ── a settled answer is recorded and not asked again ─────────────────────────

async def test_a_404_is_recorded_as_refused_and_not_asked_again_until_the_file_changes(pool):
    fake = FakeAdc()
    fake.fail[BI4_2010] = 404
    s = await _run(fake)
    assert s["refused"] == 1
    async with pool.acquire() as c:
        row = await c.fetchrow("SELECT outcome, detail FROM oceansites_gdac_fetched WHERE file = $1", _key(BI4_2010))
        assert await c.fetchval("SELECT COUNT(*) FROM oceansites_gdac_files WHERE file = $1", _key(BI4_2010)) == 0
    assert row["outcome"] == "refused" and "404" in row["detail"]
    fake.requested.clear()
    await _run(fake)
    assert BI4_2010 not in fake.requested


async def test_a_file_over_the_size_cap_is_refused_without_being_requested(pool, monkeypatch):
    from ingestion import oceansites_adc as adc
    fake = FakeAdc()
    cap = len((FIX / BI4_2010).read_bytes()) - 1
    monkeypatch.setattr(adc, "MAX_BYTES", max(cap, max(len(b) for b in fake.bytes.values()) - 1))
    biggest = max(fake.bytes, key=lambda n: len(fake.bytes[n]))
    s = await _run(fake)
    assert s["refused"] >= 1 and biggest not in fake.requested
    async with pool.acquire() as c:
        row = await c.fetchrow("SELECT outcome, detail FROM oceansites_gdac_fetched WHERE file = $1", _key(biggest))
    assert row["outcome"] == "refused" and "cap" in row["detail"]


async def test_a_file_whose_content_contradicts_its_name_is_refused_and_never_catalogued(pool):
    fake = FakeAdc()
    fake.republish(BI4_2010, (FIX / C4_2013).read_bytes())          # a C4 file under a BI4 name
    s = await _run(fake)
    assert s["refused"] == 1
    snap = await _snapshot(pool)
    assert _key(BI4_2010) not in {r["file"] for r in snap["files"]}
    assert _key(BI4_2010) not in {r["file"] for r in snap["series"]}
    row = next(r for r in snap["fetched"] if r["file"] == _key(BI4_2010))
    assert row["outcome"] == "refused" and "attributes say" in row["detail"]


async def test_bytes_that_are_not_a_netcdf_are_settled_as_nothing_to_read(pool):
    fake = FakeAdc()
    fake.republish(BI4_2010, b"<html><body>maintenance</body></html>")
    s = await _run(fake)
    assert s["empty"] >= 1 and s["failed"] == 0
    async with pool.acquire() as c:
        assert await c.fetchval("SELECT outcome FROM oceansites_gdac_fetched WHERE file = $1", _key(BI4_2010)) == "empty"


# ── links and summary, both sources ──────────────────────────────────────────

async def test_links_and_the_summary_are_built_from_the_adc_files_by_name_and_date(pool):
    from domains import oceansites_history as dom
    await _run(FakeAdc())

    summary = await dom.rebuild_links()

    assert summary["adc_linked_files"] == 5 and summary["adc_linked_stations"] == 5
    async with pool.acquire() as c:
        links = {(r["station_ref"], r["file"].split("/")[-1]): r["rule"] for r in
                 await c.fetch("SELECT station_ref, file, rule FROM oceansites_station_files")}
        summ = {r["ref"]: dict(r) for r in await c.fetch(
            "SELECT ref, history_files, history_start, history_end FROM oceansites_stations")}
    assert links[("TMP-472585258", BI4_2010)] == "adc-name-date"
    assert links[(C4_ROW, C4_2013)] == "adc-name-date"
    assert (REF[("DS_C4", date(2015, 9, 12))], C4_2013) not in links, "the row registered the day after the file ended"
    assert (REF[("DS_BI4", date(2004, 9, 28))], BI4_2004) in links
    assert (REF[("DS_BI4", date(2015, 9, 13))], BI4_2015) in links
    assert summ[C4_ROW]["history_files"] == 1
    assert str(summ[C4_ROW]["history_start"].date()) == "2013-09-16" and str(summ[C4_ROW]["history_end"].date()) == "2015-09-11"
    assert summ[REF[("DS_C4", date(2015, 9, 12))]]["history_files"] == 0
    # the all-fill C6 file is a record of that mooring even though it has nothing to plot
    assert summ[REF[("DS_C6", date(2013, 9, 16))]]["history_files"] == 1


async def test_a_non_ds_station_on_top_of_an_adc_file_is_not_linked_by_position(pool):
    from domains import oceansites_history as dom
    await _run(FakeAdc())
    async with pool.acquire() as c:
        for ref, name in (("POS1", "BI4"), ("POS2", "DS_BI9")):     # exactly at the file's position
            await c.execute(
                """INSERT INTO oceansites_stations (ref, name, status, lat, lon, geom, deploy_date)
                   VALUES ($1, $2, 'CLOSED', 66.659423, -61.1689, ST_SetSRID(ST_MakePoint(-61.1689, 66.659423), 4326), '2010-09-15')""",
                ref, name)
    await dom.rebuild_links()
    async with pool.acquire() as c:
        assert await c.fetchval("SELECT COUNT(*) FROM oceansites_station_files WHERE station_ref IN ('POS1','POS2')") == 0


async def test_the_gdac_series_step_never_reaches_for_an_adc_file(pool, monkeypatch):
    from domains import oceansites_history as dom
    await _run(FakeAdc())
    await dom.rebuild_links()
    asked = []

    async def reachable():
        return True

    monkeypatch.setattr(dom, "gdac_reachable", reachable)

    def handler(request):
        asked.append(str(request.url))
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        s = await dom.fetch_series(client=c)
    assert asked == [] and s["selected"] == 0, "ADC rows are not OPeNDAP candidates"


async def test_rebuild_counts_both_archives_for_one_station(pool):
    """A station linked to a GDAC file AND an ADC file counts both (history_files, start, end)."""
    from domains import oceansites_history as dom
    from datetime import datetime, timezone
    await _run(FakeAdc())
    t = lambda y, m, d: datetime(y, m, d, tzinfo=timezone.utc)   # noqa: E731
    async with pool.acquire() as c:
        await c.execute(
            """INSERT INTO oceansites_stations (ref, name, status, lat, lon, geom, deploy_date)
               VALUES ('G1', 'PAP-3', 'CLOSED', 48.9, -16.5, ST_SetSRID(ST_MakePoint(-16.5, 48.9), 4326), '2005-01-01')""")
        await c.execute(
            """INSERT INTO oceansites_gdac_files (file, site_dir, platform_code, data_mode, start_time, end_time, lat, lon,
                                                  bbox_south, bbox_north, bbox_west, bbox_east)
               VALUES ('DATA/PAP/OS_PAP-3_200501_D_CTD.nc', 'PAP', 'PAP-3', 'D', $1, $2, 48.9, -16.5, 48.9, 48.9, -16.5, -16.5)""",
            t(2005, 1, 1), t(2005, 6, 1))
    summary = await dom.rebuild_links()
    assert summary["links"] == summary["adc_links"] + 1
    async with pool.acquire() as c:
        g1 = await c.fetchrow("SELECT history_files, history_end FROM oceansites_stations WHERE ref = 'G1'")
        assert g1["history_files"] == 1 and g1["history_end"].year == 2005
        total = await c.fetchval("SELECT COALESCE(SUM(history_files), 0) FROM oceansites_stations")
        n_links = await c.fetchval("SELECT COUNT(*) FROM oceansites_station_files")
    assert total == n_links


# ── the sync wires both in, each independent of the other ────────────────────

def _wire_sync(monkeypatch, fake, gdac_text):
    from domains import oceansites_history as dom
    from ingestion import oceansites_history as ingest

    _real_refresh()

    async def index(*a, **k):
        return gdac_text

    async def no_series(*a, **k):
        return None

    async def adc_step():
        if fake is None:
            return None
        return await _run(fake)

    monkeypatch.setattr(ingest, "fetch_index", index)
    monkeypatch.setattr(dom, "fetch_series", no_series)
    monkeypatch.setattr(dom, "refresh_adc", adc_step)
    return dom


GDAC_TEXT = (GDAC_FIX / "oceansites_index_sample.txt").read_text(encoding="utf-8")


async def test_the_sync_links_davis_moorings_when_the_gdac_is_down(pool, monkeypatch):
    dom = _wire_sync(monkeypatch, FakeAdc(), None)
    linked = await dom.sync_oceansites_history()
    assert linked == 5                                              # 5 register rows hold an ADC file (C6 2013: all fill)
    async with pool.acquire() as c:
        row = await c.fetchrow("SELECT skipped_reason, last_synced_at FROM sync_log WHERE source = 'oceansites-history'")
    assert row["skipped_reason"] is None and row["last_synced_at"] is not None


async def test_the_sync_links_the_gdac_when_the_adc_is_down_and_keeps_what_the_adc_stored(pool, monkeypatch):
    fake = FakeAdc()
    dom = _wire_sync(monkeypatch, fake, GDAC_TEXT)
    await dom.sync_oceansites_history()
    before = await _snapshot(pool)
    assert any(r["source"] == "adc_davis" for r in before["files"]) and any(r["source"] == "gdac" for r in before["files"])

    fake.listing_status = 503
    await dom.sync_oceansites_history()
    after = await _snapshot(pool)
    adc_rows = lambda s: [r for r in s["files"] if r["source"] == "adc_davis"]   # noqa: E731
    assert [r["file"] for r in adc_rows(after)] == [r["file"] for r in adc_rows(before)]
    assert after["series"] == before["series"], "an ADC outage blanks nothing"
    assert after["links"] == before["links"], "and the links are the same, ADC ones included"


async def test_when_both_archives_are_down_the_sync_is_skipped_and_touches_nothing(pool, monkeypatch):
    dom = _wire_sync(monkeypatch, None, None)
    assert await dom.sync_oceansites_history() == 0
    async with pool.acquire() as c:
        row = await c.fetchrow("SELECT skipped_reason, last_synced_at FROM sync_log WHERE source = 'oceansites-history'")
        assert await c.fetchval("SELECT COUNT(*) FROM oceansites_gdac_files") == 0
    assert row["skipped_reason"] and row["last_synced_at"] is None


async def test_an_exception_in_the_adc_step_does_not_stop_the_gdac_half(pool, monkeypatch):
    from domains import oceansites_history as dom
    dom = _wire_sync(monkeypatch, FakeAdc(), GDAC_TEXT)

    async def boom():
        raise RuntimeError("adc step blew up")

    monkeypatch.setattr(dom, "refresh_adc", boom)
    await dom.sync_oceansites_history()
    async with pool.acquire() as c:
        assert await c.fetchval("SELECT COUNT(*) FROM oceansites_gdac_files WHERE source = 'gdac'") > 0


# ── the endpoint ─────────────────────────────────────────────────────────────

async def test_the_endpoint_names_the_source_gives_the_doi_and_cites_the_arctic_data_center(pool, client):
    from domains import oceansites_history as dom
    from ingestion import oceansites_adc as adc
    await _run(FakeAdc())
    await dom.rebuild_links()

    r = await client.get(f"/v1/oceansites/{C4_ROW}/history")
    body = r.json()

    assert r.status_code == 200
    f = body["files"][0]
    assert f["source"] == "adc_davis" and f["file"] == _key(C4_2013)
    assert f["url"] == "https://doi.org/10.18739/A2416T169" and f["url_opendap_html"] is None
    assert (f["start"][:10], f["end"][:10], f["min_depth"], f["max_depth"]) == ("2013-09-16", "2015-09-11", 500.0, 500.0)
    assert body["citations"] == [adc.CITATION] and body["citation"] == adc.CITATION
    assert "OceanSITES" not in " ".join(body["citations"]), "an Arctic Data Center record is not credited to OceanSITES"
    assert body["n_catalogue_files"] == 1 and body["n_files_read"] == 1
    east = next(s for s in body["series"] if s["standard_name"] == "eastward_sea_water_velocity")
    assert east["units"] == "m s-1" and east["depth_m"] == 500
    assert east["missing"] == 27, "the fills are counted, not drawn"
    assert all(abs(p[1]) < 1e3 for p in east["points"]) and len(east["points"]) == 150 - 27 - east["qc_withheld"] - east["range_withheld"]


async def test_the_adc_citation_comes_from_the_code_not_from_whatever_the_read_log_holds(pool, client):
    from domains import oceansites_history as dom
    from ingestion import oceansites_adc as adc
    await _run(FakeAdc())
    await dom.rebuild_links()
    async with pool.acquire() as c:
        await c.execute("UPDATE oceansites_gdac_fetched SET citation = NULL")
    body = (await client.get(f"/v1/oceansites/{C4_ROW}/history")).json()
    assert body["citations"] == [adc.CITATION]


async def test_the_endpoint_for_a_row_with_only_an_unplottable_file_reports_it_in_the_catalogue_count_only(pool, client):
    from domains import oceansites_history as dom
    await _run(FakeAdc())
    await dom.rebuild_links()
    body = (await client.get(f"/v1/oceansites/{REF[('DS_C6', date(2013, 9, 16))]}/history")).json()
    assert body["n_catalogue_files"] == 1 and body["n_files_read"] == 0 and body["files"] == [] and body["series"] == []


async def test_a_mooring_with_both_a_gdac_and_an_adc_file_cites_both_and_leads_with_oceansites(pool, client):
    from domains import oceansites_history as dom
    from ingestion import oceansites_adc as adc
    await _run(FakeAdc())
    await dom.rebuild_links()
    async with pool.acquire() as c:   # hand-seeded: no real mooring is in both archives
        await c.execute(
            "INSERT INTO oceansites_gdac_files (file, site_dir, data_mode, start_time, end_time, min_depth, max_depth) "
            "VALUES ('DATA/X/OS_X_D.nc', 'X', 'D', '2013-10-01', '2013-11-01', 10, 20)")
        await c.execute(
            "INSERT INTO oceansites_gdac_series (file, variable, depth_index, depth_m, units, standard_name, n_total, stride, times, vals, qc) "
            "VALUES ('DATA/X/OS_X_D.nc', 'TEMP', 0, 10, 'degree_Celsius', 'sea_water_temperature', 2, 1, "
            "ARRAY['2013-10-01'::timestamptz, '2013-10-02'::timestamptz], ARRAY[1.0, 2.0], ARRAY[1, 1]::smallint[])")
        await c.execute("INSERT INTO oceansites_station_files VALUES ($1, 'DATA/X/OS_X_D.nc', 'exact', 0)", C4_ROW)
    body = (await client.get(f"/v1/oceansites/{C4_ROW}/history")).json()
    assert {f["source"] for f in body["files"]} == {"gdac", "adc_davis"}
    assert body["citations"][0].startswith("These data were collected") and adc.CITATION in body["citations"]
    gdac = next(f for f in body["files"] if f["source"] == "gdac")
    assert gdac["url"] == gdac["url_opendap_html"] and gdac["url"].endswith("DATA/X/OS_X_D.nc.html")
