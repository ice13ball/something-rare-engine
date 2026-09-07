# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""AWI HAUSGARTEN / FRAM Observatory hydrophone ingest (PANGAEA-path).

Seven moored hydrophone positions from AWI's FRAM Observatory in the Fram Strait,
published via PANGAEA (doi.pangaea.de). All datasets are CC BY 4.0.

These stations complement the existing 'fram' source rows that come from the NOAA
Passive Acoustic Archive S3 bucket (acoustic_noaa_archive_ingest).  station_id prefix
'fram-pangaea:' keeps them disjoint from the NOAA-archive rows ('fram-ncei:' prefix).
Both use source='fram' so they appear under the same filter chip in the UI.

References (per-mooring PANGAEA datasets, all CC BY 4.0)
----------
SV1021 F16-9      → PANGAEA.967557 (Thomisch/Spiesecke/Boebel 2024, raw)
SV1026 ARKF04-15  → PANGAEA.945330 (Thomisch 2022, 5-recorder Fram series)
SV1088 F5-17      → PANGAEA.956286 (Thomisch/Spiesecke/Boebel 2023, raw)
SV1091 ARKR02-01  → PANGAEA.945364 (Thomisch 2022, single mooring)
SV1097 F-EGC      → PANGAEA.945330 (Thomisch 2022, 5-recorder Fram series)
F4-OZA-2 (×2)     → PANGAEA.964051 (Hoppmann 2023)
License: CC BY 4.0 — see each dataset's spatialCoverage/license field.

