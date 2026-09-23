# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Four offshore syncs used to run without ever writing to `sync_log`.

Measured on production 2026-09-23: `nopta` (254 rows) and `nzpam` (11 rows)
had data but no `sync_log` row, and `mra_png` / `mme_nam` had neither — two
sources failing on every run with nothing anywhere saying so. The staleness
monitor reads `sync_log` only, so all four were invisible to it.

Each path is EXECUTED with the upstream fetch stubbed: a failed fetch and an
empty answer must record a skip reason (never `_log_sync`, which would stamp
`last_synced_at = NOW()`), and a successful run must record the sync.
"""
from __future__ import annotations

import contextlib

import pytest

from domains import offshore

SYNCS = [
    (offshore.sync_nopta_petroleum, "nopta"),
    (offshore.sync_nzpam_offshore, "nzpam"),
    (offshore.sync_mra_png_dsm, "mra_png"),
    (offshore.sync_mme_nam_dsm, "mme_nam"),
]

_FEATURE = {
    "properties": {
        "PERMIT_OFFSHORE_ONSHORE": "Offshore",
        "Title": "T-1", "Number": "N-1", "TENEMENT_NO": "EL-1", "OBJECTID": 1,
        "Status": "Granted", "STATUS": "Granted",
    },
    "geometry": {"type": "Polygon",
                 "coordinates": [[[150, -20], [151, -20], [151, -21], [150, -20]]]},
}


@pytest.fixture
def recorded(monkeypatch):
    calls: list[tuple] = []

    async def _skipped(source, reason):
        calls.append(("skipped", source, reason))

    async def _synced(source, added, total):
        calls.append(("synced", source, added, total))

    async def _upsert(conn, rows):
        return len(rows)

    async def _noop(*a, **k):
        return None

    class _Conn:
        async def fetchval(self, *a, **k):
            return 0

    class _Pool:
        @contextlib.asynccontextmanager
        async def acquire(self):
            yield _Conn()

    monkeypatch.setattr(offshore, "_log_sync_skipped", _skipped)
    monkeypatch.setattr(offshore, "_log_sync", _synced)
    monkeypatch.setattr(offshore, "offshore_upsert", _upsert)
    monkeypatch.setattr(offshore, "offshore_tag_sovereign", _noop)
    monkeypatch.setattr(offshore, "clear_offshore_tile_cache", lambda: None)
    monkeypatch.setattr(offshore.db, "pool", _Pool(), raising=False)
    return calls


def _serve(monkeypatch, result):
    async def _fetch(*a, **k):
        if isinstance(result, Exception):
            raise result
        return result
    monkeypatch.setattr(offshore, "fetch_arcgis_features_url", _fetch)


@pytest.mark.parametrize("sync, key", SYNCS, ids=[k for _, k in SYNCS])
async def test_failed_fetch_records_a_skip(monkeypatch, recorded, sync, key):
    _serve(monkeypatch, RuntimeError("upstream down"))
    assert await sync() == 0
    assert recorded == [("skipped", key, "fetch failed: RuntimeError")]


@pytest.mark.parametrize("sync, key", SYNCS, ids=[k for _, k in SYNCS])
async def test_empty_answer_records_a_skip(monkeypatch, recorded, sync, key):
    _serve(monkeypatch, [])
    assert await sync() == 0
    assert [c[:2] for c in recorded] == [("skipped", key)]


@pytest.mark.parametrize("sync, key", SYNCS, ids=[k for _, k in SYNCS])
async def test_successful_run_records_the_sync(monkeypatch, recorded, sync, key):
    _serve(monkeypatch, [_FEATURE])
    assert await sync() == 1
    assert recorded == [("synced", key, 1, 1)]
