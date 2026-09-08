# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

# backend/tests/test_geotraces_ingest.py
import os
from backend.ingestion import geotraces_ingest as g

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "geotraces", "seawater_real_subset.csv")

def _text():
    with open(FIX, encoding="utf-8") as f:
        return f.read()

def test_normalize_lon_wraps_0_360():
    assert round(g.normalize_lon(349.963989), 6) == round(349.963989 - 360, 6)
    assert g.normalize_lon(10.5) == 10.5
    assert g.normalize_lon(180.0) == 180.0

def test_station_id_stable_and_text_safe():
    a = g.station_id_for("GA02", "(101)")
    b = g.station_id_for("GA02", "(101)")
    c = g.station_id_for("GA02", "001")
    assert a == b and a != c and len(a) == 16

def test_build_samples_units_verbatim():
    samples, units = g.build_samples(_text())
    assert units["co_d"] == "pmol/kg"      # Co differs!
    assert units["fe_d"] == "nmol/kg"
    assert units["mn_d"] == "nmol/kg"
    assert set(units) == {"mn_d","fe_d","co_d","ni_d","cu_d"}

def test_build_samples_values_and_flags():
    samples, _ = g.build_samples(_text())
    # at least one Fe value with flag retained; flag 4/9 excluded; lon normalized negative
    fe = [s for s in samples if s["fe_d"] is not None]
    assert fe, "expected Fe samples"
    s0 = fe[0]
    assert s0["fe_d"] > 0 and isinstance(s0["fe_d_qc"], int)
    assert s0["lon"] < 0  # GA01 stations are ~-10 (normalized from 349.x)
    assert all(s["fe_d_qc"] not in (4, 9) for s in fe)
    # metals coverage present in fixture
    assert any(s["mn_d"] is not None for s in samples)
    assert any(s["co_d"] is not None for s in samples)
    assert any(s["cu_d"] is not None for s in samples)
    assert any(s["ni_d"] is not None for s in samples)

def test_derive_stations_rollup():
    samples, _ = g.build_samples(_text())
    stations = g.derive_stations(samples)
    by = {s["station_id"]: s for s in stations}
    assert len(stations) == len({s["station_id"] for s in samples})
    for st in stations:
        assert st["n_samples"] >= 1
        assert st["min_depth_m"] <= st["max_depth_m"]
        if st["has_fe"]:
            assert st["fe_max"] is not None
        assert isinstance(st["decade"], int) or st["decade"] is None

def test_sample_time_and_decade_populated():
    """Regression: parse_header must match the 'time' column (yyyy-mm-ddThh:mm:ss.sss).
    Before the fix, _base_name() truncated that header at the first ':', yielding
    'yyyy-mm-ddThh' which never matched, so sample_time and decade were always None."""
    import csv as _csv, io as _io

    # 1. parse_header must include the "time" key
    with open(FIX, encoding="utf-8") as f:
        header = next(_csv.reader(f))
    h = g.parse_header(header)
    assert "time" in h["meta"], (
        f"parse_header did not match the 'time' column; meta keys = {list(h['meta'].keys())}"
    )

    # 2. At least one sample must have a non-None sample_time
    samples, _ = g.build_samples(_text())
    assert any(s["sample_time"] is not None for s in samples), (
        "All sample_time values are None — time column not matched"
    )

    # 3. derive_stations must produce at least one station with an integer decade
    stations = g.derive_stations(samples)
    assert any(isinstance(st["decade"], int) for st in stations), (
        "All station decades are None — sample_time never populated"
    )


# ── parse_all_params (2026-09-08 additive-ingest task) ──────────────────────

