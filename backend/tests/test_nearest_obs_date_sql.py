# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""DB test for the per-source `date_sql`/`date_kind` added to OBS_SOURCES: one row per
source table, inserted at the clicked point (distance 0), then the real
`carbon_nearest_obs` endpoint handler is called and every observation's "date" /
"date_kind" is checked against the exact string the source should produce.
"""
import pytest

from domains.fields import carbon
from pangaea_water_helpers import conn, needs_db  # noqa: F401

LAT, LON = 10.0, 20.0


@pytest.fixture
async def seeded(conn):
    # A session zone 12-13 h ahead of UTC: a timestamptz at 23:30 UTC is already the
    # NEXT day here, so any date_sql that formats in the session zone fails below.
    await conn.execute("SET TIME ZONE 'Pacific/Auckland'")
    # argo_profiles: timestamptz at 23:30 UTC — must give that UTC day, not the session tz.
    await conn.execute(
        """INSERT INTO argo_profiles (profile_id, platform_id, profile_date, max_depth_m, geom)
           VALUES ('t-argo-1', 'plat-1', '2020-06-14 23:30:00+00',
                   1000, ST_SetSRID(ST_MakePoint($1, $2), 4326))""",
        LON, LAT,
    )
    # geotraces_stations
    await conn.execute(
        """INSERT INTO geotraces_stations (station_id, cruise, station, sample_time, lat, lon, geom)
           VALUES ('t-geo-1', 'cruise-1', 'st-1', '2015-03-01 23:30:00+00', $2, $1,
                   ST_SetSRID(ST_MakePoint($1, $2), 4326))""",
        LON, LAT,
    )
    # memento_casts, month precision — day is stored as 01, must display YYYY-MM only.
    await conn.execute(
        """INSERT INTO memento_casts (cast_id, set_name, station, sample_time, lat, lon,
                                       geom, time_precision)
           VALUES ('t-mem-1', 'set-1', 'st-1', '2018-07-01 00:00:00+00', $2, $1,
                   ST_SetSRID(ST_MakePoint($1, $2), 4326), 'month')""",
        LON, LAT,
    )
    # wod_oxygen_profiles: the real 1970-01-01 sentinel-looking-but-real date.
    await conn.execute(
        """INSERT INTO wod_oxygen_profiles (wod_cast_id, lat, lon, geom, profile_date, dataset)
           VALUES ('t-wod-1', $2, $1, ST_SetSRID(ST_MakePoint($1, $2), 4326),
                   '1970-01-01', 'ds-1')""",
        LON, LAT,
    )
    # cascade_stations: id has no default in this schema.
    await conn.execute(
        """INSERT INTO cascade_stations (id, station, lat, lon, expedition, year, geom)
           VALUES (900001, 'st-1', $2, $1, 'exp-1', 2011,
                   ST_SetSRID(ST_MakePoint($1, $2), 4326))""",
        LON, LAT,
    )
    # seaflea_seeps: NULL obs_year.
    await conn.execute(
        """INSERT INTO seaflea_seeps (ext_id, lat, lon, primary_type, depth_m, obs_year, geom)
           VALUES ('t-seep-1', $2, $1, 'seep', 500, NULL,
                   ST_SetSRID(ST_MakePoint($1, $2), 4326))""",
        LON, LAT,
    )
    # hydrothermal_vents: date_precision 'none' -> date must be NULL, kind 'discovered',
    # even when a year is stored next to it (production has none such today; the
    # CASE in date_sql is what keeps it that way).
    await conn.execute(
        """INSERT INTO hydrothermal_vents (name, status, depth_m, latitude, longitude, geom,
                                            discovery_year_num, date_precision)
           VALUES ('t-vent-1', 'active', 2000, $2, $1,
                   ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography, 1999, 'none')""",
        LON, LAT,
    )
    # deepdata_stations: a real range (first != last). FK to deepdata_dwc_archives.slug.
    await conn.execute("INSERT INTO deepdata_dwc_archives (slug) VALUES ('slug-1')")
    await conn.execute(
        """INSERT INTO deepdata_stations (station_id, archive_slug, contractor_code, lat, lon,
                                           first_event_date, last_event_date, occurrence_count)
           VALUES ('t-dd-1', 'slug-1', 'ctr-1', $2, $1,
                   '2019-01-05 23:30:00+00', '2019-01-09 23:30:00+00', 3)""",
        LON, LAT,
    )
    yield conn


@needs_db
class TestNearestObsDates:
    async def test_every_observation_has_date_and_date_kind(self, seeded):
        body = await carbon.carbon_nearest_obs(lat=LAT, lon=LON)
        obs = body["observations"]
        assert len(obs) == 8
        for o in obs:
            assert "date" in o
            assert "date_kind" in o

    async def test_exact_date_strings_per_source(self, seeded):
        body = await carbon.carbon_nearest_obs(lat=LAT, lon=LON)
        by = {o["source"]: o for o in body["observations"]}

        assert by["argo"]["date"] == "2020-06-14"
        assert by["argo"]["date_kind"] == "sampled"

        assert by["memento"]["date"] == "2018-07"
        assert by["memento"]["date_kind"] == "sampled"

        assert by["wod-oxygen"]["date"] == "1970-01-01"
        assert by["wod-oxygen"]["date_kind"] == "sampled"

        assert by["vents"]["date"] is None
        assert by["vents"]["date_kind"] == "discovered"

        assert by["methane-seeps"]["date"] is None
        assert by["methane-seeps"]["date_kind"] == "sampled"

        assert by["deepdata-stations"]["date"] == "2019-01-05 – 2019-01-09"
        assert by["deepdata-stations"]["date_kind"] == "sampled_range"

        assert by["cascade"]["date"] == "2011"
        assert by["geotraces"]["date"] == "2015-03-01"
