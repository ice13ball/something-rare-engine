// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useState, useEffect } from "react";

export interface LayerConfig {
  id: string;
  order_idx: number;
  default_on: boolean;
  modes: string[];
}

// Mirrors backend/main.py LAYER_DEFAULTS_PY — one-time DB seed + runtime fallback.
// KEEP IN SYNC WITH backend/main.py LAYER_DEFAULTS_PY.
export const LAYER_DEFAULTS: LayerConfig[] = [
  // Bathymetry MUST stay at the lowest order_idx so it always renders behind
  // everything else (concessions, vents, Argo, etc.). Layers missing from this
  // list fall back to 9999 and end up on top — which would hide concessions
  // under the GEBCO shaded relief. Don't reassign without testing every layer.
  { id: "bathymetry",             order_idx: 50,   default_on: false, modes: ["ocean","continue"] },
  { id: "tectonic-plates",        order_idx: 100,  default_on: false, modes: ["ocean","continue"] },
  { id: "offshore-activities",    order_idx: 200,  default_on: false, modes: ["ocean","continue"] },
  { id: "relinquished-areas",     order_idx: 300,  default_on: true,  modes: ["ocean","continue"] },
  { id: "reserved-areas",         order_idx: 400,  default_on: true,  modes: ["ocean","continue"] },
  { id: "apeis",                  order_idx: 500,  default_on: true,  modes: ["ocean","continue"] },
  { id: "eez",                    order_idx: 600,  default_on: false, modes: ["ocean","continue"] },
  { id: "protected-marine-sites", order_idx: 700,  default_on: true,  modes: ["ocean","continue"] },
  { id: "contracts",              order_idx: 800,  default_on: true,  modes: ["ocean","continue"] },
  { id: "seamounts",              order_idx: 900,  default_on: false, modes: ["ocean","continue"] },
  { id: "biodiversity-hotspots",  order_idx: 1000, default_on: true,  modes: ["ocean","continue"] },
  { id: "monitoring-density",     order_idx: 1100, default_on: false, modes: ["ocean","continue"] },
  { id: "noise-risk",             order_idx: 1200, default_on: false, modes: ["ocean","continue"] },
  { id: "argo",                   order_idx: 1300, default_on: true,  modes: ["ocean","continue"] },
  { id: "hydrothermal-vents",     order_idx: 1400, default_on: true,  modes: ["ocean","continue"] },
  { id: "oceansites",             order_idx: 1500, default_on: true,  modes: ["ocean","continue"] },
  { id: "onc",                    order_idx: 1600, default_on: true,  modes: ["ocean","continue"] },
  { id: "chess",                  order_idx: 1700, default_on: true,  modes: ["ocean","continue"] },
  { id: "submarine-cables",       order_idx: 1800, default_on: false, modes: ["ocean","continue"] },
  { id: "onc-instruments",        order_idx: 1900, default_on: true,  modes: ["ocean","continue"] },
  { id: "ports",                  order_idx: 2000, default_on: false, modes: ["ocean","continue"] },
  { id: "ocean-currents",         order_idx: 2050, default_on: false, modes: ["ocean","continue"] },
  { id: "woa-climatology",        order_idx: 2075, default_on: false, modes: ["ocean","continue"] },
  { id: "oxygen-deox",            order_idx: 2076, default_on: false, modes: ["ocean","continue"] },
  { id: "wod-oxygen",             order_idx: 2077, default_on: false, modes: ["ocean","continue"] },
  { id: "geotraces",             order_idx: 2074, default_on: false, modes: ["ocean","continue"] },
  { id: "memento",               order_idx: 2079, default_on: false, modes: ["ocean","continue"] },
  { id: "surface-water",          order_idx: 2100, default_on: false, modes: ["land"] },
  { id: "forest-loss",            order_idx: 2200, default_on: false, modes: ["land"] },
  { id: "carbon-flux",            order_idx: 2300, default_on: false, modes: ["land"] },
  { id: "soil-carbon",            order_idx: 2400, default_on: false, modes: ["land"] },
  { id: "water-risk",             order_idx: 2500, default_on: false, modes: ["land"] },
  { id: "mining-footprints",      order_idx: 2600, default_on: true,  modes: ["land"] },
  { id: "tailings",               order_idx: 2900, default_on: false, modes: ["land"] },
  { id: "fires",                  order_idx: 3000, default_on: true,  modes: ["land"] },
  { id: "air-quality",            order_idx: 3100, default_on: true,  modes: ["land"] },
  { id: "landslides",             order_idx: 3200, default_on: false, modes: ["land"] },
  { id: "dams",                   order_idx: 3300, default_on: false, modes: ["land"] },
  { id: "ais-live",               order_idx: 3400, default_on: false, modes: ["ocean","continue"] },
  { id: "vessel-events",          order_idx: 3500, default_on: false, modes: ["ocean","continue"] },
  { id: "arctic-rivers",          order_idx: 2078, default_on: false, modes: ["ocean","continue"] },
  { id: "methane-seeps",          order_idx: 2080, default_on: false, modes: ["ocean","continue"] },
  { id: "ocean-carbon",           order_idx: 2081, default_on: false, modes: ["ocean","continue"] },
  { id: "ocean-co2-surface",      order_idx: 2082, default_on: false, modes: ["ocean","continue"] },
  { id: "marine-carbon",          order_idx: 70,   default_on: false, modes: ["ocean","continue"] },
  { id: "sios-svalbard",          order_idx: 2083, default_on: false, modes: ["ocean","continue"] },
  { id: "arctic-catchments",      order_idx: 2084, default_on: false, modes: ["ocean","continue"] },
  { id: "seabed-substrate",       order_idx: 70,   default_on: false, modes: ["ocean","continue"] },
  { id: "arctic-sediment-carbon", order_idx: 2085, default_on: false, modes: ["ocean","continue"] },
  { id: "permafrost-thaw",        order_idx: 2086, default_on: false, modes: ["ocean","continue"] },
  { id: "mosaic-sediment",        order_idx: 2088, default_on: false, modes: ["ocean","continue"] },
  { id: "vme-suitability",        order_idx: 68,   default_on: false, modes: ["ocean","continue"] },
  { id: "ocean-acidification",    order_idx: 69,   default_on: false, modes: ["ocean","continue"] },
  { id: "coral-acid-exposure",    order_idx: 71,   default_on: false, modes: ["ocean","continue"] },
  { id: "cumulative-human-impact", order_idx: 72,  default_on: false, modes: ["ocean","continue"] },
];

