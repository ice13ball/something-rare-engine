# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""Pure positional parser for Greenland Sea primary production 2021-2022 —
PANGAEA doi:10.1594/PANGAEA.965985, CC-BY-4.0.

Confirmed on the download of 2026-09-25 (sha256 0ae42f5e…cebad9): 12 rows x 6
columns, 12 data points. No depth column, no QC column.
⛔ `GPP C [mg/m**2/day]` is an AREAL RATE (carbon fixed under one square metre per
day), never a concentration.
"""
from __future__ import annotations

from ingestion import pangaea_tsv

DOI = "10.1594/PANGAEA.965985"
TEXTFILE_URL = f"https://doi.pangaea.de/{DOI}?format=textfile"
JSONLD_URL = f"https://doi.pangaea.de/{DOI}?format=metadata_jsonld"

EXPECTED_HEADER: tuple[str, ...] = (
    "Event", "Event 2", "Latitude", "Longitude", "Date/Time", "GPP C [mg/m**2/day]",
)
COLUMNS: tuple[tuple[str, str], ...] = (
    ("event", "text"), ("event_2", "text"), ("lat", "float"), ("lon", "float"),
    ("sample_date", "date"), ("gpp_c_mg_m2_day", "float"),
)
FIELDS: tuple[str, ...] = tuple(name for name, _ in COLUMNS)
#: Only GPP counts as a data point (Size: 12 for 12 rows).
DATA_POINT_POSITIONS: frozenset[int] = frozenset({5})


def parse_row(row_no: int, cells: tuple[str, ...]) -> dict:
    return pangaea_tsv.parse_row(COLUMNS, EXPECTED_HEADER, row_no, cells)


def is_mappable(rec: dict) -> bool:
    return pangaea_tsv.is_mappable(rec)
