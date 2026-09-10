# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Regression guards for the three Argo truncations removed 2026-09-09:
(a) ISA-zone-only polygon query -> global, (b) the destructive 180-day
DELETE -> none (history persists), (c) 5-of-35 parameters -> all of them.
The fourth truncation (surface/deep-only depth sampling) is unchanged and
NOT covered here — see extract_argo_measurements for that.

Executes against real PostGIS (TEST_DATABASE_URL) per repo policy: tests must
run code, not grep it.
"""
import os
from datetime import date, datetime, timezone

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)


def _fixture_profile(data_info_vars, data_cols, lon=170.0, lat=10.0,
                      profile_id="1900001_001", ts="2026-06-01T00:00:00Z"):
    return {
        "_id": profile_id,
        "geolocation": {"coordinates": [lon, lat]},
        "timestamp": ts,
        "data_info": [data_info_vars, [], []],
        "data": data_cols,
    }


# ── extract_argo_long_form: pure-function coverage, no DB needed ───────────

def test_extract_argo_long_form_captures_present_param_with_qc():
    from domains.sensors import extract_argo_long_form

    profile = _fixture_profile(
        ["pressure", "nitrate", "nitrate_argoqc", "chla", "chla_argoqc"],
        [
            [5, 500],          # pressure: surface=5, deep=500
            [12.5, 30.1],      # nitrate
            [1, 2],            # nitrate_argoqc
            [0.4, None],       # chla — no deep reading
            [1, None],         # chla_argoqc
        ],
    )
    rows = extract_argo_long_form(profile, ["pressure", "nitrate", "nitrate_argoqc", "chla", "chla_argoqc"])
    by_key = {(r["level"], r["param"]): r for r in rows}

    assert by_key[("surface", "nitrate")]["value"] == 12.5
    assert by_key[("surface", "nitrate")]["qc"] == 1
    assert by_key[("deep", "nitrate")]["value"] == 30.1
    assert by_key[("deep", "nitrate")]["qc"] == 2

    assert by_key[("surface", "chla")]["value"] == 0.4
    assert by_key[("surface", "chla")]["qc"] == 1
    # chla has no deep value (None) -> no row, never a 0
    assert ("deep", "chla") not in by_key
    # pressure and *_argoqc columns are not themselves emitted as params
    assert not any(r["param"] in ("pressure", "nitrate_argoqc", "chla_argoqc") for r in rows)


def test_extract_argo_long_form_absent_param_produces_no_row():
    from domains.sensors import extract_argo_long_form

    profile = _fixture_profile(["pressure", "temperature"], [[5, 500], [10.0, 4.0]])
    rows = extract_argo_long_form(profile, ["pressure", "temperature", "nitrate"])
    assert not any(r["param"] == "nitrate" for r in rows)


def test_extract_argo_long_form_column_major_mismatched_lengths_do_not_mix():
    """Two variables with DIFFERENT column lengths must never have one's
    values read at the other's offsets (the WOD-oxygen ragged-array trap)."""
    from domains.sensors import extract_argo_long_form

    # pressure has 3 levels; "doxy" only has 2 (shorter — e.g. sensor
    # stopped reporting partway through the profile).
    profile = _fixture_profile(
        ["pressure", "doxy", "temperature"],
        [
            [5, 250, 500],      # pressure: surface idx 0, deep idx 2
            [200.0, 180.0],     # doxy — length 2, shorter than pressure
            [12.0, 8.0, 4.0],   # temperature — full length
        ],
    )
    rows = extract_argo_long_form(profile, ["pressure", "doxy", "temperature"])
    by_key = {(r["level"], r["param"]): r for r in rows}

    # temperature: surface idx 0 -> 12.0, deep idx 2 -> 4.0 (full column, both valid)
    assert by_key[("surface", "temperature")]["value"] == 12.0
    assert by_key[("deep", "temperature")]["value"] == 4.0

    # doxy: surface idx 0 -> 200.0 is safe (0 < len(doxy)==2).
    assert by_key[("surface", "doxy")]["value"] == 200.0
    # deep idx is 2, but doxy's column only has indices 0-1 — must be
    # skipped, NOT filled in with doxy[1] (180.0) or any other column's
    # value at index 2 (temperature's 4.0). Silent index reuse across
    # differently-sized columns is exactly the corruption this test guards.
    assert ("deep", "doxy") not in by_key
    assert by_key[("surface", "doxy")]["value"] != by_key[("surface", "temperature")]["value"]


