# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

# backend/api_access/leak_detect.py
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from .notify import notify_telegram

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Thresholds:
    multi_country: int = 3
    multi_asn: int = 4
    multi_ua: int = 5
    spike_factor: float = 5.0
    spike_min_abs: int = 1000


DEFAULT_THRESHOLDS = Thresholds()


@dataclass(frozen=True)
class LeakStats:
    key_id: int
    req_24h: int
    distinct_countries: int
    distinct_asns: int
    distinct_uas: int
    countries: tuple[str, ...]
    baseline_daily_avg: float | None
    org_name: str = ""
    member_label: str = ""


def evaluate_leak(stats: LeakStats, thresholds: Thresholds = DEFAULT_THRESHOLDS) -> list[dict]:
    """Pure: given a key's trailing-window stats, return the leak flags to raise."""
    flags: list[dict] = []
    if stats.distinct_countries >= thresholds.multi_country:
        sev = "critical" if stats.distinct_countries >= 2 * thresholds.multi_country else "warn"
        flags.append({"flag_type": "multi_country", "severity": sev,
                      "detail": {"countries": list(stats.countries),
                                 "distinct": stats.distinct_countries, "window": "24h"}})
    if stats.distinct_asns >= thresholds.multi_asn:
        flags.append({"flag_type": "multi_asn", "severity": "warn",
                      "detail": {"distinct": stats.distinct_asns, "window": "24h"}})
    if stats.distinct_uas >= thresholds.multi_ua:
        sev = "warn" if stats.distinct_uas >= 2 * thresholds.multi_ua else "info"
        flags.append({"flag_type": "multi_ua", "severity": sev,
                      "detail": {"distinct": stats.distinct_uas, "window": "24h"}})
    if (stats.baseline_daily_avg
            and stats.req_24h >= thresholds.spike_min_abs
            and stats.req_24h > stats.baseline_daily_avg * thresholds.spike_factor):
        flags.append({"flag_type": "spike", "severity": "warn",
                      "detail": {"req_24h": stats.req_24h,
                                 "baseline_daily_avg": round(stats.baseline_daily_avg, 1),
                                 "window": "24h"}})
    return flags


_AGG_SQL = """
SELECT k.id AS key_id, k.member_label, o.name AS org_name,
       COUNT(r.*) AS req_24h,
       COUNT(DISTINCT r.country) FILTER (WHERE r.country IS NOT NULL) AS distinct_countries,
       COUNT(DISTINCT r.asn)     FILTER (WHERE r.asn IS NOT NULL)     AS distinct_asns,
       COUNT(DISTINCT r.user_agent) FILTER (WHERE r.user_agent IS NOT NULL) AS distinct_uas,
       ARRAY_AGG(DISTINCT r.country) FILTER (WHERE r.country IS NOT NULL) AS countries
FROM api_access.api_keys k
JOIN api_access.organizations o ON o.id = k.org_id
JOIN api_access.request_log r
  ON r.key_id = k.id AND r.ts > NOW() - INTERVAL '24 hours'
WHERE k.status = 'active' AND k.is_internal = FALSE
GROUP BY k.id, k.member_label, o.name
"""

_BASELINE_SQL = """
SELECT key_id, COUNT(*)::float / 6.0 AS avg_daily
FROM api_access.request_log
WHERE key_id IS NOT NULL
  AND ts <= NOW() - INTERVAL '24 hours'
  AND ts >  NOW() - INTERVAL '7 days'
GROUP BY key_id
"""


async def run_leak_detection(pool, *, notifier=notify_telegram,
                             thresholds: Thresholds = DEFAULT_THRESHOLDS) -> int:
    """Scan request_log, raise debounced leak_flags, Telegram on new flags. Returns new-flag count."""
    async with pool.acquire() as conn:
        agg = await conn.fetch(_AGG_SQL)
        baseline = {r["key_id"]: r["avg_daily"] for r in await conn.fetch(_BASELINE_SQL)}
    new_count = 0
    for r in agg:
        stats = LeakStats(
            key_id=r["key_id"], req_24h=r["req_24h"],
            distinct_countries=r["distinct_countries"] or 0,
            distinct_asns=r["distinct_asns"] or 0,
            distinct_uas=r["distinct_uas"] or 0,
            countries=tuple(r["countries"] or ()),
            baseline_daily_avg=baseline.get(r["key_id"]),
            org_name=r["org_name"], member_label=r["member_label"],
        )
        for flag in evaluate_leak(stats, thresholds):
            async with pool.acquire() as conn:
                inserted = await conn.fetchval(
                    """
                    INSERT INTO api_access.leak_flags (key_id, flag_type, detail, severity)
                    VALUES ($1, $2, $3::jsonb, $4)
                    ON CONFLICT (key_id, flag_type) WHERE acknowledged_at IS NULL
                    DO NOTHING
                    RETURNING id
                    """,
                    stats.key_id, flag["flag_type"], json.dumps(flag["detail"]), flag["severity"],
                )
            if inserted is not None:
                new_count += 1
                msg = (f"Possible key leak — org «{stats.org_name}» / «{stats.member_label}» "
                       f"(key #{stats.key_id}): {flag['flag_type']} [{flag['severity']}] "
                       f"{json.dumps(flag['detail'])}")
                try:
                    await notifier(msg)
                except Exception:
                    log.exception("leak_detect: notifier failed for key %s", stats.key_id)
    if new_count:
        log.info("leak_detect: raised %d new flag(s)", new_count)
    return new_count
