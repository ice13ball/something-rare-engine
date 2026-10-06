# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Orchestrator of the plankton import — real PostGIS, no network (all seams injected)."""
import json
import pathlib
import uuid

import asyncpg
import duckdb
import pytest

from ingestion import plankton_obis as p
from plankton_helpers import conn, needs_db  # noqa: F401  (conn is a fixture)
from schema.plankton import ensure_plankton

FIXDIR = pathlib.Path(__file__).parent / "fixtures" / "plankton_obis"
FIX = FIXDIR / "occurrences.parquet"
LIC = (FIXDIR / "licenses.tsv").read_text(encoding="utf-8")
META = {d["id"]: d for d in json.loads((FIXDIR / "datasets.json").read_text(encoding="utf-8"))}
IDS = [r[0] for r in duckdb.sql(f"SELECT DISTINCT dataset_id FROM read_parquet('{FIX}')").fetchall()]
CPR = "5c4667b8-8d93-4768-bc7e-3c31cde1cf18"   # absent from licenses.tsv


def _api(ids, **override):
    """Fake OBIS /v3/dataset: the same list for every taxonid, paged by `skip`."""
    def fetch_json(url, params):
        assert "offset" not in params
        rs = [{**META[i], **override.get(i, {})} for i in ids][params["skip"]:params["skip"] + params["size"]]
        return {"total": len(ids), "results": rs}
    return fetch_json


def _split_fixture(tmp_path):
    out = {}
    for i in IDS:
        f = tmp_path / f"src-{i}.parquet"
        duckdb.sql(f"COPY (SELECT * FROM read_parquet('{FIX}') WHERE dataset_id = '{i}') TO '{f}' (FORMAT PARQUET)")
        out[i] = str(f)
    return out


async def _setup(conn):
    await conn.execute("""CREATE TABLE IF NOT EXISTS sync_log (source text PRIMARY KEY,
        last_synced_at timestamptz, records_added int, total_records int,
        skipped_reason text, skipped_at timestamptz)""")
    for t in ("plankton_occurrences_new", "plankton_datasets_new", "plankton_occurrences", "plankton_datasets"):
        await conn.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    await ensure_plankton(conn)
    await conn.execute("DELETE FROM sync_log WHERE source = 'plankton-obis'")


async def _run(tmp_path, src, ids=None, lic=LIC, **kw):
    return await p.sync_plankton_obis(
        fetch_json=kw.pop("fetch_json", _api(ids or IDS)), fetch_licences=lambda: lic,
        source_for=kw.pop("source_for", src.__getitem__), scratch=tmp_path / "s", **kw)


@pytest.fixture
def alerts(monkeypatch):
    sent = []

    async def fake_notify(msg, title="", **_):
        sent.append((title, msg))
        return True
    monkeypatch.setattr(p, "notify_telegram", fake_notify)
    return sent


async def _log(conn):
    return await conn.fetchrow("SELECT * FROM sync_log WHERE source = 'plankton-obis'")


@needs_db
async def test_full_sync_swaps_logs_counts_and_stays_silent(conn, tmp_path, alerts):
    await _setup(conn)
    res = await _run(tmp_path, _split_fixture(tmp_path))
    assert res["outcome"] == "swapped", res
    assert res["kept"] == await conn.fetchval("SELECT count(*) FROM plankton_occurrences") > 0
    assert res["total"] == res["kept"]
    assert res["datasets"] == len(IDS)
    assert sum(res["groups"].values()) == res["kept"] and set(res["groups"]) <= set(p.GROUPS)
    assert sum(res["licences"].values()) == res["datasets"]
    assert set(p.DROP_REASONS) <= set(res["drops"]) and res["drops"]["absence"] >= 0
    row = await _log(conn)
    assert row["total_records"] == res["kept"] and row["skipped_reason"] is None
    assert row["last_synced_at"] is not None
    assert alerts == []                                   # success sends nothing
    assert not await conn.fetchval("SELECT to_regclass('plankton_occurrences_new')")
    assert not list((tmp_path / "s").rglob("*.parquet"))  # no extract file survives the run


