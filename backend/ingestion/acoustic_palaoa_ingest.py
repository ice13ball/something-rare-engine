# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""AWI PALAOA (PerenniAL Acoustic Observatory in the Antarctic Ocean) ingest.

PALAOA was a cabled hydrophone array on the Ekstrom Ice Shelf, Antarctica,
operated by AWI from 2005 until ~2017 (decommissioned after Neumayer III shelf
cable damage). No first-party REST API — station metadata is hardcoded from the
PANGAEA umbrella dataset (DOI 10.1594/PANGAEA.773610, Kindermann 2013).
Soundscape numeric product not available (PANGAEA publishes raw .wav stream
links only); returns [].

"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

log = logging.getLogger(__name__)


async def fetch_palaoa_stations() -> list[dict[str, Any]]:
    """Return the single PALAOA hydrophone station row.

    Coordinates from PANGAEA spatialCoverage (schema.org GeoCoordinates).
    Depth from Kindermann (2007) Bioacoustics paper — not in JSON-LD.
    deploy_end conservatively set to 2017-12-31 reflecting the Neumayer III
    cable-damage decommissioning; revisit if AWI publishes a re-deployment.
    """
    return [{
        "station_id":   "palaoa:awi",
        "source":       "palaoa",
        "name":         "PALAOA — PerenniAL Acoustic Observatory in the Antarctic Ocean",
        "operator":     "Alfred Wegener Institute (AWI)",
        "lat":          -70.523,
        "lon":          -8.230,
        "depth_m":      160.0,
        "deploy_start": date(2005, 12, 1),
        "deploy_end":   date(2017, 12, 31),  # decommissioned after Neumayer III cable damage
        "model":        "Three Reson TC4032 hydrophones on subice cable array",
        "hz_range_lo":  10.0,
        "hz_range_hi":  96_000.0,  # 192 kS/s effective, ~96 kHz upper
        "portal_url":   "https://doi.pangaea.de/10.1594/PANGAEA.773610",
    }]


async def fetch_palaoa_soundscape(station_id: str, days: int = 90) -> list[dict[str, Any]]:
    """Return [] — PANGAEA child datasets link to raw .wav stream files only.

    No decoded SPL or decade-band time series is published. Same Phase-1
    empty-state pattern as OOI/IMOS/MARS.
    """
    return []
