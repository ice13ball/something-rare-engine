# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""The Argo backfill must request a month one day at a time.

`data=all` is every measurement of every float. Measured against the live
ArgoVis API on 2026-09-10:

    1 day      18.4 MB      7.3 s
    7 days    135.4 MB     39.7 s
    1 month   594.9 MB    256.3 s

httpx buffers the whole body, `r.json()` builds a Python structure several
times that size, and the list stays alive through the upsert — so a month
peaked in the gigabytes. Splitting is also free in wall clock (30 x 7.3 s =
219 s against 256 s) and shrinks the cost of a dropped connection from a
month to a day.

⛔ The dangerous failure here is not "too big" — it is a split that silently
drops days. A month that requests 1..30 but never 31 loses a day of profiles
with nothing raising, which is why the tiling test asserts full coverage and
not merely "more than one request".

Covers:
  - a month is requested in one-day windows
  - those windows tile the month exactly: no gap, no overlap, no missing tail
  - each day is stored before the next is requested (peak memory is one day)
  - the month stays the cursor unit, so the bookkeeping is unchanged
  - a failure names the day, not just the month
"""
# ⚠️ Since the metadata gate landed, sync_argo_profiles makes TWO requests per
# day: a 503 KB metadata probe (params=None) and the 18.4 MB payload. The
# PERIODIC tests below count only payload requests, because that is what they
# are about — counting both would pin the gate's existence into tests that are
# not about it. The gate has its own guards in test_argo_metadata_gate.py.
# ⛔ The BACKFILL tests below still count ONE request per day, and that is not
# an oversight. The backfill gates a day only when we already hold something
# for it, and `_prepare` empties argo_profiles — so every day short-circuits
# straight to the payload. The gate's own behaviour there is guarded in
# test_argo_backfill_gate.py, which seeds a day on purpose.

import os
from datetime import date, datetime, timedelta, timezone

import pytest

pytestmark_db = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)

_MONTH_START = date(2020, 1, 1)
_MONTH_END = date(2020, 2, 1)


async def _prepare(conn):
    await conn.execute("DELETE FROM argo_profile_values")
    await conn.execute("DELETE FROM argo_profiles")
    await conn.execute("DELETE FROM argo_backfill_state")
    await conn.execute("DELETE FROM sync_log WHERE source = 'argo_profiles'")
    await conn.execute(
        "INSERT INTO argo_backfill_state (id, done_through, updated_at) VALUES (1, $1, NOW())",
        _MONTH_START,
    )


def _pin_today(monkeypatch, sensors):
    """Pin "now" one month past the cursor so the walk does exactly one month."""
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(_MONTH_END.year, _MONTH_END.month, _MONTH_END.day, tzinfo=timezone.utc)
    monkeypatch.setattr(sensors, "datetime", FixedDatetime)


async def _run(monkeypatch, fetch, upserts=None):
    import asyncpg
    import db
    from domains import sensors

    pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    db.pool = pool
    try:
        async with pool.acquire() as conn:
            await _prepare(conn)

        async def fake_vocab(_client):
            return ["pressure", "temperature"]

        monkeypatch.setattr(sensors, "_fetch_argo_param_vocabulary", fake_vocab)
        monkeypatch.setattr(sensors, "_fetch_argo_window", fetch)
        monkeypatch.setattr(sensors, "_ARGO_BACKFILL_CHUNK_PACING_SECONDS", 0)

        if upserts is not None:
            real_upsert = sensors._upsert_argo_profiles

            async def spy(profiles, params):
                upserts.append(list(profiles))
                return await real_upsert(profiles, params)

            monkeypatch.setattr(sensors, "_upsert_argo_profiles", spy)

        _pin_today(monkeypatch, sensors)
        return await sensors.sync_argo_profiles_backfill(budget_seconds=60)
    finally:
        await pool.close()


@pytestmark_db
@pytest.mark.asyncio
async def test_a_month_is_requested_one_day_at_a_time(monkeypatch):
    windows: list[tuple[datetime, datetime]] = []

    async def fetch(_client, start, end, _params):
        windows.append((start, end))
        return []

    result = await _run(monkeypatch, fetch)

    assert result["months_done"] == 1
    assert windows, "no window was requested at all"
    assert len(windows) == 31, (
        f"January is 31 days but {len(windows)} request(s) were made — the "
        "month is not being split per day"
    )
    for start, end in windows:
        assert end - start == timedelta(days=1), (
            f"window {start.date()}..{end.date()} is not one day"
        )


@pytestmark_db
@pytest.mark.asyncio
async def test_the_day_windows_tile_the_month_with_no_gap_and_no_overlap(monkeypatch):
    """⛔ A split that drops a day loses profiles with nothing raising."""
    windows: list[tuple[datetime, datetime]] = []

    async def fetch(_client, start, end, _params):
        windows.append((start, end))
        return []

    await _run(monkeypatch, fetch)

    windows.sort()
    assert windows[0][0].date() == _MONTH_START, "the month does not start at day one"
    assert windows[-1][1].date() == _MONTH_END, (
        f"the last window ends {windows[-1][1].date()}, not {_MONTH_END} — "
        "the tail of the month is being dropped"
    )
    for (_, prev_end), (next_start, _) in zip(windows, windows[1:]):
        assert prev_end == next_start, (
            f"gap or overlap between {prev_end} and {next_start}"
        )


@pytestmark_db
@pytest.mark.asyncio
async def test_each_day_is_stored_before_the_next_is_requested(monkeypatch):
    """Peak memory is one day's profiles, which is the point of the split."""
    upserts: list[list[dict]] = []
    order: list[str] = []

    def _profile(day: int) -> dict:
        return {
            "_id": f"9999003_{day:03d}",
            "timestamp": f"2020-01-{day:02d}T00:00:00Z",
            "geolocation": {"type": "Point", "coordinates": [-30.0, 40.0]},
            "geolocation_argoqc": 1,
            "data": [[10.0, 1500.0], [5.0, 2.0]],
            "data_info": [["pressure", "temperature"], [], []],
        }

    async def fetch(_client, start, _end, _params):
        order.append(f"fetch:{start.day}")
        return [_profile(start.day)]

    from domains import sensors

    real_upsert = sensors._upsert_argo_profiles

    async def spy(profiles, params):
        order.append(f"store:{len(profiles)}")
        upserts.append(list(profiles))
        return await real_upsert(profiles, params)

    monkeypatch.setattr(sensors, "_upsert_argo_profiles", spy)
    await _run(monkeypatch, fetch, upserts=None)

    assert len(upserts) == 31, (
        f"{len(upserts)} store(s) for 31 days — days are being accumulated and "
        "written once, which keeps the whole month in memory"
    )
    for batch in upserts:
        assert len(batch) == 1, (
            f"a store received {len(batch)} profiles; each day's fetch returned 1, "
            "so more than one day is alive at a time"
        )
    assert order[:4] == ["fetch:1", "store:1", "fetch:2", "store:1"], (
        f"fetch and store are not interleaved per day: {order[:4]}"
    )


