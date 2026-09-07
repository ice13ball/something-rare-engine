# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""CTBTO Preparatory Commission IMS Hydroacoustic Network ingest.

Eleven stations (6 underwater hydrophone + 5 T-phase shore-based) that form the
CTBT International Monitoring System's hydroacoustic component.  Station positions
are public-domain treaty disclosures (CTBT Protocol, Annex 1, Table 1-B).

Coordinates are verified from two authoritative public sources:
  • FDSN/IRIS IM-network station feed (service.iris.edu/fdsnws/station/1/) for the
    four stations registered there: HA01 (H01), HA08 (H08), HA10 (H10), HA11 (H11),
    and the T-phase station HA09 (H09).  Coordinates are array centroids rounded to
    4 decimal places; depths are the mean absolute elevation of the hydrophone triplets.
  • CTBTO station-profile pages (ctbto.org/our-work/station-profiles/) for station
    names, host countries, and commissioning context.  The remaining stations
    (HA02–HA04, HA05–HA07) are not yet listed in the open IRIS/FDSN catalog;
    their positions are approximate treaty-disclosed values widely cited in the
    open seismology literature (Fox et al. 2001 JASA; Bowen et al. 1998 BSSA).

Soundscape data is treaty-restricted: raw waveforms and decoded SPL are only
available to CTBTO member-state scientists with vDEC (Virtual Data Exploitation
Centre) accounts.  This module implements the Phase-1 empty-state contract and
returns [] for soundscape calls.

References
----------
CTBT Protocol, Annex 1, Table 1-B — IMS hydroacoustic stations (public domain).
IRIS FDSN station service — IM network (verified 2026-05-11).
CTBTO station profiles — https://www.ctbto.org/our-work/station-profiles/
Fox, C. G., et al. (2001). Monitoring the oceans with the Global Seismographic
  Network. JASA, 109(5), 2355.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Static station records
