# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""What fetch_series leaves in the database, against real PostGIS.

The catalogue rows are verbatim lines of the real GDAC index
(``fixtures/oceansites_gdac/opendap/index_recorded_files.txt`` and
``index_T0N140W.txt``), and the server is an httpx MockTransport that answers
with bytes recorded from the real OPeNDAP server (see oceansites_fixture_server).

⛔ What is protected: a server that cannot answer is not a file with no data.
A failed request — 503, timeout, refusal — must never write: not a row, not a
read-log entry, not an empty series over a stored one.
"""
import asyncio
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from oceansites_fixture_server import (
    BATS_BTL, FIX, IRMINGSEA, MBARI, PAP2, T0N140W, T8S165E, FixtureServer,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)

RECORDED = (FIX / "index_recorded_files.txt").read_text(encoding="utf-8")
TAO_DIR = (FIX / "index_T0N140W.txt").read_text(encoding="utf-8")
# files with recorded answers that the series step should read (PAPA / K276 have no recorded data request)
READ = [T0N140W, PAP2, IRMINGSEA, MBARI, T8S165E]
SAMPLEABLE = READ + [BATS_BTL]   # BATS: a real profile file the step must learn to leave alone


def _tao_files():
    from ingestion import oceansites_history as ingest

    return [r["file"] for r in ingest.parse_index(TAO_DIR)]


def _one_station_each(files):
    """Each file its own mooring: the 30-file selection is per station, and files of
    different moorings that overlap in time must not cover one another here."""
    return {f"S{i}": [f] for i, f in enumerate(files)}


async def _clean(c):
    for t in ("oceansites_gdac_series", "oceansites_gdac_fetched",
              "oceansites_station_files", "oceansites_gdac_files"):
        await c.execute(f"DELETE FROM {t}")


@pytest.fixture
async def pool(monkeypatch):
    import asyncpg
    import db as _db
    import schema
    from ingestion import oceansites_opendap as od

    monkeypatch.setattr(od, "REQUEST_DELAY", 0)
    monkeypatch.setattr(od, "_RETRY_DELAY", 0)
    _db.pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    await schema.ensure_schema()
    async with _db.pool.acquire() as c:
        await _clean(c)
    yield _db.pool
    async with _db.pool.acquire() as c:
        await _clean(c)
    await _db.pool.close()


async def _catalogue(pool, text, links):
    """Load real index lines; ``links`` = {station_ref: [file, ...]}."""
    from domains import oceansites_history as dom
    from ingestion import oceansites_history as ingest

    rows = ingest.parse_index(text)
    async with pool.acquire() as c:
        await c.executemany(dom._UPSERT_SQL, [dom._row_args(r) for r in rows])
        for ref, files in links.items():
            for f in files:
                await c.execute(
                    "INSERT INTO oceansites_station_files (station_ref, file, rule, distance_km) "
                    "VALUES ($1,$2,'exact',0) ON CONFLICT DO NOTHING", ref, f)
    return rows


@pytest.fixture
def reachable(monkeypatch):
    from domains import oceansites_history as dom

    state = {"up": True}

    async def probe(*a, **k):
        return state["up"]

    monkeypatch.setattr(dom, "gdac_reachable", probe)
    return state


async def _run(server, **kw):
    from domains import oceansites_history as dom

    async with httpx.AsyncClient(transport=server.transport()) as client:
        return await dom.fetch_series(client=client, **kw)


async def _series(pool):
    async with pool.acquire() as c:
        return {(r["file"], r["variable"], r["depth_index"]): dict(r) for r in await c.fetch(
            "SELECT * FROM oceansites_gdac_series ORDER BY file, variable, depth_index")}


async def _fetched(pool):
    async with pool.acquire() as c:
        return {r["file"]: dict(r) for r in await c.fetch("SELECT * FROM oceansites_gdac_fetched")}


async def _fill(pool, reachable_state=None):
    await _catalogue(pool, RECORDED, _one_station_each(SAMPLEABLE))
    server = FixtureServer()
    summary = await _run(server)
    return server, summary


# ── what is stored ──────────────────────────────────────────────────────────


async def test_rows_hold_real_samples_fill_as_null_qc_beside_and_the_files_own_units(pool, reachable):
    server, summary = await _fill(pool)
    assert summary["ok"] == 5 and summary["empty"] == 1 and summary["refused"] == 0 and summary["failed"] == 0
    rows = await _series(pool)

    # TAO: 8 depth levels, strided, QC kept, the 500 m level is almost all fill -> NULL
    tao = {k: v for k, v in rows.items() if k[0] == T0N140W}
    assert sorted(k[2] for k in tao) == [0, 2, 4, 6, 8, 10, 12, 14]
    deep = tao[(T0N140W, "TEMP", 14)]
    assert deep["depth_m"] == 500.0 and deep["units"] == "degree_Celsius"
    assert deep["n_total"] == 27005 and deep["stride"] == 181
    assert len(deep["times"]) == len(deep["vals"]) == len(deep["qc"]) == 150
    assert sum(v is None for v in deep["vals"]) == 148
    assert set(deep["qc"]) <= {3, 4, 9, 1}
    for r in tao.values():
        assert -999.0 not in r["vals"] and 1.0e33 not in r["vals"]
        assert all(v is None or -5 < v < 40 for v in r["vals"])
        assert r["times"] == sorted(r["times"]) and r["first_time"] <= r["last_time"]
        assert r["standard_name"] == "sea_water_temperature" and r["long_name"] == "Sea Water Temperature"
    assert deep["gdac_update_date"] == datetime(2019, 3, 19, 2, 20, 1, tzinfo=timezone.utc)

    # the tail of fill values of a real SST file is NULL and stops the series' own span
    sst = rows[(T8S165E, "SST", 0)]
    assert sst["standard_name"] == "sea_surface_temperature"
    assert all(v is None for v in sst["vals"][103:]) and all(v is not None for v in sst["vals"][:103])
    assert sst["last_time"] == sst["times"][102] and sst["times"][-1] > sst["last_time"]
    assert sst["qc"][103:] == [9] * 47

    # plain array without QC: qc all NULL, depth from the scalar DEPTH, no unit rewriting
    irm = rows[(IRMINGSEA, "TEMP", 0)]
    assert irm["qc"] == [None] * 150 and irm["depth_m"] == 2965.0 and irm["units"] == "degree_Celsius"
    assert rows[(IRMINGSEA, "PSAL", 0)]["units"] == "psu"
    assert irm["vals"][0] == 1.3839 and irm["times"][0] == datetime(2003, 8, 30, 12, tzinfo=timezone.utc)
    # the garbage GDAC_UPDATE_DATE of this file ("31") is not stored as a stamp
    assert irm["gdac_update_date"] is None

    # MBARI R file: blank units stay NULL, "celsius" is not "converted", QC 2.0 -> 2
    assert rows[(MBARI, "TEMP", 4)]["units"] == "celsius" and rows[(MBARI, "TEMP", 4)]["depth_m"] == 55.0
    assert rows[(MBARI, "PSAL", 0)]["units"] is None
    assert {q for q in rows[(MBARI, "TEMP", 0)]["qc"] if q is not None} <= {2, 4}

    # PAP: two variables, ten depths each
    assert len([k for k in rows if k[0] == PAP2]) == 20

    # nothing in the table is an average: every stored value is on the wire (checked on one file)
    raw = (FIX / "OS_PAP-2_200406_D_CTD.ascii").read_text()
    wire = {float(t) for t in re.findall(r"-?\d+\.\d+(?:E[+-]?\d+)?", raw)}
    assert all(v in wire for k, r in rows.items() if k[0] == PAP2 for v in r["vals"] if v is not None)


async def test_the_read_log_records_each_file_including_the_one_with_nothing_to_sample(pool, reachable):
    await _fill(pool)
    log = await _fetched(pool)
    assert {f for f, r in log.items() if r["outcome"] == "ok"} == set(READ)
    assert log[BATS_BTL]["outcome"] == "empty" and log[BATS_BTL]["n_series"] == 0
    assert log[T0N140W]["n_series"] == 8 and log[T0N140W]["standard_names"] == ["sea_water_temperature"]
    assert log[T0N140W]["change_marker"] == "g:2019-03-19T02:20:01Z"
    # the file's own citation rides with its read-log row (for the endpoint to show)
    assert log[T0N140W]["citation"] == "These data were collected and made freely available by National Data Buoy Center (NDBC)."
    assert log[MBARI]["citation"] == ("These data were collected and made freely available by the "
                                      "Monterey Bay Aquarium Research Institute.")
    assert log[IRMINGSEA]["citation"].startswith("These data were collected and made freely available by the OceanSITES project")
    assert log[BATS_BTL]["citation"] is None and log[BATS_BTL]["detail"]
    assert log[IRMINGSEA]["change_marker"].startswith("s:3446748:")      # garbage stamps -> size + end time


# ── incremental ─────────────────────────────────────────────────────────────


async def test_a_second_run_reads_nothing_that_has_not_changed(pool, reachable):
    await _fill(pool)
    before = await _series(pool)
    server = FixtureServer()
    summary = await _run(server)
    assert summary["todo"] == 0 and summary["needed"] == 0 and summary["ok"] == 0
    assert server.requests == []
    assert await _series(pool) == before


async def test_a_republished_file_is_read_again_and_only_that_one(pool, reachable):
    await _fill(pool)
    before = await _series(pool)
    async with pool.acquire() as c:
        await c.execute("UPDATE oceansites_gdac_files SET gdac_update_date = '2026-09-30T00:00:00Z' WHERE file = $1", T8S165E)
    server = FixtureServer()
    summary = await _run(server)
    assert summary["ok"] == 1 and summary["todo"] == 1
    assert {r[1].split("/")[-1] for r in server.requests} == {Path(T8S165E).name + s for s in (".dds", ".das", ".ascii")}
    after = await _series(pool)
    assert after[(T8S165E, "SST", 0)]["gdac_update_date"] == datetime(2026, 9, 30, tzinfo=timezone.utc)
    assert after[(T8S165E, "SST", 0)]["vals"] == before[(T8S165E, "SST", 0)]["vals"]
    assert (await _fetched(pool))[T8S165E]["change_marker"] == "g:2026-09-30T00:00:00Z"


async def test_the_unsampleable_file_is_not_asked_again(pool, reachable):
    await _fill(pool)
    server = FixtureServer()
    await _run(server)
    assert all("BATSCR" not in r[1] for r in server.requests)


# ── refusals ────────────────────────────────────────────────────────────────


def _refusing(stem_part, status=404):
    good = FixtureServer()
    seen = []

    def handler(request):
        if stem_part in request.url.path:
            seen.append(request.url.path)
            return httpx.Response(status, text="Not Found")
        return good.handle(request)

    return handler, seen


async def _run_with(handler, **kw):
    from domains import oceansites_history as dom

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        return await dom.fetch_series(client=client, **kw)


@pytest.mark.parametrize("status", [400, 404])
async def test_a_refused_file_is_recorded_and_not_asked_again_until_its_marker_changes(pool, reachable, status):
    await _catalogue(pool, RECORDED, _one_station_each(READ))
    handler, seen = _refusing("IRMINGSEA", status)
    s1 = await _run_with(handler)
    assert (s1["ok"], s1["refused"], s1["failed"]) == (4, 1, 0)
    log = await _fetched(pool)
    assert log[IRMINGSEA]["outcome"] == "refused" and f"HTTP {status}" in log[IRMINGSEA]["detail"]
    assert log[IRMINGSEA]["change_marker"].startswith("s:3446748:") and log[IRMINGSEA]["n_series"] == 0
    assert IRMINGSEA not in {k[0] for k in await _series(pool)}
    assert len(seen) == 1                                           # one request: 4xx is not retried

    handler2, seen2 = _refusing("IRMINGSEA", status)
    s2 = await _run_with(handler2)
    assert s2["todo"] == 0 and seen2 == []                          # settled: not asked again

    async with pool.acquire() as c:                                  # the GDAC republishes it
        await c.execute("UPDATE oceansites_gdac_files SET size_bytes = size_bytes + 1 WHERE file = $1", IRMINGSEA)
    handler3, seen3 = _refusing("IRMINGSEA", status)
    s3 = await _run_with(handler3)
    assert s3["todo"] == 1 and s3["refused"] == 1 and len(seen3) == 1

    s4 = await _run(FixtureServer())                                # republished AND now served
    assert s4["ok"] == 0 and s4["todo"] == 0                         # refused again is settled for this marker
    async with pool.acquire() as c:
        await c.execute("UPDATE oceansites_gdac_files SET size_bytes = size_bytes + 1 WHERE file = $1", IRMINGSEA)
    s5 = await _run(FixtureServer())
    assert s5["ok"] == 1 and (await _fetched(pool))[IRMINGSEA]["outcome"] == "ok"
    assert (IRMINGSEA, "TEMP", 0) in await _series(pool)


async def test_a_refusal_never_blanks_series_stored_before(pool, reachable):
    await _fill(pool)
    before = await _series(pool)
    async with pool.acquire() as c:
        await c.execute("UPDATE oceansites_gdac_files SET gdac_update_date = '2026-09-30T00:00:00Z' WHERE file = $1", T0N140W)
    handler, _ = _refusing("T0N140W", 404)
    s = await _run_with(handler)
    assert s["refused"] == 1
    assert await _series(pool) == before
    assert (await _fetched(pool))[T0N140W]["outcome"] == "refused"


# ── a republished file replaces what it answered for ───────────────────────


async def _republish(pool, file, stamp="2026-09-30T00:00:00Z"):
    async with pool.acquire() as c:
        await c.execute("UPDATE oceansites_gdac_files SET gdac_update_date = $2 WHERE file = $1",
                        file, datetime.fromisoformat(stamp.replace("Z", "+00:00")))


def _only_depth_index_zero(monkeypatch):
    """The re-read yields only the first level of the file (the others are now all fill,
    or the depth step moved): the real answer, trimmed after the real decode."""
    from ingestion import oceansites_opendap as od

    real = od.fetch_file_series

    async def trimmed(client, file, wanted):
        res = await real(client, file, wanted)
        res.series = [r for r in res.series if r.depth_index == 0]
        return res

    monkeypatch.setattr(od, "fetch_file_series", trimmed)


async def test_a_republished_file_leaves_no_stale_rows_of_the_levels_it_no_longer_yields(pool, reachable, monkeypatch):
    await _fill(pool)
    before = await _series(pool)
    tao_before = {k for k in before if k[0] == T0N140W}
    assert len(tao_before) == 8                                    # depths A (index 0) and B... (2..14)
    await _republish(pool, T0N140W)
    _only_depth_index_zero(monkeypatch)

    summary = await _run(FixtureServer())

    assert summary["ok"] == 1
    after = await _series(pool)
    assert {k for k in after if k[0] == T0N140W} == {(T0N140W, "TEMP", 0)}, "the other levels are gone"
    assert after[(T0N140W, "TEMP", 0)]["gdac_update_date"] == datetime(2026, 9, 30, tzinfo=timezone.utc)
    assert {k: v for k, v in after.items() if k[0] != T0N140W} == {k: v for k, v in before.items() if k[0] != T0N140W}
    assert (await _fetched(pool))[T0N140W]["n_series"] == 1


class _Boom(Exception):
    pass


@pytest.mark.parametrize("how", ["503", "unsupported", "decode-surprise", "refused"])
async def test_a_re_read_that_fails_or_is_refused_deletes_nothing(pool, reachable, monkeypatch, how):
    from ingestion import oceansites_opendap as od

    await _fill(pool)
    before = await _series(pool)
    await _republish(pool, T0N140W)
    if how == "503":
        summary = await _run(FixtureServer(status=503))
        assert summary["failed"] == 1
    else:
        exc = {"unsupported": od.UnsupportedFile("now nothing sampleable"),
               "decode-surprise": _Boom("parser surprise"),
               "refused": od.OpendapError("rejected", "HTTP 404")}[how]

        async def failing(client, file, wanted):
            raise exc

        monkeypatch.setattr(od, "fetch_file_series", failing)
        summary = await _run(FixtureServer())
        assert summary["failed"] + summary["empty"] + summary["refused"] == 1

    assert await _series(pool) == before, "an outage, a refusal or an unreadable file must never blank stored rows"


async def test_a_variable_the_server_refused_on_the_re_read_keeps_its_rows(pool, reachable):
    """PAP-2 has TEMP and PSAL. On the re-read the server refuses PSAL (and the combined
    request): TEMP is replaced, PSAL says nothing and stays."""
    import urllib.parse

    await _catalogue(pool, RECORDED, _one_station_each([PAP2]))
    await _run(FixtureServer())
    before = await _series(pool)
    psal_before = {k: v for k, v in before.items() if k[1] == "PSAL"}
    assert psal_before and {k[1] for k in before} == {"TEMP", "PSAL"}
    await _republish(pool, PAP2)

    good = FixtureServer(reject_multi_variable=True)

    def handler(request):
        q = urllib.parse.unquote(request.url.query.decode())
        if ".ascii" in request.url.path and "PSAL" in q and "TEMP" not in q:
            return httpx.Response(400, text="Error { message = \"refused\"; };")
        return good.handle(request)

    summary = await _run_with(handler)

    assert summary["ok"] == 1
    after = await _series(pool)
    assert {k: v for k, v in after.items() if k[1] == "PSAL"} == psal_before
    temp_after = [v for k, v in after.items() if k[1] == "TEMP"]
    assert temp_after and all(v["gdac_update_date"] == datetime(2026, 9, 30, tzinfo=timezone.utc) for v in temp_after)


async def test_a_variable_read_but_entirely_fill_replaces_its_old_rows_with_nothing(pool, reachable, monkeypatch):
    """The server ANSWERED, and the answer holds no real sample: that is an answer, not a failure."""
    await _fill(pool)
    await _republish(pool, T8S165E)
    from ingestion import oceansites_opendap as od

    real = od.fetch_file_series

    async def all_fill(client, file, wanted):
        res = await real(client, file, wanted)
        res.series = []
        return res

    monkeypatch.setattr(od, "fetch_file_series", all_fill)
    await _run(FixtureServer())

    assert not [k for k in await _series(pool) if k[0] == T8S165E]
    assert (await _fetched(pool))[T8S165E]["outcome"] == "ok"


# ── packed variables ────────────────────────────────────────────────────────


async def test_a_packed_variable_is_not_stored_and_the_run_and_the_log_say_so(pool, reachable):
    # ⚠️ synthetic variant: the REAL PAP-2 .das with scale_factor/add_offset added to TEMP
    # (no recorded GDAC file is packed). See test_oceansites_opendap._packed_das.
    das = (FIX / "OS_PAP-2_200406_D_CTD.das").read_text(encoding="latin-1")
    das = das.replace("    TEMP {\n", "    TEMP {\n        Float32 scale_factor 0.001;\n        Float32 add_offset 20.0;\n", 1)
    good = FixtureServer()

    def handler(request):
        if request.url.path.endswith("PAP-2_200406_D_CTD.nc.das"):
            return httpx.Response(200, content=das.encode("latin-1"))
        return good.handle(request)

    await _catalogue(pool, RECORDED, _one_station_each([PAP2]))
    summary = await _run_with(handler)

    assert summary["ok"] == 1 and summary["packed_skipped"] == 1
    assert {k[1] for k in await _series(pool)} == {"PSAL"}, "TEMP would have been stored as raw packed numbers"
    log = (await _fetched(pool))[PAP2]
    assert log["outcome"] == "ok" and "TEMP" in log["detail"] and "packed" in log["detail"]


@pytest.mark.parametrize("status", [503, 500, 502, 429])
async def test_5xx_and_429_are_transient_never_recorded_as_refused(pool, reachable, status):
    await _catalogue(pool, RECORDED, _one_station_each(READ))
    handler, seen = _refusing("IRMINGSEA", status)
    s1 = await _run_with(handler)
    assert (s1["ok"], s1["refused"], s1["failed"], s1["failed_unavailable"]) == (4, 0, 1, 1)
    assert IRMINGSEA not in await _fetched(pool)                    # no entry: the file stays due
    handler2, seen2 = _refusing("IRMINGSEA", status)
    s2 = await _run_with(handler2)
    assert s2["todo"] == 1 and s2["failed_unavailable"] == 1 and seen2   # asked again next run
    s3 = await _run(FixtureServer())
    assert s3["ok"] == 1 and (await _fetched(pool))[IRMINGSEA]["outcome"] == "ok"


async def test_a_timeout_is_transient_not_refused(pool, reachable):
    await _catalogue(pool, RECORDED, _one_station_each([IRMINGSEA]))

    def handler(request):
        raise httpx.ConnectTimeout("slow", request=request)

    s = await _run_with(handler)
    assert s["failed_unavailable"] == 1 and s["refused"] == 0 and await _fetched(pool) == {}


# ── budget ──────────────────────────────────────────────────────────────────


async def test_the_per_run_budget_is_honoured_and_the_remainder_is_carried_over(pool, reachable):
    await _catalogue(pool, RECORDED, _one_station_each(SAMPLEABLE))
    s1 = await _run(FixtureServer(), max_files=2)
    assert (s1["todo"], s1["ok"] + s1["empty"], s1["needed"], s1["remaining"]) == (2, 2, 6, 4)
    assert len(await _fetched(pool)) == 2
    s2 = await _run(FixtureServer(), max_files=2)
    assert s2["needed"] == 4 and s2["remaining"] == 2 and len(await _fetched(pool)) == 4
    s3 = await _run(FixtureServer(), max_files=2)
    assert s3["remaining"] == 0 and len(await _fetched(pool)) == 6
    assert (await _run(FixtureServer(), max_files=2))["needed"] == 0


def test_budget_env_var_default_and_overrides(monkeypatch):
    from domains import oceansites_history as dom

    monkeypatch.delenv("OCEANSITES_HISTORY_MAX_FILES_PER_RUN", raising=False)
    assert dom.max_files_per_run() == 6000
    monkeypatch.setenv("OCEANSITES_HISTORY_MAX_FILES_PER_RUN", "40")
    assert dom.max_files_per_run() == 40
    for junk in ("", "abc", "0", "-5"):
        monkeypatch.setenv("OCEANSITES_HISTORY_MAX_FILES_PER_RUN", junk)
        assert dom.max_files_per_run() == 6000


async def test_only_linked_files_are_read(pool, reachable):
    await _catalogue(pool, RECORDED, {"S1": [T0N140W]})          # the other 7 catalogue rows are unlinked
    server = FixtureServer()
    summary = await _run(server)
    assert summary["ok"] == 1 and {r[1].split("/")[-2] for r in server.requests} == {"T0N140W"}


# ── a server that cannot answer ─────────────────────────────────────────────


async def test_unreachable_server_reads_nothing_and_touches_nothing(pool, reachable):
    await _fill(pool)
    series_before, log_before = await _series(pool), await _fetched(pool)
    async with pool.acquire() as c:   # make every file look changed so a run WOULD want to read them
        await c.execute("UPDATE oceansites_gdac_files SET gdac_update_date = '2026-09-30T00:00:00Z'")
    reachable["up"] = False
    server = FixtureServer(status=503)
    assert await _run(server) is None
    assert server.requests == []
    assert await _series(pool) == series_before and await _fetched(pool) == log_before


async def test_a_503_during_the_run_blanks_nothing_and_writes_no_log_entry(pool, reachable):
    await _fill(pool)
    series_before, log_before = await _series(pool), await _fetched(pool)
    async with pool.acquire() as c:
        await c.execute("UPDATE oceansites_gdac_files SET gdac_update_date = '2026-09-30T00:00:00Z' WHERE file = ANY($1)", READ)
    summary = await _run(FixtureServer(status=503))               # the probe passed, then the server fell over
    assert summary["failed"] == 5 and summary["failed_unavailable"] == 5 and summary["ok"] == 0
    assert await _series(pool) == series_before                   # no value blanked, no row removed
    assert await _fetched(pool) == log_before                     # and the files stay due: retried next run
    summary = await _run(FixtureServer())
    assert summary["ok"] == 5                                     # ... and they are, once the server is back


async def test_one_failing_file_is_counted_and_skipped_while_the_rest_are_stored(pool, reachable):
    await _catalogue(pool, RECORDED, _one_station_each(READ))
    good = FixtureServer()

    def handler(request):
        if "IRMINGSEA" in request.url.path:
            return httpx.Response(503)
        return good.handle(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        from domains import oceansites_history as dom
        summary = await dom.fetch_series(client=client)
    assert (summary["ok"], summary["failed"], summary["failed_unavailable"]) == (4, 1, 1)
    files = {k[0] for k in await _series(pool)}
    assert files == set(READ) - {IRMINGSEA}
    assert IRMINGSEA not in await _fetched(pool)


async def test_a_server_that_keeps_failing_ends_the_run_instead_of_hammering(pool, reachable):
    await _catalogue(pool, TAO_DIR, {"T": _tao_files()})
    server = FixtureServer(status=503)
    summary = await _run(server)
    assert summary["aborted"] and summary["failed"] >= 10
    assert summary["todo"] > 40 and summary["failed"] < summary["todo"]       # most of the list was never tried
    assert len(server.requests) <= 2 * (10 + 4)
    assert await _series(pool) == {} and await _fetched(pool) == {}


async def test_concurrency_never_exceeds_four(pool, reachable):
    await _catalogue(pool, TAO_DIR, {"T": _tao_files()})
    peak = {"now": 0, "max": 0}

    async def handler(request):
        peak["now"] += 1
        peak["max"] = max(peak["max"], peak["now"])
        await asyncio.sleep(0.005)
        peak["now"] -= 1
        return httpx.Response(404)           # files this fixture set does not hold: refused, counted

    from domains import oceansites_history as dom
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        summary = await dom.fetch_series(client=client, max_files=60)
    assert summary["todo"] == 60 and summary["refused"] == 60 and summary["failed"] == 0
    assert 2 <= peak["max"] <= 4


# ── the sync wires it in ────────────────────────────────────────────────────


async def test_the_sync_runs_the_series_step_and_survives_its_failure(pool, reachable, monkeypatch):
    from domains import oceansites_history as dom
    from ingestion import oceansites_history as ingest

    text = (FIX.parent / "oceansites_index_sample.txt").read_text(encoding="utf-8")

    async def fake_index(*a, **k):
        return text

    monkeypatch.setattr(ingest, "fetch_index", fake_index)
    called = []

    async def boom(*a, **k):
        called.append(1)
        raise RuntimeError("series step blew up")

    monkeypatch.setattr(dom, "fetch_series", boom)

    async def no_adc(*a, **k):
        return None                      # the ADC step has its own tests; no network here

    monkeypatch.setattr(dom, "refresh_adc", no_adc)
    linked = await dom.sync_oceansites_history()
    assert called == [1]
    assert linked == 0                   # no stations in this DB; the point is that the run returned
    async with pool.acquire() as c:
        assert await c.fetchval("SELECT COUNT(*) FROM oceansites_gdac_files") > 0
        row = await c.fetchrow("SELECT * FROM sync_log WHERE source = 'oceansites-history'")
    assert row["skipped_reason"] is None and row["last_synced_at"] is not None
