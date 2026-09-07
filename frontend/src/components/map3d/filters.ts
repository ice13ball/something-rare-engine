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
