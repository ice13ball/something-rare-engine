// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import type { CurrentsMeta, CurrentArrow } from "../CurrentsLayer";
import type { VelocityField } from "../CurrentsParticleCanvas";

/** Build a sparse arrow grid (every 4th texel) from decoded RGBA + meta. */
export function decodeCurrentArrows(
  rgba: { data: Uint8ClampedArray; width: number; height: number },
  meta: CurrentsMeta,
): CurrentArrow[] {
  const { data, width: w, height: h } = rgba;
  const [west, south, east, north] = meta.bounds;
  const [umin, umax] = meta.imageUnscale;
  const span = umax - umin;
  const stepPx = 4;   // sample every 4th texel → readable arrow density
  const lenDeg = 1.2; // arrow length scale (degrees per m/s)
  const out: CurrentArrow[] = [];
  for (let y = 0; y < h; y += stepPx) {
    for (let x = 0; x < w; x += stepPx) {
      const i = (y * w + x) * 4;
      if (data[i + 3] === 0) continue;             // transparent = land/no-data
      const u = (data[i] / 255) * span + umin;     // R → u
      const v = (data[i + 1] / 255) * span + umin; // G → v
      const speed = Math.hypot(u, v);
      if (speed < 0.05) continue;                  // skip near-still cells
      const lon = west + (x / w) * (east - west);
      const lat = north - (y / h) * (north - south); // row 0 = north
      out.push({ source: [lon, lat], target: [lon + u * lenDeg, lat + v * lenDeg], speed });
    }
  }
  return out;
}

// Cap-bounded cache of decoded velocity fields + arrow sets, keyed "{depth}:{date}".
export type CurrentsCacheEntry = { field: VelocityField; arrows: CurrentArrow[] };
export const _currentsFieldLRU = new Map<string, CurrentsCacheEntry>();
const _CURRENTS_LRU_CAP = 24;
export function lruPut(key: string, entry: CurrentsCacheEntry) {
  _currentsFieldLRU.delete(key);
  _currentsFieldLRU.set(key, entry);
  while (_currentsFieldLRU.size > _CURRENTS_LRU_CAP) {
    const k = _currentsFieldLRU.keys().next().value as string;
    _currentsFieldLRU.delete(k);
  }
}
