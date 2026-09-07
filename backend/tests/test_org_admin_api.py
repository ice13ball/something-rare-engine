# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

# backend/tests/test_org_admin_api.py
import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)


@pytest.fixture
async def ctx():
    import asyncpg
    import httpx
    import db as _db
    from fastapi import FastAPI
    from api_access.schema import ensure_api_access_schema
    from api_access.admin_auth import ensure_admin_schema, create_admin_user
    from routers import org_admin_api

    _db.pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    await ensure_api_access_schema(_db.pool)
    await ensure_admin_schema(_db.pool)
    async with _db.pool.acquire() as conn:
        org_a = await conn.fetchval(
            "INSERT INTO api_access.organizations (name, max_keys) VALUES ('p4-router-a',5) RETURNING id")
        org_b = await conn.fetchval(
            "INSERT INTO api_access.organizations (name, max_keys) VALUES ('p4-router-b',5) RETURNING id")
    await create_admin_user(_db.pool, "p4admin_a", "pw-aaaaaaaa", "org_admin", org_a)
    await create_admin_user(_db.pool, "p4admin_b", "pw-bbbbbbbb", "org_admin", org_b)
    app = FastAPI()
    app.include_router(org_admin_api.router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, _db.pool, org_a, org_b
    await _db.pool.close()


async def _login(client, user, pw):
    r = await client.post("/org-admin/api/login", json={"username": user, "password": pw})
    assert r.status_code == 200, r.text
    csrf = client.cookies.get("csrf_org")
    assert csrf
    return {"X-CSRF-Token": csrf}


@pytest.mark.asyncio
async def test_login_me_and_create_key(ctx):
    client, pool, org_a, org_b = ctx
    hdr = await _login(client, "p4admin_a", "pw-aaaaaaaa")
    me = (await client.get("/org-admin/api/me")).json()
    assert me["role"] == "org_admin" and me["org_id"] == org_a
    r = await client.post("/org-admin/api/keys",
                          json={"member_label": "svc1"}, headers=hdr)
    assert r.status_code == 200 and r.json()["key"].startswith("ak_live_")


@pytest.mark.asyncio
async def test_state_change_without_csrf_is_rejected(ctx):
    client, *_ = ctx
    await _login(client, "p4admin_a", "pw-aaaaaaaa")
    r = await client.post("/org-admin/api/keys", json={"member_label": "nope"})  # no CSRF header
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_cannot_revoke_other_orgs_key(ctx):
    client, pool, org_a, org_b = ctx
    # org B creates a key
    hb = await _login(client, "p4admin_b", "pw-bbbbbbbb")
    kid = (await client.post("/org-admin/api/keys", json={"member_label": "bkey"},
                             headers=hb)).json()["id"]
    await client.post("/org-admin/api/logout", headers=hb)
    # org A tries to revoke it
    ha = await _login(client, "p4admin_a", "pw-aaaaaaaa")
    r = await client.post(f"/org-admin/api/keys/{kid}/revoke", headers=ha)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_super_admin_cannot_use_org_portal(ctx):
    client, pool, *_ = ctx
    from api_access.admin_auth import create_admin_user
    await create_admin_user(pool, "p4super", "pw-superxxx", "super_admin", None)
    r = await client.post("/org-admin/api/login",
                          json={"username": "p4super", "password": "pw-superxxx"})
    assert r.status_code == 401
