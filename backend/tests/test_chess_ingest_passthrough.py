# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""ChEssBase ingestion must not rewrite a source coordinate.

⛔ WHY THIS EXISTS. From 2026-04-07 to 2026-09-22 `chess_ingest.py` carried a
`_COORD_OVERRIDES` table with one entry, silently relocating the whale-fall
record `Grey Whale Carcass, San Diego Trough` from where ChEssBase puts it to
where Smith & Baco 2003 put it. The override was defensible on the facts — the
source coordinate is +122 m above sea level on GEBCO while the same record
claims 1240 m depth — and wrong on the principle. On 2026-09-22 we told EurOBIS
in writing that we reproduce sources unchanged while that line said otherwise.

⚠️ This test asserts on DATA COMING OUT OF THE PARSER, not on the shape of the
source file. A test that greps for the absent constant would pass against any
new override spelled differently, and would fail against a harmless rename.
This one drives the real `fetch_chess_occurrences` code path with a stubbed
HTTP layer and checks the coordinates it yields.
"""

import asyncio
import pytest

from backend.ingestion import chess_ingest

# The real record, verbatim from the GBIF API on 2026-09-22
# (https://api.gbif.org/v1/occurrence/5789994787). Its coordinates are the ones
# ChEssBase publishes — inland California, contradicting its own stated depth.
_SOURCE_RECORD = {
    "gbifID": "5789994787",
    "locality": "Grey Whale Carcass, San Diego Trough",
    "decimalLatitude": 33.349998,
    "decimalLongitude": -117.300003,
    "depth": 1240.0,
    "species": "Boudemos flokati",
    "phylum": "Annelida",
    "class": "Polychaeta",
    "family": "",
    "institutionCode": "",
}

# What the removed override used to substitute. Nothing may produce these again.
_OVERRIDE_LAT, _OVERRIDE_LON = 32.5833, -117.4833


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class _FakeClient:
    """Stands in for httpx.AsyncClient: one page, then end of records."""

    def __init__(self, *_args, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def get(self, _url, params=None):
        return _FakeResponse({"results": [_SOURCE_RECORD], "endOfRecords": True})


@pytest.fixture
def stub_gbif(monkeypatch):
    monkeypatch.setattr(chess_ingest.httpx, "AsyncClient", _FakeClient)


def test_source_coordinate_survives_ingestion(stub_gbif):
    """The parser yields the coordinate the source shipped, to full precision."""
    records = asyncio.run(chess_ingest.fetch_chess_occurrences())

    assert len(records) == 1, "the stub serves exactly one page with one record"
    rec = records[0]

    assert rec["occurrence_id"] == "5789994787"
    assert rec["lat"] == pytest.approx(_SOURCE_RECORD["decimalLatitude"], abs=1e-9)
    assert rec["lon"] == pytest.approx(_SOURCE_RECORD["decimalLongitude"], abs=1e-9)


def test_the_old_override_target_is_not_produced(stub_gbif):
    """Guards the specific substitution that was removed on 2026-09-22.

    Kept separate from the test above so a failure names the regression rather
    than just reporting a coordinate mismatch.
    """
    rec = asyncio.run(chess_ingest.fetch_chess_occurrences())[0]

    relocated = (
        abs(rec["lat"] - _OVERRIDE_LAT) < 1e-4
        and abs(rec["lon"] - _OVERRIDE_LON) < 1e-4
    )
    assert not relocated, (
        "the San Diego Trough whale fall was moved to the Smith & Baco 2003 "
        "position — a coordinate override has been reintroduced. Report source "
        "errors to the publisher; do not patch them here."
    )


def test_depth_and_locality_pass_through_untouched(stub_gbif):
    """The fields that make the source's own contradiction visible must survive.

    The record is only recognisable as an error because it carries a 1240 m
    depth next to a coordinate on dry land. Dropping either field would hide it.
    """
    rec = asyncio.run(chess_ingest.fetch_chess_occurrences())[0]

    assert rec["depth_m"] == 1240.0
    assert rec["locality"] == "Grey Whale Carcass, San Diego Trough"
