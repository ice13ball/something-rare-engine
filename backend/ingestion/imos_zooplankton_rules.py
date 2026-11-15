# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Pure constants of the imos-zooplankton layer, shared by the one-shot import and the API.

No imports beyond the standard library: the API reads this module, never the importer (which pulls in asyncpg
and the schema package), so a failed import cannot 503 the endpoints.
"""
from __future__ import annotations

import re

SOURCE = "imos-zooplankton"
LICENCE = "CC BY 4.0"
LICENCE_URL = "https://creativecommons.org/licenses/by/4.0/"
# The attribution the data provider requires, verbatim.
ATTRIBUTION = ("Data was sourced from Australia’s Integrated Marine Observing System (IMOS) – IMOS is enabled by "
               "the National Collaborative Research Infrastructure strategy (NCRIS).")
ATTRIBUTION_CPR = ("AusCPR: CSIRO and the Australian Continuous Plankton Recorder survey, towed from ships of "
                   "opportunity.")
# AODN catalogue records of the two datasets (licence confirmed there).
SOURCE_RECORDS = (
    "https://catalogue-imos.aodn.org.au/geonetwork/srv/eng/catalog.search#/metadata/bf287dfe-9ce4-4969-9c59-51c39ea4d011",
    "https://catalogue-imos.aodn.org.au/geonetwork/srv/eng/catalog.search#/metadata/c13451a9-7cfc-091c-e044-00144f7bc0f4",
)

# 'cpr:<Sample_ID>' (AusCPR) or 'nrs:<TripCode>' (National Reference Stations). The importer refuses a key that
# does not match, the API answers 422 for a malformed one and 404 for a well-formed unknown one.
SAMPLE_KEY_RE = re.compile(r"^(cpr|nrs):[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
KEY_PREFIX = {"auscpr": "cpr:", "nrs": "nrs:"}

# Does the programme's NON-COPEPOD file record counted absences as zeros? Fixed per programme, measured on the
# 15.11.2026 export: AusCPR 206,567 zero cells of ~278 k (yes); NRS 1 zero cell of 66,655 (no: it lists present taxa
# only, the single 0 is a rounding of a present count). A rule like "any zero cell" flipped NRS to true on that one
# cell. The importer aborts when a file's zero share contradicts this table (data changed shape: re-evaluate).
NONCOPEPOD_ZEROS_EXPLICIT = {"auscpr": True, "nrs": False}
NONCOPEPOD_ZERO_SHARE_EXPLICIT_MIN = 0.20   # explicit-zero files: at least this share of cells is 0
NONCOPEPOD_ZERO_SHARE_IMPLICIT_MAX = 0.01   # present-only files: at most this share
