// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { rampColor } from "../components/map3d/colors";
import type { YearRange } from "./coastdomYearFilter";

/**
 * `/api/v1/argo-oxygen/points/{depth}` (backend/domains/argo_oxygen_points.py `_assemble_points`): one document
 * per display depth, parallel columns, drawable profiles only. The stable profile key is rebuilt from
 * `floats[fi[i]]` + `cycle[i]` + (i in `descending`) — never the array index (it changes with the year filter).
 */
export type ArgoOxygenDoc = {
  product: string; depth: number; window: [number, number]; units: string; n: number;
  floats: string[]; fi: number[]; cycle: number[]; descending: number[];
  lon: number[]; lat: number[]; year: number[]; value: (number | null)[];
};
export type ArgoOxygenPoint = { i: number; key: string; position: [number, number]; year: number; value: number | null };
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

export function argoProfileKey(prefix: string, cycle: number, descending: boolean): string {
  return `${prefix}_${String(cycle).padStart(3, "0")}${descending ? "D" : ""}`;
}

/** Points filtered by an inclusive year range; grey (null) first so coloured ones draw on top. */
export function argoOxygenPoints(doc: ArgoOxygenDoc, range: YearRange | null): ArgoOxygenPoint[] {
  const desc = new Set(doc.descending);
  const grey: ArgoOxygenPoint[] = [], coloured: ArgoOxygenPoint[] = [];
  for (let i = 0; i < doc.n; i++) {
    const y = doc.year[i];
    if (range && (y < range[0] || y > range[1])) continue;
    const p: ArgoOxygenPoint = {
      i, key: argoProfileKey(doc.floats[doc.fi[i]], doc.cycle[i], desc.has(i)),
      position: [doc.lon[i], doc.lat[i]], year: y, value: doc.value[i] ?? null,
    };
    (p.value === null ? grey : coloured).push(p);
  }
  return grey.concat(coloured);
}

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

/** File a document under ITS OWN depth: a late answer for 500 m must never be drawn as 1000 m. */
export function withArgoDoc(prev: Record<number, ArgoOxygenDoc>, doc: ArgoOxygenDoc): Record<number, ArgoOxygenDoc> {
  return { ...prev, [doc.depth]: doc };
}

/** ⛔ The document that may be drawn: the SELECTED depth's own, and only while Measurements is on. While that
 *  depth loads this is undefined (an empty layer, never the previous depth's values); a late answer filed under
 *  another depth can never be returned here. */
export function selectArgoDoc(
  docs: Record<number, ArgoOxygenDoc>, depth: number, drawing: boolean,
): ArgoOxygenDoc | undefined {
  if (!drawing) return undefined;
  const d = docs[depth];
  return d && d.depth === depth ? d : undefined;
}

/** A decoded document is ~20 MB of JS heap: keep the current depth and the last two visited, no more. */
export const ARGO_DOCS_KEPT = 3;

/** Visit order, most recent first (the selected depth is always `[0]`). */
export function touchArgoDepth(recent: number[], depth: number): number[] {
  return [depth, ...recent.filter((d) => d !== depth)];
}

/**
 * File an arriving document and evict the oldest beyond `keep`. `recent` is the visit order (current first), so
 * the selected depth is never evicted. `dropped` are depths whose one-shot fetch latch the caller must release:
 * a depth that is no longer in memory has to be fetchable again, not stay latched with nothing behind it.
 */
export function fileArgoDoc(
  prev: Record<number, ArgoOxygenDoc>, doc: ArgoOxygenDoc, recent: number[], keep: number = ARGO_DOCS_KEPT,
): { docs: Record<number, ArgoOxygenDoc>; dropped: number[] } {
  const filed = withArgoDoc(prev, doc);
  const held = Object.keys(filed).map(Number);
  const order = [...recent.filter((d) => held.includes(d)), ...held.filter((d) => !recent.includes(d))];
  const kept = new Set(order.slice(0, Math.max(1, keep)));
  const docs: Record<number, ArgoOxygenDoc> = {};
  for (const d of kept) docs[d] = filed[d];
  return { docs, dropped: held.filter((d) => !kept.has(d)) };
}

/** Union of two year spans; the span is taken once per arriving document, never by rescanning the kept ones. */
export function mergeYearBounds(
  a: { min: number; max: number } | null, doc: ArgoOxygenDoc,
): { min: number; max: number } | null {
  const b = argoYearBounds([doc]);
  if (!a) return b;
  if (!b) return a;
  return a.min <= b.min && a.max >= b.max ? a : { min: Math.min(a.min, b.min), max: Math.max(a.max, b.max) };
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

export function argoYearBounds(docs: (ArgoOxygenDoc | undefined)[]): { min: number; max: number } | null {
  let min = Infinity, max = -Infinity;
  for (const d of docs) {
    if (!d) continue;
    for (const y of d.year) { if (y < min) min = y; if (y > max) max = y; }
  }
  return Number.isFinite(min) ? { min, max } : null;
}