# ── DB-backed: argo_profile_values persistence + backfill cursor ───────────

async def _clean_argo_tables(conn):
    await conn.execute("DELETE FROM argo_profile_values")
    await conn.execute("DELETE FROM argo_profiles")
    await conn.execute("DELETE FROM argo_backfill_state")
    await conn.execute("DELETE FROM sync_log WHERE source = 'argo_profiles'")


@pytest.mark.asyncio
async def test_upsert_writes_long_form_values_with_qc_and_skips_absent_param(monkeypatch):
    import asyncpg
    import db
    from domains import sensors

    pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    db.pool = pool
    try:
        async with pool.acquire() as conn:
            await _clean_argo_tables(conn)

        def fake_enrich(*args, **kwargs):
            return {
                "woa_surface_temp_c": None, "woa_surface_sal": None,
                "woa_deep_temp_c": None, "woa_deep_sal": None,
                "woa_deep_oxygen_umol_kg": None, "woa_deep_aou": None,
                "woa_deep_o2sat": None, "woa_deep_phosphate": None,
                "woa_deep_silicate": None, "woa_deep_nitrate": None,
            }
        monkeypatch.setattr(sensors.woa_climatology, "enrich_profile", fake_enrich)

        profile = _fixture_profile(
            ["pressure", "temperature", "nitrate", "nitrate_argoqc", "chla"],
            [
                [5, 500],
                [15.0, 3.0],
                [8.0, 20.0],
                [1, 1],
                [0.2, None],
            ],
            profile_id="testplat_001",
        )
        params = ["pressure", "temperature", "nitrate", "nitrate_argoqc", "chla"]
        inserted, new_platforms, _revised = await sensors._upsert_argo_profiles([profile], params)
        assert inserted == 1
        assert "testplat" in new_platforms

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT level, param, value, qc FROM argo_profile_values WHERE profile_id = $1 ORDER BY level, param",
                "testplat_001",
            )
        by_key = {(r["level"], r["param"]): r for r in rows}
        assert by_key[("surface", "nitrate")]["value"] == 8.0
        assert by_key[("surface", "nitrate")]["qc"] == 1
        # chla present at surface only (deep is None) — no deep row
        assert by_key[("surface", "chla")]["value"] == 0.2
        assert ("deep", "chla") not in by_key
        # a param the profile doesn't carry (e.g. "doxy") produces no row at all
        assert not any(k[1] == "doxy" for k in by_key)
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_upsert_rerun_does_not_duplicate_rows(monkeypatch):
    import asyncpg
    import db
    from domains import sensors

    pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    db.pool = pool
    try:
        async with pool.acquire() as conn:
            await _clean_argo_tables(conn)

        def fake_enrich(*args, **kwargs):
            return {k: None for k in (
                "woa_surface_temp_c", "woa_surface_sal", "woa_deep_temp_c", "woa_deep_sal",
                "woa_deep_oxygen_umol_kg", "woa_deep_aou", "woa_deep_o2sat",
                "woa_deep_phosphate", "woa_deep_silicate", "woa_deep_nitrate",
            )}
        monkeypatch.setattr(sensors.woa_climatology, "enrich_profile", fake_enrich)

        profile = _fixture_profile(
            ["pressure", "temperature", "nitrate"],
            [[5, 500], [15.0, 3.0], [8.0, 20.0]],
            profile_id="test_rerun_001",
        )
        params = ["pressure", "temperature", "nitrate"]
        await sensors._upsert_argo_profiles([profile], params)
        # second pass over the exact same profile — must UPSERT, not duplicate
        await sensors._upsert_argo_profiles([profile], params)

        async with pool.acquire() as conn:
            n_values = await conn.fetchval(
                "SELECT COUNT(*) FROM argo_profile_values WHERE profile_id = $1", "test_rerun_001",
            )
            n_profiles = await conn.fetchval(
                "SELECT COUNT(*) FROM argo_profiles WHERE profile_id = $1", "test_rerun_001",
            )
        # surface+deep for temperature and nitrate = 4 rows; a re-run must
        # UPSERT in place, not append duplicates.
        assert n_values == 4
        assert n_profiles == 1
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_history_survives_a_sync_run_no_delete(monkeypatch):
    """The point of removing truncation (b): an old profile inserted directly
    (simulating backfilled history) must still be present after
    _upsert_argo_profiles processes an unrelated, recent profile. There must
    be no DELETE anywhere in the Argo sync path any more."""
    import asyncpg
    import db
    from domains import sensors

    pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    db.pool = pool
    try:
        async with pool.acquire() as conn:
            await _clean_argo_tables(conn)
            await conn.execute(
                """INSERT INTO argo_profiles (profile_id, platform_id, profile_date, geom)
                   VALUES ($1, $2, $3, ST_SetSRID(ST_MakePoint($4,$5),4326))""",
                "test_old_001", "test_old", datetime(2015, 1, 1, tzinfo=timezone.utc), 10.0, 10.0,
            )

        def fake_enrich(*args, **kwargs):
            return {k: None for k in (
                "woa_surface_temp_c", "woa_surface_sal", "woa_deep_temp_c", "woa_deep_sal",
                "woa_deep_oxygen_umol_kg", "woa_deep_aou", "woa_deep_o2sat",
                "woa_deep_phosphate", "woa_deep_silicate", "woa_deep_nitrate",
            )}
        monkeypatch.setattr(sensors.woa_climatology, "enrich_profile", fake_enrich)

        recent = _fixture_profile(
            ["pressure", "temperature"], [[5, 500], [15.0, 3.0]],
            profile_id="test_recent_001",
        )
        await sensors._upsert_argo_profiles([recent], ["pressure", "temperature"])

        async with pool.acquire() as conn:
            still_there = await conn.fetchval(
                "SELECT COUNT(*) FROM argo_profiles WHERE profile_id = 'test_old_001'"
            )
        assert still_there == 1, "history was deleted by a sync run — truncation (b) is back"
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_backfill_cursor_does_not_advance_on_chunk_failure(monkeypatch):
    import asyncpg
    import db
    from domains import sensors

    pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    db.pool = pool
    try:
        async with pool.acquire() as conn:
            await _clean_argo_tables(conn)
            await conn.execute(
                """INSERT INTO argo_backfill_state (id, done_through, updated_at)
                   VALUES (1, $1, NOW())""",
                date(2020, 1, 1),
            )

        async def fake_vocab(client):
            return ["pressure", "temperature"]
        monkeypatch.setattr(sensors, "_fetch_argo_param_vocabulary", fake_vocab)

        async def failing_fetch(client, start, end, params):
            raise RuntimeError("simulated ArgoVis outage mid-chunk")
        monkeypatch.setattr(sensors, "_fetch_argo_window", failing_fetch)
        # A month is thirty requests since 2026-09-10; without this the
        # pacing sleep between them dominates the test's runtime.
        monkeypatch.setattr(sensors, "_ARGO_BACKFILL_CHUNK_PACING_SECONDS", 0)

        result = await sensors.sync_argo_profiles_backfill(budget_seconds=30)
        assert result["months_done"] == 0

        async with pool.acquire() as conn:
            done_through = await conn.fetchval(
                "SELECT done_through FROM argo_backfill_state WHERE id = 1"
            )
        assert done_through == date(2020, 1, 1), "cursor advanced despite a failed chunk"
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_backfill_cursor_advances_on_successful_chunk(monkeypatch):
    import asyncpg
    import db
    from domains import sensors

    pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    db.pool = pool
    try:
        async with pool.acquire() as conn:
            await _clean_argo_tables(conn)
            await conn.execute(
                """INSERT INTO argo_backfill_state (id, done_through, updated_at)
                   VALUES (1, $1, NOW())""",
                date(2020, 1, 1),
            )

        async def fake_vocab(client):
            return ["pressure", "temperature"]
        monkeypatch.setattr(sensors, "_fetch_argo_param_vocabulary", fake_vocab)

        async def fake_fetch(client, start, end, params):
            return []  # empty month, still a "success"
        monkeypatch.setattr(sensors, "_fetch_argo_window", fake_fetch)
        monkeypatch.setattr(sensors, "_ARGO_BACKFILL_CHUNK_PACING_SECONDS", 0)

        # Force exactly one chunk without racing the wall clock or touching
        # the global time module (which asyncio itself relies on): pin
        # "today" to exactly one month after the cursor, so the loop's own
        # `cursor < today` condition ends it after a single chunk.
        class FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2020, 2, 1, tzinfo=timezone.utc)
        monkeypatch.setattr(sensors, "datetime", FixedDatetime)

        result = await sensors.sync_argo_profiles_backfill(budget_seconds=30)
        assert result["months_done"] == 1

        async with pool.acquire() as conn:
            done_through = await conn.fetchval(
                "SELECT done_through FROM argo_backfill_state WHERE id = 1"
            )
        assert done_through == date(2020, 2, 1)
    finally:
        await pool.close()


