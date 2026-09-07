# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Schema DDL — cables domain. Extracted verbatim from the former backend/schema.py.
"""
from __future__ import annotations
import logging

# Restored 2026-08-21. The split of schema.py into this package left `log`
# behind in the original module while nine `log.debug(...)` calls came across —
# every one of them inside an `except` clause. A tolerated DDL failure would
# therefore raise NameError from its own handler and take the boot down with it.
# The DDL snapshot test could not see this: it compares statements, not error paths.
log = logging.getLogger(__name__)

async def ensure_cables(conn) -> None:
    """submarine_cables, onc_cables, ooi_cables, noaa_cables, nz_cables, au_cables, onc_instruments."""

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS submarine_cables (
            id          SERIAL PRIMARY KEY,
            name        TEXT,
            status      TEXT,
            inst_year   INTEGER,
            length_km   DOUBLE PRECISION,
            location    TEXT,
            geom        geometry(MultiLineString, 4326),
            created_at  TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_submarine_cables_geom ON submarine_cables USING GIST (geom)")

    # Multi-layer EMODnet schema extension (added 2026-05-11)
    await conn.execute("ALTER TABLE submarine_cables ADD COLUMN IF NOT EXISTS operator     TEXT")
    await conn.execute("ALTER TABLE submarine_cables ADD COLUMN IF NOT EXISTS cable_type   TEXT")
    await conn.execute("ALTER TABLE submarine_cables ADD COLUMN IF NOT EXISTS voltage_kv   REAL")
    await conn.execute("ALTER TABLE submarine_cables ADD COLUMN IF NOT EXISTS source_layer TEXT")
    await conn.execute("ALTER TABLE submarine_cables ADD COLUMN IF NOT EXISTS source_id    TEXT")
    # Replace old (name, status) unique constraint with (source_layer, source_id)
    try:
        await conn.execute("ALTER TABLE submarine_cables DROP CONSTRAINT IF EXISTS submarine_cables_name_status_key")
    except Exception as _exc:
        log.debug("submarine_cables old constraint drop skipped: %s", _exc)
    try:
        await conn.execute("DROP INDEX IF EXISTS idx_submarine_cables_name_status")
    except Exception as _exc:
        log.debug("submarine_cables old unique index drop skipped: %s", _exc)
    await conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS submarine_cables_source_unique
          ON submarine_cables (source_layer, source_id)
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS onc_cables (
            id          SERIAL PRIMARY KEY,
            ext_id      TEXT,
            status      TEXT,
            length_m    DOUBLE PRECISION,
            comments    TEXT,
            geom        geometry(MultiLineString, 4326),
            created_at  TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_onc_cables_geom ON onc_cables USING GIST (geom)")
    try:
        await conn.execute("ALTER TABLE onc_cables OWNER TO abyssal_user")
    except Exception:
        pass

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS ooi_cables (
            id          SERIAL PRIMARY KEY,
            ext_id      TEXT,
            line_name   TEXT,
            length_m    DOUBLE PRECISION,
            comments    TEXT,
            geom        geometry(MultiLineString, 4326),
            created_at  TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_ooi_cables_geom ON ooi_cables USING GIST (geom)")
    for _col, _typedef in [
        ("deepest_node_m",   "INT"),
        ("shallowest_node_m","INT"),
        ("node_count",       "INT"),
    ]:
        try:
            await conn.execute(f"ALTER TABLE ooi_cables ADD COLUMN IF NOT EXISTS {_col} {_typedef}")
        except Exception:
            pass
    try:
        await conn.execute("ALTER TABLE ooi_cables OWNER TO abyssal_user")
    except Exception:
        pass

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS noaa_cables (
            id            SERIAL PRIMARY KEY,
            object_id     INTEGER UNIQUE,
            short_name    TEXT,
            cable_system  TEXT,
            owner         TEXT,
            status        TEXT,
            region        TEXT,
            shape_length  DOUBLE PRECISION,
            geom          geometry(MultiPolygon, 4326) NOT NULL,
            fetched_at    TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_noaa_cables_geom ON noaa_cables USING GIST (geom)")
    try:
        await conn.execute("ALTER TABLE noaa_cables OWNER TO abyssal_user")
    except Exception as _exc:
        log.debug("noaa_cables OWNER alter skipped: %s", _exc)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS nz_cables (
            id          SERIAL PRIMARY KEY,
            fidn        TEXT UNIQUE NOT NULL,
            catcbl      TEXT,
            catcbl_raw  INTEGER,
            status      TEXT,
            status_raw  INTEGER,
            condtn      TEXT,
            condtn_raw  INTEGER,
            objnam      TEXT,
            inform      TEXT,
            txtdsc      TEXT,
            burdep      REAL,
            datsta      DATE,
            datend      DATE,
            geom        geometry(MultiLineString, 4326) NOT NULL,
            fetched_at  TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_nz_cables_geom ON nz_cables USING GIST (geom)")
    try:
        await conn.execute("ALTER TABLE nz_cables OWNER TO abyssal_user")
    except Exception as _exc:
        log.debug("nz_cables OWNER alter skipped: %s", _exc)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS au_cables (
            id          SERIAL PRIMARY KEY,
            object_id   INTEGER UNIQUE NOT NULL,
            cable       TEXT,
            abbrev      TEXT,
            geom        geometry(MultiLineString, 4326) NOT NULL,
            fetched_at  TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_au_cables_geom ON au_cables USING GIST (geom)")
    try:
        await conn.execute("ALTER TABLE au_cables OWNER TO abyssal_user")
    except Exception as _exc:
        log.debug("au_cables OWNER alter skipped: %s", _exc)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS onc_instruments (
            id                SERIAL PRIMARY KEY,
            device_id         BIGINT UNIQUE,
            device_code       TEXT,
            device_name       TEXT,
            device_category   TEXT,
            location_code     TEXT,
            location_name     TEXT,
            site_name         TEXT,
            depth_m           DOUBLE PRECISION,
            image_url         TEXT,
            geom              geometry(Point, 4326),
            updated_at        TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_onc_instruments_geom ON onc_instruments USING GIST (geom)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_onc_instruments_category ON onc_instruments (device_category)")
    for col, ddl in [
        ("deployment_start", "TIMESTAMPTZ"),
        ("deployment_end",   "TIMESTAMPTZ"),
        ("status",           "TEXT"),
        ("description",      "TEXT"),
        ("data_products",    "JSONB"),
        ("device_link",      "TEXT"),
        ("location_link",    "TEXT"),
        ("enriched_at",      "TIMESTAMPTZ"),
        ("latest_readings",  "JSONB"),
        ("readings_at",      "TIMESTAMPTZ"),
    ]:
        await conn.execute(f"ALTER TABLE onc_instruments ADD COLUMN IF NOT EXISTS {col} {ddl}")
    try:
        await conn.execute("ALTER TABLE onc_instruments OWNER TO abyssal_user")
    except Exception:
        pass
    # (Legacy (name, status) dedup query removed 2026-05-11 — multi-layer schema
    # uses (source_layer, source_id) unique index; TRUNCATE+insert leaves no
    # duplicates at steady state. See spec 2026-05-11-emodnet-multilayer.)
    try:
        await conn.execute("ALTER TABLE submarine_cables OWNER TO abyssal_user")
    except Exception:
        pass


