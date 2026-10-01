# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""Pure positional CSV parser for the Svalbard fjords primary-production
preview dataset — IO PAN GeoNetwork 5a2ef3d9-02ea-4b9c-acef-10e9b1968458,
doi:10.48457/iopan-2024-198. © IO PAN, used with permission (no open licence
is published for this record).

"In situ primary production, Kongsfjorden & Hornsund (Svalbard), 1994-2019."
Confirmed on the downloaded copy: 369 data rows, 45 expositions (`No`), 43
distinct positions, 29 named stations, 14 columns, comma-separated with a
quoted header carrying each column's OPeNDAP type suffix.

⛔ Known source facts — shown honestly, never silently "fixed" or hidden:
  1. `Pi_[mgC_m-2_day-1]` is the DAILY WATER-COLUMN-INTEGRATED production of the
     whole profile (exposition), not a per-depth measurement. The source writes
     it exactly once per exposition, on the shallowest row. This module verifies
     that placement and raises SvalbardFjordsPpFormatError if it is ever
     violated — never guesses which row "should" carry it.
  2. `Ca_[mg_m-3]` is not defined anywhere in the record. In primary-production
     data this usually denotes chlorophyll a — see CA_NOTE below, never
     asserted as fact.
  3. `Salinity` is published without a unit, and none is supplied here; the
     `water_mass` codes (SW/IW/LW/AW/TAW) are not defined in
     the record either — see WATER_MASS_EXPANSIONS, cited to Cottier et al.
     2005, never invented.
  4. The SAME station name is sometimes sampled at different coordinates in
     different years (e.g. K2 at 78.97/11.74 and 78.88/12.48) — 29 named
     stations but 43 distinct positions. Positions are never merged by name.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime

DOI = "10.48457/iopan-2024-198"
SOURCE_URL = ("https://opendap.iopan.pl/opendap/data/csv/"
              "Primary_production_in_Kongsfjorden_and_Hornsund_in_the_period_1994-2019.csv")
METADATA_URL = ("https://geonetwork.iopan.pl/geonetwork/srv/api/records/"
                "5a2ef3d9-02ea-4b9c-acef-10e9b1968458/formatters/xml")

#: The record declares only `copyright` — no open licence. Served at IO PAN's
#: request; IO PAN is to assign the licence in eCUDO. Never write "CC-BY" for
#: this layer.
LICENCE = ("© Institute of Oceanology PAS (IO PAN). Used with permission; "
           "the source publishes no open licence.")

#: Not a value read from the file — `Ca_[mg_m-3]` is undefined in the record.
CA_NOTE = ("Not defined in the source record; in primary-production data this "
           "usually denotes chlorophyll a.")

#: Cottier, F. et al. (2005), "Water mass modification in an Arctic fjord
#: through cross-shelf exchange: The seasonal hydrography of Kongsfjorden,
#: Svalbard" — the standard Svalbard-fjord water-mass classification. Not
#: defined in this record; shown with that attribution, never invented.
WATER_MASS_EXPANSIONS: dict[str, str] = {
    "AW": "Atlantic Water",
    "TAW": "Transformed Atlantic Water",
    "IW": "Intermediate Water",
    "SW": "Surface Water",
    "LW": "Local Water",
}
WATER_MASS_ATTRIBUTION = "Cottier et al. 2005, standard Svalbard fjord classification"

REGION_NAMES: dict[str, str] = {"K": "Kongsfjorden", "H": "Hornsund"}


class SvalbardFjordsPpFormatError(ValueError):
    """The header (or a value/placement the parser cannot make sense of) does
    not match what was confirmed on the downloaded copy. Refuses to guess."""


#: Literal header cells, in position order, exactly as the source publishes
#: them (quotes stripped, type suffix included). This is the header-guard
#: sabotage target: mutate a cell here (or in a test) and every parser test
#: should go red.
EXPECTED_HEADER: tuple[str, ...] = (
    "No<Float32>",
    "Data<String>",
    "rejon<String>",
    "part<String>",
    "station<String>",
    "Latitude<Float32>",
    "Longitude<Float32>",
    "z_[m]<Float32>",
    "Temperature[degC]<Float32>",
    "Salinity<Float32>",
    "Ca_[mg_m-3]<Float32>",
    "Pe_[mgC_m-3_h-1]<Float32>",
    "Pi_[mgC_m-2_day-1]<Float32>",
    "water_mass<String>",
)

