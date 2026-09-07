# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import re
from typing import Literal

import aiohttp
import db
from auth import get_api_key
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/feedback", tags=["feedback"])

_ALLOWED_ORIGINS = (
    "https://something-rare.com",
    "https://www.something-rare.com",
    "https://something-rare-frontend-dev-3w2whlwtbq-ew.a.run.app",
    "http://localhost:5173",
)
_MIN_DWELL_MS = 3_000
_MAX_URLS = 3
_URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
_RATE_MAX_PER_HOUR = 5

KIND_EMOJI = {"positive": "✅", "bug": "🐛", "suggestion": "💡", "api_key": "🔑"}


class FeedbackBody(BaseModel):
    kind: Literal["positive", "bug", "suggestion", "api_key"]
    message: str = Field(min_length=2, max_length=4000)
    contact: str | None = Field(default=None, max_length=200)
    page_url: str | None = Field(default=None, max_length=500)
    website: str | None = Field(default=None, max_length=200)  # honeypot
    dwell_ms: int = Field(default=0, ge=0, le=86_400_000)


def _compute_ip_hash(ip: str) -> str | None:
    """Return the rate-limit/audit hash for a client IP, or ``None`` if
    ``FEEDBACK_IP_SALT`` is not configured.

    No fallback to a literal default: a "secret" with a hard-coded default
    is not a secret, and this file is public. Store NULL instead of a
    known-salt hash, and log a warning once per request.

    Deliberate consequence for the caller: the rate-limit query in
    ``submit_feedback`` does ``WHERE ip_hash = $1`` — passing NULL there
    never matches any row (SQL NULL semantics), so the per-IP rate limit is
    effectively disabled for every submission made while the salt is unset.
    That is an intentional fail-open: a fork/dev env that hasn't configured
    FEEDBACK_IP_SALT must still be able to accept feedback, rather than
    500ing or silently rate-limiting nothing usefully. Operators who care
    about abuse protection (and about the privacy guarantee in the
    published privacy policy) must set FEEDBACK_IP_SALT.
    """
    salt = os.environ.get("FEEDBACK_IP_SALT")
    if not salt:
        log.warning(
            "FEEDBACK_IP_SALT is not set — storing NULL ip_hash and "
            "skipping per-IP rate limiting for this submission"
        )
        return None
    # Keyed digest (HMAC), not bare concatenation — concatenation is
    # length-extension-prone and is the wrong primitive for this.
    return hmac.new(salt.encode(), ip.encode(), hashlib.sha256).hexdigest()[:32]


async def _post_discord(webhook: str, body: FeedbackBody, row_id: int) -> None:
    emoji = KIND_EMOJI.get(body.kind, "📩")
    preview = body.message[:1500] + ("…" if len(body.message) > 1500 else "")
    content = f"{emoji} **{body.kind}** (#{row_id})\n{preview}"
    if body.contact:
        content += f"\n_Contact: {body.contact}_"
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(
                webhook,
                json={"content": content, "allowed_mentions": {"parse": []}},
                timeout=aiohttp.ClientTimeout(total=5),
            )
    except Exception as e:
        log.warning("Discord webhook failed: %s", e)


@router.post("")
async def submit_feedback(
    body: FeedbackBody,
    request: Request,
    _: str = Depends(get_api_key),
) -> dict:
    # Honeypot — bots fill hidden 'website' field; humans don't
    if body.website:
        return {"ok": True}

    # Origin/Referer allowlist — blocks naive curl/script replays
    origin = request.headers.get("origin") or request.headers.get("referer", "")
    if not any(origin.startswith(allowed) for allowed in _ALLOWED_ORIGINS):
        log.info("feedback rejected: bad origin %r", origin)
        raise HTTPException(status_code=403, detail="Forbidden")

    # Dwell-time — bots POST before a human could read the form
    if body.dwell_ms < _MIN_DWELL_MS:
        log.info("feedback rejected: dwell %dms", body.dwell_ms)
        raise HTTPException(status_code=400, detail="Please take a moment to review")

    # URL-count heuristic — link spam tell
    if len(_URL_RE.findall(body.message)) > _MAX_URLS:
        log.info("feedback rejected: url count")
        raise HTTPException(status_code=400, detail="Too many links")

    ip = request.client.host if request.client else "unknown"
    ip_hash = _compute_ip_hash(ip)

    async with db.pool.acquire() as conn:
        recent_count = 0
        if ip_hash is not None:
            recent_count = await conn.fetchval(
                """SELECT COUNT(*) FROM feedback_submissions
                   WHERE ip_hash = $1
                     AND submitted_at > now() - interval '1 hour'""",
                ip_hash,
            )
        if recent_count >= _RATE_MAX_PER_HOUR:
            raise HTTPException(status_code=429, detail="Too many submissions, try again later")

        row = await conn.fetchrow(
            """
            INSERT INTO feedback_submissions (kind, message, contact, user_agent, ip_hash, page_url)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
            """,
            body.kind,
            body.message,
            body.contact,
            request.headers.get("user-agent", "")[:500],
            ip_hash,
            body.page_url,
        )

    webhook = os.environ.get("DISCORD_FEEDBACK_WEBHOOK")
    if webhook:
        asyncio.create_task(_post_discord(webhook, body, row["id"]))

    return {"ok": True}
