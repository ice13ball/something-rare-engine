# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""Pre-bake after a swap: old version dirs go, the default view z0..N is on disk, sync_log records it."""
import asyncpg

from ingestion import plankton_obis as p
from plankton_helpers import _PoolFromConn, conn, needs_db, row, seed_live  # noqa: F401
from services import plankton_tiles as tiles


async def _sync_log(conn):
    await conn.execute("""CREATE TABLE IF NOT EXISTS sync_log (source text PRIMARY KEY,
        last_synced_at timestamptz, records_added integer NOT NULL DEFAULT 0,
        total_records integer NOT NULL DEFAULT 0, skipped_reason text, skipped_at timestamptz)""")
    await conn.execute("DELETE FROM sync_log WHERE source = 'plankton-tiles'")


@needs_db
async def test_bake_drops_old_versions_and_writes_the_default_view(conn, tmp_path, monkeypatch):
    root = tmp_path / "tiles"
    monkeypatch.setenv("PLANKTON_TILE_CACHE_DIR", str(root))
    monkeypatch.setenv("PLANKTON_PREBAKE_MAX_ZOOM", "2")
    monkeypatch.setattr(p.db, "pool", _PoolFromConn(conn), raising=False)
    await _sync_log(conn)
    version = await seed_live(conn, [row("copepoda", 10.2, 50.2, year=2015)])
    tiles.write_cached(tiles.tile_path(root, "20200101000000-abcdef", "all", 0, 0, 0), b"old")
    (root / "keep-me").mkdir()
    await p.bake_tiles()
    assert sorted(c.name for c in root.iterdir()) == sorted([version, "keep-me"])
    assert len(list((root / version / "all").rglob("*.pbf"))) == 1 + 4 + 16
    logged = await conn.fetchrow(
        "SELECT records_added, skipped_reason FROM sync_log WHERE source = 'plankton-tiles'")
    assert (logged["records_added"], logged["skipped_reason"]) == (21, None)


@needs_db
async def test_a_failed_bake_is_logged_and_alerted_never_raised(conn, monkeypatch):
    await _sync_log(conn)
    sent = []

    async def fake_notify(msg, title="", **_):
        sent.append(msg)
        return True

    async def broken(pool, root, max_zoom=None):
        raise RuntimeError("secret detail https://x/?token=1")
    monkeypatch.setattr(p, "notify_telegram", fake_notify)
    monkeypatch.setattr(tiles, "prebake", broken)
    monkeypatch.setattr(p.db, "pool", _PoolFromConn(conn), raising=False)
    await p.bake_tiles()
    reason = await conn.fetchval("SELECT skipped_reason FROM sync_log WHERE source = 'plankton-tiles'")
    assert reason == "error: RuntimeError" and len(sent) == 1 and "secret" not in sent[0]


@needs_db
async def test_bake_stops_and_writes_nothing_when_the_version_changes_mid_bake(conn, tmp_path, monkeypatch):
    root = tmp_path / "tiles"
    version = await seed_live(conn, [row("copepoda", 10.2, 50.2, year=2015)])
    real, calls = tiles.render, []

    async def render_then_swap(c, z, x, y, f):
        calls.append((z, x, y))
        got, data = await real(c, z, x, y, f)
        return ("20990101000000-ffffff" if len(calls) == 2 else got), data
    monkeypatch.setattr(tiles, "render", render_then_swap)
    try:
        await tiles.prebake(_PoolFromConn(conn), root, max_zoom=2)
        raise AssertionError("prebake must stop on a version change")
    except tiles.BakeVersionChanged:
        pass
    assert len(calls) == 2
    assert [f.name for f in (root / version / "all").rglob("*.pbf")] == ["0.pbf"]
    assert not (root / "20990101000000-ffffff").exists()


@needs_db
async def test_a_bake_version_change_is_logged_as_skipped_without_alert(conn, monkeypatch):
    await _sync_log(conn)
    sent = []

    async def fake_notify(msg, title="", **_):
        sent.append(msg)

    async def moved(pool, root, max_zoom=None):
        raise tiles.BakeVersionChanged("x")
    monkeypatch.setattr(p, "notify_telegram", fake_notify)
    monkeypatch.setattr(tiles, "prebake", moved)
    monkeypatch.setattr(p.db, "pool", _PoolFromConn(conn), raising=False)
    await p.bake_tiles()
    reason = await conn.fetchval("SELECT skipped_reason FROM sync_log WHERE source = 'plankton-tiles'")
    assert reason == "skipped: version changed" and sent == []


