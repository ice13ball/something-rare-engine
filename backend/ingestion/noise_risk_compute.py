#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""
Compute noise_risk_grid from noise_cells × cetacean_cells.
Run after both ingestion scripts have populated their tables.
Run standalone: cd ~/something-rare/backend && source .venv/bin/activate && python3 ingestion/noise_risk_compute.py

⚠️ sync_noise_risk (backend/domains/acoustic.py) is triggered MANUALLY from the
admin dashboard, not on a weekly/scheduled cycle — this table does not
self-heal on deploy. If pbd_norm/spl_norm or the risk_index formula below
change, noise_risk_grid keeps serving whatever it last computed until someone
runs a Force Sync for "noise-risk". A deploy that changes the norm columns can
therefore leave the API serving a stale risk_index while the legend text
already describes the new formula — that gap is closed only by a manual sync,
not by this script running again on its own.
"""
import asyncio
import os
import asyncpg
import logging
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

DB_URL = os.environ.get("DATABASE_URL", "postgresql://abyssal_user:CHANGE_ME@localhost/abyssal")


def compute_risk_index(noise_measure: float, cetacean_norm: float | None, species_weight: float) -> float:
    """noise_measure (pbd_norm or spl_norm) × cetacean_norm × species_weight, clamped
    to [0, 1] with min(1.0, ...) — a clamp, not a divisor.

    risk_level()'s 0.8/0.6/0.4/0.2 thresholds are calibrated against this
    unscaled product. species_weight tops out at 2.0 (cetacean_ingest.IUCN_LOOKUP's
    "CR" band), so the product can reach 2.0 for the ~2% of cells that combine a
    high noise measure with a high cetacean_norm and the maximum weight — dividing
    by 2.0 to fix THAT would halve every cell's index, including the common
    species_weight=1.0 (NT/LC, the default) cells that never needed correction,
    silently re-banding "high"/"critical" cells down to "moderate"/"low" or lower.
    Clamping bounds only the cells that actually breach 1.0 and leaves everyone
    else's classification exactly as calibrated.
    """
    if cetacean_norm is not None:
        return min(1.0, noise_measure * cetacean_norm * species_weight)
    return min(1.0, noise_measure * 0.5)


def risk_level(idx: float, data_gap: bool) -> str:
    if data_gap:
        return "data_gap"
    if idx >= 0.8:
        return "critical"
    if idx >= 0.6:
        return "high"
    if idx >= 0.4:
        return "moderate"
    if idx >= 0.2:
        return "low"
    return "minimal"


def assign_region(lon: float, lat: float) -> str:
    if -30 <= lon <= 40 and 20 <= lat <= 80:
        return "north_atlantic"
    if -100 <= lon <= -30 and -60 <= lat <= 80:
        return "atlantic"
    if 40 <= lon <= 180 and 0 <= lat <= 80:
        return "pacific_north"
    if -180 <= lon <= -80 and 0 <= lat <= 80:
        return "pacific_north"
    if -10 <= lon <= 42 and 30 <= lat <= 47:
        return "mediterranean"
    return "global"


async def main():
    conn = await asyncpg.connect(DB_URL)

    # Fetch all noise cells. pbd_norm (ICES / EMODnet INER pulse-block days)
    # and spl_norm (EMODnet continuous SPL) are pulled separately and must
    # never be summed or averaged into one number — they measure different
    # things. See rules/subsystems/units-and-passthrough.md.
    noise_rows = await conn.fetch(
        "SELECT lon, lat, pbd_norm, spl_norm, pbd_year, pbd_year_min, pbd_year_max, "
        "source FROM noise_cells"
    )
    # Fetch all cetacean cells
    cet_rows = await conn.fetch(
        "SELECT cell_lon, cell_lat, sighting_count, max_iucn_weight, max_iucn_cat, top_species FROM cetacean_cells"
    )

    log.info("Loaded %d noise cells, %d cetacean cells", len(noise_rows), len(cet_rows))

    # Build cetacean lookup: (lon, lat) → row
    cet_map: dict[tuple[float, float], dict] = {}
    for r in cet_rows:
        cet_map[(r["cell_lon"], r["cell_lat"])] = dict(r)

    # Regional p95 normalisation for cetacean counts
    region_counts: dict[str, list[int]] = {}
    for r in cet_rows:
        reg = assign_region(r["cell_lon"], r["cell_lat"])
        region_counts.setdefault(reg, []).append(r["sighting_count"])
    region_p95: dict[str, float] = {
        reg: float(np.percentile(counts, 95)) if counts else 1.0
        for reg, counts in region_counts.items()
    }
    log.info("Regional p95: %s", region_p95)

    await conn.execute("TRUNCATE noise_risk_grid")

    inserted = 0
    for nr in noise_rows:
        lon, lat = nr["lon"], nr["lat"]
        pbd_norm = nr["pbd_norm"]
        spl_norm = nr["spl_norm"]
        pbd_year = nr["pbd_year"]
        pbd_year_min = nr["pbd_year_min"]
        pbd_year_max = nr["pbd_year_max"]

        # A noise_cells row is written by exactly one ingest function today —
        # ices/emodnet_iner set pbd_norm, emodnet sets spl_norm (noise_ingest.py)
        # — so both are non-null here only if a future source changes that.
        # Handle it explicitly rather than coalescing one value away: emit one
        # noise_risk_grid row per measure instead of blending pbd_norm and
        # spl_norm into a single risk figure.
        if pbd_norm is not None and spl_norm is not None:
            log.warning(
                "noise_cells row at %s,%s (source=%s) has BOTH pbd_norm and "
                "spl_norm set — emitting two noise_risk_grid rows instead of "
                "blending them",
                lon, lat, nr["source"],
            )
            measures = [("pbd", float(pbd_norm)), ("spl", float(spl_norm))]
        elif pbd_norm is not None:
            measures = [("pbd", float(pbd_norm))]
        elif spl_norm is not None:
            measures = [("spl", float(spl_norm))]
        else:
            log.warning(
                "noise_cells row at %s,%s (source=%s) has neither pbd_norm nor "
                "spl_norm — skipped",
                lon, lat, nr["source"],
            )
            continue

        cet = cet_map.get((lon, lat))
        if cet:
            reg = assign_region(lon, lat)
            p95 = region_p95.get(reg, 1.0) or 1.0
            cetacean_norm   = min(1.0, cet["sighting_count"] / p95)
            species_weight  = float(cet["max_iucn_weight"])
            cetacean_count  = cet["sighting_count"]
            max_species     = cet["top_species"]
        else:
            cetacean_norm   = None
            species_weight  = 1.0
            cetacean_count  = 0
            max_species     = None

        for kind, noise_measure in measures:
            risk_idx = compute_risk_index(noise_measure, cetacean_norm, species_weight)
            data_gap = (cetacean_norm is None) and (noise_measure > 0.3)

            level = risk_level(risk_idx, data_gap)
            # cell_key includes source and measure kind (not just lon/lat) so
            # that a future cell covered by more than one noise source, or by
            # both measures on one row, gets distinct grid rows instead of a
            # UNIQUE-constraint collision that silently drops one of them.
            cell_key = f"{lon}_{lat}_{nr['source']}_{kind}"
            pbd_val = noise_measure if kind == "pbd" else None
            spl_val = noise_measure if kind == "spl" else None
            # pbd_year/_min/_max travel with the pbd measure only — an spl-kind
            # row has no year data (EMODnet's continuous-SPL source never asked
            # for one), so it must not inherit the pbd row's year by accident.
            year_val = pbd_year if kind == "pbd" else None
            year_min_val = pbd_year_min if kind == "pbd" else None
            year_max_val = pbd_year_max if kind == "pbd" else None

            await conn.execute("""
                INSERT INTO noise_risk_grid
                  (geom, lon, lat, cell_key, pbd_norm, spl_norm, pbd_year, pbd_year_min, pbd_year_max,
                   cetacean_norm, species_weight,
                   risk_index, risk_level, data_gap, noise_source, cetacean_count, max_species, computed_at)
                VALUES
                  (ST_SetSRID(ST_MakePoint($1,$2),4326), $1, $2, $3, $4, $5, $6, $7, $8,
                   $9, $10, $11, $12, $13, $14, $15, $16, NOW())
            """, lon, lat, cell_key, pbd_val, spl_val, year_val, year_min_val, year_max_val,
                 cetacean_norm, species_weight,
                 risk_idx, level, data_gap, nr["source"], cetacean_count, max_species)
            inserted += 1

    log.info("Done. noise_risk_grid: %d rows inserted", inserted)

    summary = await conn.fetch(
        "SELECT risk_level, COUNT(*) FROM noise_risk_grid GROUP BY risk_level ORDER BY COUNT(*) DESC"
    )
    for row in summary:
        log.info("  %s: %d cells", row["risk_level"], row["count"])

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
