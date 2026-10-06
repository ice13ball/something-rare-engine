// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { rampColor } from "../components/map3d/colors";
import type { YearRange } from "./coastdomYearFilter";

/**
 * The `/api/v1/glodap/casts` document (backend/domains/glodap_points.py `_assemble_casts`):
 * parallel columns, one entry per drawable cast. `values[variable][depth]` is a column of the
 * same length, `null` where no WOCE-flag-2 bottle fell in that depth's window. `cant` has no
 * key at all — bottles do not carry it.
 */
export type GlodapCastsDoc = {
  product: string; n: number; keys: string[]; lon: number[]; lat: number[]; year: number[];
  values: Record<"dic" | "talk" | "ph", Record<string, (number | null)[]>>;
};
export type GlodapPoint = { i: number; key: string; position: [number, number]; year: number; value: number | null };
type RampMeta = { vmin: number; vmax: number; ramp?: { pos: number; hex: string }[] };

/** No acceptable (WOCE 2) bottle within the selected depth's window, or a variable bottles do not carry (Cant). */
export const GLODAP_NO_VALUE_RGBA: [number, number, number, number] = [148, 163, 184, 110];
const POINT_ALPHA = 235;

/**
 * Points for the selected variable and depth, filtered by an inclusive year range. Grey (null)
 * points come FIRST so the coloured ones draw on top of them within the layer.
 */
export function glodapPoints(doc: GlodapCastsDoc, variable: string, depth: number, range: YearRange | null): GlodapPoint[] {
  const col = (doc.values as Record<string, Record<string, (number | null)[]> | undefined>)[variable]?.[String(depth)];
  const grey: GlodapPoint[] = [], coloured: GlodapPoint[] = [];
  for (let i = 0; i < doc.n; i++) {
    const y = doc.year[i];
    if (range && (y < range[0] || y > range[1])) continue;
    const v = col ? col[i] : null;
    const p: GlodapPoint = { i, key: doc.keys[i], position: [doc.lon[i], doc.lat[i]], year: y, value: v ?? null };
    (p.value === null ? grey : coloured).push(p);
  }
  return grey.concat(coloured);
}

/**
 * What the ocean-carbon layer draws for a display mode. The three are mutually exclusive: Measurements REPLACE
 * the field bitmaps and the hex view (Michal, 2026-10-06 — "both on makes no sense"). `points` additionally
 * needs the `glodap-points` layer on, which the store keeps in step with the mode.
 */
export function carbonDrawing(
  carbonActive: boolean, mode: "field" | "hexes" | "points", glodapActive: boolean,
): { field: boolean; hexes: boolean; points: boolean } {
  return {
    field: carbonActive && mode === "field",
    hexes: carbonActive && mode === "hexes",
    points: carbonActive && mode === "points" && glodapActive,
  };
}

/** The field's own ramp, raw bottle values (never corrected to 2002); out-of-ramp values clamp to the ends. */
export function glodapColor(value: number | null, vm: RampMeta | undefined): [number, number, number, number] {
  if (value === null || !Number.isFinite(value) || !vm || !vm.ramp?.length) return GLODAP_NO_VALUE_RGBA;
  return rampColor(value, vm.vmin, vm.vmax, vm.ramp, POINT_ALPHA);
}

/** Depth windows the bottles are matched in, per standard depth (m). Mirrors backend DEPTH_WINDOWS; glodap-points.test.ts pins the keys. */
export const GLODAP_DEPTH_WINDOWS: Record<number, string> = {
  0: "0–10 m", 200: "175–225 m", 500: "450–550 m", 1000: "950–1050 m",
  2000: "1875–2250 m", 3000: "2750–3250 m", 4000: "3750–4250 m",
};
/** The same windows as numbers [lo, hi] (backend DEPTH_WINDOWS), for picking a cast's bottle without the server. */
export const GLODAP_DEPTH_WINDOW_BOUNDS: Record<number, [number, number]> = {
  0: [0, 10], 200: [175, 225], 500: [450, 550], 1000: [950, 1050],
  2000: [1875, 2250], 3000: [2750, 3250], 4000: [3750, 4250],
};
export const glodapWindowLabel = (d: number): string => GLODAP_DEPTH_WINDOWS[d] ?? `${d} m`;

export function glodapYearBounds(doc: GlodapCastsDoc | null): { min: number; max: number } | null {
  if (!doc || doc.n === 0) return null;
  let min = Infinity, max = -Infinity;
  for (const y of doc.year) { if (y < min) min = y; if (y > max) max = y; }
  return { min, max };
}