def test_the_request_asks_for_all_not_a_parameter_list():
    """⛔ ArgoVis `data` is a FILTER, not a column selection: naming parameters
    returns only profiles carrying ALL of them.

    Measured against the live API 2026-09-09, one global day:
        no `data` ........................ 464 profiles
        data=all ......................... 464
        data=temperature ................. 460
        data=temperature,salinity ........ 426
        the five this ingest used to ask . 36   ← 7.8%

    So enumerating parameters was a fifth truncation nobody had noticed, and it
    is why every one of the 2,303 rows in production carried BOTH oxygen and pH
    — 100%, which no real Argo fleet looks like. Enumerating the WHOLE
    vocabulary is worse still: it means "carrying every parameter that exists",
    and the live API answers 400 or an empty 404.

    Nothing about this fails loudly. The sync succeeds, the rows look fine, and
    92% of the ocean is missing. This test is the only thing that notices.
    """
    import inspect
    from domains import sensors
    src = inspect.getsource(sensors._fetch_argo_window)
    assert '"data": "all"' in src, (
        "the Argo window request must ask for data=all; a parameter list "
        "silently filters to profiles carrying every named parameter"
    )
    assert '",".join(params)' not in src, (
        "the request enumerates parameters again — that is the AND-filter bug"
    )


