# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""A source that never ran has no date — and must not take the sitemap down.

`sync_log` deliberately holds rows for syncs that were RECORDED but did not
run: `last_synced_at IS NULL` alongside a `skipped_reason`. That is the whole
point of `test_sync_log_skipped.py` — "never ran" must be distinguishable from
"ran, found nothing". On 2026-09-15 `sbma-cook-islands` was inserted that way
("no Landfolio candidate base resolved").

Three days later the sitemap read those values back:

    max(sync_map.values())
    TypeError: '>' not supported between instances of 'NoneType' and
               'datetime.datetime'

Measured on production 2026-09-18: `/v1/seo/sitemap/core` → **500**, and with
it `https://something-rare.com/sitemap-core.xml` → 500, ~2,900 URLs
unreachable to a crawler.

⚠️ Note what collided: the honest NULL from one guard became a crash in
another. Neither piece was wrong on its own, so neither test could have caught
it alone — which is why the DB test below seeds the NULL row rather than
mocking it away.

⛔ The row itself is never modified or deleted — it is evidence. The reader
learns to skip NULLs instead.
"""
import ast
import os
import pathlib
from datetime import datetime, timezone

import asyncpg
import pytest

import db
from domains import seo
from domains.seo import SITEMAP_LASTMOD_FALLBACK, sitemap_lastmod

_OLDER = datetime(2026, 8, 18, 5, 47, tzinfo=timezone.utc)
_NEWER = datetime(2026, 9, 17, 13, 26, tzinfo=timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# The helper itself — pure, no database, fails for one reason only.
# ─────────────────────────────────────────────────────────────────────────────

def test_a_null_timestamp_does_not_crash_and_does_not_win():
    got = sitemap_lastmod({"sio-bic": _OLDER, "sbma-cook-islands": None, "argo": _NEWER})
    assert got == "2026-09-17", f"lastmod is {got!r}; the NULL row changed the answer"


def test_the_expression_it_replaces_actually_raised():
    """⛔ The defect, shown rather than asserted about.

    If this ever stops raising, the reason this file exists has changed and
    the guard above is protecting against nothing.
    """
    sync_map = {"sio-bic": _OLDER, "sbma-cook-islands": None}
    with pytest.raises(TypeError, match="NoneType"):
        max(sync_map.values())


def test_all_null_falls_back_rather_than_inventing_a_date():
    assert sitemap_lastmod({"a": None, "b": None}) == SITEMAP_LASTMOD_FALLBACK


def test_an_empty_sync_log_falls_back_too():
    assert sitemap_lastmod({}) == SITEMAP_LASTMOD_FALLBACK


def test_the_newest_timestamp_wins():
    assert sitemap_lastmod({"a": _OLDER, "b": _NEWER}) == "2026-09-17"
    assert sitemap_lastmod({"only": _OLDER}) == "2026-08-18"


def test_the_fallback_is_not_todays_date():
    """A fallback that moves is indistinguishable from a real sync date."""
    assert SITEMAP_LASTMOD_FALLBACK == "2026-04-01"


# ─────────────────────────────────────────────────────────────────────────────
# ⭐ Guard the call sites, not only the helper.
# ─────────────────────────────────────────────────────────────────────────────

def test_no_sitemap_builder_still_maxes_over_sync_values_itself():
    """A fifth `max(sync_map.values())` added later would crash exactly the
    same way. This walks the source instead of trusting memory."""
    src = pathlib.Path(seo.__file__).read_text()
    tree = ast.parse(src)
    offenders = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "max"):
            continue
        for arg in node.args:
            # max(sync_map.values()) / max(anything.values()) inside seo.py
            if (isinstance(arg, ast.Call)
                    and getattr(arg.func, "attr", None) == "values"):
                offenders.append(node.lineno)
    assert offenders == [], (
        f"seo.py lines {offenders} take max() over a dict's values directly. "
        "sync_log holds NULL timestamps for skipped sources — use "
        "sitemap_lastmod().")


def test_both_sitemap_endpoints_use_the_helper():
    src = pathlib.Path(seo.__file__).read_text()
    assert src.count("sitemap_lastmod(sync_map)") >= 4, (
        "a sitemap lastmod stopped going through the helper")


# ─────────────────────────────────────────────────────────────────────────────
# The endpoint, against a real database holding the real shape of row.
# ─────────────────────────────────────────────────────────────────────────────

pytestmark_db = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)


class _Acquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class _PoolFromConn:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _Acquire(self._conn)


@pytest.fixture
async def conn():
    c = await asyncpg.connect(os.environ["TEST_DATABASE_URL"])
    tx = c.transaction()
    await tx.start()
    previous = db.pool
    db.pool = _PoolFromConn(c)
    try:
        yield c
    finally:
        db.pool = previous
        await tx.rollback()      # the seeded rows never survive the test
        await c.close()


async def _seed_skipped_and_real(c):
    # Five layer tables are created by their ingests, not by the schema steps,
    # so a fresh CI database lacks them. `seo_sitemap_core` swallows the
    # resulting error per table (count → 0), but inside our single test
    # transaction the first one ABORTS the transaction and every later
    # statement — including the assertions below — dies with
    # InFailedSQLTransactionError, which would look like the sitemap fix
    # failing. Same approach as test_onc_seo_gate.py: give them a minimal
    # shape. All of it is rolled back.
    for ddl in (
        "CREATE TABLE IF NOT EXISTS seamounts (peak_id INTEGER PRIMARY KEY)",
        "CREATE TABLE IF NOT EXISTS apeis (id INTEGER PRIMARY KEY)",
        "CREATE TABLE IF NOT EXISTS eez (id INTEGER PRIMARY KEY)",
        "CREATE TABLE IF NOT EXISTS noise_risk_cells (id INTEGER PRIMARY KEY)",
        "CREATE TABLE IF NOT EXISTS chess_sites (id INTEGER PRIMARY KEY)",
    ):
        await c.execute(ddl)
    await c.execute(
        "INSERT INTO sync_log (source, last_synced_at, records_added, total_records, "
        "skipped_reason, skipped_at) VALUES ($1, NULL, 0, 0, $2, NOW())",
        "TEST-sbma-shaped", "no Landfolio candidate base resolved")
    await c.execute(
        "INSERT INTO sync_log (source, last_synced_at, records_added, total_records) "
        "VALUES ($1, $2, 1, 1)", "TEST-real-source", _NEWER)


@pytestmark_db
async def test_sitemap_core_survives_a_null_last_synced_at(conn):
    await _seed_skipped_and_real(conn)

    result = await seo.seo_sitemap_core()          # the 500 happened in here

    entries = result["entries"]
    assert entries, "the sitemap came back empty"
    # ⚠️ Expectation read from the table, not hardcoded: other tests in the
    # suite commit their own sync_log rows, so a literal date here passes
    # alone and fails in a full run — measured 2026-09-18. Postgres `max()`
    # ignores NULLs, which is exactly the behaviour the Python side now
    # matches.
    newest = await conn.fetchval("SELECT max(last_synced_at) FROM sync_log")
    homepage = next(e for e in entries if e["loc"] == "https://something-rare.com/")
    assert homepage["lastmod"] == str(newest.date()), (
        f"homepage lastmod is {homepage['lastmod']!r}, table says {newest!r}")
    assert homepage["lastmod"] >= "2026-09-17", (
        "the seeded dated row is not even represented — the fixture is wrong")
    assert all(len(e["lastmod"]) == 10 for e in entries), (
        "an entry carries something that is not a YYYY-MM-DD date")


@pytestmark_db
async def test_sitemap_entries_survives_it_too(conn):
    """The second endpoint reads the same table with the same expression."""
    await _seed_skipped_and_real(conn)

    entries = await seo.seo_sitemap_entries()
    assert entries, "the sitemap-entries endpoint came back empty"


@pytestmark_db
async def test_the_skipped_row_is_left_exactly_as_it_was(conn):
    """⛔ The fix reads around the row; it must never repair the data."""
    await _seed_skipped_and_real(conn)
    await seo.seo_sitemap_core()

    row = await conn.fetchrow(
        "SELECT last_synced_at, skipped_reason FROM sync_log WHERE source = $1",
        "TEST-sbma-shaped")
    assert row["last_synced_at"] is None, "the sitemap wrote a timestamp onto a skipped sync"
    assert row["skipped_reason"] == "no Landfolio candidate base resolved"
