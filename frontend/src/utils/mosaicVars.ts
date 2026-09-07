// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// frontend/src/utils/mosaicVars.ts
// Pure variable/color utility module for the MOSAIC marine-sediment-carbon layer.
// Mirrors frontend/src/utils/geotracesElements.ts (element list + color fn) and
// frontend/src/utils/wodDecades.ts (decade ramp helpers). No React/deck.gl imports.

export type MosaicVarKey = "toc" | "tn" | "d13c" | "d14c";

export interface MosaicVar {
  key: MosaicVarKey;
  label: string; // English fallback; UI uses i18n
  unit: string;
  // value range for the color ramp (display ramp only — exact bounds aren't critical)
  domain: [number, number];
  ramp: "sequential" | "diverging";
  // sequential: single hue, dim -> hex. diverging: loHex -> midHex -> hex across the domain.
  hex: string;
  loHex?: string; // diverging only
  midHex?: string; // diverging only (defaults to a neutral slate if omitted)
}

export const MOSAIC_VARS: MosaicVar[] = [
  {
    key: "toc",
    label: "TOC (%)",
    unit: "%",
    domain: [0, 5], // typical marine-sediment total organic carbon range
    ramp: "sequential",
    hex: "#22c55e", // green
  },
  {
    key: "tn",
    label: "Total N (%)",
    unit: "%",
    domain: [0, 1], // typical marine-sediment total nitrogen range
    ramp: "sequential",
    hex: "#3b82f6", // blue
  },
  {
    key: "d13c",
    label: "δ¹³C (‰)",
    unit: "‰",
    domain: [-30, -18], // typical organic-matter δ13C range (marine vs terrestrial end members)
    ramp: "diverging",
    loHex: "#a855f7", // purple (more depleted / terrestrial-like)
    midHex: "#94a3b8",
    hex: "#f97316", // orange (more enriched / marine-like)
  },
  {
    key: "d14c",
    label: "Δ¹⁴C (‰)",
    unit: "‰",
    domain: [-1000, 0], // fully depleted (old carbon) to modern
    ramp: "diverging",
    loHex: "#1d4ed8", // deep blue (old/depleted carbon)
    midHex: "#94a3b8",
    hex: "#ef4444", // red (modern carbon)
  },
];
export const MOSAIC_VAR_KEYS = MOSAIC_VARS.map((v) => v.key);

const _byKey = Object.fromEntries(MOSAIC_VARS.map((v) => [v.key, v])) as Record<MosaicVarKey, MosaicVar>;

export function mosaicVarHex(key: MosaicVarKey): string {
  return _byKey[key]?.hex ?? "#94a3b8";
}

function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

function lerpRgb(c1: [number, number, number], c2: [number, number, number], t: number): [number, number, number] {
  return [
    Math.round(lerp(c1[0], c2[0], t)),
    Math.round(lerp(c1[1], c2[1], t)),
    Math.round(lerp(c1[2], c2[2], t)),
  ];
}

/**
 * Value -> RGB color for a MOSAIC variable.
 * Sequential vars (toc/tn): dim slate (low) -> variable hue (high), linear on the domain.
 * Diverging vars (d13c/d14c): loHex (low) -> midHex (mid) -> hex (high), linear on each half.
 * null/undefined -> muted slate (no-data).
 */
export function mosaicColor(varKey: MosaicVarKey, value: number | null | undefined): [number, number, number] {
  if (value == null) return [100, 116, 139];
  const v = _byKey[varKey];
  if (!v) return [148, 163, 184];
  const [lo, hi] = v.domain;
  const t = Math.max(0, Math.min(1, (value - lo) / (hi - lo || 1)));
  const highRgb = hexToRgb(v.hex);

  if (v.ramp === "diverging") {
    const loRgb = hexToRgb(v.loHex ?? "#94a3b8");
    const midRgb = hexToRgb(v.midHex ?? "#94a3b8");
    if (t < 0.5) return lerpRgb(loRgb, midRgb, t / 0.5);
    return lerpRgb(midRgb, highRgb, (t - 0.5) / 0.5);
  }

  // sequential: dim base -> hex
  const base = 70;
  return lerpRgb([base, base, base], highRgb, t);
}

// Decades present in mosaic_cores on production (counted 2026-09-04):
// 1900:49 1950:645 1960:2716 1970:954 1980:1560 1990:2937 2000:4805
// 2010:4017 2020:287, plus 7,638 cores with no year at all.
// The previous list started at 1980 and omitted the undated bucket, leaving
// 12,002 of 25,608 cores (46.9%) impossible to select or exclude.
export const MOSAIC_DECADES: number[] = [1900, 1950, 1960, 1970, 1980, 1990, 2000, 2010, 2020];

// Perceptually-ordered ramp, older (deep indigo) -> recent (warm amber).
// One hex per entry in MOSAIC_DECADES (same length/order).
const MOSAIC_DECADE_HEX: string[] = [
  "#3d206f",
  "#3c32a7",
  "#576ecb",
  "#2d81c5",
  "#1a99a8",
  "#1eba26",
  "#cdcd23",
  "#e0a727",
  "#e77a36",
];

// Neutral color for the "undated" bucket — not part of the decade ramp above
// (it isn't a point on the older->recent gradient, so it gets its own color
// rather than borrowing one that would misleadingly imply a decade).
export const MOSAIC_UNDATED_HEX = "#6b7280";

function _bucketIndex(decade: number): number {
  let best = 0;
  let bestD = Infinity;
  for (let i = 0; i < MOSAIC_DECADES.length; i++) {
    const d = Math.abs(MOSAIC_DECADES[i] - decade);
    if (d < bestD) {
      bestD = d;
      best = i;
    }
  }
  return best;
}

export function mosaicDecadeColor(decade: number): [number, number, number] {
  return hexToRgb(MOSAIC_DECADE_HEX[_bucketIndex(decade)]);
}

export function mosaicDecadeHex(decade: number): string {
  return MOSAIC_DECADE_HEX[_bucketIndex(decade)];
}
