# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import pathlib
import pytest
from backend.ingestion.memento_ingest import (build_samples, derive_casts, NO_VALUE,
                                              _leg_is_month_dated)

FIX = pathlib.Path(__file__).parent / "fixtures" / "memento"

pytestmark = pytest.mark.skipif(
    not (FIX / "leg_300_baltic.csv").exists(),
    reason="fixture is licence-restricted (MEMENTO terms of use — contributing scientist must "
           "be contacted before publishing results) and excluded from the public repository — "
           "see DATA-LICENCES.md",
)

def _read(name):
    return (FIX / name).read_text()

def test_baltic_ch4_only():
    rows = build_samples(_read("leg_300_baltic.csv"), "Baltic Sea CH4 profiles (2011 to 2013)")
    assert len(rows) > 900
    r = rows[0]
    assert r["set_name"].startswith("Baltic")
    assert r["depth_m"] == 10.0
    assert abs(r["lat"] - 57.116667) < 1e-5 and abs(r["lon"] - 17.666667) < 1e-5
    assert r["sample_time"].year == 2011
    # CH4 stored in params (ch4_kg), not first-class ch4 (nmol/l); flag captured
    assert r["params"]["ch4_kg"] is not None
    assert r["params"]["ch4_kg_flag"] == -1
    assert r["ch4"] is None and r["n2o"] is None  # this leg has neither nmol/l col

def test_sfb754_multiparam_and_sentinel():
    rows = build_samples(_read("leg_166_sfb754.csv"), "SFB754  (M77/3)")
    r = rows[0]
    assert r["n2o"] is not None                     # first-class n2o (nmol/l)
    assert r["temp"] is not None and r["sal"] is not None
    # -999.0 sentinel -> None (no3/no2/po4 were -999 in row 1)
    assert r["params"]["no3"] is None
    assert r["station"] == "022-1"
    # first-class values NOT duplicated in params; their flags remain
    assert "n2o" not in r["params"]                 # first-class value lives top-level only
    assert "n2o_flag" in r["params"]                # its flag stays in params

def test_derive_casts_groups_depths():
    rows = build_samples(_read("leg_166_sfb754.csv"), "SFB754  (M77/3)")
    casts = derive_casts(rows)
    assert len(casts) < len(rows)                   # multiple depths collapse to casts
    c = casts[0]
    assert c["n_samples"] >= 1
    assert c["has_n2o"] is True
    assert c["max_depth_m"] >= c["min_depth_m"]
    assert len(c["cast_id"]) == 16
    # surface representative value = shallowest non-null sample's gas
    assert "n2o_surf" in c


# ── how precisely the SOURCE dated each sample ──────────────────────────────
# ⛔ MEMENTO mixes real minute precision (2009-01-10 22:58) with records that
# carry only a date, in ONE column. Measured on production 2026-09-10:
# 59,295 of 218,271 samples (27%) sit at exactly 00:00, and 8,822 of those on
# the first of a month. Midnight is a real time and the first is a real day —
# so the parsed VALUE can never tell a precise cast from a padded date. Only
# which format matched can, and only at the moment it matches.

from backend.ingestion.memento_ingest import _parse_time


def test_a_time_of_day_from_the_source_is_reported_as_minute_precision():
    dt, prec = _parse_time("2009-01-10 22:58")
    assert prec == "minute"
    assert (dt.hour, dt.minute) == (22, 58)


def test_seconds_are_still_minute_precision():
    _dt, prec = _parse_time("2009-01-10 22:58:31")
    assert prec == "minute", "a seconds field is more precision, not less"


def test_a_bare_date_is_reported_as_day_precision_not_as_midnight():
    dt, prec = _parse_time("2009-01-10")
    assert prec == "day", (
        "a date with no time parsed to midnight and was indistinguishable "
        "from a cast genuinely taken at 00:00"
    )
    assert (dt.hour, dt.minute) == (0, 0)


def test_a_genuine_midnight_cast_keeps_minute_precision():
    """⛔ The whole point. Same instant, different claim — and the difference
    comes from the string the source sent, not from the value we parsed."""
    dt_padded, prec_padded = _parse_time("2009-01-01")
    dt_real, prec_real = _parse_time("2009-01-01 00:00")
    assert dt_padded == dt_real, "fixture problem: these should be the same instant"
    assert (prec_padded, prec_real) == ("day", "minute"), (
        "two identical timestamps carry different claims about how well the "
        "source knew them; collapsing them is the defect"
    )


def test_an_unparseable_time_gives_no_value_and_no_claim():
    assert _parse_time("not a date") == (None, None)
    assert _parse_time("") == (None, None)
    assert _parse_time(None) == (None, None)


