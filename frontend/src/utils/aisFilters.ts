// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// frontend/src/utils/aisFilters.ts
//
// AIS live-layer classification + filter predicate.
// Used by BOTH Map3D.tsx useMemo AND flyConfigs["ais-live"].filter
// so the visible set never drifts between them.

export type AisShipClass = "cargo" | "tanker" | "fishing" | "passenger" | "military" | "tug" | "pleasure" | "other";

export interface AisFilterState {
  aisShipTypeFilters: Set<string>;  // classes above
  aisFlagFilters: Set<string>;      // ISO alpha-2
}

/**
 * AIS ITU-R M.1371 ship-type code → broad class bucket.
 * Reference: https://api.vtexplorer.com/docs/ref-aistypes.html
 *
 * Only the first digit encodes the broad class for most ranges; fishing (30),
 * tugs (52), and military (35) are specific codes.
 */
export function classifyShipType(code: number | null | undefined): AisShipClass {
  if (code == null) return "other";
  if (code === 30) return "fishing";
  if (code === 35) return "military";
  if (code === 52) return "tug";
  if (code >= 36 && code <= 37) return "pleasure";
  if (code >= 60 && code <= 69) return "passenger";
  if (code >= 70 && code <= 79) return "cargo";
  if (code >= 80 && code <= 89) return "tanker";
  return "other";
}

/**
 * Returns RGB(A) color for a ship class.
 *
 * TODO (user decision, 5-10 lines): this palette is a neutral first pass.
 * The design choice is whether to emphasise *risk-relevant* vessel types
 * (research/mining/support in hot colors) or *neutral* broad classes
 * (current scheme). Since the whole point of the ais-live layer is to
 * surface activity near ISA concessions, you may want to highlight support
 * & research vessels (type codes 50, 53, 54) in a warm color and dim the
 * rest. Edit the mapping below when you have a preference.
 */
export function colorForShipClass(cls: AisShipClass): [number, number, number, number] {
  switch (cls) {
    case "cargo":     return [96, 165, 250, 220];   // blue
    case "tanker":    return [251, 146, 60, 220];   // orange
    case "fishing":   return [34, 197, 94, 220];    // green
    case "passenger": return [168, 85, 247, 220];   // violet
    case "military":  return [239, 68, 68, 220];    // red
    case "tug":       return [250, 204, 21, 220];   // yellow
    case "pleasure":  return [244, 114, 182, 220];  // pink
    case "other":
    default:          return [148, 163, 184, 200];  // slate
  }
}

export function matchesAisFilters(
  p: Record<string, unknown>,
  s: AisFilterState,
): boolean {
  if (s.aisShipTypeFilters.size > 0) {
    const cls = classifyShipType(p.ship_type as number | null);
    if (!s.aisShipTypeFilters.has(cls)) return false;
  }
  if (s.aisFlagFilters.size > 0) {
    const flag = p.flag as string | undefined;
    if (!flag || !s.aisFlagFilters.has(flag)) return false;
  }
  return true;
}

export const AIS_SHIP_CLASSES: AisShipClass[] = [
  "cargo", "tanker", "fishing", "passenger", "military", "tug", "pleasure", "other",
];
