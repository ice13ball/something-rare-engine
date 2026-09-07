# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

import db as _db

log = logging.getLogger(__name__)

RETENTION_DAYS = 90

# request_log: daily RANGE partitions on ts. Globally-unique identity id (one
# sequence on the parent) drives the rollup watermark; PK includes ts (required
# for partitioned tables). key_id is nullable (unknown-key attempts).
_PARENT_DDL = """
CREATE TABLE IF NOT EXISTS api_access.request_log (
    id             BIGINT GENERATED ALWAYS AS IDENTITY,
    key_id         BIGINT,
    org_id         BIGINT,
    ts             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    method         TEXT,
    path           TEXT,
    endpoint_label TEXT,
    status_code    SMALLINT,
    response_bytes INTEGER,
    ip             INET,
    country        TEXT,
    asn            INTEGER,
    user_agent     TEXT,
    PRIMARY KEY (id, ts)
) PARTITION BY RANGE (ts);

CREATE INDEX IF NOT EXISTS request_log_ts_brin
    ON api_access.request_log USING BRIN (ts);
CREATE INDEX IF NOT EXISTS request_log_key_ts
    ON api_access.request_log (key_id, ts DESC);

CREATE TABLE IF NOT EXISTS api_access.usage_rollup (
    key_id         BIGINT NOT NULL,
    hour           TIMESTAMPTZ NOT NULL,
    endpoint_label TEXT NOT NULL,
    request_count  INTEGER NOT NULL DEFAULT 0,
    error_count    INTEGER NOT NULL DEFAULT 0,
    total_bytes    BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (key_id, hour, endpoint_label)
);
CREATE INDEX IF NOT EXISTS usage_rollup_key_hour
    ON api_access.usage_rollup (key_id, hour);

CREATE TABLE IF NOT EXISTS api_access.rollup_state (
    name        TEXT PRIMARY KEY,
    last_log_id BIGINT NOT NULL DEFAULT 0
);
"""


def daily_partition_name(d: date) -> str:
    return f"request_log_{d:%Y%m%d}"


def daily_partition_bounds(d: date) -> tuple[datetime, datetime]:
    start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def parse_partition_end(bound_expr: str) -> datetime | None:
    """Parse the TO bound out of a `FOR VALUES FROM ('..') TO ('..')` expression."""
    try:
        end_str = bound_expr.split(" TO ('")[1].rstrip("')")
        end = datetime.fromisoformat(end_str.replace(" ", "T"))
    except (IndexError, ValueError):
        return None
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return end


async def ensure_daily_partitions(conn, days_back: int = 1, days_ahead: int = 2) -> None:
    """Create partitions covering [today-days_back .. today+days_ahead]."""
    today = datetime.now(timezone.utc).date()
    for offset in range(-days_back, days_ahead + 1):
        d = today + timedelta(days=offset)
        start, end = daily_partition_bounds(d)
        await conn.execute(
            f"CREATE TABLE IF NOT EXISTS api_access.{daily_partition_name(d)} "
            f"PARTITION OF api_access.request_log "
            f"FOR VALUES FROM ('{start.isoformat()}') TO ('{end.isoformat()}')"
        )


async def ensure_log_schema(pool=None) -> None:
    """Idempotent DDL for request_log (+partitions), usage_rollup, rollup_state."""
    pool = pool or _db.pool
    async with pool.acquire() as conn:
        await conn.execute("SET lock_timeout = '10s'")
        await conn.execute(_PARENT_DDL)
        await ensure_daily_partitions(conn)


async def drop_expired_log_partitions(pool=None, retention_days: int = RETENTION_DAYS) -> int:
    """Drop request_log partitions whose end is older than the retention cutoff."""
    pool = pool or _db.pool
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    dropped = 0
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT c.relname AS name, pg_get_expr(c.relpartbound, c.oid) AS bound
            FROM pg_inherits i
            JOIN pg_class c ON c.oid = i.inhrelid
            JOIN pg_class p ON p.oid = i.inhparent
            JOIN pg_namespace n ON n.oid = p.relnamespace
            WHERE p.relname = 'request_log' AND n.nspname = 'api_access'
            """
        )
        for r in rows:
            end = parse_partition_end(r["bound"] or "")
            if end is not None and end < cutoff:
                await conn.execute(f'DROP TABLE IF EXISTS api_access."{r["name"]}"')
                dropped += 1
                log.info("Dropped expired request_log partition %s (ended %s)",
                         r["name"], end.isoformat())
    return dropped
