# backend/tests/test_argo_oxygen_api_db.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""argo-oxygen-points API through the real app (httpx ASGI); only the API-key dependency is bypassed."""
import gzip
import json
import pathlib
import shutil
import subprocess
import sys

import httpx
import pytest

import db
from domains import argo_oxygen_points as ap
from ingestion import argo_doxy as L
from ingestion import argo_doxy_rules as r
from plankton_helpers import conn, needs_db  # noqa: F401
from schema.argo_doxy import ensure_argo_doxy

FIX = pathlib.Path(__file__).parent / "fixtures" / "argo_doxy"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "SCRATCH_DIR", tmp_path / "scratch")
    monkeypatch.setattr(L, "_disk_used_fraction", lambda: 0.1)       # the developer's disk must not decide a test
    ap.clear_caches()
    yield
    ap.clear_caches()


async def _get(path, headers=None):
    import main
    from auth import get_api_key
    main.app.dependency_overrides[get_api_key] = lambda: "test"
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
            return await c.get(path, headers=headers or {})
    finally:
        main.app.dependency_overrides.pop(get_api_key, None)


async def _loaded(conn):
    await conn.execute("""CREATE TABLE IF NOT EXISTS sync_log (source text PRIMARY KEY,
        last_synced_at timestamptz, records_added int, total_records int, skipped_reason text, skipped_at timestamptz)""")
    await conn.execute("DELETE FROM sync_log WHERE source='argo-doxy'")
    await conn.execute("DROP TABLE IF EXISTS argo_doxy_profiles, argo_doxy_empty, argo_doxy_source CASCADE")
    await ensure_argo_doxy(conn)
    text = (FIX / "argo_synthetic-profile_index.excerpt.txt").read_text()
    out = await L.sync_argo_doxy(fetch_index=lambda: gzip.compress(text.encode()),
                                 fetch_sprof=lambda d, w_, dest: shutil.copy(FIX / f"{d}_{w_}_Sprof.nc", dest))
    assert out["outcome"] == "updated", out


async def test_a_keyless_request_is_rejected_exactly_like_the_oxygen_field_routes(monkeypatch):
    import main

    class Down:
        def acquire(self):
            raise AssertionError("database touched by a keyless request")
    monkeypatch.setattr(db, "pool", Down())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        ref = await c.get("/v1/oxygen/meta")
        assert ref.status_code in (401, 403)
        for path in ("/v1/argo-oxygen/points/500", "/v1/argo-oxygen/profile/aoml_1900722_001",
                     "/v1/argo-oxygen/floats", "/v1/argo-oxygen/meta"):
            got = await c.get(path)
            assert got.status_code == ref.status_code and got.json() == ref.json(), path


def test_the_api_module_does_not_pull_in_the_loader_reader_worker_or_netcdf():
    code = ("import sys; sys.path.insert(0, sys.argv[1]); import domains.argo_oxygen_points; "
            "bad = [m for m in ('netCDF4', 'argo_doxy_worker', 'ingestion.argo_doxy', 'ingestion.argo_doxy_sprof') "
            "if m in sys.modules]; print(bad); sys.exit(1 if bad else 0)")
    backend = str(pathlib.Path(__file__).parent.parent)
    res = subprocess.run([sys.executable, "-I", "-c", code, backend], cwd=backend, capture_output=True, text=True)
    assert res.returncode == 0, res.stdout + res.stderr


@needs_db
async def test_points_document_holds_drawable_profiles_with_good_values_only(conn):
    await _loaded(conn)
    res = await _get("/v1/argo-oxygen/points/500", {"Accept-Encoding": "gzip"})
    assert res.status_code == 200 and res.headers["content-encoding"] == "gzip"
    doc = res.json()
    assert doc["n"] == 8 and doc["depth"] == 500 and doc["window"] == [450.0, 550.0]
    assert len(doc["fi"]) == len(doc["cycle"]) == len(doc["lon"]) == len(doc["year"]) == len(doc["value"]) == 8
    keys = {r.profile_key(*doc["floats"][f].split("_"), c, i in doc["descending"])
            for i, (f, c) in enumerate(zip(doc["fi"], doc["cycle"]))}
    assert "kiost_2900791_053" not in keys and "aoml_1902751_001" not in keys      # R mode never drawn
    assert "coriolis_3902120_002D" in keys                                           # descending keeps its D
    assert all(v is None or isinstance(v, int) for v in doc["value"])
    plain = await _get("/v1/argo-oxygen/points/500", {"Accept-Encoding": "identity"})
    assert "content-encoding" not in plain.headers and plain.json() == doc