"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Static station records (hardcoded from PANGAEA JSON-LD abstracts + bench notes)
# ---------------------------------------------------------------------------
# Two instruments on the 2020-2022 F4-OZA-2 mooring are counted as separate stations
# because they are at distinct depths (300 m vs 836 m) with different recorder models.
_STATIONS: list[dict[str, Any]] = [
    {
        "station_id":   "fram-pangaea:F16-9-SV1021",
        "source":       "fram",
        "name":         "F16-9 (Sono.Vault SV1021)",
        "operator":     "Alfred Wegener Institute — FRAM Observatory (PANGAEA)",
        "lat":          78.8293,
        "lon":           0.4295,
        "depth_m":      800.0,
        "deploy_start": date(2012, 6, 28),
        "deploy_end":   date(2014, 9, 15),
        "model":        "develogic Sono.Vault",
        "hz_range_lo":   0.0,
        "hz_range_hi":  2666.0,   # 48 kS/s effective → 24 kHz Nyquist; broadband 0-2666 Hz usable
        "portal_url":   "https://doi.org/10.1594/PANGAEA.967557",
    },
    {
        "station_id":   "fram-pangaea:ARKF04-15-SV1026",
        "source":       "fram",
        "name":         "ARKF04-15 (Sono.Vault SV1026)",
        "operator":     "Alfred Wegener Institute — FRAM Observatory (PANGAEA)",
        "lat":          78.8335,
        "lon":           6.9998,
        "depth_m":      743.0,
        "deploy_start": date(2012, 6, 28),
        "deploy_end":   date(2015, 6, 15),
        "model":        "develogic Sono.Vault",
        "hz_range_lo":   0.0,
        "hz_range_hi":  2666.0,
        # SV1026 has no single-mooring dataset; cited via the 5-recorder Fram
        # series (Thomisch 2022) which covers SV1021/1026/1088/1091/1097.
        "portal_url":   "https://doi.org/10.1594/PANGAEA.945330",
    },
    {
        "station_id":   "fram-pangaea:F5-17-SV1088",
        "source":       "fram",
        "name":         "F5-17 (Sono.Vault SV1088)",
        "operator":     "Alfred Wegener Institute — FRAM Observatory (PANGAEA)",
        "lat":          79.00033,
        "lon":           5.66867,
        "depth_m":      808.0,
        "deploy_start": date(2016, 7, 1),
        "deploy_end":   date(2018, 9, 1),
        "model":        "develogic Sono.Vault",
        "hz_range_lo":   0.0,
        "hz_range_hi":  2666.0,
        # Raw SV1088 F5-17 2016/2017 recordings (Thomisch/Spiesecke/Boebel 2023).
        "portal_url":   "https://doi.org/10.1594/PANGAEA.956286",
    },
    {
        "station_id":   "fram-pangaea:ARKR02-01-SV1091",
        "source":       "fram",
        "name":         "ARKR02-01 (Sono.Vault SV1091)",
        "operator":     "Alfred Wegener Institute — FRAM Observatory (PANGAEA)",
        "lat":          78.8335,
        "lon":           0.0015,
        "depth_m":      806.0,
        "deploy_start": date(2016, 7, 1),
        "deploy_end":   date(2018, 7, 1),
        "model":        "develogic Sono.Vault",
        "hz_range_lo":   0.0,
        "hz_range_hi":  2666.0,
        # SV1091 single-mooring dataset (Thomisch 2022).
        "portal_url":   "https://doi.org/10.1594/PANGAEA.945364",
    },
    {
        "station_id":   "fram-pangaea:F-EGC-SV1097",
        "source":       "fram",
        "name":         "F-EGC (Sono.Vault SV1097, East Greenland Current)",
        "operator":     "Alfred Wegener Institute — FRAM Observatory (PANGAEA)",
        "lat":          78.17,
        "lon":           0.0007,
        "depth_m":      800.0,
        "deploy_start": date(2016, 7, 1),
        "deploy_end":   date(2017, 8, 1),
        "model":        "develogic Sono.Vault",
        "hz_range_lo":   0.0,
        "hz_range_hi":  2666.0,
        # SV1097 has no single-mooring dataset; cited via the 5-recorder Fram
        # series (Thomisch 2022) which covers SV1021/1026/1088/1091/1097.
        "portal_url":   "https://doi.org/10.1594/PANGAEA.945330",
    },
    {
        # F4-OZA-2 mooring upper instrument (AURAL M2, 300 m)
        "station_id":   "fram-pangaea:F4-OZA-2-AURAL",
        "source":       "fram",
        "name":         "F4-OZA-2 (AURAL M2, 300 m)",
        "operator":     "Alfred Wegener Institute — FRAM Observatory (PANGAEA)",
        "lat":          79.0,
        "lon":           4.5,
        "depth_m":      300.0,
        "deploy_start": date(2020, 7, 1),
        "deploy_end":   date(2022, 7, 1),
        "model":        "MTE AURAL M2",
        "hz_range_lo":  10.0,
        "hz_range_hi":  32000.0,  # 64 kS/s effective → 32 kHz Nyquist
        "portal_url":   "https://doi.org/10.1594/PANGAEA.964051",
    },
    {
        # F4-OZA-2 mooring lower instrument (Sono.Vault, 836 m)
        "station_id":   "fram-pangaea:F4-OZA-2-SV",
        "source":       "fram",
        "name":         "F4-OZA-2 (Sono.Vault, 836 m)",
        "operator":     "Alfred Wegener Institute — FRAM Observatory (PANGAEA)",
        "lat":          79.0,
        "lon":           4.5,
        "depth_m":      836.0,
        "deploy_start": date(2020, 7, 1),
        "deploy_end":   date(2022, 7, 1),
        "model":        "develogic Sono.Vault",
        "hz_range_lo":   0.0,
        "hz_range_hi":  2666.0,
        "portal_url":   "https://doi.org/10.1594/PANGAEA.964051",
    },
]


# Verified license for the Fram-Strait PAM dataset family (see bench notes
# §P-Polar, 2026-05-11): every sampled AWI Fram acoustic dataset on PANGAEA
# carries CC BY 4.0, and PANGAEA's institutional default is CC BY 4.0 with no
# override on any of these. Commercial-compatible — none to skip.
_LICENSE = "CC BY 4.0"


async def fetch_hausgarten_stations() -> list[dict[str, Any]]:
    """Return the 7 AWI HAUSGARTEN / FRAM Observatory hydrophone station records.

    All coordinates and metadata are sourced from PANGAEA JSON-LD dataset abstracts
    (CC BY 4.0).  No live network calls are made.
    """
    log.info("fetch_hausgarten_stations: returning %d hardcoded stations", len(_STATIONS))
    return [dict(s, license=_LICENSE) for s in _STATIONS]


async def fetch_hausgarten_soundscape(station_id: str, days: int = 90) -> list[dict[str, Any]]:
    """Return [] — PANGAEA FRAM datasets archive raw .wav files only.

    No decoded SPL or decade-band time series is published.  Same Phase-1
    empty-state pattern as PALAOA / OOI / IMOS / MARS.
    """
    return []
