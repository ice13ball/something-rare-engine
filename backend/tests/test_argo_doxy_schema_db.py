# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
from datetime import datetime, timezone

from ingestion import argo_doxy_rules as r
from plankton_helpers import conn, needs_db  # noqa: F401
from schema.argo_doxy import UPSERT_SQL, ensure_argo_doxy


def _row(**kw):
    base = dict(profile_key="aoml_1900722_001", argo_profile_id="1900722_001", dac="aoml", platform_number="1900722",
                cycle_number=1, direction="A", gdac_file="aoml/1900722/profiles/SD1900722_001.nc",
                gdac_date_update=datetime(2022, 6, 28, tzinfo=timezone.utc),
                profile_time=datetime(2006, 10, 22, 2, 16, tzinfo=timezone.utc), juld_qc=1, year=2006,
                lat=-40.3, lon=73.4, position_qc=1, doxy_mode="D", pres_source="adjusted",
                n_levels_source=2, n_good=2, n_levels=2, pres_dbar=[6.0, 500.0], depth_m=[5.9, 495.8],
                doxy_adj=[259.6, 200.0], doxy_adj_qc=[1, 1], doxy_raw=[230.9, 180.0], doxy_raw_qc=[3, 3],
                at_depth=[259.6, None, None, None, 200.0, None, None, None],
                at_depth_m=[5.9, None, None, None, 495.8, None, None, None], drawable=True)
    base.update(kw)
    return tuple(base[c] for c in r.PROFILE_COLUMNS)


@needs_db
async def test_ensure_is_idempotent_and_adds_no_index_twice(conn):
    await conn.execute("DROP TABLE IF EXISTS argo_doxy_profiles, argo_doxy_empty, argo_doxy_source CASCADE")
    await ensure_argo_doxy(conn)
    n1 = await conn.fetchval("SELECT count(*) FROM pg_indexes WHERE tablename = 'argo_doxy_profiles'")
    await ensure_argo_doxy(conn)
    assert await conn.fetchval("SELECT count(*) FROM pg_indexes WHERE tablename = 'argo_doxy_profiles'") == n1
    assert await conn.fetchval("SELECT count(*) FROM argo_doxy_source") == 1
    n2 = await conn.fetchval("SELECT count(*) FROM pg_indexes WHERE tablename = 'argo_doxy_empty'")
    await ensure_argo_doxy(conn)
    assert await conn.fetchval("SELECT count(*) FROM pg_indexes WHERE tablename = 'argo_doxy_empty'") == n2 == 1


@needs_db
async def test_upsert_writes_and_updates_one_row_per_key(conn):
    await ensure_argo_doxy(conn)
    await conn.execute("DELETE FROM argo_doxy_profiles")
    await conn.execute(UPSERT_SQL, *_row())
    await conn.execute(UPSERT_SQL, *_row(gdac_file="aoml/1900722/profiles/SR1900722_001.nc", doxy_mode="R",
                                         drawable=False))
    rows = await conn.fetch("SELECT doxy_mode, drawable FROM argo_doxy_profiles")
    assert [(x["doxy_mode"], x["drawable"]) for x in rows] == [("R", False)]


@needs_db
async def test_constraints_reject_a_malformed_key_and_a_wrong_pick_length(conn):
    import asyncpg
    import pytest
    await ensure_argo_doxy(conn)
    for bad in (_row(profile_key="1900722_001"), _row(at_depth=[1.0, 2.0])):
        sp = conn.transaction()
        await sp.start()
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(UPSERT_SQL, *bad)
        await sp.rollback()


@needs_db
async def test_argo_profiles_columns_are_untouched_by_the_extension(conn):
    """Failure mode: the existing Argo layer broken by the storage extension. argo_profiles is created by
    schema.core.ensure_core, argo_profile_values / argo_skipped_profiles by schema.core.ensure_argo_long_form."""
    from schema.core import ensure_argo_long_form, ensure_core
    await ensure_core(conn)
    await ensure_argo_long_form(conn)
    q = ("SELECT table_name, column_name, data_type FROM information_schema.columns WHERE table_name = ANY($1) "
         "ORDER BY table_name, ordinal_position")
    tables = ["argo_profiles", "argo_profile_values", "argo_skipped_profiles"]
    before = [tuple(x) for x in await conn.fetch(q, tables)]
    await conn.execute("DROP TABLE IF EXISTS argo_doxy_profiles, argo_doxy_empty, argo_doxy_source CASCADE")
    await ensure_argo_doxy(conn)
    assert [tuple(x) for x in await conn.fetch(q, tables)] == before and before
    # no FK: the existing tests' _clean_argo_tables deletes argo_profiles rows, and not every DOXY profile has one
    assert await conn.fetchval("SELECT count(*) FROM information_schema.table_constraints "
                               "WHERE table_name = 'argo_doxy_profiles' AND constraint_type = 'FOREIGN KEY'") == 0
