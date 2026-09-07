// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// Single source of truth for the WOD historical-oxygen decade colour ramp.
// Used by the map dots (Map3D), the filter chips + LayerRow legend (Map3DControls),
// and the LegendPanel swatch — so legend/filter colours always match the map.
export const WOD_DECADES: number[] = [
  1900, 1910, 1920, 1930, 1940, 1950, 1960, 1970, 1980, 1990, 2000, 2010, 2020,
];

// Perceptually-ordered ramp, older (deep indigo) -> recent (warm amber).
// One hex per entry in WOD_DECADES (same length/order).
export const WOD_DECADE_HEX: string[] = [
  "#3b1f6b", "#4a2a8a", "#3f3aa8", "#2f5fc0", "#1f86c8", "#1aa3b0",
  "#1bb58a", "#3fc06a", "#86c83f", "#c8c020", "#e8a020", "#ef7a1a", "#e23b3b",
];

function _hexToRgb(h: string): [number, number, number] {
  const n = parseInt(h.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

/** Nearest documented decade bucket for an arbitrary cast decade (handles pre-1900 / >2020). */
function _bucketIndex(decade: number): number {
  let best = 0, bestD = Infinity;
  for (let i = 0; i < WOD_DECADES.length; i++) {
    const d = Math.abs(WOD_DECADES[i] - decade);
    if (d < bestD) { bestD = d; best = i; }
  }
  return best;
}

export function wodDecadeColor(decade: number): [number, number, number] {
  return _hexToRgb(WOD_DECADE_HEX[_bucketIndex(decade)]);
}

export function wodDecadeHex(decade: number): string {
  return WOD_DECADE_HEX[_bucketIndex(decade)];
}
