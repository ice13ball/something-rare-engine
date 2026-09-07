# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Schema DDL — offshore domain. Extracted verbatim from the former backend/schema.py.
"""
from __future__ import annotations
import logging

# Restored 2026-08-21. The split of schema.py into this package left `log`
# behind in the original module while nine `log.debug(...)` calls came across —
# every one of them inside an `except` clause. A tolerated DDL failure would
# therefore raise NameError from its own handler and take the boot down with it.
# The DDL snapshot test could not see this: it compares statements, not error paths.
log = logging.getLogger(__name__)

async def ensure_ports(conn) -> None:
    """port_locations."""

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS port_locations (
            id          SERIAL PRIMARY KEY,
            city        TEXT,
            state       TEXT,
            country     TEXT,
            geom        geometry(Point, 4326),
            created_at  TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_port_locations_geom ON port_locations USING GIST (geom)")
    try:
        await conn.execute("ALTER TABLE port_locations OWNER TO abyssal_user")
    except Exception:
        pass


async def ensure_offshore_activities(conn) -> None:
    """offshore_activities."""

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS offshore_activities (
            id            SERIAL PRIMARY KEY,
            source        TEXT NOT NULL,
            source_id     TEXT,
            activity_type TEXT NOT NULL,
            name          TEXT,
            operator      TEXT,
            country       TEXT,
            sovereign     TEXT,
            status        TEXT,
            awarded_date  DATE,
            expires_date  DATE,
            jurisdiction  TEXT,
            portal_url    TEXT,
            attributes    JSONB,
            geom          GEOMETRY(MultiPolygon, 4326) NOT NULL,
            updated_at    TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(source, source_id)
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS offshore_activities_geom_gix
        ON offshore_activities USING GIST(geom)
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS offshore_activities_type_idx
        ON offshore_activities(activity_type)
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS offshore_activities_country_idx
        ON offshore_activities(sovereign)
    """)
    # Precomputed Web Mercator geometry — eliminates per-tile-request ST_Transform,
    # the dominant CPU cost at z=7-8 over dense regions. PG12+ GENERATED ALWAYS
    # auto-populates from `geom`; no trigger or sync-function changes needed.
    try:
        await conn.execute("""
            ALTER TABLE offshore_activities
            ADD COLUMN IF NOT EXISTS geom_3857 GEOMETRY
            GENERATED ALWAYS AS (ST_Transform(geom, 3857)) STORED
        """)
    except Exception as e:
        log.warning("offshore_activities geom_3857 column add failed: %s", e)
    try:
        await conn.execute("ALTER TABLE offshore_activities OWNER TO abyssal_user")
    except Exception:
        pass


