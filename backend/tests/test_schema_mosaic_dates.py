# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import pathlib, re

SCHEMA = pathlib.Path(__file__).resolve().parents[1] / "schema" / "arctic.py"

NEW_COLUMNS = [
    ("sampling_date", "DATE"),
    ("sampling_month", "SMALLINT"),
    ("sampling_day", "SMALLINT"),
    ("campaign_name", "TEXT"),
    ("campaign_start", "DATE"),
    ("campaign_end", "DATE"),
    ("core_comment", "TEXT"),
    ("date_precision", "TEXT"),
]

def test_create_block_declares_every_new_column():
    """A fresh environment gets its columns from the CREATE block."""
    src = SCHEMA.read_text(encoding="utf-8")
    for name, typ in NEW_COLUMNS:
        assert re.search(rf"\b{name}\s+{typ}\b", src), f"{name} missing from the CREATE block"

def test_every_new_column_also_has_an_add_column_guard():
    """CREATE TABLE IF NOT EXISTS is a no-op on the existing production table.
    Without an ALTER, production never gets the column and the ingest fails on
    the first write."""
    src = SCHEMA.read_text(encoding="utf-8")
    for name, typ in NEW_COLUMNS:
        assert re.search(
            rf"ALTER TABLE mosaic_cores ADD COLUMN IF NOT EXISTS {name} {typ}", src
        ), f"{name} has no ADD COLUMN IF NOT EXISTS guard"
