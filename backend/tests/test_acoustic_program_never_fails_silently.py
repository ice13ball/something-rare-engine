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


# ─────────────────────────────────────────────────────────────────────────────
# A position that was never filled in must not become a position.
# ─────────────────────────────────────────────────────────────────────────────

def _meta_at(lat, lon, **extra):
    """One metadata JSON in the archive's nested (Schema A) shape."""
    meta = {
        "SITE": "WEA",
        "PLATFORM_NAME": "Mooring",
        "INSTRUMENT_TYPE": "C-POD",
        "DEPLOYMENT": {
            "DEPLOYMENT_TIME": "2019-06-01T00:00:00",
            "DEPLOY_LAT": lat,
            "DEPLOY_LON": lon,
            "DEPLOY_INSTRUMENT_DEPTH": "-8.5",
        },
    }
    meta["DEPLOYMENT"].update(extra)
    return meta


def test_null_island_is_not_a_hydrophone(caplog):
    """⛔ (0, 0) passes every bounds check and lands in the Gulf of Guinea.

    Real file, read 2026-09-15: MD_WEA_CPOD/metadata/MD_WEA_CPOD.json carries
    DEPLOY_LAT "0", DEPLOY_LON "0", RECOVER_LAT "0", RECOVER_LON "0" and
    DEPLOYMENT_TIME "2000-01-01T00:00:00" — while its own abstract describes
    the Maryland Wind Energy Area. That is an unfilled template, and on a map
    it is a station 6,000 km from the truth with nothing marking it as wrong.
    """
    with caplog.at_level(logging.WARNING):
        rec = mod._extract_record(_meta_at("0", "0"), "pifsc")

    assert rec is None, (
        f"a deployment at (0, 0) was accepted as a station: {rec}. It would "
        "render in the Atlantic off Africa, indistinguishable from a real one.")
    said = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("(0, 0)" in m for m in said), (
        "the record was dropped in silence, so a source that stops publishing "
        "positions is indistinguishable from a source with no deployments")


def test_a_real_position_on_the_equator_survives():
    """⛔ Positive control, and the reason the test above uses AND, not OR.

    0.0 is an ordinary latitude on the equator and an ordinary longitude
    through Greenwich. A guard that dropped either one alone would quietly
    delete real stations — a worse error than the one it fixes.
    """
    on_equator = mod._extract_record(_meta_at("0", "-24.5"), "pifsc")
    assert on_equator is not None, "a station on the equator was thrown away"
    assert on_equator["lat"] == 0.0 and on_equator["lon"] == -24.5

    on_greenwich = mod._extract_record(_meta_at("51.4", "0"), "pifsc")
    assert on_greenwich is not None, "a station on the prime meridian was thrown away"
    assert on_greenwich["lat"] == 51.4 and on_greenwich["lon"] == 0.0
