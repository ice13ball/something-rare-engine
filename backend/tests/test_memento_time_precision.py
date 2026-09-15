# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""The cast endpoint must return the precision of the date it returns.

MEMENTO's source pads a month-only record to day 01 at midnight. `sample_time`
alone therefore cannot be read: `2009-01-01T00:00` means "the 1st of January"
for some casts and "some time in January" for others, and nothing in the
timestamp separates them. `time_precision` does, and the ingest has filled it
on every row since the layer shipped.

Measured on production 2026-09-15:
    memento_casts    minute 154,550 · month   875  (0.56%)
    memento_samples  minute 211,466 · month 6,805  (3.12%)
    genuinely sampled on day 01 at midnight: 17 casts

⛔ Those 17 are why a frontend heuristic ("day == 01 means padded") is wrong
and this must travel as a field. Sabotage-checked 2026-09-15: replacing the
panel's `time_precision` read with that heuristic turns one frontend test red.

⛔ Structural, like `test_geotraces_station_fields.py`, and for the same
reason: the failure is a mismatch between a SELECT list and a property read,
not a runtime error. A live call would prove it for one cast, while the
database is reachable; this proves it for the contract.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
ROUTER = ROOT / "backend" / "routers" / "spatial_v2.py"
PANEL = (
    ROOT / "frontend" / "src" / "components" / "panels" / "arctic" / "MementoPanel.tsx"
)


def _select_for(table: str) -> str:
    src = ROUTER.read_text(encoding="utf-8")
    m = re.search(rf"SELECT([^\"]*?)FROM {table} WHERE cast_id", src, re.S)
    assert m, f"fixture problem: the {table} SELECT moved or was renamed"
    return m.group(1)


def test_the_panel_really_does_read_the_precision():
    """⛔ The fixture assertion. Without it the two tests below would guard a
    contract nobody consumes — a field selected, serialised and dropped."""
    panel = PANEL.read_text(encoding="utf-8")
    assert 'data.time_precision === "month"' in panel, (
        "MementoPanel no longer distinguishes a month-precision cast, so "
        "selecting the column guards nothing"
    )


def test_the_cast_select_carries_the_precision():
    assert re.search(r"\btime_precision\b", _select_for("memento_casts")), (
        "memento_casts SELECT dropped time_precision — the panel will print a "
        "sampling day for 875 casts that never had one"
    )


def test_the_sample_select_carries_the_precision():
    assert re.search(r"\btime_precision\b", _select_for("memento_samples")), (
        "memento_samples SELECT dropped time_precision —6,805 per-depth rows "
        "lose the only thing that tells a padded month from a real day"
    )