@needs_db
async def test_dataset_absent_from_licences_tsv_takes_its_licence_from_intellectualrights(conn, tmp_path):
    await _setup(conn)
    assert CPR not in LIC
    res = await _run(tmp_path, _split_fixture(tmp_path))
    assert res["outcome"] == "swapped"
    r = await conn.fetchrow("SELECT licence, licence_raw, citation, record_count FROM plankton_datasets WHERE dataset_id = $1::uuid", CPR)
    assert r["licence"] == "cc-by" and "Creative Commons Attribution" in r["licence_raw"]
    assert r["citation"].startswith("Johns D")            # API citation, tsv has none
    assert r["record_count"] > 0
    assert {x[0] for x in await conn.fetch(
        "SELECT DISTINCT licence FROM plankton_occurrences WHERE dataset_id = $1::uuid", CPR)} == {"cc-by"}
    assert "unknown" not in res["licences"]


@needs_db
async def test_intellectualrights_wins_over_tsv_and_tsv_is_the_fallback(conn, tmp_path):
    await _setup(conn)
    src = _split_fixture(tmp_path)
    tsv_id = LIC.splitlines()[1].split("\t")[0]
    # 1) the API says NC while the tsv says CC-BY: the API wins
    await _run(tmp_path, src, fetch_json=_api(IDS, **{tsv_id: {"intellectualrights": "CC BY-NC 4.0"}}))
    assert {x[0] for x in await conn.fetch(
        "SELECT DISTINCT licence FROM plankton_occurrences WHERE dataset_id = $1::uuid", tsv_id)} == {"cc-by-nc"}
    # 2) the API says nothing: the tsv is the fallback (and its citation is preferred)
    await _run(tmp_path, src, fetch_json=_api(IDS, **{tsv_id: {"intellectualrights": None, "citation": "api cite"}}))
    r = await conn.fetchrow("SELECT licence, citation FROM plankton_datasets WHERE dataset_id = $1::uuid", tsv_id)
    assert r["licence"] == "cc-by" and r["citation"] != "api cite"
    # 3) neither source says anything: unknown, but stored (never dropped silently)
    await _run(tmp_path, src, lic="id\tlicense\tlicense_url\tcitation\n",
               fetch_json=_api(IDS, **{tsv_id: {"intellectualrights": ""}}))
    assert await conn.fetchval("SELECT licence FROM plankton_datasets WHERE dataset_id = $1::uuid", tsv_id) == "unknown"


@needs_db
async def test_licence_change_reaches_every_row_on_the_next_run(conn, tmp_path):
    """Licences are re-resolved on EVERY run: a dataset that changes licence changes its flag."""
    await _setup(conn)
    src = _split_fixture(tmp_path)
    q_rows = "SELECT licence FROM plankton_occurrences WHERE dataset_id = $1::uuid"
    await _run(tmp_path, src)                                    # CPR: intellectualrights says CC-BY
    first = [r[0] for r in await conn.fetch(q_rows, CPR)]
    assert first and set(first) == {"cc-by"}
    nc = {CPR: {"intellectualrights": "This work is licensed under CC BY-NC 4.0 (Attribution-NonCommercial)"}}
    await _run(tmp_path, src, fetch_json=_api(IDS, **nc))        # same process, same module: next run
    second = [r[0] for r in await conn.fetch(q_rows, CPR)]
    assert len(second) == len(first) and set(second) == {"cc-by-nc"}
    assert await conn.fetchval("SELECT licence FROM plankton_datasets WHERE dataset_id = $1::uuid", CPR) == "cc-by-nc"


