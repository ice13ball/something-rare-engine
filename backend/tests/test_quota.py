# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

from datetime import datetime, timedelta, timezone

import pytest

from api_access.quota import QuotaTracker
from api_access import auth
from api_access.auth import KeyRecord, resolve_and_check


def test_per_minute_window():
    t = QuotaTracker()
    now = datetime(2026, 6, 22, 12, 0, 0, tzinfo=timezone.utc)
    assert t.check_and_count(1, 2, None, now) is True
    assert t.check_and_count(1, 2, None, now) is True
    assert t.check_and_count(1, 2, None, now) is False   # 3rd in same minute
    assert t.check_and_count(1, 2, None, now + timedelta(minutes=1)) is True  # next minute resets


def test_per_day_window():
    t = QuotaTracker()
    now = datetime(2026, 6, 22, 12, 0, 0, tzinfo=timezone.utc)
    assert t.check_and_count(9, None, 1, now) is True
    assert t.check_and_count(9, None, 1, now + timedelta(hours=3)) is False  # same day
    assert t.check_and_count(9, None, 1, now + timedelta(days=1)) is True    # next day resets


def test_none_limits_always_allowed():
    t = QuotaTracker()
    now = datetime(2026, 6, 22, tzinfo=timezone.utc)
    for _ in range(100):
        assert t.check_and_count(5, None, None, now) is True


@pytest.mark.asyncio
async def test_resolve_returns_429_when_over_quota():
    now = datetime(2026, 6, 22, 12, 0, 0, tzinfo=timezone.utc)
    rec = KeyRecord(id=7, org_id=1, status="active", expires_at=None,
                    scopes=("all",), is_internal=False, rate_limit_per_min=1)

    class _Cache:
        async def get(self, h):
            return rec

    tracker = QuotaTracker()
    d1, _ = await resolve_and_check("raw", cache=_Cache(), now=now, env_key=None, quota_tracker=tracker)
    assert d1.allowed is True
    d2, _ = await resolve_and_check("raw", cache=_Cache(), now=now, env_key=None, quota_tracker=tracker)
    assert d2.allowed is False and d2.status_code == 429 and d2.reason == "quota_exceeded"


@pytest.mark.asyncio
async def test_internal_key_skips_quota():
    now = datetime(2026, 6, 22, 12, 0, 0, tzinfo=timezone.utc)
    rec = KeyRecord(id=8, org_id=1, status="active", expires_at=None,
                    scopes=("all",), is_internal=True, rate_limit_per_min=1)

    class _Cache:
        async def get(self, h):
            return rec

    tracker = QuotaTracker()
    for _ in range(5):
        d, _ = await resolve_and_check("raw", cache=_Cache(), now=now, env_key=None, quota_tracker=tracker)
        assert d.allowed is True