def test_extraction_keeps_a_parameter_the_caller_never_named():
    """With data=all the profile names its own variables, so extraction must
    read data_info[0] rather than a vocabulary list. A float reporting
    something the vocabulary has not caught up with must still be stored —
    the same "we only see what we thought to ask for" failure that hid ONC's
    oxygen readings for months."""
    from domains.sensors import extract_argo_long_form
    profile = {
        "data_info": [["pressure", "bbp700", "bbp700_argoqc"], [], []],
        "data": [[5.0, 900.0], [0.0012, 0.0004], [1, 2]],
    }
    rows = extract_argo_long_form(profile, [])
    params = {r["param"] for r in rows}
    assert "bbp700" in params, (
        "a parameter present in the profile was dropped because the caller "
        "did not name it — extraction is still driven by a list, not the data"
    )
    surface = next(r for r in rows if r["param"] == "bbp700" and r["level"] == "surface")
    assert surface["value"] == 0.0012 and surface["qc"] == 1


@pytest.mark.asyncio
async def test_backfill_retries_a_429_instead_of_treating_it_as_a_dead_chunk(monkeypatch):
    """⛔ ArgoVis rate-limits with 429 and sends NO Retry-After header.

    Observed on the first production backfill 2026-09-09: it walked two months,
    then every request came back 429 — and the endpoint still answered HTTP 200
    with months_done=0. A silent stall reporting success, which is how it could
    have sat there for days. Waiting ~20s cleared the limit, so a 429 means
    "come back later", never "this chunk is dead".
    """
    import db
    from domains import sensors
    import asyncpg
    pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    db.pool = pool
    async with pool.acquire() as conn:
        await _clean_argo_tables(conn)
        await conn.execute(
            "INSERT INTO argo_backfill_state (id, done_through, updated_at) "
            "VALUES (1, $1, NOW()) ON CONFLICT (id) DO UPDATE SET done_through = $1",
            date(2020, 1, 1),
        )
    monkeypatch.setattr(sensors, "_ARGO_429_BASE_WAIT_SECONDS", 0.01)
    monkeypatch.setattr(sensors, "_ARGO_BACKFILL_CHUNK_PACING_SECONDS", 0)

    calls = {"n": 0}

    async def fake_window(client, start, end, params):
        calls["n"] += 1
        if calls["n"] == 1:
            req = httpx.Request("GET", "https://argovis-api.colorado.edu/argo")
            raise httpx.HTTPStatusError(
                "429", request=req, response=httpx.Response(429, request=req))
        return []

    monkeypatch.setattr(sensors, "_fetch_argo_window", fake_window)
    async def fake_vocab(client):
        return ["temperature"]
    monkeypatch.setattr(sensors, "_fetch_argo_param_vocabulary", fake_vocab)

    result = await sensors.sync_argo_profiles_backfill(budget_seconds=5)
    await pool.close()

    assert calls["n"] >= 2, (
        "the 429 was not retried — a rate limit was treated as a permanent "
        "chunk failure and the backfill stalls forever"
    )
    assert result["months_done"] >= 1, (
        "the cursor never advanced despite the retry succeeding"
    )
    assert result["stalled"] is False