@needs_db
async def test_restricted_dataset_is_never_stored(conn, tmp_path):
    await _setup(conn)
    res = await _run(tmp_path, _split_fixture(tmp_path),
                     fetch_json=_api(IDS, **{CPR: {"intellectualrights": "Restricted - contact the owner"}}))
    assert res["outcome"] == "swapped"      # the other datasets still carry every group
    assert not await conn.fetchval("SELECT count(*) FROM plankton_occurrences WHERE dataset_id = $1::uuid", CPR)
    assert res["skipped_datasets"] == 1      # skipped before its file was read, so no per-row drop count


@needs_db
async def test_blocked_validation_discards_staging_keeps_live_logs_reasons_and_alerts(conn, tmp_path, alerts):
    await _setup(conn)
    src = _split_fixture(tmp_path)
    await _run(tmp_path, src)
    before = await conn.fetchval("SELECT count(*) FROM plankton_occurrences")
    ok_log = await _log(conn)
    res = await _run(tmp_path, src, ids=IDS[:1])
    assert res["outcome"] == "blocked" and res["reasons"]
    assert await conn.fetchval("SELECT count(*) FROM plankton_occurrences") == before
    assert not await conn.fetchval("SELECT to_regclass('plankton_occurrences_new')")
    row = await _log(conn)
    assert row["skipped_reason"].startswith("swap blocked") and res["reasons"][0] in row["skipped_reason"]
    assert row["total_records"] == ok_log["total_records"]    # log_sync_skipped leaves the count alone
    assert len(alerts) == 1 and "TRIP" in alerts[0][0] and res["reasons"][0] in alerts[0][1]


@needs_db
async def test_swap_lock_timeout_logs_alerts_and_leaves_live_and_staging_intact(conn, tmp_path, alerts, monkeypatch):
    await _setup(conn)
    src = _split_fixture(tmp_path)
    await _run(tmp_path, src)
    before = await conn.fetchval("SELECT count(*) FROM plankton_occurrences")

    async def locked(c, **_):
        raise p.SwapLockTimeout("held")
    monkeypatch.setattr(p, "swap", locked)
    res = await _run(tmp_path, src)
    assert res["outcome"] == "lock_timeout"
    assert await conn.fetchval("SELECT count(*) FROM plankton_occurrences") == before
    assert await conn.fetchval("SELECT count(*) FROM plankton_occurrences_new") > 0   # staging kept
    assert (await _log(conn))["skipped_reason"] == "swap lock timeout — live and staging intact"
    assert len(alerts) == 1 and "TRIP" in alerts[0][0]


@needs_db
async def test_an_exception_mid_run_logs_type_and_message_alerts_and_leaves_live_alone(
        conn, tmp_path, alerts, monkeypatch):
    await _setup(conn)
    src = _split_fixture(tmp_path)
    await _run(tmp_path, src)
    before = await conn.fetchval("SELECT count(*) FROM plankton_occurrences")

    async def boom(*_a, **_k):      # outside the per-dataset isolation (a failing dataset is only skipped)
        raise RuntimeError("DB went away at https://example.org/x?token=SECRET")
    monkeypatch.setattr(p, "swap_validated", boom)
    res = await _run(tmp_path, src)
    assert res["outcome"] == "error"
    reason = (await _log(conn))["skipped_reason"]
    assert reason.startswith("error: RuntimeError") and "DB went away" in reason
    assert "SECRET" not in reason and "SECRET" not in alerts[0][1]
    assert await conn.fetchval("SELECT count(*) FROM plankton_occurrences") == before
    assert not await conn.fetchval("SELECT to_regclass('plankton_occurrences_new')")
    assert len(alerts) == 1 and "TRIP" in alerts[0][0]


@needs_db
async def test_datasets_are_processed_one_at_a_time_and_each_extract_is_deleted(conn, tmp_path):
    await _setup(conn)
    src = _split_fixture(tmp_path)
    alive_at_next_dataset = []
    scratch = tmp_path / "s"

    def source_for(i):
        alive_at_next_dataset.append(len(list(scratch.rglob("*.parquet"))))
        return src[i]
    await _run(tmp_path, src, source_for=source_for)
    assert alive_at_next_dataset and max(alive_at_next_dataset) == 0