@needs_db
async def test_a_timed_out_tile_is_skipped_and_never_written(conn, tmp_path, monkeypatch):
    root = tmp_path / "tiles"
    version = await seed_live(conn, [row("copepoda", 10.2, 50.2, year=2015)])
    real = tiles.render

    async def flaky(c, z, x, y, f):
        if (z, x, y) == (1, 0, 0):
            raise asyncpg.QueryCanceledError("statement timeout")
        return await real(c, z, x, y, f)
    monkeypatch.setattr(tiles, "render", flaky)
    n, skipped = await tiles.prebake(_PoolFromConn(conn), root, max_zoom=1)
    assert (n, skipped) == (4, 1) and not tiles.tile_path(root, version, "all", 1, 0, 0).exists()


async def _bake_logged(conn, monkeypatch, root, max_zoom=2):
    await _sync_log(conn)
    sent = []

    async def fake_notify(msg, title="", **_):
        sent.append(msg)
    monkeypatch.setenv("PLANKTON_TILE_CACHE_DIR", str(root))
    monkeypatch.setenv("PLANKTON_PREBAKE_MAX_ZOOM", str(max_zoom))
    monkeypatch.setattr(p, "notify_telegram", fake_notify)
    monkeypatch.setattr(p.db, "pool", _PoolFromConn(conn), raising=False)
    await p.bake_tiles()
    reason = await conn.fetchval("SELECT skipped_reason FROM sync_log WHERE source = 'plankton-tiles'")
    return reason, sent


@needs_db
async def test_timed_out_tiles_are_counted_in_sync_log(conn, tmp_path, monkeypatch):
    await seed_live(conn, [row("copepoda", 10.2, 50.2, year=2015)])
    real = tiles.render

    async def flaky(c, z, x, y, f):
        if (z, x, y) in {(1, 0, 0), (2, 3, 3)}:
            raise asyncpg.QueryCanceledError("t")
        return await real(c, z, x, y, f)
    monkeypatch.setattr(tiles, "render", flaky)
    reason, sent = await _bake_logged(conn, monkeypatch, tmp_path / "t")
    assert reason == "skipped: 2 tiles timed out" and sent == []


@needs_db
async def test_consecutive_timeouts_stop_the_bake_early_and_alert(conn, tmp_path, monkeypatch):
    await seed_live(conn, [row("copepoda", 10.2, 50.2, year=2015)])
    calls = []

    async def always(c, z, x, y, f):
        calls.append(1)
        raise asyncpg.QueryCanceledError("t")
    monkeypatch.setattr(tiles, "render", always)
    monkeypatch.setattr(tiles, "PREBAKE_MAX_CONSECUTIVE_TIMEOUTS", 3)
    reason, sent = await _bake_logged(conn, monkeypatch, tmp_path / "t")
    assert reason == "error: consecutive timeouts" and len(sent) == 1 and len(calls) == 3


@needs_db
async def test_timeouts_that_are_not_consecutive_never_stop_the_bake(conn, tmp_path, monkeypatch):
    """Every other tile times out: the streak resets after each good tile, so the cap (3) is never reached."""
    await seed_live(conn, [row("copepoda", 10.2, 50.2, year=2015)])
    real, calls = tiles.render, []

    async def alternating(c, z, x, y, f):
        calls.append(1)
        if len(calls) % 2 == 1:
            raise asyncpg.QueryCanceledError("t")
        return await real(c, z, x, y, f)
    monkeypatch.setattr(tiles, "render", alternating)
    monkeypatch.setattr(tiles, "PREBAKE_MAX_CONSECUTIVE_TIMEOUTS", 3)
    reason, sent = await _bake_logged(conn, monkeypatch, tmp_path / "t")
    assert len(calls) == 21 and reason == "skipped: 11 tiles timed out" and sent == []


@needs_db
async def test_the_total_deadline_stops_the_bake(conn, tmp_path, monkeypatch):
    await seed_live(conn, [row("copepoda", 10.2, 50.2, year=2015)])
    calls = []
    real = tiles.render

    async def counting(c, z, x, y, f):
        calls.append(1)
        return await real(c, z, x, y, f)
    monkeypatch.setattr(tiles, "render", counting)
    monkeypatch.setenv("PLANKTON_PREBAKE_DEADLINE_S", "0")
    reason, sent = await _bake_logged(conn, monkeypatch, tmp_path / "t")
    assert reason == "error: bake deadline" and len(sent) == 1 and calls == []


@needs_db
async def test_a_missing_version_in_a_render_is_an_error_not_a_version_change(conn, tmp_path, monkeypatch):
    await seed_live(conn, [row("copepoda", 10.2, 50.2, year=2015)])

    async def no_version(c, z, x, y, f):
        return None, b"x"
    monkeypatch.setattr(tiles, "render", no_version)
    reason, sent = await _bake_logged(conn, monkeypatch, tmp_path / "t")
    assert reason == "error: no tile version" and len(sent) == 1
    assert not list((tmp_path / "t").rglob("*.pbf"))
