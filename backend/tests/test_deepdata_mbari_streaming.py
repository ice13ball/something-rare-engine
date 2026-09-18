# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""deepdata_ingest and mbari_vars_ingest used to return `list[dict]` — the
whole result set (~201,323 / ~175,476 rows today) built in memory before a
single row was written. On a process that also runs every other sync, that
was ~250-350MB held per run, measured contributing to a 6GB cgroup / 3.3GB
swap peak on a 15GB box (2026-09-18).

Both now yield page-sized lists — the same `AsyncIterator[list[dict]]` shape
as `noaa_corals_ingest.fetch_noaa_corals_records` — and the two callers in
`domains/biodiversity.py` (`sync_deepdata`, `sync_mbari_vars`) upsert each
page as it arrives.

Three failure modes this file guards, each one a way the streaming rewrite
could look done while quietly regressing:

1. The ingest still builds one list internally and fakes an iterator
   (nothing actually streams — memory is never reduced).
2. The caller only consumes/writes the FIRST page — a sync that "succeeds"
   with a fraction of the rows and no error.
3. `_log_sync` gets `len(last_page)` instead of the running total across
   every page, so the row count in the monitor undercounts real work.

A fourth test documents the atomicity decision made in the two sync
functions' docstrings: a mid-walk failure leaves earlier pages committed
(the upsert is `ON CONFLICT DO NOTHING`, so a retry from page 1 is safe) but
must NOT reach `_log_sync` — a failed run must not be stamped as a fresh one.
"""
import os
import uuid as _uuid
from datetime import datetime, timezone

import pytest

import db
from domains import biodiversity
from ingestion import deepdata_ingest, mbari_vars_ingest


# ─────────────────────────────────────────────────────────────────────────────
# Shared fixtures / fakes
# ─────────────────────────────────────────────────────────────────────────────

def _canonical_row(n: int, obis_id: str | None = None) -> dict:
    """A row dict carrying every column either sync's `cols` list needs —
    the union of `sync_deepdata` and `sync_mbari_vars`'s columns."""
    return {
        "obis_id":         obis_id or f"row-{n}",
        "occurrence_id":   None,
        "dataset_id":      None,
        "dataset_title":   None,
        "contractor_code": None,
        "rights_holder":   None,
        "scientific_name": "Testus fakeii",
        "phylum":          None,
        "class_":          None,
        "order_":          None,
        "family":          None,
        "genus":           None,
        "species":         None,
        "basis_of_record": None,
        "depth_m":         100.0 + n,
        "lat":             10.0 + n,
        "lon":             20.0 + n,
        "event_date":      None,
        "locality":        None,
    }


def _pages_gen(pages):
    """Returns a zero-arg callable matching `fetch_deepdata_records`'s /
    `fetch_mbari_records`'s signature: calling it produces a fresh async
    generator yielding `pages` in order."""
    def _factory():
        async def _gen():
            for p in pages:
                yield p
        return _gen()
    return _factory


class _FakeConn:
    """Records every `executemany` call so a test can prove EVERY page
    reached the DB, not just the first."""

    def __init__(self, total_after):
        self.executemany_calls: list[list[tuple]] = []
        self._total_after = total_after

    async def executemany(self, sql, args):
        self.executemany_calls.append(list(args))

    async def fetchval(self, sql):
        return self._total_after


class _Acquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class _PoolFromConn:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _Acquire(self._conn)


def _occ(idx: int) -> dict:
    """A minimal OBIS occurrence record — enough for the ingest's own
    coordinate/id filtering to accept it."""
    return {
        "id": f"occ-{idx}",
        "decimalLatitude": 10.0 + idx,
        "decimalLongitude": 20.0 + idx,
        "occurrenceID": None,
        "dataset_id": None,
        "scientificName": "Testus fakeii",
    }


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeAsyncClient:
    """Serves canned OBIS occurrence pages in order, one per `get` call.
    Also answers the dataset-map probe deepdata_ingest makes first, with an
    empty result set (contractor parsing is out of scope for this file)."""

    def __init__(self, occurrence_pages, dataset_url=None):
        self._pages = list(occurrence_pages)
        self._dataset_url = dataset_url
        self._occurrence_calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, params=None):
        if self._dataset_url is not None and url == self._dataset_url:
            return _FakeResp({"results": [], "total": 0})
        idx = self._occurrence_calls
        self._occurrence_calls += 1
        page = self._pages[idx] if idx < len(self._pages) else []
        return _FakeResp({"results": page})


# ─────────────────────────────────────────────────────────────────────────────
# 1. The ingest yields pages instead of building one list (network stubbed).
# ─────────────────────────────────────────────────────────────────────────────

