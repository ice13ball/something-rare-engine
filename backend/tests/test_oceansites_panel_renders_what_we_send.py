# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Every property the endpoint ships must be rendered, or refused on purpose.

Check 24d, and the highest-yield check in the whole list. Two days running it
found a field that costs bytes on every request and reaches nobody:

  * GEOTRACES — five columns, 100%/99.7% populated, absent from the /by-id
    SELECT; the panel rendered five blank rows on all 3,874 stations.
  * OceanSITES — `model` populated on 1,072 of 1,072 stations and `age_days`
    on 122, both serialised into every feature and read by no component.

⛔ The allowlist below must carry a REASON per field, not just a name. A bare
allowlist is how a real gap gets parked: the next reader cannot tell "we
decided" from "we forgot", which is the same failure this test exists to stop.
"""
import ast
import pathlib
import re

ROOT    = pathlib.Path(__file__).resolve().parents[2]
SENSORS = ROOT / "backend" / "domains" / "sensors.py"
PANEL   = ROOT / "frontend" / "src" / "components" / "panels" / "ocean" / "OceansitesPanel.tsx"

#: field -> why the panel does not read it.
NOT_FOR_THE_PANEL = {
    "lat": "the map's geometry, already in feature.geometry.coordinates",
    "lon": "the map's geometry, already in feature.geometry.coordinates",
}


def _properties_the_endpoint_sends() -> set[str]:
    """Keys of the `properties` dict literal inside get_oceansites()."""
    tree = ast.parse(SENSORS.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.AsyncFunctionDef) and node.name == "get_oceansites"):
            continue
        for d in ast.walk(node):
            if (isinstance(d, ast.Dict)
                    and any(isinstance(k, ast.Constant) and k.value == "properties"
                            for k in d.keys if k is not None)):
                for k, v in zip(d.keys, d.values):
                    if isinstance(k, ast.Constant) and k.value == "properties":
                        return {kk.value for kk in v.keys
                                if isinstance(kk, ast.Constant) and isinstance(kk.value, str)}
    return set()


def _fields_the_panel_reads() -> set[str]:
    src = PANEL.read_text(encoding="utf-8")
    # The panel destructures the feature as `p`, so every read is `p.<field>`.
    return set(re.findall(r"\bp\.([a-z_][a-z0-9_]*)\b", src))


def test_the_fixture_found_both_sides_and_neither_is_empty():
    # ⛔ Two empty sets make the comparison below pass while proving nothing.
    props = _properties_the_endpoint_sends()
    reads = _fields_the_panel_reads()
    assert len(props) >= 10, f"fixture problem: parsed {sorted(props)} from get_oceansites()"
    assert len(reads) >= 10, f"fixture problem: parsed {sorted(reads)} from the panel"


def test_every_field_we_ship_is_either_rendered_or_refused_with_a_reason():
    props = _properties_the_endpoint_sends()
    reads = _fields_the_panel_reads()
    unread = sorted(props - reads - set(NOT_FOR_THE_PANEL))
    assert not unread, (
        f"/v1/map/oceansites ships {unread} to every client and OceansitesPanel "
        "reads none of them. Either render the field or add it to "
        "NOT_FOR_THE_PANEL with the reason it is deliberately dropped."
    )


def test_the_refusal_list_does_not_outlive_the_fields_it_names():
    props = _properties_the_endpoint_sends()
    stale = sorted(set(NOT_FOR_THE_PANEL) - props)
    assert not stale, (
        f"NOT_FOR_THE_PANEL still excuses {stale}, which the endpoint no "
        "longer sends — an allowlist entry that names nothing hides the next one"
    )
    assert all(NOT_FOR_THE_PANEL.values()), "every refusal needs a reason, not an empty string"


def test_the_two_fields_this_test_was_written_for_are_actually_rendered():
    # Named explicitly: the general check above would go green if someone
    # "fixed" it by moving model and age_days into the allowlist.
    reads = _fields_the_panel_reads()
    for field in ("model", "age_days"):
        assert field in reads, (
            f"OceansitesPanel stopped reading {field!r}; it is populated on "
            "1,072 and 122 of 1,072 stations respectively and shipped regardless"
        )
        assert field not in NOT_FOR_THE_PANEL, (
            f"{field!r} was moved to the allowlist rather than rendered"
        )
