// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { rampColor } from "../components/map3d/colors";

export type OxygenDisplayMode = "field" | "hexes" | "points";
type RGBA = [number, number, number, number];
type OxygenViewMeta = { key: string; vmin: number; vmax: number; ramp?: { pos: number; hex: string }[] };

export const ARGO_POINTS_ID = "argo-oxygen-points";
/** ⛔ The only field view a single profile can be compared with. "change" (vs WOA 1971–2000) needs a baseline
 *  a profile does not have, so the points never use the diverging ramp (decision 2026-10-06). */
export const ARGO_POINTS_VIEW = "recent";
export const ARGO_FAILED_NAME = "Argo O₂ Measurements";
/** No good adjusted sample inside the selected depth's window. */
export const ARGO_NO_VALUE_RGBA: RGBA = [148, 163, 184, 110];
const POINT_ALPHA = 235;

/** Field / Hexagons / Measurements are mutually exclusive (Michal, 2026-10-06), as for ocean-carbon. */
export function oxygenDrawing(oxygenActive: boolean, mode: OxygenDisplayMode, pointsActive: boolean) {
  return {
    field: oxygenActive && mode === "field",
    hexes: oxygenActive && mode === "hexes",
    points: oxygenActive && mode === "points" && pointsActive,
  };
}

/** The ISAS PNG tiles are not fetched in Measurements mode (the hex view keeps its current behaviour). */
export const oxygenNeedsFieldTiles = (oxygenActive: boolean, mode: OxygenDisplayMode): boolean =>
  oxygenActive && mode !== "points";

/** The Recent O₂ ramp of /v1/oxygen/meta, whatever `oxygenView` is; out-of-ramp values clamp to the ends. */
export function argoOxygenColor(value: number | null, meta: { views: OxygenViewMeta[] } | null | undefined): RGBA {
  const vw = meta?.views.find((v) => v.key === ARGO_POINTS_VIEW);
  if (value === null || !Number.isFinite(value) || !vw || !vw.ramp?.length) return ARGO_NO_VALUE_RGBA;
  return rampColor(value, vw.vmin, vw.vmax, vw.ramp, POINT_ALPHA);
}

/** Mirrors backend DEPTH_WINDOWS (metres, from pressure by UNESCO 1983). */
export const ARGO_DEPTH_WINDOW_BOUNDS: Record<number, [number, number]> = {
  0: [0, 10], 50: [40, 60], 100: [90, 110], 200: [175, 225], 500: [450, 550],
  1000: [950, 1050], 1500: [1425, 1575], 2000: [1900, 2100],
};
export const argoWindowLabel = (d: number): string => {
  const w = ARGO_DEPTH_WINDOW_BOUNDS[d];
  return w ? `${w[0]}–${w[1]} m` : `${d} m`;
};
