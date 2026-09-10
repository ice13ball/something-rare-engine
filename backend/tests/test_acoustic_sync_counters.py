# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""`records_added` must mean rows added, not rows touched.

Measured on production 2026-09-10, before this was fixed:

    sync_log: acoustic-stations  records_added=5738  total_records=5738
    table:    acoustic_stations                              641 rows

Nine times the table, reported as new arrivals, every run — because
`total_inserted += len(rows)` sat after an `ON CONFLICT ... DO UPDATE`. The
same shape had already been found on ISA contracts two days earlier
(records_added=1817 into a 1318-row table), where the tell was the string
literal `"INSERT 0 1"`. Here there is no literal to grep for: `executemany`
returns nothing at all, so the count was simply invented from the input list.

⛔ The helper is tested AND every call site is checked. Testing only the helper
is how four green MOSAIC tests survived `sync_mosaic` being reverted to a bare
`client.get`, and how the offshore retry landed on 4 of 7 call sites.
"""
import ast
import os
import pathlib

import pytest

ACOUSTIC = pathlib.Path(__file__).resolve().parents[1] / "domains" / "acoustic.py"
_TREE    = ast.parse(ACOUSTIC.read_text(encoding="utf-8"))

#: The one call that may pass the same expression twice, and why.
#: noise_risk_compute.py TRUNCATEs noise_risk_grid and rebuilds it, so on that
#: table every row present really was added by the run that just finished.
_HONEST_SAME_VALUE = {"noise_risk"}


def _log_sync_calls():
    for node in ast.walk(_TREE):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_log_sync"
                and len(node.args) == 3
                and isinstance(node.args[0], ast.Constant)):
            yield node.args[0].value, node


def test_the_fixture_finds_the_call_sites_at_all():
    calls = list(_log_sync_calls())
    assert len(calls) >= 4, (
        f"fixture problem: only {len(calls)} _log_sync call(s) parsed out of "
        "acoustic.py, so the assertions below compare almost nothing"
    )


def test_no_sync_reports_the_same_number_as_added_and_as_total():
    offenders = []
    for source, node in _log_sync_calls():
        if source in _HONEST_SAME_VALUE:
            continue
        added, total = ast.dump(node.args[1]), ast.dump(node.args[2])
        if added == total:
            offenders.append((source, ast.unparse(node.args[1]), node.lineno))
    assert not offenders, (
        "these syncs report the row count twice, so `records_added` is really "
        f"`rows touched` and the monitor cannot see a stalled source: {offenders}"
    )


def test_every_conflicting_upsert_in_this_file_counts_through_the_helper():
    # A bare `conn.executemany` whose SQL says DO UPDATE cannot know how many
    # rows it inserted. Adding one back is exactly how this bug returns.
    src = ACOUSTIC.read_text(encoding="utf-8")
    bare = []
    for node in ast.walk(_TREE):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "executemany"):
            continue
        sql = next((a.value for a in node.args
                    if isinstance(a, ast.Constant) and isinstance(a.value, str)), "")
        if "DO UPDATE" in sql.upper():
            bare.append(node.lineno)
    assert not bare, (
        "conn.executemany with an ON CONFLICT DO UPDATE, outside "
        f"_upsert_and_count, at line(s) {bare} — its insert count is unknowable"
    )
    assert "_upsert_and_count" in src, (
        "fixture problem: the helper this test protects is gone from the file"
    )


@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"),
                    reason="needs a real database — this test executes SQL")
async def test_the_helper_counts_inserts_and_not_updates():
    import asyncpg
    conn = await asyncpg.connect(os.environ["TEST_DATABASE_URL"])
    try:
        await conn.execute("DROP TABLE IF EXISTS _t_counted")
        await conn.execute("CREATE TABLE _t_counted (k text PRIMARY KEY, v text)")
        sql = ("INSERT INTO _t_counted (k, v) VALUES ($1, $2) "
               "ON CONFLICT (k) DO UPDATE SET v = EXCLUDED.v")

        import sys
        sys.path.insert(0, str(ACOUSTIC.parents[1]))
        from domains.acoustic import _upsert_and_count

        first = await _upsert_and_count(conn, "_t_counted", sql,
                                        [("a", "1"), ("b", "1"), ("c", "1")])
        assert first == 3, f"three new keys should report 3, reported {first}"

        # Same three keys with new values, plus two genuinely new ones.
        again = await _upsert_and_count(conn, "_t_counted", sql,
                                        [("a", "2"), ("b", "2"), ("c", "2"),
                                         ("d", "1"), ("e", "1")])
        assert again == 2, (
            f"three updates and two inserts should report 2, reported {again} — "
            "updates are being counted as additions again"
        )

        # And a run that changes nothing must report nothing, or the monitor
        # can never tell a healthy sync from one whose source went quiet.
        idle = await _upsert_and_count(conn, "_t_counted", sql,
                                       [("a", "3"), ("b", "3")])
        assert idle == 0, f"an all-update run should report 0, reported {idle}"
    finally:
        await conn.execute("DROP TABLE IF EXISTS _t_counted")
        await conn.close()
