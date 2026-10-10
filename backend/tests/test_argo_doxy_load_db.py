# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""The loader against the real fixture, with the network replaced by local file copies."""
import gzip
import pathlib
import shutil

import numpy as np
import pytest

from ingestion import argo_doxy as L
from ingestion import argo_doxy_rules as r
from plankton_helpers import conn, needs_db  # noqa: F401
from schema.argo_doxy import ensure_argo_doxy

FIX = pathlib.Path(__file__).parent / "fixtures" / "argo_doxy"
INDEX_TXT = (FIX / "argo_synthetic-profile_index.excerpt.txt").read_text()


def _gz(text=INDEX_TXT) -> bytes:
    return gzip.compress(text.encode())


def _fetch_sprof(dac, wmo, dest):
    shutil.copy(FIX / f"{dac}_{wmo}_Sprof.nc", dest)
    return dest.stat().st_size


def _bump(text, needle, stamp="20991231000000"):
    """The same index with a newer date_update on every data line containing `needle`."""
    out = []
    for ln in text.splitlines(True):
        if needle in ln and not ln.startswith(("#", "file,")):
            parts = ln.rstrip("\n").split(",")
            parts[9] = stamp
            ln = ",".join(parts) + "\n"
        out.append(ln)
    return "".join(out)


async def _support(conn):
    await conn.execute("""CREATE TABLE IF NOT EXISTS sync_log (source text PRIMARY KEY,
        last_synced_at timestamptz, records_added int NOT NULL DEFAULT 0, total_records int NOT NULL DEFAULT 0,
        skipped_reason text, skipped_at timestamptz)""")
    await conn.execute("DROP TABLE IF EXISTS argo_doxy_profiles, argo_doxy_empty, argo_doxy_source CASCADE")
    await ensure_argo_doxy(conn)


@pytest.fixture(autouse=True)
def _scratch(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "SCRATCH_DIR", tmp_path / "scratch")
    # the developer's disk must not decide the outcome; the disk test passes its own reading explicitly
    monkeypatch.setattr(L, "_disk_used_fraction", lambda: 0.1)


def test_parse_index_counts_and_header_gate():
    rows, rejects, latest, untrusted = L.parse_index(_gz())
    assert len(rows) == 14 and sum(rejects.values()) == 0 and latest is not None
    with pytest.raises(ValueError):
        L.parse_index(_gz(INDEX_TXT.replace("date_update", "date_updated")))


def test_duplicate_keys_in_the_index_are_both_rejected():
    line = next(ln for ln in INDEX_TXT.splitlines() if "SD1900722_001.nc" in ln)
    rows, rejects, _, untrusted = L.parse_index(_gz(INDEX_TXT + line + "\n"))
    assert "aoml_1900722_001" not in rows and rejects["index_duplicate"] == 2
    assert untrusted == {"aoml_1900722_001"}


@needs_db
async def test_first_run_stores_the_fixture_with_the_written_arithmetic(conn):
    await _support(conn)
    out = await L.sync_argo_doxy(fetch_index=_gz, fetch_sprof=_fetch_sprof)
    assert out["outcome"] == "updated"
    n = await conn.fetchval("SELECT count(*) FROM argo_doxy_profiles")
    # 14 index rows - 1 profile without any DOXY value (aoml_5904670_038)
    assert n == 13 and out["rejects"]["no_doxy_values"] == 1
    drawn = await conn.fetchval("SELECT count(*) FROM argo_doxy_profiles WHERE drawable")
    # not drawn (5): aoml_1902751_001 + kiost_2900791_053 (R mode), coriolis_3902120_001D (no good level),
    # aoml_5906436_112 (position 9), coriolis_6901510_006 (position 4)
    assert drawn == 8
    s = await conn.fetchrow("SELECT * FROM argo_doxy_source")
    assert s["n_profiles"] == 13 and s["n_drawable"] == drawn and s["n_index_doxy"] == 14
    assert s["loaded_at"] is not None and s["last_complete_at"] is not None and s["pending_floats"] == 0
    assert not list(L.SCRATCH_DIR.glob("*.nc"))                                 # scratch cleaned


@needs_db
async def test_a_second_run_with_the_same_index_downloads_nothing(conn):
    await _support(conn)
    await L.sync_argo_doxy(fetch_index=_gz, fetch_sprof=_fetch_sprof)

    def boom(*a):
        raise AssertionError("no Sprof download when nothing changed")
    out = await L.sync_argo_doxy(fetch_index=_gz, fetch_sprof=boom)
    assert out["outcome"] == "unchanged" and out["floats_planned"] == 0


@needs_db
async def test_sr_to_sd_rename_updates_one_row(conn):
    await _support(conn)
    sr = INDEX_TXT.replace("SD1900722_001.nc", "SR1900722_001.nc")
    await L.sync_argo_doxy(fetch_index=lambda: _gz(sr), fetch_sprof=_fetch_sprof)
    newer = _bump(INDEX_TXT, "SD1900722_001.nc")                           # the SD line, a newer date_update
    await L.sync_argo_doxy(fetch_index=lambda: _gz(newer), fetch_sprof=_fetch_sprof)
    rows = await conn.fetch("SELECT gdac_file FROM argo_doxy_profiles WHERE profile_key='aoml_1900722_001'")
    assert len(rows) == 1 and rows[0]["gdac_file"].endswith("SD1900722_001.nc")


@needs_db
async def test_a_float_whose_sprof_fails_keeps_its_rows(conn):
    """Failure mode: refresh blanking live rows."""
    await _support(conn)
    await L.sync_argo_doxy(fetch_index=_gz, fetch_sprof=_fetch_sprof)
    before = await conn.fetch("SELECT profile_key, doxy_adj FROM argo_doxy_profiles WHERE platform_number='3902120'")
    bumped = _bump(INDEX_TXT, "/3902120/")

    def flaky(dac, wmo, dest):
        if wmo == "3902120":
            raise TimeoutError("GDAC timed out")
        return _fetch_sprof(dac, wmo, dest)
    out = await L.sync_argo_doxy(fetch_index=lambda: _gz(bumped), fetch_sprof=flaky)
    after = await conn.fetch("SELECT profile_key, doxy_adj FROM argo_doxy_profiles WHERE platform_number='3902120'")
    assert before == after and len(after) == 2
    assert "coriolis/3902120" in out["failed_floats"]
    rej = await conn.fetchval("SELECT last_rejects FROM argo_doxy_source")
    assert "coriolis/3902120" in rej


