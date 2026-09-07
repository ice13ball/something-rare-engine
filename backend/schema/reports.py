# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Schema DDL — reports domain. Extracted verbatim from the former backend/schema.py.
"""
from __future__ import annotations

async def ensure_reports(conn) -> None:
    """report_cache, report_cache_v2, report_jobs_v2, report_cache_v2_concession, report_jobs_v2_concession."""

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS report_cache (
            platform_id   TEXT PRIMARY KEY,
            report_json   JSONB NOT NULL,
            risk_rating   TEXT NOT NULL DEFAULT 'Low',
            headline      TEXT NOT NULL DEFAULT '',
            finding_count INTEGER NOT NULL DEFAULT 0,
            claim_count   INTEGER NOT NULL DEFAULT 0,
            generated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    await conn.execute("ALTER TABLE report_cache OWNER TO abyssal_user")

    # Reports v2 (neutral) — sibling to report_cache; no risk_rating column.
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS report_cache_v2 (
            platform_id       TEXT PRIMARY KEY,
            report_json       JSONB NOT NULL,
            headline          TEXT NOT NULL DEFAULT '',
            measurement_count INTEGER NOT NULL DEFAULT 0,
            concession_count  INTEGER NOT NULL DEFAULT 0,
            generated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    await conn.execute("ALTER TABLE report_cache_v2 OWNER TO abyssal_user")

    # Reports v2 job tracking — DB-level atomic claim across workers/processes.
    # Separate from report_cache_v2 (cache holds completed reports; this holds
    # generation lifecycle state).
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS report_jobs_v2 (
            platform_id  TEXT PRIMARY KEY,
            status       TEXT NOT NULL CHECK (status IN ('generating','ready','failed')),
            started_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            finished_at  TIMESTAMPTZ,
            worker_id    TEXT,
            error        TEXT
        )
    """)
    await conn.execute("ALTER TABLE report_jobs_v2 OWNER TO abyssal_user")

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS report_cache_v2_concession (
            isa_id            TEXT PRIMARY KEY,
            report_json       JSONB NOT NULL,
            headline          TEXT,
            seamount_count    INTEGER,
            species_count     INTEGER,
            vent_count        INTEGER,
            generated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS report_jobs_v2_concession (
            isa_id       TEXT PRIMARY KEY,
            status       TEXT NOT NULL CHECK (status IN ('generating','ready','failed')),
            started_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            finished_at  TIMESTAMPTZ,
            worker_id    TEXT,
            error        TEXT
        )
    """)
    await conn.execute("ALTER TABLE report_cache_v2_concession OWNER TO abyssal_user")
    await conn.execute("ALTER TABLE report_jobs_v2_concession  OWNER TO abyssal_user")