@needs_db
async def test_the_value_is_the_stored_pick_at_that_depth(conn):
    await _loaded(conn)
    doc = (await _get("/v1/argo-oxygen/points/2000")).json()
    pick = await conn.fetchval("SELECT at_depth[8] FROM argo_doxy_profiles WHERE profile_key='aoml_5900421_005'")
    i = next(i for i, (f, c) in enumerate(zip(doc["fi"], doc["cycle"]))
             if doc["floats"][f] == "aoml_5900421" and c == 5)
    assert pick is not None and doc["value"][i] == round(pick)


async def test_unknown_depth_or_key_is_404_and_a_broken_database_is_503(monkeypatch):
    assert (await _get("/v1/argo-oxygen/points/750")).status_code == 404
    assert (await _get("/v1/argo-oxygen/profile/not-a-key")).status_code == 404

    class Down:
        def acquire(self):
            raise ConnectionError("db down")
    monkeypatch.setattr(db, "pool", Down())
    for path in ("/v1/argo-oxygen/points/500", "/v1/argo-oxygen/profile/aoml_1900722_001",
                 "/v1/argo-oxygen/floats", "/v1/argo-oxygen/meta"):
        res = await _get(path)
        assert res.status_code == 503 and res.headers.get("Retry-After") == "60", path


@needs_db
async def test_not_loaded_is_503_not_an_empty_200(conn):
    await conn.execute("DROP TABLE IF EXISTS argo_doxy_profiles, argo_doxy_empty, argo_doxy_source CASCADE")
    await ensure_argo_doxy(conn)
    res = await _get("/v1/argo-oxygen/points/500")
    assert res.status_code == 503 and res.headers.get("Retry-After") == "60"


@needs_db
async def test_document_is_compressed_once_per_load_and_follows_loaded_at(conn, monkeypatch):
    await _loaded(conn)
    calls = []
    real = gzip.compress
    monkeypatch.setattr(ap.gzip, "compress", lambda *a, **k: calls.append(1) or real(*a, **k))
    for _ in range(3):
        assert (await _get("/v1/argo-oxygen/points/500", {"Accept-Encoding": "gzip"})).status_code == 200
    assert len(calls) == 1
    await conn.execute("UPDATE argo_doxy_profiles SET drawable = false WHERE profile_key = 'aoml_1900722_001'")
    await conn.execute("UPDATE argo_doxy_source SET loaded_at = now() + interval '1 second'")   # another process
    assert (await _get("/v1/argo-oxygen/points/500")).json()["n"] == 7


@needs_db
async def test_profile_detail_carries_both_series_flags_picks_and_the_recent_field(conn, monkeypatch):
    await _loaded(conn)
    monkeypatch.setattr(ap, "_field_recent", lambda lat, lon: {str(d): 200.0 + d / 100 for d in r.DISPLAY_DEPTHS})
    res = await _get("/v1/argo-oxygen/profile/aoml_1900722_001")
    assert res.status_code == 200
    p = res.json()
    assert p["profile_key"] == "aoml_1900722_001" and p["argo_profile_id"] == "1900722_001"
    lv = p["levels"]
    assert len(lv["depth_m"]) == len(lv["pres_dbar"]) == len(lv["doxy_adj"]) == len(lv["doxy_adj_qc"]) \
        == len(lv["doxy_raw"]) == len(lv["doxy_raw_qc"])
    assert set(p["at_depth"]) == {str(d) for d in r.DISPLAY_DEPTHS}
    assert p["field_recent"]["500"] == 205.0
    assert "delta" not in json.dumps(p).lower() and "change" not in p          # never a Δ for one profile
    assert p["source_url"].startswith("https://data-argo.ifremer.fr/dac/aoml/1900722/profiles/S")
    assert p["float_url"] == "https://fleetmonitoring.euro-argo.eu/float/1900722"
    assert all(c in p["citation"] for c in p["citations"]) and "International Argo Program" in p["citation"]


