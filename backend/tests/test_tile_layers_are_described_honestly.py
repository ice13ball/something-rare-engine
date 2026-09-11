# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""A layer that works must not be described as not working.

Three raster layers are wired to live publisher tile servers in Map3D.tsx, and
every user-facing surface said they were inert. Verified against the live
servers on 2026-09-10, tile 5/16/14:

    forest-loss   umd_tree_cover_loss v1.13         -> 200, 1,608 bytes, PNG
    carbon-flux   gfw_forest_carbon_net_flux        -> 200, 10,345 bytes, PNG
    soil-carbon   ISRIC SoilGrids WMS soc_0-5cm     -> 200, 8,535 bytes, PNG

while all four locales said "Pending — requires tile server setup" and "tiles
not yet connected", and one Dates row covered all three at once.

⛔ This is the MODIS defect pointed the other way. The rule is not "do not
oversell" — it is that the copy must describe what the code does. Underselling
a working layer is the same failure, and it hides a shipped feature from the
only people who would use it.

Two more claims went with it:

  * "weekly GLAD/RADD alerts" appeared in the legal page, the layer type
    description and four tooltips. `grep -rn -iE "glad|radd" frontend/src
    backend` found NO code anywhere — the alerts were never fetched or drawn.
  * "2001–2024" was quoted for tree cover loss. GFW's own version metadata
    returns `content_date_range = {start_date: None, end_date: None}` for
    v1.13, so that window was ours, not theirs. The version is named instead.
"""
import json
import pathlib
import re

ROOT    = pathlib.Path(__file__).resolve().parents[2]
MAP3D   = ROOT / "frontend" / "src" / "components" / "Map3D.tsx"
LOCALES = ROOT / "frontend" / "public" / "locales"
PROSE   = [
    ROOT / "frontend" / "src" / "content" / "legalContent.ts",
    ROOT / "frontend" / "src" / "types" / "landLayers.ts",
]

#: layer id -> the legend.json key that describes it.
TILE_LAYERS = {
    "forest-loss": "treeCoverLoss",
    "carbon-flux": "forestCarbonFlux",
    "soil-carbon": "soilOrganicCarbon",
}

#: Wording, in every locale we ship, that says a layer does not work.
_INERT = re.compile(
    r"not yet connected|tiles? not connected|pending — requires|setup pending"
    r"|jeszcze niepodłączone|oczekując\w* — wymaga"
    r"|non encore connect|en attente — configuration"
    r"|noch nicht verbunden|ausstehend — kachelserver",
    re.IGNORECASE)


def _locales():
    return sorted(p for p in LOCALES.iterdir() if (p / "legend.json").is_file())


def test_the_fixture_finds_the_layers_wired_and_the_locales_present():
    src = MAP3D.read_text(encoding="utf-8")
    for lid in TILE_LAYERS:
        assert f'activeLayers.has("{lid}")' in src, (
            f"fixture problem: {lid} is not wired in Map3D at all, so the "
            "assertions below would be guarding nothing"
        )
    assert len(_locales()) >= 2, "fixture problem: fewer than two locales"


def test_a_wired_tile_layer_is_never_described_as_pending():
    src = MAP3D.read_text(encoding="utf-8")
    offenders = {}
    for lid, key in TILE_LAYERS.items():
        if f'activeLayers.has("{lid}")' not in src:
            continue                      # genuinely not wired — prose may say so
        for loc in _locales():
            d = json.loads((loc / "legend.json").read_text(encoding="utf-8"))
            entry = d["layers"].get(key) or {}
            blob = "\n".join(str(v) for v in entry.values())
            blob += "\n" + str(d.get("dates", {}).get("fresh_pendingTiles", ""))
            hit = _INERT.findall(blob)
            if hit:
                offenders.setdefault(lid, []).append(f"{loc.name}: {hit[:2]}")
    assert not offenders, (
        f"these layers draw live publisher tiles and the copy calls them "
        f"inert: {offenders}"
    )


def test_we_do_not_promise_an_alert_product_we_never_fetch():
    # ⛔ Derived from the code: if GLAD/RADD is ever genuinely wired, this test
    # stops forbidding the claim rather than needing to be deleted.
    code = "\n".join(p.read_text(encoding="utf-8")
                     for p in (MAP3D,) if p.is_file())
    fetches_alerts = bool(re.search(r"glad|radd|integrated_alerts", code, re.IGNORECASE))
    if fetches_alerts:
        return
    offenders = []
    for p in PROSE:
        if re.search(r"\bGLAD\b|\bRADD\b", p.read_text(encoding="utf-8")):
            offenders.append(p.name)
    for loc in _locales():
        pj = loc / "panels.json"
        if pj.is_file() and re.search(r"\bGLAD\b|\bRADD\b", pj.read_text(encoding="utf-8")):
            offenders.append(f"{loc.name}/panels.json")
    assert not offenders, (
        f"GLAD/RADD alerts are promised in {offenders} and fetched nowhere"
    )


def test_the_tree_cover_version_we_serve_is_the_one_we_name():
    # A version pinned in the URL and a different one quoted in the copy is how
    # v1.11 was served for two annual releases while nobody could tell.
    src = MAP3D.read_text(encoding="utf-8")
    m = re.search(r"umd_tree_cover_loss/(v[\d.]+)/", src)
    assert m, "fixture problem: the tree cover loss tile URL did not parse"
    version = m.group(1)
    missing = []
    for loc in _locales():
        blob = (loc / "legend.json").read_text(encoding="utf-8")
        if (loc / "panels.json").is_file():
            blob += (loc / "panels.json").read_text(encoding="utf-8")
        if version not in blob:
            missing.append(loc.name)
    assert not missing, (
        f"Map3D serves umd_tree_cover_loss {version}; the copy in {missing} "
        "names a different version or none at all"
    )
