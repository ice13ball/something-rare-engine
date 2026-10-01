# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Regression tests for the 2026-09-29 "Too many links" false-positive bug.

Two defects fixed together:
  1. _URL_RE counted "https://" and "www." as separate matches, so
     "https://www.x.cz" counted as 2 links instead of 1.
  2. The same _MAX_URLS=3 ceiling applied to kind "api_key", where naming a
     handful of project URLs is expected and legitimate.

DB/Discord are stubbed (no network, no real Postgres) — this is a pure
routing/validation test, follows the dependency_overrides[get_api_key]
pattern from test_game_block.py. needs_db is NOT required.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

import auth as backend_auth
import db
import main

_ORIGIN = "https://something-rare.com"


class _FakeConn:
    async def fetchval(self, *args, **kwargs):
        return 0

    async def fetchrow(self, *args, **kwargs):
        return {"id": 1}


class _FakeAcquireCtx:
    async def __aenter__(self):
        return _FakeConn()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakePool:
    def acquire(self):
        return _FakeAcquireCtx()


@pytest.fixture(autouse=True)
def _stub_db(monkeypatch):
    monkeypatch.setattr(db, "pool", _FakePool())


@pytest.fixture
async def client():
    main.app.dependency_overrides[backend_auth.get_api_key] = lambda: "test-key"
    try:
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as c:
            yield c
    finally:
        main.app.dependency_overrides.pop(backend_auth.get_api_key, None)


async def _post(client, kind: str, message: str):
    return await client.post(
        "/v1/feedback",
        json={"kind": kind, "message": message, "dwell_ms": 5000},
        headers={"Origin": _ORIGIN},
    )


@pytest.mark.asyncio
async def test_two_scheme_www_links_are_accepted(client):
    r = await _post(
        client,
        "suggestion",
        "https://www.a.cz and https://www.b.cz",
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_four_distinct_links_rejected_for_suggestion(client):
    r = await _post(
        client,
        "suggestion",
        "https://a.cz https://b.cz https://c.cz https://d.cz",
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "Too many links"


@pytest.mark.asyncio
async def test_eight_links_accepted_for_api_key(client):
    links = " ".join(f"https://site{i}.example.com" for i in range(8))
    r = await _post(client, "api_key", links)
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_eleven_links_rejected_for_api_key(client):
    links = " ".join(f"https://site{i}.example.com" for i in range(11))
    r = await _post(client, "api_key", links)
    assert r.status_code == 400
    assert r.json()["detail"] == "Too many links"
