# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""SOCATv2026 point-observation parser, run on REAL rows of the official file
(tests/fixtures/socat_points/, README.md says which cruise shows which trap). Each test guards one
silent corruption; none greps source text."""
import math
import pathlib
from collections import Counter
from datetime import datetime, timedelta, timezone

import pytest

from ingestion import socat_points_parse as P
from ingestion import socat_points_rules as R

FIX = pathlib.Path(__file__).parent / "fixtures" / "socat_points"
MAIN = FIX / "SOCATv2026_excerpt.tsv"
FLAGE = FIX / "SOCATv2026_FlagE_excerpt.tsv"
UTC = timezone.utc

# rows per cruise in the main excerpt (README.md; windows of 100 rows, two whole short cruises)
ROWS = {"06AQ19911114": 100, "06AQ20200801": 100, "06AQ20241224": 100, "11BE20021104": 100,
        "31HO19571021": 100, "320620060130": 100, "33GC20040908": 100, "34FM20251127": 100,
        "34FP20031001": 100, "64SA20060719": 185, "74P220080731": 10, "76XL20160724": 100}


def _open(path):
    return path.open(encoding="utf-8", newline="")


def _raw_rows(path, expocode):
    """Data rows of one cruise as lists of the 32 text fields, straight from the fixture."""
    with _open(path) as fh:
        return [ln.rstrip("\r\n").split("\t") for ln in fh
                if ln.startswith(expocode + "\t") and ln.count("\t") == 31]


@pytest.fixture(scope="module")
def main_records():
    with _open(MAIN) as fh:
        return list(P.iter_records(fh))


@pytest.fixture(scope="module")
def flage_records():
    with _open(FLAGE) as fh:
        return list(P.iter_records(fh))


def _of(records, cls, expocode=None):
    return [r for r in records if isinstance(r, cls) and (expocode is None or r.expocode == expocode)]


def _level(records, expocode, level):
    return [p for p in _of(records, P.LodPiece, expocode) if p.level == level]


def test_counts_and_cruises(main_records):
    segs = _of(main_records, P.Segment)
    sums = {s.expocode: s for s in _of(main_records, P.CruiseSummary)}
    assert sum(len(s.lon) for s in segs) == 1195
    assert len(sums) == 12
    assert {k: v.n_obs for k, v in sums.items()} == ROWS
    assert all(v.n_rejected == 0 for v in sums.values())
    # every row of a cruise lands in exactly one segment, in order, none lost at a split
    for expo, summ in sums.items():
        cruise_segs = _of(main_records, P.Segment, expo)
        assert len(cruise_segs) == summ.n_segments
        nxt = 0
        for s in cruise_segs:
            assert s.ord0 == nxt
            nxt += len(s.lon)
        assert nxt == summ.n_obs
    # the dataset table lists 13: 09SS20080228 has metadata but no data rows, and yields no summary
    with _open(MAIN) as fh:
        table = P.read_dataset_table(fh)
    assert len(table) == 13
    assert "09SS20080228" in table and "09SS20080228" not in sums
    assert table["09SS20080228"].qc_flag == "B"
    assert set(sums) < set(table)
    assert table["06AQ20241224"].source_doi == "10.25921/y6qs-j872"
    assert table["06AQ20241224"].version == "2026.0N"
    assert table["06AQ19911114"].source_doi is None          # the file writes N/A
    assert table["06AQ19911114"].metadata_docs is None       # empty last field


def test_lon_fold_360_and_antimeridian(main_records):
    # 06AQ20241224: the file holds lon = 360.00000 on 2 rows; 360 is 0, not "360" and not -180
    lons = [x for s in _of(main_records, P.Segment, "06AQ20241224") for x in s.lon]
    assert len(lons) == 100
    assert 360.0 not in lons and all(-180.0 <= x < 180.0 for x in lons)
    assert lons.count(0.0) == 2
    assert any(math.isclose(x, 0.00008, abs_tol=1e-9) for x in lons)      # the row after the 360s
    # 320620060130: file lon runs 178.462 ... 180.014 (past 180). Folded, no unit may span the globe.
    segs = _of(main_records, P.Segment, "320620060130")
    assert sum(len(s.lon) for s in segs) == 100
    lons = [x for s in segs for x in s.lon]
    assert min(lons) < -179 and max(lons) > 178                  # both sides of +-180 are present
    for s in segs:
        assert max(s.lon) - min(s.lon) <= 180.0
    pieces = _of(main_records, P.LodPiece, "320620060130")
    assert pieces
    for p in pieces:
        xs = [v[0] for v in p.vertices]
        assert max(xs) - min(xs) <= 180.0
    # the Ross Sea cruise crosses +-180 and the summary says so
    summ = _of(main_records, P.CruiseSummary, "320620060130")[0]
    assert summ.crosses_antimeridian and summ.west > summ.east
    # pure rule
    assert R.normalize_lon(360.0) == 0.0
    assert R.normalize_lon(180.014) == pytest.approx(-179.986)
    assert R.crosses_antimeridian(179.9, -179.9) and not R.crosses_antimeridian(-0.3, 0.06)


def test_zero_meridian_stays_continuous(main_records):
    # 64SA20060719: file lon 306 ... 360 | 0 ... 4 — naive min/max of the 0..360 values spans the globe
    segs = _of(main_records, P.Segment, "64SA20060719")
    assert sum(len(s.lon) for s in segs) == 185
    for s in segs:
        assert max(s.lon) - min(s.lon) <= R.SEG_MAX_SPAN_DEG
        assert max(s.lat) - min(s.lat) <= R.SEG_MAX_SPAN_DEG
    lons = [x for s in segs for x in s.lon]
    assert min(lons) < 0 < max(lons)                              # the track really is on both sides of 0
    summ = _of(main_records, P.CruiseSummary, "64SA20060719")[0]
    assert not summ.crosses_antimeridian
    assert summ.west < 0 < summ.east and summ.east - summ.west < 180.0


def test_second_sixty_rolls_over(main_records):
    # 06AQ19911114, file row "1991 11 17 21 58 60." — second 60 is the next minute, not an exception
    raw = [r for r in _raw_rows(MAIN, "06AQ19911114") if r[9].startswith("60")]
    assert [r[4:10] for r in raw] == [["1991", "11", "17", "21", "58", "60."]]
    segs = _of(main_records, P.Segment, "06AQ19911114")
    times = {s.t0 + timedelta(seconds=d) for s in segs for d in s.dt_s}
    assert datetime(1991, 11, 17, 21, 59, 0, tzinfo=UTC) in times
    assert datetime(1991, 11, 17, 21, 58, 59, tzinfo=UTC) not in times
    # the rule itself, including a year-end roll-over
    assert R.obs_time("1991", "11", "17", "21", "58", "60.") == datetime(1991, 11, 17, 21, 59, tzinfo=UTC)
    assert R.obs_time("2025", "12", "31", "23", "59", "60.") == datetime(2026, 1, 1, tzinfo=UTC)


def test_nan_is_none_not_zero(main_records):
    assert R.num("NaN") is None and R.num("73.") == 73.0 and R.num("0.") == 0.0
    # 76XL20160724: SST and sal are the literal NaN on 2 rows
    raw = _raw_rows(MAIN, "76XL20160724")
    nan_rows = [i for i, r in enumerate(raw) if r[14] == "NaN" and r[13] == "NaN"]
    assert len(nan_rows) == 2
    segs = _of(main_records, P.Segment, "76XL20160724")
    sst = [x for s in segs for x in s.sst]
    sal = [x for s in segs for x in s.sal]
    assert [i for i, x in enumerate(sst) if math.isnan(x)] == nan_rows
    assert [i for i, x in enumerate(sal) if math.isnan(x)] == nan_rows
    assert not any(math.isnan(x) for s in segs for x in s.fco2)
    # a mean over a piece skips the missing values: finite, never NaN
    for p in _of(main_records, P.LodPiece, "76XL20160724"):
        assert p.sst is None or not math.isnan(p.sst)
        assert p.sal is None or not math.isnan(p.sal)
    # 31HO19571021: sal is NaN on EVERY row, so a piece has no salinity: None, not 0.0
    pieces = _of(main_records, P.LodPiece, "31HO19571021")
    assert pieces and all(p.sal is None for p in pieces)
    assert all(p.sst is not None for p in pieces)
    # 34FP20031001: salinity -0.03 ... -0.17 on 8 rows is real data and stays negative
    sal = [x for s in _of(main_records, P.Segment, "34FP20031001") for x in s.sal]
    neg = [x for x in sal if x < 0]
    assert len(neg) == 8 and min(neg) == pytest.approx(-0.17) and max(neg) == pytest.approx(-0.03)


def test_year_boundary_piece_split(main_records):
    # 34FM20251127: 50 rows of 2025 then 50 rows of 2026 (README); a piece spanning midnight of 1 Jan is wrong
    years = [int(r[4]) for r in _raw_rows(MAIN, "34FM20251127")]
    assert dict(Counter(years)) == {2025: 50, 2026: 50}
    for level in range(len(R.LOD_CELLS)):
        pieces = _level(main_records, "34FM20251127", level)
        assert {p.year for p in pieces} == {2025, 2026}
        by_year = Counter()
        for p in pieces:
            assert p.year == years[p.n0]                         # the year of its own first row
            by_year[p.year] += p.n_obs
        assert dict(by_year) == {2025: 50, 2026: 50}                   # a mixed piece would shift rows to one year


def test_stationary_piece_is_point(main_records):
    # 11BE20021104 at L0: lon 4.3133-4.3151, lat 51.1264-51.1278 — one 1-degree cell for all 100 rows
    pieces = _level(main_records, "11BE20021104", 0)
    assert sum(p.n_obs for p in pieces) == 100
    assert all(len(p.vertices) == 1 for p in pieces)
    # 74P220080731 at L0: lon -3.93 -> -4.04 crosses the -4 degree line: 2 cells, 2 vertices, never a 1-vertex line
    pieces = _level(main_records, "74P220080731", 0)
    assert sum(p.n_obs for p in pieces) == 10
    assert pieces and all(len(p.vertices) == 2 for p in pieces)
    assert all(p.vertices[0] != p.vertices[1] for p in pieces)


def test_flag_e_file_rows_are_rejected(flage_records):
    # 35DR19990124 (FlagE file): 96 rows, dataset flag E, WOCE 2. Stored, counted as rejected, tagged for the tile filter.
    segs = _of(flage_records, P.Segment)
    assert sum(len(s.lon) for s in segs) == 96
    assert {s.qc_flag for s in segs} == {"E"}
    assert all(f == R.GOOD_WOCE for s in segs for f in s.fco2_flag)
    summ = _of(flage_records, P.CruiseSummary)
    assert [(s.expocode, s.n_obs, s.n_rejected) for s in summ] == [("35DR19990124", 96, 96)]
    for level in range(len(R.LOD_CELLS)):
        pieces = _level(flage_records, "35DR19990124", level)
        assert pieces and {p.qc_flag for p in pieces} == {"E"}
        assert sum(p.n_obs for p in pieces) == 96                # built from WOCE-2 rows, flag E carried
    assert "E" not in R.GOOD_QC
    with _open(FLAGE) as fh:
        table = P.read_dataset_table(fh)
    assert table["35DR19990124"].qc_flag == "E"                  # this file has no "Note for data set" block


def test_header_mismatch_raises():
    lines = MAIN.read_text(encoding="utf-8").split("\n")
    i = next(n for n, ln in enumerate(lines) if ln.startswith("Expocode\t") and "\tyr\t" in ln)
    assert lines[i].split("\t") == list(R.EXPECTED_HEADER)       # the fixture IS the measured header
    lines[i] = lines[i].replace("fCO2rec_flag", "fCO2rec_flagX")
    with pytest.raises(P.SchemaError):
        list(P.iter_records(lines))
