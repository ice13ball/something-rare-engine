# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""Shared by the SOCAT points DB tests (plankton_helpers.py pattern): a rolled-back connection standing in
for db.pool, a tiny zip built from the real fixture, `load_excerpt`, and `api_get` as the HTTP client.
There are no `db` / `client` fixtures in conftest: import them from here."""
import pathlib
import zipfile

import pytest

from plankton_helpers import api_get, conn, needs_db  # noqa: F401  (re-exported for Tasks 5-6)

FIX = pathlib.Path(__file__).parent / "fixtures" / "socat_points"
MAIN = FIX / "SOCATv2026_excerpt.tsv"
FLAGE = FIX / "SOCATv2026_FlagE_excerpt.tsv"
MEMBER = "SOCATv2026.tsv"

TABLES = ("socat_segments", "socat_lod", "socat_cruises")


def excerpt_rows(path=MAIN) -> list[str]:
    """Data lines of the fixture (32 fields = 31 tabs), straight from the file."""
    with path.open(encoding="utf-8", newline="") as fh:
        return [ln for ln in fh if ln.count("\t") == 31 and not ln.startswith("Expocode\t")]


def excerpt_zip(tmp_path, src=MAIN, name="socat.zip") -> pathlib.Path:
    """The fixture file as the NCEI zip would hold it: one member SOCATv2026.tsv, real bytes."""
    dest = pathlib.Path(tmp_path) / name
    if dest.exists():                    # the same bytes (same sha256) for a second run in one test
        return dest
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(src, MEMBER)
    return dest


async def fresh_socat(conn):
    """Drop every SOCAT table (live, staging, source) and recreate the live set empty."""
    from schema.socat_points import ensure_socat_points
    for t in (*(f"{t}_new" for t in TABLES), *TABLES, "socat_points_source"):
        await conn.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    await conn.execute("""CREATE TABLE IF NOT EXISTS sync_log (source text PRIMARY KEY,
        last_synced_at timestamptz, records_added integer, total_records integer,
        skipped_reason text, skipped_at timestamptz)""")
    await conn.execute("DELETE FROM sync_log WHERE source = 'socat-points'")
    await ensure_socat_points(conn)


@pytest.fixture
async def db(conn):
    """The rolled-back connection with an empty SOCAT table set (db.pool points at it)."""
    await fresh_socat(conn)
    return conn


async def load_excerpt(tmp_path, src=MAIN, **kw) -> dict:
    """Run the real loader on the fixture zipped in tmp_path (db.pool must point at the test connection)."""
    from ingestion import socat_points as sp
    return await sp.sync_socat_points(zip_path=excerpt_zip(tmp_path, src), **kw)
