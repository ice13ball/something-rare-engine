# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""OBSEA (Expandable Seafloor Observatory) hydrophone ingest.

OBSEA is a single cabled coastal observatory 4 km off Vilanova i la Geltrú in
Catalonia, operated by the SARTI Research Group at UPC since April 2009. Shallow
(20 m) — the only Mediterranean coastal acoustic platform in the set. No public
REST API for the per-station record; coordinates from del Río et al. (2011)
Sensors and the obsea.es location page. Soundscape numeric product not
available (raw recordings surfaced via SARTI publications); returns [].

"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

log = logging.getLogger(__name__)


async def fetch_obsea_stations() -> list[dict[str, Any]]:
    """Return the single OBSEA hydrophone station row.

    Coordinates cross-checked via OceanOPS WMO 6103565 and EMODnet platform 8805.
    icListen HF (Ocean Sonics) is the current hydrophone — earlier deployments
    used the NaxysEthernet series; the model field captures the present sensor.
    """
    return [{
        "station_id":   "obsea:upc",
        "source":       "obsea",
        "name":         "OBSEA — Expandable Seafloor Observatory",
        "operator":     "SARTI Research Group, Universitat Politècnica de Catalunya (UPC)",
        "lat":          41.1817,
        "lon":          1.7522,
        "depth_m":      20.0,
        "deploy_start": date(2009, 4, 1),  # cabled-platform commissioning
        "deploy_end":   None,              # ongoing — obsea.es 2026 news confirms operation
        "model":        "icListen HF (Ocean Sonics)",
        "hz_range_lo":  10.0,
        "hz_range_hi":  200_000.0,  # icListen HF supports up to 200 kHz
        "portal_url":   "https://www.obsea.es/index.php/en/observatory",
    }]


async def fetch_obsea_soundscape(station_id: str, days: int = 90) -> list[dict[str, Any]]:
    """Return [] — OBSEA publishes raw recordings via SARTI publications.

    There is no first-party REST/ERDDAP endpoint for decoded SPL or decade-band
    time series. Same Phase-1 empty-state pattern as OOI/IMOS/MARS.
    """
    return []
