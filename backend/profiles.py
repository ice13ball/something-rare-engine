# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Startup profiles — curated layer sets for the two-tier welcome screen.

Pure module: DDL constant, the authoritative menu-layer-id set, the seed
profiles, and a validator. No DB access here (see main.py + admin router).

KEEP-IN-SYNC: KNOWN_LAYER_IDS mirrors the frontend menu taxonomy in
frontend/src/utils/menuTaxonomy.ts (LAYER_TO_SUBGROUP keys). Same dual-maintenance
discipline as LAYER_DEFAULTS_PY / LAYER_DEFAULTS.
"""
from __future__ import annotations
import re

STARTUP_PROFILES_DDL = """
CREATE TABLE IF NOT EXISTS startup_profiles (
    id          TEXT PRIMARY KEY,
    section     TEXT NOT NULL DEFAULT 'ocean',
    order_idx   INT  NOT NULL DEFAULT 100,
    status      TEXT NOT NULL DEFAULT 'enabled',
    layers      TEXT[] NOT NULL DEFAULT '{}',
    label       JSONB NOT NULL DEFAULT '{}'::jsonb,
    description JSONB NOT NULL DEFAULT '{}'::jsonb,
    views       JSONB NOT NULL DEFAULT '{}'::jsonb,
    accent      TEXT,
    updated_at  TIMESTAMPTZ DEFAULT now(),
    updated_by  TEXT
);
ALTER TABLE startup_profiles OWNER TO abyssal_user;
"""

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

# The full set of menu toggle-ids a profile may reference.
KNOWN_LAYER_IDS: frozenset[str] = frozenset({
    # sea_claims
    "contracts", "reserved-areas", "relinquished-areas", "apeis",
    "protected-marine-sites", "eez", "offshore-activities",
    # sea_life
    "biodiversity-hotspots", "hydrothermal-vents", "chess", "seamounts",
    "tectonic-plates", "bathymetry",
    # sea_analysis
    "monitoring-density", "deepdata-stations", "marine-carbon",
    "vme-suitability", "ocean-acidification", "coral-acid-exposure",
    "cumulative-human-impact",
    # sea_sensors
    "argo", "oceansites", "onc", "onc-instruments", "hydrophone-stations",
    "ocean-currents",
    # sea_woa
    "woa-climatology", "ocean-carbon", "ocean-co2-surface", "wod-oxygen",
    "memento", "geotraces", "mosaic-sediment", "methane-seeps", "oxygen-deox",
    "arctic-rivers", "arctic-catchments", "arctic-sediment-carbon",
    "permafrost-thaw", "sios-svalbard", "seabed-substrate",
    # sea_infra
    "submarine-cables", "ports",
    # sea_vessels
    "noise-risk", "ais-live", "vessel-events",
    # land
    "mining-footprints", "forest-loss",
    "tailings", "fires", "air-quality", "landslides",
    "surface-water", "dams", "carbon-flux", "soil-carbon", "water-risk",
})


def validate_profile(row: dict, known_ids: frozenset[str]) -> None:
    """Raise ValueError if the profile row is invalid."""
    slug = row.get("id") or ""
    if not SLUG_RE.match(slug):
        raise ValueError(f"invalid slug {slug!r}: use lowercase letters, digits, hyphens")
    if row.get("section") not in ("ocean", "land"):
        raise ValueError(f"section must be 'ocean' or 'land', got {row.get('section')!r}")
    layers = row.get("layers") or []
    if not layers:
        raise ValueError("profile must reference at least one layer")
    for lid in layers:
        if lid not in known_ids:
            raise ValueError(f"unknown layer {lid!r}")
    label = row.get("label") or {}
    if not label.get("en"):
        raise ValueError("profile must have an en label")


def sanitize_views(views, layers) -> dict:
    """Keep only view-overrides whose layer is in the profile; drop non-dict values.
    Field values are NOT validated here (the frontend layerViews registry is authoritative)."""
    if not isinstance(views, dict):
        return {}
    layerset = set(layers or [])
    out = {}
    for lid, fields in views.items():
        if lid in layerset and isinstance(fields, dict):
            out[lid] = fields
    return out


def _p(id, section, order, layers, en_label, en_desc):
    return {"id": id, "section": section, "order_idx": order, "layers": layers,
            "label": {"en": en_label}, "description": {"en": en_desc}, "accent": None}


PROFILE_SEED: list[dict] = [
    _p("seabed-mining", "ocean", 10,
       ["contracts", "reserved-areas", "relinquished-areas", "apeis",
        "offshore-activities", "protected-marine-sites", "cumulative-human-impact"],
       "Seabed Mining & Claims",
       "ISA exploration contracts, reserved and relinquished areas, APEIs and offshore "
       "activity — over the cumulative human-impact field for context (claims sit in "
       "low-impact abyssal zones)."),
    _p("deep-sea-life", "ocean", 20,
       ["biodiversity-hotspots", "hydrothermal-vents", "chess", "seamounts",
        "vme-suitability", "deepdata-stations"],
       "Life & Deep-Sea Habitats",
       "Biodiversity hotspots, vents, seamounts and modelled vulnerable-marine-ecosystem suitability."),
    _p("carbon-acidification", "ocean", 30,
       ["marine-carbon", "ocean-carbon", "ocean-co2-surface", "ocean-acidification",
        "coral-acid-exposure", "geotraces"],
       "Carbon & Acidification",
       "Interior and surface ocean carbon, acidification and coral exposure fields."),
    _p("arctic-land-ocean", "ocean", 40,
       ["arctic-rivers", "arctic-catchments", "arctic-sediment-carbon",
        "permafrost-thaw", "sios-svalbard", "methane-seeps"],
       "Arctic Land→Ocean",
       "Arctic river inputs, catchments, seafloor sediment carbon, permafrost thaw and Svalbard observing."),
    _p("ocean-sensors", "ocean", 50,
       ["argo", "oceansites", "onc", "onc-instruments", "ocean-currents", "wod-oxygen"],
       "Ocean Sensors & Currents",
       "Argo floats, OceanSITES and ONC observatories, currents and historical oxygen casts."),
    _p("land-mining", "land", 60,
       # ⛔ "kbas" removed 2026-09-03. BirdLife's KBA terms forbid redistribution
       # "through interactive web maps that grant users download access" — the
       # same clause that forced the WDPA withdrawal. The layer is retired in
       # layer_config; a preset that still LISTED it would keep advertising a
       # layer we no longer serve, and the description below promised it by name.
       ["mining-footprints", "tailings", "fires", "forest-loss", "water-risk"],
       "Land Mining Impacts",
       "Mining footprints, tailings dams, fires, forest loss and water risk."),
    _p("infrastructure", "ocean", 70,
       ["submarine-cables", "ports", "noise-risk"],
       "Infrastructure & Noise",
       "Submarine cables, ports and modelled underwater-noise risk."),
    _p("vessel-surveillance", "ocean", 80,
       ["ais-live", "vessel-events"],
       "Vessel Surveillance",
       "Live AIS positions and SAR×AIS dark-vessel detection in coastal waters. "
       "Free-tier AIS is nearshore only — open-ocean ISA leases are out of AIS scope."),
]
