# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""KM3NeT (ARCA + ORCA) deep-Mediterranean neutrino-telescope acoustic ingest.

KM3NeT operates two deep-sea cabled detector sites that include acoustic
hydrophones (used internally for detection-unit positioning + ambient-noise
studies). No first-party REST API for acoustic data — opendata.km3net.de hosts
only neutrino-interaction data products (Dataverse query for "acoustic" returns
total_count: 0). Station metadata is hardcoded; coordinates from the KM3NeT
detector pages and Wikipedia geo-dec markup. Soundscape numeric product not
available; returns [].

Two stations:
- ARCA / KM3NeT-It — off Capo Passero, Sicily — 3500 m
- ORCA / KM3NeT-Fr — off Toulon, France — 2500 m

These are the two deepest entries in `acoustic_stations` and the only ones
exceeding 2 km depth.

"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

log = logging.getLogger(__name__)


async def fetch_km3net_stations() -> list[dict[str, Any]]:
    """Return the two KM3NeT hydrophone station rows (ARCA + ORCA).

    Both detectors are under construction as of 2026 but already taking data
    with >10% of detection units installed. deploy_start = first detection unit
    deployment (KM3NeT sea-campaigns archive).
    """
    return [
        {
            "station_id":   "km3net:arca",
            "source":       "km3net",
            "name":         "KM3NeT/ARCA — Capo Passero",
            "operator":     "KM3NeT Collaboration (INFN, CNRS, Nikhef, et al.)",
            "lat":          36.267,
            "lon":          16.100,
            "depth_m":      3500.0,
            "deploy_start": date(2015, 12, 1),
            "deploy_end":   None,
            "model":        "Acoustic piezo sensor on Digital Optical Module + hydrophone on DU base",
            "hz_range_lo":  1_000.0,    # 1 kHz lower (positioning + ambient)
            "hz_range_hi":  100_000.0,  # 100 kHz upper (acoustic neutrino signature regime)
            "portal_url":   "https://www.km3net.org/research/research-infrastructure/km3net-it-site/",
        },
        {
            "station_id":   "km3net:orca",
            "source":       "km3net",
            "name":         "KM3NeT/ORCA — Toulon",
            "operator":     "KM3NeT Collaboration (INFN, CNRS, Nikhef, et al.)",
            "lat":          42.800,
            "lon":          6.033,
            "depth_m":      2500.0,
            "deploy_start": date(2017, 9, 1),
            "deploy_end":   None,
            "model":        "Acoustic piezo sensor on Digital Optical Module + hydrophone on DU base",
            "hz_range_lo":  1_000.0,
            "hz_range_hi":  100_000.0,
            "portal_url":   "https://www.km3net.org/research/research-infrastructure/km3net-fr-site/",
        },
    ]


async def fetch_km3net_soundscape(station_id: str, days: int = 90) -> list[dict[str, Any]]:
    """Return [] — KM3NeT publishes neutrino data, not acoustic time series.

    Acoustic work appears in one-off academic papers (Bormuth et al.,
    Adrián-Martínez et al.) but not as a continuous numeric product. Same
    Phase-1 empty-state pattern as OOI/IMOS/MARS.
    """
    return []