@needs_db
async def test_a_truncated_sprof_is_a_float_failure_not_a_crash(conn):
    await _support(conn)

    def truncated(dac, wmo, dest):
        data = (FIX / f"{dac}_{wmo}_Sprof.nc").read_bytes()
        dest.write_bytes(data[: len(data) // 3] if wmo == "1900722" else data)
        return dest.stat().st_size
    out = await L.sync_argo_doxy(fetch_index=_gz, fetch_sprof=truncated)
    assert out["outcome"] == "updated" and "aoml/1900722" in out["failed_floats"]
    assert await conn.fetchval("SELECT count(*) FROM argo_doxy_profiles WHERE platform_number='1900722'") == 0


@needs_db
async def test_too_many_failed_floats_make_the_run_an_error(conn, monkeypatch):
    """Failures spread over the run that are NOT the network (corrupt files) keep the error outcome and its back-off."""
    await _support(conn)
    monkeypatch.setattr(L, "FLOAT_FAILURE_LIMIT_MIN", 1)

    def corrupt(dac, wmo, dest):
        dest.write_bytes(b"not a netcdf file")
        return dest.stat().st_size
    out = await L.sync_argo_doxy(fetch_index=_gz, fetch_sprof=corrupt)
    assert out["outcome"] == "error"
    assert "error" in (await conn.fetchval("SELECT skipped_reason FROM sync_log WHERE source='argo-doxy'") or "")


def _down(exc, calls):
    def fetch(dac, wmo, dest):
        calls.append((dac, wmo))
        raise exc
    return fetch


@needs_db
async def test_consecutive_network_failures_stop_the_run_as_unreachable_and_leave_every_float_pending(conn):
    """A short GDAC outage must not become `error` + a 7-day back-off, nor be hammered once per remaining float."""
    await _support(conn)
    calls: list = []
    out = await L.sync_argo_doxy(fetch_index=_gz, fetch_sprof=_down(ConnectionError("GDAC down"), calls))
    assert out["outcome"] == r.UNREACHABLE_OUTCOME and r.UNREACHABLE_OUTCOME not in r.FAILED_OUTCOMES
    assert len(calls) == r.FLOAT_FAILURE_STREAK < out["floats_planned"]            # it stopped hammering
    assert out["floats_done"] == 0 and out["pending"] == out["floats_planned"]     # the failed streak stays pending
    s = await conn.fetchrow("SELECT pending_floats, last_complete_at, loaded_at FROM argo_doxy_source")
    assert s["pending_floats"] == out["floats_planned"] and s["last_complete_at"] is None
    reason = await conn.fetchval("SELECT skipped_reason FROM sync_log WHERE source='argo-doxy'")
    assert reason.startswith(r.UNREACHABLE_PREFIX) and r.UNREACHABLE_PREFIX in [
        p for p in r.TRANSIENT_PREFIXES if reason.startswith(p)]


@needs_db
@pytest.mark.parametrize("code, outcome", [(503, r.UNREACHABLE_OUTCOME), (404, "error")])
async def test_a_5xx_is_the_gdac_down_but_a_404_is_a_bad_float(conn, code, outcome):
    import urllib.error
    await _support(conn)
    exc = urllib.error.HTTPError("https://x/y.nc", code, "x", {}, None)
    out = await L.sync_argo_doxy(fetch_index=_gz, fetch_sprof=_down(exc, []))
    assert out["outcome"] == outcome


@needs_db
async def test_failures_that_are_not_consecutive_do_not_trip_the_streak(conn, monkeypatch):
    await _support(conn)
    monkeypatch.setattr(L, "FLOAT_FAILURE_STREAK", 2)
    calls: list = []

    def every_other(dac, wmo, dest):
        calls.append(wmo)
        if len(calls) % 2:
            raise ConnectionError("one dropped connection")
        return _fetch_sprof(dac, wmo, dest)
    out = await L.sync_argo_doxy(fetch_index=_gz, fetch_sprof=every_other)
    assert out["outcome"] == "updated" and len(calls) == out["floats_planned"] and len(out["failed_floats"]) >= 2


def test_which_float_failures_say_the_gdac_is_down():
    import http.client
    import urllib.error
    http_err = lambda c: urllib.error.HTTPError("https://x", c, "m", {}, None)  # noqa: E731
    down = [urllib.error.URLError("no route"), TimeoutError(), ConnectionResetError(), http_err(500), http_err(503),
            http.client.IncompleteRead(b"x"), L.FetchDeadline("slow")]
    fine = [http_err(404), http_err(403), L.FloatFailed("too big"), ValueError("bad shape"), OSError(28, "no space")]
    assert all(L.is_network_failure(e) for e in down) and not any(L.is_network_failure(e) for e in fine)


def _serve(handler_body, length=100000):
    """A real HTTP server on localhost (one thread); handler_body(wfile) writes the response body."""
    import http.server
    import threading

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", str(length))
            self.end_headers()
            try:
                handler_body(self.wfile)
            except OSError:                                  # the client gave up: exactly what the test wants
                pass

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_a_trickling_download_is_bounded_per_file_not_only_per_read(tmp_path, monkeypatch):
    """A REAL socket trickling 1 byte every 0.3 s: every read returns well inside HTTP_TIMEOUT_S, so the socket timeout
    never fires. HTTPResponse.read(n) would block until n bytes arrive; the per-file deadline must still end it."""
    import time

    def trickle(w):
        for _ in range(40):                                  # 12 s of trickle, far past the deadline
            w.write(b"x")
            w.flush()
            time.sleep(0.3)
    srv = _serve(trickle)
    try:
        monkeypatch.setattr(L, "sprof_url", lambda dac, wmo: f"http://127.0.0.1:{srv.server_port}/x.nc")
        monkeypatch.setattr(L, "FETCH_DEADLINE_S", 1.5)
        monkeypatch.setattr(L, "HTTP_TIMEOUT_S", 1.0)
        dest = tmp_path / "x.nc"
        t0 = time.monotonic()
        with pytest.raises(L.FetchDeadline) as ei:
            L.fetch_sprof("aoml", "1900722", dest)
        took = time.monotonic() - t0
        assert took < L.FETCH_DEADLINE_S + L.HTTP_TIMEOUT_S, took        # deadline + one socket timeout, not 12 s
        assert L.is_network_failure(ei.value) and 0 < dest.stat().st_size < 40

        monkeypatch.setattr(L, "FETCH_DEADLINE_S", 20)
        for length, sent, outcome in ((2048, 2048, 2048), (100000, 2048, "cut")):
            quick = _serve(lambda w, sent=sent: w.write(b"y" * sent), length)
            try:
                monkeypatch.setattr(L, "sprof_url", lambda dac, wmo, q=quick: f"http://127.0.0.1:{q.server_port}/x.nc")
                if outcome == "cut":                         # shorter than its Content-Length: a network failure
                    with pytest.raises(Exception) as cut:
                        L.fetch_sprof("aoml", "1900722", dest)
                    assert L.is_network_failure(cut.value)
                else:                                        # a quick, complete file still arrives
                    assert L.fetch_sprof("aoml", "1900722", dest) == outcome
            finally:
                quick.shutdown()
    finally:
        srv.shutdown()


@needs_db
async def test_an_index_that_shrank_by_more_than_10_percent_blocks_and_deletes_nothing(conn):
    await _support(conn)
    await L.sync_argo_doxy(fetch_index=_gz, fetch_sprof=_fetch_sprof)
    header = [ln for ln in INDEX_TXT.splitlines(True) if ln.startswith(("#", "file,"))]
    body = [ln for ln in INDEX_TXT.splitlines(True) if not ln.startswith(("#", "file,"))]
    out = await L.sync_argo_doxy(fetch_index=lambda: _gz("".join(header + body[:5])), fetch_sprof=_fetch_sprof)
    assert out["outcome"] == "blocked"
    assert await conn.fetchval("SELECT count(*) FROM argo_doxy_profiles") == 13


@needs_db
async def test_a_profile_the_index_drops_is_deleted_with_its_float_untouched_otherwise(conn):
    await _support(conn)
    await L.sync_argo_doxy(fetch_index=_gz, fetch_sprof=_fetch_sprof)
    without = "".join(ln for ln in INDEX_TXT.splitlines(True) if "SD1900722_002.nc" not in ln)
    out = await L.sync_argo_doxy(fetch_index=lambda: _gz(without), fetch_sprof=_fetch_sprof)
    assert out["deleted"] == 1
    keys = {x["profile_key"] for x in await conn.fetch("SELECT profile_key FROM argo_doxy_profiles")}
    assert "aoml_1900722_002" not in keys and "aoml_1900722_001" in keys


@needs_db
async def test_the_budget_leaves_floats_pending_not_failed(conn):
    await _support(conn)
    ticks = iter(range(0, 10**6, 1000))
    out = await L.sync_argo_doxy(fetch_index=_gz, fetch_sprof=_fetch_sprof, budget_s=2500, clock=lambda: next(ticks))
    assert out["outcome"] == "partial" and out["floats_done"] < out["floats_planned"]
    s = await conn.fetchrow("SELECT pending_floats, last_complete_at FROM argo_doxy_source")
    assert s["pending_floats"] == out["floats_planned"] - out["floats_done"] and s["last_complete_at"] is None


@needs_db
async def test_a_disk_above_the_stop_line_ends_the_run_between_floats(conn):
    await _support(conn)
    out = await L.sync_argo_doxy(fetch_index=_gz, fetch_sprof=_fetch_sprof, disk_used=lambda: 0.9)
    assert out["outcome"] == "disk" and out["floats_done"] == 0


@needs_db
async def test_argo_profiles_rows_are_untouched_by_a_doxy_import(conn):
    """Failure mode: the existing Argo layer broken by the storage extension. The rows checked are ones this test
    inserts itself under the fixture's own profile ids, so a concurrent session writing other argo_profiles rows
    on the shared test database cannot make it flap."""
    from schema.core import ensure_core
    await ensure_core(conn)
    await _support(conn)
    ids = ["1900722_001", "1900722_002", "5900421_005"]
    await conn.execute("DELETE FROM argo_profiles WHERE profile_id = ANY($1::text[])", ids)
    await conn.execute("INSERT INTO argo_profiles (profile_id, platform_id, profile_date, oxygen_umol_kg, geom) "
                       "SELECT i, split_part(i, '_', 1), '2006-10-22T02:16:24Z', 250.0 + length(i), "
                       "ST_SetSRID(ST_MakePoint(73.4, -40.3), 4326) FROM unnest($1::text[]) i", ids)
    q = "SELECT md5(string_agg(t::text, '' ORDER BY profile_id)), count(*) FROM argo_profiles t WHERE profile_id = ANY($1::text[])"
    before = tuple(await conn.fetchrow(q, ids))
    assert before[1] == 3
    out = await L.sync_argo_doxy(fetch_index=_gz, fetch_sprof=_fetch_sprof)
    assert out["outcome"] == "updated"
    assert await conn.fetchval("SELECT count(*) FROM argo_doxy_profiles WHERE argo_profile_id = ANY($1::text[])",
                               ids) == 3                                       # the same ids really were imported
    assert tuple(await conn.fetchrow(q, ids)) == before


# ── Carry-overs from the group-1 review: duplicates inside a Sprof, a corrupt shape, a lost connection ──────────
def _rewrite_sprof(src: pathlib.Path, dst: pathlib.Path, order, mutate=None, drop=()):
    """Copy a REAL fixture Sprof with N_PROF re-ordered/duplicated (`order` = source profile indices);
    mutate(name, array, position) may alter the copy of one profile; `drop` omits variables."""
    import netCDF4
    with netCDF4.Dataset(src) as s, netCDF4.Dataset(dst, "w", format=s.data_model) as d:
        s.set_auto_mask(False)
        for name, dim in s.dimensions.items():
            d.createDimension(name, len(order) if name == "N_PROF" else len(dim))
        for name, v in s.variables.items():
            if name in drop:
                continue
            fill = v.getncattr("_FillValue") if "_FillValue" in v.ncattrs() else None
            o = d.createVariable(name, v.dtype, v.dimensions, fill_value=fill)
            o.setncatts({a: v.getncattr(a) for a in v.ncattrs() if a != "_FillValue"})
            data = v[:]
            if "N_PROF" in v.dimensions:
                data = data[order]
                if mutate is not None:
                    data = data.copy()
                    for pos in range(len(order)):
                        data[pos] = mutate(name, data[pos], pos)
            o[:] = data
        d.setncatts({a: s.getncattr(a) for a in s.ncattrs()})


def _dup_fetch(tmp_path, mutate, order=(0, 1, 0)):
    """aoml/1900722 holds cycles 1 and 2 (both 'A'); `order` makes the file list cycle 1 twice."""
    def fetch(dac, wmo, dest):
        if wmo != "1900722":
            return _fetch_sprof(dac, wmo, dest)
        _rewrite_sprof(FIX / "aoml_1900722_Sprof.nc", dest, list(order), mutate)
        return dest.stat().st_size
    return fetch




@needs_db
@pytest.mark.parametrize("spoiled_entry", [0, 2])
async def test_a_duplicate_cycle_in_one_sprof_is_counted_and_the_better_profile_kept(conn, tmp_path, spoiled_entry):
    """The file lists cycle 1, cycle 2, cycle 1 again; one of the two cycle-1 entries has no good level. The one with
    the good levels survives whether it is the first or the last entry (so neither 'first wins' nor 'last wins')."""
    await _support(conn)

    def spoil(name, arr, pos):
        return np.full_like(arr, b"4") if (pos == spoiled_entry and name == "DOXY_ADJUSTED_QC") else arr
    out = await L.sync_argo_doxy(fetch_index=_gz, fetch_sprof=_dup_fetch(tmp_path, spoil))
    assert out["outcome"] == "updated" and out["rejects"]["sprof_duplicate"] == 1
    row = await conn.fetchrow("SELECT n_good, drawable FROM argo_doxy_profiles WHERE profile_key='aoml_1900722_001'")
    assert row["n_good"] == 70 and row["drawable"]
    assert await conn.fetchval("SELECT count(*) FROM argo_doxy_profiles WHERE platform_number='1900722'") == 2
    assert "sprof_duplicate" in await conn.fetchval("SELECT last_rejects FROM argo_doxy_source")


@needs_db
async def test_identical_duplicates_keep_the_first_entry_of_the_file(conn, tmp_path):
    await _support(conn)
    out = await L.sync_argo_doxy(fetch_index=_gz, fetch_sprof=_dup_fetch(tmp_path, None))
    assert out["outcome"] == "updated" and out["rejects"]["sprof_duplicate"] == 1
    assert await conn.fetchval("SELECT count(*) FROM argo_doxy_profiles WHERE platform_number='1900722'") == 2


@needs_db
async def test_a_sprof_without_a_required_variable_is_a_float_failure(conn, tmp_path):
    await _support(conn)

    def broken(dac, wmo, dest):
        if wmo != "5900421":
            return _fetch_sprof(dac, wmo, dest)
        _rewrite_sprof(FIX / "aoml_5900421_Sprof.nc", dest, [0], drop=("DOXY_QC",))
        return dest.stat().st_size
    out = await L.sync_argo_doxy(fetch_index=_gz, fetch_sprof=broken)
    assert out["outcome"] == "updated" and list(out["failed_floats"]) == ["aoml/5900421"]
    assert "DOXY_QC" in out["failed_floats"]["aoml/5900421"]
    assert await conn.fetchval("SELECT count(*) FROM argo_doxy_profiles") == 12      # the other floats are stored


@needs_db
async def test_a_profile_array_of_the_wrong_shape_is_a_float_failure_not_a_crash(conn, tmp_path, monkeypatch):
    """An exception raised by the rules for one float (here: a profile dict the rules cannot read)."""
    await _support(conn)
    real = L.build_profile

    def boom(raw, row, upd):
        if row.wmo == "1901466":
            raise IndexError("shape")
        return real(raw, row, upd)
    monkeypatch.setattr(L, "build_profile", boom)
    out = await L.sync_argo_doxy(fetch_index=_gz, fetch_sprof=_fetch_sprof)
    assert out["outcome"] == "updated" and "aoml/1901466" in out["failed_floats"]
    assert await conn.fetchval("SELECT count(*) FROM argo_doxy_profiles") == 12


@needs_db
@pytest.mark.parametrize("kind", ["asyncpg", "socket-reset"])
async def test_a_lost_database_connection_ends_the_run_instead_of_failing_every_float(conn, monkeypatch, kind):
    """asyncpg's own connection errors, and a plain OSError from a socket that died (the connection reports closed)."""
    import asyncpg
    import db
    await _support(conn)

    class DyingConn:
        def __init__(self, c):
            self._c = c

        def __getattr__(self, name):
            return getattr(self._c, name)

        def is_closed(self):
            return kind == "socket-reset"

        async def executemany(self, *a, **k):
            if kind == "asyncpg":
                raise asyncpg.ConnectionDoesNotExistError("connection was closed in the middle of operation")
            raise ConnectionResetError("reset by peer")

    monkeypatch.setattr(db, "pool", type("P", (), {"acquire": lambda self: _Acq(DyingConn(conn))})())
    calls = []

    def counting(dac, wmo, dest):
        calls.append(wmo)
        return _fetch_sprof(dac, wmo, dest)
    out = await L.sync_argo_doxy(fetch_index=_gz, fetch_sprof=counting)
    assert out["outcome"] == "error" and out["error"].startswith(("ConnectionDoesNotExistError", "ConnectionLost"))
    assert len(calls) == 1                                # the first float ended the run; no more downloads
    assert not list(L.SCRATCH_DIR.glob("*.nc"))


class _Acq:
    def __init__(self, c):
        self._c = c

    async def __aenter__(self):
        return self._c

    async def __aexit__(self, *exc):
        return False


@needs_db
async def test_a_profile_without_doxy_values_is_remembered_not_redownloaded(conn):
    await _support(conn)
    await L.sync_argo_doxy(fetch_index=_gz, fetch_sprof=_fetch_sprof)
    assert [x["profile_key"] for x in await conn.fetch("SELECT profile_key FROM argo_doxy_empty")] == [
        "aoml_5904670_038"]
    without = "".join(ln for ln in INDEX_TXT.splitlines(True) if "SD5904670_038.nc" not in ln)
    out = await L.sync_argo_doxy(fetch_index=lambda: _gz(without), fetch_sprof=_fetch_sprof)
    assert out["floats_planned"] == 1 and out["outcome"] == "unchanged"                 # the float with a goner
    assert await conn.fetchval("SELECT count(*) FROM argo_doxy_empty") == 0
    assert await conn.fetchval("SELECT count(*) FROM argo_doxy_profiles") == 13


@needs_db
async def test_a_profile_that_stops_carrying_doxy_is_deleted_and_remembered(conn, tmp_path):
    await _support(conn)
    await L.sync_argo_doxy(fetch_index=_gz, fetch_sprof=_fetch_sprof)
    assert await conn.fetchval("SELECT count(*) FROM argo_doxy_profiles WHERE profile_key='aoml_1900722_001'") == 1

    def emptied(dac, wmo, dest):
        if wmo != "1900722":
            return _fetch_sprof(dac, wmo, dest)

        def blank(name, arr, pos):                     # cycle 1 loses every DOXY value (fill 99999)
            return np.full_like(arr, 99999.0) if pos == 0 and name in ("DOXY", "DOXY_ADJUSTED") else arr
        _rewrite_sprof(FIX / "aoml_1900722_Sprof.nc", dest, [0, 1], blank)
        return dest.stat().st_size
    out = await L.sync_argo_doxy(fetch_index=lambda: _gz(_bump(INDEX_TXT, "SD1900722_001.nc")), fetch_sprof=emptied)
    assert out["deleted"] == 1 and out["outcome"] == "updated"
    assert await conn.fetchval("SELECT count(*) FROM argo_doxy_profiles WHERE profile_key='aoml_1900722_001'") == 0
    assert await conn.fetchval("SELECT count(*) FROM argo_doxy_empty WHERE profile_key='aoml_1900722_001'") == 1


def _blanked(dacs, wmos=None):
    """A GDAC whose `dacs` (all their floats, or only `wmos`) reprocessed every file with all DOXY values blanked
    (fill 99999); everything else is intact."""
    import netCDF4

    def blank(name, arr, pos):
        return np.full_like(arr, 99999.0) if name in ("DOXY", "DOXY_ADJUSTED") else arr

    def fetch(dac, wmo, dest):
        if dac not in dacs or (wmos is not None and wmo not in wmos):
            return _fetch_sprof(dac, wmo, dest)
        src = FIX / f"{dac}_{wmo}_Sprof.nc"
        with netCDF4.Dataset(src) as d:
            n = len(d.dimensions["N_PROF"])
        _rewrite_sprof(src, dest, list(range(n)), blank)
        return dest.stat().st_size
    return fetch


@needs_db
async def test_a_whole_dac_whose_floats_turn_empty_keeps_its_live_rows_and_reports_the_held_count(conn):
    """Failure mode: a DAC reprocesses its files with blanked DOXY and the drawn rows are deleted float by float.
    aoml holds 6 drawn profiles + 1 marker: losing 6 is > 10 % of its keys, held exactly like a vanished profile."""
    await _first_run(conn, _padded())
    before = await conn.fetch("SELECT profile_key, doxy_adj FROM argo_doxy_profiles ORDER BY 1")
    changed = _bump(_padded(), "aoml/")
    out = await L.sync_argo_doxy(fetch_index=lambda: _gz(changed), fetch_sprof=_blanked({"aoml"}))
    assert out["deleted"] == 0 and out["outcome"] == "unchanged"
    assert await conn.fetch("SELECT profile_key, doxy_adj FROM argo_doxy_profiles ORDER BY 1") == before
    rej = await _rejects(conn)
    assert rej["empties_held"] == {"aoml": 6} and rej["deletions_held"] == {"aoml": 6}
    assert "deletions held (aoml: 6)" in await conn.fetchval("SELECT skipped_reason FROM sync_log WHERE source='argo-doxy'")
    # nothing was written for the held profiles: no marker, so the next run reads them again
    assert await conn.fetchval("SELECT count(*) FROM argo_doxy_empty WHERE profile_key LIKE 'aoml_%'") == 1       # the old 5904670_038
    s = await conn.fetchrow("SELECT rules_version, pending_floats FROM argo_doxy_source")
    out2 = await L.sync_argo_doxy(fetch_index=lambda: _gz(changed), fetch_sprof=_fetch_sprof)       # DAC fixed its files
    assert out2["written"] >= 1 and (await _rejects(conn)).get("empties_held") is None and s["pending_floats"] == 0


@needs_db
async def test_emptied_profiles_count_with_the_dacs_vanished_ones_and_above_the_global_ceiling(conn, monkeypatch):
    await _first_run(conn, _padded())
    # one vanished + one emptied profile of aoml: each alone is within DELETE_DAC_MIN (1) and is not an outage, but
    # together they are 2 of aoml's 7 keys: the vanished one is applied (planned first), the emptied one is held
    monkeypatch.setattr(L, "DELETE_DAC_MIN", 1)
    changed = _bump(_drop(_padded(), "SD5900421_005.nc"), "SD1900722_001.nc")
    out = await L.sync_argo_doxy(fetch_index=lambda: _gz(changed), fetch_sprof=_blanked({"aoml"}, wmos={"1900722"}))
    assert out["deleted"] == 1 and (await _rejects(conn))["deletions_held"] == {"aoml": 1}
    assert await conn.fetchval("SELECT count(*) FROM argo_doxy_profiles") == 12
    assert await conn.fetchval("SELECT count(*) FROM argo_doxy_profiles WHERE profile_key='aoml_1900722_001'") == 1
    await _first_run(conn, _padded())
    monkeypatch.setattr(L, "DELETE_DAC_MIN", 5)
    monkeypatch.setattr(L, "DELETE_ALL_FLOOR", 0)
    monkeypatch.setattr(L, "DELETE_ALL_FRAC", 0.0)
    out = await L.sync_argo_doxy(fetch_index=lambda: _gz(_bump(_padded(), "SD1900722_001.nc")),
                                 fetch_sprof=_blanked({"aoml"}))
    assert out["deleted"] == 0 and (await _rejects(conn))["empties_held"] == {"aoml": 1}
    assert await conn.fetchval("SELECT count(*) FROM argo_doxy_profiles WHERE profile_key='aoml_1900722_001'") == 1


@needs_db
async def test_a_database_error_in_one_dacs_emptied_batch_fails_that_batch_not_the_run(conn, monkeypatch):
    """The DAC-level transaction (delete the emptied rows + write their markers) can fail on its own, not only the
    per-float one. It rolls back whole: that DAC's rows stay, the failure is counted, and the next DAC is still judged."""
    await _first_run(conn, _padded())
    changed = _bump(_bump(_padded(), "SD1900722_001.nc"), "SD1902751_001.nc")     # aoml 1900722 and coriolis 1902751
    real, good = L._apply_empties, L.UPSERT_EMPTY_SQL

    async def failing_for_aoml(c, emptied):
        if not emptied[0][0].startswith("aoml_"):
            return await real(c, emptied)
        monkeypatch.setattr(L, "UPSERT_EMPTY_SQL", "SELECT 1/0 WHERE $1::text <> '' AND $2::timestamptz IS NOT NULL "
                                                   "AND $3::int IS NOT NULL")      # a real, non-connection DB error
        try:
            return await real(c, emptied)
        finally:
            monkeypatch.setattr(L, "UPSERT_EMPTY_SQL", good)
    monkeypatch.setattr(L, "_apply_empties", failing_for_aoml)
    blank = _blanked({"aoml", "coriolis"}, wmos={"1900722", "1902751"})
    out = await L.sync_argo_doxy(fetch_index=lambda: _gz(changed), fetch_sprof=blank)
    assert out["outcome"] == "updated"                                              # the run went on
    assert "DivisionByZero" in out["failed_floats"]["aoml/emptied"]
    assert (await _rejects(conn))["failed_emptied_profiles"] == 1
    live = "SELECT count(*) FROM argo_doxy_profiles WHERE profile_key"
    assert await conn.fetchval(f"{live} = 'aoml_1900722_001'") == 1                # rolled back whole: the row stays
    assert await conn.fetchval("SELECT count(*) FROM argo_doxy_empty WHERE profile_key = 'aoml_1900722_001'") == 0
    assert await conn.fetchval(f"{live} = 'coriolis_1902751_001'") == 0             # the next DAC was judged and applied
    assert await conn.fetchval("SELECT count(*) FROM argo_doxy_empty WHERE profile_key = 'coriolis_1902751_001'") == 1
    assert out["deleted"] == 1


@needs_db
async def test_a_dac_the_run_did_not_finish_is_not_judged_and_is_read_again_next_run(conn):
    """Emptied profiles are judged once their DAC is complete; a budget stop inside the DAC leaves them untouched."""
    await _first_run(conn, _padded())
    changed = _bump(_padded(), "aoml/")                       # all six aoml floats are re-read
    ticks = iter(range(0, 10**6, 1000))                       # two floats fit the 2500 s budget
    out = await L.sync_argo_doxy(fetch_index=lambda: _gz(changed), fetch_sprof=_blanked({"aoml"}, wmos={"1900722"}),
                                 budget_s=2500, clock=lambda: next(ticks))
    assert out["outcome"] == "partial" and out["pending"] > 0 and out["deleted"] == 0
    live = "SELECT count(*) FROM argo_doxy_profiles WHERE platform_number='1900722'"
    assert await conn.fetchval(live) == 2                     # emptied, not yet judged: still drawn
    assert await conn.fetchval("SELECT count(*) FROM argo_doxy_empty WHERE profile_key LIKE 'aoml_1900722_%'") == 0
    out = await L.sync_argo_doxy(fetch_index=lambda: _gz(changed), fetch_sprof=_blanked({"aoml"}, wmos={"1900722"}))
    assert out["outcome"] == "updated" and out["deleted"] == 2    # DAC complete: 2 of 7 is within the limits
    assert await conn.fetchval(live) == 0
    assert await conn.fetchval("SELECT count(*) FROM argo_doxy_empty WHERE profile_key LIKE 'aoml_1900722_%'") == 2


@needs_db
async def test_a_float_whose_database_write_fails_loses_nothing_not_even_its_deletions(conn, monkeypatch):
    """Failure mode: refresh blanking live rows. One float has a profile the index dropped (a DELETE) AND a changed
    profile whose upsert violates a CHECK: the delete must be rolled back with it."""
    await _support(conn)
    await L.sync_argo_doxy(fetch_index=_gz, fetch_sprof=_fetch_sprof)
    before = await conn.fetch("SELECT profile_key, gdac_date_update FROM argo_doxy_profiles "
                              "WHERE platform_number='1900722' ORDER BY 1")
    assert len(before) == 2
    # 002 leaves the index (-> DELETE), 001 changes (-> upsert) and its built row gets an impossible latitude
    changed = _bump("".join(ln for ln in INDEX_TXT.splitlines(True) if "SD1900722_002.nc" not in ln),
                    "SD1900722_001.nc")
    real = L.build_profile

    def impossible_latitude(raw, row, upd):
        p = real(raw, row, upd)
        if row.wmo == "1900722" and p is not None:
            p["lat"] = 123.0
        return p
    monkeypatch.setattr(L, "build_profile", impossible_latitude)
    out = await L.sync_argo_doxy(fetch_index=lambda: _gz(changed), fetch_sprof=_fetch_sprof)
    assert "aoml/1900722" in out["failed_floats"] and "CheckViolation" in out["failed_floats"]["aoml/1900722"]
    after = await conn.fetch("SELECT profile_key, gdac_date_update FROM argo_doxy_profiles "
                             "WHERE platform_number='1900722' ORDER BY 1")
    assert after == before and out["deleted"] == 0


# ── Fix round 1: deletions gated on the deletions, rules version, import weight, refresh request ──────────────────
def _padded(text=INDEX_TXT, n=200):
    """The fixture index plus n valid lines WITHOUT DOXY (other floats' profiles), so a single malformed line is
    well under the 1 % format-change limit and a deletion is a small share of the file."""
    extra = "".join(f"aoml/{4000000 + i}/profiles/SD{4000000 + i}_001.nc,20200101000000,1.0,2.0,A,846,AO,"
                    f"PRES TEMP PSAL,DDD,20220101000000\n" for i in range(n))
    return text + extra


def _drop(text, needle):
    return "".join(ln for ln in text.splitlines(True) if needle not in ln)


def _replace_line(text, needle, fn):
    return "".join(fn(ln) if needle in ln else ln for ln in text.splitlines(True))


async def _first_run(conn, text=None):
    await _support(conn)
    out = await L.sync_argo_doxy(fetch_index=lambda: _gz(text or INDEX_TXT), fetch_sprof=_fetch_sprof)
    assert out["outcome"] == "updated"
    return out


async def _rejects(conn):
    import json
    return json.loads(await conn.fetchval("SELECT last_rejects FROM argo_doxy_source"))


@needs_db
async def test_a_whole_small_dac_vanishing_from_the_index_keeps_its_rows_and_upserts_still_proceed(conn):
    await _first_run(conn, _padded())
    gone_dac = _drop(_padded(), "kiost/")
    changed = _bump(gone_dac, "SD1900722_001.nc")                  # an unrelated float changes in the same run
    out = await L.sync_argo_doxy(fetch_index=lambda: _gz(changed), fetch_sprof=_fetch_sprof)
    assert out["deleted"] == 0 and out["written"] >= 1
    assert await conn.fetchval("SELECT count(*) FROM argo_doxy_profiles WHERE dac='kiost'") == 1
    assert (await _rejects(conn))["deletions_held"] == {"kiost": 1}
    assert "deletions held (kiost: 1)" in await conn.fetchval("SELECT skipped_reason FROM sync_log WHERE source='argo-doxy'")


@needs_db
async def test_deletions_above_the_global_ceiling_are_all_held(conn, monkeypatch):
    await _first_run(conn, _padded())
    monkeypatch.setattr(L, "DELETE_ALL_FLOOR", 0)
    monkeypatch.setattr(L, "DELETE_ALL_FRAC", 0.0)
    out = await L.sync_argo_doxy(fetch_index=lambda: _gz(_drop(_padded(), "SD1900722_002.nc")),
                                 fetch_sprof=_fetch_sprof)
    assert out["deleted"] == 0 and (await _rejects(conn))["deletions_held"] == {"all": 1}
    assert await conn.fetchval("SELECT count(*) FROM argo_doxy_profiles") == 13


@needs_db
async def test_a_dac_losing_more_than_a_tenth_of_its_keys_is_held_but_a_small_loss_goes_through(conn, monkeypatch):
    await _first_run(conn, _padded())
    dropped = _drop(_padded(), "SD1900722_002.nc")                  # aoml: 1 of 7 stored keys = 14 %
    out = await L.sync_argo_doxy(fetch_index=lambda: _gz(dropped), fetch_sprof=_fetch_sprof)
    assert out["deleted"] == 1                                       # below DELETE_DAC_MIN: not an outage
    await _first_run(conn, _padded())
    monkeypatch.setattr(L, "DELETE_DAC_MIN", 0)
    out = await L.sync_argo_doxy(fetch_index=lambda: _gz(dropped), fetch_sprof=_fetch_sprof)
    assert out["deleted"] == 0 and (await _rejects(conn))["deletions_held"] == {"aoml": 1}


@needs_db
async def test_a_stored_key_on_an_untrusted_index_line_is_never_deleted(conn):
    await _first_run(conn, _padded())
    dup = next(ln for ln in INDEX_TXT.splitlines() if "SD1900722_001.nc" in ln)
    malformed = _replace_line(_padded(), "SD1900722_002.nc", lambda ln: ln.rsplit(",", 1)[0] + "\n")
    no_doxy = _replace_line(_padded(), "SD1901466_000.nc", lambda ln: ln.replace("PRES TEMP PSAL DOXY", "PRES TEMP PSAL"))
    for text, reject in ((_padded() + dup + "\n", "index_duplicate"), (malformed, "index_malformed"),
                         (no_doxy, "index_doxy_dropped")):
        out = await L.sync_argo_doxy(fetch_index=lambda t=text: _gz(t), fetch_sprof=_fetch_sprof)
        assert out["deleted"] == 0 and (await _rejects(conn))[reject] >= 1, reject
        assert await conn.fetchval("SELECT count(*) FROM argo_doxy_profiles") == 13, reject


@needs_db
async def test_more_than_one_percent_malformed_lines_is_a_format_change(conn):
    await _first_run(conn)
    broken = _replace_line(INDEX_TXT, "SD1900722_002.nc", lambda ln: ln.rsplit(",", 1)[0] + "\n")   # 1 of 14 lines
    out = await L.sync_argo_doxy(fetch_index=lambda: _gz(broken),
                                 fetch_sprof=lambda *a: (_ for _ in ()).throw(AssertionError("no download")))
    assert out["outcome"] == "schema" and "malformed" in out["error"]
    assert await conn.fetchval("SELECT count(*) FROM argo_doxy_profiles") == 13


@needs_db
async def test_a_rules_version_bump_replans_every_float_and_a_half_done_reread_resumes(conn, monkeypatch):
    await _first_run(conn)
    assert await conn.fetchval("SELECT rules_version FROM argo_doxy_source") == r.RULES_VERSION
    assert await conn.fetchval("SELECT count(*) FROM argo_doxy_profiles WHERE rules_version = $1", r.RULES_VERSION) == 13
    boom_calls = []

    def counting(dac, wmo, dest):
        boom_calls.append((dac, wmo))
        return _fetch_sprof(dac, wmo, dest)
    out = await L.sync_argo_doxy(fetch_index=_gz, fetch_sprof=counting)
    assert out["outcome"] == "unchanged" and boom_calls == []         # same rules: nothing to read
    monkeypatch.setattr(L, "RULES_VERSION", r.RULES_VERSION + 1)
    ticks = iter(range(0, 10**6, 1000))
    out = await L.sync_argo_doxy(fetch_index=_gz, fetch_sprof=counting, budget_s=2500, clock=lambda: next(ticks))
    assert out["outcome"] == "partial" and len(boom_calls) == 2
    assert await conn.fetchval("SELECT rules_version FROM argo_doxy_source") == r.RULES_VERSION    # not complete yet
    out = await L.sync_argo_doxy(fetch_index=_gz, fetch_sprof=counting)                              # resumes
    assert out["floats_planned"] == 12 - 2 and len(boom_calls) == 12
    assert len(set(boom_calls)) == 12                                  # nothing read twice
    assert await conn.fetchval("SELECT rules_version FROM argo_doxy_source") == r.RULES_VERSION + 1
    assert await conn.fetchval("SELECT count(*) FROM argo_doxy_profiles WHERE rules_version = $1",
                               r.RULES_VERSION + 1) == 13
    assert await conn.fetchval("SELECT rules_version FROM argo_doxy_empty") == r.RULES_VERSION + 1


@needs_db
async def test_a_rules_change_reaches_an_empty_marker(conn, monkeypatch):
    """A profile our own rules emptied is hidden by its marker only until the rules change."""
    await _support(conn)
    real = L.build_profile
    monkeypatch.setattr(L, "build_profile", lambda raw, row, upd: None if row.wmo == "1900722" else real(raw, row, upd))
    await L.sync_argo_doxy(fetch_index=_gz, fetch_sprof=_fetch_sprof)
    assert await conn.fetchval("SELECT count(*) FROM argo_doxy_empty") == 3                  # 1900722 x2 + 5904670_038
    monkeypatch.setattr(L, "build_profile", real)
    out = await L.sync_argo_doxy(fetch_index=_gz, fetch_sprof=lambda *a: (_ for _ in ()).throw(AssertionError()))
    assert out["floats_planned"] == 0                                  # same rules version: the marker still hides it
    monkeypatch.setattr(L, "RULES_VERSION", r.RULES_VERSION + 1)
    out = await L.sync_argo_doxy(fetch_index=_gz, fetch_sprof=_fetch_sprof)
    assert out["outcome"] == "updated"
    assert await conn.fetchval("SELECT count(*) FROM argo_doxy_profiles WHERE platform_number='1900722'") == 2
    assert [x["profile_key"] for x in await conn.fetch("SELECT profile_key FROM argo_doxy_empty")] == [
        "aoml_5904670_038"]


@needs_db
async def test_an_empty_profile_that_gains_values_becomes_a_row_and_loses_its_marker(conn, monkeypatch):
    await _support(conn)
    real = L.build_profile
    monkeypatch.setattr(L, "build_profile", lambda raw, row, upd: None if row.key == "aoml_1900722_001" else real(raw, row, upd))
    await L.sync_argo_doxy(fetch_index=_gz, fetch_sprof=_fetch_sprof)
    assert await conn.fetchval("SELECT count(*) FROM argo_doxy_empty WHERE profile_key='aoml_1900722_001'") == 1
    monkeypatch.setattr(L, "build_profile", real)                      # the profile now has values; the index says so
    # a stamp newer than the index's but not newer than the Sprof file's (08:37:04): a Sprof that LAGS its index is
    # deliberately re-read on every run (profile_stamp), which would hide what this test is about
    bumped = _bump(INDEX_TXT, "SD1900722_001.nc", "20220628082000")
    out = await L.sync_argo_doxy(fetch_index=lambda: _gz(bumped), fetch_sprof=_fetch_sprof)
    assert out["outcome"] == "updated"
    assert await conn.fetchval("SELECT count(*) FROM argo_doxy_profiles WHERE profile_key='aoml_1900722_001'") == 1
    assert await conn.fetchval("SELECT count(*) FROM argo_doxy_empty WHERE profile_key='aoml_1900722_001'") == 0
    out = await L.sync_argo_doxy(fetch_index=lambda: _gz(bumped),
                                 fetch_sprof=lambda *a: (_ for _ in ()).throw(AssertionError("stale marker")))
    assert out["floats_planned"] == 0                                  # no stale marker re-plans the float


@needs_db
@pytest.mark.parametrize("requested, cleared", [("2000-01-01T00:00:00Z", True), ("2999-01-01T00:00:00Z", False)])
async def test_a_refresh_request_made_after_the_run_started_is_not_cleared(conn, requested, cleared):
    from datetime import datetime
    await _first_run(conn)
    await conn.execute("UPDATE argo_doxy_source SET refresh_requested_at = $1",
                       datetime.fromisoformat(requested.replace("Z", "+00:00")))
    out = await L.sync_argo_doxy(fetch_index=_gz, fetch_sprof=_fetch_sprof)
    assert out["outcome"] == "unchanged"
    assert (await conn.fetchval("SELECT refresh_requested_at IS NULL FROM argo_doxy_source")) is cleared


def test_importing_the_loader_does_not_import_the_api_stack():
    """A fresh interpreter (-I: no cwd/PYTHONPATH): the worker's cgroup must not pay for fastapi/domains/schema."""
    import subprocess
    import sys
    backend = str(pathlib.Path(__file__).resolve().parent.parent)
    code = ("import sys; sys.path.insert(0, %r); import ingestion.argo_doxy; "
            "bad = sorted(m for m in sys.modules if m.split('.')[0] in ('fastapi', 'starlette', 'domains', 'schema', "
            "'routers', 'main')); print(bad); sys.exit(1 if bad else 0)" % backend)
    res = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stdout + res.stderr
