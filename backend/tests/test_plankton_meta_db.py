# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""GET /v1/plankton/meta: counts only, cached, never a 500 on an empty or missing table."""
import asyncio
import os

import asyncpg
import httpx
import pytest

import db
import response_cache
from domains import plankton as route
from plankton_helpers import conn, needs_db  # noqa: F401

DS = "00000000-0000-0000-0000-000000000001"


@pytest.fixture(autouse=True)
def _clean_cache(monkeypatch):
    response_cache.store.pop("plankton-meta", None)
    for name, value in (("_signature", None), ("_counts_task", None), ("_last_counts", None),
                        ("_no_recount_before", 0.0)):
        monkeypatch.setattr(route, name, value, raising=False)
    yield
    response_cache.store.pop("plankton-meta", None)


async def _get(headers=None, *, authed=True, path="/v1/plankton/meta"):
    """authed: bypass get_api_key — the test connection is ONE shared transaction, and the key
    lookup against api_access tables this DB may not have would abort it. The real dependency
    is exercised by test_meta_without_api_key_is_rejected."""
    import main
    from auth import get_api_key
    if authed:
        main.app.dependency_overrides[get_api_key] = lambda: "test"
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
            return await c.get(path, headers=headers or {})
    finally:
        main.app.dependency_overrides.pop(get_api_key, None)


async def _sync_log(conn):
    await conn.execute("""CREATE TABLE IF NOT EXISTS sync_log (source text PRIMARY KEY,
        last_synced_at timestamptz, records_added integer NOT NULL DEFAULT 0,
        total_records integer NOT NULL DEFAULT 0, skipped_reason text, skipped_at timestamptz)""")


async def _seed(conn, n=2):
    await _sync_log(conn)
    from schema.plankton import ensure_plankton
    await ensure_plankton(conn)
    await conn.execute("INSERT INTO plankton_datasets (dataset_id, title, licence, licence_raw) "
                       f"VALUES ('{DS}','t','cc-by','x')")
    for i in range(n):
        await conn.execute("INSERT INTO plankton_occurrences (taxon_group, dataset_id, licence, is_edna, lon, lat) "
                           f"VALUES ('copepoda','{DS}','cc-by',false,{i},{i})")


@needs_db
async def test_meta_counts_by_group_and_licence(conn):
    await _seed(conn)
    r = await _get()
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2 and body["datasets"] == 1
    assert {"taxon_group": "copepoda", "licence": "cc-by", "records": 2} in body["by_group_licence"]
    assert "occurrences" not in body and "rows" not in body


async def _set_sync(conn, reason):
    await _sync_log(conn)
    await conn.execute("INSERT INTO sync_log (source, last_synced_at, records_added, total_records, "
                       "skipped_reason, skipped_at) VALUES ('plankton-obis', NOW(), 2, 2, $1, "
                       "CASE WHEN $1::text IS NULL THEN NULL ELSE NOW() END) ON CONFLICT (source) DO UPDATE SET "
                       "skipped_reason=$1, skipped_at=CASE WHEN $1::text IS NULL THEN NULL ELSE NOW() END, "
                       "last_synced_at=NOW(), records_added=2, total_records=2", reason)


@needs_db
async def test_meta_success_row_is_swapped(conn):
    await _seed(conn)
    await _set_sync(conn, None)
    li = (await _get()).json()["last_import"]
    assert li["synced_at"] and li["records_added"] == 2 and li["total_records"] == 2
    assert li["outcome"] == "swapped" and li["skipped_at"] is None
    assert "skipped_reason" not in li


@needs_db
@pytest.mark.parametrize("reason,outcome,checks", [
    ("swap blocked — rows dropped 100 -> 10 (more than 30 %); group copepoda has 0 rows",
     "blocked", ["row_drop", "missing_group"]),
    ("swap blocked — group copepoda has 0 rows", "blocked", ["missing_group"]),
    ("swap blocked — rows dropped 100 -> 10 (more than 30 %)", "blocked", ["row_drop"]),
    ("swap lock timeout — live and staging intact", "lock_timeout", None),
    ("low memory — MemAvailable 1 KiB below 2 KiB, import deferred", "low_memory", None),
    ("error: ValueError: whatever", "error", None),
    ("started: import in progress", "running", None),
    ("something nobody ever wrote", "error", None),
])
async def test_meta_outcome_category_mapping(conn, reason, outcome, checks):
    await _seed(conn)
    await _set_sync(conn, reason)
    li = (await _get()).json()["last_import"]
    assert li["outcome"] == outcome and li["skipped_at"]
    assert li.get("blocked_checks") == checks


@needs_db
async def test_meta_failed_datasets_is_an_int_parsed_from_the_token_only(conn):
    await _seed(conn)
    await _set_sync(conn, "swapped with failed datasets: failed_datasets=2 /var/cache/x db.internal")
    r = await _get()
    li = r.json()["last_import"]
    assert li["outcome"] == "swapped" and li["failed_datasets"] == 2 and isinstance(li["failed_datasets"], int)
    for leak in ("/var/cache", "db.internal", "swapped with failed"):
        assert leak not in r.text


