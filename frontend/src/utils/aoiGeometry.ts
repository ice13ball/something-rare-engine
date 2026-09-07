// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// AOI (Area of Interest) geometry utilities for the export feature.
// All functions are pure — no side effects, no imports.

export type AoiSelection =
  | { mode: "box"; bbox: [number, number, number, number] }
  | { mode: "polygon"; polygon: number[][] }
  | { mode: "hexes"; cellIds: string[] };

/**
 * Build a normalised [minLng, minLat, maxLng, maxLat] bbox from two drag corners.
 * Order of start/end doesn't matter.
 */
export function bboxFromDrag(
  start: [number, number],
  end: [number, number],
): [number, number, number, number] {
  const [ax, ay] = start, [bx, by] = end;
  return [Math.min(ax, bx), Math.min(ay, by), Math.max(ax, bx), Math.max(ay, by)];
}

/**
 * Toggle a hex cell id in/out of a list (immutable).
 */
export function toggleHexCell(ids: string[], id: string): string[] {
  return ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id];
}

/**
 * Close a polygon ring if the last vertex doesn't already equal the first.
 * Returns the original array unchanged when len < 3 or already closed.
 */
export function closePolygon(verts: number[][]): number[][] {
  if (verts.length < 3) return verts;
  const first = verts[0], last = verts[verts.length - 1];
  if (first[0] === last[0] && first[1] === last[1]) return verts;
  return [...verts, first];
}

/**
 * Serialise an AoiSelection to a URL query-string fragment consumed by the
 * backend `parse_aoi` helper:
 *   box    → "bbox=minLng,minLat,maxLng,maxLat"
 *   hexes  → "cells=id1;id2;..."  (";" delimiter: a cell_id is "i,j" so it
 *            already contains a comma — joining with "," would be ambiguous.
 *            Each id is percent-encoded so its internal comma survives transit.)
 *   polygon→ "poly=<encodeURIComponent(GeoJSON Polygon geometry)>"
 */
export function aoiToParams(sel: AoiSelection): string {
  if (sel.mode === "box") return `bbox=${sel.bbox.join(",")}`;
  if (sel.mode === "hexes")
    return `cells=${sel.cellIds.map(encodeURIComponent).join(";")}`;
  const geom = { type: "Polygon", coordinates: [closePolygon(sel.polygon)] };
  return `poly=${encodeURIComponent(JSON.stringify(geom))}`;
}
