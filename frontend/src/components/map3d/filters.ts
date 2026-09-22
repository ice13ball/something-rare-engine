// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

/**
 * Layer filter predicates.
 *
 * ⚠️ The project-wide convention lives here: an EMPTY Set means SHOW ALL, so
 * this returns `undefined` (no filter) rather than a predicate that rejects
 * everything. Getting that backwards blanks a layer instead of unfiltering it.
 */
/** Returns a filter predicate for features whose `properties[propKey]` is in the Set.
 *  Returns undefined when the Set is empty (= show all features). */
export function makeSetFilter(filterSet: Set<string>, propKey: string): ((f: { properties?: Record<string, unknown> | null }) => boolean) | undefined {
  if (!filterSet.size) return undefined;
  return (f) => filterSet.has(f.properties?.[propKey] as string);
}

/**
 * ONC EOV filter rule — explicit handling for categories the bucket map
 * doesn't know about yet.
 *
 * ~1,993 ONC locations now span ~129 device categories from two independent
 * naming sources (see types/onc.ts). ONC_EOV_CATEGORIES only ever covers a
 * curated subset. The failure mode this guards against: a location whose
 * only category is one we haven't bucketed yet would match nothing in
 * `allowed` and DISAPPEAR the instant any EOV filter is turned on — with no
 * error, indistinguishable from "this location has no matching sensor".
 *
 * Chosen rule: an unclassified category (present in the feature's
 * `device_categories` but absent from every bucket in ONC_EOV_CATEGORIES)
 * always keeps the location visible, even while a filter is active. A
 * location whose categories are ALL known-but-unselected is correctly
 * hidden. A location with zero categories is treated as unclassified
 * (visible) rather than excluded, for the same reason.
 */
/**
 * Tailings hazard-rating filter. `hazard_raw` is the operator's own rating
 * string (120 distinct values on production); the filter chips only cover
 * the six most common (`knownValues`) plus an "other" bucket for every other
 * non-null value.
 *
 * A row with NO rating (`hazard_raw` null) is always visible, filter active
 * or not — a missing rating is not a statement that the dam is safe, and
 * there is no invented "Unclassified" bucket to opt into any more (that
 * concept belonged to the deleted `risk_class` scoring).
 */
export function tailingsHazardVisible(
  hazardRaw: string | null | undefined,
  filterSet: Set<string>,
  knownValues: readonly string[],
): boolean {
  if (filterSet.size === 0) return true;
  if (hazardRaw == null) return true;
  if (filterSet.has(hazardRaw)) return true;
  if (filterSet.has("other") && !knownValues.includes(hazardRaw)) return true;
  return false;
}

export function oncEovVisible(
  deviceCategories: readonly string[] | null | undefined,
  allowed: Set<string> | null,
  knownCategories: Set<string>,
): boolean {
  if (!allowed) return true; // no filter active
  const cats = deviceCategories ?? [];
  if (cats.length === 0) return true; // no category data — never silently hide
  if (cats.some((c) => allowed.has(c))) return true;
  return cats.some((c) => !knownCategories.has(c)); // unclassified — show, don't vanish
}