@needs_db
@pytest.mark.parametrize("reason", [None, "error: failed_datasets=9", "swap blocked — failed_datasets=9",
                                    "swapped with failed datasets: nothing parseable"])
async def test_meta_failed_datasets_is_zero_unless_a_partial_swap_says_otherwise(conn, reason):
    await _seed(conn)
    await _set_sync(conn, reason)
    li = (await _get()).json()["last_import"]
    assert li["failed_datasets"] == 0


@needs_db
async def test_meta_never_leaks_exception_text(conn):
    await _seed(conn)
    await _set_sync(conn, "error: OSError: [Errno 13] Permission denied: "
                          "'/var/cache/abyssal-plankton/run/x.parquet' at host db.internal")
    r = await _get()
    li = r.json()["last_import"]
    assert li["outcome"] == "error"
    for leak in ("/var/cache", "Errno", "db.internal", "OSError", "Permission"):
        assert leak not in r.text


@needs_db
async def test_meta_empty_tables_is_200_with_zeros(conn):
    from schema.plankton import ensure_plankton
    await _sync_log(conn)
    await ensure_plankton(conn)
    await conn.execute("DELETE FROM sync_log WHERE source = 'plankton-obis'")
    r = await _get()
    assert r.status_code == 200
    assert r.json() == {"total": 0, "datasets": 0, "by_group_licence": [], "last_import": None,
                        "tile_version": None, "tile_built_at": None}


@needs_db
async def test_meta_absent_tables_is_200_with_zeros(conn):
    await _sync_log(conn)
    await conn.execute("DROP TABLE IF EXISTS plankton_occurrences CASCADE")
    await conn.execute("DROP TABLE IF EXISTS plankton_datasets CASCADE")
    r = await _get()
    assert r.status_code == 200
    assert r.json()["total"] == 0 and r.json()["by_group_licence"] == []


@needs_db
async def test_meta_second_call_is_served_from_cache(conn, monkeypatch):
    await _seed(conn)
    first = (await _get()).json()
    await conn.execute(f"INSERT INTO plankton_occurrences (taxon_group, dataset_id, licence, is_edna, lon, lat) "
                       f"VALUES ('copepoda','{DS}','cc-by',false,9,9)")
    second = (await _get()).json()
    assert second == first and second["total"] == 2       # the heavy count did not run again


@needs_db
async def test_meta_new_import_is_visible_immediately(conn):
    """A fresh import moves sync_log; the API process (a different process from the worker,
    so it cannot be told to drop its cache) sees that and recounts."""
    await _seed(conn)
    assert (await _get()).json()["total"] == 2
    await conn.execute(f"INSERT INTO plankton_occurrences (taxon_group, dataset_id, licence, is_edna, lon, lat) "
                       f"VALUES ('copepoda','{DS}','cc-by',false,9,9)")
    await conn.execute("INSERT INTO sync_log (source, last_synced_at, records_added, total_records) "
                       "VALUES ('plankton-obis', NOW(), 3, 3) ON CONFLICT (source) DO UPDATE "
                       "SET last_synced_at = NOW(), records_added = 3, total_records = 3")
    assert (await _get()).json()["total"] == 3


@needs_db
async def test_swap_clears_the_cache_key(conn):
    from ingestion import plankton_obis as po
    response_cache.store["plankton-meta"] = (0.0, "x", b"{}")
    await po.build_staging(conn)
    await po.swap(conn)
    assert "plankton-meta" not in response_cache.store


@needs_db
async def test_meta_without_api_key_is_rejected(conn):
    r = await _get(authed=False)
    assert r.status_code in (401, 403)


@needs_db
async def test_meta_stale_started_marker_is_an_error_and_leaks_nothing(conn):
    from ingestion.plankton_obis import STARTED_PREFIX
    await _seed(conn)
    await _set_sync(conn, STARTED_PREFIX + ": import in progress /var/cache/x")
    await conn.execute("UPDATE sync_log SET skipped_at = now() - interval '13 hours' WHERE source = 'plankton-obis'")
    r = await _get()
    assert r.json()["last_import"]["outcome"] == "error"
    assert "/var/cache" not in r.text and "progress" not in r.text


def test_meta_started_prefix_matches_the_importer():
    from domains import plankton as d
    from ingestion import plankton_obis as p
    assert d.STARTED_PREFIX == p.STARTED_PREFIX


@needs_db
async def test_meta_carries_the_tile_version_and_follows_a_rebuild_at_once(conn, monkeypatch):
    from ingestion import plankton_obis as p
    from plankton_helpers import row, seed_live
    await _sync_log(conn)
    v1 = await seed_live(conn, [row("copepoda", 10.2, 50.2, year=2015)])
    body = (await _get()).json()
    assert body["tile_version"] == v1 and body["tile_built_at"]
    # The worker is another process: its cache reset never reaches the API. Only the signature can.
    monkeypatch.setattr(p, "_forget_meta_cache", lambda: None)
    v2 = await p.rebuild_aggregates_from_live(conn, backoff=())
    assert v2 != v1
    assert (await _get()).json()["tile_version"] == v2


