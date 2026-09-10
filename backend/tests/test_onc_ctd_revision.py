# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""A cast ONC revises must reach the table; an unchanged one must not touch it.

`onc_ctd_profiles` carries `updated_at`, and `sync_onc_ctd` re-fetches a
rolling 7-day window on every run — so ONC gets seven chances to hand us a
delayed-mode QC revision of the same (location, device, cast_time). The insert
was `ON CONFLICT ... DO NOTHING`, so all seven were dropped and `updated_at`
recorded only when we first stored the row.

⛔ A DO NOTHING is not automatically a bug. `sios_datasets` TRUNCATEs in the
same transaction, which makes its DO NOTHING inert — that finding was raised
and rejected on 2026-09-09. Here there is no TRUNCATE of this table anywhere
in onc.py, which is why this one is real. The last test below holds that
distinction in place.

The counter went the same way: `inserted += 1` fired for every profile
FETCHED, including the ones DO NOTHING had just discarded. Production carried
`onc-ctd records_added=15 total_records=15` against 84 rows.
"""
import datetime
import os
import pathlib

import pytest

ONC = pathlib.Path(__file__).resolve().parents[1] / "domains" / "onc.py"

DDL = """
CREATE TABLE IF NOT EXISTS _t_onc_ctd (
    location_code text, device_code text, cast_time timestamptz,
    profile jsonb, updated_at timestamptz,
    PRIMARY KEY (location_code, device_code, cast_time)
)
"""

#: The statement under test, with the table renamed. Kept in sync with the
#: production one by test_the_production_insert_still_has_this_shape below.
UPSERT = """
INSERT INTO _t_onc_ctd (location_code, device_code, cast_time, profile, updated_at)
VALUES ($1, $2, $3, $4::jsonb, NOW())
ON CONFLICT (location_code, device_code, cast_time) DO UPDATE
   SET profile = EXCLUDED.profile, updated_at = NOW()
 WHERE _t_onc_ctd.profile IS DISTINCT FROM EXCLUDED.profile
RETURNING (xmax = 0) AS was_insert
"""


def _sync_onc_ctd_source() -> str:
    src = ONC.read_text(encoding="utf-8")
    start = src.index("async def sync_onc_ctd")
    return src[start:src.index("\n# ── USGS Earthquakes", start)]


def test_the_fixture_actually_isolated_the_function():
    body = _sync_onc_ctd_source()
    assert "onc_ctd_profiles" in body and len(body) > 500, (
        "fixture problem: sync_onc_ctd was not sliced out of onc.py, so every "
        "source assertion below would be searching the wrong text"
    )


def test_the_production_insert_can_revise_a_cast():
    body = _sync_onc_ctd_source()
    ins = body[body.index("INSERT INTO onc_ctd_profiles"):]
    ins = ins[:ins.index('"""')]
    assert "DO NOTHING" not in ins.upper(), (
        "onc_ctd_profiles is back to DO NOTHING — a cast ONC re-publishes "
        "after delayed-mode QC can never reach the table again"
    )
    assert "DO UPDATE" in ins.upper() and "IS DISTINCT FROM" in ins.upper(), (
        "the upsert must refresh a changed profile and leave an unchanged one "
        "alone, or updated_at stops meaning anything"
    )


def test_the_counter_does_not_report_fetched_casts_as_new_ones():
    body = _sync_onc_ctd_source()
    assert "_log_sync(\"onc-ctd\", inserted, inserted)" not in body, (
        "onc-ctd reports its added count as its total again"
    )
    # The count must come from the RETURNING, not from the fetch loop.
    assert "row[\"was_insert\"]" in body, (
        "nothing reads was_insert, so inserts and updates are indistinguishable"
    )
    assert "fetched += 1" in body and "revised" in body, (
        "fetched / new / revised must stay three different numbers"
    )


def test_no_truncate_of_this_table_makes_the_conflict_clause_load_bearing():
    # If someone ever adds a TRUNCATE onc_ctd_profiles, the DO UPDATE above
    # becomes inert and this suite is guarding a decoration. Redden then.
    src = ONC.read_text(encoding="utf-8")
    truncated = {
        n.strip().rstrip('"').rstrip("'")
        for n in __import__("re").findall(r"TRUNCATE (?:TABLE )?([a-z_]+)", src)
    }
    assert "onc_ctd_profiles" not in truncated, (
        "onc_ctd_profiles is now truncated somewhere in onc.py — re-read "
        "whether the conflict clause still does anything before trusting it"
    )
    assert truncated, "fixture problem: no TRUNCATE found at all, regex is wrong"


@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"),
                    reason="needs a real database — this test executes SQL")
async def test_a_revised_profile_lands_and_an_unchanged_one_does_not():
    import asyncpg
    conn = await asyncpg.connect(os.environ["TEST_DATABASE_URL"])
    try:
        await conn.execute("DROP TABLE IF EXISTS _t_onc_ctd")
        await conn.execute(DDL)
        key = ("BACAX", "23771",
               datetime.datetime(2026, 9, 1, 12, 0, tzinfo=datetime.timezone.utc))

        first = await conn.fetchrow(UPSERT, *key, '{"depth":[1,2],"temperature":[8.0,7.9]}')
        assert first is not None and first["was_insert"] is True

        stamp1 = await conn.fetchval("SELECT updated_at FROM _t_onc_ctd")

        # ONC re-publishes the same cast unchanged — the daily case.
        same = await conn.fetchrow(UPSERT, *key, '{"depth":[1,2],"temperature":[8.0,7.9]}')
        assert same is None, "an unchanged re-fetch must not rewrite the row"
        assert await conn.fetchval("SELECT updated_at FROM _t_onc_ctd") == stamp1

        # ONC re-publishes it with delayed-mode QC applied.
        revised = await conn.fetchrow(UPSERT, *key, '{"depth":[1,2],"temperature":[8.2,7.7]}')
        assert revised is not None, "a revised cast was dropped — the old DO NOTHING is back"
        assert revised["was_insert"] is False, "a revision must not count as an insert"

        got = await conn.fetchval("SELECT profile->'temperature'->>0 FROM _t_onc_ctd")
        assert got == "8.2", f"the revision never reached the table: temperature[0]={got}"
        assert await conn.fetchval("SELECT updated_at FROM _t_onc_ctd") > stamp1

        assert await conn.fetchval("SELECT count(*) FROM _t_onc_ctd") == 1, (
            "the revision must replace the cast, not duplicate it"
        )
    finally:
        await conn.execute("DROP TABLE IF EXISTS _t_onc_ctd")
        await conn.close()
