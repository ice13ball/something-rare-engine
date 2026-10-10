# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""Shared by the WOD casts DB tests (socat_helpers.py pattern): a rolled-back connection standing in for db.pool,
the real cut files registered in `wod_files`, and `api_get` as the HTTP client. There are no `db` / `client`
fixtures in conftest: import them from here."""
import json
import pathlib
import shutil

import pytest

from plankton_helpers import api_get, conn, needs_db  # noqa: F401  (re-exported)

FIX = pathlib.Path(__file__).parent / "fixtures" / "wod_casts"
EXPECTED = json.loads((FIX / "expected.json").read_text())["files"]
# source file name (what the NCEI URL ends with) -> cut file
CUT_OF = {v["source_file"]: k for k, v in EXPECTED.items()}

TABLES = ("wod_casts_stage", "wod_points_stage", "wod_cells_new", "wod_cells", "wod_cast_points", "wod_casts",
          "wod_files", "wod_casts_source")


async def fresh_wod(conn):
    """Drop every WOD table (live, staging, `_new`, files, source) and recreate the live set empty."""
    from schema.wod_casts import ensure_wod_casts
    for t in TABLES:
        await conn.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    await conn.execute("""CREATE TABLE IF NOT EXISTS sync_log (source text PRIMARY KEY,
        last_synced_at timestamptz, records_added integer, total_records integer,
        skipped_reason text, skipped_at timestamptz)""")
    await conn.execute("DELETE FROM sync_log WHERE source = 'wod-casts'")
    await ensure_wod_casts(conn)


@pytest.fixture
async def db(conn):
    """The rolled-back connection with an empty WOD table set (db.pool points at it)."""
    await fresh_wod(conn)
    return conn


def fixture_fetch(name_map=None):
    """A `fetch(url, dest)` that copies the cut file standing in for the file the URL names."""
    mapping = name_map or CUT_OF

    def fetch(url, dest):
        shutil.copyfile(FIX / mapping[url.rsplit("/", 1)[-1]], dest)
    return fetch


def base_url() -> str:
    from ingestion import wod_casts_rules as R
    return R.BASE_URL.rstrip("/")


async def register(conn, source_name: str, *, url: str | None = None) -> int:
    """Register one cut file as `pending`, content_length = its size, as discovery would have."""
    _, inst, year = source_name[:-3].split("_")
    url = url or f"{base_url()}/{year}/{source_name}"
    size = (FIX / CUT_OF[source_name]).stat().st_size
    return await conn.fetchval(
        "INSERT INTO wod_files (url, instrument, year, content_length, last_modified, seen_at, status) "
        "VALUES ($1, $2, $3, $4, 'Wed, 01 Jan 2025 00:00:00 GMT', now(), 'pending') RETURNING file_id",
        url, inst, int(year), size)


async def load_fixtures(conn, tmp_path, names=None, **kw) -> dict:
    """Register the cut files (all five by default) as pending and run the real loader on them."""
    for n in (names or sorted(CUT_OF)):
        await register(conn, n)
    return await run_loader(tmp_path, **kw)


async def run_loader(tmp_path, **kw) -> dict:
    from ingestion import wod_casts as wc
    dl = pathlib.Path(tmp_path) / "download"
    dl.mkdir(exist_ok=True)
    return await wc.sync_wod_casts(fetch=kw.pop("fetch", fixture_fetch()), scratch=dl, **kw)