// Maps deck.gl layer `.id` to toggle group id for ordering in Map3D.tsx.
// Only entries that differ from the toggle id are listed; others pass through as-is.
export const DECK_TO_TOGGLE: Record<string, string> = {
  "tectonic-plates-fill":           "tectonic-plates",
  "tectonic-plates-boundaries":     "tectonic-plates",
  "offshore-zones-mvt":             "offshore-activities",
  "offshore-activities-mvt":        "offshore-activities",
  "mining-contracts-mvt":           "contracts",
  "marine-carbon-hexes":            "marine-carbon",
  // Hex aggregations of layers that also draw individual stations. Without
  // these two, clicking a GEOTRACES station showed its layer's time frame and
  // clicking a GEOTRACES hex of the same layer showed nothing.
  "geotraces-hexes":                "geotraces",
  "memento-hexes":                  "memento",
  "vme-suitability-hexes":          "vme-suitability",
  "ocean-acidification-raster":     "ocean-acidification",
  "ocean-acidification-hexes":      "ocean-acidification",
  "coral-acid-exposure-hexes":      "coral-acid-exposure",
  "cumulative-human-impact-raster": "cumulative-human-impact",
  "cumulative-human-impact-hexes":  "cumulative-human-impact",
  "biodiversity-hotspots-glow":     "biodiversity-hotspots",
  "argo-glow":                      "argo",
  "argo-floats-3d":                 "argo",
  "hydrothermal-vents-active-glow": "hydrothermal-vents",
  "hydrothermal-vents-active":      "hydrothermal-vents",
  "hydrothermal-vents-inactive":    "hydrothermal-vents",
  "onc-glow":                       "onc",
  "onc-cables":                     "submarine-cables",
  "ooi-cables":                     "submarine-cables",
  "noaa-cables":                    "submarine-cables",
  "nz-cables":                      "submarine-cables",
  "au-cables":                      "submarine-cables",
  "water-risk-mvt":                 "water-risk",
  "arctic-catchments-mvt":          "arctic-catchments",
  "seabed-substrate-raster":        "seabed-substrate",
  "seabed-substrate-hexes":         "seabed-substrate",
  "arctic-sediment-carbon-raster":   "arctic-sediment-carbon",
  "arctic-sediment-carbon-stations": "arctic-sediment-carbon",
  "mosaic-hexes":                   "mosaic-sediment",
};

