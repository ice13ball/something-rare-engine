# SPDX-License-Identifier: AGPL-3.0-or-later
"""sync_memento must not hold the event loop.

`memento_ingest` uses `requests`, which is synchronous, and the scrape is 313
blocking HTTP calls. Awaiting that from the coroutine itself froze production on
2026-09-08: the public /health timed out, every layer timed out, and systemd still
reported the unit `active` because the process was alive — just unable to reach its
own event loop. The bug had been dormant for months only because MEMENTO_EMAIL was
never set on the server, so the credentials guard returned first. Adding the
credential armed it.

This test executes the real coroutine with the network stubbed out, and asserts the
loop stayed responsive while the "scrape" was in progress.
"""
import asyncio
import time

import pytest


@pytest.mark.asyncio
async def test_the_scrape_runs_off_the_event_loop(monkeypatch):
    from domains import geochem
    from ingestion import memento_ingest

    monkeypatch.setenv("MEMENTO_EMAIL", "someone@example.org")
    monkeypatch.setenv("MEMENTO_PASSWORD", "placeholder-value")

    BLOCK = 0.40  # stands in for a 313-leg scrape

    def fake_login(email, password):
        time.sleep(BLOCK)          # a real blocking call, not an await
        return object()

    monkeypatch.setattr(memento_ingest, "login_session", fake_login)
    monkeypatch.setattr(memento_ingest, "fetch_leg_index", lambda s: [])
    # No legs -> no samples -> the function logs and returns before touching the DB.
    async def fake_log_sync(*a, **k):
        return None
    monkeypatch.setattr(geochem, "_log_sync", fake_log_sync)

    ticks = 0

    async def heartbeat():
        """If the loop is blocked this coroutine never gets to run."""
        nonlocal ticks
        while True:
            await asyncio.sleep(0.02)
            ticks += 1

    beat = asyncio.create_task(heartbeat())
    try:
        result = await geochem.sync_memento()
    finally:
        beat.cancel()

    assert result == 0                       # the no-samples branch, as set up
    # With the scrape on the loop, ticks would be 0-1. Off the loop it should tick
    # roughly BLOCK/0.02 times; assert well below that to stay robust on slow CI.
    assert ticks >= 5, (
        f"event loop only ticked {ticks} times during a {BLOCK}s blocking scrape — "
        "the scrape is running ON the loop again, which takes production down"
    )


@pytest.mark.asyncio
async def test_a_partial_scrape_never_replaces_a_larger_stored_set(monkeypatch):
    """⛔ load_memento TRUNCATEs. Its docstring claimed the empty-scrape check made
    that safe; it does not, because a PARTIAL scrape passes that check.

    On 2026-09-08 two of 313 legs died on a momentary "Connection refused" and the
    run replaced a complete table with one 9,831 casts smaller — 155,418 down to
    145,587 — while reporting success, because a lost leg is only a WARNING.
    """
    from domains import geochem
    from ingestion import memento_ingest

    monkeypatch.setenv("MEMENTO_EMAIL", "someone@example.org")
    monkeypatch.setenv("MEMENTO_PASSWORD", "placeholder-value")
    monkeypatch.setattr(memento_ingest, "login_session", lambda e, p: object())
    monkeypatch.setattr(memento_ingest, "fetch_leg_index",
                        lambda s: [{"id": "1", "name": "good"}, {"id": "2", "name": "broken"}])

    def flaky_download(session, leg_id):
        if leg_id == "2":
            raise ConnectionRefusedError("portal said no")
        return "csv"

    monkeypatch.setattr(memento_ingest, "download_leg_csv", flaky_download)
    monkeypatch.setattr(memento_ingest, "build_samples", lambda csv, name: [{"x": 1}] * 10)

    loaded = False

    async def must_not_run(*a, **k):
        nonlocal loaded
        loaded = True
        return 0

    monkeypatch.setattr(memento_ingest, "load_memento", must_not_run)
    monkeypatch.setattr(memento_ingest, "derive_casts", lambda s: [])

    async def fake_log_sync(*a, **k):
        return None
    monkeypatch.setattr(geochem, "_log_sync", fake_log_sync)

    class _Conn:
        async def fetchval(self, *a, **k):
            return 500          # far more already stored than the 10 scraped
    class _Acq:
        async def __aenter__(self): return _Conn()
        async def __aexit__(self, *a): return False
    class _Pool:
        def acquire(self): return _Acq()

    monkeypatch.setattr(geochem.db, "pool", _Pool())

    result = await geochem.sync_memento()

    assert result == 0
    assert not loaded, "a partial scrape reached load_memento, which TRUNCATEs first"
