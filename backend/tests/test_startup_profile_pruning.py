# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""A startup profile must never offer a layer that is switched off.

The welcome screen is the first thing a new visitor clicks, and its modes were
seeded once and never re-checked against `layer_config`. On 2026-09-14 the two
AIS layers were switched off; the "Vessel Surveillance" mode kept offering them,
so choosing it turned two layers on and showed an empty map. Nothing failed,
nothing was logged, and every existing test stayed green — they only asserted
that a seeded layer id EXISTS, never that it is still alive.

⛔ Deleting that one profile would have fixed the symptom and left the mechanism:
the next layer switched off would rot the next mode the same way.
"""
import pytest

from main import prune_dead_profile_layers
import profiles as _profiles
from startup_seeds import WITHDRAWN_LAYER_IDS

LIVE = {"contracts", "argo", "seamounts"}


def _p(pid, layers):
    return {"id": pid, "section": "ocean", "order_idx": 10, "layers": layers,
            "label": {"en": pid}, "description": {}, "accent": None, "views": {}}


def test_a_profile_of_only_dead_layers_is_hidden():
    kept, notes = prune_dead_profile_layers([_p("ghost", ["ais-live", "vessel-events"])], LIVE)
    assert kept == []
    assert any("hidden" in n for n in notes)


def test_a_mixed_profile_keeps_only_what_is_alive():
    kept, _ = prune_dead_profile_layers([_p("mixed", ["contracts", "ais-live", "argo"])], LIVE)
    assert len(kept) == 1
    assert kept[0]["layers"] == ["contracts", "argo"]


def test_a_healthy_profile_passes_through_untouched():
    """The common case must cost nothing and change nothing — including the
    other keys, which a careless rebuild would drop."""
    original = _p("fine", ["contracts", "argo"])
    kept, notes = prune_dead_profile_layers([original], LIVE)
    assert kept == [original]
    assert notes == []


def test_an_empty_live_set_is_refused_not_obeyed():
    """⛔ The failure this guard exists for: if the layer_config read comes back
    empty — failed query, fresh database, a typo in the status filter — then
    "nothing is alive" is indistinguishable from "everything is dead". Obeying it
    would hide every mode and blank the welcome screen for every visitor at once.
    """
    given = [_p("a", ["contracts"]), _p("b", ["argo"])]
    kept, notes = prune_dead_profile_layers(given, set())
    assert kept == given
    assert any("skipped" in n for n in notes)


def test_what_was_removed_is_named():
    """A silent prune trades one invisible problem for another — the operator has
    to be able to see WHICH layer took a mode down."""
    _, notes = prune_dead_profile_layers([_p("mixed", ["contracts", "ais-live"])], LIVE)
    assert any("ais-live" in n for n in notes)


def test_no_seed_profile_references_a_withdrawn_layer():
    """The code-side half of the same rule: a layer withdrawn for licence reasons
    must not be reachable from the welcome screen of a fresh database either."""
    seeded = {lid for p in _profiles.PROFILE_SEED for lid in p["layers"]}
    withdrawn = set(WITHDRAWN_LAYER_IDS)
    # ⛔ Both sides asserted non-empty first: an empty set on either side makes
    # the intersection below empty for a reason that has nothing to do with the
    # thing being tested.
    assert seeded, "PROFILE_SEED carries no layers at all — the check would pass vacuously"
    assert withdrawn, "WITHDRAWN_LAYER_IDS is empty — the check would pass vacuously"
    assert seeded & withdrawn == set()


def test_every_seed_profile_still_offers_something():
    assert _profiles.PROFILE_SEED, "no seed profiles at all"
    for p in _profiles.PROFILE_SEED:
        assert p["layers"], f"seed {p['id']} offers no layers"
