# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Schema DDL — onc domain. Extracted verbatim from the former backend/schema.py.
"""
from __future__ import annotations

async def ensure_onc_core(conn) -> None:
    """onc_locations, onc_location_categories, onc_sparklines, onc_adcp_strips, onc_ctd_profiles."""

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS onc_locations (
            location_code     TEXT PRIMARY KEY,
            name              TEXT NOT NULL,
            lat               DOUBLE PRECISION NOT NULL,
            lon               DOUBLE PRECISION NOT NULL,
            depth_m           DOUBLE PRECISION,
            description       TEXT DEFAULT '',
            geom              GEOMETRY(Point, 4326),
            updated_at        TIMESTAMPTZ DEFAULT NOW(),
            latest_sensors    JSONB,
            sensors_fetched_at TIMESTAMPTZ
        )
    """)
    # Migration: add sensor columns to existing tables
    for col, defn in [
        ("latest_sensors",     "JSONB"),
        ("sensors_fetched_at", "TIMESTAMPTZ"),
    ]:
        try:
            await conn.execute(
                f"ALTER TABLE onc_locations ADD COLUMN IF NOT EXISTS {col} {defn}"
            )
        except Exception:
            pass
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS onc_locations_geom_idx
        ON onc_locations USING GIST(geom)
    """)
    try:
        await conn.execute("ALTER TABLE onc_locations OWNER TO abyssal_user")
    except Exception:
        pass

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS onc_sparklines (
            location_code TEXT,
            property_code TEXT,
            unit          TEXT,
            samples       JSONB,
            window_start  TIMESTAMPTZ,
            window_end    TIMESTAMPTZ,
            updated_at    TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (location_code, property_code)
        )
    """)

    # onc_acoustic_events RETIRED 2026-07-10. ONC publishes no detection events
    # through any API: hydrophones expose only engineering scalars via
    # scalardata (voltage, internaltemperature, statuscode…), the `AF`
    # annotation product is not orderable for them, and the quantitative
    # products (HSD/HSPD) are spectra, not detections. The table held 0 rows
    # for its entire life. Dropped rather than left as a dead promise.
    await conn.execute("DROP TABLE IF EXISTS onc_acoustic_events")

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS onc_adcp_strips (
            location_code TEXT,
            device_code   TEXT,
            beam_count    INT,
            bin_count     INT,
            window_start  TIMESTAMPTZ,
            window_end    TIMESTAMPTZ,
            strip         JSONB,
            updated_at    TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (location_code, device_code)
        )
    """)
    # RADCPTS migration (2026-07-10): the strip is now depth-resolved mean
    # backscatter in dB, so the bin depths travel with it. `beam_count` is
    # retained (nullable) but no longer written — ONC averages the 4 beams.
    await conn.execute("""
        ALTER TABLE onc_adcp_strips ADD COLUMN IF NOT EXISTS depths   JSONB;
        ALTER TABLE onc_adcp_strips ADD COLUMN IF NOT EXISTS variable TEXT;
        ALTER TABLE onc_adcp_strips ADD COLUMN IF NOT EXISTS units    TEXT;
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS onc_location_categories (
            location_code         TEXT NOT NULL,
            device_category_code  TEXT NOT NULL,
            PRIMARY KEY (location_code, device_category_code)
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS onc_location_categories_category_idx
        ON onc_location_categories (device_category_code)
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS onc_ctd_profiles (
            location_code TEXT,
            device_code   TEXT,
            cast_time     TIMESTAMPTZ,
            profile       JSONB,
            updated_at    TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (location_code, device_code, cast_time)
        )
    """)
    # ⛔ `cast_time` is NOT the time of a cast. It is the timestamp of the first
    # pressure sample inside the 7-day window WE ask ONC for, so it lands
    # exactly 7.00 days before every sync — measured on all 84 rows 2026-09-10.
    # These are moored, fixed-depth instruments: 27 of 28 device-locations span
    # under 5 m of pressure (RCNW4: 10,080 samples across 1.2 m; PVIP.C1:
    # 100,000 samples across 0.1 m).
    #
    # The columns below are ONC's own numbers, read straight off the response
    # we already hold, so the panel can state what the window covers instead of
    # us naming it a cast. ⛔ Nothing is dropped, filtered or recomputed — the
    # portal mirrors ONC 1:1 (Michal, 2026-09-10).
    for ddl in (
        "ALTER TABLE onc_ctd_profiles ADD COLUMN IF NOT EXISTS sample_start TIMESTAMPTZ",
        "ALTER TABLE onc_ctd_profiles ADD COLUMN IF NOT EXISTS sample_end   TIMESTAMPTZ",
        "ALTER TABLE onc_ctd_profiles ADD COLUMN IF NOT EXISTS n_samples    INTEGER",
        "ALTER TABLE onc_ctd_profiles ADD COLUMN IF NOT EXISTS depth_min_m  DOUBLE PRECISION",
        "ALTER TABLE onc_ctd_profiles ADD COLUMN IF NOT EXISTS depth_max_m  DOUBLE PRECISION",
    ):
        await conn.execute(ddl)


async def ensure_onc_ctd_series(conn) -> None:
    """onc_ctd_series, onc_deployment_citations — our accumulating ONC archive.

    ⛔ WHAT THIS IS, stated once so no panel has to guess: our own archive of
    the 10-minute series ONC publishes. It is NOT ONC's record, and it does not
    reach back before the day we started collecting.

    Why it exists. ONC's scalardata endpoint caps a response at 100,000 samples
    per property. Measured 2026-09-10 against BACAX: asking for 7 days of the
    raw 1 Hz stream returned 100,000 samples covering 1.2 days — the other 5.8
    were silently dropped. Asking for the same 7 days at `resamplePeriod=600`
    returned 1,009 samples covering the FULL window. So the resampled series is
    not a lesser product, it is the only one that comes back complete.

    ⛔ And it is still ONC's data 1:1. The averaging happens on THEIR side, by
    their method; we store what they answer, verbatim. Their `counts` column
    travels with it, so the number of raw samples behind each bin is disclosed
    rather than hidden, along with their qaqcFlags and the min/max they saw
    inside the bin. Nothing here is computed by us.

    Nine properties, not the three the profile plot plots: conductivity,
    density, depth, pressure, salinity, sigmat, sigmatheta, soundspeed and
    seawatertemperature all arrive in the same response and were being thrown
    away.

    Volume, measured before building: 28 device-locations x 9 properties x 144
    samples a day = 36,288 rows a day, 13.2M a year, roughly 1.5 GB a year
    against 37 GB free. Michal chose this cadence on 2026-09-10.
    """
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS onc_ctd_series (
            location_code TEXT        NOT NULL,
            device_code   TEXT        NOT NULL,
            property_code TEXT        NOT NULL,
            sample_time   TIMESTAMPTZ NOT NULL,
            value         DOUBLE PRECISION,
            unit          TEXT,
            -- ONC's own figures for this bin, stored because they are what
            -- makes the average readable rather than a bare number.
            qaqc_flag     SMALLINT,
            raw_count     INTEGER,           -- their `counts`
            -- ⛔ No value_min / value_max here. A dry run against live ONC on
            -- 2026-09-10 showed the resampled response carries counts,
            -- qaqcFlags, minTimes, maxTimes, minQuality and maxQuality — the
            -- TIMES of the extremes, never their values. Columns for them
            -- would have been 100% NULL forever, which is the exact defect
            -- this audit keeps finding in other people's tables.
            resample_s    INTEGER NOT NULL,  -- the cadence WE asked for, recorded
                                             -- so a later change is visible in the
                                             -- data rather than only in the code
            first_seen_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at    TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (location_code, device_code, property_code, sample_time)
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_onc_series_time "
        "ON onc_ctd_series (location_code, property_code, sample_time DESC)")

    # ONC returns a DOI and a formatted citation per deployment. Storing them is
    # a licence obligation, not decoration — a reader must be able to cite the
    # deployment their number came from.
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS onc_deployment_citations (
            location_code TEXT NOT NULL,
            device_code   TEXT NOT NULL,
            doi           TEXT NOT NULL,
            citation      TEXT,
            landing_page  TEXT,
            first_seen_at TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (location_code, device_code, doi)
        )
    """)


