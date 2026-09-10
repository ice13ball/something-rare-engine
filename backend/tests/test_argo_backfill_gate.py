# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""The backfill asks the cheap question first — but only when it can pay off.

The periodic sync gates every day: 503 KB of metadata before 18.4 MB of
measurements. The backfill cannot copy that unchanged. Its ordinary day is a
day we have NEVER stored, and metadata about such a day can only ever answer
"fetch everything" — so gating it would add a 503 KB request per day and save
nothing. Walking 1999-2026 that way is ~10,000 wasted requests.

So the backfill runs the gate only for days it already holds something for,
and answers that question from our own database, which costs no bandwidth at
all.

Covers:
  - a day we hold nothing for costs exactly one request, and it is the payload
  - a day we already hold is gated: metadata first, and the payload is not
    re-requested when nothing is missing
  - the short-circuit is decided PER DAY, not per month
"""
import os
from datetime import date, datetime, timedelta, timezone

import pytest

pytestmark_db = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)

_MONTH_START = date(2020, 1, 1)
_MONTH_END = date(2020, 2, 1)
_HELD_DAY = datetime(2020, 1, 5, 12, 0, tzinfo=timezone.utc)


async def _prepare(conn):
    await conn.execute("DELETE FROM argo_profile_values")
    await conn.execute("DELETE FROM argo_profiles")
    await conn.execute("DELETE FROM argo_backfill_state")
    await conn.execute("DELETE FROM sync_log WHERE source = 'argo_profiles'")
    await conn.execute(
        "INSERT INTO argo_backfill_state (id, done_through, updated_at) "
        "VALUES (1, $1, NOW())",
        _MONTH_START,
    )


async def _seed_held_profile(conn, pid="9999008_1", when=_HELD_DAY, updated=None):
    """A complete row: header AND measurements.

    ⛔ Both halves. A header with no values is what `argo_day_plan` calls
    BROKEN, and a broken day is fetched — which would make this fixture test
    the opposite of what it says.
    """
    await conn.execute(
        """INSERT INTO argo_profiles
               (profile_id, platform_id, profile_date, surface_temp_c,
                date_updated_argovis, geom)
           VALUES ($1, '9999008', $2, 5.0, $3,
                   ST_SetSRID(ST_MakePoint(20.0, -40.0), 4326))""",
        pid, when, updated or datetime(2020, 1, 6, tzinfo=timezone.utc),
    )
    await conn.execute(
        "INSERT INTO argo_profile_values (profile_id, level, param, value, qc) "
        "VALUES ($1, 0, 'temperature', 5.0, 1)",
        pid,
    )


def _pin_today(monkeypatch, sensors):
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(_MONTH_END.year, _MONTH_END.month, _MONTH_END.day,
                            tzinfo=timezone.utc)
    monkeypatch.setattr(sensors, "datetime", FixedDatetime)


def _remote(pid, when, updated):
    """What ArgoVis returns for a profile in its metadata-only response."""
    return {
        "_id": pid,
        "timestamp": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "date_updated_argovis": updated.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "geolocation": {"type": "Point", "coordinates": [20.0, -40.0]},
        "data_info": [["pressure", "temperature"], [], []],
    }


async def _run(monkeypatch, calls, seed=None):
    """Walk one month; record every request as (start, kind)."""
    import asyncpg
    import db
    from domains import sensors

    pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    db.pool = pool
    try:
        async with pool.acquire() as conn:
            await _prepare(conn)
            if seed is not None:
                await seed(conn)

        async def fake_vocab(_client):
            return ["pressure", "temperature"]

        async def fetch(_client, start, end, params):
            calls.append((start.date(), "metadata" if params is None else "payload"))
            if params is None and start.date() == _HELD_DAY.date():
                # The source lists exactly the profile we already hold, at the
                # same revision — so nothing is new, corrected or broken.
                return [_remote("9999008_1", _HELD_DAY,
                                datetime(2020, 1, 6, tzinfo=timezone.utc))]
            return []

        monkeypatch.setattr(sensors, "_fetch_argo_param_vocabulary", fake_vocab)
        monkeypatch.setattr(sensors, "_fetch_argo_window", fetch)
        monkeypatch.setattr(sensors, "_ARGO_BACKFILL_CHUNK_PACING_SECONDS", 0)
        _pin_today(monkeypatch, sensors)
        return await sensors.sync_argo_profiles_backfill(budget_seconds=60)
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM argo_profile_values")
            await conn.execute("DELETE FROM argo_profiles WHERE platform_id = '9999008'")
        await pool.close()


@pytestmark_db
@pytest.mark.asyncio
async def test_an_untouched_day_costs_one_request_and_it_is_the_payload(monkeypatch):
    """⛔ ~10,000 days of history we hold nothing for.

    Gating them would add a 503 KB question whose answer is never in doubt.
    """
    calls: list[tuple[date, str]] = []
    await _run(monkeypatch, calls)

    kinds = [k for _d, k in calls]
    assert kinds.count("metadata") == 0, (
        f"{kinds.count('metadata')} metadata request(s) for a month we hold "
        "nothing of — the gate is running where its answer can only ever be "
        "'fetch everything', which is 503 KB per day for no saving"
    )
    assert kinds.count("payload") == 31, (
        f"{kinds.count('payload')} payload request(s) for 31 days — the "
        "short-circuit is skipping days, not skipping metadata"
    )


@pytestmark_db
@pytest.mark.asyncio
async def test_a_day_we_already_hold_is_gated_and_not_re_downloaded(monkeypatch):
    """The whole point: re-walking history must stop re-downloading it."""
    calls: list[tuple[date, str]] = []
    await _run(monkeypatch, calls, seed=_seed_held_profile)

    held = [k for d, k in calls if d == _HELD_DAY.date()]
    assert "metadata" in held, (
        f"the day we hold a complete profile for was requested as {held} — "
        "the backfill went straight for the 18.4 MB payload instead of the "
        "503 KB question about what changed"
    )
    assert "payload" not in held, (
        "nothing on that day is new, corrected or broken, and the payload was "
        "downloaded anyway — the gate decided and was then ignored"
    )


@pytestmark_db
@pytest.mark.asyncio
async def test_the_short_circuit_is_decided_per_day_not_per_month(monkeypatch):
    """⛔ One stored profile must not gate the other thirty days.

    A month-wide EXISTS would look identical on the day that matters and
    quietly add a metadata request to every empty day beside it.
    """
    calls: list[tuple[date, str]] = []
    await _run(monkeypatch, calls, seed=_seed_held_profile)

    other_days = {d for d, k in calls if k == "metadata"} - {_HELD_DAY.date()}
    assert other_days == set(), (
        f"metadata was also requested for {sorted(other_days)[:5]} — days we "
        "hold nothing of are being gated because the EXISTS asks about the "
        "month rather than the day"
    )
