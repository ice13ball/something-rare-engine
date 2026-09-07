# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""device_category → ONC deviceCategoryCode, and product selection.

Strings are verbatim from `onc_instruments`; the product entries below are the real
shapes returned by ONC's /dataProducts on 2026-07-10.
"""
import pytest

from backend.ingestion.onc_dataproduct import (
    adcp_device_category_code as dcc,
    pick_product_code,
)

# Verbatim subsets of real /dataProducts responses.
RDI_ENTRIES = [  # RCNE5 / ADCP75KHZ
    {"dataProductCode": "LF", "extension": "txt", "dataProductName": "Log File"},
    {"dataProductCode": "RADCPTS", "extension": "mat", "dataProductName": "RDI ADCP Time Series"},
    {"dataProductCode": "RADCPTS", "extension": "nc", "dataProductName": "RDI ADCP Time Series"},
    {"dataProductCode": "RADCPTS", "extension": "rdi", "dataProductName": "RDI ADCP Time Series"},
    {"dataProductCode": "TSSD", "extension": "csv", "dataProductName": "Time Series Scalar Data"},
]
NORTEK_ENTRIES = [  # BACAX / ADCP2MHZ — offers NTS only, no RADCPTS at all
    {"dataProductCode": "NTS", "extension": "mat", "dataProductName": "Nortek Time Series"},
    {"dataProductCode": "NTS", "extension": "nc", "dataProductName": "Nortek Time Series"},
    {"dataProductCode": "TSSD", "extension": "mat", "dataProductName": "Time Series Scalar Data"},
]
HYDROPHONE_ENTRIES = [
    {"dataProductCode": "HSD", "extension": "mat", "dataProductName": "Hydrophone Spectral Data"},
    {"dataProductCode": "AD", "extension": "wav", "dataProductName": "Audio Data"},
]


@pytest.mark.parametrize(
    "category,expected",
    [
        ("Acoustic Doppler Current Profiler 75 kHz", "ADCP75KHZ"),
        ("Acoustic Doppler Current Profiler 150 kHz", "ADCP150KHZ"),
        ("Acoustic Doppler Current Profiler 300 kHz", "ADCP300KHZ"),
        ("Acoustic Doppler Current Profiler 400 kHz", "ADCP400KHZ"),
        ("Acoustic Doppler Current Profiler 600 kHz", "ADCP600KHZ"),
        ("Acoustic Doppler Current Profiler 2 MHz", "ADCP2MHZ"),
    ],
)
def test_every_live_adcp_category_maps(category, expected):
    """All six categories present in onc_instruments; all 17 locations verified
    to expose RADCPTS/nc on 2026-07-10."""
    assert dcc(category) == expected


def test_current_meter_is_not_an_adcp():
    """The trap: the stored ADCP category contains the words 'Current Profiler',
    so a '%CURRENT%' filter matches plain 'Current Meter' too. The old sync did
    exactly that and fed current meters into an ADCP code path."""
    assert dcc("Current Meter") is None


def test_non_doppler_categories_rejected():
    assert dcc("Conductivity Temperature Depth") is None
    assert dcc("Hydrophone") is None
    assert dcc("") is None


def test_decimal_frequency_is_trimmed():
    assert dcc("Acoustic Doppler Current Profiler 1.0 MHz") == "ADCP1MHZ"
    assert dcc("Acoustic Doppler Current Profiler 1.2 MHz") == "ADCP1.2MHZ"


def test_doppler_without_a_frequency_is_rejected():
    """Better no request than a guessed 'ADCP' code that 400s."""
    assert dcc("Acoustic Doppler Current Profiler") is None


def test_rdi_device_resolves_to_radcpts():
    assert pick_product_code(RDI_ENTRIES) == "RADCPTS"


def test_nortek_device_resolves_to_nts():
    """BACAX/ADCP2MHZ and HRBIP/ADCP400KHZ are Nortek. Ordering RADCPTS from them
    returns HTTP 400 errorCode 127 — the product must be read off /dataProducts,
    never inferred from the instrument frequency."""
    assert pick_product_code(NORTEK_ENTRIES) == "NTS"


def test_device_offering_neither_returns_none():
    assert pick_product_code(HYDROPHONE_ENTRIES) is None
    assert pick_product_code([]) is None


def test_extension_must_match():
    """RADCPTS exists as .mat and .rdi too; we only parse netCDF."""
    assert pick_product_code(RDI_ENTRIES, extension="nc") == "RADCPTS"
    assert pick_product_code(NORTEK_ENTRIES, extension="csv") is None


def test_malformed_entries_do_not_crash():
    assert pick_product_code([None, "junk", {"no": "keys"}]) is None  # type: ignore[list-item]
