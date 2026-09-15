// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

/**
 * Which layers a link's panels need switched on — and, crucially, WHAT SET
 * those additions are merged onto.
 *
 * ⛔ The base set is the whole point of this file. The logic used to live
 * inline in a `useEffect` and merged onto `activeLayers`, the React state
 * captured in that effect's closure. That value is one render behind the
 * layer restore in the mount effect, so a link carrying BOTH a layer list and
 * a panel overwrote its own layer list with a stale snapshot plus the panel's
 * own layer.
 *
 * Measured on production 2026-09-15: a link with `l:["ocean-carbon",
 * "ocean-co2-surface"]` and one `ocean-carbon` point opened with exactly
 * `["ocean-carbon"]` active. The second layer was dropped silently — no
 * notice, no console error — and the live address writer then re-encoded the
 * loss, so the recipient could not even pass the original link on.
 *
 * Pulled out here so the base set is an argument a test can control, rather
 * than a closure variable no test can reach.
 */

/** A link entry whose first element is the public layer id. */
type LayerEntry = readonly [string, ...unknown[]];

/**
 * The set to hand `setActiveLayers`, or null when nothing needs switching on.
 *
 * ⛔ Returns null rather than an equal set when there is nothing to add: the
 * caller uses that to decide whether to write to the store at all, and an
 * unconditional write re-runs the effect that called it.
 */
export function nextActiveForLink(
  base: ReadonlySet<string>,
  wanted: readonly LayerEntry[],
  wantedPoints: readonly LayerEntry[],
  isOpenable: (layerId: string) => boolean,
  isPoint: (layerId: string) => boolean,
): Set<string> | null {
  const needed = [
    ...wanted.filter(([layerId]) => isOpenable(layerId)).map(([l]) => l),
    ...wantedPoints.filter(([layerId]) => isPoint(layerId)).map(([l]) => l),
  ].filter((l) => !base.has(l));

  if (needed.length === 0) return null;

  // ⛔ Merge, never replace. Every layer already on stays on — the link's own
  // list, the reader's restored session, anything a previous pass added.
  const next = new Set(base);
  for (const l of needed) next.add(l);
  return next;
}

/**
 * What a layer with no client-side copy puts in `searchDataRef`.
 *
 * ⛔ NOT `null`. Everywhere else in the map `null` means "the fetch has not
 * landed yet", and the link's panel opener waits on exactly that before
 * deciding an object is missing. Three MVT-only layers — `memento`,
 * `geotraces` and `mosaic-sediment` — stored a literal `null` that would never
 * be replaced, so a link naming one of them waited forever: no panel, no
 * `/by-id` request, and no failure notice either, because the wait happens
 * before the code that reports one. Verified on the dev deployment
 * 2026-09-15: nine tile requests, zero `by-id` requests, zero notices.
 *
 * An empty collection says the true thing — "there is a copy and it holds
 * nothing" — which sends the resolver straight to `/by-id`, and leaves the
 * search bar's `!fc?.features` check behaving exactly as before.
 */
export const NO_CLIENT_COPY = Object.freeze({
  type: "FeatureCollection",
  features: [],
}) as unknown as import("geojson").FeatureCollection;