async def test_dataset_selection_paginates_with_skip_not_offset():
    seen = []

    def fetch_json(url, params):
        seen.append(dict(params))
        assert "offset" not in params
        if params["skip"] >= 150:
            return {"total": 150, "results": []}
        return {"total": 150, "results": [{"id": str(uuid.UUID(int=params["taxonid"] * 1000 + params["skip"] + k))}
                                           for k in range(100 if params["skip"] == 0 else 50)]}
    ds = await p.select_datasets(fetch_json)
    assert any(pp["skip"] == 100 for pp in seen)
    assert len(ds) == 150 * len(p.TAXON_IDS)


async def test_dataset_selection_dedupes_across_taxonids():
    a, b = str(uuid.UUID(int=1)), str(uuid.UUID(int=2))

    def fetch_json(url, params):
        return {"total": 2, "results": [{"id": a}, {"id": b}][params["skip"]:]}
    assert set(await p.select_datasets(fetch_json)) == {a, b}


async def test_dataset_selection_includes_haptophyta():
    assert 369190 in p.TAXON_IDS


async def test_dataset_selection_rejects_unsafe_ids_and_canonicalises_valid_ones():
    good = "5C4667B8-8D93-4768-BC7E-3C31CDE1CF18"
    ok = [good, "{5c4667b8-8d93-4768-bc7e-3c31cde1cf19}"]
    bad = ["../../evil", "abc", "", None, "5c4667b8-8d93-4768-bc7e-3c31cde1cf18/../x"]

    def fetch_json(url, params):
        rs = [{"id": i} for i in ok + bad]
        return {"total": len(rs), "results": rs[params["skip"]:]}
    ds = await p.select_datasets(fetch_json)
    assert set(ds) == {good.lower(), "5c4667b8-8d93-4768-bc7e-3c31cde1cf19"}
    assert all(m["id"] == k for k, m in ds.items())


AM = "b508f7bc-8708-43d5-b940-e44f2765d1af"   # Australian Microbiome 18S (DNADerivedData rows)
TITLE_TRAP = "11111111-2222-3333-4444-555555555555"


@needs_db
async def test_is_edna_comes_only_from_the_per_row_rule_not_from_the_title(conn, tmp_path):
    await _setup(conn)
    src = _split_fixture(tmp_path)
    # CPR rows (empty DNA list) re-labelled as a dataset whose TITLE screams eDNA
    trap = tmp_path / "trap.parquet"
    duckdb.sql(f"COPY (SELECT * REPLACE ('{TITLE_TRAP}' AS dataset_id) FROM read_parquet('{src[CPR]}')) "
               f"TO '{trap}' (FORMAT PARQUET)")
    src[TITLE_TRAP] = str(trap)
    meta = {**META[CPR], "id": TITLE_TRAP, "title": "Plankton omics microbiome sequencing 18S metabarcoding"}
    api = lambda url, params: {"total": 5, "results": ([*META.values(), meta])[params["skip"]:]}  # noqa: E731
    res = await _run(tmp_path, src, fetch_json=api)
    assert res["outcome"] == "swapped", res
    q = "SELECT is_edna, count(*) FROM plankton_occurrences WHERE dataset_id = $1::uuid GROUP BY 1"
    for ds, want in ((CPR, False), (TITLE_TRAP, False), (AM, True)):
        got = {r[0]: r[1] for r in await conn.fetch(q, ds)}
        assert got and set(got) == {want}, (ds, got)


# ---- final fix wave -------------------------------------------------------------------------
BAD = "8726cede-98ab-4c06-859d-ce997e8f9717"      # copepoda only: losing it leaves every group present


