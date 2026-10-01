# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import os
import sys
from pathlib import Path

import pytest

# Add backend directory to sys.path so imports like `import db` work within backend modules
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


@pytest.fixture(autouse=True)
def _lock_connection_dsn():
    """Point `db.dsn` at the test database, the way production points it at
    the pool's own DSN.

    `sensors._connect_for_lock` opens a connection OUTSIDE the pool to hold
    the Argo advisory walk lock. Production sets `db.dsn` beside the pool;
    tests build their pools inline in seven different places, so without this
    the lock connection fell back to `os.environ["DATABASE_URL"]` — unset
    here — and every test that reaches the lock died with a KeyError before
    asserting anything. Twelve guards across two files could not go red, and
    a guard that cannot go red is not a guard.

    Autouse and cheap: it only assigns a module attribute.
    """
    import db as _db
    url = os.environ.get("TEST_DATABASE_URL")
    previous = _db.dsn
    if url:
        _db.dsn = url
    yield
    _db.dsn = previous


@pytest.fixture(autouse=True)
def _fast_openaq_pacer(monkeypatch):
    """The OpenAQ call sites share ONE per-process pacer (~5 req/min in
    production). Tests must never wait 12 s between mocked requests, so every
    test gets a fresh pacer with no interval; tests of the pacing itself build
    their own RateLimitPacer with an injected clock/sleep."""
    import openaq_guard
    monkeypatch.setattr(
        openaq_guard, "_process_pacer", openaq_guard.RateLimitPacer(min_interval_s=0.0))


@pytest.fixture
async def export_client():
    from httpx import AsyncClient, ASGITransport
    from main import app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://t",
        headers={"X-API-Key": os.environ.get("ABYSSAL_API_KEY", "")},
    ) as client:
        yield client
