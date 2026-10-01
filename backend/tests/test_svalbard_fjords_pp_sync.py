# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""Sync + serving for the Svalbard fjords primary-production preview layer,
against a real Postgres."""
import hashlib

import pytest

from domains import svalbard_fjords_pp as dm
from ingestion import svalbard_fjords_pp as parser
from svalbard_fjords_pp_helpers import CSV, conn, fake_fetch, needs_db  # noqa: F401  (conn is a fixture)

SHA = hashlib.sha256(CSV).hexdigest()


@pytest.fixture
async def seeded(conn, monkeypatch):
    monkeypatch.setattr(dm, "_fetch_bytes", fake_fetch({parser.SOURCE_URL: CSV}))
    await dm.sync_svalbard_fjords_pp()
    dm.clear_caches()
    yield conn
    dm.clear_caches()


@needs_db
class TestSync:
    async def test_sync_inserts_a_current_version_with_every_row(self, seeded):
        row = await seeded.fetchrow(
            "SELECT * FROM svalbard_fjords_pp_version WHERE is_current")
        assert row["sha256"] == SHA
        assert row["rows_in_source"] == 369
        assert row["doi"] == parser.DOI
        assert row["citation"] == dm.CITATION
        assert row["licence"] == dm.LICENCE

        n = await seeded.fetchval("SELECT count(*) FROM svalbard_fjords_pp_samples_current")
        assert n == 369

    async def test_re_sync_with_unchanged_file_adds_nothing(self, seeded):
        version_before = await seeded.fetchval(
            "SELECT version_id FROM svalbard_fjords_pp_version WHERE is_current")
        added = await dm.sync_svalbard_fjords_pp()
        assert added == 0
        version_after = await seeded.fetchval(
            "SELECT version_id FROM svalbard_fjords_pp_version WHERE is_current")
        assert version_before == version_after
        n_versions = await seeded.fetchval("SELECT count(*) FROM svalbard_fjords_pp_version")
        assert n_versions == 1
        skip_row = await seeded.fetchrow(
            "SELECT last_synced_at FROM sync_log WHERE source = 'svalbard-fjords-pp'")
        assert skip_row is not None, "even a same-bytes re-sync must log"

    async def test_a_changed_file_adds_a_new_version_and_deletes_nothing(self, seeded, monkeypatch):
        old_version = await seeded.fetchval(
            "SELECT version_id FROM svalbard_fjords_pp_version WHERE is_current")
        lines = CSV.decode("utf-8-sig").splitlines(keepends=True)
        mutated = "".join(lines[:-1]).encode("utf-8")
        assert mutated != CSV
        monkeypatch.setattr(dm, "_fetch_bytes", fake_fetch({parser.SOURCE_URL: mutated}))

        added = await dm.sync_svalbard_fjords_pp()
        assert added == 368

        n_versions = await seeded.fetchval("SELECT count(*) FROM svalbard_fjords_pp_version")
        assert n_versions == 2
        old_rows_still_present = await seeded.fetchval(
            "SELECT count(*) FROM svalbard_fjords_pp_samples WHERE version_id = $1", old_version)
        assert old_rows_still_present == 369, "old version's rows must never be deleted"

        current = await seeded.fetchval(
            "SELECT version_id FROM svalbard_fjords_pp_version WHERE is_current")
        assert current != old_version
        current_n = await seeded.fetchval("SELECT count(*) FROM svalbard_fjords_pp_samples_current")
        assert current_n == 368

    async def test_a_bad_header_aborts_before_the_transaction_commits(self, seeded, monkeypatch):
        version_before = await seeded.fetchval(
            "SELECT version_id FROM svalbard_fjords_pp_version WHERE is_current")
        rows_before = await seeded.fetchval("SELECT count(*) FROM svalbard_fjords_pp_samples_current")

        mutated = CSV.replace(b"Pi_[mgC_m-2_day-1]<Float32>", b"Pi_[mgC_m-2_day-1]_CHANGED<Float32>")
        monkeypatch.setattr(dm, "_fetch_bytes", fake_fetch({parser.SOURCE_URL: mutated}))

        with pytest.raises(parser.SvalbardFjordsPpFormatError):
            await dm.sync_svalbard_fjords_pp()

        version_after = await seeded.fetchval(
            "SELECT version_id FROM svalbard_fjords_pp_version WHERE is_current")
        rows_after = await seeded.fetchval("SELECT count(*) FROM svalbard_fjords_pp_samples_current")
        assert version_after == version_before
        assert rows_after == rows_before

        skip_row = await seeded.fetchrow(
            "SELECT skipped_reason, last_synced_at FROM sync_log WHERE source = 'svalbard-fjords-pp'")
        assert skip_row["skipped_reason"] is not None
