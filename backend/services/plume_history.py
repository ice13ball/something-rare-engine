# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Batch pre-computation and storage of RK4 plume back-track paths."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta

import asyncpg

from services.ocean_currents import backtrack, CMEMSUnavailableError, CMEMSTooRecentError

log = logging.getLogger(__name__)

REANALYSIS_LAG_DAYS = 28
DEFAULT_HOURS = 168   # 7 days back-track
DEFAULT_DEPTH = 1000  # metres


def _dataset_label(profile_date: datetime) -> str:
    """Return 'nrt' for recent profiles, 'reanalysis' for older ones."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=REANALYSIS_LAG_DAYS)
    dt = profile_date if profile_date.tzinfo else profile_date.replace(tzinfo=timezone.utc)
    return "nrt" if dt > cutoff else "reanalysis"


async def _resolve_contractor(pool: asyncpg.Pool, origin_lon: float, origin_lat: float) -> str | None:
    """
    Spatial lookup: find which mining contract (if any) the back-tracked origin
    point falls inside. Returns contractor_name or None if origin is in open ocean.

    This catches cases where the water mass came from a licensed area even when
    the Argo float itself was not flagged as near_mining.
    """
    row = await pool.fetchrow(
        """
        SELECT contractor_name
        FROM mining_contracts
        WHERE ST_Contains(
            geom::geometry,
            ST_SetSRID(ST_MakePoint($1, $2), 4326)
        )
        LIMIT 1
        """,
        origin_lon,
        origin_lat,
    )
    return row["contractor_name"] if row else None


async def compute_pending_plume_paths(
    pool: asyncpg.Pool,
    max_batch: int = 100,
    hours: int = DEFAULT_HOURS,
    depth: int = DEFAULT_DEPTH,
) -> int:
    """
    Back-track up to `max_batch` Argo profiles (ALL profiles, not just near_mining)
    that have no stored plume path yet. Stores results in `plume_paths`.

    contractor_name is resolved via PostGIS after back-tracking:
    - If the back-tracked origin falls inside a licensed mining contract → contractor_name set
    - If origin is in open ocean (no license) → contractor_name is NULL
      (useful for detecting unlicensed / illegal mining activity)

    Returns the number of paths successfully computed and stored.
    """
    rows = await pool.fetch(
        """
        SELECT
            ap.profile_id,
            ap.platform_id,
            ap.profile_date,
            ST_X(ap.geom::geometry) AS lon,
            ST_Y(ap.geom::geometry) AS lat
        FROM argo_profiles ap
        LEFT JOIN plume_paths pp ON pp.profile_id = ap.profile_id
        WHERE pp.profile_id IS NULL
        ORDER BY ap.profile_date DESC
        LIMIT $1
        """,
        max_batch,
    )

    if not rows:
        log.info("plume_history: no pending profiles")
        return 0

    log.info("plume_history: computing %d paths", len(rows))
    computed = 0
    loop = asyncio.get_running_loop()

    for row in rows:
        profile_id = row["profile_id"]
        try:
            result = await loop.run_in_executor(
                None,
                lambda r=row: backtrack(
                    lon=r["lon"],
                    lat=r["lat"],
                    date=r["profile_date"],
                    depth_m=depth,
                    hours=hours,
                ),
            )

            if result.steps_completed < 2:
                log.debug("plume_history: skipping %s (%d steps)", profile_id, result.steps_completed)
                continue

            # Resolve which contract (if any) the origin falls inside
            contractor_name = await _resolve_contractor(pool, result.origin[0], result.origin[1])

            await pool.execute(
                """
                INSERT INTO plume_paths
                    (profile_id, platform_id, profile_date, origin_lon, origin_lat,
                     path_coords, speed_cms, steps_completed, source_dataset, contractor_name)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9, $10)
                ON CONFLICT (profile_id) DO NOTHING
                """,
                profile_id,
                row["platform_id"],
                row["profile_date"],
                result.origin[0],
                result.origin[1],
                json.dumps(result.path),
                result.speed_cms,
                result.steps_completed,
                _dataset_label(row["profile_date"]),
                contractor_name,
            )
            computed += 1
            log.debug("plume_history: stored path for %s (origin contractor: %s)", profile_id, contractor_name or "none")

        except (CMEMSUnavailableError, CMEMSTooRecentError) as exc:
            log.debug("plume_history: CMEMS skip for %s — %s", profile_id, exc)
        except Exception as exc:
            log.warning("plume_history: failed for %s — %s", profile_id, exc)

        await asyncio.sleep(0.5)

    log.info("plume_history: %d/%d paths stored", computed, len(rows))
    return computed
