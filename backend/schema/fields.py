# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Schema DDL — fields domain. Extracted verbatim from the former backend/schema.py.
"""
from __future__ import annotations

async def ensure_vme(conn) -> None:
    """vme_cells, vme_models, vme_bake_control, vme_exposure_cells."""

    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS vme_cells (
            cell_id       TEXT,
            taxon_set     TEXT,
            suitability   DOUBLE PRECISION,
            uncertainty   DOUBLE PRECISION,
            extrapolated  BOOLEAN,
            top_predictors JSONB,
            PRIMARY KEY (taxon_set, cell_id)
        )
        """
    )
    await conn.execute("ALTER TABLE vme_cells OWNER TO abyssal_user")
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS vme_models (
            id             SERIAL PRIMARY KEY,
            taxon_set      TEXT,
            model          TEXT,
            n_occurrences  INT,
            auc            DOUBLE PRECISION,
            boyce          DOUBLE PRECISION,
            var_importance JSONB,
            aphia_ids      INT[],
            published      BOOLEAN,
            trained_at     TIMESTAMPTZ DEFAULT now()
        )
        """
    )
    await conn.execute("ALTER TABLE vme_models OWNER TO abyssal_user")
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS vme_bake_control (
            id             BOOLEAN PRIMARY KEY DEFAULT TRUE,
            force_requested BOOLEAN DEFAULT FALSE,
            requested_at   TIMESTAMPTZ,
            CONSTRAINT vme_bake_control_singleton CHECK (id)
        )
        """
    )
    await conn.execute("ALTER TABLE vme_bake_control OWNER TO abyssal_user")
    await conn.execute("INSERT INTO vme_bake_control (id) VALUES (TRUE) ON CONFLICT (id) DO NOTHING")

    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS vme_exposure_cells (
            cell_id           TEXT PRIMARY KEY,
            taxon_set         TEXT,
            suitability       DOUBLE PRECISION,
            uncertainty       DOUBLE PRECISION,
            lat               DOUBLE PRECISION,
            lon               DOUBLE PRECISION,
            seafloor_m        DOUBLE PRECISION,
            horizon_today_m   DOUBLE PRECISION,
            horizon_pi_m      DOUBLE PRECISION,
            state             TEXT NOT NULL,
            geom              geometry(Polygon, 4326)
        );
        """
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS vme_exposure_cells_gix ON vme_exposure_cells USING GIST (geom)")
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS vme_exposure_cells_state_idx ON vme_exposure_cells (state)")
    await conn.execute("ALTER TABLE vme_exposure_cells OWNER TO abyssal_user")


