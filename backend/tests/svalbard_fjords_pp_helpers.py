# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""Shared by the svalbard-fjords-pp DB tests: a rolled-back connection standing
in for db.pool, and the real fixture bytes served in place of the source CSV."""
import os
import pathlib

import asyncpg
import pytest

import db

needs_db = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")

FIX = pathlib.Path(__file__).parent / "fixtures" / "svalbard_fjords_pp" / "svalbard_fjords_pp.csv"
CSV = FIX.read_bytes()


def fake_fetch(files: dict[str, bytes]):
    calls: list[str] = []

    async def fetch(url: str, **_kw) -> bytes:
        calls.append(url)
        if url not in files:
            raise AssertionError(f"unexpected fetch of {url}")
        return files[url]

    fetch.calls = calls
    return fetch


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
    """One connection inside one transaction, rolled back at the end — nothing a
    test does is ever committed. Installed as db.pool so production code under
    test uses it."""
    c = await asyncpg.connect(os.environ["TEST_DATABASE_URL"])
    tx = c.transaction()
    await tx.start()
    previous = db.pool
    db.pool = _PoolFromConn(c)
    try:
        yield c
    finally:
        db.pool = previous
        await tx.rollback()
        await c.close()