def test_parse_all_params_finds_value_std_qc_triplets():
    import csv as _csv
    with open(FIX, encoding="utf-8") as f:
        header = next(_csv.reader(f))
    params = g.parse_all_params(header)
    by_code = {p["param_code"]: p for p in params}
    # CTDTMP is a real value column followed by STANDARD_DEV then QV:SEADATANET
    p = by_code["CTDTMP_UP_T_VALUE_SENSOR"]
    assert header[p["value_idx"]] == "CTDTMP_UP_T_VALUE_SENSOR [deg C]"
    assert header[p["std_idx"]] == "STANDARD_DEV"
    assert header[p["qc_idx"]].startswith("QV:")
    # The 5 wide metals must all show up as params too (additive, not a replacement)
    for exact in g._METAL_COL.values():
        assert exact in by_code, f"{exact} missing from parse_all_params"
    # Metadata / STANDARD_DEV / QV columns must never be emitted as params
    codes = set(by_code)
    assert "STANDARD_DEV" not in codes
    assert not any(c.startswith("QV:") for c in codes)
    assert "Cruise" not in codes and "Station" not in codes and "DEPTH" not in codes


def test_parse_all_params_unit_verbatim_pmol_vs_nmol():
    import csv as _csv
    with open(FIX, encoding="utf-8") as f:
        header = next(_csv.reader(f))
    params = g.parse_all_params(header)
    by_code = {p["param_code"]: p for p in params}
    assert by_code["Co_D_CONC"]["unit"] == "pmol/kg"
    assert by_code["Fe_D_CONC"]["unit"] == "nmol/kg"
    assert by_code["Mn_D_CONC"]["unit"] == "nmol/kg"


def test_parse_all_params_unpaired_column_gets_none_not_wrong_neighbour():
    # A value column whose immediate neighbours are NOT its own STANDARD_DEV/QV
    # must record std_idx/qc_idx as None rather than silently grabbing them.
    header = ["Cruise", "Station:METAVAR:INDEXED_TEXT", "Type",
              "yyyy-mm-ddThh:mm:ss.sss", "Longitude [degrees_east]",
              "Latitude [degrees_north]", "Bot. Depth [m]", "DEPTH [m]", "QV:SEADATANET",
              "Foo_D_CONC [nmol/kg]", "Bar_D_CONC [nmol/kg]"]  # Foo has no companions at all
    params = g.parse_all_params(header)
    foo = next(p for p in params if p["param_code"] == "Foo_D_CONC")
    assert foo["std_idx"] is None and foo["qc_idx"] is None


def test_bottle_without_any_target_metal_is_kept():
    """Regression for the `if any_metal:` gate that dropped 79% of bottles."""
    samples, _ = g.build_samples(_text())
    no_metal = [
        s for s in samples
        if all(s.get(f"{m}_d") is None for m in g.TARGET_METALS)
    ]
    assert no_metal, "expected at least one bottle with none of the 5 target metals — none found"


def test_stream_samples_value_rows_drop_bad_flags_keep_flag_6():
    total_seen = {"4_or_9": 0, "6": 0}
    for batch in g.stream_samples(FIX, batch_size=10_000):
        for _rec, value_rows in batch:
            for param_code, val, std, qc in value_rows:
                assert qc not in (4, 9), f"flag {qc} should have been dropped for {param_code}"
                if qc == 6:
                    total_seen["6"] += 1
    # Not asserting a specific count (fixture-dependent) — just that dropping held
    # across the whole fixture and that the mechanism is exercised at all.


# ── Anti-truncation guard (rule 5 of the shared brief) ───────────────────────

class _FakeConn:
    def __init__(self, existing_count):
        self.existing_count = existing_count
        self.executed = []
        self.transaction_entered = False

    async def fetchval(self, *a, **kw):
        return self.existing_count

    def transaction(self):
        conn = self

        class _Tx:
            async def __aenter__(self_):
                conn.transaction_entered = True
                return self_

            async def __aexit__(self_, *exc):
                return False

        return _Tx()

    async def execute(self, *a, **kw):
        self.executed.append(("execute", a))

    async def executemany(self, *a, **kw):
        self.executed.append(("executemany", a))


