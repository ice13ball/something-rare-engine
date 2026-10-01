# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""The sync: JSON-LD first, TSV only on change, a new version beside the old one,
and an aborted download that leaves every stored row exactly as it was."""
import datetime

import asyncpg
import pytest

from domains import pangaea_water as pw
from ingestion import coastdom, greenland_pp
from ingestion.pangaea_tsv import PangaeaFormatError
from pangaea_water_helpers import (  # noqa: F401  (conn is a fixture)
    PP_TSV, coastdom_jsonld, coastdom_tsv, conn, fake_fetch, needs_db, pp_jsonld,
)

pytestmark = needs_db


def _files(tsv=None, ld=None):
    return {
        coastdom.TEXTFILE_URL: coastdom_tsv() if tsv is None else tsv,
        coastdom.JSONLD_URL: coastdom_jsonld() if ld is None else ld,
        greenland_pp.TEXTFILE_URL: PP_TSV,
        greenland_pp.JSONLD_URL: pp_jsonld(),
    }


async def _versions(conn, layer="coastdom"):
    return await conn.fetch(
        "SELECT * FROM pangaea_dataset_version WHERE layer_id = $1 ORDER BY version_id", layer)


async def _first_sync(conn, monkeypatch):
    monkeypatch.setattr(pw, "_fetch_bytes", fake_fetch(_files()))
    assert await pw.sync_coastdom() == 12


async def test_first_sync_stores_every_row_and_one_current_version(conn, monkeypatch):
    await _first_sync(conn, monkeypatch)
    [v] = await _versions(conn)
    assert v["is_current"]
    assert (v["rows_in_source"], v["rows_unmappable"], v["data_points"]) == (12, 2, 207)
    assert v["date_published"] == datetime.date(2023, 12, 12)
    assert v["doi"] == "10.1594/PANGAEA.964012"
    assert v["citation"].endswith("[dataset]. PANGAEA, https://doi.org/10.1594/PANGAEA.964012")
    assert v["related_citation"].endswith("https://doi.org/10.5194/essd-16-1107-2024")
    assert v["license"] == "https://creativecommons.org/licenses/by/4.0/"
    assert tuple(v["header"]) == coastdom.EXPECTED_HEADER
    assert await conn.fetchval("SELECT count(*) FROM coastdom_samples") == 12
    log = await conn.fetchrow("SELECT total_records, skipped_reason FROM sync_log WHERE source = 'coastdom'")
    assert log["total_records"] == 12 and log["skipped_reason"] is None


async def test_unmappable_rows_pi_email_and_raw_are_stored(conn, monkeypatch):
    await _first_sync(conn, monkeypatch)
    assert await conn.fetchval("SELECT count(*) FROM coastdom_samples WHERE geom IS NULL") == 2
    assert await conn.fetchval("SELECT pi_email FROM coastdom_samples WHERE row_no = 1") == "pi1@example.org"
    r10 = await conn.fetchrow("SELECT sample_date, lat, lon FROM coastdom_samples WHERE row_no = 10")
    assert r10["sample_date"] is None and r10["lat"] is None and r10["lon"] is None
    raw8 = await conn.fetchval("SELECT raw FROM coastdom_samples WHERE row_no = 8")
    assert len(raw8) == 49 and raw8[0] == "East China Sea "


async def test_greenland_pp_first_sync(conn, monkeypatch):
    monkeypatch.setattr(pw, "_fetch_bytes", fake_fetch(_files()))
    assert await pw.sync_greenland_pp() == 12
    [v] = await _versions(conn, "greenland-primary-production")
    assert (v["rows_in_source"], v["rows_unmappable"], v["data_points"]) == (12, 0, 12)
    assert v["date_published"] == datetime.date(2025, 4, 7)
    assert await conn.fetchval("SELECT count(*) FROM greenland_pp_stations_current WHERE geom IS NOT NULL") == 12


async def test_unchanged_date_published_skips_the_tsv(conn, monkeypatch):
    await _first_sync(conn, monkeypatch)
    only_ld = fake_fetch({coastdom.JSONLD_URL: coastdom_jsonld()})
    monkeypatch.setattr(pw, "_fetch_bytes", only_ld)
    assert await pw.sync_coastdom() == 0
    assert only_ld.calls == [coastdom.JSONLD_URL]
    assert len(await _versions(conn)) == 1
    log = await conn.fetchrow("SELECT total_records, skipped_reason FROM sync_log WHERE source = 'coastdom'")
    assert log["total_records"] == 12 and log["skipped_reason"] is None


async def test_a_changed_file_adds_a_version_and_keeps_the_old_rows(conn, monkeypatch):
    await _first_sync(conn, monkeypatch)
    changed = coastdom_tsv().replace(b"\t118.00\t", b"\t119.00\t", 1)
    assert changed != coastdom_tsv()
    monkeypatch.setattr(pw, "_fetch_bytes", fake_fetch(_files(changed, coastdom_jsonld("2024-06-01"))))
    assert await pw.sync_coastdom() == 12
    old, new = await _versions(conn)
    assert (old["is_current"], new["is_current"]) == (False, True)
    assert new["date_published"] == datetime.date(2024, 6, 1)
    # Nothing deleted: both versions' rows are in the table.
    assert await conn.fetchval("SELECT count(*) FROM coastdom_samples WHERE version_id = $1", old["version_id"]) == 12
    assert await conn.fetchval("SELECT count(*) FROM coastdom_samples WHERE version_id = $1", new["version_id"]) == 12
    assert await conn.fetchval("SELECT count(*) FROM coastdom_samples_current") == 12
    assert await conn.fetchval("SELECT doc_umol_l FROM coastdom_samples_current WHERE row_no = 1") == 119.0


async def _assert_untouched(conn, version_before):
    [v] = await _versions(conn)
    assert v["version_id"] == version_before and v["is_current"]
    assert await conn.fetchval("SELECT count(*) FROM coastdom_samples") == 12
    reason = await conn.fetchval("SELECT skipped_reason FROM sync_log WHERE source = 'coastdom'")
    assert reason.startswith("aborted, stored version untouched: PangaeaFormatError")


@pytest.mark.parametrize("bad_tsv", [
    b"<!DOCTYPE html><html><body>Service unavailable</body></html>\n",
    coastdom_tsv()[:-40],                                                   # cut mid-row
    coastdom_tsv()[: coastdom_tsv().rstrip(b"\n").rfind(b"\n") + 1],        # last row missing
    coastdom_tsv().replace("DOC [µmol/l]".encode(), "DOC [µmol/kg]".encode()),  # unit changed
], ids=["html", "cut-mid-row", "last-row-missing", "unit-changed"])
async def test_a_bad_download_aborts_and_leaves_the_table_untouched(conn, monkeypatch, bad_tsv):
    await _first_sync(conn, monkeypatch)
    before = (await _versions(conn))[0]["version_id"]
    monkeypatch.setattr(pw, "_fetch_bytes", fake_fetch(_files(bad_tsv, coastdom_jsonld("2024-06-01"))))
    with pytest.raises(PangaeaFormatError):
        await pw.sync_coastdom()
    await _assert_untouched(conn, before)


async def test_jsonld_without_a_date_falls_back_to_a_full_download(conn, monkeypatch):
    await _first_sync(conn, monkeypatch)
    recorder = fake_fetch(_files(ld=coastdom_jsonld(None)))
    monkeypatch.setattr(pw, "_fetch_bytes", recorder)
    assert await pw.sync_coastdom() == 0                  # same bytes → same SHA → nothing new
    assert coastdom.TEXTFILE_URL in recorder.calls
    assert len(await _versions(conn)) == 1


async def test_a_purged_current_version_is_refilled_not_skipped(conn, monkeypatch):
    await _first_sync(conn, monkeypatch)
    await conn.execute("TRUNCATE coastdom_samples")       # what the admin purge does
    monkeypatch.setattr(pw, "_fetch_bytes", fake_fetch(_files()))
    assert await pw.sync_coastdom() == 12
    assert len(await _versions(conn)) == 1
    assert await conn.fetchval("SELECT count(*) FROM coastdom_samples_current") == 12


async def test_force_with_the_same_file_adds_nothing(conn, monkeypatch):
    await _first_sync(conn, monkeypatch)
    monkeypatch.setattr(pw, "_fetch_bytes", fake_fetch(_files()))
    assert await pw.sync_coastdom(force=True) == 0
    assert len(await _versions(conn)) == 1
    assert await conn.fetchval("SELECT count(*) FROM coastdom_samples") == 12


async def test_a_db_error_during_insert_is_logged_and_reraised_leaving_rows_untouched(conn, monkeypatch):
    """A PostgresError raised mid-transaction (e.g. a constraint violation, a
    dropped connection) must still be recorded via _log_sync_skipped, exactly
    like a bad download — the spec requires _log_sync on every path — and the
    transaction's rollback means no partial rows land in the table."""
    await _first_sync(conn, monkeypatch)
    before = (await _versions(conn))[0]["version_id"]
    changed = coastdom_tsv().replace(b"\t118.00\t", b"\t119.00\t", 1)
    monkeypatch.setattr(pw, "_fetch_bytes", fake_fetch(_files(changed, coastdom_jsonld("2024-06-01"))))

    async def boom(self, *args, **kwargs):
        raise asyncpg.PostgresError("simulated failure")

    monkeypatch.setattr(asyncpg.Connection, "executemany", boom)
    with pytest.raises(asyncpg.PostgresError):
        await pw.sync_coastdom()

    await _assert_db_error_untouched(conn, before)


async def _assert_db_error_untouched(conn, version_before):
    [v] = await _versions(conn)
    assert v["version_id"] == version_before and v["is_current"]
    assert await conn.fetchval("SELECT count(*) FROM coastdom_samples") == 12
    reason = await conn.fetchval("SELECT skipped_reason FROM sync_log WHERE source = 'coastdom'")
    assert reason.startswith("aborted, stored version untouched: PostgresError")
