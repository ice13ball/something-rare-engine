# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""GLODAPv3 points API: map document, cast detail, cruises, meta (with health), cache and failure semantics.

Requests go through the real app (httpx ASGI transport, so they share the test's event loop and its one
rolled-back connection standing in for db.pool); only the API-key dependency is bypassed."""
import gzip
import json
import pathlib
import subprocess
import sys
import zipfile

import httpx
import pytest

import db
from domains import glodap_points as gp
from ingestion import glodap_bottles as g
from plankton_helpers import conn, needs_db  # noqa: F401
from schema.glodap_bottles import ensure_glodap_bottles

FIXCSV = pathlib.Path(__file__).parent / "fixtures" / "glodap_v3" / "glodapv3_excerpt.csv"
CAST = "49UF20150620_4511_1"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    sent = []

    async def fake(message, title="", **kw):
        sent.append(message)
        return True
    monkeypatch.setattr(g, "notify_telegram", fake)        # no Telegram from tests
    gp.clear_caches()
    yield
    gp.clear_caches()


async def _get(path, headers=None):
    import main
    from auth import get_api_key
    main.app.dependency_overrides[get_api_key] = lambda: "test"
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
            return await c.get(path, headers=headers or {})
    finally:
        main.app.dependency_overrides.pop(get_api_key, None)


def _fetch(dest):
    with zipfile.ZipFile(dest, "w") as z:
        z.write(FIXCSV, "GLODAPv3_Merged_Master_File.csv")
    return {"etag": '"t"', "content_length": 1, "last_modified": "x"}


async def _fresh(conn):
    for t in ("glodap_casts_new", "glodap_cruises_new", "glodap_casts", "glodap_cruises", "glodap_bottle_source"):
        await conn.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    await conn.execute("""CREATE TABLE IF NOT EXISTS sync_log (source text PRIMARY KEY,
        last_synced_at timestamptz, records_added integer, total_records integer,
        skipped_reason text, skipped_at timestamptz)""")
    await conn.execute("DELETE FROM sync_log WHERE source = 'glodap-bottles'")
    await ensure_glodap_bottles(conn)


async def _loaded(conn, tmp_path):
    await _fresh(conn)
    out = await g.sync_glodap_bottles(fetch=_fetch, ship_lookup=lambda c: {"49UF": "Keifu Maru"},
                                      scratch=tmp_path / "s")
    assert out["outcome"] == "swapped", out
    gp.clear_caches()


# ── API key + import hygiene ──────────────────────────────────────────────────────────────────────
async def test_a_keyless_request_is_rejected_exactly_like_the_ocean_carbon_routes(monkeypatch):
    """No dependency override here: the real get_api_key. The ocean-carbon field endpoints (/v1/carbon/meta) are
    behind the same dependency, so a keyless call must fail the same way, before any database access."""
    import main

    class Down:                              # a keyless request must be refused BEFORE the database is touched
        def acquire(self):
            raise AssertionError("database touched by a keyless request")
    monkeypatch.setattr(db, "pool", Down())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        reference = await c.get("/v1/carbon/meta")
        assert reference.status_code in (401, 403)
        for path in ("/v1/glodap/casts", "/v1/glodap/cast/X_1_1", "/v1/glodap/cruises", "/v1/glodap/meta"):
            r = await c.get(path)
            assert r.status_code == reference.status_code and r.json() == reference.json(), path
            assert (await c.get(path, headers={"X-API-Key": ""})).status_code in (401, 403), path


def test_the_api_module_does_not_pull_in_the_loader_duckdb_or_the_worker():
    """A fresh interpreter, so imports made earlier in this test session cannot mask the answer."""
    code = ("import sys; sys.path.insert(0, sys.argv[1]); import domains.glodap_points; "
            "bad = [m for m in ('duckdb', 'glodap_bottles_worker', 'ingestion.glodap_bottles') if m in sys.modules]; "
            "print(bad); sys.exit(1 if bad else 0)")
    backend = str(pathlib.Path(__file__).parent.parent)
    r = subprocess.run([sys.executable, "-I", "-c", code, backend], cwd=backend, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


# ── a cast the source gives no number for ─────────────────────────────────────────────────────────
@needs_db
async def test_cast_without_a_number_is_served_with_cast_no_null_and_a_url_safe_key(conn, tmp_path):
    import csv
    src = tmp_path / "nocast.csv"
    with FIXCSV.open(newline="") as f, src.open("w", newline="") as o:
        rd = csv.DictReader(f)
        w = csv.DictWriter(o, fieldnames=rd.fieldnames, lineterminator="\n")
        w.writeheader()
        for row in rd:
            if row["expocode"] == "49UF20150620":
                row["cast"] = "-9999"
            w.writerow(row)

    def fetch(dest):
        with zipfile.ZipFile(dest, "w") as z:
            z.write(src, "GLODAPv3_Merged_Master_File.csv")
        return {"etag": '"t"', "content_length": 1, "last_modified": "x"}
    await _fresh(conn)
    out = await g.sync_glodap_bottles(fetch=fetch, ship_lookup=lambda c: {}, scratch=tmp_path / "s")
    assert out["outcome"] == "swapped" and out["rejected"] == {}, out
    gp.clear_caches()
    r = await _get("/v1/glodap/cast/49UF20150620_4511_nc")
    assert r.status_code == 200
    body = r.json()
    assert body["cast_no"] is None and body["station"] == "4511" and body["cast_key"] == "49UF20150620_4511_nc"
    assert "49UF20150620_4511_nc" in json.loads(await gp.build_casts_document())["keys"]
    assert (await _get("/v1/glodap/cast/49UF20150620_4511_1")).status_code == 404


# ── map document ────────────────────────────────────────────────────────────────────────────────────
@needs_db
async def test_map_document_holds_only_good_values_and_no_nan(conn, tmp_path):
    await _loaded(conn, tmp_path)
    doc = json.loads(await gp.build_casts_document())
    assert doc["n"] == len(doc["keys"]) == len(doc["lon"]) == len(doc["year"])
    assert doc["n"] == await conn.fetchval("SELECT count(*) FROM glodap_casts WHERE n_good > 0")
    assert set(doc["values"]) == {"dic", "talk", "ph"}
    for per_depth in doc["values"].values():
        assert set(per_depth) == {"0", "200", "500", "1000", "2000", "3000", "4000"}
        for arr in per_depth.values():
            assert len(arr) == doc["n"]
            assert all(v is None or (v == v and v > 0) for v in arr)     # no NaN, no 0 for missing, no -9999
    i = doc["keys"].index(CAST)
    assert doc["values"]["dic"]["4000"][i] is not None                 # deep cast coloured at 4000 m


@needs_db
async def test_map_document_value_is_the_flag_2_level_not_a_flagged_bottle(conn, tmp_path):
    await _loaded(conn, tmp_path)
    doc = json.loads(await gp.build_casts_document())
    i = doc["keys"].index(CAST)
    lv = json.loads(await conn.fetchval("SELECT levels FROM glodap_casts WHERE cast_key = $1", CAST))
    for depth, hit in lv["dic"].items():
        assert doc["values"]["dic"][depth][i] == hit[0]
    # a cast with no flag-2 value anywhere is not drawn at all
    await conn.execute("UPDATE glodap_casts SET n_good = 0 WHERE cast_key = $1", CAST)
    assert CAST not in json.loads(await gp.build_casts_document())["keys"]


# ── /casts: gzip once, cache follows the swap ─────────────────────────────────────────────────────────
@needs_db
async def test_casts_endpoint_gzips_exactly_once(conn, tmp_path):
    await _loaded(conn, tmp_path)
    r = await _get("/v1/glodap/casts", {"Accept-Encoding": "gzip"})
    assert r.status_code == 200 and r.headers["content-encoding"] == "gzip"
    assert r.json()["n"] > 0                 # httpx decodes ONCE; a second (middleware) gzip would not parse
    assert "Accept-Encoding" in r.headers["vary"]
    plain = await _get("/v1/glodap/casts", {"Accept-Encoding": "identity"})
    assert plain.status_code == 200 and "content-encoding" not in plain.headers
    assert plain.json() == r.json()


@needs_db
async def test_casts_endpoint_compresses_once_per_load_not_once_per_request(conn, tmp_path, monkeypatch):
    await _loaded(conn, tmp_path)
    calls = []
    real = gzip.compress
    monkeypatch.setattr(gp.gzip, "compress", lambda *a, **k: calls.append(1) or real(*a, **k))
    for _ in range(3):
        assert (await _get("/v1/glodap/casts", {"Accept-Encoding": "gzip"})).status_code == 200
    assert len(calls) == 1


@needs_db
async def test_a_swap_clears_the_cached_map_document(conn, tmp_path):
    await _loaded(conn, tmp_path)
    await gp._casts_document_cached()
    assert gp._casts_cache is not None
    out = await g.sync_glodap_bottles(fetch=_fetch, ship_lookup=lambda c: {}, scratch=tmp_path / "s2")
    assert out["outcome"] == "swapped"
    assert gp._casts_cache is None           # the loader's post-swap hook, not the next request, emptied it


@needs_db
async def test_a_swap_by_another_process_is_noticed_through_loaded_at(conn, tmp_path):
    """The import runs in glodap_bottles_worker; its clear_caches() cannot reach this process's memory."""
    await _loaded(conn, tmp_path)
    first = json.loads((await gp._casts_document_cached())[0])
    await conn.execute("UPDATE glodap_casts SET n_good = 0 WHERE cast_key = $1", CAST)
    assert json.loads((await gp._casts_document_cached())[0]) == first          # same stamp: cache is served
    await conn.execute("UPDATE glodap_bottle_source SET loaded_at = now() + interval '1 second' WHERE id = 1")
    assert CAST not in json.loads((await gp._casts_document_cached())[0])["keys"]