#: (DB column name, python type tag) for each header position, in order.
COLUMNS: tuple[tuple[str, str], ...] = (
    ("exposition_no", "text"),
    ("sample_date", "ddmmyyyy"),
    ("region_code", "text"),
    ("fjord_part", "text"),
    ("station", "text"),
    ("lat", "float"),
    ("lon", "float"),
    ("depth_m", "float"),
    ("temperature_degc", "float"),
    ("salinity", "float"),
    ("ca_mg_m3", "float"),
    ("pe_mgc_m3_h", "float"),
    ("pi_mgc_m2_day", "float"),
    ("water_mass", "text"),
)
FIELDS: tuple[str, ...] = tuple(name for name, _ in COLUMNS)


@dataclass(frozen=True)
class SvalbardFjordsPpFile:
    header: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]


def parse_csv(raw: bytes) -> SvalbardFjordsPpFile:
    """Split the whole CSV into a validated header and the data rows. Refuses
    (raises SvalbardFjordsPpFormatError) on a header that does not match
    EXPECTED_HEADER cell-for-cell, or a row with the wrong cell count."""
    text = raw.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    try:
        header = tuple(next(reader))
    except StopIteration:
        raise SvalbardFjordsPpFormatError("empty file - no header row") from None
    if header != EXPECTED_HEADER:
        raise SvalbardFjordsPpFormatError(
            f"header mismatch - refusing to guess column positions. "
            f"expected {EXPECTED_HEADER!r}, got {header!r}")
    rows: list[tuple[str, ...]] = []
    for row in reader:
        if not row:
            continue
        if len(row) != len(EXPECTED_HEADER):
            raise SvalbardFjordsPpFormatError(
                f"row {len(rows) + 1} has {len(row)} cells, expected {len(EXPECTED_HEADER)}: {row!r}")
        rows.append(tuple(row))
    return SvalbardFjordsPpFile(header=header, rows=tuple(rows))


def _to_float(cell: str) -> float | None:
    cell = cell.strip()
    return None if cell == "" else float(cell)


def _to_text(cell: str) -> str | None:
    cell = cell.strip()
    return cell or None


def _to_ddmmyyyy(cell: str) -> date | None:
    cell = cell.strip()
    if not cell:
        return None
    # Source publishes dd.mm.yyyy, no time, no timezone.
    return datetime.strptime(cell, "%d.%m.%Y").date()


_CONVERTERS = {"text": _to_text, "float": _to_float, "ddmmyyyy": _to_ddmmyyyy}


def parse_row(row_no: int, cells: tuple[str, ...]) -> dict:
    """One CSV row -> a dict of typed DB columns plus `row_no` and `raw` (every
    cell verbatim, in source order). A missing value is None, never 0 —
    depth_m 0 is a real surface sample."""
    if len(cells) != len(COLUMNS):
        raise SvalbardFjordsPpFormatError(f"row {row_no}: {len(cells)} cells, expected {len(COLUMNS)}")
    rec: dict = {"row_no": row_no, "raw": list(cells)}
    for (name, kind), cell in zip(COLUMNS, cells):
        rec[name] = _CONVERTERS[kind](cell)
    return rec


def position_id(rec: dict) -> str:
    """Lookup key is a string built from the source's OWN text, never floats —
    'K2' sampled at two different coordinate sets in different years must not
    collide or be merged."""
    return f"{rec['region_code']}:{rec['station']}:{rec['raw'][5]}:{rec['raw'][6]}"


def group_by_exposition(records: list[dict]) -> dict[str, list[dict]]:
    """`No` groups the rows of one incubation profile (one station visit on one
    date), ordered by depth."""
    groups: dict[str, list[dict]] = {}
    for rec in records:
        groups.setdefault(rec["exposition_no"], []).append(rec)
    for no, recs in groups.items():
        recs.sort(key=lambda r: (r["depth_m"] is None, r["depth_m"]))
    return groups


def validate_pi_placement(records: list[dict]) -> None:
    """Pi belongs to the EXPOSITION, not to a depth: the source writes it at
    most once per exposition, and only on its shallowest row. Raises
    SvalbardFjordsPpFormatError if that is ever violated — never guesses."""
    for no, recs in group_by_exposition(records).items():
        pi_positions = [i for i, r in enumerate(recs) if r["pi_mgc_m2_day"] is not None]
        if not pi_positions:
            continue
        if len(pi_positions) > 1:
            raise SvalbardFjordsPpFormatError(
                f"exposition {no}: Pi present on {len(pi_positions)} rows, expected at most 1")
        if pi_positions != [0]:
            raise SvalbardFjordsPpFormatError(
                f"exposition {no}: Pi present on a row that is not the shallowest")


def observation_window(records: list[dict]) -> tuple[date | None, date | None]:
    dts = [r["sample_date"] for r in records if r.get("sample_date") is not None]
    if not dts:
        return None, None
    return min(dts), max(dts)
