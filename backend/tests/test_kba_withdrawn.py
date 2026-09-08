# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""KBA is withheld pending written permission from the KBA Secretariat.

BirdLife's KBA terms forbid redistribution "through interactive web maps ...
that grant users download access" without prior written permission, plus a
separate no-commercial-use clause. Verified against
keybiodiversityareas.org/termsofservice on 2026-09-03. This is the same
clause that forced the WDPA withdrawal (see test_wdpa_withdrawn.py). The rows
stay in the database; only the serving surfaces stop.

⛔ 410, not 404. 404 means "maybe temporary" and Google keeps the URL for weeks.
410 means withdrawn on purpose.
"""
import layer_ops
import main
import startup_seeds


def test_kba_is_gone_from_every_layer_registry():
    assert "kbas" not in {d["id"] for d in startup_seeds.LAYER_DEFAULTS_PY}
    assert "kbas" not in layer_ops.LAYER_OPS


def test_kba_is_gone_from_the_public_data_inventory():
    """The inventory is a public claim about what the platform offers."""
    assert "kbas" not in {row[0] for row in main._INVENTORY}
    assert "kba" not in {row[0] for row in main._INVENTORY}


def test_the_three_layer_registries_still_agree():
    """They carried KEEP IN SYNC at 57. A removal must leave them equal, not one short."""
    assert len(startup_seeds.LAYER_DEFAULTS_PY) == len(layer_ops.LAYER_OPS)


# ── the SERVING paths, not just the registries ────────────────────────────
#
# The first WDPA withdrawal edited the in-memory registries and stopped, and a
# follow-up commit on 2026-09-03 had to close every path that actually handed
# geometry or identity to a client: the MVT tile endpoint, the bulk export,
# the overlaps listing, the startup-profile whitelist, and the frontend layer
# that requests the tiles. A layer absent from a registry but still
# addressable by URL is not withdrawn — it is unlisted.
#
# These tests assert against the SOURCE of each serving path, because that is
# the only place the exposure can be checked without a database.

import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
FRONTEND = REPO / "frontend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def test_the_mvt_tile_endpoint_cannot_address_kba():
    """`/v2/spatial/tiles/key_biodiversity_areas/{z}/{x}/{y}` served full geometry
    + site_name + country + status + criteria.

    FastAPI resolves `{layer}` through the SpatialLayer enum, so removing the
    member is what makes the URL unroutable (422), not merely unlisted.
    """
    from routers import spatial_v2

    assert not hasattr(spatial_v2.SpatialLayer, "key_biodiversity_areas")
    assert "key_biodiversity_areas" not in {m.value for m in spatial_v2.SpatialLayer}


def test_no_kba_tile_sql_survives_in_the_tile_router():
    """A dormant `_MVT_KBAS` is one `elif` away from serving again."""
    src = (BACKEND / "routers" / "spatial_v2.py").read_text()
    assert "_MVT_KBAS" not in src
    assert "FROM key_biodiversity_areas k" not in src


def test_kba_is_not_offered_for_export():
    """The licence clause names download access explicitly — this is that path."""
    from services.export_registry import EXPORT_LAYERS

    assert "kbas" not in EXPORT_LAYERS


def test_no_startup_profile_can_switch_kba_on():
    """A profile listing a withdrawn layer turns the whole withdrawal into a toggle."""
    from profiles import KNOWN_LAYER_IDS

    assert "kbas" not in KNOWN_LAYER_IDS


def test_the_mining_overlap_endpoint_does_not_republish_kba_identity():
    """`/mining-kba` returned `kba_id` and `site_name` per row — KBA records, reshaped.

    The aggregate COUNT stays: a number of overlaps is our own finding, not their
    database. The per-site listing is their database.
    """
    src = (BACKEND / "land_overlaps.py").read_text()
    body = src[src.index("async def get_mining_kba_overlaps"):]
    body = body[:body.index("\n@router.get", 1)] if "\n@router.get" in body[1:] else body
    assert "410" in body, "the withdrawn overlaps listing must answer 410 Gone"


def test_the_layer_row_is_retired_by_code_rather_than_by_hand():
    """⛔ No manual UPDATE on production. The retirement must travel with the code.

    `ensure_layer_config_seed` seeds ON CONFLICT DO NOTHING, so an existing
    `kbas` row keeps `status='enabled'` forever and `/v1/map/layer-config`
    (WHERE status='enabled') keeps advertising it — on every environment the
    code is deployed to, including any restored backup.
    """
    import startup_seeds

    assert "kbas" in startup_seeds.WITHDRAWN_LAYER_IDS
    src = (BACKEND / "startup_seeds.py").read_text()
    fn = src[src.index("async def ensure_layer_config_seed"):]
    fn = fn[:fn.index("\nasync def ", 1)]
    assert "WITHDRAWN_LAYER_IDS" in fn
    assert "retired" in fn


# ── the frontend half ───────────────────────────────────────────────────────
# Checked from here rather than vitest because the exposure is one fact spanning
# both halves: a backend that stops serving plus a frontend that keeps asking is
# still a broken map, and a frontend that keeps offering a download is still the
# licence breach even after the backend stops.

def test_the_map_no_longer_builds_a_kba_tile_layer():
    src = (FRONTEND / "src" / "components" / "Map3D.tsx").read_text()
    assert "kbas-mvt" not in src
    assert "tiles/key_biodiversity_areas" not in src


def test_the_frontend_export_menu_no_longer_offers_kbas():
    src = (FRONTEND / "src" / "utils" / "exportLayers.ts").read_text()
    assert not re.search(r'id:\s*"kbas"', src)


def test_no_discovery_preset_enables_kbas_in_one_click():
    src = (FRONTEND / "src" / "components" / "DiscoveryPanel.tsx").read_text()
    assert '"kbas"' not in src


def test_no_control_or_search_entry_can_switch_kba_on():
    """A toggle for a layer the backend 410s renders an empty map and a support ticket."""
    for rel in (
        ("src", "components", "controls", "sections", "LandCoreSection.tsx"),
        ("src", "components", "SearchBar.tsx"),
        ("src", "utils", "menuTaxonomy.ts"),
    ):
        src = (FRONTEND.joinpath(*rel)).read_text()
        assert '"kbas"' not in src, f"{rel[-1]} still references the kbas layer id"


# ── the public claim ─────────────────────────────────────────────────────

def test_no_public_surface_still_advertises_kba_as_a_layer():
    """A withdrawn layer that is still listed is a claim we cannot honour.

    `index.html` and `legalContent.ts` are the noscript/legal copy Google reads;
    `site-graph.json` asserts a schema.org Dataset. All three said the platform
    offers 16,000+ (or 16,800+) Key Biodiversity Areas from BirdLife/KBA
    Partnership — a claim to something we no longer serve.
    """
    surfaces = {
        "index.html": FRONTEND / "index.html",
        "legalContent.ts": FRONTEND / "src" / "content" / "legalContent.ts",
        "site-graph.json": FRONTEND / "seo" / "site-graph.json",
    }
    for name, path in surfaces.items():
        text = path.read_text()
        assert "Key Biodiversity Areas" not in text, f"{name} still advertises KBA"
