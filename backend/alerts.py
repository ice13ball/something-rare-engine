# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""
Dark-vessel alerts (Phase 5).

Posts new dark vessel_events to a generic webhook URL. Payload is shaped
to render readably in Slack/Discord incoming-webhooks (top-level ``text``
field) while also carrying a structured ``events`` array for n8n or any
custom receiver.

Deduplication via ``vessel_event_alerts`` — one row per ``(event_id,
webhook_url)``. Even if the webhook URL changes, past events won't be
re-sent to the same URL twice.

Disabled when ``ALERT_WEBHOOK_URL`` is unset, so local dev stays silent.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

import db

log = logging.getLogger("alerts")

ALERT_WEBHOOK_URL  = os.getenv("ALERT_WEBHOOK_URL", "").strip()
ALERT_SITE_ORIGIN  = os.getenv("ALERT_SITE_ORIGIN", "https://something-rare.com").rstrip("/")
ALERT_LOOKBACK_HRS = 48     # don't alert on events older than this on first run
ALERT_BATCH_MAX    = 20     # bundle up to N events per webhook post


async def ensure_alerts_schema() -> None:
    async with db.pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS vessel_event_alerts (
                event_id      TEXT NOT NULL,
                webhook_url   TEXT NOT NULL,
                sent_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                status_code   INTEGER,
                response      TEXT,
                PRIMARY KEY (event_id, webhook_url)
            )
        """)


def _format_slack_text(events: list[dict]) -> str:
    """Readable one-liner + per-event bullets, rendered natively by Slack/Discord."""
    header = f"🚨 {len(events)} new dark vessel detection(s)"
    lines = [header]
    for e in events[:5]:
        where = e.get("aoi_source_id") or e.get("inside_polygon_id") or "open ocean"
        lines.append(
            f"• `{e['event_id']}` — {e['ts']} @ ({e['lat']:.3f}, {e['lon']:.3f}) "
            f"— inside {where}"
        )
    if len(events) > 5:
        lines.append(f"…and {len(events) - 5} more")
    return "\n".join(lines)


async def alert_new_dark_events() -> dict[str, int]:
    """Send a webhook for any dark event not yet alerted on this URL.

    Runs after SAR detect + correlate + S2 confirm so the payload can
    include s2_thumbnail_url when available.
    """
    summary = {"candidates": 0, "sent": 0, "failed": 0}
    if not ALERT_WEBHOOK_URL:
        return summary

    await ensure_alerts_schema()

    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT ve.event_id, ve.ts, ve.lat, ve.lon,
                   ve.inside_polygon_type, ve.inside_polygon_id,
                   ve.s2_thumbnail_url
            FROM vessel_events ve
            LEFT JOIN vessel_event_alerts vea
                ON vea.event_id = ve.event_id
               AND vea.webhook_url = $1
            WHERE ve.classification = 'dark'
              AND ve.ts > NOW() - INTERVAL '{ALERT_LOOKBACK_HRS} hours'
              AND vea.event_id IS NULL
            ORDER BY ve.ts DESC
            LIMIT {ALERT_BATCH_MAX}
            """,
            ALERT_WEBHOOK_URL,
        )

    summary["candidates"] = len(rows)
    if not rows:
        return summary

    events: list[dict[str, Any]] = []
    for r in rows:
        e = {
            "event_id":            r["event_id"],
            "ts":                  r["ts"].isoformat(),
            "lat":                 float(r["lat"]),
            "lon":                 float(r["lon"]),
            "aoi_kind":            r["inside_polygon_type"],
            "aoi_source_id":       r["inside_polygon_id"],
            "s2_thumbnail_url":    (
                f"{ALERT_SITE_ORIGIN}{r['s2_thumbnail_url']}"
                if r["s2_thumbnail_url"] else None
            ),
            "map_url":             f"{ALERT_SITE_ORIGIN}/?event={r['event_id']}",
        }
        events.append(e)

    payload = {"text": _format_slack_text(events), "events": events}

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(ALERT_WEBHOOK_URL, json=payload, timeout=30.0)
        status = resp.status_code
        body_snip = resp.text[:500]
    except Exception as exc:
        status, body_snip = 0, f"request error: {exc}"
        log.warning("alert webhook failed: %s", exc)

    # Record outcome per event. We mark all attempted events as sent even on
    # HTTP error so we don't retry forever — if the webhook is broken the
    # operator will see it from the stored status_code.
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            for e in events:
                await conn.execute(
                    """
                    INSERT INTO vessel_event_alerts
                        (event_id, webhook_url, status_code, response)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (event_id, webhook_url) DO NOTHING
                    """,
                    e["event_id"], ALERT_WEBHOOK_URL, status, body_snip,
                )

    if 200 <= status < 300:
        summary["sent"] = len(events)
        log.info("alerts: sent %d dark-vessel events to webhook", len(events))
    else:
        summary["failed"] = len(events)
        log.warning("alerts: webhook returned %s — %s", status, body_snip[:200])
    return summary