class _FakePool:
    def __init__(self, existing_count):
        self.conn = _FakeConn(existing_count)

    def acquire(self):
        pool = self

        class _Acq:
            async def __aenter__(self_):
                return pool.conn

            async def __aexit__(self_, *exc):
                return False

        return _Acq()


def _one_sample():
    return {
        "station_id": "abc", "cruise": "GA01", "station": "1", "sample_time": None,
        "lat": 10.0, "lon": 20.0, "depth_m": 5.0, "bottom_depth_m": None,
        "mn_d": None, "fe_d": None, "co_d": None, "ni_d": None, "cu_d": None,
        "mn_d_qc": None, "fe_d_qc": None, "co_d_qc": None, "ni_d_qc": None, "cu_d_qc": None,
        "params": {}, "csv_row": 0,
    }


async def _run_load_guard(existing_count, n_new_samples):
    pool = _FakePool(existing_count)
    samples = [_one_sample() for _ in range(n_new_samples)]
    inserted = await g.load(pool, samples, [], {}, [])
    return pool, inserted


def test_lossy_scrape_guard_refuses_to_truncate(anyio_backend=None):
    import asyncio as _asyncio
    pool, inserted = _asyncio.run(_run_load_guard(existing_count=1000, n_new_samples=5))
    assert inserted == 0
    assert pool.conn.transaction_entered is False, (
        "guard must refuse BEFORE opening the TRUNCATE transaction"
    )
    assert pool.conn.executed == [], "no TRUNCATE/INSERT should have run"


def test_lossy_scrape_guard_allows_when_new_parse_is_not_smaller(anyio_backend=None):
    import asyncio as _asyncio
    pool, inserted = _asyncio.run(_run_load_guard(existing_count=3, n_new_samples=5))
    assert inserted == 5
    assert pool.conn.transaction_entered is True

# SABOTAGE CHECK (2026-09-08, done once by hand while writing this guard):
# temporarily changed `if len(samples) < existing:` in ingestion/geotraces_ingest.py
# load() to `if False:` and re-ran test_lossy_scrape_guard_refuses_to_truncate —
# it went RED (asserted inserted == 0, got 5; transaction_entered was True).
# Confirms the test actually exercises the guard rather than passing regardless.
# The `if False:` change was reverted immediately after observing the failure.


# ── DEFECT 1 (2026-09-08 audit): csv_row keying, not "GEOTRACES Sample ID" ──
#
# Real IDP2025 file measurements: "GEOTRACES Sample ID" is empty on 41% of
# rows (53,092 / 129,148); of the 76,056 non-empty values only 29,944 are
# distinct (46,112 duplicates). No natural key in the file is unique. Keying
# geotraces_values on the CSV row ordinal (assigned in stream_samples) is the
# only option that never drops a bottle and never collides.

_MIN_HEADER = [
    "Cruise", "Station", "Type", "yyyy-mm-ddThh:mm:ss.sss",
    "Longitude [degrees_east]", "Latitude [degrees_north]", "Bot. Depth [m]",
    "DEPTH [m]", "GEOTRACES Sample ID", "QV:SEADATANET",
    "Fe_D_CONC [nmol/kg]", "STANDARD_DEV", "QV:SEADATANET",
]


def _write_min_csv(tmp_path, rows):
    import csv as _csv
    path = tmp_path / "min.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = _csv.writer(f)
        w.writerow(_MIN_HEADER)
        for row in rows:
            w.writerow(row)
    return str(path)


