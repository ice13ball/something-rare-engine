# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""A hydrophone's longitude reaches the row exactly as NOAA published it.

Until 2026-09-23 `_extract_record` negated any longitude of 100..180 whose
`SEA_AREA` mentioned "Pacific", to repair a few Navy SoCal sites published
without their minus sign. The western Pacific has positive longitudes too, so
the rule moved real sites across the ocean. Measured on production:

    PIFSC Wake_S    published 166.3073  -> stored -166.31  (~2,900 km)
    PIFSC Saipan_A  published ~145.5    -> stored -145.46  (~7,400 km)
    PIFSC Tinian_A  published ~145.8    -> stored -145.76  (~7,400 km)

The metadata below is copied from
`pifsc/audio/pipan_200/wake_s/pipan_wake_s_03_200/metadata/PIPAN_Wake_S_03_200.json`
in the public `noaa-passive-bioacoustic` bucket.
"""
from ingestion import acoustic_noaa_archive_ingest as mod

_WAKE_S = {
    "SITE": "Wake_S",
    "PLATFORM_NAME": "Mooring",
    "DEPLOYMENT": {
        "DEPLOYMENT_TIME": "2019-05-01T00:00:00",
        "SEA_AREA": "North Pacific Ocean",
        "DEPLOY_LAT": 19.2209,
        "DEPLOY_LON": 166.3073,
    },
}


def _meta(lon, sea_area="North Pacific Ocean", lat=32.0):
    return {
        "SITE": "S1",
        "PLATFORM_NAME": "Mooring",
        "DEPLOYMENT": {
            "DEPLOYMENT_TIME": "2019-05-01T00:00:00",
            "SEA_AREA": sea_area,
            "DEPLOY_LAT": lat,
            "DEPLOY_LON": lon,
        },
    }


def test_western_pacific_longitude_is_not_negated():
    rec = mod._extract_record(_WAKE_S, "pifsc")
    assert rec is not None
    assert rec["lon"] == 166.3073
    assert rec["lat"] == 19.2209


def test_a_longitude_that_looks_sign_dropped_is_still_passed_through():
    """The Navy SoCal case the old rule was written for. It renders where the
    source puts it; the defect is the publisher's to fix."""
    rec = mod._extract_record(_meta(118.78), "navy")
    assert rec is not None
    assert rec["lon"] == 118.78


def test_zero_to_360_longitude_is_still_normalised():
    """241.22 and -118.78 are the same meridian written two ways; this is a
    change of notation, not a correction, and it stays."""
    rec = mod._extract_record(_meta(241.22), "navy")
    assert rec is not None
    assert abs(rec["lon"] - (-118.78)) < 1e-9


async def test_the_station_row_carries_the_published_longitude(monkeypatch):
    """Guard the call site, not only the helper: the row that reaches the
    upsert must carry the published value."""
    path = "pifsc/audio/pipan_200/wake_s/pipan_wake_s_03_200/metadata/PIPAN_Wake_S_03_200.json"

    async def _discover(client, prefix, max_depth=6):
        return [path]

    async def _fetch(client, name):
        return _WAKE_S if name == path else None

    monkeypatch.setattr(mod, "_discover_metadata_jsons", _discover)
    monkeypatch.setattr(mod, "_fetch_json", _fetch)

    rows = await mod.fetch_program_stations("pifsc")

    assert len(rows) == 1
    assert rows[0]["lon"] == 166.3073