@pytest.mark.asyncio
async def test_a_run_that_walked_no_months_reports_itself_stalled(monkeypatch):
    """A backfill that made zero progress must SAY so. It used to answer
    HTTP 200 with months_done=0 and nothing else — indistinguishable from a
    healthy no-op, which is what hid the 429 stall on 2026-09-09."""
    import db
    from domains import sensors
    import asyncpg
    pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    db.pool = pool
    async with pool.acquire() as conn:
        await _clean_argo_tables(conn)
        await conn.execute(
            "INSERT INTO argo_backfill_state (id, done_through, updated_at) "
            "VALUES (1, $1, NOW()) ON CONFLICT (id) DO UPDATE SET done_through = $1",
            date(2020, 1, 1),
        )
    monkeypatch.setattr(sensors, "_ARGO_429_BASE_WAIT_SECONDS", 0.01)
    monkeypatch.setattr(sensors, "_ARGO_429_MAX_ATTEMPTS", 2)

    async def always_429(client, start, end, params):
        req = httpx.Request("GET", "https://argovis-api.colorado.edu/argo")
        raise httpx.HTTPStatusError(
            "429", request=req, response=httpx.Response(429, request=req))

    async def fake_vocab(client):
        return ["temperature"]

    monkeypatch.setattr(sensors, "_fetch_argo_window", always_429)
    monkeypatch.setattr(sensors, "_ARGO_BACKFILL_CHUNK_PACING_SECONDS", 0)
    monkeypatch.setattr(sensors, "_fetch_argo_param_vocabulary", fake_vocab)

    result = await sensors.sync_argo_profiles_backfill(budget_seconds=5)
    await pool.close()

    assert result["stalled"] is True, (
        "a run that walked zero months called itself healthy"
    )
    assert result["failed_chunk"], "the failing chunk was not named"