@needs_db
async def test_meta_before_the_first_build_has_no_tile_version(conn):
    await _seed(conn)
    await conn.execute("DELETE FROM plankton_tile_version")
    body = (await _get()).json()
    assert body["tile_version"] is None and body["tile_built_at"] is None


class _SpyConn:
    """Counts (and optionally delays or gates) the recount query; everything else goes through untouched."""
    def __init__(self, conn, spy):
        self._c, self._spy = conn, spy

    async def fetch(self, sql, *a, **k):
        if "GROUP BY 1, 2" in sql:
            self._spy.counts += 1
            self._spy.started.set()
            await self._spy.gate.wait()
        return await self._c.fetch(sql, *a, **k)

    def __getattr__(self, name):
        return getattr(self._c, name)


class _SpyPool:
    def __init__(self, pool):
        self.pool, self.counts = pool, 0
        self.started, self.gate = asyncio.Event(), asyncio.Event()

    def acquire(self):
        spy, inner = self, self.pool.acquire()

        class _Ctx:
            async def __aenter__(self):
                return _SpyConn(await inner.__aenter__(), spy)

            async def __aexit__(self, *exc):
                return await inner.__aexit__(*exc)
        return _Ctx()


@pytest.fixture
async def spy_pool(monkeypatch):
    """A REAL 4-connection pool (concurrent requests need separate connections), wrapped by a recount spy."""
    pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"], min_size=1, max_size=4)
    spy = _SpyPool(pool)
    monkeypatch.setattr(db, "pool", spy)
    yield spy
    spy.gate.set()
    await pool.close()


@needs_db
async def test_concurrent_meta_calls_run_one_count_query(spy_pool):
    tasks = [asyncio.create_task(_get()) for _ in range(5)]
    await asyncio.wait_for(spy_pool.started.wait(), 5)
    await asyncio.sleep(0.3)                         # everyone has reached the recount by now
    spy_pool.gate.set()
    responses = await asyncio.wait_for(asyncio.gather(*tasks), 10)
    assert [r.status_code for r in responses] == [200] * 5
    assert spy_pool.counts == 1


@needs_db
async def test_a_slow_count_does_not_block_the_version_path(spy_pool):
    meta = asyncio.create_task(_get())
    await asyncio.wait_for(spy_pool.started.wait(), 5)   # the recount is running and held back
    r = await asyncio.wait_for(_get(path="/v1/plankton/tile-version"), 3)
    assert r.status_code == 200 and set(r.json()) == {"tile_version", "tile_built_at"}
    assert not meta.done()
    spy_pool.gate.set()
    assert (await asyncio.wait_for(meta, 10)).status_code == 200


@needs_db
async def test_the_version_endpoint_returns_the_live_version(conn):
    from plankton_helpers import row, seed_live
    version = await seed_live(conn, [row("copepoda", 10.2, 50.2, year=2015)])
    body = (await _get(path="/v1/plankton/tile-version")).json()
    assert body["tile_version"] == version and body["tile_built_at"]


SLOW_SQL = ("SELECT 'copepoda'::text AS taxon_group, 'cc-by'::text AS licence, 1::bigint AS records "
            "FROM pg_sleep(1) WHERE 'x' = 'x' GROUP BY 1, 2")


@needs_db
async def test_a_timed_out_count_is_a_503_with_retry_after_never_a_500_or_exception_text(conn, monkeypatch):
    monkeypatch.setattr(route, "COUNT_STATEMENT_TIMEOUT", "100ms")
    monkeypatch.setattr(route, "_COUNT_SQL", SLOW_SQL)
    r = await _get()
    assert r.status_code == 503 and r.headers["retry-after"] == "30"
    assert "statement" not in r.text.lower() and "pg_sleep" not in r.text


@needs_db
async def test_a_timed_out_count_serves_the_last_good_counts(conn, monkeypatch):
    await _seed(conn)
    first = (await _get()).json()
    assert first["total"] == 2 and "counts_stale" not in first
    response_cache.store.pop("plankton-meta", None)           # the cache expired; the recount now times out
    monkeypatch.setattr(route, "COUNT_STATEMENT_TIMEOUT", "100ms")
    monkeypatch.setattr(route, "_COUNT_SQL", SLOW_SQL)
    r = await _get()
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2 and body["counts_stale"] is True
    assert response_cache.store.get("plankton-meta") is None  # a stale answer is never cached

    async def boom():
        raise RuntimeError("a recount started inside the back-off")
    monkeypatch.setattr(route, "_count_occurrences", boom)
    assert (await _get()).json()["counts_stale"] is True       # inside the back-off: no new recount