# ── cast detail ───────────────────────────────────────────────────────────────────────────────────
@needs_db
async def test_cast_detail_404_for_unknown_and_carries_flags_and_field(conn, tmp_path, monkeypatch):
    await _loaded(conn, tmp_path)
    monkeypatch.setattr(gp.glodap_carbon, "sample", lambda var, lat, lon, d: 2100.0 if var == "dic" else None)
    assert await gp.get_cast_payload("NOPE_1_1") is None
    p = await gp.get_cast_payload(CAST)
    assert p["ship_name"] == "Keifu Maru" and p["product"] == "GLODAPv3 (2026)"
    assert p["field_product"].startswith("GLODAPv2.2016b")
    t = p["variables"]["tco2"]
    assert len(t["values"]) == len(t["flags"]) == len(p["depth_m"]) and t["units"] == "µmol/kg"
    assert p["field"]["dic"]["0"] == 2100.0 and p["field"]["talk"]["0"] is None
    assert set(p["field"]) == {"dic", "talk", "ph", "cant"}
    json.dumps(p, allow_nan=False, default=str)


@needs_db
async def test_cast_detail_has_no_float32_noise_and_no_nan(conn, tmp_path):
    await _loaded(conn, tmp_path)
    await conn.execute("UPDATE glodap_casts SET tco2[1] = 'NaN'::real, phtsinsitutp[1] = 7.9876::real "
                       "WHERE cast_key = $1", CAST)
    r = await _get(f"/v1/glodap/cast/{CAST}")
    assert r.status_code == 200
    assert "NaN" not in r.text
    body = r.json()
    assert body["variables"]["tco2"]["values"][0] is None          # a NaN sample is missing, not 0
    assert body["variables"]["phtsinsitutp"]["values"][0] == 7.9876   # not 7.987599849700928


