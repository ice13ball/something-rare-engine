# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""profiles.KNOWN_LAYER_IDS is a hand-kept twin of LAYER_DEFAULTS_PY (and of the frontend's
LAYER_TO_SUBGROUP). A layer missing from it can never be named by a startup profile — validate_profile
rejects the id — and nothing else notices.

Compared as run-time objects, not source text. UNLISTED records the layers that are absent today: a
known gap, not a verdict. When one is fixed this test fails until the entry is deleted, so the set can
only shrink.
"""
from __future__ import annotations

import profiles
from startup_seeds import LAYER_DEFAULTS_PY

# Found 2026-10-06 while adding glodap-points; the frontend's LAYER_TO_SUBGROUP lacks the same three
# (menu-taxonomy-covers-layer-defaults.test.ts). Whether profiles may reference them is Michal's call.
UNLISTED = {"marhys", "greenland-sea-poc-aoc2025", "svalbard-fjords-primary-production"}


def test_every_rendered_layer_is_a_known_profile_layer_bar_the_recorded_gaps():
    ids = {d["id"] for d in LAYER_DEFAULTS_PY}
    assert ids - profiles.KNOWN_LAYER_IDS == UNLISTED


def test_known_layer_ids_name_no_layer_the_registry_lacks():
    ids = {d["id"] for d in LAYER_DEFAULTS_PY}
    assert profiles.KNOWN_LAYER_IDS - ids == set()


def test_a_profile_may_name_glodap_points():
    profiles.validate_profile(
        {"id": "glodap-demo", "section": "ocean", "order_idx": 1, "layers": ["ocean-carbon", "glodap-points"],
         "label": {"en": "X"}, "description": {}, "accent": None},
        profiles.KNOWN_LAYER_IDS,
    )
