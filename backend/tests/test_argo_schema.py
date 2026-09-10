# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Executes `schema.core.ensure_argo_long_form` (and `ensure_core`, for the
legacy `argo_profiles` regression guard) against real PostGIS.

Covers:
  - the three new tables (argo_profile_values, argo_params,
    argo_backfill_state) exist with the documented columns/types
  - the DDL is idempotent — run three times, no error
  - every legacy `argo_profiles` column the ADDITIVE contract promises to
    keep is still there
"""
import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)

# The ADDITIVE contract: these argo_profiles columns must survive untouched.
_LEGACY_ARGO_PROFILES_COLUMNS = {
    "surface_temp_c", "surface_salinity", "deep_temp_c", "deep_salinity",
    "deep_pressure_m", "oxygen_umol_kg", "ph", "max_depth_m",
    "temp_qc", "sal_qc", "oxygen_qc", "ph_qc",
    "woa_surface_temp_c", "woa_surface_sal", "woa_deep_temp_c", "woa_deep_sal",
    "woa_deep_oxygen_umol_kg", "woa_deep_aou", "woa_deep_o2sat",
    "woa_deep_phosphate", "woa_deep_silicate", "woa_deep_nitrate",
    "near_mining", "mining_zone", "mining_dist_km",
}


async def _fetch_columns(conn, table: str) -> dict[str, str]:
    rows = await conn.fetch(
        """SELECT column_name, data_type
           FROM information_schema.columns
           WHERE table_schema = 'public' AND table_name = $1""",
        table,
    )
    return {r["column_name"]: r["data_type"] for r in rows}


@pytest.mark.asyncio
async def test_argo_schema_is_created_idempotently_and_keeps_legacy_columns():
    import asyncpg
    from schema.core import ensure_core, ensure_argo_long_form

    pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    try:
        async with pool.acquire() as conn:
            # Run three times — the idempotency guard.
            for _ in range(3):
                await ensure_core(conn)
                await ensure_argo_long_form(conn)

            # --- legacy argo_profiles columns: the regression guard ---
            argo_cols = await _fetch_columns(conn, "argo_profiles")
            missing = _LEGACY_ARGO_PROFILES_COLUMNS - set(argo_cols)
            assert not missing, f"argo_profiles lost legacy column(s): {missing}"

            # --- argo_profile_values ---
            values_cols = await _fetch_columns(conn, "argo_profile_values")
            assert values_cols["profile_id"] == "text"
            assert values_cols["level"] == "text"
            assert values_cols["param"] == "text"
            assert values_cols["value"] == "double precision"
            assert values_cols["qc"] == "smallint"

            pk = await conn.fetch(
                """SELECT a.attname
                   FROM pg_index i
                   JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                   WHERE i.indrelid = 'argo_profile_values'::regclass AND i.indisprimary
                   ORDER BY array_position(i.indkey, a.attnum)"""
            )
            assert [r["attname"] for r in pk] == ["profile_id", "level", "param"]

            idx = await conn.fetchval(
                """SELECT count(*) FROM pg_indexes
                   WHERE tablename = 'argo_profile_values'
                     AND indexdef ILIKE '%(param)%'"""
            )
            assert idx >= 1, "argo_profile_values is missing its index on (param)"

            # --- argo_params ---
            params_cols = await _fetch_columns(conn, "argo_params")
            assert params_cols["param"] == "text"
            assert params_cols["label"] == "text"
            assert params_cols["unit"] == "text"
            assert params_cols["n_values"] == "integer"

            params_pk = await conn.fetchval(
                """SELECT a.attname
                   FROM pg_index i
                   JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                   WHERE i.indrelid = 'argo_params'::regclass AND i.indisprimary"""
            )
            assert params_pk == "param"

            # --- argo_backfill_state ---
            state_cols = await _fetch_columns(conn, "argo_backfill_state")
            assert state_cols["id"] == "integer"
            assert state_cols["done_through"] == "date"
            assert state_cols["updated_at"] == "timestamp with time zone"

            # id=1 CHECK constraint present
            check_def = await conn.fetchval(
                """SELECT pg_get_constraintdef(oid) FROM pg_constraint
                   WHERE conrelid = 'argo_backfill_state'::regclass AND contype = 'c'"""
            )
            assert check_def is not None and "1" in check_def

            # One-row contract: inserting id=1 twice must upsert, never duplicate.
            await conn.execute(
                """INSERT INTO argo_backfill_state (id, done_through, updated_at)
                   VALUES (1, '2026-01-01', now())
                   ON CONFLICT (id) DO UPDATE SET done_through = EXCLUDED.done_through"""
            )
            await conn.execute(
                """INSERT INTO argo_backfill_state (id, done_through, updated_at)
                   VALUES (1, '2026-02-01', now())
                   ON CONFLICT (id) DO UPDATE SET done_through = EXCLUDED.done_through"""
            )
            n_rows = await conn.fetchval("SELECT count(*) FROM argo_backfill_state")
            assert n_rows == 1
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM argo_backfill_state")
            await conn.execute("DELETE FROM argo_profile_values")
            await conn.execute("DELETE FROM argo_params")
        await pool.close()


@pytest.mark.asyncio
async def test_argo_profiles_records_the_sources_own_revision_stamp():
    """`date_updated_argovis` is how we learn a profile has been corrected.

    Argo publishes real-time data first and a quality-controlled delayed-mode
    version months later, so a profile is not finished when we first see it.
    Measured against the live API 2026-09-10: of 464 profiles dated
    2024-03-01, eighty had been revised in the previous three months.

    ⛔ TIMESTAMPTZ, not TIMESTAMP. ArgoVis sends `...Z`; comparing a naive
    timestamp against an aware one raises TypeError, and that exception is
    NOT caught by the `except httpx.HTTPError` around the fetch — it would
    travel up and take the scheduler with it.

    ⛔ Nullable, with no default. NULL means "we never asked about this row",
    and 388k existing rows will carry it until a cheap metadata pass fills
    them in. A NOT NULL or a DEFAULT would also force a full table rewrite
    under an AccessExclusiveLock, which migrate.py's lock timeout would not
    survive.
    """
    import asyncpg
    from schema.core import ensure_core

    pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    try:
        async with pool.acquire() as conn:
            await ensure_core(conn)
            row = await conn.fetchrow(
                """SELECT data_type, is_nullable, column_default
                     FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'argo_profiles'
                      AND column_name = 'date_updated_argovis'"""
            )
            assert row is not None, (
                "argo_profiles has no date_updated_argovis — without it every "
                "correction ArgoVis publishes is invisible to us"
            )
            assert row["data_type"] == "timestamp with time zone", (
                f"date_updated_argovis is {row['data_type']}; a naive timestamp "
                "cannot be compared with ArgoVis's UTC stamps without raising"
            )
            assert row["is_nullable"] == "YES"
            assert row["column_default"] is None, (
                "a default would make NULL unreachable, and NULL is how we say "
                "'we have never asked about this row'"
            )
    finally:
        await pool.close()