async def test_deepdata_ingest_yields_multiple_pages_not_one_list(monkeypatch):
    monkeypatch.setattr(deepdata_ingest, "PAGE_SIZE", 2)
    occurrence_pages = [
        [_occ(0), _occ(1)],   # full page (== PAGE_SIZE) -> continue
        [_occ(2), _occ(3)],   # full page -> continue
        [_occ(4)],            # short page -> stop after this one
    ]
    monkeypatch.setattr(
        deepdata_ingest.httpx, "AsyncClient",
        lambda **kw: _FakeAsyncClient(occurrence_pages, dataset_url=deepdata_ingest.OBIS_DATASET_URL),
    )

    gen = deepdata_ingest.fetch_deepdata_records()
    assert hasattr(gen, "__anext__"), "fetch_deepdata_records must return an async iterator, not a list"

    pages = [p async for p in gen]
    assert len(pages) == 3, f"expected 3 yielded pages, got {len(pages)} — pagination is not streaming"
    assert [len(p) for p in pages] == [2, 2, 1]
    assert sum(len(p) for p in pages) == 5


async def test_mbari_ingest_yields_multiple_pages_not_one_list(monkeypatch):
    monkeypatch.setattr(mbari_vars_ingest, "PAGE_SIZE", 2)
    occurrence_pages = [
        [_occ(0), _occ(1)],
        [_occ(2)],
    ]
    monkeypatch.setattr(
        mbari_vars_ingest.httpx, "AsyncClient",
        lambda **kw: _FakeAsyncClient(occurrence_pages),
    )

    gen = mbari_vars_ingest.fetch_mbari_records()
    assert hasattr(gen, "__anext__"), "fetch_mbari_records must return an async iterator, not a list"

    pages = [p async for p in gen]
    assert len(pages) == 2, f"expected 2 yielded pages, got {len(pages)}"
    assert sum(len(p) for p in pages) == 3


# ─────────────────────────────────────────────────────────────────────────────
# 2. The caller writes EVERY page, and logs the SUM across pages.
# ─────────────────────────────────────────────────────────────────────────────

async def test_sync_deepdata_writes_every_page_and_logs_the_running_total(monkeypatch):
    """A caller that only consumed the first page would still 'succeed' —
    fewer rows, no error, nothing in the logs to flag it. This asserts the
    number of writes equals the number of pages, and that `_log_sync` gets
    the SUM across pages, not `len(last page)`."""
    pages = [
        [_canonical_row(0), _canonical_row(1)],
        [_canonical_row(2)],
        [_canonical_row(3), _canonical_row(4)],
    ]
    monkeypatch.setattr(deepdata_ingest, "fetch_deepdata_records", _pages_gen(pages))

    fake_conn = _FakeConn(total_after=999)
    monkeypatch.setattr(db, "pool", _PoolFromConn(fake_conn))

    logged = {}

    async def _fake_log_sync(source, added, total):
        logged["source"], logged["added"], logged["total"] = source, added, total

    monkeypatch.setattr(biodiversity, "_log_sync", _fake_log_sync)

    result = await biodiversity.sync_deepdata()

    assert len(fake_conn.executemany_calls) == len(pages), (
        f"{len(fake_conn.executemany_calls)} executemany call(s) for {len(pages)} pages — "
        "a page was consumed by the generator but never written"
    )
    written = sum(len(c) for c in fake_conn.executemany_calls)
    assert written == 5, f"only {written} of 5 rows across all pages were written"

    assert logged == {"source": "deepdata", "added": 5, "total": 999}, (
        f"{logged} — added must be the SUM across pages (5), not e.g. "
        "len(last page) == 2"
    )
    assert result == 999


async def test_sync_mbari_writes_every_page_and_logs_the_running_total(monkeypatch):
    pages = [
        [_canonical_row(0)],
        [_canonical_row(1), _canonical_row(2), _canonical_row(3)],
    ]
    monkeypatch.setattr(mbari_vars_ingest, "fetch_mbari_records", _pages_gen(pages))

    fake_conn = _FakeConn(total_after=42)
    monkeypatch.setattr(db, "pool", _PoolFromConn(fake_conn))

    logged = {}

    async def _fake_log_sync(source, added, total):
        logged["source"], logged["added"], logged["total"] = source, added, total

    monkeypatch.setattr(biodiversity, "_log_sync", _fake_log_sync)

    result = await biodiversity.sync_mbari_vars()

    assert len(fake_conn.executemany_calls) == len(pages), (
        f"{len(fake_conn.executemany_calls)} executemany call(s) for {len(pages)} pages"
    )
    written = sum(len(c) for c in fake_conn.executemany_calls)
    assert written == 4

    assert logged == {"source": "mbari-vars", "added": 4, "total": 42}, (
        f"{logged} — added must be the SUM across pages (4), not e.g. "
        "len(last page) == 3"
    )
    assert result == 42


