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

Extended 2026-09-23: an audit found ~20 more failure/empty exit paths across
the rest of the offshore concession syncs with no `sync_log` write at all.
Each newly-added `_log_sync_skipped` / `_log_sync` call below is exercised
the same way — fetch stubbed to fail, to return nothing, or to succeed.
"""
from __future__ import annotations

import contextlib
import io
import zipfile

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


# ── 2026-09-23 audit: the ~20 additional untraced paths ─────────────────────
# `total` in the success call comes from a live `SELECT COUNT(*)`, which the
# `recorded` fixture's fake connection always answers with 0 — so for the
# syncs that log `total` instead of `len(rows)` we only assert the source key
# and the inserted count, not the (fixture-artifact) total.

# Group A — single fetch_arcgis_features_url call; both the fetch-exception
# and the empty-result exits got a new trace this session.
SYNCS_FETCH_AND_EMPTY = [
    (offshore.sync_crown_estate_wind, "crown_estate"),
    (offshore.sync_sodir_petroleum, "sodir"),
    (offshore.sync_nsta_petroleum, "nsta"),
    (offshore.sync_esdm_indonesia, "esdm"),
    (offshore.sync_sodir_co2, "sodir_co2"),
    (offshore.sync_nsta_co2, "nsta_co2"),
    (offshore.sync_anh_colombia, "anh_co"),
    (offshore.sync_meei_trinidad, "meei_tt"),
    (offshore.sync_pad_ireland, "pad_ie"),
    (offshore.sync_perupetro, "perupetro_pe"),
    (offshore.sync_petrocom_ghana, "petrocom_gh"),
]


@pytest.mark.parametrize("sync, key", SYNCS_FETCH_AND_EMPTY, ids=[k for _, k in SYNCS_FETCH_AND_EMPTY])
async def test_group_a_failed_fetch_records_a_skip(monkeypatch, recorded, sync, key):
    _serve(monkeypatch, RuntimeError("upstream down"))
    assert await sync() == 0
    assert recorded == [("skipped", key, "fetch failed: RuntimeError")]


@pytest.mark.parametrize("sync, key", SYNCS_FETCH_AND_EMPTY, ids=[k for _, k in SYNCS_FETCH_AND_EMPTY])
async def test_group_a_empty_answer_records_a_skip(monkeypatch, recorded, sync, key):
    _serve(monkeypatch, [])
    assert await sync() == 0
    assert [c[:2] for c in recorded] == [("skipped", key)]


@pytest.mark.parametrize("sync, key", SYNCS_FETCH_AND_EMPTY, ids=[k for _, k in SYNCS_FETCH_AND_EMPTY])
async def test_group_a_successful_run_records_the_sync(monkeypatch, recorded, sync, key):
    _serve(monkeypatch, [_FEATURE])
    assert await sync() == 1
    assert [c[:3] for c in recorded] == [("synced", key, 1)]


# Group B — multiple layers/datasets fetched via fetch_arcgis_features_url,
# each wrapped in its own try/except that swallows a per-layer failure and
# `continue`s. Only the function's *terminal* `if not rows` exit got a new
# trace — a fetch that raises for every layer collapses into that same exit,
# same message, since the per-layer exceptions never propagate.
SYNCS_MULTI_LAYER = [
    (offshore.sync_anp_brazil, "anp"),
    (offshore.sync_crown_estate_scotland, "crown_estate_scotland"),
    (offshore.sync_pasa_sa, "pasa"),
    (offshore.sync_cnsopb_petroleum, "cnsopb"),
    (offshore.sync_cnlopb_petroleum, "cnlopb"),
]


@pytest.mark.parametrize("sync, key", SYNCS_MULTI_LAYER, ids=[k for _, k in SYNCS_MULTI_LAYER])
async def test_group_b_every_layer_failing_records_a_skip(monkeypatch, recorded, sync, key):
    _serve(monkeypatch, RuntimeError("upstream down"))
    assert await sync() == 0
    assert len(recorded) == 1
    assert recorded[0][:2] == ("skipped", key)
    assert recorded[0][2].startswith("fetch failed")


@pytest.mark.parametrize("sync, key", SYNCS_MULTI_LAYER, ids=[k for _, k in SYNCS_MULTI_LAYER])
async def test_group_b_empty_answer_records_a_skip(monkeypatch, recorded, sync, key):
    _serve(monkeypatch, [])
    assert await sync() == 0
    assert recorded == [("skipped", key, "source returned no features with geometry")]


@pytest.mark.parametrize("sync, key", SYNCS_MULTI_LAYER, ids=[k for _, k in SYNCS_MULTI_LAYER])
async def test_group_b_successful_run_records_the_sync(monkeypatch, recorded, sync, key):
    # Each of these fetches one or more layers, calling the (single, mocked)
    # fetch once per layer, so the same feature is ingested once per layer.
    _serve(monkeypatch, [_FEATURE])
    inserted = await sync()
    assert inserted >= 1
    assert [c[:2] for c in recorded] == [("synced", key)]
    assert recorded[0][2] == inserted


class _FakeResponse:
    """Minimal stand-in for an httpx.Response — only `.json()` is used."""

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


async def test_boem_empty_result_records_a_skip(monkeypatch, recorded):
    # sync_boem_offshore resolves its layer id via its own private
    # `_resolve_layer` closure, which calls `_get_with_retry` directly — no
    # layer is ever found, so every region and the wind dataset are skipped,
    # landing on the function's terminal `if not rows` trace.
    async def _get_with_retry(client, url, *a, **k):
        return _FakeResponse({"layers": []})

    monkeypatch.setattr(offshore, "_get_with_retry", _get_with_retry)
    assert await offshore.sync_boem_offshore() == 0
    assert recorded == [("skipped", "boem-offshore", "source returned no features with geometry")]


async def test_emodnet_empty_result_records_a_skip(monkeypatch, recorded):
    # sync_emodnet_offshore fetches each WFS type via `_get_with_retry` +
    # `r.json()` directly (not fetch_arcgis_features_url).
    async def _get_with_retry(client, url, *a, **k):
        return _FakeResponse({"features": []})

    monkeypatch.setattr(offshore, "_get_with_retry", _get_with_retry)
    assert await offshore.sync_emodnet_offshore() == 0
    assert recorded == [("skipped", "offshore_activities", "source returned no features with geometry")]


def _serve_no_ssl(monkeypatch, result):
    async def _fetch(*a, **k):
        if isinstance(result, Exception):
            raise result
        return result
    monkeypatch.setattr(offshore, "fetch_arcgis_no_ssl", _fetch)


async def test_cnh_mexico_failed_fetch_records_a_skip(monkeypatch, recorded):
    _serve_no_ssl(monkeypatch, RuntimeError("upstream down"))
    assert await offshore.sync_cnh_mexico() == 0
    assert recorded == [("skipped", "cnh", "fetch failed: RuntimeError")]


async def test_cnh_mexico_empty_answer_records_a_skip(monkeypatch, recorded):
    _serve_no_ssl(monkeypatch, [])
    assert await offshore.sync_cnh_mexico() == 0
    assert recorded == [("skipped", "cnh", "source returned no features with geometry")]


async def test_cnh_mexico_successful_run_records_the_sync(monkeypatch, recorded):
    _serve_no_ssl(monkeypatch, [_FEATURE])
    assert await offshore.sync_cnh_mexico() == 1
    assert [c[:3] for c in recorded] == [("synced", "cnh", 1)]


async def test_dea_dk_failed_fetch_records_a_skip(monkeypatch, recorded):
    async def _get_with_retry(client, url, *a, **k):
        raise RuntimeError("upstream down")

    monkeypatch.setattr(offshore, "_get_with_retry", _get_with_retry)
    assert await offshore.sync_dea_dk_petroleum() == 0
    assert recorded == [("skipped", "dea-dk", "fetch failed: RuntimeError")]


async def test_dea_dk_empty_answer_records_a_skip(monkeypatch, recorded):
    async def _get_with_retry(client, url, *a, **k):
        return _FakeResponse({"features": []})

    monkeypatch.setattr(offshore, "_get_with_retry", _get_with_retry)
    assert await offshore.sync_dea_dk_petroleum() == 0
    assert recorded == [("skipped", "dea-dk", "source returned no features with geometry")]


async def test_dea_dk_successful_run_records_the_sync(monkeypatch, recorded):
    async def _get_with_retry(client, url, *a, **k):
        return _FakeResponse({"features": [_FEATURE]})

    monkeypatch.setattr(offshore, "_get_with_retry", _get_with_retry)
    assert await offshore.sync_dea_dk_petroleum() == 1
    assert [c[:3] for c in recorded] == [("synced", "dea-dk", 1)]


async def test_sbma_ck_all_tenements_inactive_records_a_skip(monkeypatch, recorded):
    # Resolve succeeds (a Tenements layer is found), but every feature comes
    # back with a status in the INACTIVE set, so they're all filtered out —
    # hitting the `if not rows` trace after the status filter, not the
    # already-traced "no service found" / "fetch failed" paths.
    async def _get_with_retry(client, url, *a, **k):
        return _FakeResponse({"layers": [{"name": "Tenements", "id": 1,
                                           "geometryType": "esriGeometryPolygon"}]})

    inactive_feature = {
        "properties": {"TENEMENT_NUMBER": "T-1", "STATUS": "SURRENDERED"},
        "geometry": {"type": "Polygon",
                     "coordinates": [[[-159, -21], [-158, -21], [-158, -20], [-159, -21]]]},
    }

    monkeypatch.setattr(offshore, "_get_with_retry", _get_with_retry)
    _serve(monkeypatch, [inactive_feature])
    assert await offshore.sync_sbma_ck() == 0
    assert recorded == [("skipped", "sbma-cook-islands", "source returned no features with geometry")]


def _pmp_zip_with(names_and_bytes: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in names_and_bytes.items():
            z.writestr(name, content)
    return buf.getvalue()


async def test_pmp_guyana_no_shapefile_in_zip_records_a_skip(monkeypatch, recorded):
    class _ZipResponse:
        content = _pmp_zip_with({"readme.txt": b"no shapefile here"})

    async def _get(client, url, *a, **k):
        return _ZipResponse()

    monkeypatch.setattr(offshore, "_get_with_retry", _get)
    assert await offshore.sync_pmp_guyana() == 0
    assert recorded == [("skipped", "pmp_gy", "no .shp file found in downloaded zip")]


async def test_pmp_guyana_download_failure_records_a_skip(monkeypatch, recorded):
    async def _get(client, url, *a, **k):
        raise RuntimeError("upstream down")

    monkeypatch.setattr(offshore, "_get_with_retry", _get)
    assert await offshore.sync_pmp_guyana() == 0
    assert recorded == [("skipped", "pmp_gy", "fetch failed: RuntimeError")]


async def test_pmp_guyana_no_polygon_shapes_records_a_skip(monkeypatch, recorded):
    import shapefile as shapefile_module

    class _ZipResponse:
        content = _pmp_zip_with({"blocks.shp": b"\x00", "blocks.dbf": b"\x00"})

    async def _get(client, url, *a, **k):
        return _ZipResponse()

    class _FakeReader:
        def __init__(self, shp=None, dbf=None):
            self.fields = [("DeletionFlag",), ("Id",)]

        def shapeRecords(self):
            return []

    monkeypatch.setattr(offshore, "_get_with_retry", _get)
    monkeypatch.setattr(shapefile_module, "Reader", _FakeReader)
    assert await offshore.sync_pmp_guyana() == 0
    assert recorded == [("skipped", "pmp_gy", "source returned no features with geometry")]