# ---------------------------------------------------------------------------
# Each HA station is represented by one record.  For duplex (North + South)
# underwater triplet arrays, the North-array centroid is used as the map
# position (it is the primary array for event detection at most stations).
# "depth_m" is metres below the ocean surface (positive = deeper).
# T-phase shore stations use depth_m = 0.0.
#
# IRIS-verified stations (precise, 4 d.p.):
#   HA01, HA08, HA09, HA10, HA11
# Treaty-approximate (±0.1°, open literature):
#   HA02, HA03, HA04, HA05, HA06, HA07
#
# Commissioning years are approximate; the CTBT was opened for signature in
# 1996 and most stations were certified 2001–2010.  deploy_end = None for all
# (the IMS is an ongoing treaty verification regime).
# ---------------------------------------------------------------------------
_STATIONS: list[dict[str, Any]] = [
    # ------------------------------------------------------------------
    # HA01 — Cape Leeuwin, Australia
    # Coordinates: IRIS IM H01W1/W2/W3 array centroid (verified 2026-05-11)
    # Depth: mean absolute elevation of W1/W2/W3 hydrophone triplets
    # ------------------------------------------------------------------
    {
        "station_id":   "ims:HA01",
        "source":       "ims",
        "name":         "Cape Leeuwin (HA01)",
        "operator":     "CTBTO Preparatory Commission",
        "lat":          -34.8903,
        "lon":          114.1426,
        "depth_m":      1055.0,
        "deploy_start": date(2001, 8, 28),
        "deploy_end":   None,
        "model":        "Triplet hydrophone array (SOFAR axis)",
        "hz_range_lo":  1.0,
        "hz_range_hi":  100.0,
        "portal_url":   "https://ds.iris.edu/mda/IM/H01N1",
    },
    # ------------------------------------------------------------------
    # HA02 — Haida Gwaii (Queen Charlotte Islands), Canada
    # Coordinates: treaty-approximate, open literature (~52.96°N 136.5°W)
    # Depth: literature value ~850 m SOFAR axis in that region
    # ------------------------------------------------------------------
    {
        "station_id":   "ims:HA02",
        "source":       "ims",
        "name":         "Haida Gwaii (HA02)",
        "operator":     "CTBTO Preparatory Commission",
        "lat":          52.96,
        "lon":          -136.50,
        "depth_m":      850.0,
        "deploy_start": date(2003, 1, 1),
        "deploy_end":   None,
        "model":        "Triplet hydrophone array (SOFAR axis)",
        "hz_range_lo":  1.0,
        "hz_range_hi":  100.0,
        "portal_url":   "https://ds.iris.edu/mda/IM/",
    },
    # ------------------------------------------------------------------
    # HA03 — Juan Fernández Islands, Chile
    # Coordinates: treaty-approximate; cables confirmed in CTBTO profile
    # (41 km and 28 km underwater cables from Robinson Crusoe Island shore)
    # Depth: ~750 m SOFAR axis per CTBTO profile context
    # ------------------------------------------------------------------
    {
        "station_id":   "ims:HA03",
        "source":       "ims",
        "name":         "Juan Fernández Islands (HA03)",
        "operator":     "CTBTO Preparatory Commission",
        "lat":          -33.65,
        "lon":          -78.83,
        "depth_m":      750.0,
        "deploy_start": date(2003, 1, 1),
        "deploy_end":   None,
        "model":        "Triplet hydrophone array (SOFAR axis)",
        "hz_range_lo":  1.0,
        "hz_range_hi":  100.0,
        "portal_url":   "https://ds.iris.edu/mda/IM/",
    },
    # ------------------------------------------------------------------
    # HA04 — Crozet Islands, France (Île de la Possession)
    # Coordinates: treaty-approximate (CTBT Annex 1 Table 1-B)
    # Depth: ~1000 m SOFAR axis in the southern Indian Ocean
    # ------------------------------------------------------------------
    {
        "station_id":   "ims:HA04",
        "source":       "ims",
        "name":         "Crozet Islands (HA04)",
        "operator":     "CTBTO Preparatory Commission",
        "lat":          -46.45,
        "lon":          51.88,
        "depth_m":      1000.0,
        "deploy_start": date(2004, 1, 1),
        "deploy_end":   None,
        "model":        "Triplet hydrophone array (SOFAR axis)",
        "hz_range_lo":  1.0,
        "hz_range_hi":  100.0,
        "portal_url":   "https://ds.iris.edu/mda/IM/",
    },
    # ------------------------------------------------------------------
    # HA05 — Guadeloupe, France (T-phase)
    # Coordinates: treaty-approximate (~16.2°N 61.8°W, eastern Caribbean)
    # Shore-based seismometer on steep volcanic slope
    # ------------------------------------------------------------------
    {
        "station_id":   "ims:HA05",
        "source":       "ims",
        "name":         "Guadeloupe (HA05)",
        "operator":     "CTBTO Preparatory Commission",
        "lat":          16.20,
        "lon":          -61.80,
        "depth_m":      0.0,
        "deploy_start": date(2005, 1, 1),
        "deploy_end":   None,
        "model":        "Shore-based T-phase seismometer",
        "hz_range_lo":  0.01,
        "hz_range_hi":  10.0,
        "portal_url":   "https://ds.iris.edu/mda/IM/",
    },
    # ------------------------------------------------------------------
    # HA06 — Socorro Island, Mexico (T-phase)
    # Coordinates: Revillagigedo Islands; Socorro ~18.78°N 110.92°W
    # Confirmed T-phase from CTBTO station profile ("T-phase facilities")
    # ------------------------------------------------------------------
    {
        "station_id":   "ims:HA06",
        "source":       "ims",
        "name":         "Socorro Island (HA06)",
        "operator":     "CTBTO Preparatory Commission",
        "lat":          18.78,
        "lon":          -110.92,
        "depth_m":      0.0,
        "deploy_start": date(2006, 1, 1),
        "deploy_end":   None,
        "model":        "Shore-based T-phase seismometer",
        "hz_range_lo":  0.01,
        "hz_range_hi":  10.0,
        "portal_url":   "https://ds.iris.edu/mda/IM/",
    },
    # ------------------------------------------------------------------
    # HA07 — Flores, Portugal (Azores) (T-phase)
    # Coordinates: Flores Island, westernmost of Azores (~39.42°N 31.13°W)
    # Shore-based seismometer on steep volcanic island slope
    # ------------------------------------------------------------------
    {
        "station_id":   "ims:HA07",
        "source":       "ims",
        "name":         "Flores, Azores (HA07)",
        "operator":     "CTBTO Preparatory Commission",
        "lat":          39.42,
        "lon":          -31.13,
        "depth_m":      0.0,
        "deploy_start": date(2005, 1, 1),
        "deploy_end":   None,
        "model":        "Shore-based T-phase seismometer",
        "hz_range_lo":  0.01,
        "hz_range_hi":  10.0,
        "portal_url":   "https://ds.iris.edu/mda/IM/",
    },
    # ------------------------------------------------------------------
    # HA08 — BIOT/Chagos Archipelago, UK (Diego Garcia)
    # Coordinates: IRIS IM H08N1/N2/N3 North-array centroid (verified 2026-05-11)
    # Depth: mean of H08N1-N3 absolute depths (South array at ~72.48°E, 1376 m avg)
    # ------------------------------------------------------------------
    {
        "station_id":   "ims:HA08",
        "source":       "ims",
        "name":         "Diego Garcia / BIOT (HA08)",
        "operator":     "CTBTO Preparatory Commission",
        "lat":          -6.3375,
        "lon":          71.0021,
        "depth_m":      1224.0,
        "deploy_start": date(2002, 1, 17),
        "deploy_end":   None,
        "model":        "Triplet hydrophone array (SOFAR axis)",
        "hz_range_lo":  1.0,
        "hz_range_hi":  100.0,
        "portal_url":   "https://ds.iris.edu/mda/IM/H08N1",
    },
    # ------------------------------------------------------------------
    # HA09 — Tristan da Cunha, UK (T-phase)
    # Coordinates: IRIS IM H09N1 (-37.068111, -12.31523) — verified 2026-05-11
    # Shore-based seismic station; commissioned 2004-03-17 per IRIS
    # ------------------------------------------------------------------
    {
        "station_id":   "ims:HA09",
        "source":       "ims",
        "name":         "Tristan da Cunha (HA09)",
        "operator":     "CTBTO Preparatory Commission",
        "lat":          -37.0681,
        "lon":          -12.3152,
        "depth_m":      0.0,
        "deploy_start": date(2004, 3, 17),
        "deploy_end":   None,
        "model":        "Shore-based T-phase seismometer",
        "hz_range_lo":  0.01,
        "hz_range_hi":  10.0,
        "portal_url":   "https://ds.iris.edu/mda/IM/H09N1",
    },
    # ------------------------------------------------------------------
    # HA10 — Ascension Island, UK
    # Coordinates: IRIS IM H10N1/N2/N3 North-array centroid (verified 2026-05-11)
    # Depth: mean of H10N1-N3 absolute depths (South array ~860 m at ~8.95°S)
    # ------------------------------------------------------------------
    {
        "station_id":   "ims:HA10",
        "source":       "ims",
        "name":         "Ascension Island (HA10)",
        "operator":     "CTBTO Preparatory Commission",
        "lat":          -7.8381,
        "lon":          -14.4898,
        "depth_m":      847.0,
        "deploy_start": date(2004, 9, 14),
        "deploy_end":   None,
        "model":        "Triplet hydrophone array (SOFAR axis)",
        "hz_range_lo":  1.0,
        "hz_range_hi":  100.0,
        "portal_url":   "https://ds.iris.edu/mda/IM/H10N1",
    },
    # ------------------------------------------------------------------
    # HA11 — Wake Island, USA
    # Coordinates: IRIS IM H11N1/N2/N3 North-array centroid (verified 2026-05-11)
    # Depth: mean of H11N1-N3 absolute depths (South array ~739 m at ~18.50°N)
    # ------------------------------------------------------------------
    {
        "station_id":   "ims:HA11",
        "source":       "ims",
        "name":         "Wake Island (HA11)",
        "operator":     "CTBTO Preparatory Commission",
        "lat":          19.7205,
        "lon":          166.8996,
        "depth_m":      731.0,
        "deploy_start": date(2007, 2, 12),
        "deploy_end":   None,
        "model":        "Triplet hydrophone array (SOFAR axis)",
        "hz_range_lo":  1.0,
        "hz_range_hi":  100.0,
        "portal_url":   "https://ds.iris.edu/mda/IM/H11N1",
    },
]


