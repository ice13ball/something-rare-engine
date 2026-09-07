# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import json
import re

import pathlib

METHODS = pathlib.Path(__file__).resolve().parents[2] / "docs" / "methods" / "data-passthrough.md"

def test_methods_note_pins_every_date_precision_level():
    """The five precision levels are a contract. If one is dropped from the note,
    a future panel will invent its own rendering for it."""
    text = METHODS.read_text(encoding="utf-8")
    for level in ("`day`", "`month`", "`year`", "`campaign`", "`none`"):
        assert level in text, f"date_precision level {level} missing from the methods note"

def test_methods_note_forbids_upsampling_and_downsampling():
    text = METHODS.read_text(encoding="utf-8")
    assert "never widen" in text.lower() or "never add" in text.lower()
    assert "never narrow" in text.lower() or "never round" in text.lower()


FRONTEND_SRC = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src"


def test_no_panel_claims_a_glodap_release_we_do_not_serve():
    """We bake GLODAPv2.2016b. Any other version string in a user-facing panel
    is a claim about provenance that the data does not support."""
    offenders = []
    for path in FRONTEND_SRC.rglob("*.tsx"):
        text = path.read_text(encoding="utf-8")
        if "v2.2021" in text or "v2.2022" in text or "v2.2023" in text:
            offenders.append(str(path.relative_to(FRONTEND_SRC)))
    assert offenders == [], f"panels claim a GLODAP release we do not serve: {offenders}"


LOCALES = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "public" / "locales"
LOCALE_NAMES = ("en", "de", "fr", "pl")


def _legend(loc):
    return (LOCALES / loc / "legend.json").read_text(encoding="utf-8")


FRONTEND_ROOT = pathlib.Path(__file__).resolve().parents[2] / "frontend"

# The rule these two guards encode is "nowhere in shipping frontend content do we
# name FAO/GSOCmap as the source of soil carbon" — the rule is about what ships,
# not about which files one particular fix happened to touch. An earlier version
# of this guard, fixed 2026-09-04, scanned only frontend/src and frontend/public
# and missed frontend/index.html and
# frontend/server.js, both of which still said FAO GSOCmap and both of which are
# live, server-rendered content (index.html is the static shell; server.js is the
# LAYER_META served to bots and to the SEO /layer/:id pages). This is the third
# time in this repo a guard has been scoped to a diff instead of to the rule it
# is meant to enforce — so this scan covers every shipping frontend surface:
# frontend/src, frontend/public, plus the two hand-authored root files, across
# every extension that can carry user-facing or bot-facing prose. It explicitly
# excludes frontend/node_modules and frontend/dist (or any build output), which
# are neither authored nor shipped as source and would only make the scan slow
# and noisy with vendored/bundled text.
_EXCLUDED_DIR_NAMES = {"node_modules", "dist", "build", ".git"}
_SCAN_EXTS = ("*.ts", "*.tsx", "*.json", "*.snap", "*.txt", "*.md", "*.html", "*.js")


def _iter_frontend_shipping_files():
    # frontend/seo/ is the server-side render pipeline: fourteen render* functions
    # that build their own HTML and are served to every visitor and every bot. It
    # was outside this scan until 2026-09-06, which meant neither the soil-carbon
    # attribution guard nor the licence-notice guard could see the pages most
    # likely to be read by a search engine. If you add another directory whose
    # contents reach a browser, it belongs here too.
    roots = [FRONTEND_ROOT / "src", FRONTEND_ROOT / "public", FRONTEND_ROOT / "seo"]
    for root in roots:
        for ext in _SCAN_EXTS:
            for path in root.rglob(ext):
                if _EXCLUDED_DIR_NAMES.isdisjoint(path.parts):
                    yield path
    for extra in (FRONTEND_ROOT / "index.html", FRONTEND_ROOT / "server.js"):
        if extra.exists():
            yield extra


def _names_fao_as_the_soil_carbon_source(line: str) -> bool:
    """True when one line credits FAO with our soil-carbon data.

    Matching the literal "GSOCmap" is not enough, and that is not a
    hypothetical: frontend/index.html carried `FAO - Global soil organic carbon
    map`, which names the wrong institution without ever spelling GSOCmap. A
    guard widened to more directories but still asking the old question walks
    past it exactly as the narrower one did.

    So the predicate is the CLAIM, not one spelling of it: FAO named on the same
    line as soil carbon. FAO publishes real data we may legitimately cite one
    day (fisheries, land cover); this stays quiet about those because it needs
    both halves on the line.
    """
    low = line.lower()
    if "gsocmap" in low:
        return True
    if "fao" not in low:
        return False
    return "soil" in low or "soc_" in low or "organic carbon" in low


def test_soil_carbon_is_attributed_to_the_service_we_fetch_from():
    """Map3D fetches maps.isric.org soc_0-5cm_mean. Naming FAO GSOCmap credits the
    wrong institution, states the wrong depth, and links a dataset we never render.
    The claim leaked into more files than the layer definition: the legal
    attributions page, llms.txt, the static index.html marketing copy, and the
    server.js LAYER_META served to bots and SEO pages all carried it.

    The rule this guard encodes is "nowhere in shipping frontend content do we
    name FAO/GSOCmap as the source of soil carbon" — so its scope is the whole
    shipping frontend surface (frontend/src, frontend/public, index.html,
    server.js), not just the files one earlier fix happened to touch."""
    offenders = []
    for path in _iter_frontend_shipping_files():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _names_fao_as_the_soil_carbon_source(line):
                offenders.append(f"{path}:{lineno}")
    assert offenders == [], f"these still attribute soil carbon to FAO: {offenders}"


def test_soil_carbon_states_the_depth_we_actually_render():
    """soc_0-5cm_mean is the top 5 cm, not the top 30 cm. The claim lived in more
    files than the layer catalogue: the layer-menu tooltip in panels.json carried
    it too, and a guard that reads only legend.json walks straight past it.

    Same rule, same scope as the attribution guard above: the whole shipping
    frontend surface, not one author's diff."""
    offenders = []
    for path in _iter_frontend_shipping_files():
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if ("30cm" in line or "30 cm" in line) and "soil" in line.lower():
                offenders.append(f"{path}: {line.strip()[:80]}")
    assert offenders == [], f"these still claim the top 30 cm for soil carbon: {offenders}"


def test_carbon_flux_states_one_year_window_per_locale():
    """Two windows for one layer in one file means at least one is wrong."""
    for loc in LOCALE_NAMES:
        windows = set(re.findall(r"2001[–-]20\d\d", _legend(loc)))
        assert len(windows) <= 1, f"{loc}/legend.json states {sorted(windows)} for the same layer"


LEGEND_PANEL = FRONTEND_SRC / "components" / "LegendPanel.tsx"


def test_legend_gives_carbon_layers_an_observation_window():
    """The ISAS line already does this right: 'Static (ISAS 2014-2018 release)'.
    A bare release name next to a fresh sync date reads as fresh data."""
    text = LEGEND_PANEL.read_text(encoding="utf-8")
    assert "Static (GLODAPv2.2016b release)" not in text, \
        "GLODAP still shows a release name where ISAS shows an observation window"
    assert "Static (CASCADE v2 release)" not in text
    assert "1934" in text, "CASCADE's observation window (1934-2018) is not stated"
