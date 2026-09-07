# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

from domains.geochem_sql import MOSAIC_HEX_SQL


def test_hex_sql_aggregates_the_sampling_year():
    """A hex is an aggregate over cores spanning 1900-2022. Returning only a
    count makes a cell holding one 1912 core look like a cell holding five
    from 2019."""
    assert "min(s.sampling_year)" in MOSAIC_HEX_SQL
    assert "max(s.sampling_year)" in MOSAIC_HEX_SQL
    assert "sampling_year IS NULL" in MOSAIC_HEX_SQL, "undated cores are not counted"


def test_hex_payload_declares_every_time_field():
    """The SQL side of the contract; the actual GeoJSON property names come
    from geochem_sql.hex_feature_collection(), exercised end to end by
    test_hex_hist_sql_exec.py."""
    assert "jsonb_object_agg" in MOSAIC_HEX_SQL
    assert "FILTER (WHERE decade IS NOT NULL)" in MOSAIC_HEX_SQL
