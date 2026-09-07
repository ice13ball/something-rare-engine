# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)


@pytest.fixture
async def ctx():
    import asyncpg, httpx
    import db as _db
    from fastapi import FastAPI
    from api_access.schema import ensure_api_access_schema
    from api_access.admin_auth import ensure_admin_schema, create_admin_user
    from routers import admin_api

    _db.pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    await ensure_api_access_schema(_db.pool)
    await ensure_admin_schema(_db.pool)
    async with _db.pool.acquire() as c:
        org = await c.fetchval("INSERT INTO api_access.organizations (name) VALUES ('p5-flags') RETURNING id")
        kid = await c.fetchval(
            "INSERT INTO api_access.api_keys (org_id, member_label, key_hash, key_prefix) "
            "VALUES ($1,'svc','p5fh','ak_live_p5f') RETURNING id", org)
        fid = await c.fetchval(
            "INSERT INTO api_access.leak_flags (key_id, flag_type, detail, severity) "
            "VALUES ($1,'multi_ua','{\"distinct\":7}'::jsonb,'warn') RETURNING id", kid)
    await create_admin_user(_db.pool, "p5super", "pw-superpw", "super_admin", None)
    app = FastAPI(); app.include_router(admin_api.router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, _db.pool, fid
    async with _db.pool.acquire() as c:
        await c.execute("DELETE FROM api_access.organizations WHERE name='p5-flags'")
        await c.execute("DELETE FROM api_access.admin_users WHERE username='p5super'")
    await _db.pool.close()


@pytest.mark.asyncio
async def test_flags_list_and_ack(ctx):
    client, pool, fid = ctx
    r = await client.post("/admin/api/login", json={"username": "p5super", "password": "pw-superpw"})
    assert r.status_code == 200
    lst = await client.get("/admin/api/flags")
    assert lst.status_code == 200
    assert any(f["id"] == fid and f["flag_type"] == "multi_ua" for f in lst.json())
    ack = await client.post(f"/admin/api/flags/{fid}/ack")
    assert ack.status_code == 200
    # now no longer active
    lst2 = await client.get("/admin/api/flags")
    assert all(f["id"] != fid for f in lst2.json())
    # ack of unknown flag -> 404
    assert (await client.post("/admin/api/flags/999999/ack")).status_code == 404
