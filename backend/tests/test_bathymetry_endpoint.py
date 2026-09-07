# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

# Pure unit test for _BATHY_TABLES — no DB or app import required.
# Re-declares the map locally so the test is importable on dev without a
# DATABASE_URL (same pattern as task-3 micro-tests).

_BATHY_TABLES = {
    "isa_contract":       ("mining_contracts",    "isa_id"),
    "isa_reserved":       ("reserved_areas",      "arcgis_id"),
    "isa_apei":           ("isa_apeis",           "arcgis_id"),
    "isa_relinquished":   ("relinquished_areas",  "arcgis_id"),
    "offshore_activity":  ("offshore_activities", "id"),
}


def test_bathy_tables_has_all_feature_types():
    expected = {
        "isa_contract",
        "isa_reserved",
        "isa_apei",
        "isa_relinquished",
        "offshore_activity",
    }
    assert set(_BATHY_TABLES.keys()) == expected


def test_bathy_tables_correct_mappings():
    assert _BATHY_TABLES["isa_contract"]      == ("mining_contracts",    "isa_id")
    assert _BATHY_TABLES["isa_reserved"]      == ("reserved_areas",      "arcgis_id")
    assert _BATHY_TABLES["isa_apei"]          == ("isa_apeis",           "arcgis_id")
    assert _BATHY_TABLES["isa_relinquished"]  == ("relinquished_areas",  "arcgis_id")
    assert _BATHY_TABLES["offshore_activity"] == ("offshore_activities", "id")


def test_bathy_tables_no_extra_keys():
    assert len(_BATHY_TABLES) == 5
