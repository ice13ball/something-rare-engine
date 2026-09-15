# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""A configured acoustic program that yields nothing must say so.

Found 2026-09-15. The `ioos` program pointed at `ioos/audio/`, a prefix the
NOAA archive had emptied — verified live: zero objects and zero sub-prefixes,
while the same network's data sits under `esons/` in 50 deployment folders.

The walker returned `[]` without a word. Twelve programs share one row count in
`sync_log`, so a zero vanished in the sum: the sync kept reporting success and
the map kept serving 19 station positions last fetched on 2026-05-30, while
every other program refreshed on 2026-09-10.

⛔ "Ran and found nothing" and "the source moved out from under us" must not
look the same. This test holds the warning that separates them.
"""
import logging

import pytest

from ingestion import acoustic_noaa_archive_ingest as mod


@pytest.mark.asyncio
async def test_a_program_whose_prefix_yields_nothing_warns_by_name(monkeypatch, caplog):
    async def _nothing(client, prefix):
        return []

    monkeypatch.setattr(mod, "_discover_metadata_jsons", _nothing)
    with caplog.at_level(logging.WARNING):
        rows = await mod.fetch_program_stations("pifsc")

    assert rows == []
    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, "an empty program returned silently — the ioos failure again"
    joined = " ".join(warnings)
    # ⛔ Named, not just counted. A warning that does not say WHICH program is
    # as useless as none when twelve share one sync row.
    assert "pifsc" in joined
    assert mod.PROGRAMS["pifsc"]["prefix"] in joined


@pytest.mark.asyncio
async def test_a_program_that_does_yield_stays_quiet(monkeypatch, caplog):
    """⛔ Positive control. Without it the assertion above would pass on a
    walker that warned unconditionally, which trains people to ignore it."""
    async def _one(client, prefix):
        return [f"{prefix}x/metadata/y.json"]

    async def _meta(client, path):
        return None  # parsed away later; we only care that no warning fires here

    monkeypatch.setattr(mod, "_discover_metadata_jsons", _one)
    monkeypatch.setattr(mod, "_fetch_json", _meta)
    with caplog.at_level(logging.WARNING):
        await mod.fetch_program_stations("pifsc")

    moved = [r.getMessage() for r in caplog.records
             if r.levelno >= logging.WARNING and "yielded NO metadata" in r.getMessage()]
    assert not moved, f"warned about a program that did yield: {moved}"


def test_no_configured_program_points_at_the_emptied_prefix():
    """The specific regression: `ioos/audio/` is empty in the bucket."""
    bad = [name for name, cfg in mod.PROGRAMS.items() if cfg["prefix"] == "ioos/audio/"]
    assert not bad, (
        f"{bad} still point at ioos/audio/, which the NOAA archive has emptied — "
        "this network is published under esons/"
    )
