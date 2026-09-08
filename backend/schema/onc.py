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
    # Verified against production 2026-09: reaches -2.84 km. This is CORRECT,
    # not a defect - USGS's own ComCat docs state the reference depth may be
    # relative to the WGS84 geoid, mean sea-level, or seismic-station
    # elevation, and events above that reference report as negative.
    await conn.execute("""
        COMMENT ON COLUMN usgs_earthquakes.depth_km IS
          'Kilometres below sea level. NEGATIVE values are correct - USGS reports events '
          'above sea level that way. Not a defect.'
    """)


