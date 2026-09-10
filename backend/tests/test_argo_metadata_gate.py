# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Decide whether a day's measurements are worth fetching, from metadata alone.

`sync_argo_profiles` runs every 12 hours over a 30-day window and inserts
nothing: every September date already held 430-480 profiles and the last
periodic run recorded `records_added: 0` having downloaded ~552 MB. Measured
against the live API 2026-09-10, one global day:

    with data=all ..... 18 414 KB, 7.1 s
    no `data` key .....    503 KB, 3.4 s      ← 36x smaller

The cheap answer still carries `_id`, `timestamp`, `data_info` and
`date_updated_argovis` — enough to tell "nothing here has changed" from
"there is something new or corrected".

⛔ Nothing here is wired into a sync yet, on purpose. This is the whole
decision surface, testable in isolation, before it can affect production.

Covers:
  - a day we already hold completely is skipped
  - a day with a profile we have never seen is fetched
  - a day with a profile the source has REVISED is fetched
  - a header row with no measurements counts as broken, and is fetched
  - NULL means "never asked", not "stale" — it does NOT force a fetch
  - NULL rows get stamped from the metadata, at no extra cost
  - a profile the source stopped listing is reported, never deleted
"""
import os
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)

_DAY_START = datetime(2020, 5, 1, tzinfo=timezone.utc)
_DAY_END = datetime(2020, 5, 2, tzinfo=timezone.utc)
_PLATFORM = "9999006"


def _index(entries):
    """The shape ArgoVis returns when `data` is omitted."""
    return [
        {"_id": pid, "timestamp": "2020-05-01T12:00:00Z",
         **({"date_updated_argovis": updated} if updated else {})}
        for pid, updated in entries
    ]


async def _with_rows(rows):
    """rows: (profile_id, date_updated_argovis, with_values)"""
    import asyncpg
    import db

    pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    db.pool = pool
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM argo_profile_values WHERE profile_id LIKE $1", f"{_PLATFORM}%")
        await conn.execute("DELETE FROM argo_profiles WHERE platform_id = $1", _PLATFORM)
        for pid, updated, with_values in rows:
            await conn.execute(
                """INSERT INTO argo_profiles
                       (profile_id, platform_id, profile_date, date_updated_argovis, geom)
                   VALUES ($1, $2, $3, $4, ST_SetSRID(ST_MakePoint(0, 0), 4326))""",
                pid, _PLATFORM, _DAY_START, updated,
            )
            if with_values:
                await conn.execute(
                    """INSERT INTO argo_profile_values (profile_id, level, param, value, qc)
                       VALUES ($1, 'surface', 'temperature', 4.0, 1)""",
                    pid,
                )
    return pool


async def _plan(rows, index):
    from domains import sensors

    pool = await _with_rows(rows)
    try:
        async with pool.acquire() as conn:
            return await sensors.argo_day_plan(conn, _DAY_START, _DAY_END, index)
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM argo_profile_values WHERE profile_id LIKE $1", f"{_PLATFORM}%")
            await conn.execute("DELETE FROM argo_profiles WHERE platform_id = $1", _PLATFORM)
        await pool.close()


_T0 = datetime(2020, 6, 1, tzinfo=timezone.utc)
_T1 = datetime(2026, 7, 1, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_a_day_we_already_hold_is_not_fetched():
    plan = await _plan(
        [(f"{_PLATFORM}_001", _T0, True), (f"{_PLATFORM}_002", _T0, True)],
        _index([(f"{_PLATFORM}_001", "2020-06-01T00:00:00Z"),
                (f"{_PLATFORM}_002", "2020-06-01T00:00:00Z")]),
    )
    assert plan.fetch_data is False, (
        "every profile is already stored and unrevised, yet the day would still "
        "cost 18.4 MB"
    )
    assert (plan.n_new, plan.n_corrected, plan.n_broken) == (0, 0, 0)


@pytest.mark.asyncio
async def test_a_new_profile_forces_a_fetch():
    plan = await _plan(
        [(f"{_PLATFORM}_001", _T0, True)],
        _index([(f"{_PLATFORM}_001", "2020-06-01T00:00:00Z"),
                (f"{_PLATFORM}_099", "2020-06-01T00:00:00Z")]),
    )
    assert plan.fetch_data is True
    assert plan.n_new == 1


@pytest.mark.asyncio
async def test_a_revised_profile_forces_a_fetch():
    """⛔ Argo's delayed-mode QC arrives months later. Missing it means we keep
    the real-time value forever."""
    plan = await _plan(
        [(f"{_PLATFORM}_001", _T0, True)],
        _index([(f"{_PLATFORM}_001", "2026-07-01T00:00:00Z")]),
    )
    assert plan.fetch_data is True
    assert plan.n_corrected == 1


@pytest.mark.asyncio
async def test_a_header_without_measurements_counts_as_broken():
    """The header INSERT and the values write are not one transaction, so an
    interrupted run leaves a row that metadata alone would call complete."""
    plan = await _plan(
        [(f"{_PLATFORM}_001", _T0, False)],
        _index([(f"{_PLATFORM}_001", "2020-06-01T00:00:00Z")]),
    )
    assert plan.fetch_data is True
    assert plan.n_broken == 1


@pytest.mark.asyncio
async def test_a_null_stamp_does_not_force_a_fetch():
    """⛔ NULL means "we never asked", not "stale". Reading it as stale would
    pull the payload for all 388k existing rows to find nothing changed."""
    plan = await _plan(
        [(f"{_PLATFORM}_001", None, True)],
        _index([(f"{_PLATFORM}_001", "2026-07-01T00:00:00Z")]),
    )
    assert plan.fetch_data is False
    assert plan.n_corrected == 0


@pytest.mark.asyncio
async def test_a_null_stamp_is_filled_in_from_the_metadata():
    plan = await _plan(
        [(f"{_PLATFORM}_001", None, True)],
        _index([(f"{_PLATFORM}_001", "2026-07-01T00:00:00Z")]),
    )
    assert plan.to_stamp == [(f"{_PLATFORM}_001", _T1)]


@pytest.mark.asyncio
async def test_a_profile_the_source_dropped_is_reported_not_deleted():
    plan = await _plan(
        [(f"{_PLATFORM}_001", _T0, True), (f"{_PLATFORM}_002", _T0, True)],
        _index([(f"{_PLATFORM}_001", "2020-06-01T00:00:00Z")]),
    )
    assert plan.vanished == [f"{_PLATFORM}_002"]
    assert plan.fetch_data is False, "a disappearance is not a reason to re-download"


@pytest.mark.asyncio
async def test_stamping_never_overwrites_a_stamp_we_already_have():
    """⛔ Overwriting would mark a row current whose measurements we never
    fetched — a correction lost in silence."""
    import asyncpg
    import db
    from domains import sensors

    pool = await _with_rows([(f"{_PLATFORM}_001", _T0, True)])
    try:
        async with pool.acquire() as conn:
            await sensors.apply_argo_stamps(conn, [(f"{_PLATFORM}_001", _T1)])
            got = await conn.fetchval(
                "SELECT date_updated_argovis FROM argo_profiles WHERE profile_id = $1",
                f"{_PLATFORM}_001")
        assert got == _T0, "an existing stamp was overwritten by the cheap pass"
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM argo_profile_values WHERE profile_id LIKE $1", f"{_PLATFORM}%")
            await conn.execute("DELETE FROM argo_profiles WHERE platform_id = $1", _PLATFORM)
        await pool.close()


# ── the request that makes the saving possible ──────────────────────────────

@pytest.mark.asyncio
async def test_metadata_request_omits_the_data_key_entirely():
    """⛔ 36x smaller only if the `data` key is ABSENT.

    `data` is a filter, not a column selection, so `data=""` is a different
    filter — not the absence of one. Someone "tidying" the sentinel into an
    empty string would restore the 18.4 MB request with no other symptom.
    """
    import httpx
    from datetime import timedelta
    from domains import sensors

    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        return httpx.Response(200, json=[])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await sensors._fetch_argo_window(client, _DAY_START, _DAY_END, None)

    assert seen, "no request was made"
    assert "data" not in seen[0], (
        f"the metadata request carries data={seen[0].get('data')!r} — an empty "
        "string is a different filter, not the absence of one, and the answer "
        "is the full 18.4 MB payload again"
    )
    assert seen[0]["startDate"].startswith("2020-05-01")


@pytest.mark.asyncio
async def test_the_full_request_still_asks_for_every_measurement():
    """The saving must not quietly become a truncation."""
    import httpx
    from domains import sensors

    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        return httpx.Response(200, json=[])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await sensors._fetch_argo_window(client, _DAY_START, _DAY_END, ["temperature"])

    assert seen[0]["data"] == "all", (
        "`data` must stay `all`; naming parameters filters to profiles carrying "
        "ALL of them, which once cut a day's 464 profiles down to 36"
    )


# ── the gate acting: fetch only what is missing ─────────────────────────────
#
# ⚠️ These replace the shadow-run guard, which asserted the payload was always
# fetched. That behaviour is intentionally gone — it was a staging property,
# true for exactly one commit, and its guard was there to stop the skip being
# smuggled in early. Deleting it now is the plan working, not a guard quietly
# dropped: what it protected has been observed on production and superseded.


async def _run_periodic(monkeypatch, *, window_days, day_fetch, profile_fetch):
    import asyncpg
    import db
    from domains import sensors

    pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    db.pool = pool
    try:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM argo_profile_values WHERE profile_id LIKE $1", f"{_PLATFORM}%")
            await conn.execute("DELETE FROM argo_profiles WHERE platform_id = $1", _PLATFORM)
            await conn.execute("DELETE FROM sync_log WHERE source = 'argo_profiles'")

        async def fake_vocab(_client):
            return ["pressure", "temperature"]

        monkeypatch.setattr(sensors, "_fetch_argo_param_vocabulary", fake_vocab)
        monkeypatch.setattr(sensors, "_fetch_argo_window", day_fetch)
        monkeypatch.setattr(sensors, "_fetch_argo_profile", profile_fetch)
        monkeypatch.setattr(sensors, "_ARGO_BACKFILL_CHUNK_PACING_SECONDS", 0)
        monkeypatch.setattr(sensors, "_ARGO_RECENT_WINDOW_DAYS", window_days)
        await sensors.sync_argo_profiles()
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM sync_log WHERE source = 'argo_profiles'")
        await pool.close()


@pytest.mark.asyncio
async def test_a_day_we_hold_costs_no_payload_request(monkeypatch):
    """⛔ The whole point: 503 KB instead of 18.4 MB when nothing changed."""
    from domains import sensors

    payload_calls: list[str] = []

    async def day_fetch(_client, _start, _end, params):
        if params is not None:
            payload_calls.append("day")
        return []          # empty index ⇒ nothing remote ⇒ nothing wanted

    async def profile_fetch(_client, pid):
        payload_calls.append(f"profile:{pid}")
        return []

    await _run_periodic(monkeypatch, window_days=3,
                        day_fetch=day_fetch, profile_fetch=profile_fetch)

    assert payload_calls == [], (
        f"nothing was missing, yet measurements were still fetched: {payload_calls}"
    )


@pytest.mark.asyncio
async def test_a_few_late_arrivals_are_fetched_one_by_one(monkeypatch):
    """155 KB each beats 18.4 MB for the whole day."""
    from domains import sensors

    day_calls: list[str] = []
    profile_calls: list[str] = []

    async def day_fetch(_client, start, _end, params):
        if params is None:
            return [{"_id": f"{_PLATFORM}_{start.day:03d}",
                     "date_updated_argovis": "2026-01-01T00:00:00Z"}]
        day_calls.append("day")
        return []

    async def profile_fetch(_client, pid):
        profile_calls.append(pid)
        return []

    await _run_periodic(monkeypatch, window_days=3,
                        day_fetch=day_fetch, profile_fetch=profile_fetch)

    assert len(profile_calls) == 3, (
        f"expected one request per missing profile, got {profile_calls}"
    )
    assert day_calls == [], (
        "the day payload was fetched for a handful of profiles — that is the "
        "18.4 MB this gate exists to avoid"
    )


@pytest.mark.asyncio
async def test_a_mostly_missing_day_takes_one_bulk_request(monkeypatch):
    """⛔ Above the threshold, per-profile fetching is more requests AND more
    bytes. A virgin backfill day is ~500 profiles."""
    from domains import sensors

    monkeypatch.setattr(sensors, "_ARGO_PROFILE_FETCH_MAX", 2)

    day_calls: list[str] = []
    profile_calls: list[str] = []

    async def day_fetch(_client, start, _end, params):
        if params is None:
            return [{"_id": f"{_PLATFORM}_{start.day:03d}_{n}",
                     "date_updated_argovis": "2026-01-01T00:00:00Z"} for n in range(5)]
        day_calls.append("day")
        return []

    async def profile_fetch(_client, pid):
        profile_calls.append(pid)
        return []

    await _run_periodic(monkeypatch, window_days=1,
                        day_fetch=day_fetch, profile_fetch=profile_fetch)

    assert day_calls == ["day"], f"expected one bulk request, got {day_calls}"
    assert profile_calls == [], (
        f"{len(profile_calls)} single-profile requests above the threshold — "
        "that is more requests and more bytes than the bulk answer"
    )


@pytest.mark.asyncio
async def test_a_single_profile_request_carries_one_id_and_its_data(monkeypatch):
    """⛔ ArgoVis has no multi-id endpoint: `id=a,b` is HTTP 400 and a repeated
    `id=` parameter is HTTP 400. Anyone batching these gets an error, not a
    saving — so the request shape is pinned."""
    import httpx
    from domains import sensors

    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        return httpx.Response(200, json=[{"_id": "X_1"}])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        got = await sensors._fetch_argo_profile(client, "4903739_058")

    assert got == [{"_id": "X_1"}]
    assert seen[0]["id"] == "4903739_058"
    assert "," not in seen[0]["id"], "ArgoVis answers 400 to a comma-separated id list"
    assert seen[0]["data"] == "all", "a profile fetched without its measurements is pointless"


# ── every ArgoVis call is retried, not just the window fetches ──────────────

@pytest.mark.asyncio
async def test_the_vocabulary_fetch_survives_a_rate_limit(monkeypatch):
    """⛔ Observed on production 2026-09-10, minutes after the gate started
    making thirty extra requests per run:

        httpx.HTTPStatusError: Client error '429 Too Many Requests'
          for url '.../argo/vocabulary?parameter=data'

    That call had no retry and is the FIRST thing a sync does, so one 429
    there aborted the entire run before a single day was walked. Splitting a
    window into days multiplies requests and therefore the chance of meeting
    a limit; one unprotected call turns that into a total stall.
    """
    import httpx
    from domains import sensors

    monkeypatch.setattr(sensors, "_ARGO_429_BASE_WAIT_SECONDS", 0.0)
    monkeypatch.setattr(sensors, "_argo_param_vocab_cache", None, raising=False)

    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"message": "slow down"})
        return httpx.Response(200, json=["pressure", "temperature"])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        got = await sensors._fetch_argo_param_vocabulary(client)

    assert got == ["pressure", "temperature"]
    assert calls["n"] == 2, "the 429 was not retried — the whole sync would abort"
    monkeypatch.setattr(sensors, "_argo_param_vocab_cache", None, raising=False)


@pytest.mark.asyncio
async def test_a_non_429_error_on_the_vocabulary_still_raises(monkeypatch):
    """Retrying "ask again" must not become retrying everything."""
    import httpx
    from domains import sensors

    monkeypatch.setattr(sensors, "_ARGO_429_BASE_WAIT_SECONDS", 0.0)
    monkeypatch.setattr(sensors, "_argo_param_vocab_cache", None, raising=False)

    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404, json={"message": "gone"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await sensors._fetch_argo_param_vocabulary(client)

    # ⛔ Assert the COUNT, not just that it eventually raised. Retrying every
    # HTTP status still ends in the same exception after the last attempt, so
    # "it raised" passes happily while we hammer a source that already told us
    # the answer. A sabotage removing the 429 check went undetected until this
    # line was added.
    assert calls["n"] == 1, (
        f"a 404 was retried {calls['n']} times; only 429 and transport failures "
        "mean 'ask again' — everything else is an answer we should respect"
    )
    monkeypatch.setattr(sensors, "_argo_param_vocab_cache", None, raising=False)


@pytest.mark.asyncio
async def test_an_empty_upsert_never_touches_the_pool():
    """⛔ The pool has max_size=4 and the gate now skips whole days.

    An unconditional acquire would take a connection — and run the three
    spatial enrichment queries — once per skipped day, for nothing. Guarding
    at the call sites instead would leave the next caller to remember.
    """
    import db
    from domains import sensors

    class RefusingPool:
        def acquire(self):
            raise AssertionError(
                "a connection was acquired for zero profiles; the early return "
                "in _upsert_argo_profiles is gone"
            )

    original = db.pool
    db.pool = RefusingPool()          # type: ignore[assignment]
    try:
        inserted, platform_ids, revised = await sensors._upsert_argo_profiles([], ["temperature"])
    finally:
        db.pool = original

    assert inserted == 0
    assert platform_ids == set()


# ── profiles we deliberately do not store ───────────────────────────────────
#
# Measured on production 2026-09-10, the first run with the gate acting:
# 30 profiles fetched, 0 stored. They declare `temperature` in data_info while
# every one of their ~1000 values is null, and the upsert drops a profile with
# no temperature at all. The gate sees parameter NAMES only, so it asked for
# the same 30 again on the next run — 30 x 155 KB, twice a day, in perpetuity.
#
# ⛔ Remembering the decision must not turn a temporary gap into a permanent
# one: Argo's delayed-mode QC can FILL IN a column that was empty in real
# time, so the skip is valid only for the revision we judged.

_JUDGED = datetime(2026, 1, 1, tzinfo=timezone.utc)
_REVISED = datetime(2026, 8, 1, tzinfo=timezone.utc)


async def _plan_with_skips(skips, index):
    """skips: (profile_id, date_updated_argovis_when_judged)"""
    import asyncpg
    import db
    from domains import sensors

    pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    db.pool = pool
    try:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM argo_profiles WHERE platform_id = $1", _PLATFORM)
            await conn.execute(
                "DELETE FROM argo_skipped_profiles WHERE profile_id LIKE $1", f"{_PLATFORM}%")
            for pid, judged in skips:
                await conn.execute(
                    """INSERT INTO argo_skipped_profiles
                           (profile_id, date_updated_argovis, reason)
                       VALUES ($1, $2, 'no temperature values')""",
                    pid, judged,
                )
            return await sensors.argo_day_plan(conn, _DAY_START, _DAY_END, index)
    finally:
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM argo_skipped_profiles WHERE profile_id LIKE $1", f"{_PLATFORM}%")
        await pool.close()


@pytest.mark.asyncio
async def test_a_profile_we_already_rejected_is_not_asked_for_again():
    """⛔ The loop this closes: fetched every run, stored never."""
    pid = f"{_PLATFORM}_501"
    plan = await _plan_with_skips(
        [(pid, _JUDGED)],
        _index([(pid, "2026-01-01T00:00:00Z")]),
    )
    assert plan.wanted == [], (
        "a profile we have already looked at and rejected is being fetched "
        "again — 155 KB per run, forever, for a row we will drop"
    )
    assert plan.fetch_data is False


@pytest.mark.asyncio
async def test_a_rejected_profile_is_reconsidered_once_the_source_revises_it():
    """⛔ Delayed-mode QC can fill in a column that was empty in real time.

    Without this, remembering the rejection would turn a temporary gap into a
    permanent one — the opposite of what the record is for.
    """
    pid = f"{_PLATFORM}_502"
    plan = await _plan_with_skips(
        [(pid, _JUDGED)],
        _index([(pid, "2026-08-01T00:00:00Z")]),      # newer than when we judged
    )
    assert plan.wanted == [pid], (
        "the source revised a profile we once rejected and we ignored it; the "
        "skip record must be keyed on the revision, not on the id alone"
    )


@pytest.mark.asyncio
async def test_a_rejection_with_no_stamp_is_not_reconsidered_forever():
    """A skip recorded without a stamp means "judged, revision unknown".

    ⚠️ Treating that as "always reconsider" would restore the loop for every
    row written before the source started sending a stamp.
    """
    pid = f"{_PLATFORM}_503"
    plan = await _plan_with_skips(
        [(pid, None)],
        _index([(pid, "2026-08-01T00:00:00Z")]),
    )
    assert plan.wanted == []


@pytest.mark.asyncio
async def test_rejections_do_not_hide_a_genuinely_new_profile():
    """⛔ The record must narrow nothing beyond its own ids."""
    rejected = f"{_PLATFORM}_504"
    fresh = f"{_PLATFORM}_505"
    plan = await _plan_with_skips(
        [(rejected, _JUDGED)],
        _index([(rejected, "2026-01-01T00:00:00Z"), (fresh, "2026-01-01T00:00:00Z")]),
    )
    assert plan.wanted == [fresh]
    assert plan.n_new == 1


@pytest.mark.asyncio
async def test_a_batch_of_nothing_but_rejects_still_records_them():
    """⛔ The case that created the loop in the first place.

    When every profile in a batch is dropped, `touched_ids` is empty. A record
    written inside `if touched_ids:` would never run for exactly the batches
    that need it, and the gate would keep asking forever while the log said
    "0 new".
    """
    import asyncpg
    import db
    from domains import sensors

    pid = f"{_PLATFORM}_601"
    profile = {
        "_id": pid,
        "timestamp": "2020-05-01T00:00:00Z",
        "date_updated_argovis": "2026-01-01T00:00:00Z",
        "geolocation": {"type": "Point", "coordinates": [-30.0, 40.0]},
        "geolocation_argoqc": 1,
        # ⛔ temperature is DECLARED but every value is null — exactly the
        # shape production served: 1016 levels, 0 usable readings.
        "data": [[10.0, 1500.0], [None, None]],
        "data_info": [["pressure", "temperature"], [], []],
    }

    pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    db.pool = pool
    try:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM argo_profiles WHERE platform_id = $1", _PLATFORM)
            await conn.execute(
                "DELETE FROM argo_skipped_profiles WHERE profile_id LIKE $1", f"{_PLATFORM}%")

        inserted, _, _revised = await sensors._upsert_argo_profiles(
            [profile], ["pressure", "temperature"])

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT reason, date_updated_argovis FROM argo_skipped_profiles "
                "WHERE profile_id = $1", pid)
            stored = await conn.fetchval(
                "SELECT count(*) FROM argo_profiles WHERE profile_id = $1", pid)

        assert inserted == 0
        assert stored == 0, "a profile with no temperature values must not be stored"
        assert row is not None, (
            "nothing was stored, so nothing was recorded — the gate will ask "
            "for this profile on every run for as long as it exists"
        )
        assert row["reason"] == "no temperature values"
        assert row["date_updated_argovis"] == datetime(2026, 1, 1, tzinfo=timezone.utc), (
            "the revision we judged was not recorded, so a later correction "
            "could never be noticed"
        )
    finally:
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM argo_skipped_profiles WHERE profile_id LIKE $1", f"{_PLATFORM}%")
        await pool.close()
