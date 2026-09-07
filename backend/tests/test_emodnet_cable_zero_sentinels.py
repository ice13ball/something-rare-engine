# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""EMODnet ships "unknown" as 0. It must not reach the panel as a measurement.

Measured against the raw WFS on 2026-08-27 (not inferred from our own tables):
`emodnet:pcablesnve` returns 918 features with NO nulls in either field —
`driftsatta` is 0 on 228 of them and `spenning_k` on 14, NorNed included.
NorNed is really 450 kV, commissioned 2008.

The zero is the upstream's. Our job is to stop repeating it as fact.
"""
from __future__ import annotations

from ingestion.emodnet_cables_ingest import (
    _drop_zero_sentinels,
    _map_pcablesnve,
    _ZERO_IS_MISSING,
)

# Shape copied from the live WFS response for one of NorNed's three segments.
NORNED_RAW = {
    "properties": {
        "lokalid": "A02D87DB-B3F6-464D-BB3E-F85514DC6012",
        "navn": "NorNed",
        "eier": "STATNETT SF",
        "spenning_k": 0.0,
        "driftsatta": 0,
    },
    "geometry": {"type": "LineString", "coordinates": [[5.0, 58.0], [6.0, 57.0]]},
}


def test_the_mapper_still_reproduces_the_upstream_zero():
    """The defect is upstream's, and the mapper is a faithful mirror.

    Asserted so the guard below is known to be doing the work — if the mapper
    ever starts nulling this itself, this test says so instead of the guard
    silently becoming decoration.
    """
    norm = _map_pcablesnve(NORNED_RAW)
    assert norm["voltage_kv"] == 0.0
    assert norm["inst_year"] == 0


def test_zero_voltage_and_zero_year_become_missing():
    norm = _drop_zero_sentinels(_map_pcablesnve(NORNED_RAW))
    assert norm["voltage_kv"] is None
    assert norm["inst_year"] is None
    assert norm["name"] == "NorNed"          # untouched
    assert norm["operator"] == "STATNETT SF"


def test_real_values_survive():
    """The guard must not eat data. 450 kV / 2008 is what NorNed actually is."""
    raw = {**NORNED_RAW, "properties": {**NORNED_RAW["properties"],
                                        "spenning_k": 450.0, "driftsatta": 2008}}
    norm = _drop_zero_sentinels(_map_pcablesnve(raw))
    assert norm["voltage_kv"] == 450.0
    assert norm["inst_year"] == 2008


def test_only_the_two_fields_that_cannot_be_zero_are_touched():
    """⛔ 0 is a legitimate value elsewhere — do not widen this blindly.

    A 0 km segment is a data error worth seeing, not a null to hide.
    """
    assert set(_ZERO_IS_MISSING) == {"voltage_kv", "inst_year"}
    norm = _drop_zero_sentinels({"length_km": 0, "voltage_kv": 0})
    assert norm["length_km"] == 0
    assert norm["voltage_kv"] is None


def test_none_passes_through_unchanged():
    norm = _drop_zero_sentinels({"voltage_kv": None, "inst_year": None})
    assert norm == {"voltage_kv": None, "inst_year": None}


# ── The wiring, not just the helper ─────────────────────────────────────────
# ⚠️ The five tests above call `_drop_zero_sentinels` directly, so they stay
# green even if nothing calls it — a guard that is never reached looks exactly
# like a guard that works. This one drives `fetch_all_layers`, the only path
# production uses, with the WFS stubbed out.
import pytest

from ingestion import emodnet_cables_ingest as ingest


@pytest.mark.asyncio
async def test_fetch_all_layers_nulls_the_zeros_end_to_end(monkeypatch):
    async def fake_fetch(_client, layer):
        return [NORNED_RAW] if layer == "pcablesnve" else []

    monkeypatch.setattr(ingest, "_fetch_one_layer", fake_fetch)

    rows = {layer: items async for layer, items in ingest.fetch_all_layers()}
    norned = rows["pcablesnve"]
    assert len(norned) == 1, "the stubbed feature should have normalized"
    assert norned[0]["voltage_kv"] is None
    assert norned[0]["inst_year"] is None
