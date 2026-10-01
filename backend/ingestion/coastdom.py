# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""Pure positional parser for CoastDOM v1 — PANGAEA doi:10.1594/PANGAEA.964012, CC-BY-4.0.

Confirmed on the download of 2026-09-25 (sha256 76f550dd…fe129e): 70,823 rows x 49
columns, 1,286,555 data points, dates YYYY-MM-DD 1978-05-25..2022-03-02.

The header repeats names — `Analyt method (…)` x6, `Reference (…)` x3, `PI (…)` x2 —
so columns are resolved by POSITION against EXPECTED_HEADER and any header that
differs in one character is refused.

⚠️ The 531 undated rows are location-only lines: 518 read "Inorganic nutrients data
may be available", 13 "Chesapeake Bay to Middle Atlantic", each followed by a row
whose location continues the text ("Bight"). They are stored like every other row —
storage is 1:1 — and are never drawn. One more row (Parker River) has a latitude and
no longitude: 532 unmappable rows in total.
"""
from __future__ import annotations

from ingestion import pangaea_tsv

DOI = "10.1594/PANGAEA.964012"
TEXTFILE_URL = f"https://doi.pangaea.de/{DOI}?format=textfile"
JSONLD_URL = f"https://doi.pangaea.de/{DOI}?format=metadata_jsonld"

#: Byte-exact header. µ is MICRO SIGN, ° DEGREE SIGN — as the source writes them.
EXPECTED_HEADER: tuple[str, ...] = (
    "Location (Name of location where sample...)",
    "Sample ID (ID of the sample provided by ...)",
    "Date/Time",
    "Latitude",
    "Longitude",
    "Elevation [m a.s.l.]",
    "Depth water [m]",
    "Temp [°C]",
    "Sal",
    "TSS [mg/l]",
    "Chl a [µg/l]",
    "QF chl a",
    "[NO3]- + [NO2]- [µmol/l]",
    "QF [NO3]- + [NO2]-",
    "[NH4]+ [µmol/l]",
    "QF [NH4]+",
    "[HPO4]2- [µmol/l] (Soluble reactive phosphorus c...)",
    "QF [HPO4]2-",
    "DOC [µmol/l]",
    "Analyt method (Method used to measure dissol...)",
    "QF DOC",
    "DON [µmol/l]",
    "TDN [µmol/l]",
    "Analyt method (Method used to measure total ...)",
    "QF TDN",
    "DOP [µmol/l]",
    "TDP [µmol/l]",
    "Analyt method (Method used to measure total ...)",
    "QF TDP",
    "POC [µmol/l]",
    "Analyt method (Method used to measure partic...)",
    "QF POC",
    "PN [µmol/l]",
    "Analyt method (Method used to measure partic...)",
    "QF TPN",
    "PP [µmol/l]",
    "Analyt method (Method used to measure partic...)",
    "QF PP",
    "DIC [µmol/kg]",
    "QF DIC",
    "AT [µmol/kg]",
    "QF AT",
    "PI (Name of the person responsibl...)",
    "Institution (Name of the instittue respons...)",
    "PI (Email contact of the person r...)",
    "Reference (Potential publications where ...)",
    "Reference (Potential publications where ...)",
    "Reference (Potential publications where ...)",
    "Comment (Add any additional neccesary ...)",
)

#: (database column, kind) per source position. Names carry the unit of the
#: header at the same position; the QF after PN is `QF TPN` in the source and
#: keeps that name.
COLUMNS: tuple[tuple[str, str], ...] = (
    ("location", "text"), ("sample_id", "text"), ("sample_date", "date"),
    ("lat", "float"), ("lon", "float"), ("elevation_m", "float"), ("depth_m", "float"),
    ("temp_c", "float"), ("sal", "float"), ("tss_mg_l", "float"),
    ("chl_a_ug_l", "float"), ("qf_chl_a", "flag"),
    ("no3_no2_umol_l", "float"), ("qf_no3_no2", "flag"),
    ("nh4_umol_l", "float"), ("qf_nh4", "flag"),
    ("hpo4_umol_l", "float"), ("qf_hpo4", "flag"),
    ("doc_umol_l", "float"), ("doc_method", "text"), ("qf_doc", "flag"),
    ("don_umol_l", "float"),
    ("tdn_umol_l", "float"), ("tdn_method", "text"), ("qf_tdn", "flag"),
    ("dop_umol_l", "float"),
    ("tdp_umol_l", "float"), ("tdp_method", "text"), ("qf_tdp", "flag"),
    ("poc_umol_l", "float"), ("poc_method", "text"), ("qf_poc", "flag"),
    ("pn_umol_l", "float"), ("pn_method", "text"), ("qf_tpn", "flag"),
    ("pp_umol_l", "float"), ("pp_method", "text"), ("qf_pp", "flag"),
    ("dic_umol_kg", "float"), ("qf_dic", "flag"),
    ("at_umol_kg", "float"), ("qf_at", "flag"),
    ("pi", "text"), ("institution", "text"), ("pi_email", "text"),
    ("ref_1", "text"), ("ref_2", "text"), ("ref_3", "text"), ("comment", "text"),
)
FIELDS: tuple[str, ...] = tuple(name for name, _ in COLUMNS)

#: Positions PANGAEA counts as data points: everything except the geocodes
#: (Date/Time, Latitude, Longitude, Elevation, Depth water). Verified: 1,286,555.
DATA_POINT_POSITIONS: frozenset[int] = frozenset(range(49)) - {2, 3, 4, 5, 6}


def parse_row(row_no: int, cells: tuple[str, ...]) -> dict:
    return pangaea_tsv.parse_row(COLUMNS, EXPECTED_HEADER, row_no, cells)


def is_mappable(rec: dict) -> bool:
    return pangaea_tsv.is_mappable(rec)
