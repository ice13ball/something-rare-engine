// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// frontend/src/utils/geotracesElements.ts
export type GeotracesElementKey = "mn" | "fe" | "co" | "ni" | "cu";

export interface GeotracesElement {
  key: GeotracesElementKey;
  symbol: string;   // "Mn"
  label: string;    // English fallback; UI uses i18n
  hex: string;
  // value range for color ramp (source units; Co is pmol/kg, others nmol/kg)
  domain: [number, number];
}

export const GEOTRACES_ELEMENTS: GeotracesElement[] = [
  { key: "mn", symbol: "Mn", label: "Manganese", hex: "#a855f7", domain: [0, 5] },
  { key: "fe", symbol: "Fe", label: "Iron",      hex: "#f97316", domain: [0, 3] },
  { key: "co", symbol: "Co", label: "Cobalt",    hex: "#22d3ee", domain: [0, 120] },
  { key: "ni", symbol: "Ni", label: "Nickel",    hex: "#84cc16", domain: [0, 12] },
  { key: "cu", symbol: "Cu", label: "Copper",    hex: "#fbbf24", domain: [0, 6] },
];
export const ELEMENT_KEYS = GEOTRACES_ELEMENTS.map((e) => e.key);

/** Decades covered by GEOTRACES IDP2025 (~2003–2023). Used by the decade-chip filter. */
export const GEOTRACES_DECADES = [2000, 2010, 2020];
const _byKey = Object.fromEntries(GEOTRACES_ELEMENTS.map((e) => [e.key, e]));

export function elementHex(key: GeotracesElementKey): string {
  return _byKey[key]?.hex ?? "#94a3b8";
}

function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

// low value -> dim slate, high -> element hex (linear on the element domain)
export function elementColor(key: GeotracesElementKey, value: number | null | undefined): [number, number, number, number] {
  if (value == null) return [100, 116, 139, 60];
  const el = _byKey[key];
  const [lo, hi] = el ? el.domain : [0, 1];
  const t = Math.max(0, Math.min(1, (value - lo) / (hi - lo || 1)));
  const [r, g, b] = hexToRgb(el?.hex ?? "#94a3b8");
  const base = 70;
  return [Math.round(base + (r - base) * t), Math.round(base + (g - base) * t), Math.round(base + (b - base) * t), 200];
}
