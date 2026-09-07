# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Coral Acidification Exposure — crosses the VME coral-suitability model with the
aragonite saturation horizon to report how much modeled habitat sits in undersaturated
("corrosive") water, and how much of that became corrosive only in the industrial era.

EXPOSURE, NOT LOSS. Omega_arag < 1 means the water is undersaturated with respect to
aragonite. It does NOT mean the coral is dead or doomed: cold-water corals are documented
living below the aragonite saturation horizon, calcifying at metabolic cost. Every string
this module feeds to the UI must respect that distinction.

Pure helpers only — no DB, no numpy, no I/O. The bake orchestration lives in
`bake_exposure()` at the bottom and imports its heavy dependencies lazily.
"""
from __future__ import annotations

import math

# Priority order is meaningful for legends: most-alarming state first.
STATES = ("newly_corrosive", "corrosive_preindustrial", "supersaturated", "no_data")

EXPOSED_STATES = frozenset({"newly_corrosive", "corrosive_preindustrial"})

STATE_COLORS: dict[str, tuple[int, int, int, int]] = {
    "newly_corrosive":         (190, 30, 90, 205),    # magenta — the industrial-era change
    "corrosive_preindustrial": (140, 90, 150, 190),   # muted purple — corrosive before 1850
    "supersaturated":          (60, 140, 175, 175),   # calm blue — bed in supersaturated water
    "no_data":                 (148, 163, 184, 90),   # slate — same null convention as siblings
}

CITATION = (
    "Platform-derived analysis. Habitat: our own MaxEnt VME coral-suitability model "
    "(modeled, not observed; predictors include GEBCO 2024, seabed substrate "
    "Dutkiewicz et al. 2015 (CC-BY-NC), WOA23, ISAS, GLODAPv2). Aragonite saturation "
    "horizons reconstructed with PyCO2SYS from GLODAP v2.2016b present-day (TCO2) and "
    "preindustrial (PI_TCO2) dissolved inorganic carbon (Lauvset et al. 2016, ESSD 8:325; "
    "Key et al. 2015, NDP-093; PyCO2SYS: Humphreys et al. 2022, GMD 15:15). Seafloor depth: "
    "GEBCO 2024. Exposure to undersaturated water — NOT a prediction of habitat loss."
)


def _bad(x) -> bool:
    """True when a numeric input is absent or not-a-number. Accepts numpy scalars: they
    satisfy math.isnan, whereas isinstance(x, float) is False for numpy.float32."""
    if x is None:
        return True
    try:
        return math.isnan(float(x))
    except (TypeError, ValueError):
        return True


def classify(seafloor_m, horizon_today_m, horizon_pi_m) -> str:
    """Classify one cell by where its seafloor sits relative to both horizons.

    `seafloor_m` is a POSITIVE depth in metres below sea level. GEBCO returns elevation
    (negative below sea level), so callers pass `-elevation`; a non-positive value therefore
    means the cell was land and is rejected as no_data.

    `math.inf` for a horizon means the water column never crosses omega=1, i.e. it is
    supersaturated all the way down — no seafloor in that column can be exposed.
    """
    if _bad(seafloor_m) or _bad(horizon_today_m) or _bad(horizon_pi_m):
        return "no_data"
    bed = float(seafloor_m)
    if bed <= 0.0:
        return "no_data"
    today = float(horizon_today_m)
    pi = float(horizon_pi_m)
    if bed <= today:
        return "supersaturated"
    if bed <= pi:
        return "newly_corrosive"
    return "corrosive_preindustrial"


def weighted_exposure(rows) -> dict:
    """Suitability-weighted exposure over (suitability, state) pairs.

    Weighting by the continuous suitability removes the arbitrary "what counts as habitat?"
    threshold that a simple cell count would smuggle in. `no_data` cells are excluded from
    BOTH numerator and denominator — counting them as unexposed would bias the headline down.
    Returns None (not 0.0) when nothing is classifiable, so the caller can say "no data"
    rather than report a confident zero.
    """
    total = 0.0
    exposed = 0.0
    newly = 0.0
    for suitability, state in rows:
        if state == "no_data" or _bad(suitability):
            continue
        w = float(suitability)
        total += w
        if state in EXPOSED_STATES:
            exposed += w
        if state == "newly_corrosive":
            newly += w
    if total <= 0.0:
        return {"exposed": None, "newly": None, "total_weight": 0.0}
    return {"exposed": exposed / total, "newly": newly / total, "total_weight": total}


def threshold_table(rows, cutoffs=(0.3, 0.5, 0.7)) -> list[dict]:
    """Count-based exposure at several suitability cutoffs, shown beside the weighted
    headline so a reader can see how much the answer depends on the threshold choice.
    A cutoff that captures no cells reports None rather than dividing by zero.
    """
    out = []
    for cutoff in cutoffs:
        sel = [(s, st) for s, st in rows
               if st != "no_data" and not _bad(s) and float(s) >= cutoff]
        n = len(sel)
        if n == 0:
            out.append({"cutoff": cutoff, "n_cells": 0,
                        "exposed_pct": None, "newly_pct": None})
            continue
        n_exposed = sum(1 for _, st in sel if st in EXPOSED_STATES)
        n_newly = sum(1 for _, st in sel if st == "newly_corrosive")
        out.append({"cutoff": cutoff, "n_cells": n,
                    "exposed_pct": 100.0 * n_exposed / n,
                    "newly_pct": 100.0 * n_newly / n})
    return out


def seafloor_from_elevation(elevation_m):
    """Convert a GEBCO elevation to a positive seafloor depth, or None on land.

    Verified against the live baked grid 2026-07-20: Fram Strait -2713.0, Gotland Deep
    -242.0, Station Papa -4253.0, Sahara +756.0. So negative is below sea level, and
    elevation >= 0 is land, which has no seafloor depth to classify.
    """
    if _bad(elevation_m):
        return None
    e = float(elevation_m)
    return None if e >= 0.0 else -e


async def bake_exposure(pool) -> dict:
    """Join vme_cells to the hex grid, sample seafloor depth and both horizons, classify,
    and write vme_exposure_cells. Heavy imports are lazy so the pure helpers above stay
    testable without them.

    Prerequisites are checked rather than assumed: this needs vme_cells populated AND the
    acidification horizon reconstructions AND the baked GEBCO grid. Any missing one is a
    graceful skip, not a crash — on a cold environment the GEBCO grid is produced by a
    startup task that may not have run yet.
    """
    from services import acidification as acid            # runtime import: bare, not backend.*
    from services import bathymetry_grid_export as bg
    from services import glodap_carbon
    from services import vme_sdm

    async with pool.acquire() as conn:
        n_vme = await conn.fetchval(
            "SELECT count(*) FROM vme_cells WHERE taxon_set=$1", vme_sdm.TAXON_SET
        )
    if not n_vme:
        return {"cells": 0, "skipped": "vme_cells is empty", "summary": {}}
    if bg._load_grid("depth") is None:
        return {"cells": 0, "skipped": "baked GEBCO grid absent", "summary": {}}
    h_today = acid.horizon_recon_grid("today")
    h_pi = acid.horizon_recon_grid("pi")
    if h_today is None or h_pi is None:
        return {"cells": 0, "skipped": "GLODAP holdings absent", "summary": {}}
    axes = acid._load_grid("aragonite")

    async with pool.acquire() as conn:
        # vme_cells' primary key is (taxon_set, cell_id) — several taxon sets can share a
        # cell_id. vme_exposure_cells is keyed on cell_id ALONE (one row per hex, matching
        # its API/frontend/export contract), so an unfiltered join would return one row per
        # taxon_set per cell and the INSERT below would violate that single-column PK the
        # moment a second taxon set is published. Filter here, exactly like the established
        # /v1/vme/hexes consumer in domains/fields/habitat.py (`WHERE v.taxon_set=$1` with
        # vme_sdm.TAXON_SET).
        rows = await conn.fetch(
            """
            SELECT v.cell_id, v.taxon_set, v.suitability, v.uncertainty,
                   ST_Y(ST_Centroid(d.geom)) AS lat,
                   ST_X(ST_Centroid(d.geom)) AS lon,
                   ST_AsText(d.geom)         AS wkt
            FROM vme_cells v
            JOIN density_hex_cells d USING (cell_id)
            WHERE v.taxon_set=$1
            """,
            vme_sdm.TAXON_SET,
        )

    out = []
    pairs = []
    for r in rows:
        lat, lon = float(r["lat"]), float(r["lon"])
        bed = seafloor_from_elevation(bg.sample("depth", lat, lon, None))
        yi = glodap_carbon._nearest_idx(axes.lats, lat)
        xi = glodap_carbon._nearest_idx(axes.lons, lon)

        def _h(grid):
            v = grid[yi, xi]
            if math.isnan(float(v)):
                return None
            return math.inf if math.isinf(float(v)) else float(v)

        ht, hp = _h(h_today), _h(h_pi)
        state = classify(bed, ht, hp)
        pairs.append((r["suitability"], state))
        out.append((r["cell_id"], r["taxon_set"], r["suitability"], r["uncertainty"],
                    lat, lon, bed,
                    None if ht is None or math.isinf(ht) else ht,
                    None if hp is None or math.isinf(hp) else hp,
                    state, r["wkt"]))

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("TRUNCATE vme_exposure_cells")
            await conn.executemany(
                """
                INSERT INTO vme_exposure_cells
                    (cell_id, taxon_set, suitability, uncertainty, lat, lon,
                     seafloor_m, horizon_today_m, horizon_pi_m, state, geom)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10, ST_GeomFromText($11, 4326))
                """,
                out,
            )

    summary = {
        "weighted": weighted_exposure(pairs),
        "thresholds": threshold_table(pairs),
        "counts": {s: sum(1 for _, st in pairs if st == s) for s in STATES},
        "citation": CITATION,
    }
    return {"cells": len(out), "skipped": None, "summary": summary}