@needs_db
async def test_one_failing_dataset_does_not_abort_the_run(conn, tmp_path, alerts, caplog):
    await _setup(conn)
    src = _split_fixture(tmp_path)
    src[BAD] = str(tmp_path / "missing.parquet")      # the API lists it, S3 has no file
    res = await _run(tmp_path, src)
    assert res["outcome"] == "swapped" and res["failed_datasets"] == 1
    assert not await conn.fetchval("SELECT count(*) FROM plankton_occurrences WHERE dataset_id = $1::uuid", BAD)
    assert await conn.fetchval("SELECT count(*) FROM plankton_occurrences") > 0
    # RR1: loud. One alert naming the count and the dataset; the sync_log row carries the token.
    assert len(alerts) == 1
    title, msg = alerts[0]
    assert title == p.ALERT_TITLE and "1 of" in msg and BAD in msg and "missing.parquet" not in msg
    row = await _log(conn)
    assert row["last_synced_at"] is not None and row["skipped_reason"] == f"{p.SWAPPED_PARTIAL_PREFIX}: failed_datasets=1"
    from domains.plankton import _last_import
    last = await _last_import(conn)
    assert last["outcome"] == "swapped" and last["failed_datasets"] == 1
    assert "missing.parquet" not in json.dumps(last)
    warned = " ".join(r.getMessage() for r in caplog.records if r.levelname == "WARNING")
    assert BAD in warned and "missing.parquet" not in warned     # id + exception type, never the source


def test_failure_threshold_is_max_3_or_2_percent_and_safe_for_zero_attempts():
    assert [p.failure_threshold(n) for n in (0, 1, 150, 151, 200, 201, 1000)] == [3, 3, 3, 4, 4, 5, 20]


@needs_db
async def test_more_failures_than_the_threshold_means_no_swap_an_error_and_an_alert(conn, tmp_path, alerts, monkeypatch):
    await _setup(conn)
    src = _split_fixture(tmp_path)
    await _run(tmp_path, src)                              # a live table to protect
    alerts.clear()
    live = await conn.fetchval("SELECT count(*) FROM plankton_occurrences")
    monkeypatch.setattr(p, "FAILED_FLOOR", 1)             # 4 datasets: threshold max(1, ceil(0.08)) = 1
    broken = [i for i in IDS if i != IDS[0]][:2]
    for i in broken:
        src[i] = str(tmp_path / f"gone-{i}.parquet")
    res = await _run(tmp_path, src)
    assert res["outcome"] == "error" and "too many datasets failed" in res["reasons"][0]
    assert await conn.fetchval("SELECT count(*) FROM plankton_occurrences") == live       # live untouched
    assert not await conn.fetchval("SELECT to_regclass('plankton_occurrences_new')")      # staging discarded
    assert len(alerts) == 1 and "2 of" in alerts[0][1] and all(i in alerts[0][1] for i in broken)
    row = await _log(conn)
    assert row["skipped_reason"].startswith("error: too many datasets failed") and broken[0] in row["skipped_reason"]


@needs_db
async def test_at_the_threshold_the_swap_still_happens(conn, tmp_path, alerts, monkeypatch):
    await _setup(conn)
    src = _split_fixture(tmp_path)
    monkeypatch.setattr(p, "FAILED_FLOOR", 2)
    broken = [BAD, "cd42b44b-2560-450d-88e7-70b5778d0194"]     # every group survives without these two
    for i in broken:
        src[i] = str(tmp_path / f"gone-{i}.parquet")
    res = await _run(tmp_path, src)
    assert res["outcome"] == "swapped" and res["failed_datasets"] == 2
    assert len(alerts) == 1 and "2 of" in alerts[0][1]
    assert (await _log(conn))["skipped_reason"].endswith("failed_datasets=2")