@pytestmark_db
@pytest.mark.asyncio
async def test_the_month_is_still_the_cursor_unit(monkeypatch):
    """Splitting the request must not change the bookkeeping."""
    import asyncpg
    import db

    async def fetch(_client, _start, _end, _params):
        return []

    result = await _run(monkeypatch, fetch)

    pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    try:
        async with pool.acquire() as conn:
            done_through = await conn.fetchval(
                "SELECT done_through FROM argo_backfill_state WHERE id = 1"
            )
    finally:
        await pool.close()

    assert result["months_done"] == 1, "the walk must still count in months"
    assert done_through == _MONTH_END, (
        f"cursor is {done_through}; it must advance a whole month, not a day"
    )


@pytestmark_db
@pytest.mark.asyncio
async def test_a_failure_names_the_day_not_only_the_month(monkeypatch, caplog):
    """"The month failed" is not actionable when the month is thirty requests."""
    async def fetch(_client, start, _end, _params):
        if start.day == 17:
            raise ValueError("upstream said no")
        return []

    with caplog.at_level("ERROR"):
        result = await _run(monkeypatch, fetch)

    assert result["months_done"] == 0
    assert result["failed_chunk"], "a failed walk must say which chunk failed"
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "2020-01-17" in logged, (
        f"the failing day is not named in the error log:\n{logged}"
    )


