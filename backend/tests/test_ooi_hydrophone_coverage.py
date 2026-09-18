# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Every OOI deployment file that carries a hydrophone is fetched — all nine.

Measured 2026-09-18 by downloading `deployment/` from
oceanobservatories/asset-management@master and grepping all 185 CSVs:

    185 files · 9 mention HYDBBA/HYDLFA · we fetched 4

The four that were listed carried six instruments; the five that were not
carried six more. Half the layer was missing and nothing said so — the fetch
loop walks its own list, so an absent file cannot fail, cannot warn, and cannot
be counted. That is the shape this file guards: not "does the parser work"
(it did) but "is the list the whole list".

⚠️ The old comment justified the four as "Regional Cabled Array sites", which
was wrong in both directions: CE02SHBP/CE04OSBP belong to Coastal Endurance,
and RS01SUM1/RS03CCAL/RS03ECAL are RCA sites that were missing anyway. A scope
sentence that does not match the list is worse than none, because it reads like
a decision.
"""
import logging

import pytest

from ingestion import acoustic_ooi_ingest as mod

_ADDED_2026_09_18 = ["CE02SHBP", "CE04OSBP", "RS01SUM1", "RS03CCAL", "RS03ECAL"]
_ALREADY_THERE = ["RS01SBPS", "RS01SLBS", "RS03AXPS", "RS03AXBS"]


# ─────────────────────────────────────────────────────────────────────────────
# The list is the whole list.
# ─────────────────────────────────────────────────────────────────────────────

def test_all_nine_arrays_with_hydrophones_are_listed():
    listed = set(mod.DEPLOYMENT_ARRAYS_WITH_HYDROPHONES)
    missing = (set(_ADDED_2026_09_18) | set(_ALREADY_THERE)) - listed
    assert missing == set(), (
        f"{sorted(missing)} carry hydrophones in the source and are not fetched")
    assert len(mod.DEPLOYMENT_ARRAYS_WITH_HYDROPHONES) == 9


def test_the_five_that_were_missing_are_named_one_by_one():
    """⛔ Spelled out, not counted: a future edit that drops CE04OSBP while
    adding something else would keep the count at nine and hide the loss."""
    for array in _ADDED_2026_09_18:
        assert array in mod.DEPLOYMENT_ARRAYS_WITH_HYDROPHONES, (
            f"{array} was added on 2026-09-18 after measuring the source; "
            "removing it silently drops instruments again")


def test_no_array_is_listed_twice():
    listed = mod.DEPLOYMENT_ARRAYS_WITH_HYDROPHONES
    assert len(listed) == len(set(listed))


# ─────────────────────────────────────────────────────────────────────────────
# ⭐ The registry IS the wiring — a name that reaches no URL fetches nothing.
# ─────────────────────────────────────────────────────────────────────────────

def test_every_listed_array_produces_exactly_one_url():
    assert len(mod._ARRAY_CSV_URLS) == len(mod.DEPLOYMENT_ARRAYS_WITH_HYDROPHONES)
    for array in mod.DEPLOYMENT_ARRAYS_WITH_HYDROPHONES:
        matching = [u for u in mod._ARRAY_CSV_URLS if f"/{array}_Deploy.csv" in u]
        assert len(matching) == 1, f"{array} maps to {len(matching)} URLs, expected 1"


def test_urls_are_derived_not_hand_written():
    for url in mod._ARRAY_CSV_URLS:
        assert url.startswith(mod._DEPLOY_BASE) and url.endswith("_Deploy.csv")


def test_the_snapshot_covers_exactly_the_fetched_arrays():
    assert set(mod.HYDROPHONES_SEEN) == set(mod.DEPLOYMENT_ARRAYS_WITH_HYDROPHONES)


@pytest.mark.parametrize("array,designators", sorted(mod.HYDROPHONES_SEEN.items()))
def test_each_recorded_designator_belongs_to_its_array_and_parses_as_a_hydrophone(array, designators):
    assert designators, f"{array} is listed with no instrument at all"
    for d in designators:
        assert d.startswith(array + "-"), f"{d} is filed under {array}"
        assert mod._is_hydrophone(d), (
            f"{d} was measured as a hydrophone but the parser's own filter "
            "rejects it — the filter and the snapshot disagree")


def test_twelve_instruments_in_total():
    """The number the fix is worth: 6 before, 12 after."""
    total = sum(len(v) for v in mod.HYDROPHONES_SEEN.values())
    before = sum(len(mod.HYDROPHONES_SEEN[a]) for a in _ALREADY_THERE)
    assert (before, total) == (6, 12), f"{before} -> {total}, expected 6 -> 12"


# ─────────────────────────────────────────────────────────────────────────────
# The fetch path itself, with the network stubbed out.
# ─────────────────────────────────────────────────────────────────────────────

_HEADER = "Reference Designator,startDateTime,stopDateTime,lat,lon,deployment_depth"


class _Resp:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


def _stub_source(monkeypatch, per_array: dict[str, str]):
    """Serve a canned CSV per array; anything unlisted gets a header only."""
    async def fake_get(client, url, label=None, **kw):
        array = url.rsplit("/", 1)[-1].replace("_Deploy.csv", "")
        return _Resp(per_array.get(array, _HEADER))

    monkeypatch.setattr(mod, "get_with_retry", fake_get)


async def test_a_designator_from_a_newly_added_array_reaches_the_rows(monkeypatch):
    """⛔ Guard the call site: listing CE04OSBP is worthless if the loop that
    walks the list never reads it."""
    _stub_source(monkeypatch, {
        "CE04OSBP": "\n".join([
            _HEADER,
            "CE04OSBP-LJ01C-11-HYDBBA105,2015-07-05T00:00:00,2016-07-01T00:00:00,44.36,-124.95,580",
            "CE04OSBP-LJ01C-11-HYDBBA110,2021-08-01T00:00:00,,44.36,-124.95,581",
        ]),
    })
    rows = await mod.fetch_ooi_stations()
    ids = {r["station_id"] for r in rows}
    assert ids == {"ooi:CE04OSBP-LJ01C-11-HYDBBA105", "ooi:CE04OSBP-LJ01C-11-HYDBBA110"}
    open_cycle = next(r for r in rows if r["station_id"].endswith("HYDBBA110"))
    assert open_cycle["deploy_end"] is None, "an open deployment cycle read as ended"


async def test_deployment_cycles_collapse_to_one_station_with_the_earliest_start(monkeypatch):
    _stub_source(monkeypatch, {
        "RS01SUM1": "\n".join([
            _HEADER,
            "RS01SUM1-LJ01B-05-HYDLFA104,2019-06-01T00:00:00,2020-06-01T00:00:00,44.5,-125.1,774",
            "RS01SUM1-LJ01B-05-HYDLFA104,2015-09-01T00:00:00,2016-09-01T00:00:00,44.5,-125.1,774",
        ]),
    })
    rows = await mod.fetch_ooi_stations()
    assert len(rows) == 1
    assert rows[0]["deploy_start"].year == 2015, "the earliest cycle did not win"
    assert rows[0]["deploy_end"].year == 2020


async def test_a_row_without_coordinates_is_dropped_loudly(monkeypatch, caplog):
    """⛔ Missing and broken must not look the same. A deployment cycle with no
    position cannot be mapped — but it must not vanish in silence either."""
    _stub_source(monkeypatch, {
        "RS03CCAL": "\n".join([
            _HEADER,
            "RS03CCAL-MJ03F-06-HYDLFA305,2018-07-01T00:00:00,,,,1527",
        ]),
    })
    with caplog.at_level(logging.WARNING):
        rows = await mod.fetch_ooi_stations()

    assert rows == []
    assert any("HYDLFA305" in r.getMessage() and "no position" in r.getMessage()
               for r in caplog.records), "a positionless deployment left no trace"


async def test_an_array_that_goes_empty_upstream_is_a_warning_not_a_quiet_zero(monkeypatch, caplog):
    """The failure this whole file exists for, in its future form: the fetch
    succeeds, the file parses, and the instruments are simply gone."""
    _stub_source(monkeypatch, {})          # every array returns a bare header
    with caplog.at_level(logging.WARNING):
        rows = await mod.fetch_ooi_stations()

    assert rows == []
    warned = {r.getMessage() for r in caplog.records}
    for array in mod.DEPLOYMENT_ARRAYS_WITH_HYDROPHONES:
        assert any(array in m and "NO hydrophone rows" in m for m in warned), (
            f"{array} produced nothing and said nothing")


async def test_a_designator_that_disappears_from_one_array_is_named(monkeypatch, caplog):
    _stub_source(monkeypatch, {
        "CE04OSBP": "\n".join([
            _HEADER,
            "CE04OSBP-LJ01C-11-HYDBBA105,2015-07-05T00:00:00,,44.36,-124.95,580",
        ]),
    })
    with caplog.at_level(logging.WARNING):
        await mod.fetch_ooi_stations()

    assert any("no longer lists" in r.getMessage() and "HYDBBA110" in r.getMessage()
               for r in caplog.records), "the vanished instrument was not named"