@needs_db
async def test_cast_detail_credits_dataset_paper_and_ship_names(conn, tmp_path):
    await _loaded(conn, tmp_path)
    body = (await _get(f"/v1/glodap/cast/{CAST}")).json()
    text = " ".join(body["citations"])
    assert "10.25921/m6tp-mj50" in text and "10.5194/essd-2026-496" in text
    assert "NERC Vocabulary Server" in text and "CC BY 4.0" in text and "vocab.nerc.ac.uk" in text
    assert all(c in body["citation"] for c in body["citations"])


async def test_cast_route_semantics(monkeypatch):
    # SEO/API contract: missing -> 404, broken -> 503 + Retry-After
    async def missing(k):
        return None

    async def broken(k):
        raise ConnectionError("db down")
    monkeypatch.setattr(gp, "get_cast_payload", missing)
    assert (await _get("/v1/glodap/cast/NOPE_1_1")).status_code == 404
    monkeypatch.setattr(gp, "get_cast_payload", broken)
    r = await _get("/v1/glodap/cast/X_1_1")
    assert r.status_code == 503 and r.headers.get("Retry-After") == "60"


async def test_every_endpoint_answers_503_with_retry_after_when_the_database_is_down(monkeypatch):
    class Down:
        def acquire(self):
            raise ConnectionError("db down")
    monkeypatch.setattr(db, "pool", Down())
    for path in ("/v1/glodap/casts", "/v1/glodap/cast/X_1_1", "/v1/glodap/cruises", "/v1/glodap/meta"):
        r = await _get(path)
        assert r.status_code == 503 and r.headers.get("Retry-After") == "60", path
        assert r.content and "detail" in r.json(), path


