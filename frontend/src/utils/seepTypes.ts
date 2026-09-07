// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

export interface SeepType { key: string; label: string; hex: string; rgb: [number, number, number]; }

// Priority order (index 0 = highest) — matches backend primary_type derivation.
export const SEEP_TYPES: SeepType[] = [
  { key: "gas_bubbles",    label: "Gas bubbles / flares",       hex: "#ef4444", rgb: [239, 68, 68] },
  { key: "hydrate",        label: "Gas hydrate",                hex: "#22d3ee", rgb: [34, 211, 238] },
  { key: "mound",          label: "Mound",                      hex: "#fbbf24", rgb: [251, 191, 36] },
  { key: "pockmark",       label: "Pockmark",                   hex: "#60a5fa", rgb: [96, 165, 250] },
  { key: "chem_community", label: "Chemosynthetic community",   hex: "#34d399", rgb: [52, 211, 153] },
  { key: "hardground",     label: "Carbonate hardground",       hex: "#a78bfa", rgb: [167, 139, 250] },
];

const BY_KEY = new Map(SEEP_TYPES.map(t => [t.key, t]));
const FALLBACK: [number, number, number] = [148, 163, 184]; // slate for unknown/none

export function seepTypeColorRgba(key: string | null | undefined, alpha = 230): [number, number, number, number] {
  const rgb = (key && BY_KEY.get(key)?.rgb) || FALLBACK;
  return [rgb[0], rgb[1], rgb[2], alpha];
}
export function seepTypeLabel(key: string): string {
  return BY_KEY.get(key)?.label ?? key;
}
