// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

/**
 * Shapes served by `/api/v1/bgc-model/*` (layer `ocean-nutrients-model`):
 * surface nitrate, chlorophyll-a, volumetric net primary production and N*
 * from the Copernicus Marine global biogeochemical model, monthly means.
 * ⛔ Model output, not measurements.
 */

export interface BgcModelRampStop { pos: number; hex: string }
export interface BgcModelTick { value: number; pos: number }

export interface BgcModelVariable {
  key: string;
  label: string;
  unit: string;
  /** Name of the unit-carrying field in the /point response, e.g. `no3_mmol_m3`. */
  field: string;
  scale: "linear" | "log" | "sqrt";
  vmin: number;
  vmax: number;
  ramp: BgcModelRampStop[];
  ticks: BgcModelTick[];
  note: string;
  stats: { p1?: number; p50?: number; p99?: number; n_valid: number; n_nan: number } | null;
}

export interface BgcModelGrid {
  lat0: number; lon0: number; step: number; n_lat: number; n_lon: number;
  lat_max: number; lon_max: number; lon_global: boolean;
  /** Pixel EDGES [west, south, east, north] of the PNG texture (rows run N -> S). */
  bounds: [number, number, number, number];
}

export interface BgcModelMeta {
  layer: string;
  months: string[];          // "yyyy-mm", oldest first
  latest: string | null;
  variables: BgcModelVariable[];
  grid: BgcModelGrid | null;
  product: { id: string; title: string; doi: string; doi_url: string; url: string; licence_url: string };
  attribution: string;
  caveat: string;
}

export type BgcModelPointStatus = "ok" | "no_data" | "not_covered";

export interface BgcModelPoint {
  var: string;
  month: string;
  lat: number;
  lon: number;
  unit: string;
  value_field: string;
  status: BgcModelPointStatus;
  attribution: string;
  caveat: string;
  [field: string]: unknown;   // the unit-named value, e.g. `no3_mmol_m3`
}

/** The month to show: the store's choice if the product still offers it, else the latest. */
export function effectiveBgcMonth(meta: BgcModelMeta | null, chosen: string | null): string | null {
  if (!meta || !meta.latest) return null;
  return chosen && meta.months.includes(chosen) ? chosen : meta.latest;
}

/** The variable to show: the store's choice if the product serves it, else the first. */
export function effectiveBgcVariable(meta: BgcModelMeta | null, chosen: string): string | null {
  if (!meta || meta.variables.length === 0) return null;
  return meta.variables.some((v) => v.key === chosen) ? chosen : meta.variables[0].key;
}

/** deck.gl hands out longitudes that continue past ±180 when the world repeats. */
export function wrapLongitude(lon: number): number {
  return ((((lon + 180) % 360) + 360) % 360) - 180;
}
