// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

export interface ThawCategory { key: string; label: string; hex: string; rgb: [number, number, number]; }

// key = lowercased/trimmed feature_category from the source (real values verified in Task 1).
export const THAW_CATEGORIES: ThawCategory[] = [
  { key: "thermokarst lake",         label: "Thermokarst lake",        hex: "#38bdf8", rgb: [56, 189, 248] },
  { key: "active layer detachment",  label: "Active-layer detachment", hex: "#f97316", rgb: [249, 115, 22] },
  { key: "retrogressive thaw slump", label: "Retrogressive thaw slump",hex: "#ef4444", rgb: [239, 68, 68] },
  { key: "thermokarst",              label: "Thermokarst (generic)",   hex: "#a78bfa", rgb: [167, 139, 250] },
  { key: "wildfire-induced thaw",    label: "Wildfire-induced thaw",   hex: "#fbbf24", rgb: [251, 191, 36] },
  { key: "thermokarst wetland",      label: "Thermokarst wetland",     hex: "#34d399", rgb: [52, 211, 153] },
  { key: "thermoerosional gully",    label: "Thermo-erosional gully",  hex: "#e879f9", rgb: [232, 121, 249] },
  { key: "thaw pond",                label: "Thaw pond",               hex: "#22d3ee", rgb: [34, 211, 238] },
  { key: "non-abrupt",               label: "Non-abrupt",              hex: "#94a3b8", rgb: [148, 163, 184] },
];

const BY_KEY = new Map(THAW_CATEGORIES.map(t => [t.key, t]));
const FALLBACK: [number, number, number] = [148, 163, 184]; // slate for unmatched / non-abrupt

function _norm(k: string | null | undefined): string {
  return (k ?? "").trim().toLowerCase();
}
export function thawCategoryColorRgba(key: string | null | undefined, alpha = 230): [number, number, number, number] {
  const rgb = BY_KEY.get(_norm(key))?.rgb || FALLBACK;
  return [rgb[0], rgb[1], rgb[2], alpha];
}

// Darker shade of the category colour, used as the dot OUTLINE so points stay
// visible against the near-white Arctic terrain (a white border vanished there)
// while still reading as a "coloured" ring on the dark ocean too.
export function thawCategoryLineRgba(key: string | null | undefined, alpha = 255): [number, number, number, number] {
  const rgb = BY_KEY.get(_norm(key))?.rgb || FALLBACK;
  const dark = (c: number) => Math.round(c * 0.45);
  return [dark(rgb[0]), dark(rgb[1]), dark(rgb[2]), alpha];
}
export function thawCategoryLabel(key: string | null | undefined): string {
  return BY_KEY.get(_norm(key))?.label ?? (key ?? "Unclassified");
}