async def ensure_usgs_earthquakes(conn) -> None:
    """usgs_earthquakes."""

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS usgs_earthquakes (
            usgs_id    TEXT PRIMARY KEY,
            occurred_at TIMESTAMPTZ NOT NULL,
            magnitude  REAL,
            depth_km   REAL,
            place      TEXT,
            geom       GEOGRAPHY(POINT, 4326)
        )
    """)
    # ⛔ USGS states which magnitude SCALE it used, and the scales are not
    # interchangeable. Measured over the live M>=3 feed 2026-09-10 (1,577
    # events): mb 1,048 · ml 328 · mww 96 · md 82 · mwr 11 · mw 7. We stored
    # only the number and the panel printed "M4.2" — a bare figure the feed
    # never states on its own. `status` separates a reviewed solution from an
    # automatic one (1,572 vs 5 in that window), and `usgs_updated_at` is
    # USGS's own revision stamp, present on every event.
    for ddl in (
        "ALTER TABLE usgs_earthquakes ADD COLUMN IF NOT EXISTS mag_type        TEXT",
        "ALTER TABLE usgs_earthquakes ADD COLUMN IF NOT EXISTS status          TEXT",
        "ALTER TABLE usgs_earthquakes ADD COLUMN IF NOT EXISTS usgs_updated_at TIMESTAMPTZ",
    ):
        await conn.execute(ddl)
    # Verified against production 2026-09: reaches -2.84 km. This is CORRECT,
    # not a defect - USGS's own ComCat docs state the reference depth may be
    # relative to the WGS84 geoid, mean sea-level, or seismic-station
    # elevation, and events above that reference report as negative.
    await conn.execute("""
        COMMENT ON COLUMN usgs_earthquakes.depth_km IS
          'Kilometres below sea level. NEGATIVE values are correct - USGS reports events '
          'above sea level that way. Not a defect.'
    """)


