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
 * Stage 1 covers the five layers `?focus=` already proves: anything else is
 * refused here rather than emitted into a link the reader cannot honour.
 */
import type { Feature, FeatureCollection } from "geojson";

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

interface OpenableLayer {
  /**
   * Properties that may hold the identifier a link carries, in priority order.
   *
   * ⛔ A LIST, not one name, because the write side and the read side must agree
   * and they reach the id by different routes. The store takes whatever the
   * click path put in `SelectedFeature.id`; `?focus=vent:<name>` and the SEO
   * "View on map" buttons carry a NAME. Vents have both `id` and `name`, and a
   * single-property lookup made a link built from the search bar (which emits
   * `id`) unresolvable — the panel never opened and only the new notice
   * revealed it. Measured against live data on 2026-09-14.
   */
  idProps: readonly string[];
  /** Chosen once the feature is in hand — see the module note. */
  routingKey: (properties: Record<string, unknown>) => string;
  /**
   * Every key `routingKey` can return. Needed for the WRITE direction: the
   * store holds the routing key, a link must carry the public layer id.
   * ⚠️ Two lists that must agree; `open-from-link.test.ts` pins them together
   * so a new branch in `routingKey` cannot be forgotten here.
   */
  routingKeys: readonly string[];
  zoom: number;
}

/**
 * ⛔ Stage 1 only. Adding a layer here without checking that `DetailPanel`
 * has a branch for the routing key produces a link that opens nothing and
 * blames the data. Every key below was verified against `DetailPanel.tsx`
 * on 2026-09-14 — exactly one branch each.
 */
export const STAGE1_OPENABLE: Record<string, OpenableLayer> = {
  "contracts": {
    idProps: ["isa_id"],
    routingKey: () => "mining-contracts-mvt",
    routingKeys: ["mining-contracts-mvt"],
    zoom: 6,
  },
  "hydrothermal-vents": {
    idProps: ["id", "name"],
    // The one value-dependent case, and the reason the routing key cannot be
    // decided before the lookup: the two panels render differently.
    routingKey: (p) => (p.status === "Active" ? "hydrothermal-vents-active" : "hydrothermal-vents-inactive"),
    routingKeys: ["hydrothermal-vents-active", "hydrothermal-vents-inactive"],
    zoom: 8,
  },
  "argo": {
    idProps: ["platform_id"],
    routingKey: () => "argo-floats-3d",
    routingKeys: ["argo-floats-3d"],
    zoom: 7,
  },
  "chess": {
    idProps: ["locality"],
    routingKey: () => "chess",
    routingKeys: ["chess"],
    zoom: 7,
  },
  "seamounts": {
    idProps: ["peak_id"],
    routingKey: () => "seamounts",
    routingKeys: ["seamounts"],
    zoom: 7,
  },
};

/** The layer ids a link may carry today. Used on the WRITE side too. */
export const OPENABLE_LAYER_IDS: readonly string[] = Object.keys(STAGE1_OPENABLE);

export function isOpenableLayer(layerId: string): boolean {
  return layerId in STAGE1_OPENABLE;
}

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
  const cfg = STAGE1_OPENABLE[layerId];
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
  Object.entries(STAGE1_OPENABLE).flatMap(([layerId, cfg]) =>
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

