# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""DDL surface net for `schema.ensure_schema()`.

`ensure_schema` emits 200+ DDL statements in a **load-bearing order** — an index or
an ALTER that runs before its CREATE TABLE fails at boot. Nothing tested it. This
records every statement, in order, against a fake connection and snapshots the lot,
so a split of `schema.py` into per-domain modules is correct exactly when the
snapshot does not move.

Statements are whitespace-normalised, so re-indenting code as it moves between
files is invisible here — but dropping, reordering or editing a statement is not.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

SNAPSHOT = Path(__file__).parent / "__snapshots__" / "ensure_schema_ddl.txt"


class RecordingConn:
    """Stands in for an asyncpg connection, keeping the SQL instead of running it."""

    def __init__(self, sink: list[str]) -> None:
        self._sink = sink

    async def execute(self, sql: str, *args) -> str:
        self._sink.append(sql)
        return "OK"

    async def executemany(self, sql: str, args) -> None:
        # The argument rows are seed data, not schema — only the statement is surface.
        self._sink.append(sql)

    async def fetchval(self, sql: str, *args):
        # `domains.blog.seed_blog_if_empty` counts rows before seeding. 0 = "empty",
        # which is the branch that emits DDL-adjacent SQL, so it is the one to record.
        return 0

    async def fetch(self, sql: str, *args) -> list:
        return []

    async def fetchrow(self, sql: str, *args):
        return None


class _Acquire:
    def __init__(self, conn: RecordingConn) -> None:
        self._conn = conn

    async def __aenter__(self) -> RecordingConn:
        return self._conn

    async def __aexit__(self, *exc) -> bool:
        return False


class RecordingPool:
    def __init__(self, sink: list[str]) -> None:
        self._conn = RecordingConn(sink)

    def acquire(self) -> _Acquire:
        return _Acquire(self._conn)


def _normalise(raw: str) -> list[str]:
    """One statement per entry, whitespace collapsed, comments stripped."""
    without_comments = re.sub(r"--[^\n]*", " ", raw)
    out = []
    for stmt in without_comments.split(";"):
        collapsed = " ".join(stmt.split())
        if collapsed:
            out.append(collapsed)
    return out


async def _record() -> list[str]:
    import db
    import schema

    sink: list[str] = []
    original = db.pool
    db.pool = RecordingPool(sink)          # type: ignore[assignment]
    try:
        await schema.ensure_schema()
    finally:
        db.pool = original

    statements: list[str] = []
    for raw in sink:
        statements.extend(_normalise(raw))
    return statements


@pytest.mark.asyncio
async def test_ddl_surface_matches_snapshot():
    statements = await _record()
    assert statements, "ensure_schema emitted nothing — the fake pool was not used"

    current = "\n".join(statements) + "\n"
    if not SNAPSHOT.exists():
        SNAPSHOT.write_text(current, encoding="utf-8")
        pytest.fail(
            f"snapshot did not exist and was written to {SNAPSHOT}. "
            "Inspect it, then re-run — a snapshot must be reviewed before it is trusted."
        )

    expected = SNAPSHOT.read_text(encoding="utf-8").splitlines()
    if statements != expected:
        # Report the first divergence rather than dumping 200 lines.
        for i, (got, want) in enumerate(zip(statements, expected)):
            if got != want:
                raise AssertionError(
                    f"DDL statement #{i} changed.\n  expected: {want[:200]}\n  got:      {got[:200]}"
                )
        raise AssertionError(
            f"DDL statement count changed: {len(expected)} -> {len(statements)}"
        )


@pytest.mark.asyncio
async def test_every_index_and_alter_follows_its_create_table():
    """The property the ordering actually protects, asserted directly."""
    statements = await _record()
    created: set[str] = set()
    for stmt in statements:
        upper = stmt.upper()
        if upper.startswith("CREATE TABLE"):
            m = re.search(r"CREATE TABLE (?:IF NOT EXISTS )?([\w.]+)", stmt, re.I)
            if m:
                created.add(m.group(1).lower())
        elif upper.startswith("ALTER TABLE"):
            m = re.search(r"ALTER TABLE (?:IF EXISTS )?([\w.]+)", stmt, re.I)
            if m and m.group(1).lower() not in created:
                pytest.fail(f"ALTER before CREATE for table {m.group(1)}: {stmt[:160]}")
        elif "CREATE INDEX" in upper or "CREATE UNIQUE INDEX" in upper:
            m = re.search(r"\bON ([\w.]+)", stmt, re.I)
            if m and m.group(1).lower() not in created:
                pytest.fail(f"INDEX before CREATE for table {m.group(1)}: {stmt[:160]}")
