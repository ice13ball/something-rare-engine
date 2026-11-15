// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

/**
 * IMOS zooplankton (AusCPR + National Reference Stations): colour and marker rules.
 *
 * ⛔ Three states, never merged: a total above zero is a filled marker on a log scale; a total of exactly 0 is a
 * HOLLOW marker (outline only: counted, nothing found); a total of null is UNKNOWN (no copepod taxon was counted
 * in that sample) and is drawn faint grey. An unknown must never read as a zero.
 */

export type Rgba = [number, number, number, number];

/** Upper edges (individuals per m³) of the first four classes; the fifth is open-ended. Log10 steps. */
export const IMOS_ZOOP_THRESHOLDS = [1, 10, 100, 1000] as const;
/** Positional with layers["imos-zooplankton"].colorRamp[i].label in legend.json, and LAYER_STRUCT.colorRampHex. */
export const IMOS_ZOOP_BIN_HEX = ["#4c1d95", "#7c3aed", "#c026d3", "#fb7185", "#fde047"] as const;

function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

/** Class index 0..4 for a positive total. */
export function imosZoopBin(total: number): number {
  const i = IMOS_ZOOP_THRESHOLDS.findIndex((edge) => total < edge);
  return i === -1 ? IMOS_ZOOP_THRESHOLDS.length : i;
}

/** The total as a finite number, or null for anything else (missing, NaN, non-number). */
export function imosZoopTotal(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) && v >= 0 ? v : null;
}

export function imosZoopFill(v: unknown): Rgba {
  const total = imosZoopTotal(v);
  if (total === null) return [148, 163, 184, 45];       // unknown: faint grey
  if (total === 0) return [0, 0, 0, 0];                  // counted and absent: hollow
  const [r, g, b] = hexToRgb(IMOS_ZOOP_BIN_HEX[imosZoopBin(total)]);
  return [r, g, b, 215];
}

export function imosZoopLine(v: unknown): Rgba {
  const total = imosZoopTotal(v);
  if (total === null) return [148, 163, 184, 150];
  if (total === 0) return [226, 232, 240, 235];          // the outline IS the marker
  return [255, 255, 255, 150];
}

export function imosZoopLineWidth(v: unknown): number {
  return imosZoopTotal(v) === 0 ? 2 : 1;
}