const LS_KEY = "abyssal_layer_config";
const LS_TTL_MS = 60 * 1000; // visibility must be fresh — a disabled layer disappears within ~1 min

/** Merge LAYER_DEFAULTS into API response so any layer added to the frontend
 * before the backend's layer_config table is updated still gets its order_idx
 * (otherwise sorting falls back to 9999 → renders on top of everything). */
function mergeDefaults(apiData: LayerConfig[]): LayerConfig[] {
  const present = new Set(apiData.map(d => d.id));
  const missing = LAYER_DEFAULTS.filter(d => !present.has(d.id));
  return [...apiData, ...missing];
}

/** The enabled-layer id set from a successful API response (which returns only
 *  status='enabled' rows). null means "unknown / fetch failed" → callers allow all. */
export function deriveEnabledIds(apiData: LayerConfig[] | null): Set<string> | null {
  return apiData ? new Set(apiData.map(d => d.id)) : null;
}

export async function fetchLayerConfig(): Promise<{ config: LayerConfig[]; enabledIds: Set<string> | null }> {
  // 1. localStorage cache (short TTL) — cached payload is the enabled-only API data.
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (raw) {
      const { ts, data } = JSON.parse(raw) as { ts: number; data: LayerConfig[] };
      if (Date.now() - ts < LS_TTL_MS) {
        return { config: mergeDefaults(data), enabledIds: deriveEnabledIds(data) };
      }
    }
  } catch {}

  // 2. API (5s timeout)
  try {
    const ctrl = new AbortController();
    const tid = setTimeout(() => ctrl.abort(), 5000);
    const res = await fetch("/api/v1/map/layer-config", { signal: ctrl.signal });
    clearTimeout(tid);
    if (res.ok) {
      const data: LayerConfig[] = await res.json();
      try { localStorage.setItem(LS_KEY, JSON.stringify({ ts: Date.now(), data })); } catch {}
      return { config: mergeDefaults(data), enabledIds: deriveEnabledIds(data) };
    }
  } catch {}

  // 3. Hardcoded fallback — allow-all (enabledIds null) so a backend outage NEVER blanks the map.
  console.warn("[layerConfig] using hardcoded LAYER_DEFAULTS fallback (allow-all)");
  return { config: LAYER_DEFAULTS, enabledIds: null };
}

export function useLayerConfig(): [LayerConfig[], boolean, Set<string> | null] {
  const [config, setConfig] = useState<LayerConfig[]>(LAYER_DEFAULTS);
  const [enabledIds, setEnabledIds] = useState<Set<string> | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    fetchLayerConfig().then(({ config, enabledIds }) => {
      setConfig(config);
      setEnabledIds(enabledIds);
      setLoaded(true);
    });
  }, []);

  return [config, loaded, enabledIds];
}
