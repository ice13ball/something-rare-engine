# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

from __future__ import annotations

import db as _db

# Isolated schema so a future "direct DB access for a partner" grant on the data
# schema (public) never exposes key material.
#
# Schema creation is split from table creation deliberately: Postgres checks
# CREATE-on-database privilege for `CREATE SCHEMA IF NOT EXISTS` *before* the
# IF-NOT-EXISTS short-circuit, so a role without that privilege errors even when
# the schema already exists. The app role (e.g. abyssal_user) typically lacks
# CREATE-on-database but DOES own the api_access schema (created once by a
# superuser as `CREATE SCHEMA api_access AUTHORIZATION <app_role>`), which lets
# it create tables inside. So we only issue CREATE SCHEMA when the schema is
# genuinely missing — on a prepared DB this is a no-op and never trips the
# privilege check. See memory feedback_postgis_hexgrid_gotchas.
_TABLES_DDL = """
CREATE TABLE IF NOT EXISTS api_access.organizations (
    id                     BIGSERIAL PRIMARY KEY,
    name                   TEXT UNIQUE NOT NULL,
    contact                TEXT,
    scopes                 TEXT[] NOT NULL DEFAULT '{all}',
    rate_limit_per_day_cap INTEGER,
    rate_limit_per_min_cap INTEGER,
    max_keys               INTEGER,
    expires_at             TIMESTAMPTZ,
    status                 TEXT NOT NULL DEFAULT 'active',
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by             TEXT,
    notes                  TEXT
);

CREATE TABLE IF NOT EXISTS api_access.api_keys (
    id                 BIGSERIAL PRIMARY KEY,
    org_id             BIGINT NOT NULL REFERENCES api_access.organizations(id) ON DELETE CASCADE,
    member_label       TEXT NOT NULL,
    key_hash           TEXT UNIQUE NOT NULL,
    key_prefix         TEXT NOT NULL,
    scopes             TEXT[] NOT NULL DEFAULT '{all}',
    rate_limit_per_day INTEGER,
    rate_limit_per_min INTEGER,
    expires_at         TIMESTAMPTZ,
    status             TEXT NOT NULL DEFAULT 'active',
    is_internal        BOOLEAN NOT NULL DEFAULT FALSE,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by         TEXT,
    last_used_at       TIMESTAMPTZ,
    notes              TEXT
);
CREATE INDEX IF NOT EXISTS api_keys_org_id_idx ON api_access.api_keys(org_id);

CREATE TABLE IF NOT EXISTS api_access.leak_flags (
    id              BIGSERIAL PRIMARY KEY,
    key_id          BIGINT NOT NULL REFERENCES api_access.api_keys(id) ON DELETE CASCADE,
    flag_type       TEXT NOT NULL CHECK (flag_type IN ('multi_country','multi_asn','multi_ua','spike')),
    detail          JSONB,
    severity        TEXT NOT NULL DEFAULT 'info' CHECK (severity IN ('info','warn','critical')),
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    acknowledged_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS leak_flags_key_idx ON api_access.leak_flags(key_id);
CREATE UNIQUE INDEX IF NOT EXISTS leak_flags_active_uq
    ON api_access.leak_flags(key_id, flag_type) WHERE acknowledged_at IS NULL;
"""


async def ensure_api_access_schema(pool=None) -> None:
    """Idempotent DDL for the api_access schema (organizations + api_keys).

    Called with no argument from lifespan (uses the global db.pool); a pool may
    be passed for tests. Runs with a short lock_timeout like schema.ensure_schema.
    """
    pool = pool or _db.pool
    async with pool.acquire() as conn:
        await conn.execute("SET lock_timeout = '10s'")
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_namespace WHERE nspname = 'api_access'"
        )
        if not exists:
            # Only reached on a DB where the schema was not pre-created; requires
            # the app role to hold CREATE-on-database (else this raises, which is
            # the correct signal that the one-time superuser CREATE SCHEMA ...
            # AUTHORIZATION <app_role> step is missing for this environment).
            await conn.execute("CREATE SCHEMA api_access")
        await conn.execute(_TABLES_DDL)
