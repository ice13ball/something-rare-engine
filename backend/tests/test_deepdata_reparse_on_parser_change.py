# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""A parser that learns something new must reach archives that never moved.

`sync_deepdata_stations` HEAD-probes every archive and skips the ones whose
ETag and content-length are unchanged. That is a correct statement about the
SOURCE and a wrong one about US.

Measured on production 2026-09-18 — three days after the parser learned to
read `extendedmeasurementorfact.txt`:

    140 archives · last_parsed_at = 2026-05-05 for every one
    measurement_count IS NULL for every one

The columns existed, the parser filled them, the sync ran daily and reported
success — and not one row was ever written, because ISA's archives do not
change. A fix that cannot reach the data is not a fix.

⛔ The guard is `parser_version`, compared against `PARSER_VERSION` in the
ingest — not a date. A timestamp says when something was parsed; it cannot say
WHICH parser did it, and that is the only question this decision asks.

Re-parsing the whole corpus costs 11 MB, so there is no economy to defend here.
"""
import os

import asyncpg
import pytest

import db
from domains import biodiversity
from ingestion import deepdata_dwc_ingest as ingest

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)

_SLUG = "test-parser-version-guard"
_ETAG = '"abc123"'
_LEN = 4242


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

    async def fetchval(self, *a, **kw):
        return await self._conn.fetchval(*a, **kw)


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
        await tx.rollback()
        await c.close()


async def _seed(c, parser_version):
    await c.execute(
        "INSERT INTO deepdata_dwc_archives "
        "(slug, etag, content_length, parser_version, last_parsed_at, occurrence_count) "
        "VALUES ($1, $2, $3, $4, '2026-05-05', 10)",
        _SLUG, _ETAG, _LEN, parser_version)


def _stub_network(monkeypatch, parsed: list):
    """No HTTP: the archive is unchanged upstream, which is the whole point."""
    async def list_remote_slugs(client):
        return [_SLUG]

    async def head_probe_all(client, slugs):
        return [{"slug": _SLUG, "etag": _ETAG, "content_length": _LEN,
                 "last_modified": None}]

    async def fetch_archive(client, slug):
        return b"PK\x05\x06" + b"\x00" * 18          # never actually opened

    def parse_archive(slug, zip_bytes):
        parsed.append(slug)
        meta = {
            "slug": slug, "title": "t", "citation": None, "license": None,
            "rights_holder": None, "pub_date": None,
            "occurrence_count": 10, "station_count": 0,
            "measurement_count": 7,
            "measurement_types": ["Relative abundance"],
            "parser_version": ingest.PARSER_VERSION,
        }
        return meta, []

    for name, fn in (("list_remote_slugs", list_remote_slugs),
                     ("head_probe_all", head_probe_all),
                     ("fetch_archive", fetch_archive),
                     ("parse_archive", parse_archive)):
        monkeypatch.setattr(ingest, name, fn)


async def test_an_archive_parsed_by_an_older_parser_is_re_parsed(conn, monkeypatch):
    await _seed(conn, "2026-05-05-base")
    parsed: list[str] = []
    _stub_network(monkeypatch, parsed)

    await biodiversity.sync_deepdata_stations()

    assert parsed == [_SLUG], (
        "the archive was skipped: unchanged upstream, but parsed by a parser "
        "that did not know about the measurement file")
    row = await conn.fetchrow(
        "SELECT parser_version, measurement_count, measurement_types "
        "FROM deepdata_dwc_archives WHERE slug = $1", _SLUG)
    assert row["parser_version"] == ingest.PARSER_VERSION
    assert row["measurement_count"] == 7, (
        "re-parsed but the new column is still empty — the INSERT column list "
        "does not carry it")
    assert row["measurement_types"] == ["Relative abundance"]


async def test_an_archive_parsed_by_the_current_parser_is_left_alone(conn, monkeypatch):
    """⛔ The other half. Without this, "re-parse everything, every run" would
    pass the test above and download the whole corpus daily for nothing."""
    await _seed(conn, ingest.PARSER_VERSION)
    parsed: list[str] = []
    _stub_network(monkeypatch, parsed)

    await biodiversity.sync_deepdata_stations()

    assert parsed == [], (
        "an archive that is unchanged upstream AND current for this parser was "
        "downloaded and parsed again")


async def test_a_row_that_never_recorded_a_parser_is_treated_as_stale(conn, monkeypatch):
    """NULL means "we do not know which parser wrote this" — which is exactly
    the state production was in on 2026-09-18. Unknown is not current."""
    await _seed(conn, None)
    parsed: list[str] = []
    _stub_network(monkeypatch, parsed)

    await biodiversity.sync_deepdata_stations()

    assert parsed == [_SLUG]


def test_the_parser_version_is_written_by_the_parser_itself():
    """⭐ Guard the producer too: the sync can only compare a value the parse
    step actually puts in archive_meta."""
    import inspect

    src = inspect.getsource(ingest.parse_archive)
    assert '"parser_version"' in src, (
        "parse_archive does not stamp parser_version, so every archive would "
        "read as unknown and be re-parsed on every run")


def test_the_column_reaches_the_insert():
    import inspect

    src = inspect.getsource(biodiversity.upsert_dwc_archive_and_stations)
    assert '"parser_version"' in src, (
        "parser_version is parsed and never written — the comparison would "
        "then always see NULL and re-parse the corpus every run")
