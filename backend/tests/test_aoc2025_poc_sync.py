# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""Sync + serving for the AOC2025 POC preview layer, against a real Postgres."""
import hashlib

import pytest

from domains import aoc2025_poc as dm
from ingestion import aoc2025_poc as parser
from aoc2025_poc_helpers import CSV, conn, fake_fetch, needs_db  # noqa: F401  (conn is a fixture)

SHA = hashlib.sha256(CSV).hexdigest()


@pytest.fixture
async def seeded(conn, monkeypatch):
    monkeypatch.setattr(dm, "_fetch_bytes", fake_fetch({parser.SOURCE_URL: CSV}))
    await dm.sync_aoc2025_poc()
    dm.clear_caches()
    yield conn
    dm.clear_caches()


@needs_db
class TestSync:
    async def test_sync_inserts_a_current_version_with_every_row(self, seeded):
        row = await seeded.fetchrow(
            "SELECT * FROM aoc2025_poc_version WHERE is_current")
        assert row["sha256"] == SHA
        assert row["rows_in_source"] == 94
        assert row["doi"] == parser.DOI
        assert row["citation"] == dm.CITATION
        assert row["license"] == dm.LICENSE

        n = await seeded.fetchval("SELECT count(*) FROM aoc2025_poc_samples_current")
        assert n == 94

    async def test_re_sync_with_unchanged_file_adds_nothing(self, seeded):
        version_before = await seeded.fetchval(
            "SELECT version_id FROM aoc2025_poc_version WHERE is_current")
        added = await dm.sync_aoc2025_poc()
        assert added == 0
        version_after = await seeded.fetchval(
            "SELECT version_id FROM aoc2025_poc_version WHERE is_current")
        assert version_before == version_after
        n_versions = await seeded.fetchval("SELECT count(*) FROM aoc2025_poc_version")
        assert n_versions == 1

    async def test_a_changed_file_adds_a_new_version_and_deletes_nothing(self, seeded, monkeypatch):
        old_version = await seeded.fetchval(
            "SELECT version_id FROM aoc2025_poc_version WHERE is_current")
        # Drop the last data row to produce a different, still-valid file.
        lines = CSV.decode("utf-8").splitlines(keepends=True)
        mutated = "".join(lines[:-1]).encode("utf-8")
        assert mutated != CSV
        monkeypatch.setattr(dm, "_fetch_bytes", fake_fetch({parser.SOURCE_URL: mutated}))

        added = await dm.sync_aoc2025_poc()
        assert added == 93

        n_versions = await seeded.fetchval("SELECT count(*) FROM aoc2025_poc_version")
        assert n_versions == 2
        old_rows_still_present = await seeded.fetchval(
            "SELECT count(*) FROM aoc2025_poc_samples WHERE version_id = $1", old_version)
        assert old_rows_still_present == 94, "old version's rows must never be deleted"

        current = await seeded.fetchval(
            "SELECT version_id FROM aoc2025_poc_version WHERE is_current")
        assert current != old_version
        current_n = await seeded.fetchval("SELECT count(*) FROM aoc2025_poc_samples_current")
        assert current_n == 93

    async def test_a_bad_header_aborts_before_the_transaction_commits(self, seeded, monkeypatch):
        version_before = await seeded.fetchval(
            "SELECT version_id FROM aoc2025_poc_version WHERE is_current")
        rows_before = await seeded.fetchval("SELECT count(*) FROM aoc2025_poc_samples_current")

        mutated = CSV.replace(b"SDN:P01::CORGCAP1<Float32>", b"SDN:P01::CORGCAP1_CHANGED<Float32>")
        monkeypatch.setattr(dm, "_fetch_bytes", fake_fetch({parser.SOURCE_URL: mutated}))

        with pytest.raises(parser.Aoc2025PocFormatError):
            await dm.sync_aoc2025_poc()

        version_after = await seeded.fetchval(
            "SELECT version_id FROM aoc2025_poc_version WHERE is_current")
        rows_after = await seeded.fetchval("SELECT count(*) FROM aoc2025_poc_samples_current")
        assert version_after == version_before
        assert rows_after == rows_before

        skip_row = await seeded.fetchrow(
            "SELECT skipped_reason, last_synced_at FROM sync_log WHERE source = 'aoc2025-poc'")
        assert skip_row["skipped_reason"] is not None
