# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

# backend/tests/test_org_crud.py
import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)


@pytest.fixture
async def pool():
    import asyncpg
    from api_access.schema import ensure_api_access_schema
    p = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    await ensure_api_access_schema(p)
    yield p
    await p.close()


async def _mk_org(conn, name, **caps):
    return await conn.fetchval(
        "INSERT INTO api_access.organizations (name, rate_limit_per_day_cap, max_keys) "
        "VALUES ($1,$2,$3) RETURNING id",
        name, caps.get("day_cap"), caps.get("max_keys"),
    )


@pytest.mark.asyncio
async def test_update_and_revoke_are_org_scoped(pool):
    from api_access import org_crud
    async with pool.acquire() as conn:
        org_a = await _mk_org(conn, "p4-a", max_keys=10)
        org_b = await _mk_org(conn, "p4-b", max_keys=10)
    ka, _ = await org_crud.create_key_for_org(pool, org_a, "alice", None, None, None, "a-admin")
    # org B must NOT be able to update or revoke org A's key
    assert await org_crud.update_key_in_org(pool, org_id=org_b, key_id=ka, member_label="hax") is False
    assert await org_crud.revoke_key_in_org(pool, org_id=org_b, key_id=ka) is False
    # org A can
    assert await org_crud.update_key_in_org(pool, org_id=org_a, key_id=ka, member_label="alice2") is True
    assert await org_crud.revoke_key_in_org(pool, org_id=org_a, key_id=ka) is True


@pytest.mark.asyncio
async def test_update_clamps_to_org_cap(pool):
    from api_access import org_crud
    async with pool.acquire() as conn:
        org = await _mk_org(conn, "p4-clamp", day_cap=100, max_keys=10)
    kid, _ = await org_crud.create_key_for_org(pool, org, "bob", None, None, None, "admin")
    await org_crud.update_key_in_org(pool, org_id=org, key_id=kid, rate_limit_per_day=999999)
    async with pool.acquire() as conn:
        val = await conn.fetchval("SELECT rate_limit_per_day FROM api_access.api_keys WHERE id=$1", kid)
    assert val == 100  # clamped to cap


@pytest.mark.asyncio
async def test_stats_return_none_for_foreign_key(pool):
    from api_access import org_crud
    async with pool.acquire() as conn:
        org_a = await _mk_org(conn, "p4-sa", max_keys=10)
        org_b = await _mk_org(conn, "p4-sb", max_keys=10)
    ka, _ = await org_crud.create_key_for_org(pool, org_a, "x", None, None, None, "admin")
    assert await org_crud.usage_for_key_in_org(pool, org_b, ka) is None
    assert await org_crud.sources_for_key_in_org(pool, org_b, ka) is None
    assert isinstance(await org_crud.usage_for_key_in_org(pool, org_a, ka), dict)
