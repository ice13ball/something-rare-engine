# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""Pure positional CSV parser for the AOC2025 POC dataset —
doi:10.48457/IOPAN.2026.571, CC-BY 4.0, IO PAN GeoNetwork/OPeNDAP.

"Particulate organic carbon concentrations in water samples collected in the
Greenland Sea, during Atlantic-Arctic Ocean Change cruise (AOC2025) between
19-31 May 2025." Confirmed on the download of 2026-09-25: 94 data rows, 32
stations, 15 columns, comma-separated with a quoted header carrying each
column's OPeNDAP type suffix (e.g. `"SDN:P01::CORGCAP1<Float32>"`).

⛔ Known source defects — shown honestly, never silently "fixed":
  1. The ISO XML metadata's temporal extent (2024-07-24..2024-08-09) does not
     match the title or the data (May 2025). This module uses the dates IN
     THE DATA; the discrepancy is surfaced in the panel/legend, not here.
  2. The CSV carries no unit for POC/PN. The dataset abstract states `mg dm-3`
     for both — see POC_PN_UNIT below. It is NOT a value read from the file.

⛔ Units not stated anywhere in the CSV are resolved from the SeaDataNet P01
vocabulary, one entry per name, cited at the constant that uses it — never
invented, never silently assumed.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime

DOI = "10.48457/IOPAN.2026.571"
SOURCE_URL = "https://opendap.iopan.pl/opendap/data/csv/SeaQuester/AOC2025/2025_AOC_POC.csv"
METADATA_URL = ("https://geonetwork.iopan.pl/geonetwork/srv/eng/catalog.search#/metadata/"
                "a5efb78a-cc02-4839-9c94-18730e470eb4")

#: Abstract text (ISO XML, gmd:abstract), verbatim unit clause. Not present anywhere
#: in the CSV — a column named "_mg_dm3" would otherwise be an unsupported claim.
POC_PN_UNIT = "mg dm-3 (from the dataset abstract; not in the data file)"

#: https://vocab.nerc.ac.uk/collection/P01/current/PRESPR01/ — "Pressure (spatial
#: coordinate) exerted by the water body by profiling pressure sensor and
#: correction to read zero at sea level" — decibar (SeaDataNet P06 code UPDB).
PRESPR01_UNIT = "db (SeaDataNet P01 PRESPR01, profiling pressure sensor)"

#: https://vocab.nerc.ac.uk/collection/P01/current/D13CMOP11/ — "Stable carbon
#: isotope ratio of particulate organic matter" — per mil (P06 code UPMM).
D13C_UNIT = "‰ (SeaDataNet P01 D13CMOP11)"

#: https://vocab.nerc.ac.uk/collection/P01/current/D15NEAM1/ — "Stable nitrogen
#: isotope ratio of particulate organic matter" — per mil (P06 code UPMM).
D15N_UNIT = "‰ (SeaDataNet P01 D15NEAM1)"


class Aoc2025PocFormatError(ValueError):
    """The header (or a value the parser cannot make sense of) does not match
    what was confirmed on the download of 2026-09-25. Refuses to guess."""


#: Literal header cells, in position order, exactly as the source publishes
#: them (quotes stripped, type suffix included). A changed column name, order
#: or declared type refuses the sync rather than silently reading a shifted
#: column. This is the header-guard sabotage target: mutate CORGCAP1 here (or
#: patch the header in a test) and every parser test should go red.
EXPECTED_HEADER: tuple[str, ...] = (
    "Cruise-ID<String>",
    "Station<String>",
    "Date<String>",
    "Latitude<Float32>",
    "Longitude<Float32>",
    "SDN:P01::PRESPR01<Float32>",
    "Pressure_(db)<Float32>",
    "Activity<String>",
    "Sample_ID<String>",
    "Salinity<Float32>",
    "Temperature_[deg._C]<Float32>",
    "SDN:P01::D15NEAM1<Float32>",
    "SDN:P01::D13CMOP11<Float32>",
    "SDN:P01::CORGCAP1<Float32>",
    "SDN:P01::NTOTCAP1<Float32>",
)

