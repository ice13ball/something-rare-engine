# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Schema DDL — acoustic domain. Extracted verbatim from the former backend/schema.py.
"""
from __future__ import annotations
import logging

# Restored 2026-08-21. The split of schema.py into this package left `log`
# behind in the original module while nine `log.debug(...)` calls came across —
# every one of them inside an `except` clause. A tolerated DDL failure would
# therefore raise NameError from its own handler and take the boot down with it.
# The DDL snapshot test could not see this: it compares statements, not error paths.
log = logging.getLogger(__name__)

async def ensure_acoustic_stations(conn) -> None:
    """acoustic_stations, acoustic_soundscape."""
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS usgs_earthquakes_geom_gix
        ON usgs_earthquakes USING GIST (geom)
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS usgs_earthquakes_time
        ON usgs_earthquakes (occurred_at DESC)
    """)

    # acoustic_stations — hydrophone stations from observatory networks
    # (OOI/IMOS/MARS/PALAOA/OBSEA/KM3NeT/NRS/SanctSound/NEFSC)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS acoustic_stations (
            station_id      TEXT PRIMARY KEY,
            source          TEXT NOT NULL CHECK (source IN ('ooi','imos','mars','palaoa','obsea','km3net','nrs','sanctsound','nefsc','pifsc','sefsc','onms','adeon','boem','aeon','navy','nps','jasco','fram','coastal_studies_institute','ioos','sambah','ims')),
            name            TEXT,
            operator        TEXT,
            lat             DOUBLE PRECISION NOT NULL,
            lon             DOUBLE PRECISION NOT NULL,
            depth_m         REAL,
            deploy_start    DATE,
            deploy_end      DATE,
            model           TEXT,
            hz_range_lo     REAL,
            hz_range_hi     REAL,
            portal_url      TEXT,
            license         TEXT,
            fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            geom            GEOGRAPHY(POINT, 4326) GENERATED ALWAYS AS (
                                ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography
                            ) STORED
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS acoustic_stations_geom_gix
        ON acoustic_stations USING GIST(geom)
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS acoustic_stations_source_idx
        ON acoustic_stations (source)
    """)
    await conn.execute("ALTER TABLE acoustic_stations OWNER TO abyssal_user")
    # Per-dataset license metadata (P-Polar task) — populated by ingests that
    # verified their source licenses (HAUSGARTEN CC BY 4.0, SAMBAH CC0 1.0).
    await conn.execute("ALTER TABLE acoustic_stations ADD COLUMN IF NOT EXISTS license TEXT")

    # Migration: expand source enum
    # Phase 2 P1: added nrs/sanctsound
    # Phase 2 P3: added nefsc
    # Phase 2 P4 (this migration): added 12 NOAA-archive programs (pifsc,
    #   sefsc, onms, adeon, boem, aeon, navy, nps, jasco, fram,
    #   coastal_studies_institute, ioos) — 21 total enum members.
    # Phase 3: added sambah (Baltic Sea C-POD) — 22 total enum members.
    #   HAUSGARTEN reuses the existing 'fram' enum; no new enum needed for it.
    # Phase 4: added ims (CTBTO IMS Hydroacoustic Network) — 23 total.
    try:
        await conn.execute("ALTER TABLE acoustic_stations DROP CONSTRAINT IF EXISTS acoustic_stations_source_check")
        await conn.execute(
            "ALTER TABLE acoustic_stations ADD CONSTRAINT acoustic_stations_source_check "
            "CHECK (source IN ("
            "'ooi','imos','mars','palaoa','obsea','km3net','nrs','sanctsound','nefsc',"
            "'pifsc','sefsc','onms','adeon','boem','aeon','navy','nps','jasco','fram',"
            "'coastal_studies_institute','ioos','sambah','ims'))"
        )
    except Exception as exc:
        log.warning("acoustic_stations CHECK constraint migration: %s", exc)

    # acoustic_soundscape — daily soundscape metrics per station
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS acoustic_soundscape (
            station_id          TEXT NOT NULL REFERENCES acoustic_stations(station_id) ON DELETE CASCADE,
            day                 DATE NOT NULL,
            broadband_spl_db    REAL,
            spl_10hz_db         REAL,
            spl_63hz_db         REAL,
            spl_100hz_db        REAL,
            spl_125hz_db        REAL,
            spl_1khz_db         REAL,
            spl_10khz_db        REAL,
            l50_db              REAL,
            l95_db              REAL,
            n_minutes_recorded  INTEGER,
            source_url          TEXT,
            fetched_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (station_id, day)
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS acoustic_soundscape_day_idx
        ON acoustic_soundscape (day DESC)
    """)
    await conn.execute("ALTER TABLE acoustic_soundscape OWNER TO abyssal_user")


