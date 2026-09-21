// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

/**
 * `status` on a hydrothermal-vent feature is InterRidge's own Activity value,
 * served VERBATIM since 2026-09-21: "active, confirmed" | "active, inferred" |
 * "inactive" | null (source left it blank). The platform no longer invents
 * "Active"/"Inactive"/"Extinct" — those words do not exist in the source.
 *
 * ⛔ Every place that routes a vent to the "-active" vs "-inactive" deck
 * layer MUST go through this helper, not a lookup keyed on an exact word —
 * a future InterRidge wording change (or a differently-worded confirmed/
 * inferred split) must degrade to "inactive", never throw or silently miss.
 */
export function isActiveVentStatus(status: unknown): boolean {
  return String(status ?? "").startsWith("active");
}

/**
 * Within "active" vents, whether venting was directly observed ("active,
 * confirmed") vs deduced from a plume or chemical anomaly ("active,
 * inferred"). 54% of what the platform used to lump into one word "Active"
 * was inferred, not observed — this is the split that must stay visible.
 */
export function isConfirmedVentStatus(status: unknown): boolean {
  return String(status ?? "").includes("confirmed");
}
