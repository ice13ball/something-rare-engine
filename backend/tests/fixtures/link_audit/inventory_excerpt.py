# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

_INVENTORY: list[tuple[str, str, str, str, str | None, str, str]] = [
    ("obis",           "OBIS deep-sea occurrences",     "ocean-bio", "biodiversity_hotspots",  "biodiversity_hotspots", "OBIS / UNESCO-IOC",                       "https://obis.org/"),
    ("vents",          "Hydrothermal vents",            "ocean-bio", "hydrothermal_vents",     "hydrothermal_vents",    "InterRidge / PANGAEA",                    "https://doi.org/10.1594/PANGAEA.917894"),
    ("onc-locations",  "ONC observatory locations",     "ocean-bio", "onc_locations",          "onc-sensors",           "Ocean Networks Canada",                   "https://www.oceannetworks.ca/"),
    # Real 4-line entry, copied byte-for-byte from backend/main.py:15509-15512.
    # A real _INVENTORY tuple can span multiple physical lines — this fixture
    # exists so extract_inventory() is never allowed to regress to assuming
    # one tuple == one line.
    ("acoustic-stations", "Hydrophone stations from observatory networks", "ocean-monitoring",
     "acoustic_stations", "acoustic-stations",
     "OOI + IMOS + MBARI MARS",
     "https://oceanobservatories.org/"),
]
