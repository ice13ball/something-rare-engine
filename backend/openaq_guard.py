# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""Safeguards for every OpenAQ request this backend makes.

OpenAQ banned this project's key on 2026-09-27 for requesting too often, and it
never sent a single 429 first (~4,000 requests/day, zero 429s in our logs). So
"react to 429" is not a defence; the limits below are ours, enforced before the
request is sent. Ported from downWindGlobal's `agents/l6_openaq.py`
(its OpenAQ hardening of 2026-09-27/28) with the differences listed in each block.

⚠️ THE KEY IS SHARED WITH downWindGlobal (owner's decision, 2026-09-30).
downWindGlobal is the paid product: it paces at ~20 req/min and brakes at 20
requests left in OpenAQ's 60/min window. something-rare YIELDS FIRST — it is
slower (~5/min), stops (never sleeps) much earlier on the shared headers, and
has a hard daily budget. Do not raise any constant here without checking
downWindGlobal's current usage.

Design (mirrors downwind's 2026-09-28 pacer refactor): the pacer and the budget are ordinary
objects passed explicitly to `guarded_get`; there is no fallback default inside
the request function, so "no pacer" is not a supported case. The one exception
is `process_pacer()`: both something-rare call sites (the `air_quality`
station sync and the `air_quality_readings` drip) live in one process and must
share ONE pacer, otherwise two concurrent runs each pace correctly and together
double the rate. The accessor is that single, explicit place; tests pass their
own pacer and never touch it.

Every stop is an `OpenAQStop` carrying the human-readable reason that callers
write to sync_log via `sync_log.log_sync_skipped` — a stop is never silent.
"""
from __future__ import annotations

import asyncio
import os
import time
from datetime import date, datetime, timezone
from typing import Any, Callable

import httpx

import db

# ── Pacing ───────────────────────────────────────────────────────────────────
# downWindGlobal: 3.0 s (~20/min), floor 2.0 s.
# something-rare: 12 s (~5/min), floor 10 s. A config typo must never speed us up
# past 6/min; OpenAQ's limit is 60/min and 2,000/h PER KEY, shared with downwind.
DEFAULT_MIN_INTERVAL_S = 12.0
MIN_ALLOWED_INTERVAL_S = 10.0

# ── Header brake ─────────────────────────────────────────────────────────────
# x-ratelimit-remaining / x-ratelimit-reset describe the CURRENT per-minute
# window of the KEY (limit 60, reset in seconds), so they include downwind's
# traffic. downwind sleeps out the window at <=20 left. We STOP at <=30 left:
# with downwind at ~20/min plus us at ~5/min the window normally ends with ~35
# left, so this stays quiet in ordinary operation and trips as soon as combined
# use climbs past half the window, well before downwind's own brake (20).
HEADROOM_STOP_REMAINING = 30
#: Never trust a header to keep us stopped longer than this many seconds.
MAX_YIELD_S = 120

# ── Daily budget ─────────────────────────────────────────────────────────────
DEFAULT_DAILY_BUDGET = 1000


class OpenAQStop(Exception):
    """The run must end now. `reason` is what goes into sync_log."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class OpenAQKeyRejected(OpenAQStop):
    """401/403: key invalid or banned. Never retried."""


class OpenAQRateLimited(OpenAQStop):
    """429. Never retried (downwind waits and retries twice; we yield instead)."""


class OpenAQBudgetExhausted(OpenAQStop):
    pass


class OpenAQHeadroomLow(OpenAQStop):
    pass


def _min_interval_s() -> float:
    """`OPENAQ_MIN_INTERVAL_S` override, clamped to >= MIN_ALLOWED_INTERVAL_S."""
    raw = os.environ.get("OPENAQ_MIN_INTERVAL_S")
    if raw is None:
        return DEFAULT_MIN_INTERVAL_S
    try:
        return max(float(raw), MIN_ALLOWED_INTERVAL_S)
    except ValueError:
        return DEFAULT_MIN_INTERVAL_S


def daily_budget_limit() -> int:
    """`OPENAQ_DAILY_BUDGET` (requests per UTC day); bad values -> default."""
    raw = os.environ.get("OPENAQ_DAILY_BUDGET")
    if raw is None:
        return DEFAULT_DAILY_BUDGET
    try:
        return max(int(raw), 0)
    except ValueError:
        return DEFAULT_DAILY_BUDGET


def parse_ratelimit_headers(headers: Any) -> tuple[int | None, int | None]:
    """(remaining, reset_seconds); missing/garbled -> None, never raises."""
    def _to_int(v: Any) -> int | None:
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    return (_to_int(headers.get("x-ratelimit-remaining")),
            _to_int(headers.get("x-ratelimit-reset")))


class RateLimitPacer:
    """>= `min_interval_s` between request STARTS, plus the header brake.

    `clock`/`sleep` are injectable so tests never really sleep. `sleep=None`
    resolves `asyncio.sleep` at call time (so patching it in a test works).
    """

    def __init__(
        self,
        min_interval_s: float | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Any = None,
    ) -> None:
        self.min_interval_s = (
            min_interval_s if min_interval_s is not None else _min_interval_s()
        )
        self._clock = clock
        self._sleep = sleep
        self._lock = asyncio.Lock()
        self._last_start: float | None = None
        self._yield_until: float | None = None
        self._yield_remaining: int | None = None
        self.request_count = 0
        self.min_remaining_seen: int | None = None

    async def wait_for_slot(self) -> None:
        """Raise OpenAQHeadroomLow while yielding; else wait out the interval."""
        async with self._lock:
            now = self._clock()
            if self._yield_until is not None:
                if now < self._yield_until:
                    raise OpenAQHeadroomLow(
                        f"OpenAQ shared-key headroom low: {self._yield_remaining} "
                        f"requests left in the window (<= {HEADROOM_STOP_REMAINING}) "
                        "— yielding to downWindGlobal"
                    )
                self._yield_until = None
            if self._last_start is not None:
                wait = self.min_interval_s - (now - self._last_start)
                if wait > 0:
                    await (self._sleep or asyncio.sleep)(wait)
            self._last_start = self._clock()
            self.request_count += 1

    def observe_headers(self, headers: Any) -> None:
        """After a response: thin headroom -> the NEXT wait_for_slot stops the run
        (until the window resets). Never sleeps: yielding, not hogging."""
        remaining, reset = parse_ratelimit_headers(headers)
        if remaining is None:
            return
        if self.min_remaining_seen is None or remaining < self.min_remaining_seen:
            self.min_remaining_seen = remaining
        if remaining <= HEADROOM_STOP_REMAINING:
            hold = min((reset if reset is not None else 60) + 1, MAX_YIELD_S)
            self._yield_until = self._clock() + hold
            self._yield_remaining = remaining


_process_pacer: RateLimitPacer | None = None


def process_pacer() -> RateLimitPacer:
    """The one pacer of this process, shared by both call sites (see module doc)."""
    global _process_pacer
    if _process_pacer is None:
        _process_pacer = RateLimitPacer()
    return _process_pacer


_TAKE_SQL = """
INSERT INTO openaq_request_budget AS b (utc_day, requests)
VALUES ($1, 1)
ON CONFLICT (utc_day) DO UPDATE
   SET requests = b.requests + 1, updated_at = now()
 WHERE b.requests < $2
RETURNING b.requests
"""


class DailyBudget:
    """Requests per UTC day, counted in Postgres so a restart cannot reset it.

    One atomic UPSERT per request: the increment only happens while the day's
    count is under the limit, so concurrent runs (or processes) cannot overshoot.
    """

    def __init__(self, today: Callable[[], date] | None = None) -> None:
        self._today = today or (lambda: datetime.now(timezone.utc).date())

    async def take(self) -> int:
        """Reserve one request; raise OpenAQBudgetExhausted when none is left."""
        limit = daily_budget_limit()
        if limit > 0:
            async with db.pool.acquire() as conn:
                used = await conn.fetchval(_TAKE_SQL, self._today(), limit)
            if used is not None:
                return used
        raise OpenAQBudgetExhausted(f"OpenAQ daily budget {limit} reached")


async def guarded_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    pacer: RateLimitPacer,
    budget: DailyBudget,
    params: dict[str, Any] | None = None,
) -> httpx.Response:
    """One paced, budgeted GET. Returns the response for 2xx/5xx/other 4xx.

    Raises OpenAQStop (never retries): budget spent, headroom low, 401/403
    (key invalid or banned), 429. Network errors propagate as httpx errors.
    """
    await pacer.wait_for_slot()   # may raise OpenAQHeadroomLow before any request
    await budget.take()
    resp = await client.get(url, params=params) if params else await client.get(url)
    code = resp.status_code
    if code in (401, 403):
        raise OpenAQKeyRejected(
            f"OpenAQ rejected the API key ({code}) — key invalid or banned")
    if code == 429:
        raise OpenAQRateLimited(
            "OpenAQ answered 429 (rate limit) — run stopped, not retried")
    pacer.observe_headers(resp.headers)
    return resp
