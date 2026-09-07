# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

from pathlib import Path

from backend.scripts.link_audit.extract_py import extract_inventory, extract_provenance

FIXTURES = Path(__file__).parent / "fixtures" / "link_audit"


def test_inventory_uses_first_tuple_element_as_layer_id_and_last_as_url():
    text = (FIXTURES / "inventory_excerpt.py").read_text(encoding="utf-8")
    rows = {r.layer_id: r for r in extract_inventory(text, "backend/main.py")}
    assert set(rows) == {"obis", "vents", "onc-locations", "acoustic-stations"}
    assert rows["obis"].url_normalized == "https://obis.org/"
    assert rows["vents"].kind == "doi"
    assert rows["obis"].surface == "inventory"


def test_inventory_reassembles_a_multiline_tuple():
    """The real acoustic-stations entry (backend/main.py:15509-15512) spans 4
    physical lines. extract_inventory must reassemble it before reading
    quoted strings, or it silently drops the row (as it did before this
    fix — the opening line's last quoted string is "ocean-monitoring", not
    a URL, so the http(s):// guard rejected it)."""
    text = (FIXTURES / "inventory_excerpt.py").read_text(encoding="utf-8")
    rows = {r.layer_id: r for r in extract_inventory(text, "backend/main.py")}
    assert "acoustic-stations" in rows
    assert rows["acoustic-stations"].url_normalized == "https://oceanobservatories.org/"
    assert rows["acoustic-stations"].surface == "inventory"


def test_inventory_tolerates_none_in_the_sync_log_key_slot():
    """sync_log_key is `str | None`; a bare None must not shift which quoted
    string is read as the URL."""
    text = (
        '_INVENTORY: list[tuple[str, str, str, str, str | None, str, str]] = [\n'
        '    ("live", "Live layer", "grp", "tbl", None, "Some Org", "https://example.org/live"),\n'
        ']\n'
    )
    rows = extract_inventory(text, "backend/main.py")
    assert len(rows) == 1
    assert rows[0].layer_id == "live"
    assert rows[0].url_normalized == "https://example.org/live"


def test_provenance_attributes_url_to_the_enclosing_export_id():
    text = (FIXTURES / "provenance_excerpt.py").read_text(encoding="utf-8")
    rows = {r.layer_id: r for r in extract_provenance(text, "backend/services/export_registry.py")}
    assert rows["socat-co2"].url_normalized == "https://www.socat.info/"
    assert rows["glodap-carbon"].url_normalized == "https://www.glodap.info/"
    assert rows["glodap-carbon"].surface == "provenance"
