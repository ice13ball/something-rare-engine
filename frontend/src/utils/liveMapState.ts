// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import type { LayerId } from "../types/layers";

/**
 * The camera and active layers as they are RIGHT NOW, readable from outside the
 * map component.
 *
 * ⛔ Deliberately a plain module variable, not Zustand state and not React
 * context. The camera changes on every frame of a drag; putting it in the store
 * would re-render every subscriber continuously for the sake of one button that
 * reads it once, when clicked.
 *
 * ⛔ And deliberately not `loadMapState()` either. That value is written on a
 * debounce, so a share link built from it would carry wherever the map was a
 * moment ago — usually right, occasionally embarrassing, and never detectably
 * wrong to the person who sent it.
 *
 * `Map3D` already maintains exactly this pair in a ref for its unmount flush;
 * this is that same pair, published.
 */
let live: { viewState: Record<string, unknown>; activeLayers: Set<LayerId> } | null = null;

export function setLiveMapState(
  viewState: Record<string, unknown>,
  activeLayers: Set<LayerId>,
): void {
  live = { viewState, activeLayers };
}

export function getLiveMapState(): {
  viewState: Record<string, unknown>;
  activeLayers: Set<LayerId>;
} | null {
  return live;
}
