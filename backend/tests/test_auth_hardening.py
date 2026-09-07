# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Auth-hardening regression tests, ahead of the public release.

Covers three of the four auth defects fixed alongside this file:
  1. `/v1/plumes/history` was missing its `Depends(get_api_key)` guard — the
     only endpoint of its kind left open by oversight (see the route sweep in
     the commit that added this file).
  2/3. The admin-token check (`backend/auth.py::require_admin_token`) used a
     `!=` comparison (timing side-channel) and took the token only via a query
     parameter (access logs / proxy logs / browser history). Both the header
     path and constant-time comparison are exercised here.

No live DATABASE_URL is required: `main` imports cleanly without one (see
test_import_smoke.py), and the one endpoint we use as the "known-open, still
200" control (`/v1/map/layer-config`) has its DB pool swapped for an in-memory
fake so the whole file runs offline.
"""
from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

import auth as backend_auth
import main
from api_access import auth as api_access_auth


# ── Fake DB pool — enough surface for the one public endpoint we exercise ────
class _FakeConn:
    async def fetch(self, *a, **kw):
        return []

    async def fetchval(self, *a, **kw):
        return 0

    async def fetchrow(self, *a, **kw):
        return None

    async def execute(self, *a, **kw):
        return None


class _FakeAcquire:
    async def __aenter__(self):
        return _FakeConn()

    async def __aexit__(self, *exc):
        return False


class _FakePool:
    def acquire(self):
        return _FakeAcquire()


@pytest.fixture
def anon_client(monkeypatch):
    """An httpx client against the real `main.app`, with NO X-API-Key header
    and a stubbed DB pool so public, DB-touching endpoints still resolve."""
    monkeypatch.setattr(main, "_pool", _FakePool())
    monkeypatch.setattr(main, "_layer_config_cache", None)
    monkeypatch.setattr(main, "_layer_config_cache_ts", 0.0)
    return AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test")


# ── Defect 1: /v1/plumes/history had no API-key requirement ─────────────────
@pytest.mark.asyncio
async def test_plumes_history_requires_api_key(anon_client):
    async with anon_client as client:
        r = await client.get("/v1/plumes/history?contractor_name=NORI&limit=1")
        assert r.status_code in (401, 403), (
            f"/v1/plumes/history must reject an unauthenticated request, got {r.status_code}"
        )


@pytest.mark.asyncio
async def test_known_open_endpoint_still_returns_200(anon_client):
    """Companion to the test above: proves the 401/403 is specific to
    plumes/history, not a client/app-wide failure that would 403 everything."""
    async with anon_client as client:
        r = await client.get("/v1/map/layer-config")
        assert r.status_code == 200, (
            f"/v1/map/layer-config is deliberately public — expected 200, got {r.status_code}: {r.text}"
        )


# ── Defects 2 & 3: admin token — header, constant-time, correct length trap ──
@pytest.mark.asyncio
async def test_require_admin_token_accepts_correct_header_token(monkeypatch):
    correct = "A" * 24
    monkeypatch.setattr(backend_auth, "ADMIN_DASHBOARD_TOKEN", correct)
    request = SimpleNamespace(headers={"X-Admin-Token": correct})
    await backend_auth.require_admin_token(request)  # must not raise


@pytest.mark.asyncio
async def test_require_admin_token_rejects_wrong_token_same_length(monkeypatch):
    """A length-only check would let this through: `wrong` is the exact same
    length as `correct`, differing only in content."""
    correct = "A" * 24
    wrong_same_length = "B" * 24
    monkeypatch.setattr(backend_auth, "ADMIN_DASHBOARD_TOKEN", correct)
    request = SimpleNamespace(headers={"X-Admin-Token": wrong_same_length})
    with pytest.raises(HTTPException) as exc_info:
        await backend_auth.require_admin_token(request)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_require_admin_token_falls_back_to_query_param(monkeypatch):
    """Header is preferred; the deprecated `token` query param must still work
    so nothing behind Tailscale gets locked out."""
    correct = "A" * 24
    monkeypatch.setattr(backend_auth, "ADMIN_DASHBOARD_TOKEN", correct)
    request = SimpleNamespace(headers={})
    await backend_auth.require_admin_token(request, token=correct)  # must not raise


@pytest.mark.asyncio
async def test_require_admin_token_rejects_when_unconfigured(monkeypatch):
    monkeypatch.setattr(backend_auth, "ADMIN_DASHBOARD_TOKEN", "")
    request = SimpleNamespace(headers={"X-Admin-Token": "anything"})
    with pytest.raises(HTTPException) as exc_info:
        await backend_auth.require_admin_token(request)
    assert exc_info.value.status_code == 403


# ── Grep-style guard, narrowly scoped to the two functions we hardened ───────
def test_no_naive_equality_left_in_the_fixed_secret_comparisons():
    """Only guard: `==`/`!=` must not reappear in the two functions this patch
    hardened with hmac.compare_digest. Not a blanket repo-wide grep."""
    targets = {
        "api_access.auth.resolve_and_check": inspect.getsource(api_access_auth.resolve_and_check),
        "auth.require_admin_token": inspect.getsource(backend_auth.require_admin_token),
    }
    for name, src in targets.items():
        assert "==" not in src, f"{name} still compares a secret with '==' (timing side-channel)"
        assert "!=" not in src, f"{name} still compares a secret with '!=' (timing side-channel)"
