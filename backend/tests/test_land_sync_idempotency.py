# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""A sync that can re-run must not double its table, and must not lose it.

`_sync_wdpa` loads through `ogr2ogr -append`. Its `if count > 0: return` guard
was never a freshness policy — it was the only thing standing between us and a
duplicated table. `kbas` is the one land source whose cadence lets it re-run, so
it is the one that must be safe first.
"""
import pytest

from domains.land import extractive


class _FakeConn:
    def __init__(self, staging_rows: int):
        self.executed: list[str] = []
        self._staging_rows = staging_rows

    async def execute(self, sql, *args):
        self.executed.append(sql)
        return "DELETE 0"

    async def fetchval(self, sql, *args):
        self.executed.append(sql)
        return self._staging_rows

    def transaction(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@pytest.mark.asyncio
async def test_replace_deletes_before_inserting_so_a_rerun_does_not_double():
    conn = _FakeConn(staging_rows=42)
    n = await extractive._replace_table_atomically(conn, "kbas", "kbas_staging")
    assert n == 42
    order = [s.strip().split()[0].upper() for s in conn.executed if s.strip()]
    assert "DELETE" in order
    assert order.index("DELETE") < order.index("INSERT")


@pytest.mark.asyncio
async def test_empty_staging_raises_and_never_deletes():
    """An empty upstream release must not become data loss here."""
    conn = _FakeConn(staging_rows=0)
    with pytest.raises(RuntimeError, match="0 rows"):
        await extractive._replace_table_atomically(conn, "kbas", "kbas_staging")
    assert not [s for s in conn.executed if s.strip().upper().startswith("DELETE")]


@pytest.mark.asyncio
async def test_truncated_staging_raises_and_never_deletes():
    """A partial download must not replace a complete table with a fragment.

    `_sync_kbas` pages through an ArcGIS feature server and `break`s out of the
    loop on an empty page or an ogr2ogr failure. Both leave staging holding SOME
    rows. The zero-check passes them, so a network hiccup on page 3 of 10 would
    delete 4,000 live rows and install 400 — while the docstring claimed to
    protect against exactly this. `expected` is the server's own count for this
    run, so a short load is a failed download, not a smaller release.
    """
    conn = _FakeConn(staging_rows=400)
    with pytest.raises(RuntimeError, match="short"):
        await extractive._replace_table_atomically(
            conn, "key_biodiversity_areas", "kba_staging", expected=4000)
    assert not [s for s in conn.executed if s.strip().upper().startswith("DELETE")]


@pytest.mark.asyncio
async def test_a_complete_load_still_swaps():
    """The guard must not reject a good run — 4000 of 4000 proceeds."""
    conn = _FakeConn(staging_rows=4000)
    n = await extractive._replace_table_atomically(
        conn, "key_biodiversity_areas", "kba_staging", expected=4000)
    assert n == 4000
    assert [s for s in conn.executed if s.strip().upper().startswith("DELETE")]


# ── the guard's reference must not come only from the degraded server ────────

class _FakeConnWithLive(_FakeConn):
    """Answers `count(*)` per table, so staging and live can differ."""

    def __init__(self, staging_rows: int, live_rows: int, live_table: str):
        super().__init__(staging_rows)
        self._live_rows = live_rows
        self._live_table = live_table

    async def fetchval(self, sql, *args):
        self.executed.append(sql)
        if self._live_table in sql and "staging" not in sql:
            return self._live_rows
        return self._staging_rows


@pytest.mark.asyncio
async def test_a_degraded_count_endpoint_cannot_shrink_a_full_table():
    """`expected` comes from the SAME server that serves the pages.

    NCEI-style intermittent degradation hits both: `returnCountOnly` answers 500
    instead of 16,800, the paging loop faithfully fetches those 500, and 500 of
    500 sails through a guard that only ever compares the server against itself.
    16,800 live rows are then deleted and replaced with 500 — a 97% data loss
    that every check reports as a successful sync.

    The live table is the one reference the upstream cannot degrade.
    """
    conn = _FakeConnWithLive(staging_rows=500, live_rows=16_800,
                             live_table="key_biodiversity_areas")
    with pytest.raises(RuntimeError, match="short"):
        await extractive._replace_table_atomically(
            conn, "key_biodiversity_areas", "key_biodiversity_areas_staging",
            expected=500)
    assert not [s for s in conn.executed if s.strip().upper().startswith("DELETE")]


@pytest.mark.asyncio
async def test_expected_zero_is_refused_rather_than_silently_disabling_the_guard():
    """`if expected and ...` turned an upstream answering 0 into NO guard at all.

    A count endpoint that returns 0 is the loudest possible signal that the
    upstream is broken. Falsiness made it the quietest: the guard switched off
    and any non-empty staging table was promoted.
    """
    conn = _FakeConnWithLive(staging_rows=3, live_rows=16_800,
                             live_table="key_biodiversity_areas")
    with pytest.raises(RuntimeError, match="0 expected|reported 0"):
        await extractive._replace_table_atomically(
            conn, "key_biodiversity_areas", "key_biodiversity_areas_staging",
            expected=0)
    assert not [s for s in conn.executed if s.strip().upper().startswith("DELETE")]


@pytest.mark.asyncio
async def test_the_first_ever_load_is_not_blocked_by_an_empty_live_table():
    """The live floor must not make a fresh database unsyncable."""
    conn = _FakeConnWithLive(staging_rows=4000, live_rows=0,
                             live_table="key_biodiversity_areas")
    n = await extractive._replace_table_atomically(
        conn, "key_biodiversity_areas", "key_biodiversity_areas_staging",
        expected=4000)
    assert n == 4000


@pytest.mark.asyncio
async def test_a_genuine_upstream_growth_still_swaps():
    """A larger release is not a failure — only a SHORT load is."""
    conn = _FakeConnWithLive(staging_rows=18_000, live_rows=16_800,
                             live_table="key_biodiversity_areas")
    n = await extractive._replace_table_atomically(
        conn, "key_biodiversity_areas", "key_biodiversity_areas_staging",
        expected=18_000)
    assert n == 18_000


# ── a failed swap must still clean up and still be recorded ──────────────────

class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return self

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


@pytest.mark.asyncio
async def test_a_failed_swap_still_drops_the_staging_table(monkeypatch):
    """The DROP sat AFTER the transaction, so a raise skipped it.

    A leaked `key_biodiversity_areas_staging` is a full copy of a 16,800-row
    polygon table sitting on the VPS until the next run happens to drop it —
    and a run that keeps failing keeps one there permanently.
    """
    import db

    conn = _FakeConnWithLive(staging_rows=500, live_rows=16_800,
                             live_table="key_biodiversity_areas")
    monkeypatch.setattr(db, "pool", _FakePool(conn))
    logged: list[tuple] = []
    monkeypatch.setattr(extractive, "_log_land_sync_failure",
                        lambda *a: _record(logged, a))

    with pytest.raises(RuntimeError):
        await extractive._promote_staging(
            "kbas", "key_biodiversity_areas",
            "key_biodiversity_areas_staging", expected=500)

    drops = [s for s in conn.executed if "DROP TABLE" in s.upper()]
    assert drops, "staging table leaked after a failed swap"


async def _record(sink, args):
    sink.append(args)


@pytest.mark.asyncio
async def test_a_failed_swap_is_written_to_the_sync_log(monkeypatch):
    """Otherwise the monitor cannot tell "tried and failed" from "never ran".

    ⛔ And it must NOT advance last_synced_at: a failure that marks the source
    fresh is worse than no row at all — the staleness monitor would go quiet on
    exactly the source that needs attention.
    """
    import db

    conn = _FakeConnWithLive(staging_rows=500, live_rows=16_800,
                             live_table="key_biodiversity_areas")
    monkeypatch.setattr(db, "pool", _FakePool(conn))
    logged: list[tuple] = []
    monkeypatch.setattr(extractive, "_log_land_sync_failure",
                        lambda *a: _record(logged, a))

    with pytest.raises(RuntimeError):
        await extractive._promote_staging(
            "kbas", "key_biodiversity_areas",
            "key_biodiversity_areas_staging", expected=500)

    assert logged, "a failed swap wrote nothing to the sync log"
    assert logged[0][0] == "kbas"


def test_the_failure_log_never_advances_freshness():
    import inspect

    from domains.land import common

    src = inspect.getsource(common._log_land_sync_failure)
    assert "last_synced_at = NOW()" not in src, (
        "a failed sync must not mark the source fresh"
    )


@pytest.mark.asyncio
async def test_a_successful_swap_drops_staging_and_returns_the_count(monkeypatch):
    import db

    conn = _FakeConnWithLive(staging_rows=17_000, live_rows=16_800,
                             live_table="key_biodiversity_areas")
    monkeypatch.setattr(db, "pool", _FakePool(conn))
    n = await extractive._promote_staging(
        "kbas", "key_biodiversity_areas",
        "key_biodiversity_areas_staging", expected=17_000)
    assert n == 17_000
    assert [s for s in conn.executed if "DROP TABLE" in s.upper()]