# ── the periodic sync: same split, and it runs far more often ──────────────
#
# ⛔ This is the path that matters most. sync_argo_profiles runs every 12 hours
# and used to pull its whole 30-day window in ONE request — ~552 MB at the
# measured 18.4 MB/day — inside the process that also serves the map. The
# backfill split alone did not touch it; that gap survived a round of "the
# memory hog is fixed" and was caught by a question, not by a test.
#
# ⚠️ The 30-day window is NOT a freshness setting. It is how late-arriving
# profiles are picked up, so these tests pin the split, never the window.

async def _run_periodic(monkeypatch, fetch, window_days=30):
    import asyncpg
    import db
    from domains import sensors

    pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    db.pool = pool
    try:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM argo_profile_values")
            await conn.execute("DELETE FROM argo_profiles WHERE platform_id = '9999004'")
            await conn.execute("DELETE FROM sync_log WHERE source = 'argo_profiles'")

        async def fake_vocab(_client):
            return ["pressure", "temperature"]

        monkeypatch.setattr(sensors, "_fetch_argo_param_vocabulary", fake_vocab)
        monkeypatch.setattr(sensors, "_fetch_argo_window", fetch)
        monkeypatch.setattr(sensors, "_ARGO_BACKFILL_CHUNK_PACING_SECONDS", 0)
        monkeypatch.setattr(sensors, "_ARGO_RECENT_WINDOW_DAYS", window_days)
        return await sensors.sync_argo_profiles()
    finally:
        await pool.close()


@pytestmark_db
@pytest.mark.asyncio
async def test_the_periodic_sync_splits_its_window_into_days(monkeypatch):
    windows: list[tuple[datetime, datetime]] = []

    async def fetch(_client, start, end, params):
        # ⚠️ The METADATA windows now carry this property. Since the gate
        # landed, the payload is fetched per PROFILE when only a few are
        # missing, so there may be no payload window at all — but the cheap
        # probe still walks day by day, and it is what guarantees we never ask
        # ArgoVis for a 30-day span in one request.
        if params is None:
            windows.append((start, end))
        return []

    await _run_periodic(monkeypatch, fetch)

    assert windows, "the periodic sync made no request at all"
    assert len(windows) == 30, (
        f"a 30-day window produced {len(windows)} request(s) — it is not being "
        "split per day, so the whole window is buffered at once"
    )
    for start, end in windows:
        assert end - start <= timedelta(days=1), (
            f"window {start}..{end} is longer than a day"
        )


@pytestmark_db
@pytest.mark.asyncio
async def test_the_periodic_windows_tile_the_whole_lookback(monkeypatch):
    """⛔ A split that drops days loses late-arriving profiles, silently."""
    windows: list[tuple[datetime, datetime]] = []

    async def fetch(_client, start, end, params):
        # ⚠️ The METADATA windows now carry this property. Since the gate
        # landed, the payload is fetched per PROFILE when only a few are
        # missing, so there may be no payload window at all — but the cheap
        # probe still walks day by day, and it is what guarantees we never ask
        # ArgoVis for a 30-day span in one request.
        if params is None:
            windows.append((start, end))
        return []

    await _run_periodic(monkeypatch, fetch)

    windows.sort()
    span = windows[-1][1] - windows[0][0]
    assert span == timedelta(days=30), (
        f"the day windows cover {span}, not the 30-day lookback — "
        "the window was narrowed by the split, which is a behaviour change"
    )
    for (_, prev_end), (next_start, _) in zip(windows, windows[1:]):
        assert prev_end == next_start, f"gap or overlap between {prev_end} and {next_start}"


