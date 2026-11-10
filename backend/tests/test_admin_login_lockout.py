# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""The admin login lockout expires, and a refused login never says why.

Until 2026-11-10 five wrong passwords locked an account for good (the counter was
checked before the window, and only a successful login reset it), and a locked
account answered 429 where every other failure answered 401, so the status code
told anyone the username existed.

These run the real route and the real `lockout_state` / bcrypt calls with the DB
calls replaced by an in-memory row that applies the same rules as
`_FAILED_LOGIN_SQL` (that SQL was checked on PostgreSQL separately). No DB needed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi import FastAPI

import db as _db
from api_access import admin_auth
from routers import admin_api

USER, PW = "op@example.com", "right-password-123"
T0 = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)


class _Clock:
    now_value = T0

    @classmethod
    def now(cls, tz=None):
        return cls.now_value


class _Store:
    def __init__(self):
        self.row = {"id": 1, "username": USER, "password_hash": admin_auth.hash_password(PW),
                    "role": "super_admin", "status": "active", "failed_logins": 0, "locked_until": None}

    async def get_admin_by_username(self, pool, username):
        return dict(self.row) if username == USER else None

    async def register_login_result(self, pool, user_id, success, now):
        r = self.row
        if success:
            r["failed_logins"], r["locked_until"] = 0, None
            return
        lu = r["locked_until"]
        if lu is not None and lu <= now:          # expired window: a new count starts at 1
            r["failed_logins"], r["locked_until"] = 1, None
        elif lu is not None:                      # a live lock is never extended
            r["failed_logins"] += 1
        else:
            r["failed_logins"] += 1
            if r["failed_logins"] >= 5:
                r["locked_until"] = now + timedelta(minutes=15)

    async def create_session(self, pool, user_id, ip, ttl):
        return "tok"


@pytest.fixture
async def ctx(monkeypatch):
    store = _Store()
    _Clock.now_value = T0
    monkeypatch.setattr(_db, "pool", object(), raising=False)
    monkeypatch.setattr(admin_api, "datetime", _Clock)
    for name in ("get_admin_by_username", "register_login_result", "create_session"):
        monkeypatch.setattr(admin_auth, name, getattr(store, name))
    bcrypt_calls = []
    real_verify = admin_auth.verify_password

    def counting_verify(pw, hashed):
        bcrypt_calls.append(1)
        return real_verify(pw, hashed)

    monkeypatch.setattr(admin_auth, "verify_password", counting_verify)
    app = FastAPI()
    app.include_router(admin_api.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://test") as client:
        yield client, store, bcrypt_calls


async def _login(client, user, pw):
    return await client.post("/admin/api/login", json={"username": user, "password": pw})


def test_expired_window_unlocks_even_at_the_threshold():
    past = T0 - timedelta(seconds=1)
    assert admin_auth.lockout_state(5, past, T0) == (False, None)
    assert admin_auth.lockout_state(9, past, T0) == (False, None)


@pytest.mark.asyncio
async def test_five_failures_lock_the_account(ctx):
    client, store, _ = ctx
    for _ in range(5):
        assert (await _login(client, USER, "wrong")).status_code == 401
    assert store.row["locked_until"] == T0 + timedelta(minutes=15)
    # the right password is refused while the window runs, and the window is not extended
    assert (await _login(client, USER, PW)).status_code == 401
    assert store.row["locked_until"] == T0 + timedelta(minutes=15)


@pytest.mark.asyncio
async def test_right_password_gets_in_after_the_window(ctx):
    client, store, _ = ctx
    for _ in range(5):
        await _login(client, USER, "wrong")
    _Clock.now_value = T0 + timedelta(minutes=15, seconds=1)
    r = await _login(client, USER, PW)
    assert r.status_code == 200, r.text
    assert store.row["failed_logins"] == 0 and store.row["locked_until"] is None


@pytest.mark.asyncio
async def test_wrong_password_after_the_window_starts_a_new_count(ctx):
    client, store, _ = ctx
    for _ in range(5):
        await _login(client, USER, "wrong")
    _Clock.now_value = T0 + timedelta(minutes=15, seconds=1)
    assert (await _login(client, USER, "wrong")).status_code == 401
    assert store.row["failed_logins"] == 1 and store.row["locked_until"] is None
    # four more failures (five in the new window) lock it again
    for _ in range(4):
        await _login(client, USER, "wrong")
    assert store.row["locked_until"] == _Clock.now_value + timedelta(minutes=15)


@pytest.mark.asyncio
async def test_missing_locked_and_wrong_password_are_indistinguishable(ctx):
    client, store, bcrypt_calls = ctx
    wrong = await _login(client, USER, "wrong")
    for _ in range(4):
        await _login(client, USER, "wrong")
    bcrypt_calls.clear()
    locked = await _login(client, USER, PW)
    assert len(bcrypt_calls) == 1          # the locked path still pays for one bcrypt check
    bcrypt_calls.clear()
    missing = await _login(client, "nobody@example.com", "whatever")
    assert len(bcrypt_calls) == 1          # so does an unknown username
    for r in (locked, missing):
        assert (r.status_code, r.json()) == (wrong.status_code, wrong.json()) == (401, {"detail": "invalid credentials"})
