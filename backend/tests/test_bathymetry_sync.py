# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Micro-test: verify _BATHY_SETS shape without importing main.py (heavy VPS-only deps)."""

# Redeclare the constant exactly as in main.py so the test is standalone.
_BATHY_SETS = [
    ("isa_contract",      "mining_contracts",    "isa_id"),
    ("isa_reserved",      "reserved_areas",      "arcgis_id"),
    ("isa_apei",          "isa_apeis",           "arcgis_id"),
    ("isa_relinquished",  "relinquished_areas",  "arcgis_id"),
    ("offshore_activity", "offshore_activities", "id"),
]


def test_bathy_sets_has_five_entries():
    assert len(_BATHY_SETS) == 5


def test_bathy_sets_feature_types():
    ftypes = [t for t, _, _ in _BATHY_SETS]
    assert ftypes == [
        "isa_contract",
        "isa_reserved",
        "isa_apei",
        "isa_relinquished",
        "offshore_activity",
    ]


def test_bathy_sets_tables():
    tables = [tbl for _, tbl, _ in _BATHY_SETS]
    assert tables == [
        "mining_contracts",
        "reserved_areas",
        "isa_apeis",
        "relinquished_areas",
        "offshore_activities",
    ]


def test_bathy_sets_pks():
    pks = [pk for _, _, pk in _BATHY_SETS]
    assert pks == ["isa_id", "arcgis_id", "arcgis_id", "arcgis_id", "id"]
