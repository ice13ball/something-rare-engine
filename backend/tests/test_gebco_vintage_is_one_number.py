# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""One GEBCO vintage, stated once, matching what the tiles actually are.

wms.gebco.net serves GEBCO_LATEST, so the grid changes under us. The repo held
three different answers for the same live layer:

    utils/gebcoTiles.ts  GEBCO_ATTRIBUTION = "... GEBCO_2026 Grid"   correct
    types/layers.ts      "GEBCO_2026 shaded-relief seafloor"          correct
    legend.json          "... GEBCO_2025 Grid via wms.gebco.net"      WRONG,
                         and the one a reader actually sees
    Map3D.tsx comment    "GEBCO_2025 shaded-relief seafloor"          stale

Checked live 2026-09-10: GetCapabilities on wms.gebco.net lists GEBCO_2026 and
nothing else. gebcoTiles.ts already carried a comment recording that this exact
drift happened once before — a comment predicting "GEBCO_2025 from June 2026"
while GEBCO published 2026 in April — and instructing a manual GetCapabilities
check. The check was made; the legend was not updated.

⛔ The expected vintage is READ from GEBCO_ATTRIBUTION, never hardcoded here.
The next release must be changed in one place, not four.
"""
import json
import pathlib
import re

ROOT    = pathlib.Path(__file__).resolve().parents[2] / "frontend"
TILES   = ROOT / "src" / "utils" / "gebcoTiles.ts"
TYPES   = ROOT / "src" / "types" / "layers.ts"
LOCALES = ROOT / "public" / "locales"

_VINTAGE = re.compile(r"GEBCO_(20\d\d)")


def _strip_comments(src: str) -> str:
    """Drop // and /* */ comments.

    ⛔ Four guards this week first reddened on the assistant's own prose. Both
    gebcoTiles.ts and Map3D.tsx carry comments that QUOTE the old wrong vintage
    in order to explain the mistake; a plain search reddens on the very text
    that documents the fix.
    """
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(ln.split("//")[0] for ln in src.splitlines())


def _declared_vintage() -> str:
    code = _strip_comments(TILES.read_text(encoding="utf-8"))
    m = re.search(r"GEBCO_ATTRIBUTION\s*=\s*\"([^\"]*)\"", code)
    assert m, "fixture problem: GEBCO_ATTRIBUTION did not parse"
    v = _VINTAGE.search(m.group(1))
    assert v, f"fixture problem: no vintage in {m.group(1)!r}"
    return v.group(0)


def test_the_fixture_finds_a_single_declared_vintage():
    v = _declared_vintage()
    assert re.fullmatch(r"GEBCO_20\d\d", v), v


def test_the_comment_stripper_does_not_eat_the_declaration():
    # ⛔ If stripping removed the string literal too, every assertion below
    # would compare nothing against nothing.
    code = _strip_comments(TILES.read_text(encoding="utf-8"))
    assert "GEBCO_ATTRIBUTION" in code
    assert _VINTAGE.search(code), "stripping removed the vintage itself"


def test_every_locale_states_the_vintage_the_tiles_actually_are():
    want = _declared_vintage()
    offenders = {}
    for loc in sorted(p for p in LOCALES.iterdir() if (p / "legend.json").is_file()):
        d = json.loads((loc / "legend.json").read_text(encoding="utf-8"))
        entry = d["layers"].get("bathymetry") or {}
        blob = "\n".join(str(v) for v in entry.values())
        found = set(_VINTAGE.findall(blob))
        if not found:
            offenders[loc.name] = "no vintage stated at all"
        elif found != {want.split("_")[1]}:
            offenders[loc.name] = sorted("GEBCO_" + f for f in found)
    assert not offenders, (
        f"the tiles are {want}; these locales say otherwise: {offenders}"
    )


def test_the_type_description_agrees_too():
    want = _declared_vintage()
    code = _strip_comments(TYPES.read_text(encoding="utf-8"))
    found = set(_VINTAGE.findall(code))
    assert found == {want.split("_")[1]}, (
        f"layers.ts states {sorted(found)} while the tiles are {want}"
    )


def test_the_three_gebco_products_stay_three_and_are_not_harmonised():
    """⛔ This platform serves THREE different GEBCO products, on purpose.

        WMS shaded relief   GEBCO_LATEST -> 2026   what the map draws
        bathymetry_stats    GEBCO 2024            the confidence table
        /lookup depth       GEBCO 2020            via Open-Topo-Data

    The split is deliberate and recorded in the layer's rule file. A guard that
    demanded one number everywhere would push someone to state a vintage that
    is not true of the product they are labelling — this test first failed
    exactly that way, which is why it now names each product separately.
    """
    want = _declared_vintage().split("_")[1]
    legend  = (ROOT / "src" / "components" / "LegendPanel.tsx").read_text(encoding="utf-8")
    chips   = (ROOT / "src" / "components" / "panels" / "shared" / "chips.tsx").read_text(encoding="utf-8")

    # The confidence table and the point lookup must NOT drift to the WMS
    # vintage — that would be a silent claim about data that never changed.
    # ⛔ EVERY mention, not just one. LegendPanel names GEBCO_2024 four times
    # across the Dates row and the Verify paragraph; asserting mere presence
    # let a sabotage change the Dates row while the Verify text kept the guard
    # green, which is how one surface drifts away from another unnoticed.
    legend_vintages = set(_VINTAGE.findall(_strip_comments(legend)))
    assert legend_vintages == {"2024"}, (
        f"LegendPanel names GEBCO vintages {sorted(legend_vintages)}; every "
        "mention there describes bathymetry_stats, computed against GEBCO 2024"
    )
    assert "GEBCO_2020" in _strip_comments(chips), (
        "the depth chip no longer states GEBCO_2020, the grid Open-Topo-Data "
        "serves for the point lookup"
    )
    assert want not in ("2024", "2020"), (
        f"the WMS vintage is now {want}, which collides with one of the two "
        "fixed products — re-read the rule file before trusting any of these"
    )


def test_only_the_attribution_pins_the_wms_vintage():
    # One number, one place, for the layer that actually changes under us.
    want = _declared_vintage().split("_")[1]
    #: Files allowed to name a GEBCO vintage, and which product each describes.
    ALLOWED = {
        "src/utils/gebcoTiles.ts":                    "WMS — the source of truth",
        "src/types/layers.ts":                        "WMS — layer description",
        "src/components/LegendPanel.tsx":             "bathymetry_stats — GEBCO 2024",
        "src/components/panels/shared/chips.tsx":     "point lookup — GEBCO 2020",
    }
    strays = {}
    for p in sorted((ROOT / "src").rglob("*.ts")) + sorted((ROOT / "src").rglob("*.tsx")):
        rel = str(p.relative_to(ROOT))
        found = set(_VINTAGE.findall(_strip_comments(p.read_text(encoding="utf-8"))))
        if not found:
            continue
        if rel not in ALLOWED:
            strays[rel] = sorted(found)
        elif "WMS" in ALLOWED[rel] and found != {want}:
            strays[rel] = f"{sorted(found)} but the tiles are GEBCO_{want}"
    assert not strays, (
        f"a GEBCO vintage is stated somewhere it is not accounted for: {strays}"
    )