@needs_db
async def test_profile_detail_has_no_float32_noise_and_no_nan(conn, monkeypatch):
    await _loaded(conn)
    monkeypatch.setattr(ap, "_field_recent", lambda lat, lon: {str(d): None for d in r.DISPLAY_DEPTHS})
    body = (await _get("/v1/argo-oxygen/profile/coriolis_3902120_002D")).text
    assert "NaN" not in body and "99999" not in body
    lv = json.loads(body)["levels"]
    for v in lv["doxy_adj"] + lv["doxy_raw"] + lv["depth_m"] + lv["pres_dbar"]:
        if v is not None:
            assert float(f"{v:.7g}") == v                # float32 noise trimmed to 7 significant digits


@needs_db
async def test_floats_is_a_feature_collection_one_point_per_float(conn):
    await _loaded(conn)
    fc = (await _get("/v1/argo-oxygen/floats")).json()
    assert fc["type"] == "FeatureCollection"
    pairs = [(f["properties"]["dac"], f["properties"]["wmo"]) for f in fc["features"]]
    assert len(pairs) == len(set(pairs)) and ("coriolis", "1902751") in pairs
    assert ("aoml", "1902751") not in pairs                                   # its only profile is R mode


@needs_db
async def test_meta_writes_the_count_arithmetic_down(conn):
    await _loaded(conn)
    m = (await _get("/v1/argo-oxygen/meta")).json()
    a = m["arithmetic"]
    assert a["index_doxy"] == 14 and a["rejected"]["no_doxy_values"] == 1 and a["stored"] == 13
    assert a["drawn"] == 8 and sum(a["not_drawn"].values()) == 5
    assert a["not_drawn"] == {"realtime_only": 2, "no_good_adjusted": 2, "bad_position": 1, "bad_time": 0}
    assert m["licence"] == "CC BY 4.0" and m["health"]["status"] == "ok"
    assert m["depth_windows"]["2000"] == [1900.0, 2100.0]


@needs_db
async def test_a_drawable_profile_without_a_good_sample_in_the_window_is_a_null_value_not_a_gap(conn):
    await _loaded(conn)
    await conn.execute("UPDATE argo_doxy_profiles SET at_depth[5] = NULL WHERE profile_key = 'aoml_1900722_001'")
    await conn.execute("UPDATE argo_doxy_source SET loaded_at = now() + interval '1 second'")
    doc = (await _get("/v1/argo-oxygen/points/500")).json()
    i = next(i for i, (f, c) in enumerate(zip(doc["fi"], doc["cycle"])) if doc["floats"][f] == "aoml_1900722" and c == 1)
    assert doc["n"] == 8 and doc["value"][i] is None and doc["value"][i + 1] is not None


@needs_db
async def test_a_stored_but_not_drawn_profile_is_served_by_key_and_says_so(conn, monkeypatch):
    await _loaded(conn)
    monkeypatch.setattr(ap, "_field_recent", lambda lat, lon: {str(d): None for d in r.DISPLAY_DEPTHS})
    p = (await _get("/v1/argo-oxygen/profile/aoml_1902751_001")).json()
    assert p["drawable"] is False and p["doxy_mode"] == "R"
    assert (await _get("/v1/argo-oxygen/profile/aoml_9999999_001")).status_code == 404       # well-formed, unknown


@needs_db
async def test_profile_time_has_no_sub_second_noise_and_float_positions_are_rounded(conn, monkeypatch):
    await _loaded(conn)
    monkeypatch.setattr(ap, "_field_recent", lambda lat, lon: {str(d): None for d in r.DISPLAY_DEPTHS})
    t = (await _get("/v1/argo-oxygen/profile/aoml_1900722_001")).json()["profile_time"]
    assert t == "2006-10-22T02:16:24+00:00"
    for f in (await _get("/v1/argo-oxygen/floats")).json()["features"]:
        for x in f["geometry"]["coordinates"]:
            assert round(x, 3) == x


@needs_db
async def test_an_unreadable_field_still_serves_the_measurement(conn, monkeypatch):
    await _loaded(conn)

    def boom():
        raise OSError("isas file unreadable")
    monkeypatch.setattr(ap.oxygen_deox, "load_recent_grid", boom)
    res = await _get("/v1/argo-oxygen/profile/aoml_1900722_001")
    assert res.status_code == 200
    assert set(res.json()["field_recent"].values()) == {None}


