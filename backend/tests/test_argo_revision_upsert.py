# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""A corrected profile has to reach the row the map reads.

ArgoVis publishes real-time data first and a quality-controlled delayed-mode
version months later. `argo_profile_values` already accepted those revisions
(`ON CONFLICT ... DO UPDATE`); `argo_profiles` — the summary row every map
query reads — dropped them on the floor with `DO NOTHING`. The two halves of
the same profile could disagree, and the half nobody could see was the
correct one.

Turning that into DO UPDATE creates a second problem, and this file guards
both halves:

  - a corrected profile overwrites the summary, the QC flags, the position
    AND the WOA climatology that is derived from that position;
  - the same revision seen twice writes nothing, so the backfill cannot
    rewrite ~389k rows on every pass;
  - ⛔ a position that moves out of range CLEARS near_mining and its zone
    columns. Nothing else in the codebase ever sets near_mining back to
    FALSE — it was written when a row's position could not change.
"""
import os
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)

_PLATFORM = "9999007"
_PID = f"{_PLATFORM}_1"

# Clarion-Clipperton: a square that a real ISA contract could plausibly sit in.
_ZONE_LON, _ZONE_LAT = -130.0, 12.0
# ~9,000 km away — comfortably outside the 200 km near_mining radius.
_FAR_LON, _FAR_LAT = 20.0, -40.0


def _profile(lon, lat, updated, temp=5.0):
    return {
        "_id": _PID,
        "timestamp": "2026-01-15T00:00:00Z",
        "geolocation": {"type": "Point", "coordinates": [lon, lat]},
        "geolocation_argoqc": 1,
        "date_updated_argovis": updated,
        "data": [[10.0, 1500.0], [temp, 2.0]],
        "data_info": [["pressure", "temperature"], [], []],
    }


async def _pool():
    import asyncpg
    import db

    pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    db.pool = pool
    return pool


async def _clean(conn):
    await conn.execute("DELETE FROM argo_profile_values WHERE profile_id = $1", _PID)
    await conn.execute("DELETE FROM argo_profiles WHERE platform_id = $1", _PLATFORM)
    await conn.execute(
        "DELETE FROM mining_contracts WHERE isa_id LIKE 'TEST-REVISION%'"
    )


async def _seed_contract(conn, lon=None, lat=None, isa_id="TEST-REVISION",
                         name="Test Contractor"):
    """A contract polygon the float can be inside, then outside."""
    await conn.execute(
        """
        INSERT INTO mining_contracts (isa_id, contractor_name, geom)
        VALUES ($3, $4,
                ST_Multi(ST_Buffer(ST_SetSRID(ST_MakePoint($1,$2),4326)::geography,
                                   50000)::geometry))
        """,
        _ZONE_LON if lon is None else lon,
        _ZONE_LAT if lat is None else lat,
        isa_id, name,
    )


async def _row(conn):
    return await conn.fetchrow(
        "SELECT * FROM argo_profiles WHERE profile_id = $1", _PID
    )


# ── the revision reaches the summary row ────────────────────────────────────

@pytest.mark.asyncio
async def test_a_newer_revision_overwrites_the_summary_row():
    """DO NOTHING froze argo_profiles at whatever we saw first."""
    from domains import sensors

    pool = await _pool()
    try:
        async with pool.acquire() as conn:
            await _clean(conn)
        await sensors._upsert_argo_profiles(
            [_profile(_FAR_LON, _FAR_LAT, "2026-01-16T00:00:00.000Z", temp=5.0)],
            ["pressure", "temperature"],
        )
        await sensors._upsert_argo_profiles(
            [_profile(_FAR_LON, _FAR_LAT, "2026-06-01T00:00:00.000Z", temp=7.25)],
            ["pressure", "temperature"],
        )
        async with pool.acquire() as conn:
            row = await _row(conn)
        assert row["surface_temp_c"] == pytest.approx(7.25), (
            "the delayed-mode correction did not reach argo_profiles — the map "
            "still reads the real-time value while argo_profile_values holds "
            "the corrected one"
        )
        assert row["date_updated_argovis"] == datetime(2026, 6, 1, tzinfo=timezone.utc)
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_a_correction_is_counted_as_corrected_not_as_new():
    """`inserted` drives _log_sync; a rewrite is not a new profile."""
    from domains import sensors

    pool = await _pool()
    try:
        async with pool.acquire() as conn:
            await _clean(conn)
        first, _p, revised_first = await sensors._upsert_argo_profiles(
            [_profile(_FAR_LON, _FAR_LAT, "2026-01-16T00:00:00.000Z")],
            ["pressure", "temperature"],
        )
        second, _p2, revised_second = await sensors._upsert_argo_profiles(
            [_profile(_FAR_LON, _FAR_LAT, "2026-06-01T00:00:00.000Z", temp=7.25)],
            ["pressure", "temperature"],
        )
        assert (first, revised_first) == (1, 0), "a first sighting is an insert"
        assert (second, revised_second) == (0, 1), (
            "a rewritten row was counted as new — `xmax = 0` is the only thing "
            "that tells an insert from an update, because both report "
            "'INSERT 0 1'"
        )
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_the_same_revision_twice_writes_nothing():
    """⛔ Without this the backfill rewrites ~389k rows on every pass."""
    from domains import sensors

    pool = await _pool()
    try:
        async with pool.acquire() as conn:
            await _clean(conn)
        await sensors._upsert_argo_profiles(
            [_profile(_FAR_LON, _FAR_LAT, "2026-01-16T00:00:00.000Z")],
            ["pressure", "temperature"],
        )
        async with pool.acquire() as conn:
            before = (await _row(conn))["synced_at"]
        got, _p, revised = await sensors._upsert_argo_profiles(
            [_profile(_FAR_LON, _FAR_LAT, "2026-01-16T00:00:00.000Z")],
            ["pressure", "temperature"],
        )
        async with pool.acquire() as conn:
            after = (await _row(conn))["synced_at"]
        assert (got, revised) == (0, 0), (
            "an unchanged revision was written again — every backfill pass "
            "would rewrite the whole table and make that many dead tuples"
        )
        assert after == before, "synced_at moved, so the row really was rewritten"
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_the_climatology_moves_with_the_position(monkeypatch):
    """⛔ woa_* is a pure function of (lat, lon, month).

    Leaving the old climatology beside a corrected position turns every
    `temp - woa_temp` anomaly on that row into a fiction.

    ⚠️ The real WOA grids are not present outside the VPS — `enrich_profile`
    returns all-None here, and all-None cannot tell "moved" from "did not
    move". So the climatology is stubbed with a function of longitude: what
    this guards is our SQL carrying the enrichment forward with geom, which
    is the part that can regress.
    """
    from domains import sensors
    from services import woa_climatology

    def fake_enrich(lat, lon, month, surface_depth, deep_depth):
        return {k: (None if k != "woa_surface_temp_c" else round(lon, 3))
                for k in (
                    "woa_surface_temp_c", "woa_surface_sal", "woa_deep_temp_c",
                    "woa_deep_sal", "woa_deep_oxygen_umol_kg", "woa_deep_aou",
                    "woa_deep_o2sat", "woa_deep_phosphate", "woa_deep_silicate",
                    "woa_deep_nitrate",
                )}

    monkeypatch.setattr(woa_climatology, "enrich_profile", fake_enrich)

    pool = await _pool()
    try:
        async with pool.acquire() as conn:
            await _clean(conn)
        await sensors._upsert_argo_profiles(
            [_profile(_FAR_LON, _FAR_LAT, "2026-01-16T00:00:00.000Z")],
            ["pressure", "temperature"],
        )
        async with pool.acquire() as conn:
            before = await _row(conn)
        await sensors._upsert_argo_profiles(
            [_profile(_ZONE_LON, _ZONE_LAT, "2026-06-01T00:00:00.000Z")],
            ["pressure", "temperature"],
        )
        async with pool.acquire() as conn:
            after = await _row(conn)

        assert before["woa_surface_temp_c"] == pytest.approx(_FAR_LON), (
            "fixture problem: the stub did not reach the insert, so this test "
            "cannot tell whether the correction replaced the climatology"
        )
        assert after["woa_surface_temp_c"] == pytest.approx(_ZONE_LON), (
            "the position moved ~9,000 km and the WOA climatology did not "
            "follow it — the anomaly on this row is now computed against the "
            "wrong part of the ocean"
        )
    finally:
        await pool.close()


# ── Step 0: the zone columns must be able to go back ────────────────────────

@pytest.mark.asyncio
async def test_a_float_that_moves_out_of_range_stops_being_near_mining():
    """⛔ Nothing else in the codebase ever writes near_mining = FALSE."""
    from domains import sensors

    pool = await _pool()
    try:
        async with pool.acquire() as conn:
            await _clean(conn)
            await _seed_contract(conn)

        await sensors._upsert_argo_profiles(
            [_profile(_ZONE_LON, _ZONE_LAT, "2026-01-16T00:00:00.000Z")],
            ["pressure", "temperature"],
        )
        async with pool.acquire() as conn:
            inside = await _row(conn)
        assert inside["near_mining"] is True, (
            "fixture problem: the float was not flagged near_mining in the "
            "first place, so this test could not detect a failure to clear it"
        )
        assert inside["mining_zone"] == "Test Contractor"

        await sensors._upsert_argo_profiles(
            [_profile(_FAR_LON, _FAR_LAT, "2026-06-01T00:00:00.000Z")],
            ["pressure", "temperature"],
        )
        async with pool.acquire() as conn:
            outside = await _row(conn)

        assert outside["near_mining"] is False, (
            "the corrected fix is ~9,000 km from the nearest contract and the "
            "float is still flagged as being at a mine — the map shows a "
            "float somewhere it is not"
        )
        assert outside["mining_zone"] is None, (
            "near_mining was cleared but the contractor name was left behind"
        )
        assert outside["mining_dist_km"] is None
        assert outside["nearest_contract_lon"] is None
        assert outside["nearest_contract_lat"] is None
    finally:
        async with pool.acquire() as conn:
            await _clean(conn)
        await pool.close()


@pytest.mark.asyncio
async def test_a_corrected_position_is_attributed_to_the_contract_it_moved_to():
    """The zone has to follow the fix, not merely survive it.

    ⚠️ Written this way on purpose. An earlier version corrected the float
    WITHIN one contract and asserted the zone was still there — and no
    sabotage of Step 0 or of the refresh could turn it red, because a stale
    value and a recomputed value were the same string. Two contracts make
    the difference visible: a float that drifts from one contractor's block
    into another's must stop being reported under the first.
    """
    from domains import sensors

    pool = await _pool()
    try:
        async with pool.acquire() as conn:
            await _clean(conn)
            await _seed_contract(conn)
            # A second block ~150 km east — still inside the 200 km radius of
            # the first, so near_mining stays TRUE either way and the only
            # thing that can change is WHICH contractor is named.
            await _seed_contract(
                conn, lon=_ZONE_LON + 1.4, lat=_ZONE_LAT,
                isa_id="TEST-REVISION-B", name="Second Contractor",
            )

        await sensors._upsert_argo_profiles(
            [_profile(_ZONE_LON, _ZONE_LAT, "2026-01-16T00:00:00.000Z")],
            ["pressure", "temperature"],
        )
        async with pool.acquire() as conn:
            before = await _row(conn)
        assert before["mining_zone"] == "Test Contractor", (
            "fixture problem: the float did not land in the first block, so "
            "this test cannot tell whether the correction re-attributed it"
        )

        await sensors._upsert_argo_profiles(
            [_profile(_ZONE_LON + 1.4, _ZONE_LAT, "2026-06-01T00:00:00.000Z")],
            ["pressure", "temperature"],
        )
        async with pool.acquire() as conn:
            after = await _row(conn)

        assert after["near_mining"] is True, (
            "the corrected fix is still inside a contract block and the float "
            "was un-flagged — Step 0 is clearing rows it should leave alone"
        )
        assert after["mining_zone"] == "Second Contractor", (
            f"the float moved into another contractor's block and is still "
            f"reported under {before['mining_zone']!r} — the zone did not "
            "follow the corrected position"
        )
        names = {z["name"] for z in (after["mining_zones"] and
                                     __import__("json").loads(after["mining_zones"]))}
        assert names == {"Test Contractor", "Second Contractor"}, (
            f"mining_zones lists {names} — the full zone list was not "
            "recomputed against the corrected position"
        )
    finally:
        async with pool.acquire() as conn:
            await _clean(conn)
        await pool.close()


# ── the repair path ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_values_are_written_even_when_the_header_is_unchanged():
    """The header INSERT and the values executemany are not one transaction.

    An interrupted run leaves a header with no values. The gate calls that
    day broken and asks for the profile again — at the SAME revision, so the
    header write is correctly rejected. If the values write hung off that
    rejection, the gate would report the day broken forever and this call
    would never repair it.
    """
    from domains import sensors

    pool = await _pool()
    try:
        async with pool.acquire() as conn:
            await _clean(conn)
        await sensors._upsert_argo_profiles(
            [_profile(_FAR_LON, _FAR_LAT, "2026-01-16T00:00:00.000Z")],
            ["pressure", "temperature"],
        )
        # Simulate the interrupted run: header kept, values lost.
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM argo_profile_values WHERE profile_id = $1", _PID
            )

        await sensors._upsert_argo_profiles(
            [_profile(_FAR_LON, _FAR_LAT, "2026-01-16T00:00:00.000Z")],
            ["pressure", "temperature"],
        )
        async with pool.acquire() as conn:
            n = await conn.fetchval(
                "SELECT COUNT(*) FROM argo_profile_values WHERE profile_id = $1", _PID
            )
        assert n > 0, (
            "the header was rejected as unchanged and the measurements were "
            "skipped with it, so a half-written profile can never be repaired"
        )
    finally:
        await pool.close()
