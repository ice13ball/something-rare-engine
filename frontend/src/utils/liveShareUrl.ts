// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

/**
 * Decide what a LIVE share URL (the address bar itself, updated as the user
 * moves the map) can afford to carry, given `MAX_PARAM_LENGTH`.
 *
 * Why filters are the thing that gets dropped, not layers or camera:
 * measured encoded `?s=` lengths (see the caller's brief, verified today) —
 * all 57 layers with zero filters encode to 1302 chars, comfortably under the
 * 4000 cap, while all layers plus all 33 filter groups at ~5 values each
 * reach 4832 — OVER the cap. So camera + layers alone essentially always fit;
 * only filters, which have no upper bound on how many values a user can pile
 * into a group, can push the total over the line. Layers already have a hard
 * ceiling (the fixed set of real layer ids) and the camera is five numbers —
 * neither can grow the way filters can.
 *
 * Why an overflow drops ALL filters rather than trimming them down to fit:
 * a URL that silently carries SOME of the sender's filters shows MORE data
 * than the sender meant and looks deliberate — the reader has no way to tell
 * "this is the exact view" from "this is a view with some filters quietly
 * removed". Dropping everything at once is visibly a reduction; dropping
 * some of them is a silent corruption of meaning. All filters or none.
 */

import { encodeShareState, MAX_PARAM_LENGTH } from "./shareState";
import type { LayerId } from "../types/layers";

export type LiveShareParam = {
  /** The `s` value to put in the URL, or null if even camera+layers won't fit. */
  param: string | null;
  /**
   * What had to be left out to fit, in the order things are given up.
   * ⚠️ "objects" covers both kinds a link can point at — records (`o`) and
   * spots on a field (`p`). They are given up together: keeping one kind and
   * dropping the other would show the reader a subset that looks deliberate.
   */
  dropped: "nothing" | "filters" | "filters+objects";
};

export function liveShareParam(state: {
  camera: { longitude: number; latitude: number; zoom: number; pitch: number; bearing: number };
  layers: readonly string[];
  filters: Record<string, string[]>;
  /** `[public layer id, feature id]` for each open record panel. */
  openObjects: ReadonlyArray<[string, string]>;
  /** `[public layer id, lon, lat, selector?]` for each open field panel. */
  points: ReadonlyArray<readonly [string, number, number, number?]>;
  /**
   * Per-layer display selectors that differ from their defaults.
   *
   * ⛔ Never dropped, and deliberately not given a rung below. These decide
   * WHICH DATA a layer draws — a link that gave up the sender's depth would
   * render the recipient a different measurement under the sender's camera and
   * look completely normal. They are also bounded and small (32 short keys,
   * only the changed ones emitted), so they cannot be the cause of an overflow.
   */
  display: Record<string, string | number | boolean>;
}): LiveShareParam {
  const layers = [...state.layers] as LayerId[];
  const openObjects = state.openObjects.map(([l, i]) => [l, i] as [string, string]);
  const points = state.points;
  const display = state.display;

  const full = encodeShareState({ camera: state.camera, layers, filters: state.filters, openObjects, points, display });
  if (full.length <= MAX_PARAM_LENGTH) {
    return { param: full, dropped: "nothing" };
  }

  // Filters go first, as a whole. Never a partial filter set: see the module
  // docstring. Objects survive this step because they are what the sender
  // pointed at — a filter can be re-applied by hand, the object they meant
  // cannot be guessed.
  const noFilters = encodeShareState({ camera: state.camera, layers, filters: {}, openObjects, points, display });
  if (noFilters.length <= MAX_PARAM_LENGTH) {
    return { param: noFilters, dropped: "filters" };
  }

  // Objects next, also as a whole. A partial set would open some of what the
  // sender had and look deliberate.
  const bare = encodeShareState({ camera: state.camera, layers, filters: {}, openObjects: [], points: [], display });
  if (bare.length <= MAX_PARAM_LENGTH) {
    return { param: bare, dropped: "filters+objects" };
  }

  // Measured today: camera + all 57 layers alone is 1302 chars, well under
  // the 4000 cap, so this branch should be unreachable in practice. Guard it
  // anyway rather than assume — emitting an oversized URL would just hand
  // `decodeShareState` a value it rejects on arrival.
  return { param: null, dropped: "filters+objects" };
}