# ─────────────────────────────────────────────────────────────────────────────
# 3. Zero-page path: an early return must still call `_log_sync`.
# ─────────────────────────────────────────────────────────────────────────────

async def test_a_zero_page_deepdata_run_still_logs(monkeypatch):
    """The engine rule (CLAUDE.md): every early return needs `_log_sync`,
    or the monitor cannot tell 'ran, found nothing' from 'never ran'. The
    OLD code returned 0 on an empty result WITHOUT calling `_log_sync` at
    all — this guards that the streamed version does not repeat it."""
    monkeypatch.setattr(deepdata_ingest, "fetch_deepdata_records", _pages_gen([]))

    fake_conn = _FakeConn(total_after=0)
    monkeypatch.setattr(db, "pool", _PoolFromConn(fake_conn))

    logged = {}

    async def _fake_log_sync(source, added, total):
        logged["source"], logged["added"], logged["total"] = source, added, total

    monkeypatch.setattr(biodiversity, "_log_sync", _fake_log_sync)

    result = await biodiversity.sync_deepdata()

    assert logged == {"source": "deepdata", "added": 0, "total": 0}, (
        "a run with zero pages must still call _log_sync — otherwise a "
        "genuinely empty upstream response is indistinguishable from a sync "
        "that never ran"
    )
    assert result == 0
    assert fake_conn.executemany_calls == []


# ─────────────────────────────────────────────────────────────────────────────
# 4. Mid-walk failure: the atomicity decision, against a real database.
# ─────────────────────────────────────────────────────────────────────────────

pytestmark_db = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)


class _RealAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class _RealPoolFromConn:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _RealAcquire(self._conn)


@pytest.fixture
async def real_conn():
    import asyncpg
    c = await asyncpg.connect(os.environ["TEST_DATABASE_URL"])
    tx = c.transaction()
    await tx.start()
    try:
        yield c
    finally:
        await tx.rollback()      # nothing here is ever committed
        await c.close()


@pytestmark_db
async def test_a_mid_walk_failure_leaves_earlier_pages_committed_but_does_not_log_a_fresh_sync(
    monkeypatch, real_conn,
):
    """The atomicity decision documented in `sync_deepdata`'s docstring:

    Streaming means a failure on page 2 leaves page 1 already upserted —
    unlike the old list-based version, where nothing was written until the
    ENTIRE fetch succeeded. We accept that because the upsert is
    `ON CONFLICT DO NOTHING` on `obis_id` (a retry from page 1 just re-skips
    the rows already there), and because the exception still propagates
    BEFORE `_log_sync` is reached — so the failed run is never stamped as a
    fresh sync. This test proves both halves of that trade-off at once.
    """
    monkeypatch.setattr(db, "pool", _RealPoolFromConn(real_conn))

    stale_synced_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    await real_conn.execute(
        """INSERT INTO sync_log (source, last_synced_at, records_added, total_records)
           VALUES ('deepdata', $1, 11, 22)
           ON CONFLICT (source) DO UPDATE
           SET last_synced_at = $1, records_added = 11, total_records = 22""",
        stale_synced_at,
    )

    id_a, id_b = str(_uuid.uuid4()), str(_uuid.uuid4())
    good_page = [_canonical_row(0, obis_id=id_a), _canonical_row(1, obis_id=id_b)]

    async def _one_page_then_fail():
        yield good_page
        raise RuntimeError("simulated OBIS timeout on page 2")

    monkeypatch.setattr(deepdata_ingest, "fetch_deepdata_records", lambda: _one_page_then_fail())

    with pytest.raises(RuntimeError, match="simulated OBIS timeout"):
        await biodiversity.sync_deepdata()

    # (a) page 1's rows persist even though the overall run failed.
    rows = await real_conn.fetch(
        "SELECT obis_id FROM deepdata_occurrences WHERE obis_id IN ($1, $2)",
        id_a, id_b,
    )
    assert {str(r["obis_id"]) for r in rows} == {id_a, id_b}, (
        "page 1 was upserted before the failure but is not visible — "
        "streaming should commit earlier pages, not buffer everything until the end"
    )

    # (b) the failed run must not be mistaken for a fresh, successful sync.
    row = await real_conn.fetchrow(
        "SELECT last_synced_at, records_added, total_records FROM sync_log WHERE source = 'deepdata'"
    )
    assert row["last_synced_at"] == stale_synced_at, (
        "_log_sync ran even though the walk raised — a failed sync must not "
        "look freshly synced to the staleness monitor"
    )
    assert row["records_added"] == 11 and row["total_records"] == 22, (
        "the stale sync_log row was overwritten by a run that did not complete"
    )
