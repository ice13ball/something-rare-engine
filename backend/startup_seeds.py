# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Two of the sixteen startup schema steps, moved out of main.py so a script
can import them without importing the whole application.

main.py:1212 does `_db.pool = _pool`, so `main._pool` and `db.pool` are the
same object — reading `db.pool` here at call time (not `from db import pool`,
which would capture None at import time) is behaviour-identical.
"""

import json
import logging

import db

log = logging.getLogger(__name__)

LAYER_CONFIG_DDL = """
CREATE TABLE IF NOT EXISTS layer_config (
    id          TEXT PRIMARY KEY,
    order_idx   INTEGER NOT NULL,
    default_on  BOOLEAN NOT NULL DEFAULT FALSE,
    modes       TEXT[] NOT NULL DEFAULT ARRAY['ocean','land','continue']::TEXT[],
    updated_at  TIMESTAMPTZ DEFAULT now(),
    updated_by  TEXT
);
CREATE INDEX IF NOT EXISTS layer_config_order_idx ON layer_config (order_idx);
"""

# Mirror of frontend/src/utils/layerConfig.ts LAYER_DEFAULTS.
# KEEP IN SYNC — this is the one-time DB seed only; TS list is the runtime fallback.
LAYER_DEFAULTS_PY = [
    # Bathymetry MUST stay at the lowest order_idx so the GEBCO shaded-relief
    # tiles render behind every other layer. See KEEP-IN-SYNC note in
    # frontend/src/utils/layerConfig.ts.
    {"id": "bathymetry",             "order_idx": 50,   "default_on": False, "modes": ["ocean","continue"]},
    {"id": "tectonic-plates",        "order_idx": 100,  "default_on": False, "modes": ["ocean","continue"]},
    {"id": "offshore-activities",    "order_idx": 200,  "default_on": False, "modes": ["ocean","continue"]},
    {"id": "relinquished-areas",     "order_idx": 300,  "default_on": True,  "modes": ["ocean","continue"]},
    {"id": "reserved-areas",         "order_idx": 400,  "default_on": True,  "modes": ["ocean","continue"]},
    {"id": "apeis",                  "order_idx": 500,  "default_on": True,  "modes": ["ocean","continue"]},
    {"id": "eez",                    "order_idx": 600,  "default_on": False, "modes": ["ocean","continue"]},
    {"id": "protected-marine-sites", "order_idx": 700,  "default_on": True,  "modes": ["ocean","continue"]},
    {"id": "contracts",              "order_idx": 800,  "default_on": True,  "modes": ["ocean","continue"]},
    {"id": "seamounts",              "order_idx": 900,  "default_on": False, "modes": ["ocean","continue"]},
    {"id": "biodiversity-hotspots",  "order_idx": 1000, "default_on": True,  "modes": ["ocean","continue"]},
    {"id": "monitoring-density",     "order_idx": 1100, "default_on": False, "modes": ["ocean","continue"]},
    {"id": "noise-risk",             "order_idx": 1200, "default_on": False, "modes": ["ocean","continue"]},
    {"id": "hydrophone-stations",    "order_idx": 1250, "default_on": False, "modes": ["ocean","continue"]},
    {"id": "argo",                   "order_idx": 1300, "default_on": True,  "modes": ["ocean","continue"]},
    {"id": "hydrothermal-vents",     "order_idx": 1400, "default_on": True,  "modes": ["ocean","continue"]},
    {"id": "oceansites",             "order_idx": 1500, "default_on": True,  "modes": ["ocean","continue"]},
    {"id": "onc",                    "order_idx": 1600, "default_on": True,  "modes": ["ocean","continue"]},
    {"id": "chess",                  "order_idx": 1700, "default_on": True,  "modes": ["ocean","continue"]},
    {"id": "deepdata-stations",      "order_idx": 1750, "default_on": False, "modes": ["ocean","continue"]},
    {"id": "submarine-cables",       "order_idx": 1800, "default_on": False, "modes": ["ocean","continue"]},
    {"id": "onc-instruments",        "order_idx": 1900, "default_on": True,  "modes": ["ocean","continue"]},
    {"id": "ports",                  "order_idx": 2000, "default_on": False, "modes": ["ocean","continue"]},
    {"id": "ocean-currents",         "order_idx": 2050, "default_on": False, "modes": ["ocean","continue"]},
    {"id": "geotraces",              "order_idx": 2074, "default_on": False, "modes": ["ocean","continue"]},
    {"id": "woa-climatology",        "order_idx": 2075, "default_on": False, "modes": ["ocean","continue"]},
    {"id": "oxygen-deox",            "order_idx": 2076, "default_on": False, "modes": ["ocean","continue"]},
    {"id": "wod-oxygen",             "order_idx": 2077, "default_on": False, "modes": ["ocean","continue"]},
    {"id": "memento",                "order_idx": 2078, "default_on": False, "modes": ["ocean","continue"]},
    {"id": "ocean-carbon",           "order_idx": 2081, "default_on": False, "modes": ["ocean","continue"]},
    {"id": "ocean-co2-surface",      "order_idx": 2082, "default_on": False, "modes": ["ocean","continue"]},
    {"id": "marine-carbon",          "order_idx": 70,   "default_on": False, "modes": ["ocean","continue"]},
    {"id": "surface-water",          "order_idx": 2100, "default_on": False, "modes": ["land"]},
    {"id": "forest-loss",            "order_idx": 2200, "default_on": False, "modes": ["land"]},
    {"id": "carbon-flux",            "order_idx": 2300, "default_on": False, "modes": ["land"]},
    {"id": "soil-carbon",            "order_idx": 2400, "default_on": False, "modes": ["land"]},
    {"id": "water-risk",             "order_idx": 2500, "default_on": False, "modes": ["land"]},
    {"id": "mining-footprints",      "order_idx": 2600, "default_on": True,  "modes": ["land"]},
    {"id": "tailings",               "order_idx": 2900, "default_on": False, "modes": ["land"]},
    {"id": "fires",                  "order_idx": 3000, "default_on": True,  "modes": ["land"]},
    {"id": "air-quality",            "order_idx": 3100, "default_on": True,  "modes": ["land"]},
    {"id": "landslides",             "order_idx": 3200, "default_on": False, "modes": ["land"]},
    {"id": "dams",                   "order_idx": 3300, "default_on": False, "modes": ["land"]},
    {"id": "arctic-rivers",          "order_idx": 2079, "default_on": False, "modes": ["ocean","continue"]},
    {"id": "methane-seeps",          "order_idx": 2080, "default_on": False, "modes": ["ocean","continue"]},
    {"id": "permafrost-thaw",        "order_idx": 2086, "default_on": False, "modes": ["ocean","continue"]},
    {"id": "sios-svalbard",          "order_idx": 2083, "default_on": False, "modes": ["ocean","continue"]},
    {"id": "arctic-catchments",      "order_idx": 2084, "default_on": False, "modes": ["ocean","continue"]},
    {"id": "seabed-substrate",       "order_idx": 70,   "default_on": False, "modes": ["ocean","continue"]},
    {"id": "arctic-sediment-carbon", "order_idx": 2085, "default_on": False, "modes": ["ocean","continue"]},
    {"id": "mosaic-sediment", "order_idx": 2088, "default_on": False, "modes": ["ocean","continue"]},
    {"id": "vme-suitability",        "order_idx": 68,   "default_on": False, "modes": ["ocean","continue"]},
    {"id": "ocean-acidification",    "order_idx": 69,   "default_on": False, "modes": ["ocean","continue"]},
    {"id": "coral-acid-exposure",    "order_idx": 71,   "default_on": False, "modes": ["ocean","continue"]},
    {"id": "cumulative-human-impact","order_idx": 72,   "default_on": False, "modes": ["ocean","continue"]},
    {"id": "ais-live",               "order_idx": 3400, "default_on": False, "modes": ["ocean","continue"]},
    {"id": "vessel-events",          "order_idx": 3500, "default_on": False, "modes": ["ocean","continue"]},
]


# Layers withdrawn from the platform. The ROWS stay in the database — only the
# serving stops — but `layer_config` must stop advertising them.
#
# ⛔ This is deliberately code, not a hand-run UPDATE on production. The seed
# below is `ON CONFLICT (id) DO NOTHING`, so an existing row keeps whatever
# status it already has: a `wdpa` row seeded before the withdrawal would sit at
# status='enabled' forever, and `/v1/map/layer-config` (WHERE status='enabled')
# would keep serving it. A hand-run UPDATE would fix exactly one database and
# nothing else — not a fresh deploy, not a restored backup, not a dev instance.
# Retiring in code fixes every environment the code reaches, every restart.
#
# `status` already carries 'retired' in the CHECK constraint below, and the
# admin panel's own UPDATE cannot resurrect these: the retirement reapplies on
# the next boot.
WITHDRAWN_LAYER_IDS: tuple[str, ...] = (
    # WDPA, 2026-09-03. Protected Planet's terms forbid redistribution "through
    # interactive web maps ... that grant users download access" without prior
    # written permission from UNEP-WCMC (protectedareas@unep-wcmc.org).
    "wdpa",
    # KBA, 2026-09-03. BirdLife's KBA terms carry the same clause — redistribution
    # "through interactive web maps ... that grant users download access" is
    # prohibited without written permission from the KBA Secretariat, plus a
    # separate no-commercial-use clause. Verified against
    # keybiodiversityareas.org/termsofservice on 2026-09-03.
    "kbas",
)


async def ensure_layer_config_seed() -> None:
    async with db.pool.acquire() as conn:
        await conn.execute(LAYER_CONFIG_DDL)
        # --- status lifecycle column (idempotent; ON CONFLICT seed below never overwrites it,
        #     so a 'retired' layer survives every restart/redeploy) ---
        await conn.execute(
            "ALTER TABLE layer_config "
            "ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'enabled'"
        )
        await conn.execute(
            """DO $$ BEGIN
                 IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'layer_config_status_chk') THEN
                   ALTER TABLE layer_config
                     ADD CONSTRAINT layer_config_status_chk
                     CHECK (status IN ('enabled','disabled','retired'));
                 END IF;
               END $$;"""
        )
        await conn.executemany(
            """INSERT INTO layer_config (id, order_idx, default_on, modes)
               VALUES ($1, $2, $3, $4)
               ON CONFLICT (id) DO NOTHING""",
            [(e["id"], e["order_idx"], e["default_on"], e["modes"]) for e in LAYER_DEFAULTS_PY],
        )
        # Retire withdrawn layers. Idempotent: the WHERE clause makes a re-run a
        # no-op, so this costs nothing on the 99% of boots where it changes
        # nothing, and it self-heals a row someone re-enabled by hand.
        if WITHDRAWN_LAYER_IDS:
            retired = await conn.fetch(
                "UPDATE layer_config SET status = 'retired', updated_at = now(), "
                "updated_by = 'withdrawal (code)' "
                "WHERE id = ANY($1::text[]) AND status <> 'retired' RETURNING id",
                list(WITHDRAWN_LAYER_IDS),
            )
            if retired:
                log.warning(
                    "layer_config: retired withdrawn layer(s) %s",
                    ", ".join(r["id"] for r in retired),
                )
    log.info("layer_config: table ready (%d default rows available)", len(LAYER_DEFAULTS_PY))


_ARCTIC_RIVERS_ORDER_IDX = next(
    e["order_idx"] for e in LAYER_DEFAULTS_PY if e["id"] == "arctic-rivers"
)


async def ensure_arctic_rivers_order_idx_fix() -> None:
    """One-time correction for a stale `layer_config` row.

    `arctic-rivers` was a LAND layer until a 2026-09 commit moved it into
    Ocean and dropped `order_idx` from 3400 down to what LAYER_DEFAULTS_PY
    now carries.
    The seed above is `ON CONFLICT (id) DO NOTHING`, so any database whose
    row predates that commit never picked up the new value — production is
    still serving `order_idx=3400`, drawing the layer above everything else
    as if it were still land.

    ⛔ A hand-run UPDATE would fix exactly one database and nothing else — not
    a fresh deploy, not a restored backup, not a dev instance. This step fixes
    every environment the code reaches, every restart (same reasoning as
    WITHDRAWN_LAYER_IDS above).

    Guarded on the OLD value (`order_idx = 3400`) so this can never clobber a
    deliberate admin edit made afterwards via `PATCH /layers/{id}`
    (`routers/admin_layers_api.py`) — once the row reads anything other than
    3400, this step is a permanent, idempotent no-op.
    """
    async with db.pool.acquire() as conn:
        fixed = await conn.fetchval(
            """UPDATE layer_config
                  SET order_idx  = $1,
                      updated_at = now(),
                      updated_by = 'schema-step (arctic-rivers order_idx fix)'
                WHERE id = 'arctic-rivers' AND order_idx = 3400
                RETURNING id""",
            _ARCTIC_RIVERS_ORDER_IDX,
        )
        if fixed:
            log.warning(
                "layer_config: corrected stale arctic-rivers order_idx 3400 -> %d",
                _ARCTIC_RIVERS_ORDER_IDX,
            )


async def ensure_startup_profiles_seed() -> None:
    """Create startup_profiles + seed defaults. ON CONFLICT DO NOTHING so operator
    edits and disabled profiles are never overwritten on restart."""
    import profiles as _profiles
    async with db.pool.acquire() as conn:
        await conn.execute(_profiles.STARTUP_PROFILES_DDL)
        await conn.execute(
            "ALTER TABLE startup_profiles "
            "ADD COLUMN IF NOT EXISTS views JSONB NOT NULL DEFAULT '{}'::jsonb")
        await conn.executemany(
            """INSERT INTO startup_profiles
                 (id, section, order_idx, status, layers, label, description, accent)
               VALUES ($1,$2,$3,'enabled',$4,$5,$6,$7)
               ON CONFLICT (id) DO NOTHING""",
            [(p["id"], p["section"], p["order_idx"], p["layers"],
              json.dumps(p["label"]), json.dumps(p["description"]), p.get("accent"))
             for p in _profiles.PROFILE_SEED],
        )
    log.info("startup_profiles seed ready")