def test_the_precision_reaches_the_row_not_only_the_parser():
    """⛔ Asserting the KEY exists proves nothing.

    Caught by sabotage 2026-09-10: an earlier version of this test checked
    `"time_precision" in r` and that the values were a subset including None —
    so hardcoding every row to None passed it. A guard that a null value
    satisfies is not a guard. Assert the real distribution instead.
    """
    rows = build_samples(_read("leg_166_sfb754.csv"), "SFB754  (M77/3)")
    assert rows, "fixture problem: no rows parsed, the assertions below prove nothing"
    got = {r.get("time_precision") for r in rows}
    assert got <= {"minute", "day", None}, f"unexpected precision values: {got}"
    assert got & {"minute", "day"}, (
        "every row came back with no precision at all — the parser's verdict "
        "is not reaching the row"
    )
    # and it must agree with the sample_time it sits beside
    for r in rows:
        if r["sample_time"] is None:
            assert r["time_precision"] is None
        else:
            assert r["time_precision"] in ("minute", "day"), r


def test_the_precision_reaches_the_cast_rollup_too():
    rows = build_samples(_read("leg_166_sfb754.csv"), "SFB754  (M77/3)")
    casts = derive_casts(rows)
    assert casts, "fixture problem: no casts derived"
    got = {c.get("time_precision") for c in casts}
    assert got & {"minute", "day"}, (
        "the rollup dropped the precision the samples carried — the map reads "
        "casts, so this is the half that matters"
    )


# ── the padding MEMENTO does inside the string ──────────────────────────────
# ⛔ A correction to the commit that added time_precision. That change recorded
# which FORMAT matched, which is honest and — measured against every leg on
# production — useless here: MEMENTO always ships a full 'YYYY-MM-DD HH:MM'
# and pads the time to 00:00 INSIDE it. 100% of samples came back "minute",
# including all 59,295 at midnight.
#
# What does show is cardinality. Real fixture `leg_300_baltic.csv`: 978 of 978
# rows carry the identical string '2011-08-01 00:00'. 978 bottles were not
# filled in one minute. Fixture `leg_166_sfb754.csv`: 230 rows, real varying
# minutes, no midnight at all.
#
# Production, all 294 legs: 27 have exactly one distinct timestamp, all 27 of
# those at midnight, 5,688 samples, 5,588 of them on the 1st of a month.

def test_a_leg_stamped_only_on_first_of_month_midnights_is_month_dated():
    rows = build_samples(_read("leg_300_baltic.csv"),
                         "Baltic Sea CH4 profiles (2011 to 2013)")
    assert len(rows) > 900, "fixture problem: the Baltic leg did not parse"
    stamps = {r["sample_time"] for r in rows}
    assert len(stamps) > 1, (
        "fixture problem: this leg is supposed to carry SEVERAL month stamps "
        "(11 of them), so a one-timestamp rule would not describe it"
    )
    assert {r["time_precision"] for r in rows} == {"month"}, (
        "978 samples, every one stamped midnight on the first of a month, are "
        "still presented as timed to the minute"
    )


def test_a_leg_with_real_varying_times_keeps_minute_precision():
    """⛔ The scalpel half. 59,295 midnight samples exist across the layer and
    most sit in legs whose other samples carry real minutes — judging on
    midnight alone would mislabel them."""
    rows = build_samples(_read("leg_166_sfb754.csv"), "SFB754  (M77/3)")
    assert len({r["sample_time"] for r in rows}) > 1, "fixture problem"
    assert {r["time_precision"] for r in rows} == {"minute"}


def test_one_sample_is_not_enough_evidence():
    """A leg of one shows no pattern. The smallest real all-padded leg on
    production holds 4 samples, so this guard costs nothing."""
    import datetime as _d
    t = _d.datetime(2011, 8, 1, 0, 0, tzinfo=_d.timezone.utc)
    assert _leg_is_month_dated([{"sample_time": t}]) is False
    assert _leg_is_month_dated([{"sample_time": t}, {"sample_time": t}]) is True


def test_midnight_on_a_day_that_is_not_the_first_is_left_alone():
    """⛔ Midnight is a real time. Only the FIRST-of-month shape is the pad."""
    import datetime as _d
    t = _d.datetime(2011, 8, 17, 0, 0, tzinfo=_d.timezone.utc)
    assert _leg_is_month_dated([{"sample_time": t}] * 5) is False


def test_the_first_of_a_month_at_a_real_hour_is_left_alone():
    import datetime as _d
    t = _d.datetime(2011, 8, 1, 13, 42, tzinfo=_d.timezone.utc)
    assert _leg_is_month_dated([{"sample_time": t}] * 5) is False


def test_one_unpadded_sample_saves_the_whole_leg_from_being_relabelled():
    """⛔ All-or-nothing on purpose. 41 production legs are MIXED and their
    2,098 midnight-on-the-1st samples stay "minute": in a leg with real
    varying times, such a sample may be a genuine cast and nothing separates
    it from a pad."""
    import datetime as _d
    pad = _d.datetime(2011, 8, 1, 0, 0, tzinfo=_d.timezone.utc)
    real = _d.datetime(2011, 8, 3, 14, 5, tzinfo=_d.timezone.utc)
    assert _leg_is_month_dated([{"sample_time": pad}] * 9 + [{"sample_time": real}]) is False