@needs_db
async def test_a_layer_that_has_not_loaded_is_503_not_an_empty_200(conn):
    await _fresh(conn)                       # tables exist, nothing swapped in yet
    for path in ("/v1/glodap/casts", "/v1/glodap/cruises"):
        r = await _get(path)
        assert r.status_code == 503 and r.headers.get("Retry-After"), path
    assert gp._casts_cache is None


@needs_db
async def test_not_loaded_yet_logs_one_warning_line_not_a_traceback(conn, caplog):
    await _fresh(conn)
    for path in ("/v1/glodap/casts", "/v1/glodap/cruises"):
        caplog.clear()
        with caplog.at_level("DEBUG", logger=gp.log.name):
            assert (await _get(path)).status_code == 503
        records = [r for r in caplog.records if r.name == gp.log.name]
        assert len(records) == 1, path
        assert records[0].levelname == "WARNING" and records[0].exc_info is None, path
        assert "not loaded" in records[0].getMessage(), path


async def test_a_database_that_is_down_still_logs_the_traceback(monkeypatch, caplog):
    class Down:
        def acquire(self):
            raise ConnectionError("db down")
    monkeypatch.setattr(db, "pool", Down())
    with caplog.at_level("DEBUG", logger=gp.log.name):
        assert (await _get("/v1/glodap/casts")).status_code == 503
    assert any(r.exc_info for r in caplog.records if r.name == gp.log.name)


# ── cruises ───────────────────────────────────────────────────────────────────────────────────────
@needs_db
async def test_cruises_is_a_feature_collection_one_point_per_expocode(conn, tmp_path):
    await _loaded(conn, tmp_path)
    fc = (await _get("/v1/glodap/cruises")).json()
    assert fc["type"] == "FeatureCollection"
    n = await conn.fetchval("SELECT count(*) FROM glodap_cruises")
    assert len(fc["features"]) == n > 0
    f = next(x for x in fc["features"] if x["properties"]["expocode"] == "49UF20150620")
    assert f["geometry"]["type"] == "Point" and len(f["geometry"]["coordinates"]) == 2
    assert set(f["properties"]) == {"expocode", "ship_name", "platform_code", "doi", "first_date", "last_date",
                                    "n_casts", "first_cast_key"}
    assert f["properties"]["ship_name"] == "Keifu Maru"


# ── meta + health ─────────────────────────────────────────────────────────────────────────────────
@needs_db
async def test_meta_reports_counts_citations_and_a_healthy_layer(conn, tmp_path):
    await _loaded(conn, tmp_path)
    m = (await _get("/v1/glodap/meta")).json()
    assert m["product"] == "GLODAPv3 (2026)" and m["licence"] == "CC BY 4.0"
    assert m["n_casts"] == await conn.fetchval("SELECT count(*) FROM glodap_casts")
    assert m["n_casts_drawn"] == await conn.fetchval("SELECT count(*) FROM glodap_casts WHERE n_good > 0")
    assert m["year_min"] <= m["year_max"] and m["loaded_at"]
    assert m["field_to_bottle"]["cant"] is None and m["depth_windows"]["4000"] == [3750.0, 4250.0]
    assert "NERC Vocabulary Server" in m["citation"] and "essd-2026-496" in m["citation"]
    assert m["health"]["status"] == "ok" and m["health"]["failure"] is None


