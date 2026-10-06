# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""GET /v1/plankton/meta: counts only, cached, never a 500 on an empty or missing table."""
import httpx
import pytest

import response_cache
from plankton_helpers import conn, needs_db  # noqa: F401

DS = "00000000-0000-0000-0000-000000000001"


@pytest.fixture(autouse=True)
def _clean_cache():
    response_cache.store.pop("plankton-meta", None)
    yield
    response_cache.store.pop("plankton-meta", None)


async def _get(headers=None, *, authed=True):
    """authed: bypass get_api_key — the test connection is ONE shared transaction, and the key
    lookup against api_access tables this DB may not have would abort it. The real dependency
    is exercised by test_meta_without_api_key_is_rejected."""
    import main
    from auth import get_api_key
    if authed:
        main.app.dependency_overrides[get_api_key] = lambda: "test"
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
            return await c.get("/v1/plankton/meta", headers=headers or {})
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
    assert r.json() == {"total": 0, "datasets": 0, "by_group_licence": [], "last_import": None}


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
    await conn.execute("UPDATE sync_log SET skipped_at = now() - interval '9 hours' WHERE source = 'plankton-obis'")
    r = await _get()
    assert r.json()["last_import"]["outcome"] == "error"
    assert "/var/cache" not in r.text and "progress" not in r.text


def test_meta_started_prefix_matches_the_importer():
    from domains import plankton as d
    from ingestion import plankton_obis as p
    assert d.STARTED_PREFIX == p.STARTED_PREFIX
