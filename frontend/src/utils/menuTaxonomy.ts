// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// frontend/src/utils/menuTaxonomy.ts
// Maps each menu toggle-id to its left-menu sub-group storageKey, and derives
// which categories a set of active layers should expand.
//
// KEEP IN SYNC with backend/profiles.py KNOWN_LAYER_IDS and the <SubGroup>
// storageKeys in Map3DControls.tsx.

export const LAYER_TO_SUBGROUP: Record<string, string> = {
  // sea_claims
  "contracts": "sea_claims", "reserved-areas": "sea_claims",
  "relinquished-areas": "sea_claims", "apeis": "sea_claims",
  "protected-marine-sites": "sea_claims", "eez": "sea_claims",
  "offshore-activities": "sea_claims",
  // sea_life
  "biodiversity-hotspots": "sea_life", "hydrothermal-vents": "sea_life",
  "chess": "sea_life", "seamounts": "sea_life", "tectonic-plates": "sea_life",
  "bathymetry": "sea_life",
  // sea_analysis
  "monitoring-density": "sea_analysis", "deepdata-stations": "sea_analysis",
  "marine-carbon": "sea_analysis", "vme-suitability": "sea_analysis",
  "ocean-acidification": "sea_analysis", "coral-acid-exposure": "sea_analysis",
  "cumulative-human-impact": "sea_analysis",
  // sea_sensors
  "argo": "sea_sensors", "oceansites": "sea_sensors", "onc": "sea_sensors",
  "onc-instruments": "sea_sensors", "hydrophone-stations": "sea_sensors",
  "ocean-currents": "sea_sensors",
  // sea_woa
  "woa-climatology": "sea_woa", "ocean-carbon": "sea_woa",
  "ocean-co2-surface": "sea_woa", "wod-oxygen": "sea_woa", "memento": "sea_woa",
  "geotraces": "sea_woa", "mosaic-sediment": "sea_woa", "methane-seeps": "sea_woa",
  "oxygen-deox": "sea_woa", "arctic-rivers": "sea_woa",
  "arctic-catchments": "sea_woa", "arctic-sediment-carbon": "sea_woa",
  "permafrost-thaw": "sea_woa", "sios-svalbard": "sea_woa",
  "seabed-substrate": "sea_woa",
  // sea_infra
  "submarine-cables": "sea_infra", "ports": "sea_infra",
  // sea_vessels
  "noise-risk": "sea_vessels", "ais-live": "sea_vessels", "vessel-events": "sea_vessels",
  // land
  "mining-footprints": "land_core",
  "forest-loss": "land_core",
  "tailings": "land_hazards", "fires": "land_hazards", "air-quality": "land_hazards",
  "landslides": "land_hazards",
  "surface-water": "land_water", "dams": "land_water", "carbon-flux": "land_water",
  "soil-carbon": "land_water", "water-risk": "land_water",
};

export const SUBGROUP_KEYS: string[] = [
  "sea_claims", "sea_life", "sea_analysis", "sea_sensors", "sea_woa",
  "sea_infra", "sea_vessels", "land_core", "land_hazards", "land_water",
];

export function deriveExpansion(
  activeIds: Iterable<string>,
): { expand: string[]; seaOpen: boolean; landOpen: boolean } {
  const expand = new Set<string>();
  for (const id of activeIds) {
    const key = LAYER_TO_SUBGROUP[id];
    if (key) expand.add(key);
  }
  const list = [...expand];
  return {
    expand: list,
    seaOpen: list.some((k) => k.startsWith("sea_")),
    landOpen: list.some((k) => k.startsWith("land_")),
  };
}