@needs_db
async def test_before_the_first_load_every_endpoint_logs_one_warning_and_no_traceback(conn, caplog):
    await conn.execute("DROP TABLE IF EXISTS argo_doxy_profiles, argo_doxy_empty, argo_doxy_source CASCADE")
    await ensure_argo_doxy(conn)
    for path in ("/v1/argo-oxygen/points/500", "/v1/argo-oxygen/floats"):
        caplog.clear()
        assert (await _get(path)).status_code == 503
        mine = [x for x in caplog.records if x.name == ap.log.name]
        assert [x.levelname for x in mine] == ["WARNING"] and mine[0].exc_info is None, path
    assert (await _get("/v1/argo-oxygen/profile/aoml_1900722_001")).status_code == 404
    meta = await _get("/v1/argo-oxygen/meta")
    assert meta.status_code == 200 and meta.json()["health"]["status"] == "not_loaded"


async def _meta_after(conn, sql, *args):
    await _loaded(conn)
    await conn.execute(sql, *args)
    return (await _get("/v1/argo-oxygen/meta")).json()


@needs_db
async def test_health_failing_only_while_a_recorded_failure_stands(conn):
    m = await _meta_after(conn, "UPDATE argo_doxy_source SET last_failed_at = now(), last_failure = 'error: boom'")
    assert m["health"]["status"] == "failing" and m["health"]["failure"] == "error: boom"
    await conn.execute("UPDATE argo_doxy_source SET last_failed_at = NULL, last_failure = NULL")
    assert (await _get("/v1/argo-oxygen/meta")).json()["health"]["status"] == "ok"


@needs_db
async def test_health_transient_skips_and_updated_with_rejects_are_not_failures(conn):
    for reason, field in ((f"{r.LOW_MEMORY_PREFIX}: 0.4 GiB available", "deferred"),
                          (f"{r.DISK_PREFIX} 83 %: stopped after 3 of 9 floats", "deferred"),
                          (f"{r.INDEX_FAILED_PREFIX}: URLError, will retry", "deferred"),
                          (f"{r.UPDATED_WITH_REJECTS_PREFIX}: 2 of 9 floats kept their previous rows", "note")):
        await _loaded(conn)
        await conn.execute("INSERT INTO sync_log (source, skipped_reason, skipped_at) VALUES ('argo-doxy', $1, now()) "
                           "ON CONFLICT (source) DO UPDATE SET skipped_reason = $1, skipped_at = now()", reason)
        h = (await _get("/v1/argo-oxygen/meta")).json()["health"]
        assert h["status"] == "ok" and h[field] == reason, reason


@needs_db
async def test_health_running_while_a_fresh_started_marker_stands_and_not_when_stale(conn):
    await _loaded(conn)
    await conn.execute("UPDATE argo_doxy_source SET last_failed_at = now(), last_failure = 'interrupted'")
    await conn.execute("INSERT INTO sync_log (source, skipped_reason, skipped_at) VALUES ('argo-doxy', $1, now()) "
                       "ON CONFLICT (source) DO UPDATE SET skipped_reason = $1, skipped_at = now()",
                       f"{r.STARTED_PREFIX} 2026-10-06T05:40")
    h = (await _get("/v1/argo-oxygen/meta")).json()["health"]
    assert h["status"] == "running" and h["failure"] is None
    await conn.execute("UPDATE sync_log SET skipped_at = now() - interval '7 hours' WHERE source = 'argo-doxy'")
    assert (await _get("/v1/argo-oxygen/meta")).json()["health"]["status"] == "failing"


@needs_db
async def test_meta_surfaces_held_deletions_and_the_rules_version_state(conn):
    m = await _meta_after(conn, "UPDATE argo_doxy_source SET last_rejects = $1::jsonb",
                          json.dumps({"deletions_held": {"coriolis": 400}, "no_doxy_values": 1}))
    assert m["health"]["deletions_held"] == {"coriolis": 400} and m["health"]["status"] == "ok"
    assert "deletions_held" not in m["arithmetic"]["rejected"]                  # a dict is not a count
    assert m["rules_version"] == {"code": r.RULES_VERSION, "last_complete_run": r.RULES_VERSION,
                                  "profiles_on_other_version": 0}
    await conn.execute("UPDATE argo_doxy_profiles SET rules_version = 0 WHERE profile_key = 'aoml_1900722_001'")
    await conn.execute("UPDATE argo_doxy_source SET rules_version = NULL")
    rv = (await _get("/v1/argo-oxygen/meta")).json()["rules_version"]
    assert rv["profiles_on_other_version"] == 1 and rv["last_complete_run"] is None
    assert (await _get("/v1/argo-oxygen/meta")).json()["health"]["deletions_held"] == {"coriolis": 400}