@pytestmark_db
@pytest.mark.asyncio
async def test_the_periodic_sync_stores_each_day_before_fetching_the_next(monkeypatch):
    from domains import sensors

    order: list[str] = []

    # ⛔ Force the BULK path: the peak-memory property this test pins ("one
    # day alive at a time") only applies when a day is fetched as a whole.
    # A threshold of 0 sends every day with anything missing down that path.
    monkeypatch.setattr(sensors, "_ARGO_PROFILE_FETCH_MAX", 0)

    async def fetch(_client, start, _end, params):
        if params is None:
            # The gate must want this day, or no payload is fetched at all.
            return [{"_id": f"9999004_{start.strftime('%m%d')}"}]
        order.append("fetch")
        return [{
            "_id": f"9999004_{start.strftime('%m%d')}",
            "timestamp": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "geolocation": {"type": "Point", "coordinates": [-30.0, 40.0]},
            "geolocation_argoqc": 1,
            "data": [[10.0, 1500.0], [5.0, 2.0]],
            "data_info": [["pressure", "temperature"], [], []],
        }]

    real_upsert = sensors._upsert_argo_profiles

    async def spy(profiles, params):
        order.append(f"store:{len(profiles)}")
        return await real_upsert(profiles, params)

    monkeypatch.setattr(sensors, "_upsert_argo_profiles", spy)
    inserted = await _run_periodic(monkeypatch, fetch, window_days=4)

    assert order == ["fetch", "store:1", "fetch", "store:1",
                     "fetch", "store:1", "fetch", "store:1"], (
        f"fetch and store are not interleaved per day: {order}"
    )
    assert inserted == 4, f"every day's profile should be counted, got {inserted}"


@pytestmark_db
@pytest.mark.asyncio
async def test_a_transient_failure_on_one_day_is_retried_not_fatal(monkeypatch):
    """30 requests instead of 1 means 30x the chance of meeting a blip."""
    import httpx
    from domains import sensors

    monkeypatch.setattr(sensors, "_ARGO_429_BASE_WAIT_SECONDS", 0.0)
    calls: list[int] = []

    async def fetch(_client, start, _end, _params):
        calls.append(start.day)
        if calls.count(start.day) == 1 and start.day % 2 == 0:
            raise httpx.ReadError("connection dropped mid-response")
        return []

    inserted = await _run_periodic(monkeypatch, fetch, window_days=4)

    assert inserted == 0
    assert len(set(calls)) == 4, (
        f"only {len(set(calls))} distinct day(s) were reached — a transient "
        "error on one day killed the rest of the window"
    )


@pytestmark_db
@pytest.mark.asyncio
async def test_a_failed_periodic_sync_names_the_day_and_is_not_stamped(monkeypatch, caplog):
    """⛔ "ran, found nothing" and "failed" must never look the same."""
    import asyncpg
    import httpx
    from domains import sensors

    monkeypatch.setattr(sensors, "_ARGO_429_MAX_ATTEMPTS", 1)

    async def fetch(_client, start, _end, _params):
        if start.day % 7 == 3:
            raise httpx.ReadError("upstream gone")
        return []

    with caplog.at_level("ERROR"):
        result = await _run_periodic(monkeypatch, fetch, window_days=10)

    assert result == 0
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "failed on" in logged, f"the failing day is not named:\n{logged}"

    pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    try:
        async with pool.acquire() as conn:
            stamped = await conn.fetchval(
                "SELECT count(*) FROM sync_log WHERE source = 'argo_profiles'"
            )
    finally:
        await pool.close()
    assert stamped == 0, (
        "a failed sync stamped sync_log — the monitor can no longer tell it "
        "apart from a run that found nothing"
    )
