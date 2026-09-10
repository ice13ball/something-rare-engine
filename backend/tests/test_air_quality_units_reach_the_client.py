# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""The unit OpenAQ published must reach the client, or every consumer guesses.

`air_quality_params.unit` has been stored verbatim since the layer was built —
the sync's own comment says "verbatim unit, no conversion, no unit ever
assumed". The endpoint then dropped it, and both consumers guessed wrong:

  * AirQualityPanel printed a hardcoded "ppb" on NO/NO2/NOx/SO2/O3/CO
  * stationAqi() scored those same values on a ppb scale

Measured over air_quality_params on production 2026-09-10:

    o3    µg/m³ 6,692   ppm 3,583   ppb     7    -> ppb on 0.07% of stations
    no2   µg/m³ 8,093   ppm 4,114   ppb   586    -> ppb on 4.6%
    co    µg/m³ 4,345   ppm 2,126   ppb   563    -> ppb on 8.0%

So the panel printed a unit the source never gave on roughly 95% of gas rows,
and the map's dot colours were wrong in both directions.

⛔ Check 24d, the third time this week: a column that is POPULATED but absent
from the endpoint's SELECT is a column nobody has.
"""
import pathlib
import re

ROOT    = pathlib.Path(__file__).resolve().parents[2]
HAZARDS = ROOT / "backend" / "domains" / "land" / "hazards.py"
PANEL   = ROOT / "frontend" / "src" / "components" / "panels" / "land" / "AirQualityPanel.tsx"
AQI     = ROOT / "frontend" / "src" / "styles" / "aqi.ts"

_SRC = HAZARDS.read_text(encoding="utf-8")


def _endpoint() -> str:
    i = _SRC.index('@router.get("/air-quality")')
    return _SRC[i:_SRC.index("_air_quality_cache = row", i)]


def test_the_fixture_found_the_endpoint():
    body = _endpoint()
    assert "air_quality_stations" in body and len(body) > 800, (
        "fixture problem: the /air-quality endpoint did not slice out"
    )


def test_the_endpoint_carries_the_published_units():
    body = _endpoint()
    assert "'units'" in body, "the /air-quality payload has no units key"
    assert "air_quality_params" in body, (
        "units are not sourced from air_quality_params, the only table that "
        "stores what OpenAQ actually published"
    )
    assert "p.unit IS NOT NULL" in body, (
        "a NULL unit must be omitted, not carried as a key with a null value — "
        "the client treats a present-but-null unit as a unit it can trust"
    )


def test_the_panel_no_longer_prints_a_unit_of_its_own_invention():
    panel = PANEL.read_text(encoding="utf-8")
    # Any hardcoded ppb/ppm inside a Row value is a unit we made up.
    bad = re.findall(r'value=\{`[^`]*\b(ppb|ppm)\b[^`]*`\}', panel)
    assert not bad, (
        f"AirQualityPanel still hardcodes {sorted(set(bad))} in a row value. "
        "OpenAQ publishes the unit; print theirs."
    )
    assert "units" in panel, "the panel never reads the units map"


def test_the_aqi_refuses_a_unit_it_cannot_map():
    aqi = AQI.read_text(encoding="utf-8")
    assert "toAqiUnit" in aqi, "the unit normaliser is gone"
    # ⛔ The molecular weights must be per-gas. One shared constant would make
    # every conversion wrong for every gas but one.
    for gas, mw in (("o3", "48"), ("no2", "46."), ("so2", "64."), ("co", "28.")):
        assert re.search(rf"{gas}:\s*{re.escape(mw)}", aqi), (
            f"{gas} has no molecular weight of its own in _MOLECULAR_WEIGHT"
        )
    assert "return null;   // unknown or missing unit" in aqi or "return null" in aqi, (
        "toAqiUnit must return null for an unrecognised unit"
    )
    # And stationAqi's own contract must no longer assert every gas is ppb.
    # ⛔ Scoped to the JSDoc immediately above the function on purpose: the
    # explanatory comment further up QUOTES that old claim in order to bury it,
    # and a whole-file search reddens on the very text that documents the fix.
    # A counter guard hit this exact trap two days ago.
    i = aqi.index("export function stationAqi")
    doc = aqi[aqi.rindex("/**", 0, i):i]
    assert "→ ppb" not in doc, (
        f"stationAqi's contract still promises ppb for every gas:\n{doc}"
    )
    assert "unit" in doc.lower(), (
        "stationAqi's contract says nothing about units at all, so the next "
        "caller has no way to know it needs to supply them"
    )


def test_the_sync_still_stores_the_unit_verbatim():
    # ⛔ The 1:1 rule. If the sync ever starts normalising units, the honest
    # record of what OpenAQ published is gone and this whole fix is undone.
    assert 'unit = param.get("units")' in _SRC, (
        "the sync no longer reads OpenAQ's own unit field"
    )
    assert "units[param_name] = unit" in _SRC
