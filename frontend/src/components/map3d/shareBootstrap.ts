// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

/**
 * Pure precedence rules for what the map opens showing, pulled out of
 * Map3D.tsx so they're testable without pulling in deck.gl/MapLibre (see
 * map3d-helpers.test.ts's note on why Map3D.tsx itself isn't imported from
 * tests).
 */
import type { LayerId } from "../../types/layers";
import type { ShareCamera } from "../../utils/shareState";
import type { PersistedViewState } from "../../utils/mapState";

interface FlyTarget { longitude: number; latitude: number; zoom: number }

/**
 * Camera precedence: `?fly=`/`?focus=` are "jump to this ONE feature" intent
 * (a report back-link) and outrank everything, including a share link's own
 * camera — a bookmarked whole-view is less specific than "show me this vent".
 * A share-link camera in turn outranks the visitor's own saved position,
 * because following a link is more specific intent than "resume where I left
 * off" — otherwise a shared link would never actually move the recipient.
 */
export function resolveInitialCamera(
  urlFly: FlyTarget | null,
  shareCamera: ShareCamera | null,
  saved: PersistedViewState | null,
): { longitude: number; latitude: number; zoom: number; pitch: number; bearing: number } {
  if (urlFly) return { ...urlFly, pitch: 45, bearing: 0 };
  if (shareCamera) return shareCamera;
  if (saved) return saved;
  return { longitude: -30, latitude: 20, zoom: 3, pitch: 45, bearing: 0 };
}

/**
 * Layer precedence: a share link naming layers is authoritative and must NOT
 * merge with the reader's saved preferences or the "auto-enable a layer
 * that's new since this visitor last saved" behaviour below — a link says
 * "show exactly this", and blending in whatever the recipient already had
 * open would make that promise false silently.
 *
 * With no share link, today's behaviour is preserved unchanged: restore the
 * saved active set, then auto-enable any `allLayerIds` entry NOT present in
 * `knownLayers` (a layer that shipped after this visitor's last save) —
 * except `seamounts`, which is opt-in only.
 */
export function resolveInitialLayers(
  // `layers` may be absent OR explicitly null — `decodeShareState` uses null for
  // "the payload carried no layer list", and both must mean the same thing here.
  share: { layers?: LayerId[] | null } | null,
  saved: { activeLayers: LayerId[]; knownLayers?: LayerId[] } | null,
  allLayerIds: readonly LayerId[],
): Set<LayerId> | null {
  // ⛔ Takes the whole share envelope, not just its layer list, because the two
  // cases it must tell apart look identical once the list is extracted:
  // "no link at all" and "a link that carries a camera but no layers". Passing
  // `share?.layers ?? null` collapsed them, and the second case then fell
  // through to the reader's own saved preferences — so opening someone else's
  // link quietly showed the recipient's layers under the sender's camera, which
  // is the one outcome requirement 3 exists to forbid.
  //
  // A link with no layer list therefore yields `null` = "start from the
  // defaults", the same as a first-time visitor. Never the reader's save.
  if (share) return share.layers ? new Set(share.layers) : null;
  if (!saved) return null;
  const active = new Set<LayerId>(saved.activeLayers);
  const known = new Set(saved.knownLayers ?? []);
  for (const id of allLayerIds) {
    if (!known.has(id) && id !== ("seamounts" as LayerId)) active.add(id);
  }
  return active;
}
