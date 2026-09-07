# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Deterministic link fetching and mechanical verdict assignment.

Every rule here exists because a naive checker gets it wrong:
  * HEAD is rejected (405/403) by many government and ArcGIS endpoints.
  * A default user-agent is blocked by Cloudflare-class WAFs.
  * A redirect is the publisher's own indirection, not a defect.
  * "I could not reach it" is not "it no longer exists".
"""
from __future__ import annotations

import asyncio
import re

import httpx

from .models import FetchResult

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 AbyssalLinkAudit/1.0"
)
TIMEOUT = httpx.Timeout(20.0, connect=10.0)

_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)

# Matched against the *whole* title, lowercased. Kept deliberately tight: a bare
# "404" substring would flag a dataset page titled "Station 404 CTD casts".
_SOFT_404_PATTERNS = (
    r"^\s*404\b",
    r"\bpage not found\b",
    r"\bnot found\b",
    r"\bdomain is for sale\b",
    r"\bparked domain\b",
    r"\bno longer available\b",
)
_SOFT_404 = re.compile("|".join(_SOFT_404_PATTERNS), re.I)


def _strip_trailing_slash(u: str) -> str:
    return u[:-1] if u.endswith("/") else u


def classify(result: FetchResult) -> str:
    if result.error or result.status is None:
        return "BLOCKED"
    if result.status == 429:
        return "RATE_LIMITED"
    if result.status == 403:
        return "BLOCKED"
    if result.status >= 500:
        return "BLOCKED"
    if result.status in (404, 410):
        return "DEAD"
    if 200 <= result.status < 300:
        if result.title and _SOFT_404.search(result.title):
            return "CHANGED_MEANING"
        if result.final_url and (
            _strip_trailing_slash(result.final_url) != _strip_trailing_slash(result.url)
        ):
            return "REDIRECT_OK"
        return "OK"
    return "BLOCKED"


async def _fetch_one(client: httpx.AsyncClient, url: str) -> FetchResult:
    for attempt in (1, 2):
        try:
            resp = await client.get(url)
        except Exception as exc:  # noqa: BLE001 — any transport failure is BLOCKED
            if attempt == 2:
                return FetchResult(url, None, None, None, type(exc).__name__)
            await asyncio.sleep(1.0)
            continue
        # One retry for transient throttling / server errors.
        if resp.status_code in (429,) or resp.status_code >= 500:
            if attempt == 1:
                await asyncio.sleep(1.0)
                continue
        m = _TITLE.search(resp.text[:20000]) if resp.text else None
        title = " ".join(m.group(1).split()) if m else None
        return FetchResult(url, resp.status_code, str(resp.url), title, None)
    # Unreachable defensive backstop: attempt 1 either returns above or falls
    # through to attempt 2, and attempt 2 always returns (success, or the
    # `attempt == 2` branches in the except/status-check above). Kept because
    # a `for` loop gives the interpreter no proof of exhaustive return, and
    # removing this would leave an implicit `None` return if the loop bounds
    # ever changed. If you ever see "retries_exhausted" in real output, the
    # loop's return coverage has regressed.
    return FetchResult(url, None, None, None, "retries_exhausted")


async def fetch_all(
    urls: list[str], concurrency: int = 8, transport: httpx.BaseTransport | None = None
) -> list[FetchResult]:
    sem = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(
        follow_redirects=True, timeout=TIMEOUT,
        headers={"User-Agent": USER_AGENT}, transport=transport,
    ) as client:
        async def guarded(u: str) -> FetchResult:
            async with sem:
                return await _fetch_one(client, u)
        return list(await asyncio.gather(*(guarded(u) for u in urls)))
