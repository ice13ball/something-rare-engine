# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Regression guard for the claim_species_cache rebuild.

The dangerous property is invisible to a live smoke test that only checks the
final row count: the failure is a *window* mid-rebuild, not a wrong end state.
Since the 2026-07-26 switch to reading species counts from this cache instead of
a live spatial join, the public SEO pages read this table directly, so the rebuild MUST
run inside a single transaction and MUST NOT use autocommitting TRUNCATE — else
crawlers see "0 species" for the whole ~10-min rebuild. This test pins that
structure with a fake asyncpg connection that records the call sequence.
"""
from __future__ import annotations

import asyncio

import db
from backend.services import species_cache


class _FakeTxn:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        self.conn.calls.append("BEGIN")
        return self

    async def __aexit__(self, *exc):
        self.conn.calls.append("COMMIT" if exc[0] is None else "ROLLBACK")
        return False


class _FakeConn:
    def __init__(self):
        self.calls: list[str] = []

    def transaction(self):
        return _FakeTxn(self)

    async def execute(self, sql, *args):
        self.calls.append(" ".join(sql.split())[:40])

    async def fetchval(self, sql, *args):
        self.calls.append("COUNT")
        return 123


class _FakePoolCtx:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        return False


class _FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _FakePoolCtx(self.conn)


def _run_refresh(monkeypatch) -> _FakeConn:
    conn = _FakeConn()
    monkeypatch.setattr(db, "pool", _FakePool(conn))
    n = asyncio.run(species_cache.refresh_species_cache())
    assert n == 123
    return conn


def test_rebuild_runs_inside_a_transaction(monkeypatch):
    conn = _run_refresh(monkeypatch)
    assert "BEGIN" in conn.calls and "COMMIT" in conn.calls, conn.calls
    # Every write must happen between BEGIN and COMMIT — no autocommit window.
    begin, commit = conn.calls.index("BEGIN"), conn.calls.index("COMMIT")
    writes = [i for i, c in enumerate(conn.calls)
              if c.startswith(("DELETE", "INSERT"))]
    assert writes, conn.calls
    assert all(begin < i < commit for i in writes), conn.calls


def test_rebuild_uses_delete_not_autocommitting_truncate(monkeypatch):
    """TRUNCATE takes ACCESS EXCLUSIVE (blocks readers for the whole rebuild) and,
    pre-fix, autocommitted (empty-table window). DELETE + MVCC does neither."""
    conn = _run_refresh(monkeypatch)
    assert any(c.startswith("DELETE FROM claim_species_cache") for c in conn.calls), conn.calls
    assert not any("TRUNCATE" in c for c in conn.calls), conn.calls


def test_rebuild_inserts_after_it_clears(monkeypatch):
    conn = _run_refresh(monkeypatch)
    delete_at = next(i for i, c in enumerate(conn.calls) if c.startswith("DELETE"))
    insert_at = next(i for i, c in enumerate(conn.calls) if c.startswith("INSERT"))
    assert delete_at < insert_at, conn.calls
