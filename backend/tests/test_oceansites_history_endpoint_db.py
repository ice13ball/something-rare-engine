# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""GET /v1/oceansites/{ref}/history and the summary the map carries, against real PostGIS.

The stored rows are seeded straight into the tables the series step fills
(``oceansites_gdac_files`` / ``_station_files`` / ``_series`` / ``_fetched``) and
the requests go through the real FastAPI routes of ``domains.oceansites_history``
and ``domains.sensors``; only the API-key dependency is overridden.

⛔ What is protected: a point the file flags bad is never shown as good, a fill
value is never shown at all, and neither disappears without a count — and the
two counts are not the same number (a missing sample is not a rejected one).
"""
import os
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)

T0 = datetime(2010, 1, 1, tzinfo=timezone.utc)
STD_CITATION = (
    "These data were collected and made freely available by the international "
    "OceanSITES project and the national programs that contribute to it."
)
_TABLES = ("oceansites_gdac_series", "oceansites_gdac_fetched", "oceansites_station_files",
           "oceansites_gdac_files", "oceansites_deployments", "oceansites_stations")


def _hours(n, start=T0):
    return [start + timedelta(hours=i) for i in range(n)]


async def _clean(c):
    for t in _TABLES:
        await c.execute(f"DELETE FROM {t}")


@pytest.fixture
async def pool():
    import asyncpg
    import db as _db
    import response_cache
    import schema
    from domains import sensors

    _db.pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    await schema.ensure_schema()
    async with _db.pool.acquire() as c:
        await _clean(c)
    response_cache.store.clear()
    sensors.clear_oceansites_map_cache()
    yield _db.pool
    async with _db.pool.acquire() as c:
        await _clean(c)
    response_cache.store.clear()
    sensors.clear_oceansites_map_cache()
    await _db.pool.close()


@pytest.fixture
async def client(pool):
    from auth import get_api_key
    from domains import oceansites_history, sensors
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    app = FastAPI()
    app.include_router(oceansites_history.router)
    app.include_router(sensors.router)
    app.dependency_overrides[get_api_key] = lambda: None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def _station(pool, ref, name="PAP-X", lat=49.0, lon=-16.0, **summary):
    async with pool.acquire() as c:
        await c.execute(
            """INSERT INTO oceansites_stations
                   (ref, name, status, lat, lon, geom, history_start, history_end, history_files)
               VALUES ($1, $2, 'CLOSED', $3, $4, ST_SetSRID(ST_MakePoint($4, $3), 4326), $5, $6, $7)""",
            ref, name, lat, lon, summary.get("start"), summary.get("end"), summary.get("files"),
        )


async def _file(pool, ref, file, mode="D", start=T0, end=T0 + timedelta(days=30), citation=None,
                link=True, fetched=True):
    async with pool.acquire() as c:
        await c.execute(
            """INSERT INTO oceansites_gdac_files (file, site_dir, data_mode, start_time, end_time,
                                                   min_depth, max_depth)
               VALUES ($1, 'PAP', $2, $3, $4, 10, 800)
               ON CONFLICT (file) DO NOTHING""",
            file, mode, start, end,
        )
        if link:
            await c.execute(
                "INSERT INTO oceansites_station_files (station_ref, file, rule, distance_km) "
                "VALUES ($1, $2, 'exact', 0) ON CONFLICT DO NOTHING", ref, file)
        if fetched:
            await c.execute(
                "INSERT INTO oceansites_gdac_fetched (file, outcome, citation) VALUES ($1, 'ok', $2) "
                "ON CONFLICT (file) DO UPDATE SET citation = EXCLUDED.citation", file, citation)


async def _series(pool, file, times, vals, qc=None, *, variable="TEMP", depth=10.0, index=0,
                  units="degree_Celsius", std="sea_water_temperature", stride=4, n_total=None,
                  gdac=None):
    qc = qc if qc is not None else [1] * len(vals)
    async with pool.acquire() as c:
        await c.execute(
            """INSERT INTO oceansites_gdac_series
                   (file, variable, depth_index, depth_m, units, long_name, standard_name,
                    n_total, stride, times, vals, qc, gdac_update_date)
               VALUES ($1,$2,$3,$4,$5,'Temperature',$6,$7,$8,$9,$10,$11,$12)""",
            file, variable, index, depth, units, std, n_total or len(vals) * stride, stride,
            times, vals, qc, gdac,
        )


async def _get(client, ref, **params):
    r = await client.get(f"/v1/oceansites/{ref}/history", params=params)
    return r.status_code, r.json()


# ── merge ────────────────────────────────────────────────────────────────────

async def test_series_of_two_files_merge_into_one_sorted_by_time(pool, client):
    await _station(pool, "S1")
    # file B is stored first but holds the EARLIER samples; its depth is 10.4 m, A's 10.0 m
    await _file(pool, "S1", "DATA/PAP/OS_PAP-X_A.nc", start=T0 + timedelta(days=10))
    await _file(pool, "S1", "DATA/PAP/OS_PAP-X_B.nc", start=T0)
    await _series(pool, "DATA/PAP/OS_PAP-X_A.nc", _hours(2, T0 + timedelta(days=10)), [3.0, 4.0],
                  depth=10.0, stride=4, n_total=100)
    await _series(pool, "DATA/PAP/OS_PAP-X_B.nc", _hours(2, T0), [1.0, 2.0], depth=10.4,
                  stride=9, n_total=50)

    code, body = await _get(client, "S1")

    assert code == 200
    assert len(body["series"]) == 1, "the same quantity at the same whole-metre depth must be one series"
    s = body["series"][0]
    assert [p[1] for p in s["points"]] == [1.0, 2.0, 3.0, 4.0]
    times = [p[0] for p in s["points"]]
    assert times == sorted(times) and times[0] == "2010-01-01T00:00:00Z"
    assert s["depth_m"] == 10 and s["standard_name"] == "sea_water_temperature"
    assert s["units"] == "degree_Celsius"
    assert s["n_total_measurements"] == 150, "n_total is the sum over the merged files"
    assert s["duplicates_dropped"] == 0 and s["depths_available"] == [10]
    assert s["stride_max"] == 9
    assert [f["file"] for f in body["files"]] == ["DATA/PAP/OS_PAP-X_B.nc", "DATA/PAP/OS_PAP-X_A.nc"]
    assert body["files"][0]["url_opendap_html"] == (
        "https://tds0.ifremer.fr/thredds/dodsC/CORIOLIS-OCEANSITES-GDAC-OBS/DATA/PAP/OS_PAP-X_B.nc.html")


async def test_other_depth_other_units_and_other_quantity_stay_separate(pool, client):
    await _station(pool, "S1")
    await _file(pool, "S1", "DATA/PAP/f.nc")
    f = "DATA/PAP/f.nc"
    await _series(pool, f, _hours(1), [1.0], depth=10.0, index=0)
    await _series(pool, f, _hours(1), [2.0], depth=10.6, index=1)          # rounds to 11 m
    await _series(pool, f, _hours(1), [3.0], depth=10.0, index=2, variable="VCUR",
                  units="cm/s", std="northward_sea_water_velocity")
    await _series(pool, f, _hours(1), [4.0], depth=10.0, index=3, variable="VCUR2",
                  units="m/s", std="northward_sea_water_velocity")        # a unit is never converted

    _, body = await _get(client, "S1")

    got = sorted((s["standard_name"], s["depth_m"], s["units"]) for s in body["series"])
    assert got == [
        ("northward_sea_water_velocity", 10, "cm/s"),
        ("northward_sea_water_velocity", 10, "m/s"),
        ("sea_water_temperature", 10, "degree_Celsius"),
        ("sea_water_temperature", 11, "degree_Celsius"),
    ]


async def test_another_stations_files_do_not_leak_in(pool, client):
    await _station(pool, "S1")
    await _station(pool, "S2", name="PAP-Y")
    await _file(pool, "S1", "DATA/PAP/mine.nc", citation="MINE citation")
    await _file(pool, "S2", "DATA/PAP/theirs.nc", citation="THEIRS citation")
    await _series(pool, "DATA/PAP/mine.nc", _hours(2), [1.0, 2.0])
    await _series(pool, "DATA/PAP/theirs.nc", _hours(2), [90.0, 91.0])

    _, body = await _get(client, "S1")

    assert [p[1] for p in body["series"][0]["points"]] == [1.0, 2.0]
    assert [f["file"] for f in body["files"]] == ["DATA/PAP/mine.nc"]
    assert not any("THEIRS" in c for c in body["citations"])


# ── QC and fill ──────────────────────────────────────────────────────────────

async def test_bad_qc_points_are_withheld_and_counted(pool, client):
    await _station(pool, "S1")
    await _file(pool, "S1", "DATA/PAP/f.nc")
    vals = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0]
    qc = [1, 4, 3, 9, 2, None, 0, 7]        # None: the file has no QC for this sample
    await _series(pool, "DATA/PAP/f.nc", _hours(8), vals, qc)

    _, body = await _get(client, "S1")

    s = body["series"][0]
    assert [p[1] for p in s["points"]] == [10.0, 14.0, 15.0, 16.0, 17.0], (
        "QC 3, 4 and 9 must be withheld; 0, 1, 2, 7 and 'no QC' are shown")
    assert s["qc_withheld"] == 3
    assert s["missing"] == 0


async def test_fill_is_counted_as_missing_not_as_withheld(pool, client):
    await _station(pool, "S1")
    await _file(pool, "S1", "DATA/PAP/f.nc")
    # NULL = a fill value the file declared. TAO files carry QC 4 and 9 next to their fills:
    # the sample is MISSING, it was not measured-and-rejected.
    vals = [1.0, None, None, 4.0, 5.0]
    qc = [1, 4, 9, 1, 4]                     # last one is a real value flagged bad
    await _series(pool, "DATA/PAP/f.nc", _hours(5), vals, qc)

    _, body = await _get(client, "S1")

    s = body["series"][0]
    assert [p[1] for p in s["points"]] == [1.0, 4.0]
    assert s["missing"] == 2, "two fills"
    assert s["qc_withheld"] == 1, "only the real value flagged bad; fills are not 'withheld'"
    assert all(p[1] is not None for p in s["points"])


# ── cap, first/last, depths ──────────────────────────────────────────────────

async def test_more_than_the_cap_are_thinned_keeping_first_and_last(pool, client):
    await _station(pool, "S1")
    await _file(pool, "S1", "DATA/PAP/f.nc")
    vals = [float(i) for i in range(1000)]
    await _series(pool, "DATA/PAP/f.nc", _hours(1000), vals, stride=3, n_total=3000,
                  variable="PRES", units="dbar", std="sea_water_pressure")   # no range test: values 0..999

    _, default = await _get(client, "S1")
    _, full = await _get(client, "S1", all_depths="true")

    d = default["series"][0]["points"]
    assert len(d) <= 200
    assert d[0][1] == 0.0 and d[-1][1] == 999.0, "first and last real point are always kept"
    assert [p[1] for p in d[:-1]] == vals[:997:6], "interior = every 6th real sample (5 would need 201 points), nothing averaged"
    assert default["series"][0]["stride_max"] == 3 * 6
    f = full["series"][0]["points"]
    assert len(f) <= 600 and f[0][1] == 0.0 and f[-1][1] == 999.0
    assert [p[1] for p in f[:-1]] == vals[:999:2]
    assert full["series"][0]["stride_max"] == 3 * 2
    assert full["series"][0]["n_total_measurements"] == 3000


async def test_a_series_within_the_cap_is_not_thinned(pool, client):
    await _station(pool, "S1")
    await _file(pool, "S1", "DATA/PAP/f.nc")
    await _series(pool, "DATA/PAP/f.nc", _hours(200), [float(i) for i in range(200)], stride=3,
                  variable="PRES", units="dbar", std="sea_water_pressure")

    s = (await _get(client, "S1"))[1]["series"][0]

    assert len(s["points"]) == 200 and s["stride_max"] == 3


async def _fourteen_depths(pool):
    await _station(pool, "S1")
    await _file(pool, "S1", "DATA/PAP/f.nc")
    for i, d in enumerate([1, 5, 10, 20, 30, 40, 60, 80, 100, 150, 200, 400, 800, 1000]):
        await _series(pool, "DATA/PAP/f.nc", _hours(3), [float(d)] * 3, depth=float(d), index=i)
    # a second quantity with only two depths, and the same quantity in other units
    for i, d in enumerate([5, 50]):
        await _series(pool, "DATA/PAP/f.nc", _hours(3), [35.0] * 3, depth=float(d), index=20 + i,
                      variable="PSAL", units="1", std="sea_water_practical_salinity")
    await _series(pool, "DATA/PAP/f.nc", _hours(3), [60.0] * 3, depth=7.0, index=30,
                  variable="TEMPF", units="degree_Fahrenheit")


async def test_default_returns_shallowest_deepest_and_median_depth_per_quantity(pool, client):
    await _fourteen_depths(pool)

    _, body = await _get(client, "S1")

    temp = [s for s in body["series"] if s["units"] == "degree_Celsius"]
    assert [s["depth_m"] for s in temp] == [1, 60, 1000], "shallowest, nearest the median (70; 60 and 80 tie, the shallower wins), deepest"
    all14 = [1, 5, 10, 20, 30, 40, 60, 80, 100, 150, 200, 400, 800, 1000]
    assert all(s["depths_available"] == all14 for s in temp)
    psal = [s for s in body["series"] if s["standard_name"] == "sea_water_practical_salinity"]
    assert [s["depth_m"] for s in psal] == [5, 50] and psal[0]["depths_available"] == [5, 50]
    fahr = [s for s in body["series"] if s["units"] == "degree_Fahrenheit"]
    assert [s["depth_m"] for s in fahr] == [7], "another unit is its own quantity, selected on its own"


async def test_all_depths_returns_every_depth(pool, client):
    await _fourteen_depths(pool)

    _, default = await _get(client, "S1")
    _, full = await _get(client, "S1", all_depths="true")
    _, again = await _get(client, "S1")

    assert len([s for s in full["series"] if s["units"] == "degree_Celsius"]) == 14
    assert len(full["series"]) == 14 + 2 + 1
    assert len(default["series"]) == 3 + 2 + 1
    assert again == default, "the two modes are cached apart"


@pytest.mark.parametrize("depths,chosen", [
    ([10], [10]), ([10, 20], [10, 20]), ([10, 20, 30], [10, 20, 30]),
    ([1, 2, 3, 100], [1, 2, 100]),            # median 2.5: 2 and 3 tie, the shallower wins
    ([1, 5, 10, 20, 100], [1, 10, 100]),
    ([1, 2, 3, 4, 5, 6], [1, 3, 6]),          # median 3.5: 3 and 4 tie -> 3
])
def test_depth_selection(depths, chosen):
    from domains.oceansites_history import _pick_depths

    assert sorted(_pick_depths(depths)) == chosen


def test_a_file_without_depth_never_takes_a_slot_from_real_depths():
    from domains.oceansites_history import _pick_depths

    # four real depths + a depthless file: shallowest, deepest and median-nearest are all real
    assert _pick_depths([1, 10, 100, 500, None]) == {1, 10, 500}
    assert _pick_depths([None, 5]) == {5}
    assert _pick_depths([5, 6, 7, None]) == {5, 6, 7}
    # no numeric depth at all: the depthless series is all there is
    assert _pick_depths([None]) == {None}


async def test_default_view_keeps_the_deepest_real_level_next_to_a_depthless_file(pool, client):
    await _station(pool, "S1")
    await _file(pool, "S1", "DATA/PAP/f.nc")
    await _file(pool, "S1", "DATA/PAP/nodepth.nc", mode="R")
    for i, d in enumerate([1.0, 10.0, 100.0, 500.0]):
        await _series(pool, "DATA/PAP/f.nc", _hours(3), [1.0] * 3, depth=d, index=i)
    await _series(pool, "DATA/PAP/nodepth.nc", _hours(3), [2.0] * 3, depth=None, index=0)

    _, default = await _get(client, "S1")
    _, full = await _get(client, "S1", all_depths="true")

    assert [s["depth_m"] for s in default["series"]] == [1, 10, 500]
    assert sorted(s["depth_m"] for s in full["series"] if s["depth_m"] is not None) == [1, 10, 100, 500]
    assert [s["depth_m"] for s in full["series"] if s["depth_m"] is None] == [None]   # nothing is hidden in all_depths
    assert all(None not in s["depths_available"] for s in full["series"])


# ── the merge runs off the event loop ────────────────────────────────────────

async def test_merge_series_does_not_run_on_the_event_loop_thread(pool, client, monkeypatch):
    import threading

    from domains import oceansites_history as dom

    await _station(pool, "S1")
    await _file(pool, "S1", "DATA/PAP/f.nc")
    await _series(pool, "DATA/PAP/f.nc", _hours(3), [1.0] * 3)
    real, seen = dom.merge_series, []

    def spy(*a, **k):
        seen.append(threading.get_ident())
        return real(*a, **k)

    monkeypatch.setattr(dom, "merge_series", spy)
    code, _ = await _get(client, "S1")

    assert code == 200 and len(seen) == 1
    assert seen[0] != threading.get_ident(), "CPU-bound merge must not block the loop"


# ── duplicates ───────────────────────────────────────────────────────────────

async def test_n_total_measurements_counts_an_overlapping_instant_once(pool, client):
    await _station(pool, "S1")
    await _file(pool, "S1", "DATA/PAP/a.nc", mode="D")
    await _file(pool, "S1", "DATA/PAP/b.nc", mode="R")
    # a: hours 0-5, b: hours 3-6 (stride 1: every measurement stored) -> 3 shared instants, 7 unique
    await _series(pool, "DATA/PAP/a.nc", _hours(6), [1.0] * 6, stride=1)
    await _series(pool, "DATA/PAP/b.nc", _hours(4, T0 + timedelta(hours=3)), [2.0] * 4, stride=1)

    s = (await _get(client, "S1"))[1]["series"][0]

    assert s["duplicates_dropped"] == 3
    assert s["n_total_measurements"] == 7, "6 + 4 minus the 3 instants both files hold"
    assert len(s["points"]) == 7


async def test_n_total_measurements_weighs_a_dropped_sample_by_its_stride(pool, client):
    await _station(pool, "S1")
    await _file(pool, "S1", "DATA/PAP/a.nc", mode="D")
    await _file(pool, "S1", "DATA/PAP/b.nc", mode="R")
    ts = [T0 + timedelta(hours=2 * i) for i in range(3)]      # same sampled instants, stride 2
    await _series(pool, "DATA/PAP/a.nc", ts, [1.0] * 3, stride=2, n_total=6)
    await _series(pool, "DATA/PAP/b.nc", ts, [2.0] * 3, stride=2, n_total=6)

    s = (await _get(client, "S1"))[1]["series"][0]

    assert s["duplicates_dropped"] == 3
    assert s["n_total_measurements"] == 6, "two copies of the same 6 measurements are 6, not 12"



async def test_identical_timestamps_keep_the_better_mode_then_the_later_marker(pool, client):
    await _station(pool, "S1")
    await _file(pool, "S1", "DATA/PAP/r.nc", mode="R")
    await _file(pool, "S1", "DATA/PAP/d_old.nc", mode="D")
    await _file(pool, "S1", "DATA/PAP/d_new.nc", mode="D")
    await _file(pool, "S1", "DATA/PAP/p.nc", mode="P")
    ts = _hours(3)
    old, new = datetime(2020, 1, 1, tzinfo=timezone.utc), datetime(2024, 1, 1, tzinfo=timezone.utc)
    await _series(pool, "DATA/PAP/r.nc", ts, [1.0, 1.0, 1.0], gdac=new)
    await _series(pool, "DATA/PAP/p.nc", ts, [2.0, 2.0, 2.0], gdac=new)
    await _series(pool, "DATA/PAP/d_old.nc", ts[:2], [3.0, 3.0], gdac=old)
    await _series(pool, "DATA/PAP/d_new.nc", ts[:1], [4.0], gdac=new)

    _, body = await _get(client, "S1")

    s = body["series"][0]
    # t0: D(new) beats D(old), P and R; t1: D(old) beats P and R; t2: only P and R, P wins
    assert [p[1] for p in s["points"]] == [4.0, 3.0, 2.0]
    assert s["duplicates_dropped"] == (4 - 1) + (3 - 1) + (2 - 1)


async def test_every_stored_sample_is_in_exactly_one_bucket(pool, client):
    """points + missing + qc_withheld + duplicates_dropped == samples stored."""
    await _station(pool, "S1")
    await _file(pool, "S1", "DATA/PAP/a.nc", mode="D")
    await _file(pool, "S1", "DATA/PAP/b.nc", mode="R")
    await _series(pool, "DATA/PAP/a.nc", _hours(6), [1.0, None, 3.0, 4.0, 5.0, 6.0], [1, 4, 4, 1, 1, 1])
    await _series(pool, "DATA/PAP/b.nc", _hours(4, T0 + timedelta(hours=3)), [7.0, 8.0, 9.0, 10.0])

    s = (await _get(client, "S1"))[1]["series"][0]

    assert (len(s["points"]), s["missing"], s["qc_withheld"], s["duplicates_dropped"]) == (5, 1, 1, 3)
    assert 5 + 1 + 1 + 3 == 6 + 4  # = the 10 stored samples


async def test_dedup_preferring_a_better_file_does_not_resurrect_its_fill(pool, client):
    await _station(pool, "S1")
    await _file(pool, "S1", "DATA/PAP/a.nc", mode="D")
    await _file(pool, "S1", "DATA/PAP/b.nc", mode="R")
    await _series(pool, "DATA/PAP/a.nc", _hours(1), [None], [9])
    await _series(pool, "DATA/PAP/b.nc", _hours(1), [5.0])

    s = (await _get(client, "S1"))[1]["series"][0]

    assert s["points"] == [] and s["missing"] == 1 and s["duplicates_dropped"] == 1


# ── 404 / empty ──────────────────────────────────────────────────────────────

async def test_unknown_ref_is_404(pool, client):
    code, _ = await _get(client, "NO-SUCH-STATION")
    assert code == 404


async def test_known_station_without_history_is_200_with_empty_lists(pool, client):
    await _station(pool, "S1")

    code, body = await _get(client, "S1")

    assert code == 200
    assert body["files"] == [] and body["series"] == []
    assert body["ref"] == "S1" and body["n_catalogue_files"] == 0 and body["n_files_read"] == 0
    assert body["start"] is None and body["end"] is None
    assert body["citations"] == [STD_CITATION], "the OceanSITES citation is always present"


async def test_linked_but_not_yet_fetched_is_200_with_the_span_only(pool, client):
    start, end = T0, T0 + timedelta(days=400)
    await _station(pool, "S1", start=start, end=end, files=2)
    await _file(pool, "S1", "DATA/PAP/a.nc", fetched=False)
    await _file(pool, "S1", "DATA/PAP/b.nc", fetched=False)

    code, body = await _get(client, "S1")

    assert code == 200
    assert body["n_catalogue_files"] == 2 and body["n_files_read"] == 0 and body["start"] == "2010-01-01T00:00:00Z"
    assert body["end"] == "2011-02-05T00:00:00Z"
    assert body["files"] == [] and body["series"] == []


# ── citations ────────────────────────────────────────────────────────────────

async def test_citations_are_the_standard_one_plus_each_distinct_file_citation(pool, client):
    await _station(pool, "S1")
    for name, cite in [("a", "Alpha programme citation"), ("b", "Alpha programme citation"),
                       ("c", "Beta programme citation"), ("d", None), ("e", STD_CITATION)]:
        f = f"DATA/PAP/{name}.nc"
        await _file(pool, "S1", f, citation=cite)
        await _series(pool, f, _hours(1), [1.0], index=0)

    _, body = await _get(client, "S1")

    assert body["citation"] == STD_CITATION
    assert body["citations"] == [STD_CITATION, "Alpha programme citation", "Beta programme citation"]


# ── the map carries the summary ──────────────────────────────────────────────

async def test_map_carries_history_start_end_and_files(pool, client):
    import json

    start, end = datetime(1998, 5, 10, 22, 40, tzinfo=timezone.utc), datetime(2026, 9, 29, 23, 58, tzinfo=timezone.utc)
    await _station(pool, "S1", start=start, end=end, files=511)
    await _station(pool, "S2", name="NOHIST", lat=10.0, lon=10.0)

    r = await client.get("/v1/map/oceansites")

    assert r.status_code == 200
    props = {f["properties"]["ref"]: f["properties"] for f in json.loads(r.content)["features"]}
    assert props["S1"]["history_start"] == "1998-05-10T22:40:00+00:00"
    assert props["S1"]["history_end"] == "2026-09-29T23:58:00+00:00"
    assert props["S1"]["history_files"] == 511
    assert props["S2"]["history_start"] is None and props["S2"]["history_end"] is None
    assert not props["S2"]["history_files"]


async def test_dropping_the_history_caches_refreshes_map_and_history(pool, client):
    from domains import oceansites_history as dom

    await _station(pool, "S1")
    await _file(pool, "S1", "DATA/PAP/f.nc")
    assert (await _get(client, "S1"))[1]["series"] == []
    assert (await client.get("/v1/map/oceansites")).json()["features"][0]["properties"]["history_files"] is None
    await _series(pool, "DATA/PAP/f.nc", _hours(2), [1.0, 2.0])
    async with pool.acquire() as c:
        await c.execute("UPDATE oceansites_stations SET history_files = 1 WHERE ref = 'S1'")

    dom.drop_history_caches()

    assert len((await _get(client, "S1"))[1]["series"]) == 1
    assert (await client.get("/v1/map/oceansites")).json()["features"][0]["properties"]["history_files"] == 1


async def test_range_withheld_travels_through_the_endpoint_beside_the_other_counts(pool, client):
    await _station(pool, "S1")
    await _file(pool, "S1", "DATA/PAP/f.nc")
    # PAP PSAL: exactly 0 with QC 1 is the real production case; stored data stay as they are
    await _series(pool, "DATA/PAP/f.nc", _hours(5), [35.1, 0.0, None, 35.2, 99.0], [1, 1, 1, 4, 1],
                  variable="PSAL", units="psu", std="sea_water_practical_salinity")

    _, body = await _get(client, "S1")

    s = body["series"][0]
    assert [p[1] for p in s["points"]] == [35.1]
    assert (s["range_withheld"], s["qc_withheld"], s["missing"]) == (2, 1, 1)
    async with pool.acquire() as c:
        stored = await c.fetchval("SELECT vals FROM oceansites_gdac_series WHERE file = 'DATA/PAP/f.nc'")
    assert stored == [35.1, 0.0, None, 35.2, 99.0], "the endpoint withholds; it never edits what is stored"


# ── pure merge ───────────────────────────────────────────────────────────────

def _row(**kw):
    base = dict(file="f", data_mode="D", gdac_update_date=None, variable="TEMP", depth_m=10.0, units="degC", long_name="T",
                standard_name="sea_water_temperature", n_total=10, stride=1,
                times=[T0], vals=[1.0], qc=[1])
    base.update(kw)
    return base


@pytest.mark.parametrize("depth,bucket", [(0.4, 0), (0.5, 1), (1.5, 2), (10.49, 10), (10.5, 11), (-0.2, 0)])
def test_depth_buckets_are_whole_metres_halves_up(depth, bucket):
    from domains.oceansites_history import merge_series

    assert merge_series([_row(depth_m=depth)])[0]["depth_m"] == bucket


def test_a_non_finite_value_is_missing_never_a_point():
    from domains.oceansites_history import merge_series

    s = merge_series([_row(times=_hours(3), vals=[1.0, float("nan"), float("inf")], qc=[1, 1, 1])])[0]
    assert [p[1] for p in s["points"]] == [1.0] and s["missing"] == 2 and s["qc_withheld"] == 0
