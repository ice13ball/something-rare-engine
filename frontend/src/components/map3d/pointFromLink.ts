// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

/**
 * Turns a coordinate from a share link into an open panel, and back.
 *
 * ⛔ Separate from `openFromLink.ts` on purpose. That one looks a record up and
 * can fail to find it; this one cannot — a spot on a continuous field always
 * exists, and "no measurement here" is a sentence the panel itself already
 * says correctly. The only failure this module has is a layer that is not
 * addressable by coordinate at all, and that is decided here rather than
 * during parsing so the reader can be told.
 *
 * ⭐ Nothing here moves the camera. A link already carries the sender's exact
 * framing in `c`, and a field layer has no natural landing zoom to fly to —
 * inventing one would overwrite what the sender chose with a guess.
 */
import { POINT_LOOKUP } from "../../types/pointRegistry";

/** What the caller needs to put a point panel on screen. */
export interface PointTarget {
  /** The string `DetailPanel` dispatches on. */
  routingKey: string;
  /** Byte-identical to the id a click on the same spot produces. */
  id: string;
  properties: Record<string, unknown>;
}

export function isPointLayer(layerId: string): boolean {
  return layerId in POINT_LOOKUP;
}

/**
 * Rebuild the selection a click on this spot would have made.
 *
 * Returns null when the layer cannot be addressed by coordinate, or when the
 * link omits a selector value the panel needs. ⛔ Both are failures the caller
 * must REPORT: a panel opened without its depth would query `depth=undefined`
 * and render the ordinary "No data found." message, which is a wrong answer
 * that looks like an empty one.
 */
export function pointTargetFor(
  layerId: string,
  lon: number,
  lat: number,
  extra: number | undefined,
): PointTarget | null {
  const cfg = POINT_LOOKUP[layerId];
  if (!cfg) return null;
  if (cfg.extra === null && extra !== undefined) return null;
  if (cfg.extra !== null && extra === undefined) return null;

  // ⛔ `<lat>,<lon>`, in that order, and never rounded. This string is compared
  // against the one `Map3D`'s click handler builds — matching it exactly is
  // what stops a link-opened panel and a clicked panel from stacking as two
  // panels for one spot. JSON round-trips a double exactly, so carrying the
  // raw number costs a few characters and removes rounding as a failure mode
  // entirely.
  const id = cfg.extra === null
    ? `${cfg.idPrefix}:${lat},${lon}`
    : `${cfg.idPrefix}:${lat},${lon},${extra}`;

  const properties: Record<string, unknown> = { _lat: lat, _lon: lon };
  if (cfg.extra !== null) properties[cfg.extra] = extra;

  return { routingKey: cfg.routingKey, id, properties };
}

/**
 * Open point panels, as the tuples a link carries.
 *
 * ⛔ A panel whose selection is missing a coordinate, or whose layer needs a
 * selector the selection does not carry, is DROPPED here at WRITE time. The
 * alternative is emitting a well-formed link that is guaranteed to fail — and
 * links travel: it would be in someone else's inbox long before anyone noticed.
 */
export function pointObjectsFor(
  selected: ReadonlyArray<{ layer: string; properties: Record<string, unknown> }>,
): Array<[string, number, number, number?]> {
  const out: Array<[string, number, number, number?]> = [];
  for (const f of selected) {
    // The registry is keyed by layer id; for these nine the routing key is the
    // same string, but the lookup goes through `routingKey` so that a future
    // divergence is a miss here rather than a wrong entry in someone's link.
    const hit = Object.entries(POINT_LOOKUP).find(([, cfg]) => cfg.routingKey === f.layer);
    if (!hit) continue;
    const [layerId, cfg] = hit;

    const lon = f.properties?._lon;
    const lat = f.properties?._lat;
    if (typeof lon !== "number" || !Number.isFinite(lon)) continue;
    if (typeof lat !== "number" || !Number.isFinite(lat)) continue;

    if (cfg.extra === null) {
      out.push([layerId, lon, lat]);
      continue;
    }
    const extra = f.properties?.[cfg.extra];
    if (typeof extra !== "number" || !Number.isFinite(extra)) continue;
    out.push([layerId, lon, lat, extra]);
  }
  return out;
}
