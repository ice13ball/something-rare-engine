# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""A naive datetime handed to TIMESTAMPTZ is silently read in the server's zone.

asyncpg passes a naive `datetime` through unchanged, and PostgreSQL then
interprets it in the SESSION's TimeZone. On this VPS that is Europe/Warsaw, so
a UTC instant stripped of its tzinfo lands one or two hours early — and a
date-only value lands on the previous DAY.

Measured on production 2026-09-10 over noaa_corals_records, 1,504,031 dated
rows, queried in UTC:

    22:00:00   1,204,413    midnight at UTC+2  (Warsaw summer)
    23:00:00     292,569    midnight at UTC+1  (Warsaw winter)
    23:50:39       6,665    midnight at Warsaw's pre-1880 LMT
    00:00:00         384    genuinely midnight UTC

Four distinct times across a million and a half records, three of them the
server's own midnight. 99.6% of the layer read a day early. The cause was one
call: `datetime.utcfromtimestamp()`, which returns naive.

⚠️ The pre-1900 dates in this table were separately suspected of being
sentinels. They are not: the neighbourhood shows a continuous distribution —
1878:206, 1879:878, 1883:253, 1884:420, 1885:814, 1886:361, 1890:142, 1902:314,
1906:455, 1908:545, 1909:601 — which is what nineteenth-century expedition and
museum collections look like. The dates are real; only the time-of-day was ours.

⛔ Guards the RULE, not the one call, because the same shape can appear in any
ingest that writes a TIMESTAMPTZ.
"""
import ast
import datetime
import pathlib
import sys

import pytest

ROOT   = pathlib.Path(__file__).resolve().parents[1]
INGEST = ROOT / "ingestion"

sys.path.insert(0, str(ROOT))


def _naive_utc_calls(path: pathlib.Path) -> list[int]:
    """Line numbers of `datetime.utcfromtimestamp` / `datetime.utcnow`."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("utcfromtimestamp", "utcnow")):
            out.append(node.lineno)
    return out


def test_the_fixture_walks_a_real_corpus():
    files = sorted(INGEST.glob("*.py"))
    assert len(files) > 20, f"fixture problem: only {len(files)} ingest modules found"


def test_no_ingest_builds_a_naive_utc_datetime():
    # ⛔ Both of these return a NAIVE datetime. utcnow() is additionally
    # deprecated in 3.12. Neither may reach a TIMESTAMPTZ column.
    offenders = {p.name: lines for p in sorted(INGEST.glob("*.py"))
                 if (lines := _naive_utc_calls(p))}
    assert not offenders, (
        f"naive-UTC constructors in {offenders}. Handed to a TIMESTAMPTZ they "
        "are read in the server's zone — Europe/Warsaw here — and a date-only "
        "value lands on the previous day."
    )


def test_the_detector_would_actually_fire():
    # Prove the AST walk catches the exact call that caused this.
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write("from datetime import datetime\n"
                "def g(v):\n    return datetime.utcfromtimestamp(v / 1000.0)\n")
        tmp = pathlib.Path(f.name)
    try:
        assert _naive_utc_calls(tmp) == [3], "the detector misses utcfromtimestamp"
    finally:
        tmp.unlink()


# ── The parser this was found in ────────────────────────────────────────────

@pytest.mark.parametrize("value,expect", [
    (1434326400000, datetime.datetime(2015, 6, 15, 0, 0, tzinfo=datetime.timezone.utc)),
    ("2015-06-15", datetime.datetime(2015, 6, 15, 0, 0, tzinfo=datetime.timezone.utc)),
    ("2015-06-15T12:30:00", datetime.datetime(2015, 6, 15, 12, 30, tzinfo=datetime.timezone.utc)),
    ("2015-06-15T12:30:00Z", datetime.datetime(2015, 6, 15, 12, 30, tzinfo=datetime.timezone.utc)),
])
def test_every_accepted_shape_comes_back_aware_and_in_utc(value, expect):
    from ingestion.noaa_corals_ingest import _parse_obs_date
    got = _parse_obs_date(value)
    assert got is not None, f"{value!r} no longer parses at all"
    assert got.tzinfo is not None, (
        f"{value!r} parsed to a NAIVE datetime — PostgreSQL will read it in the "
        "server's zone and the date moves"
    )
    assert got.utcoffset() == datetime.timedelta(0), f"{value!r} is not UTC"
    assert got == expect


@pytest.mark.parametrize("bad", [None, "", "not a date", "15/06/2015"])
def test_an_unparseable_value_is_still_none_not_a_guess(bad):
    from ingestion.noaa_corals_ingest import _parse_obs_date
    assert _parse_obs_date(bad) is None


def test_a_date_only_value_does_not_shift_a_day_under_a_non_utc_session():
    # The whole failure, reproduced: take the aware value, drop its tzinfo the
    # way the old code did, and read it as Warsaw local — the calendar date
    # moves back one day.
    from ingestion.noaa_corals_ingest import _parse_obs_date
    from zoneinfo import ZoneInfo
    aware = _parse_obs_date("2015-06-15")
    assert aware.date() == datetime.date(2015, 6, 15)

    naive = aware.replace(tzinfo=None)                       # what utcfromtimestamp gave
    as_warsaw = naive.replace(tzinfo=ZoneInfo("Europe/Warsaw"))
    assert as_warsaw.astimezone(datetime.timezone.utc).date() == datetime.date(2015, 6, 14), (
        "fixture problem: the day-shift this test describes did not reproduce, "
        "so the assertion above proves nothing"
    )
