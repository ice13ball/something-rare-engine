// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// Bbox helpers (for flyToLayer) — extracted from Map3D.tsx, bodies byte-identical.

export type Box = { minLon: number; maxLon: number; minLat: number; maxLat: number };
export function expandBox(box: Box, coords: number[]) {
  const [lon, lat] = coords;
  if (lon < box.minLon) box.minLon = lon;
  if (lon > box.maxLon) box.maxLon = lon;
  if (lat < box.minLat) box.minLat = lat;
  if (lat > box.maxLat) box.maxLat = lat;
}
export function walkCoords(coords: unknown, box: Box) {
  if (!Array.isArray(coords)) return;
  if (typeof coords[0] === "number") { expandBox(box, coords as number[]); return; }
  for (const c of coords) walkCoords(c, box);
}
export function bboxToView(box: Box) {
  if (!isFinite(box.minLon)) return { longitude: 0, latitude: 10, zoom: 2 };
  const span = Math.max(box.maxLon - box.minLon, box.maxLat - box.minLat);
  const zoom = span > 40 ? 3 : span > 20 ? 4 : span > 10 ? 5 : span > 5 ? 6 : span > 2 ? 7 : span > 1 ? 8 : span > 0.5 ? 9 : 10;
  return { longitude: (box.minLon + box.maxLon) / 2, latitude: (box.minLat + box.maxLat) / 2, zoom };
}
export function getBBoxCenter(features: { geometry: unknown }[]) {
  const box: Box = { minLon: Infinity, maxLon: -Infinity, minLat: Infinity, maxLat: -Infinity };
  for (const f of features) {
    const geom = f.geometry as { coordinates?: unknown } | null;
    if (geom?.coordinates) walkCoords(geom.coordinates, box);
  }
  return bboxToView(box);
}

// Approximate visible lon/lat span at a given zoom; pitch widens it (perspective
// shows more terrain at the top of the screen). Generous on purpose — we use this
// to gate viewport-culling refilters, not to clip pixel-perfectly.
export function approxViewBbox(vs: { longitude?: unknown; latitude?: unknown; zoom?: unknown; pitch?: unknown }): Box {
  const lon = (vs.longitude as number) ?? 0;
  const lat = (vs.latitude as number) ?? 0;
  const zoom = (vs.zoom as number) ?? 2;
  const pitch = (vs.pitch as number) ?? 0;
  const span = 360 / Math.pow(2, Math.max(0, zoom));
  const pitchMul = 1 + Math.max(0, pitch) / 45;  // 0° → 1×, 45° → 2×
  const halfLon = Math.min(180, span * 1.5 * pitchMul);
  const halfLat = Math.min(90,  span * 1.0 * pitchMul);
  return {
    minLon: lon - halfLon,
    maxLon: lon + halfLon,
    minLat: Math.max(-90, lat - halfLat),
    maxLat: Math.min(90,  lat + halfLat),
  };
}

export function bboxContains(outer: Box, inner: Box): boolean {
  return outer.minLon <= inner.minLon
      && outer.maxLon >= inner.maxLon
      && outer.minLat <= inner.minLat
      && outer.maxLat >= inner.maxLat;
}

export function expandBoxBuffer(b: Box, factor: number): Box {
  const cx = (b.minLon + b.maxLon) / 2;
  const cy = (b.minLat + b.maxLat) / 2;
  const halfW = (b.maxLon - b.minLon) / 2;
  const halfH = (b.maxLat - b.minLat) / 2;
  return {
    minLon: cx - halfW * factor,
    maxLon: cx + halfW * factor,
    minLat: Math.max(-90, cy - halfH * factor),
    maxLat: Math.min(90,  cy + halfH * factor),
  };
}
