// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// The asymmetry that is the whole point of this design (see
// layers-param.test.ts's header comment): an unknown layer id in a URL is
// hostile input and rejects everything it's part of. The SAME unknown id read
// back from our own localStorage means "a layer we retired since this
// visitor's last save" and must be filtered out quietly, not used to reject
// the whole saved view (which would also throw away the visitor's camera).
import { describe, it, expect, beforeEach } from "vitest";

import { loadMapState, saveMapState } from "../utils/mapState";
import { SEA_LAYER_IDS } from "../types/layers";

const MAP_STATE_KEY = "abyssal_map_state";

beforeEach(() => {
  localStorage.clear();
});

describe("loadMapState drops retired layer ids", () => {
  it("filters an unknown id out of activeLayers and knownLayers, keeps the camera", () => {
    localStorage.setItem(MAP_STATE_KEY, JSON.stringify({
      viewState: { longitude: 1, latitude: 2, zoom: 5, pitch: 45, bearing: 0 },
      activeLayers: [SEA_LAYER_IDS[0], "a-retired-layer-id"],
      knownLayers: [SEA_LAYER_IDS[0], "another-retired-id"],
    }));
    const loaded = loadMapState();
    expect(loaded).not.toBeNull();
    expect(loaded!.viewState.longitude).toBe(1);
    expect(loaded!.activeLayers).toEqual([SEA_LAYER_IDS[0]]);
    expect(loaded!.knownLayers).toEqual([SEA_LAYER_IDS[0]]);
  });

  it("a save containing only real ids round-trips unchanged", () => {
    saveMapState(
      { longitude: 1, latitude: 2, zoom: 5, pitch: 45, bearing: 0 },
      new Set([SEA_LAYER_IDS[0], SEA_LAYER_IDS[1]]),
      [SEA_LAYER_IDS[0], SEA_LAYER_IDS[1]],
    );
    const loaded = loadMapState();
    expect(new Set(loaded!.activeLayers)).toEqual(new Set([SEA_LAYER_IDS[0], SEA_LAYER_IDS[1]]));
  });
});
