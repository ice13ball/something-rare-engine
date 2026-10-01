# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""Shared by the pangaea-water DB tests: a rolled-back connection standing in for
db.pool, and the real fixture bytes served in place of PANGAEA."""
import json
import os
import pathlib

import asyncpg
import pytest

import db

needs_db = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")

FIX = pathlib.Path(__file__).parent / "fixtures"
COASTDOM_TSV = (FIX / "coastdom" / "coastdom_slice.tsv").read_bytes()
COASTDOM_JSONLD = (FIX / "coastdom" / "coastdom_meta.jsonld").read_bytes()
PP_TSV = (FIX / "greenland_pp" / "greenland_pp.tsv").read_bytes()
PP_JSONLD = (FIX / "greenland_pp" / "greenland_pp_meta.jsonld").read_bytes()

#: The slice keeps the WHOLE file's Size line (1,286,555). A 12-row excerpt cannot
#: carry that count, so DB tests substitute the slice's own — 207, pinned by
#: test_pangaea_water_parsers.py::test_row_accounting_matches_the_slice — in memory.
COASTDOM_SLICE_POINTS = 207


def coastdom_tsv(points: int = COASTDOM_SLICE_POINTS) -> bytes:
    old = b"Size:\t1286555 data points"
    assert old in COASTDOM_TSV
    return COASTDOM_TSV.replace(old, f"Size:\t{points} data points".encode())


def coastdom_jsonld(date_published: str | None = "2023-12-12",
                    points: int = COASTDOM_SLICE_POINTS) -> bytes:
    d = json.loads(COASTDOM_JSONLD)
    if date_published is None:
        d.pop("datePublished", None)
    else:
        d["datePublished"] = date_published
    d["size"]["value"] = float(points)
    return json.dumps(d).encode()


def pp_jsonld(date_published: str = "2025-04-07") -> bytes:
    d = json.loads(PP_JSONLD)
    d["datePublished"] = date_published
    return json.dumps(d).encode()


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
