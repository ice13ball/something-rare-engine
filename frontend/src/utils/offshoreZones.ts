// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// Some offshore_activities sources include polygons that are NOT specific
// concessions but aggregate zone classifications: "available", "environmental",
// "planned" zones — administrative metadata for a whole EEZ. They share a row
// schema with concessions but mean something completely different, and
// rendering them with the same red fill swamps the map (Colombia ANH alone
// has a single 347,378 km² "DISPONIBLE OFFSHORE" polygon).
//
// This module flags those (source, status) tuples so the frontend can render
// them in a muted style and label them honestly in the panel. The backend
// stores them as-is — re-categorisation happens client-side.
//
// To extend: add a tuple to ZONE_RULES and a label below.

const ZONE_RULES: ReadonlyArray<readonly [string, string]> = [
  ["anh_co",  "sin asignar"],      // Colombia: "available" — not a concession
  ["anh_co",  "ambiental"],         // Colombia: environmental zone
  ["pasa",    "available_block"],   // South Africa: open for licensing
  // EMODnet 'planned' / 'other' previously listed here turned out to be real
  // concessions (344 planned wind farms, 21 oil/gas 'other'), not zone
  // metadata. Removed Apr 2026 — keep in sync with backend _ZONE_TUPLES.
] as const;

export function isZoneClassification(source: string, status: string): boolean {
  return ZONE_RULES.some(([s, st]) => s === source && st === status);
}

export function zoneLabelFor(source: string, status: string): string | null {
  if (source === "anh_co" && status === "sin asignar")     return "Available zone (Colombia)";
  if (source === "anh_co" && status === "ambiental")        return "Environmental zone (Colombia)";
  if (source === "pasa"   && status === "available_block")  return "Available block (South Africa)";
  return null;
}
