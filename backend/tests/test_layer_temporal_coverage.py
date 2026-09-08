# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Every layer IO PAN named must be anchored in time — this is the gate.

⛔ This file is deliberately RED until all thirteen are filled in. A layer with no
temporal coverage is not a cosmetic gap: it is a layer whose values cannot be
judged fit for modelling, because nobody can tell whether they are from 1934 or
2024. IO PAN raised precisely this on 2026-09-04.

⛔ Do NOT make this pass by deleting ids from the list below. The list is the
requirement. It shrinks only if Michal says a layer is out of scope.
"""
import datetime
import re
from pathlib import Path

import pytest

from layer_temporal_coverage import COVERAGE, KINDS, seed_rows

# The "Ocean Climatology" menu group, as Michal marked it on 2026-09-08.
IOPAN_LAYERS = (
    "woa-climatology",         # Ocean Climatology (WOA)
    "wod-oxygen",              # Historical Oxygen Profiles
    "memento",                 # Marine CH4 / N2O (MEMENTO)
    "geotraces",               # Trace Metals (GEOTRACES)
    "mosaic-sediment",         # Marine Sediment Carbon
    "methane-seeps",           # Methane Seeps (SEAFLEA)
    "oxygen-deox",             # Ocean Oxygen & Deoxygenation
    "arctic-rivers",           # Arctic River Inputs
    "arctic-catchments",       # Arctic Catchments
    "arctic-sediment-carbon",  # Arctic Sediment Carbon (CASCADE)
    "permafrost-thaw",         # Permafrost Thaw
    "sios-svalbard",           # SIOS Svalbard (Arctic)
    # A6 "Ocean carbon (GLODAP + SOCAT + Marine Carbon)" — a row of IO PAN's own
    # roadmap in AI-Wall/LAYER-PROPOSALS.md, and the only one of theirs the menu
    # group above does not contain. ⛔ ocean-acidification is anchored too but is
    # deliberately NOT listed: IO PAN did not name it, and this constant has to keep
    # meaning "what they asked for" rather than "what we happened to do".
    "ocean-carbon",           # A6 — GLODAP
    "ocean-co2-surface",      # A6 — SOCAT
    "marine-carbon",          # A6 — the synthesis
)

# ⛔ REMOVED from IOPAN_LAYERS on 2026-09-08 after checking the wiki instead of
# trusting this file. `seabed-substrate` appears nowhere in
# rare-seo/organizations/nauka/iopan/ or _archiwum/iopan-materials/ — not once. It
# traces to ONC's own lunch-and-learn deck and to a Mission Ocean grant narrative we
# wrote ourselves, where it links a source-to-sea story. Someone (me) folded a layer
# we value into a list whose whole job is to record what THEY asked for.
#
# It keeps its temporal anchor — the gate below still covers it — because the frame
# is about the data, not about who requested it. What changes is the label, and the
# label is the part that would have gone into an email to IO PAN.
OURS_NOT_THEIRS = (
    "seabed-substrate",       # Seabed Substrate — ours/ONC's interest, not IO PAN's ask
)

# The "Life & Geology" menu group, raised by Michal on 2026-09-08. ⛔ Deliberately
# NOT folded into IOPAN_LAYERS: that constant has to keep meaning "what IO PAN
# asked for", and these six were not on their list. They are a priority of ours,
# which is a different fact and gets a different name.
LIFE_AND_GEOLOGY_LAYERS = (
    "biodiversity-hotspots",   # OBIS Species (Deep)
    "hydrothermal-vents",      # Hydrothermal Vents
    "chess",                   # Chemosynthetic Sites — already anchored
    "seamounts",               # Seamounts
    "tectonic-plates",         # Tectonic Plates
    "bathymetry",              # Seafloor Bathymetry
)

BY_ID = {c.layer_id: c for c in COVERAGE}


def test_every_iopan_layer_has_a_time_frame():
    missing = [lid for lid in IOPAN_LAYERS if lid not in BY_ID]
    assert not missing, (
        f"{len(missing)} of {len(IOPAN_LAYERS)} layers carry no temporal anchor: {missing}. "
        "Each needs a row read AT THE SOURCE — dataset-level coverage counts, and is "
        "often present where per-record dates are absent (ChEssBase: no eventDate on "
        "any of 3,715 records, yet the GBIF dataset states 1977-2025)."
    )


def test_layers_we_track_for_ourselves_are_anchored_too():
    """A layer losing its IO PAN label must not lose its temporal frame with it."""
    missing = [lid for lid in OURS_NOT_THEIRS if lid not in BY_ID]
    assert not missing, f"no temporal anchor: {missing}"


def test_every_life_and_geology_layer_is_anchored():
    """Same gate, second group. A layer people can click on the globe and get no
    temporal answer for is the defect this whole table exists to prevent."""
    missing = [lid for lid in LIFE_AND_GEOLOGY_LAYERS if lid not in BY_ID]
    assert not missing, (
        f"{len(missing)} of {len(LIFE_AND_GEOLOGY_LAYERS)} Life & Geology layers "
        f"carry no temporal anchor: {missing}. A landform layer still has one — "
        "not 'when the seamount appeared', but which bathymetry vintage the "
        "catalogue was predicted from, which is what decides if it may be pooled."
    )


@pytest.mark.parametrize("layer_id", IOPAN_LAYERS)
def test_the_frame_is_usable_for_a_pooling_decision(layer_id):
    """A row exists — now is it good enough to decide 'may I merge this with new data?'"""
    c = BY_ID.get(layer_id)
    if c is None:
        pytest.skip("covered by test_every_iopan_layer_has_a_time_frame")
    # At least one bound. A frame open at one end still anchors the data; a frame
    # open at both ends is the same as saying nothing.
    assert c.start_year is not None or c.end_year is not None, layer_id
    assert c.kind in KINDS, f"{layer_id}: unknown kind {c.kind!r}"


def test_ids_match_the_frontend_layer_union():
    """A typo here would silently anchor a layer that does not exist."""
    union = Path("frontend/src/types/layers.ts").read_text().split("\n")[5]
    land = Path("frontend/src/types/landLayers.ts").read_text()
    known = set(re.findall(r'"([a-z0-9-]+)"', union)) | set(re.findall(r'id:\s*"([a-z0-9-]+)"', land))
    unknown = [lid for lid in IOPAN_LAYERS if lid not in known]
    assert not unknown, f"not real layer ids: {unknown}"


def test_no_row_invents_a_span_it_cannot_cite():
    for c in COVERAGE:
        assert c.wording.strip(), f"{c.layer_id}: coverage with no source wording"
        assert c.source_url.startswith("http"), f"{c.layer_id}: no citable source url"
        # Stored verbatim so a reader can check the claim against the publisher.
        datetime.date.fromisoformat(c.verified_on)


def test_spans_run_forwards_and_are_plausible():
    this_year = datetime.date.today().year
    for c in COVERAGE:
        if c.start_year is not None and c.end_year is not None:
            assert c.start_year <= c.end_year, c.layer_id
        for y in (c.start_year, c.end_year):
            if y is not None:
                # Nothing here predates instrumental oceanography; a 2-digit year or a
                # unit mix-up lands far outside this window rather than looking odd.
                assert 1750 <= y <= this_year + 1, f"{c.layer_id}: implausible year {y}"


def test_every_parameter_is_a_type_asyncpg_can_bind():
    """The bug this catches took production's migration down on 2026-09-08.

    asyncpg binds each parameter to a Postgres type BEFORE the query's own `::date`
    cast runs, so an ISO *string* for a DATE column dies with
    `'str' object has no attribute 'toordinal'` — a message naming neither the column
    nor the value. Every check in this file passed while that was broken, because
    none of them looked at what actually gets sent to the database.
    """
    for row in seed_rows():
        layer_id, start_year, end_year, kind, wording, source_url, verified_on = row
        assert isinstance(layer_id, str)
        assert start_year is None or isinstance(start_year, int)
        assert end_year is None or isinstance(end_year, int)
        assert isinstance(kind, str) and isinstance(wording, str)
        assert source_url is None or isinstance(source_url, str)
        # ⛔ datetime.date, never the string the table is written with.
        assert isinstance(verified_on, datetime.date), (
            f"{layer_id}: verified_on is {type(verified_on).__name__}, not datetime.date")


def test_seed_rows_covers_every_curated_entry():
    assert len(seed_rows()) == len(COVERAGE)


def test_every_anchor_actually_reaches_the_legend_panel():
    """A frame nobody can see is not a frame — this pins the cross-language seam.

    LegendPanel renders `coverage[s.layerId ?? s.id]`. If an id here does not match
    an entry over there, the row simply does not appear: no error, no warning, no
    red test. Michal's requirement was "widoczne na stronie", so the seam gets a
    gate rather than trust.

    ⚠️ `layerId` and `id` differ on purpose for some entries (a legend section can
    document a layer under its own doc id), which is why the component falls back
    and why this check accepts either.
    """
    panel = Path("frontend/src/components/LegendPanel.tsx").read_text()
    unreachable = []
    for c in COVERAGE:
        as_layer_id = f'layerId: "{c.layer_id}"' in panel
        as_doc_id = re.search(rf'\bid:\s*"{re.escape(c.layer_id)}"', panel) is not None
        if not (as_layer_id or as_doc_id):
            unreachable.append(c.layer_id)
    assert not unreachable, (
        f"anchored but invisible — no LAYER_STRUCT entry keys on these: {unreachable}"
    )


def test_the_two_kind_vocabularies_agree():
    """`kind` is spelled in three places: this module, a database CHECK constraint,
    and a TypeScript union. A value present in one but not another either fails the
    insert or renders `undefined` on the page — neither says which of the three is
    wrong, so the drift is caught here instead."""
    tsx = Path("frontend/src/components/panels/shared/TemporalFrame.tsx").read_text()
    union = re.search(r"export type CoverageKind\s*=(.*?);", tsx, re.S).group(1)
    ts_kinds = set(re.findall(r'"([a-z]+)"', union))
    assert ts_kinds == set(KINDS), (
        f"kind vocabularies drifted — only in Python: {set(KINDS) - ts_kinds}, "
        f"only in TypeScript: {ts_kinds - set(KINDS)}")
    meanings = set(re.findall(r"^\s{2}([a-z]+):\s+\"", tsx, re.M))
    assert meanings == set(KINDS), (
        f"every kind needs a plain-language meaning on screen; missing: {set(KINDS) - meanings}")


def test_no_variant_of_an_anchored_layer_is_left_without_its_frame():
    """A hex and a station of the SAME layer must both show the same frame.

    They did not: `geotraces-hexes` and `memento-hexes` resolved to nothing while
    `geotraces` and `memento` resolved fine, so the frame appeared or vanished
    depending on which rendering of one layer you happened to click. Nothing
    errored — the popup just quietly dropped a line.

    The rule this enforces: if a deck layer id the DetailPanel dispatches on begins
    with an anchored layer's id, it has to resolve to that layer.
    """
    dp = Path("frontend/src/components/DetailPanel.tsx").read_text()
    lc = Path("frontend/src/utils/layerConfig.ts").read_text()
    block = re.search(r"DECK_TO_TOGGLE[^{]*\{(.*?)\n\};", lc, re.S).group(1)
    mapping = dict(re.findall(r'"([^"]+)"\s*:\s*"([^"]+)"', block))
    anchored = {c.layer_id for c in COVERAGE}

    orphans = []
    for deck_id in sorted(set(re.findall(r'layer\s*===\s*"([^"]+)"', dp))):
        resolved = mapping.get(deck_id, deck_id)
        if resolved in anchored:
            continue
        # A variant like "<anchored>-hexes" / "-raster" / "-stations" that resolves
        # to something with no frame is the defect.
        for lid in anchored:
            if deck_id.startswith(lid + "-"):
                orphans.append(f"{deck_id} → {resolved} (should be {lid})")
                break
    assert not orphans, (
        "these renderings of an anchored layer show no time frame: " + "; ".join(orphans))
