# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

# backend/tests/test_leak_detect.py
import os
import pytest

from api_access.leak_detect import LeakStats, evaluate_leak, Thresholds


def _stats(**kw):
    base = dict(key_id=1, req_24h=0, distinct_countries=0, distinct_asns=0,
                distinct_uas=0, countries=(), baseline_daily_avg=None)
    base.update(kw)
    return LeakStats(**base)


def test_no_flags_when_quiet():
    assert evaluate_leak(_stats(req_24h=10, distinct_countries=1, distinct_asns=1,
                                distinct_uas=1, baseline_daily_avg=8.0)) == []


def test_multi_country_flag():
    flags = evaluate_leak(_stats(distinct_countries=3, countries=("PL", "US", "CN")))
    types = {f["flag_type"] for f in flags}
    assert "multi_country" in types
    f = next(f for f in flags if f["flag_type"] == "multi_country")
    assert f["detail"]["countries"] == ["PL", "US", "CN"]


def test_multi_country_critical_at_double_threshold():
    flags = evaluate_leak(_stats(distinct_countries=6,
                                 countries=tuple("ABCDEF")))
    f = next(f for f in flags if f["flag_type"] == "multi_country")
    assert f["severity"] == "critical"


def test_multi_ua_and_asn():
    flags = evaluate_leak(_stats(distinct_asns=4, distinct_uas=5))
    types = {f["flag_type"] for f in flags}
    assert {"multi_asn", "multi_ua"} <= types


def test_spike_requires_floor_and_factor():
    # below floor: no spike even if ratio huge
    assert evaluate_leak(_stats(req_24h=100, baseline_daily_avg=1.0)) == []
    # above floor and >5x baseline: spike
    flags = evaluate_leak(_stats(req_24h=6000, baseline_daily_avg=1000.0))
    assert any(f["flag_type"] == "spike" for f in flags)
    # above floor but only 2x: no spike
    assert evaluate_leak(_stats(req_24h=2000, baseline_daily_avg=1000.0)) == []


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")
@pytest.mark.asyncio
async def test_orchestrator_inserts_and_debounces():
    import asyncpg
    from api_access.schema import ensure_api_access_schema
    from api_access import leak_detect

    pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    try:
        await ensure_api_access_schema(pool)
        async with pool.acquire() as c:
            org = await c.fetchval(
                "INSERT INTO api_access.organizations (name) VALUES ('p5-leak') RETURNING id")
            kid = await c.fetchval(
                "INSERT INTO api_access.api_keys (org_id, member_label, key_hash, key_prefix) "
                "VALUES ($1,'svc','p5hash','ak_live_p5') RETURNING id", org)
            # 12 requests in last hour from 5 distinct user agents -> multi_ua
            for i in range(12):
                await c.execute(
                    "INSERT INTO api_access.request_log (key_id, ts, method, path, "
                    "endpoint_label, status_code, response_bytes, user_agent) "
                    "VALUES ($1, NOW(), 'GET','/x','/x',200,10,$2)",
                    kid, f"ua-{i % 6}")
        calls = []
        async def fake_notifier(msg, title="t", **kw):
            calls.append(msg); return True
        n1 = await leak_detect.run_leak_detection(pool, notifier=fake_notifier)
        assert n1 >= 1
        async with pool.acquire() as c:
            active = await c.fetchval(
                "SELECT COUNT(*) FROM api_access.leak_flags WHERE key_id=$1 AND acknowledged_at IS NULL", kid)
        assert active >= 1
        # second run must NOT create duplicates or re-alert (debounce)
        calls.clear()
        n2 = await leak_detect.run_leak_detection(pool, notifier=fake_notifier)
        assert n2 == 0 and calls == []
        # cleanup
        async with pool.acquire() as c:
            await c.execute("DELETE FROM api_access.organizations WHERE name='p5-leak'")
    finally:
        await pool.close()
