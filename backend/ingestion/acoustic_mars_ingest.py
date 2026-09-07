# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""MBARI MARS (Monterey Accelerated Research System) hydrophone ingest.

MARS is a single cabled hydrophone in Monterey Bay, 891 m depth. No API — station
metadata is hardcoded from public documentation (docs.mbari.org/pacific-sound).
Soundscape numeric product not available publicly (only daily spectrogram JPGs
exist in the pacific-sound-spectra S3 bucket); returns [].

"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

log = logging.getLogger(__name__)


async def fetch_mars_stations() -> list[dict[str, Any]]:
    """Return the single MARS hydrophone station row.

    All values are constants drawn from MBARI's public cabled-observatory
    documentation and the AWS Open Data pacific-sound registry.
    """
    return [{
        "station_id":   "mars:mbari",
        "source":       "mars",
        "name":         "MARS Cabled Observatory",
        "operator":     "Monterey Bay Aquarium Research Institute",
        "lat":          36.7128,
        "lon":          -122.1869,
        "depth_m":      891.0,
        "deploy_start": date(2015, 7, 28),
        "deploy_end":   None,  # ongoing
        "model":        "Naxys Ethernet Hydrophone 02345 (2015-2017) / Reson TC-4032 (current)",
        "hz_range_lo":  10.0,
        "hz_range_hi":  100_000.0,
        "portal_url":   "https://docs.mbari.org/pacific-sound/",
    }]


async def fetch_mars_soundscape(station_id: str, days: int = 90) -> list[dict[str, Any]]:
    """Return [] — MARS publishes only daily spectrogram JPGs, no numeric SPL.

    A Phase 2 enhancement could surface the most-recent JPG as a thumbnail in the
    panel, but that's not a sparkline data row — out of scope for Phase 1.
    """
    return []