@needs_db
async def test_every_attempted_dataset_failing_is_an_error_whatever_the_threshold(conn, tmp_path, alerts, monkeypatch):
    await _setup(conn)
    src = _split_fixture(tmp_path)
    monkeypatch.setattr(p, "FAILED_FLOOR", 100)           # threshold far above the failure count
    res = await _run(tmp_path, {i: str(tmp_path / f"gone-{i}.parquet") for i in IDS})
    assert res["outcome"] == "error" and "every attempted dataset failed" in res["reasons"][0]
    assert len(alerts) == 1 and f"{len(IDS)} of {len(IDS)}" in alerts[0][1]
    assert not await conn.fetchval("SELECT to_regclass('plankton_occurrences_new')")


@needs_db
async def test_a_failure_to_list_nothing_attempted_is_not_a_failure(conn, tmp_path, alerts):
    """attempted == 0 must not divide, raise on `failed == attempted` (0 == 0) or alert."""
    await _setup(conn)
    res = await _run(tmp_path, {}, fetch_json=_api([]))
    assert res["outcome"] == "blocked" and res.get("failed_datasets", 0) == 0       # the empty-group check, as before
    assert not any("datasets failed" in m for _, m in alerts)


@needs_db
@pytest.mark.parametrize("exc", [asyncpg.exceptions.ConnectionDoesNotExistError("connection was closed"),
                                 asyncpg.InterfaceError("connection is closed"),
                                 ConnectionResetError("reset")])
async def test_a_lost_connection_ends_the_run_without_touching_the_remaining_datasets(
        conn, tmp_path, alerts, monkeypatch, exc):
    await _setup(conn)
    src = _split_fixture(tmp_path)
    extracted, loaded = [], []
    real = p.extract_dataset

    def spy(con, source, dest, **kw):
        extracted.append(source)
        return real(con, source, dest, **kw)

    async def dead(c, path, lic):
        loaded.append(path)
        raise exc
    monkeypatch.setattr(p, "extract_dataset", spy)
    monkeypatch.setattr(p, "load_extract", dead)
    res = await _run(tmp_path, src)
    assert res["outcome"] == "error"
    assert len(extracted) == 1 and len(loaded) == 1       # NOT one per dataset
    assert len(alerts) == 1 and "datasets failed" not in alerts[0][1]     # diagnosed as an error, not a data problem


@needs_db
async def test_a_closed_connection_after_a_failure_ends_the_run(conn, tmp_path, alerts, monkeypatch):
    await _setup(conn)
    src = _split_fixture(tmp_path)
    extracted = []
    real = p.extract_dataset

    def spy(con, source, dest, **kw):
        extracted.append(source)
        return real(con, source, dest, **kw)

    closed = []

    async def boom(c, path, lic):
        closed.append(1)                                  # the connection dies during this load ...
        raise ValueError("looks like a data problem")     # ... but surfaces as a generic error
    monkeypatch.setattr(p, "extract_dataset", spy)
    monkeypatch.setattr(p, "load_extract", boom)
    monkeypatch.setattr(type(conn), "is_closed", lambda self: bool(closed), raising=False)
    try:
        res = await _run(tmp_path, src)
    finally:
        monkeypatch.undo()
    assert res["outcome"] == "error" and len(extracted) == 1


@needs_db
async def test_a_failing_load_leaves_no_partial_extract_and_live_untouched(conn, tmp_path, alerts, monkeypatch):
    await _setup(conn)
    src = _split_fixture(tmp_path)
    await _run(tmp_path, src)
    before = await conn.fetchval("SELECT count(*) FROM plankton_occurrences")
    real = p.load_extract

    async def half_load_then_boom(c, path, lic):
        await real(c, path, lic)
        raise ValueError("corrupt")
    monkeypatch.setattr(p, "load_extract", half_load_then_boom)
    res = await _run(tmp_path, src)
    assert res["outcome"] in ("blocked", "error")           # every dataset failed: the drop check blocks the swap
    assert await conn.fetchval("SELECT count(*) FROM plankton_occurrences") == before
    assert not list((tmp_path / "s").rglob("*.parquet"))


