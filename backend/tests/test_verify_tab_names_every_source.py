# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""A multi-source layer must offer a verification path for EVERY source.

Check 8c of abyssal-new-layer-check: the Verify Data tab tells a reader how to
cross-check what they clicked. For a layer that unions two compilations, one
DOI is not a shortcut — it is a wrong answer for whichever half it does not
cover.

Found 2026-09-10 on permafrost-thaw. The entry named only the Alaska Webb
Zenodo DOI and called it "the full compilation", while `arts_panarctic` is the
LARGER half: 27,699 rows against 19,540 measured on production. A reader
clicking a Siberian thaw slump was pointed at an Alaska-only record.

⛔ This test names the sources explicitly rather than deriving them, on
purpose. Deriving them would need a live DB, and a guard that skips when the
database is absent is a guard that does not run in CI.
"""
import pathlib

LEGEND = (pathlib.Path(__file__).resolve().parents[2]
          / "frontend" / "src" / "components" / "LegendPanel.tsx")

#: layer -> the strings that prove each of its sources has a verification path.
#: Keep a source's own identifier next to the DOI: the identifier is what the
#: click panel shows, so it is what a reader matches on.
MULTI_SOURCE_VERIFY = {
    "Permafrost Thaw": [
        "alaska_webb",
        "zenodo.16996415",      # Webb et al. 2026, Alaska, CC-BY 4.0
        "arts_panarctic",
        "zenodo.10535025",      # ARTS v6.0.0, circumpolar, CC0
    ],
}


def test_every_source_of_a_multi_source_layer_can_be_verified():
    src = LEGEND.read_text(encoding="utf-8")
    assert "Verify" in src or 'active === "verify"' in src, (
        "fixture problem: LegendPanel has no verify section at all, so the "
        "assertions below would pass on an empty search"
    )
    missing = {}
    for layer, needles in MULTI_SOURCE_VERIFY.items():
        assert layer in src, f"fixture problem: {layer!r} absent from LegendPanel"
        gone = [n for n in needles if n not in src]
        if gone:
            missing[layer] = gone
    assert not missing, (
        "a reader who clicked one of these sources has no way to check it: "
        + "; ".join(f"{k}: {', '.join(v)}" for k, v in missing.items())
    )
