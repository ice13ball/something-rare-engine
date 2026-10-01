// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

/**
 * Shapes served by `/api/v1/ocean-colour/*` (layer `ocean-colour-satellite`):
 * satellite chlorophyll-a and primary production (Copernicus-GlobColour), monthly,
 * block-averaged to 0.25°. Each month comes from the multi-year (reprocessed) or the
 * near-real-time product; the API says which.
 */
import type { BgcModelGrid, BgcModelRampStop, BgcModelTick } from "./bgcModel";

export type OceanColourProductKey = "my" | "nrt";

export interface OceanColourVariable {
  key: string;
  label: string;
  unit: string;
  /** Name of the unit-carrying field in the /point response, e.g. `chl_mg_m3`. */
  field: string;
  scale: "linear" | "log" | "sqrt";
  vmin: number;
  vmax: number;
  ramp: BgcModelRampStop[];
  ticks: BgcModelTick[];
  note: string;
  stats: { p1?: number; p50?: number; p99?: number; n_valid: number; n_nan: number } | null;
}

export interface OceanColourProduct {
  id: string; title: string; label: string; doi: string; doi_url: string; url: string;
}

export interface OceanColourMeta {
  layer: string;
  months: string[];                                        // "yyyy-mm", oldest first
  latest: string | null;
  month_products: Record<string, OceanColourProductKey | null>;
  variables: OceanColourVariable[];
  grid: BgcModelGrid | null;
  products: Record<OceanColourProductKey, OceanColourProduct>;
  licence_url: string;
  attribution: string;
  caveat: string;
}

export type OceanColourPointStatus = "ok" | "no_data" | "not_covered";

export interface OceanColourPoint {
  var: string;
  month: string;
  lat: number;
  lon: number;
  unit: string;
  value_field: string;
  status: OceanColourPointStatus;
  /** Share of the 36 source cells (4 km) that held a value; null outside the grid. */
  valid_fraction: number | null;
  product_key: OceanColourProductKey | null;
  product_label: string | null;
  reason?: string;
  attribution: string;
  caveat: string;
  [field: string]: unknown;   // the unit-named value, e.g. `chl_mg_m3`
}

/** The month to show: the store's choice if the product still offers it, else the latest. */
export function effectiveOceanColourMonth(meta: OceanColourMeta | null, chosen: string | null): string | null {
  if (!meta || !meta.latest) return null;
  return chosen && meta.months.includes(chosen) ? chosen : meta.latest;
}

/** The variable to show: the store's choice if the product serves it, else the first. */
export function effectiveOceanColourVariable(meta: OceanColourMeta | null, chosen: string): string | null {
  if (!meta || meta.variables.length === 0) return null;
  return meta.variables.some((v) => v.key === chosen) ? chosen : meta.variables[0].key;
}
