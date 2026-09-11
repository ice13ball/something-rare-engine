# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""The oxygen-deox layer denied a feature it has, and named the wrong baseline.

Two defects, both user-facing, both in all four locales:

1. `limitations` said "Numeric values are not available on click (pre-baked
   image)." `/v1/oxygen/point` answers every click with three numbers.
   Measured against production 2026-09-11:
       20.0N 120.0W 300 m   recent 32.5   baseline 26.35   delta  +6.15
      -10.0S  85.0W 300 m   recent  6.40  baseline  9.95   delta  -3.55
       50.0N  30.0W 300 m   recent 231.2  baseline 232.86  delta  -1.66
   A legend that talks a reader out of clicking is as damaging as a wrong value.

2. Every user-facing surface said "~1980s baseline". The baseline is WOA23's
   `decav71A0`, 1971-2000. 1985 is the MIDPOINT of that window, not the window.
   The Δ is a 30-year mean subtracted from a 5-year mean.

⛔ The backend already knew. `domains/fields/climatology.py` carries a docstring
that says '⛔ NOT "~1980s"' in as many words, and `layer_temporal_coverage.py`
carries NOAA's own "WOA23N 1971-2000 'Climate Normal'". The knowledge sat one
file away from the text the reader saw — the same call-site-versus-helper gap
this suite keeps finding.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LOCALES = ROOT / "frontend" / "public" / "locales"
LAYER = "oxygen-deox"


def _locales() -> list[str]:
    found = sorted(p.name for p in LOCALES.iterdir() if p.is_dir())
    assert len(found) >= 2, f"only {found} discovered — re-anchor this guard"
    return found


# Every way the four locales phrase "you cannot click this".
_DENIALS = (
    "not available on click",          # en
    "nie są dostępne po kliknięciu",   # pl
    "beim Klick nicht verfügbar",      # de
    "ne sont pas disponibles au clic", # fr
)

# Every way they wrote the wrong decade.
_WRONG_BASELINE = ("~1980s", "~lat 80", "~1980er", "années ~1980")


@pytest.mark.parametrize("loc", _locales())
def test_legend_does_not_deny_the_click_that_works(loc):
    entry = json.loads((LOCALES / loc / "legend.json").read_text())["layers"][LAYER]
    blob = " ".join(str(v) for v in entry.values())
    hit = [d for d in _DENIALS if d in blob]
    assert not hit, (
        f"{loc}/legend.json tells the reader clicking returns nothing ({hit}), but "
        "/v1/oxygen/point returns recent_o2, baseline_o2 and delta_o2 for every point."
    )


@pytest.mark.parametrize("loc", _locales())
def test_no_locale_calls_the_baseline_the_1980s(loc):
    for fname, path in (("legend.json", ("layers", LAYER)),
                        ("panels.json", ("tooltip", "descriptions"))):
        data = json.loads((LOCALES / loc / fname).read_text())
        node = data
        for k in path:
            node = node.get(k, {})
        blob = json.dumps(node.get(LAYER, node), ensure_ascii=False) if fname == "panels.json" \
            else json.dumps(node, ensure_ascii=False)
        hit = [w for w in _WRONG_BASELINE if w in blob]
        assert not hit, (
            f"{loc}/{fname} calls the baseline {hit}; WOA23 period decav71A0 is 1971-2000 "
            "and 1985 is its midpoint, not its span"
        )


def test_the_panel_and_the_api_agree_with_the_coverage_record():
    """The three surfaces must not drift apart again."""
    panel = (ROOT / "frontend" / "src" / "components" / "panels" / "fields"
             / "OxygenPointPanel.tsx").read_text()
    service = (ROOT / "backend" / "services" / "oxygen_deox.py").read_text()
    coverage = (ROOT / "backend" / "layer_temporal_coverage.py").read_text()

    # layer_temporal_coverage is the authority: it stores the publisher's wording.
    assert "1971" in coverage and "2000" in coverage, \
        "the coverage record no longer carries WOA23's 1971-2000 — re-anchor this guard"

    for name, blob, wrong in (("OxygenPointPanel.tsx", panel, "~1980s"),
                              ("services/oxygen_deox.py", service, "vs ~1980s")):
        # strip the comment/docstring lines that deliberately quote the old wording
        live = "\n".join(
            ln for ln in blob.splitlines()
            if not ln.lstrip().startswith(("//", "#", "*", "⛔"))
        )
        assert wrong not in live, f"{name} still shows {wrong!r} to the reader"

    assert "1971" in panel, "the panel no longer names the baseline period at all"