@needs_db
async def test_meta_health_a_layer_with_rejects_and_a_transient_skip_is_healthy(conn, tmp_path):
    from glodap_bottles_worker import TRANSIENT_PREFIXES
    await _loaded(conn, tmp_path)
    await conn.execute("UPDATE glodap_bottle_source SET last_rejects = '{\"fill_value_rows\": 6}'::jsonb, "
                       "last_rejects_at = now(), last_run_at = now(), last_decision = 'unchanged'")
    for prefix in (*TRANSIENT_PREFIXES, g.SWAPPED_WITH_REJECTS_PREFIX):
        await conn.execute("UPDATE sync_log SET skipped_reason = $1, skipped_at = now() "
                           "WHERE source = 'glodap-bottles'", f"{prefix}: x")
        h = (await _get("/v1/glodap/meta")).json()["health"]
        assert h["status"] == "ok", prefix
        assert h["failure"] is None and h["failed_at"] is None
        assert h["last_rejects"] == {"fill_value_rows": 6} and h["last_decision"] == "unchanged"
    await conn.execute("UPDATE sync_log SET skipped_reason = $1 WHERE source = 'glodap-bottles'",
                       f"{TRANSIENT_PREFIXES[0]}: deferred")
    assert (await _get("/v1/glodap/meta")).json()["health"]["deferred"].startswith(TRANSIENT_PREFIXES[0])


@needs_db
@pytest.mark.parametrize("failure", ["blocked", "error", "schema"])
async def test_meta_health_reports_a_recorded_failure(conn, tmp_path, failure):
    await _loaded(conn, tmp_path)
    await conn.execute("UPDATE glodap_bottle_source SET last_failed_at = now(), last_failure = $1, "
                       "last_decision = $1", failure)
    h = (await _get("/v1/glodap/meta")).json()["health"]
    assert h["status"] == "failing" and h["failure"] == failure and h["failed_at"]
    assert h["last_decision"] == failure


@needs_db
async def test_meta_health_a_live_import_is_running_not_failing(conn, tmp_path):
    """The worker stamps last_failure='interrupted' before it starts and clears it on completion."""
    await _loaded(conn, tmp_path)
    await conn.execute("UPDATE glodap_bottle_source SET last_failed_at = now(), last_failure = 'interrupted'")
    await conn.execute("UPDATE sync_log SET skipped_reason = 'started (changed)', skipped_at = now() "
                       "WHERE source = 'glodap-bottles'")
    h = (await _get("/v1/glodap/meta")).json()["health"]
    assert h["status"] == "running" and h["failure"] is None
    await conn.execute("UPDATE sync_log SET skipped_at = now() - interval '9 hours' WHERE source = 'glodap-bottles'")
    h = (await _get("/v1/glodap/meta")).json()["health"]
    assert h["status"] == "failing" and h["failure"] == "interrupted"        # a stale marker = a killed run


@needs_db
async def test_meta_before_the_first_load_says_not_loaded(conn):
    await _fresh(conn)
    r = await _get("/v1/glodap/meta")
    assert r.status_code == 200
    m = r.json()
    assert m["health"]["status"] == "not_loaded" and m["loaded_at"] is None and m["year_min"] is None


# ── force-sync request ────────────────────────────────────────────────────────────────────────────
@needs_db
async def test_request_refresh_sets_the_flag_and_logs(conn):
    await _fresh(conn)
    out = await gp.request_refresh()
    assert out["requested"] is True
    assert await conn.fetchval("SELECT refresh_requested_at FROM glodap_bottle_source") is not None
    assert "refresh requested" in await conn.fetchval(
        "SELECT skipped_reason FROM sync_log WHERE source = 'glodap-bottles'")