@needs_db
async def test_excluded_and_restricted_datasets_are_not_read(conn, tmp_path, monkeypatch):
    await _setup(conn)
    src = _split_fixture(tmp_path)
    excluded = "cd42b44b-2560-450d-88e7-70b5778d0194"      # CPR (restricted below) is not the only carrier
    monkeypatch.setattr(p, "EXCLUDED_DATASETS", frozenset({excluded}))
    asked = []
    real = p.extract_dataset

    def spy(con, source, dest, **kw):
        asked.append(source)
        return real(con, source, dest, **kw)
    monkeypatch.setattr(p, "extract_dataset", spy)
    res = await _run(tmp_path, src, fetch_json=_api(IDS, **{CPR: {"intellectualrights": "Restricted - ask"}}))
    assert src[excluded] not in asked and src[CPR] not in asked
    assert len(asked) == len(IDS) - 2 and res["skipped_datasets"] == 2


@needs_db
async def test_licences_tsv_failure_is_a_warning_not_an_abort(conn, tmp_path, caplog):
    await _setup(conn)
    src = _split_fixture(tmp_path)

    def down():
        raise OSError("licenses.tsv unreachable https://x.example/licenses.tsv?k=SECRET")
    res = await p.sync_plankton_obis(fetch_json=_api(IDS), fetch_licences=down,
                                     source_for=src.__getitem__, scratch=tmp_path / "s")
    assert res["outcome"] == "swapped"          # licences come from intellectualrights; the tsv is a fallback
    text = " ".join(r.getMessage() for r in caplog.records if r.levelname == "WARNING")
    assert "licen" in text.lower() and "SECRET" not in text


def test_http_text_retries_transient_failures(monkeypatch):
    calls = []

    class _R:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"id\tlicense\n"

    def flaky(url, timeout=None):
        calls.append(url)
        if len(calls) < 3:
            raise OSError("reset")
        return _R()
    monkeypatch.setattr(p.urllib.request, "urlopen", flaky)
    monkeypatch.setattr(p.time, "sleep", lambda s: None)
    assert p._http_text("https://example.org/x.tsv").startswith("id")
    assert len(calls) == 3


@needs_db
async def test_started_marker_is_written_before_any_work_and_cleared_by_success(conn, tmp_path, monkeypatch):
    await _setup(conn)
    seen = []
    real = p._import

    async def peek(*a, **k):
        seen.append(await _log(conn))
        return await real(*a, **k)
    monkeypatch.setattr(p, "_import", peek)
    res = await _run(tmp_path, _split_fixture(tmp_path))
    assert res["outcome"] == "swapped"
    assert seen[0]["skipped_reason"].startswith(p.STARTED_PREFIX) and seen[0]["skipped_at"]
    assert (await _log(conn))["skipped_reason"] is None


@needs_db
async def test_started_marker_survives_a_killed_run(conn, tmp_path, monkeypatch):
    """SIGKILL / OOM runs no except-block: the marker is all that is left behind."""
    await _setup(conn)

    async def killed(*a, **k):
        raise KeyboardInterrupt            # BaseException: no handler of the orchestrator catches it
    monkeypatch.setattr(p, "_import", killed)
    with pytest.raises(KeyboardInterrupt):
        await _run(tmp_path, {})
    assert (await _log(conn))["skipped_reason"].startswith(p.STARTED_PREFIX)


@needs_db
async def test_unusable_scratch_dir_is_logged_alerted_and_never_raises(conn, tmp_path, alerts):
    await _setup(conn)
    blocker = tmp_path / "file"
    blocker.write_text("x")
    res = await p.sync_plankton_obis(fetch_json=_api(IDS), fetch_licences=lambda: LIC,
                                     source_for=lambda i: "", scratch=blocker)   # <file>/run cannot be created
    assert res["outcome"] == "error"
    assert (await _log(conn))["skipped_reason"] == p.SCRATCH_REASON
    assert str(blocker) not in p.SCRATCH_REASON
    assert len(alerts) == 1 and "TRIP" in alerts[0][0]
