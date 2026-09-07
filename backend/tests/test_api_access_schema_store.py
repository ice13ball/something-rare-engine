# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import os

import asyncpg
import pytest

from backend.api_access.schema import ensure_api_access_schema
from backend.api_access.store import load_active_keys, seed_internal_key
from backend.api_access.keys import hash_key

TEST_DB = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DB, reason="TEST_DATABASE_URL not set")


@pytest.mark.asyncio
async def test_ensure_schema_is_idempotent_and_creates_tables():
    pool = await asyncpg.create_pool(TEST_DB, min_size=1, max_size=2)
    try:
        await ensure_api_access_schema(pool)
        await ensure_api_access_schema(pool)  # second run must not error
        rows = await pool.fetch(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'api_access'"
        )
        names = {r["table_name"] for r in rows}
        assert {"organizations", "api_keys"} <= names
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_seed_internal_key_is_idempotent_and_loadable():
    pool = await asyncpg.create_pool(TEST_DB, min_size=1, max_size=2)
    try:
        await ensure_api_access_schema(pool)
        await pool.execute("DELETE FROM api_access.api_keys WHERE is_internal")
        await pool.execute("DELETE FROM api_access.organizations WHERE name = '_internal'")

        await seed_internal_key(pool, "test-frontend-key")
        await seed_internal_key(pool, "test-frontend-key")  # idempotent

        n = await pool.fetchval(
            "SELECT COUNT(*) FROM api_access.api_keys WHERE key_hash = $1",
            hash_key("test-frontend-key"),
        )
        assert n == 1

        keys = await load_active_keys(pool)
        rec = keys[hash_key("test-frontend-key")]
        assert rec.is_internal is True
        assert rec.status == "active"
        assert rec.scopes == ("all",)
    finally:
        await pool.close()
