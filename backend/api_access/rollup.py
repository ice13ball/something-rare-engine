# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

from __future__ import annotations

import db as _db

# Aggregate request_log rows newer than the watermark into usage_rollup.
# Additive upsert keyed on (key_id, hour, endpoint_label); because the watermark
# advances past every processed id, each raw row contributes exactly once even
# when an hour bucket spans multiple runs. NULL key_id rows are excluded.
_ROLLUP_SQL = """
INSERT INTO api_access.usage_rollup AS u
    (key_id, hour, endpoint_label, request_count, error_count, total_bytes)
SELECT key_id,
       date_trunc('hour', ts) AS hour,
       endpoint_label,
       COUNT(*),
       COUNT(*) FILTER (WHERE status_code >= 400),
       COALESCE(SUM(response_bytes), 0)
FROM api_access.request_log
WHERE id > $1 AND id <= $2 AND key_id IS NOT NULL
GROUP BY key_id, date_trunc('hour', ts), endpoint_label
ON CONFLICT (key_id, hour, endpoint_label) DO UPDATE
SET request_count = u.request_count + EXCLUDED.request_count,
    error_count   = u.error_count   + EXCLUDED.error_count,
    total_bytes   = u.total_bytes   + EXCLUDED.total_bytes
"""


async def rollup_new_rows(pool=None) -> int:
    """Roll new request_log rows into usage_rollup. Returns rows advanced."""
    pool = pool or _db.pool
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO api_access.rollup_state (name, last_log_id) "
                "VALUES ('request_log', 0) ON CONFLICT (name) DO NOTHING"
            )
            last = await conn.fetchval(
                "SELECT last_log_id FROM api_access.rollup_state "
                "WHERE name = 'request_log' FOR UPDATE"
            )
            maxid = await conn.fetchval(
                "SELECT COALESCE(MAX(id), $1) FROM api_access.request_log WHERE id > $1",
                last,
            )
            if maxid <= last:
                return 0
            await conn.execute(_ROLLUP_SQL, last, maxid)
            await conn.execute(
                "UPDATE api_access.rollup_state SET last_log_id = $1 WHERE name = 'request_log'",
                maxid,
            )
            return maxid - last