# Station positions are public-domain treaty disclosures (CTBT Protocol,
# Annex 1, Table 1-B); the IRIS-sourced coordinates come from the open FDSN
# station service. No licence restriction applies to the station metadata —
# only the raw waveforms are treaty-restricted (handled by fetch_ims_soundscape).
_LICENSE = "Public domain (CTBT treaty disclosure)"


async def fetch_ims_stations() -> list[dict[str, Any]]:
    """Return all 11 CTBTO IMS hydroacoustic station records.

    Coordinates for 5 stations (HA01, HA08, HA09, HA10, HA11) are verified from
    the IRIS FDSN IM-network station feed.  The remaining 6 stations use
    treaty-approximate positions from CTBT Annex 1 / open seismology literature.
    No live network calls are made.
    """
    log.info("fetch_ims_stations: returning %d hardcoded stations", len(_STATIONS))
    return [dict(s, license=_LICENSE) for s in _STATIONS]


async def fetch_ims_soundscape(station_id: str, days: int = 90) -> list[dict[str, Any]]:
    """Return [] — waveform data is treaty-restricted (vDEC accounts only).

    CTBTO IMS hydroacoustic waveforms and decoded SPL time series are only
    available to credentialed scientists through the Virtual Data Exploitation
    Centre (vDEC).  No public soundscape API exists.  Same Phase-1
    empty-state pattern as HAUSGARTEN / PALAOA / OOI / IMOS / MARS.
    """
    return []
