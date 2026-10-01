# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""DDL for the OpenAQ daily request counter (one row per UTC day).

Persisted in Postgres, not in memory: the API restarts 2-3 times a day on
deploys, and a counter that resets on restart is no budget at all.
"""


async def ensure_openaq_request_budget(conn) -> None:
    """openaq_request_budget: how many OpenAQ requests this project sent per UTC day."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS openaq_request_budget (
            utc_day    DATE PRIMARY KEY,
            requests   INTEGER NOT NULL DEFAULT 0,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    await conn.execute("ALTER TABLE openaq_request_budget OWNER TO abyssal_user")
