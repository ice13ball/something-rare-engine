// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

/** Every land layer id, as a VALUE — the type is derived from it.
  * Same reasoning as SEA_LAYER_IDS in ./layers.ts. */
export const LAND_LAYER_IDS = [
  "mining-footprints", "forest-loss", "tailings", "fires", "air-quality", "landslides",
  "surface-water", "dams", "arctic-rivers", "carbon-flux", "soil-carbon", "water-risk",
  "permafrost-thaw",
] as const;

export type LandLayerId = (typeof LAND_LAYER_IDS)[number];

export interface LandLayerConfig {
  id: LandLayerId;
  label: string;
  color: string;
  fillRgba: [number, number, number, number];
  lineRgba: [number, number, number, number];
  description: string;
  phase: 1 | 2 | 3;
}

export const LAND_LAYER_CONFIGS: LandLayerConfig[] = [
  // Phase 1 — Core Conflict Map
  {
    id: "mining-footprints",
    label: "Global Mining Footprints",
    color: "#dc267f",
    fillRgba: [220, 38, 127, 140],
    lineRgba: [255, 255, 255, 200],
    description: "74,548 mine polygons (pits, tailings, waste dumps, processing sites) from Sentinel-2 at 10m — Maus et al. 2022/2023",
    phase: 1,
  },
  {
    id: "forest-loss",
    label: "Tree Cover Loss",
    color: "#f59e0b",
    fillRgba: [245, 158, 11, 150],
    lineRgba: [245, 158, 11, 255],
    description: "Annual deforestation at 30m resolution, umd_tree_cover_loss v1.13 — University of Maryland / WRI",
    phase: 1,
  },
  // Phase 2 — Environmental Hazards & Industrial Risk
  {
    id: "tailings",
    label: "Tailings Dams",
    color: "#dc2626",
    fillRgba: [220, 38, 38, 200],
    lineRgba: [220, 38, 38, 255],
    description: "11,587 mine tailings dam locations — WAPHA (Hudson-Edwards et al. 2023). Global Tailings Portal hazard-rating fields withdrawn pending permission.",
    phase: 2,
  },
  {
    id: "fires",
    label: "Active Fires (FIRMS)",
    color: "#ff6b00",
    fillRgba: [255, 107, 0, 200],
    lineRgba: [255, 107, 0, 255],
    description: "Near-real-time fire detection from NASA's three VIIRS satellites — NASA LANCE, updated within 3 hours",
    phase: 2,
  },
  {
    id: "air-quality",
    label: "Air Quality Stations",
    color: "#7c9bb5",
    fillRgba: [124, 155, 181, 200],
    lineRgba: [124, 155, 181, 255],
    description: "Real-time PM2.5, SO₂, NO₂, O₃, CO from government stations worldwide — OpenAQ",
    phase: 2,
  },
  {
    id: "landslides",
    label: "Landslide Catalog",
    color: "#92400e",
    fillRgba: [146, 64, 14, 200],
    lineRgba: [146, 64, 14, 255],
    description: "Rainfall-triggered landslides since 2007 — NASA COOLR / Goddard Space Flight Center",
    phase: 2,
  },
  // Phase 3 — Deeper Environmental Context
  {
    id: "surface-water",
    label: "Global Surface Water",
    color: "#06b6d4",
    fillRgba: [6, 182, 212, 150],
    lineRgba: [6, 182, 212, 255],
    description: "Surface water occurrence and change 1984–2021 at 30m — JRC / European Commission",
    phase: 3,
  },
  {
    id: "dams",
    label: "Global Dams",
    color: "#5e8ab4",
    fillRgba: [94, 138, 180, 200],
    lineRgba: [94, 138, 180, 255],
    description: "41,145 river barriers from GDW v1.0 (2024) — GOODD and GRanD merged; a quarter carry a name",
    phase: 3,
  },
  {
    id: "arctic-rivers",
    label: "Arctic River Inputs",
    color: "#38bdf8",
    fillRgba: [56, 189, 248, 200],
    lineRgba: [56, 189, 248, 255],
    description: "River discharge + biogeochemistry (carbon, nutrients) at the great Arctic river mouths — ArcticGRO + PANGAEA",
    phase: 3,
  },
  {
    id: "permafrost-thaw",
    label: "Permafrost Thaw",
    color: "#38bdf8",
    fillRgba: [56, 189, 248, 200],
    lineRgba: [255, 255, 255, 180],
    description: "Observed permafrost thaw features across Alaska (thermokarst lakes, thaw slumps, active-layer detachments) — Webb et al. 2026",
    phase: 3,
  },
  {
    id: "carbon-flux",
    label: "Forest Carbon Flux",
    color: "#065f46",
    fillRgba: [6, 95, 70, 150],
    lineRgba: [6, 95, 70, 255],
    description: "CO₂ emissions and removals per hectare at 30m (2001–2025) — WRI / Global Forest Watch",
    phase: 3,
  },
  {
    id: "soil-carbon",
    label: "Soil Organic Carbon",
    color: "#78350f",
    fillRgba: [120, 53, 15, 150],
    lineRgba: [120, 53, 15, 255],
    description: "Global soil organic carbon, top 0–5 cm at ~250 m — ISRIC SoilGrids",
    phase: 3,
  },
  {
    id: "water-risk",
    label: "Water Risk (Aqueduct)",
    color: "#0ea5e9",
    fillRgba: [14, 165, 233, 80],
    lineRgba: [14, 165, 233, 200],
    description: "Global water risk at sub-basin level — stress, depletion, drought, flood — WRI Aqueduct 4.0 (mining-weighted)",
    phase: 3,
  },
];

export const LAND_LAYERS_OFF_BY_DEFAULT = new Set<LandLayerId>(
  LAND_LAYER_CONFIGS.map(l => l.id)
);

/**
 * Tailings dam hazard rating — `hazard_raw` is the operator's own rating
 * string, verbatim, from the Global Tailings Portal (120 distinct values
 * live on production). This platform runs no scoring of its own (the former
 * `risk_class` six-tier collapse was deleted 2026-09-22) — these are the six
 * values the filter UI and the map's categorical colors key off of, plus an
 * "other" bucket (added at the call site) for the other 114 distinct values.
 *
 * ⛔ Order is the source's own frequency (Low 507, High 419, Significant 296,
 * Medium 124, Very High 112, Extreme 102), NOT a severity ranking — do not
 * re-sort this into Low..Extreme or Extreme..Low.
 */
export const TAILINGS_HAZARD_VALUES = ["Low", "High", "Significant", "Medium", "Very High", "Extreme"] as const;
export type TailingsHazardValue = (typeof TAILINGS_HAZARD_VALUES)[number];
