# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""We must keep ArgoVis's own revision stamp, not just our write time.

Argo publishes real-time data first and a quality-controlled delayed-mode
version months later. Measured against the live API 2026-09-10: of 464
profiles dated 2024-03-01, eighty had been revised in the previous three
months; of 400 dated 2019-09-01, twenty-five were revised in July 2026.

`synced_at` cannot answer this — it says when WE wrote the row. Only the
source's own stamp distinguishes "corrected since we last looked" from
"a profile we have simply seen before", and that distinction is what will
let a cheap 503 KB metadata request replace an 18.4 MB one.

Covers:
  - the stamp ArgoVis sends is stored
  - it is stored as an AWARE datetime (naive vs aware raises TypeError, and
    that exception is not caught where the fetch happens)
  - a profile without the field stores NULL, not our own clock
  - an unparseable stamp stores NULL and does NOT lose the profile
"""
import os
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)


def _profile(pid: str, updated=None):
    p = {
        "_id": pid,
        "timestamp": "2026-01-15T00:00:00Z",
        "geolocation": {"type": "Point", "coordinates": [-30.0, 40.0]},
        "geolocation_argoqc": 1,
        "data": [[10.0, 1500.0], [5.0, 2.0]],
        "data_info": [["pressure", "temperature"], [], []],
    }
    if updated is not None:
        p["date_updated_argovis"] = updated
    return p


async def _run(profiles):
    import asyncpg
    import db
    from domains import sensors

    pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    db.pool = pool
    try:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM argo_profile_values")
            await conn.execute("DELETE FROM argo_profiles WHERE platform_id = '9999005'")
        await sensors._upsert_argo_profiles(profiles, ["pressure", "temperature"])
        async with pool.acquire() as conn:
            return {
                r["profile_id"]: r["date_updated_argovis"]
                for r in await conn.fetch(
                    "SELECT profile_id, date_updated_argovis FROM argo_profiles "
                    "WHERE platform_id = '9999005'")
            }
    finally:
        await pool.close()


# ── the parser ──────────────────────────────────────────────────────────────

def test_the_stamp_is_parsed_as_an_aware_datetime():
    """⛔ Naive vs aware raises TypeError, uncaught where the fetch happens."""
    from domains import sensors

    got = sensors._parse_argovis_ts("2026-07-28T11:57:00.680Z")
    assert got is not None
    assert got.tzinfo is not None, (
        "a naive datetime cannot be compared with the aware stamps we store; "
        "the TypeError would travel up out of the sync and kill the scheduler"
    )
    assert got == datetime(2026, 7, 28, 11, 57, 0, 680000, tzinfo=timezone.utc)


def test_a_missing_stamp_is_none():
    from domains import sensors

    assert sensors._parse_argovis_ts(None) is None
    assert sensors._parse_argovis_ts("") is None


def test_an_unreadable_stamp_is_none_not_an_exception():
    """A stamp we cannot read must not cost us the profile."""
    from domains import sensors

    assert sensors._parse_argovis_ts("not-a-date") is None


# ── the write path ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_stamp_argovis_sent_reaches_the_database():
    stored = await _run([_profile("9999005_001", "2026-07-28T11:57:00.680Z")])
    got = stored["9999005_001"]
    assert got is not None, "the revision stamp never reached the row"
    assert got == datetime(2026, 7, 28, 11, 57, 0, 680000, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_a_profile_without_a_stamp_stores_null_not_our_clock():
    """⛔ NULL means "we do not know". Substituting now() would make every row
    look freshly revised and defeat the comparison this column exists for."""
    stored = await _run([_profile("9999005_002")])
    assert stored["9999005_002"] is None


@pytest.mark.asyncio
async def test_an_unreadable_stamp_does_not_drop_the_profile():
    stored = await _run([_profile("9999005_003", "28 July 2026")])
    assert "9999005_003" in stored, "a bad date cost us the whole measurement"
    assert stored["9999005_003"] is None
