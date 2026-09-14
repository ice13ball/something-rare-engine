// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

/**
 * Turns `[public layer id, feature id]` from a share link into everything
 * needed to open that feature's panel — without importing deck.gl, so it can
 * be tested directly (same reasoning as shareBootstrap.ts).
 *
 * ⛔ Two namespaces meet here and they are NOT the same. A link carries the
 * PUBLIC layer id (`hydrothermal-vents`), because an address someone keeps for
 * months must not depend on the name of a variable in our code. `DetailPanel`
 * dispatches on a private routing key (`hydrothermal-vents-active`), 24 of
 * which differ from any layer id. The bridge works because the routing key is
 * chosen AFTER the feature is found — so the resolver has the properties in
 * hand, exactly as `SearchBar`'s `DECK_LAYER_ID[id]?.(properties)` does today.
 *
 * Which layers may be carried, and how each one is found, lives in
 * `types/openableRegistry.ts` — where a compile-time guard forces every layer
 * to be either wired or opted out with a reason. Anything not wired is refused
 * here rather than emitted into a link the reader cannot honour.
 */
import type { Feature, FeatureCollection } from "geojson";

import { OPENABLE, OPENABLE_LOOKUP } from "../../types/openableRegistry";

/** What the caller needs to fly to a feature and open its panel. */
export interface OpenTarget {
  /** The string `DetailPanel` dispatches on — not the public layer id. */
  routingKey: string;
  id: string | number;
  properties: Record<string, unknown>;
  feature: Feature;
  /** Landing zoom, mirroring what `?focus=` uses for the same layer. */
  zoom: number;
}

/** The layer ids a link may carry. Used on the WRITE side too. */
export const OPENABLE_LAYER_IDS: readonly string[] = Object.keys(OPENABLE);

export function isOpenableLayer(layerId: string): boolean {
  return layerId in OPENABLE;
}

/** Re-exported so callers have one import for the whole subject. */
export { OPENABLE, OPENABLE_LOOKUP };

/**
 * Find the feature a link names. Returns null when the layer is not openable,
 * the data has not arrived, or nothing matches — the caller must treat null as
 * "say so", never as "do nothing".
 *
 * ⚠️ Matching is exact (case-insensitive). `searchById` uses a substring match
 * because a human is typing there; a link is machine-generated, and a
 * substring match would let one link open a different vent than the sender saw.
 */
export function resolveOpenTarget(
  layerId: string,
  featureId: string,
  collection: FeatureCollection | null | undefined,
): OpenTarget | null {
  const cfg = OPENABLE_LOOKUP[layerId];
  if (!cfg || !collection?.features?.length) return null;

  const wanted = featureId.trim().toLowerCase();
  if (!wanted) return null;

  // Try each candidate property in turn, so a link built from the search bar
  // (which carries `id`) and one built from an SEO page (which carries `name`)
  // both land on the same feature.
  let matchedProp: string | null = null;
  const feature = collection.features.find((f) => {
    const props = f.properties as Record<string, unknown> | null;
    for (const prop of cfg.idProps) {
      const raw = props?.[prop];
      if (raw != null && String(raw).trim().toLowerCase() === wanted) {
        matchedProp = prop;
        return true;
      }
    }
    return false;
  });
  if (!feature || !matchedProp) return null;

  const properties = (feature.properties ?? {}) as Record<string, unknown>;
  return {
    routingKey: cfg.routingKey(properties),
    // ⛔ The id handed to the store must be the value the panel and the store's
    // own dedup expect — the raw property, not the lower-cased search key.
    id: (properties[matchedProp] as string | number) ?? featureId,
    properties,
    feature,
    zoom: cfg.zoom,
  };
}

/**
 * Routing key → public layer id, for building a link from what the store holds.
 *
 * ⛔ `SelectedFeature.layer` is the routing key, not the layer id. Writing it
 * into a URL verbatim would put a private name in an address someone keeps for
 * months — and `argo-floats-3d` is not a thing anyone can look up.
 */
const ROUTING_KEY_TO_LAYER: Record<string, string> = Object.fromEntries(
  Object.entries(OPENABLE_LOOKUP).flatMap(([layerId, cfg]) =>
    cfg.routingKeys.map((k) => [k, layerId] as const),
  ),
);

/** Null when this panel is not one a stage-1 link may carry. */
export function layerIdForRoutingKey(routingKey: string): string | null {
  return ROUTING_KEY_TO_LAYER[routingKey] ?? null;
}

/**
 * Open panels, as `[public layer id, feature id]`.
 *
 * ⛔ A panel whose routing key is not one a link may carry is DROPPED at write
 * time, not just refused at read time. Emitting it would produce a link that
 * is well-formed and still fails — and links travel: it would be in someone
 * else's inbox long before the layer became openable.
 */
export function openObjectsFor(
  selected: ReadonlyArray<{ id: string | number; layer: string }>,
): Array<[string, string]> {
  const out: Array<[string, string]> = [];
  for (const f of selected) {
    const layerId = layerIdForRoutingKey(f.layer);
    if (!layerId) continue;
    out.push([layerId, String(f.id)]);
  }
  return out;
}

/**
 * Ask the server for one feature of a tiled layer.
 *
 * ⛔ Tried only AFTER the client-held collection, never instead of it. `/by-id`
 * supplements a tile, it does not reproduce one: `PermafrostThawPanel` renders
 * category, type and site name straight from the tile's properties and the
 * endpoint returns none of them. Preferring the network would open a panel
 * poorer than a click produces — and say nothing about the difference.
 *
 * Returns null on any failure. The caller must report a null, not swallow it.
 */
export async function fetchOpenTarget(
  layerId: string,
  featureId: string,
  api: string,
  signal?: AbortSignal,
): Promise<OpenTarget | null> {
  const cfg = OPENABLE_LOOKUP[layerId];
  if (!cfg?.byIdPath) return null;
  try {
    const r = await fetch(`${api}${cfg.byIdPath}${encodeURIComponent(featureId)}`, { signal });
    if (!r.ok) return null;
    const body = await r.json();
    // The endpoints answer either a bare object or a GeoJSON Feature.
    const feature = (body?.type === "Feature" ? body : null) as Feature | null;
    const properties = (feature?.properties ?? body ?? {}) as Record<string, unknown>;
    if (Object.keys(properties).length === 0) return null;
    return {
      routingKey: cfg.routingKey(properties),
      id: featureId,
      properties,
      feature: feature ?? ({ type: "Feature", geometry: null, properties } as unknown as Feature),
      zoom: cfg.zoom,
    };
  } catch {
    return null;
  }
}

/**
 * The whole lookup, in the order that matters: what the client already holds,
 * and only then the network.
 *
 * ⛔ Reversing these two compiles, passes a smoke test, and quietly opens a
 * poorer panel than a click does — `/by-id` supplements a tile rather than
 * reproducing it. Exists as one function so that ordering can be sabotaged in
 * a test instead of living inside a React effect nothing can reach.
 */
export async function openTargetFor(
  layerId: string,
  featureId: string,
  collection: FeatureCollection | null | undefined,
  api: string,
  signal?: AbortSignal,
): Promise<OpenTarget | null> {
  return (
    resolveOpenTarget(layerId, featureId, collection) ??
    (await fetchOpenTarget(layerId, featureId, api, signal))
  );
}