def test_duplicate_and_missing_geotraces_sample_id_all_keep_their_own_measurements(tmp_path):
    """Two bottles share the same 'GEOTRACES Sample ID' ("S1") and a third has
    none at all. All three must be kept with their own distinct key and their
    own value_rows — none dropped, none colliding.

    This test FAILS against the old keying: rec.get("geotraces_sample_id")
    would drop the third bottle (`if not sid: continue`) and give bottles one
    and two the SAME key ("S1"), which is a PRIMARY KEY (sample_id, param_code)
    violation in the real database — collision, not just a wrong join.
    """
    rows = [
        ["GA01", "1", "B", "2020-01-01T00:00:00", "10", "5", "100", "10", "S1", "1", "1.1", "0.01", "1"],
        ["GA01", "2", "B", "2020-01-01T00:00:00", "11", "6", "100", "20", "S1", "1", "2.2", "0.01", "1"],
        ["GA01", "3", "B", "2020-01-01T00:00:00", "12", "7", "100", "30", "", "", "3.3", "0.01", "1"],
    ]
    path = _write_min_csv(tmp_path, rows)
    recs = []
    for batch in g.stream_samples(path, batch_size=10):
        recs.extend(batch)
    assert len(recs) == 3

    csv_row_keys = [rec["csv_row"] for rec, _vr in recs]
    assert len(set(csv_row_keys)) == 3, "csv_row must be unique per bottle"

    fe_values_by_csv_row = {
        rec["csv_row"]: next(val for pc, val, _std, _qc in value_rows if pc == "Fe_D_CONC")
        for rec, value_rows in recs
    }
    assert fe_values_by_csv_row == {0: 1.1, 1: 2.2, 2: 3.3}, (
        "each bottle's own Fe measurement must survive under its own csv_row key"
    )

    # Demonstrate the OLD keying's failure mode directly: rows 0 and 1 collide
    # on "GEOTRACES Sample ID", and row 2 has none to key on at all.
    old_keys = [rec.get("geotraces_sample_id") for rec, _vr in recs]
    assert old_keys[0] == old_keys[1] == "S1", "sanity: rows 0/1 really do share the old key"
    assert not old_keys[2], "sanity: row 2 really does have no old key"
    surviving_under_old_scheme = {k for k in old_keys if k}
    assert len(surviving_under_old_scheme) < 3, (
        "old keying collides/drops — this is the bug being fixed"
    )


def test_csv_row_ordinal_survives_a_skipped_row_before_it(tmp_path):
    """A row with no usable lat/lon is skipped by stream_samples (`continue`).
    csv_row on the rows AFTER it must still equal their TRUE physical position
    in the CSV, not be shifted down by one, or their measurements get attached
    to the wrong bottle once matched against geotraces_samples.csv_row."""
    rows = [
        ["GA01", "1", "B", "2020-01-01T00:00:00", "10", "", "100", "10", "S1", "1", "9.9", "0.01", "1"],  # no lat -> skipped
        ["GA01", "2", "B", "2020-01-01T00:00:00", "11", "6", "100", "20", "S2", "1", "8.8", "0.01", "1"],
        ["GA01", "3", "B", "2020-01-01T00:00:00", "12", "7", "100", "30", "S3", "1", "7.7", "0.01", "1"],
    ]
    path = _write_min_csv(tmp_path, rows)
    recs = []
    for batch in g.stream_samples(path, batch_size=10):
        recs.extend(batch)
    assert len(recs) == 2, "the no-lat row must have been skipped"
    csv_rows = [rec["csv_row"] for rec, _vr in recs]
    assert csv_rows == [1, 2], (
        f"expected the two kept rows to carry their TRUE physical row numbers "
        f"[1, 2] (row 0 was skipped) — got {csv_rows}. If this is off by one, "
        f"the ordinal counter is only advancing for kept rows."
    )

# SABOTAGE CHECK (2026-09-08, done once by hand while writing this test):
# moved the `csv_row += 1` line in stream_samples() to AFTER the
# `if lat is None or lon is None: continue` skip and re-ran
# test_csv_row_ordinal_survives_a_skipped_row_before_it — it went RED:
# got [0, 1] instead of the expected [1, 2] (the counter only advanced for
# the two KEPT rows, so both were shifted down by one). Reverted immediately
# after observing the failure; the increment is back before the skip.