#: DB column name, python type tag) for each header position, in order.
COLUMNS: tuple[tuple[str, str], ...] = (
    ("cruise_id", "text"),
    ("station", "text"),
    ("sample_date", "datetime"),
    ("lat", "float"),
    ("lon", "float"),
    ("prespr01_db", "float"),
    ("pressure_db", "float"),
    ("activity", "text"),
    ("sample_id", "text"),
    ("salinity", "float"),
    ("temp_c", "float"),
    ("d15n_permil", "float"),
    ("d13c_permil", "float"),
    ("poc_mg_dm3", "float"),
    ("pn_mg_dm3", "float"),
)
FIELDS: tuple[str, ...] = tuple(name for name, _ in COLUMNS)


@dataclass(frozen=True)
class Aoc2025PocFile:
    header: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]


def parse_csv(raw: bytes) -> Aoc2025PocFile:
    """Split the whole CSV into a validated header and the data rows. Refuses
    (raises Aoc2025PocFormatError) on a header that does not match
    EXPECTED_HEADER cell-for-cell, or a row with the wrong cell count."""
    text = raw.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    try:
        header = tuple(next(reader))
    except StopIteration:
        raise Aoc2025PocFormatError("empty file - no header row") from None
    if header != EXPECTED_HEADER:
        raise Aoc2025PocFormatError(
            f"header mismatch - refusing to guess column positions. "
            f"expected {EXPECTED_HEADER!r}, got {header!r}")
    rows: list[tuple[str, ...]] = []
    for row in reader:
        if not row:
            continue
        if len(row) != len(EXPECTED_HEADER):
            raise Aoc2025PocFormatError(
                f"row {len(rows) + 1} has {len(row)} cells, expected {len(EXPECTED_HEADER)}: {row!r}")
        rows.append(tuple(row))
    return Aoc2025PocFile(header=header, rows=tuple(rows))


def _to_float(cell: str) -> float | None:
    cell = cell.strip()
    return None if cell == "" else float(cell)


def _to_text(cell: str) -> str | None:
    cell = cell.strip()
    return cell or None


def _to_datetime(cell: str) -> datetime | None:
    cell = cell.strip()
    if not cell:
        return None
    # Source publishes ISO UTC, e.g. "2025-05-19T04:30:00Z".
    return datetime.fromisoformat(cell.replace("Z", "+00:00"))


_CONVERTERS = {"text": _to_text, "float": _to_float, "datetime": _to_datetime}


def parse_row(row_no: int, cells: tuple[str, ...]) -> dict:
    """One CSV row -> a dict of typed DB columns plus `row_no` and `raw` (every
    cell verbatim, in source order). Undated is not possible in this source (Date
    is never empty in the confirmed download), but a blank cell still yields
    `sample_date: None` rather than a substituted date, matching every other
    layer's undated convention."""
    if len(cells) != len(COLUMNS):
        raise Aoc2025PocFormatError(f"row {row_no}: {len(cells)} cells, expected {len(COLUMNS)}")
    rec: dict = {"row_no": row_no, "raw": list(cells)}
    for (name, kind), cell in zip(COLUMNS, cells):
        rec[name] = _CONVERTERS[kind](cell)
    return rec


def is_mappable(rec: dict) -> bool:
    return rec.get("lat") is not None and rec.get("lon") is not None


def observation_window(rows: list[dict]) -> tuple[date | None, date | None]:
    """min/max sample_date across parsed rows, as dates (source carries time-of-day
    too, but the panel/legend describe an observation WINDOW, not a timestamp)."""
    dts = [r["sample_date"].date() for r in rows if r.get("sample_date") is not None]
    if not dts:
        return None, None
    return min(dts), max(dts)