def _fake_isas(nan_depth=None):
    import numpy as np
    from services.oxygen_deox import _IsasGrid
    depths = np.array(r.DISPLAY_DEPTHS, dtype="float64")
    data = np.zeros((len(depths), 2, 2), dtype="float32")
    for di in range(len(depths)):
        for la in range(2):
            for lo in range(2):
                data[di, la, lo] = 100 * di + 10 * la + lo
    if nan_depth is not None:
        data[r.DISPLAY_DEPTHS.index(nan_depth), 0, 1] = np.nan
    return _IsasGrid(np.array([0.0, 10.0]), np.array([0.0, 10.0]), depths, data)


@needs_db
async def test_the_real_field_lookup_returns_the_recent_value_at_the_spot(conn, monkeypatch):
    await _loaded(conn)
    # aoml_1900722_001 lies at (-40.3, 73.4): the nearest cell of the fake grid is lat index 0, lon index 1
    monkeypatch.setattr(ap.oxygen_deox, "load_recent_grid", lambda: _fake_isas(nan_depth=1000))
    p = (await _get("/v1/argo-oxygen/profile/aoml_1900722_001")).json()
    want = {str(d): float(100 * i + 1) for i, d in enumerate(r.DISPLAY_DEPTHS)}
    want["1000"] = None                                                      # a NaN cell is no value, not 0
    assert p["field_recent"] == want
    assert p["field_product"] == r.FIELD_PRODUCT


@needs_db
async def test_a_missing_isas_field_is_looked_for_once_per_interval_not_once_per_request(conn, monkeypatch):
    await _loaded(conn)
    calls = []
    monkeypatch.setattr(ap.oxygen_deox, "load_recent_grid", lambda: calls.append(1))      # -> None: file absent
    for _ in range(3):
        res = await _get("/v1/argo-oxygen/profile/aoml_1900722_001")
        assert res.status_code == 200 and set(res.json()["field_recent"].values()) == {None}
    assert len(calls) == 1
    monkeypatch.setattr(ap, "_field_retry_at", 0.0)                                       # the interval has passed
    await _get("/v1/argo-oxygen/profile/aoml_1900722_001")
    assert len(calls) == 2


@needs_db
async def test_floats_document_is_built_once_per_load_and_rebuilt_when_loaded_at_moves(conn, monkeypatch):
    await _loaded(conn)
    builds, compressions = [], []
    real_build, real_gz = ap._build_floats, gzip.compress

    async def counting():
        builds.append(1)
        return await real_build()
    monkeypatch.setattr(ap, "_build_floats", counting)
    monkeypatch.setattr(ap.gzip, "compress", lambda *a, **k: compressions.append(1) or real_gz(*a, **k))
    first = await _get("/v1/argo-oxygen/floats", {"Accept-Encoding": "gzip"})
    assert first.status_code == 200 and first.headers["content-encoding"] == "gzip"
    n = len(first.json()["features"])
    for _ in range(2):
        again = await _get("/v1/argo-oxygen/floats", {"Accept-Encoding": "identity"})
        assert again.status_code == 200 and "content-encoding" not in again.headers
        assert len(again.json()["features"]) == n
    assert len(builds) == 1 and len(compressions) == 1
    await conn.execute("UPDATE argo_doxy_profiles SET drawable = false WHERE dac = 'aoml' AND platform_number = '1900722'")
    await conn.execute("UPDATE argo_doxy_source SET loaded_at = now() + interval '1 second'")   # another process
    assert len((await _get("/v1/argo-oxygen/floats")).json()["features"]) == n - 1
    assert len(builds) == 2


@needs_db
async def test_a_bug_in_a_builder_is_a_logged_503_not_a_quiet_not_loaded(conn, monkeypatch, caplog):
    await _loaded(conn)

    def broken(rows, depth):
        raise KeyError("typo")
    monkeypatch.setattr(ap, "_assemble_points", broken)
    res = await _get("/v1/argo-oxygen/points/500")
    assert res.status_code == 503 and res.headers.get("Retry-After") == "60"
    mine = [x for x in caplog.records if x.name == ap.log.name]
    assert [x.levelname for x in mine] == ["ERROR"] and mine[0].exc_info is not None
