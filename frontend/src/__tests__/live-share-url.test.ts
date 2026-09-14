// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// The live share URL (the address bar itself) re-encodes on every camera
// move. Camera + layers essentially always fit under MAX_PARAM_LENGTH
// (measured: all 57 layers, zero filters = 1302 chars); only filters, whose
// value counts have no upper bound, can push the total over the 4000 cap
// (measured: all layers + all 33 filter groups x5 values = 4832). So an
// overflow must drop ALL filters, never a partial subset — a URL carrying
// SOME of the sender's filters shows MORE data than intended and looks
// deliberate, which is worse than a visibly reduced link.
import { describe, it, expect } from "vitest";

import { liveShareParam } from "../utils/liveShareUrl";
import { decodeShareState, encodeShareState, MAX_PARAM_LENGTH } from "../utils/shareState";
import { VALID_LAYER_IDS } from "../utils/layersParam";
import { SHAREABLE_FILTER_FIELDS } from "../types/filterRegistry";

const CAMERA = { longitude: 12.34, latitude: -56.78, zoom: 4.2, pitch: 30, bearing: 15 };
const ALL_LAYERS = [...VALID_LAYER_IDS];

/** All 33 shareable filter groups, each with 5 values — big enough to push
 * the encoded payload past MAX_PARAM_LENGTH (measured: 4832 chars). Built
 * programmatically rather than pasted so it tracks the real filter registry. */
function heavyFilters(): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const key of SHAREABLE_FILTER_FIELDS) {
    out[key] = Array.from({ length: 5 }, (_, i) => `${key}-value-${i}`);
  }
  return out;
}

describe("a small state round-trips unchanged", () => {
  it("keeps camera, layers and filters, and reports nothing dropped", () => {
    const state = {
      camera: CAMERA,
      layers: ["contracts", "argo"],
      filters: { hiddenContractors: ["acme"] },
    };

    const result = liveShareParam(state);
    expect(result.dropped).toBe("nothing");
    expect(result.param).not.toBeNull();

    const decoded = decodeShareState(result.param);
    expect(decoded).not.toBeNull();
    expect(decoded!.camera).toEqual(CAMERA);
    expect(decoded!.layers).toEqual(["contracts", "argo"]);
    expect(decoded!.filters).toEqual({ hiddenContractors: ["acme"] });
  });
});

describe("overflow drops filters wholesale, keeps camera and layers", () => {
  const heavy = heavyFilters();
  const state = { camera: CAMERA, layers: ALL_LAYERS, filters: heavy };

  it("has a non-empty layer list and a non-empty filter set to begin with", () => {
    // ⛔ An empty comparison is not evidence — prove both sides are real
    // before trusting anything derived from them.
    expect(ALL_LAYERS.length).toBeGreaterThan(0);
    expect(Object.keys(heavy).length).toBeGreaterThan(0);
  });

  it("positive control: the same state WITH filters would exceed the cap", () => {
    const withFilters = encodeShareState({ camera: CAMERA, layers: ALL_LAYERS as never, filters: heavy });
    expect(withFilters.length).toBeGreaterThan(MAX_PARAM_LENGTH);
  });

  it("reports dropped filters and returns a usable param", () => {
    const result = liveShareParam(state);
    expect(result.dropped).toBe("filters");
    expect(result.param).not.toBeNull();
  });

  it("keeps the full camera and the full layer list, and carries no filters", () => {
    const result = liveShareParam(state);
    const decoded = decodeShareState(result.param);
    expect(decoded).not.toBeNull();
    expect(decoded!.camera).toEqual(CAMERA);
    expect(decoded!.layers).not.toBeNull();
    expect(decoded!.layers!.length).toBe(ALL_LAYERS.length);
    expect(new Set(decoded!.layers!)).toEqual(new Set(ALL_LAYERS));
    expect(decoded!.filters).toBeNull();
  });
});

describe("the returned param always decodes", () => {
  it("is accepted by decodeShareState for the small state", () => {
    const result = liveShareParam({
      camera: CAMERA,
      layers: ["contracts"],
      filters: {},
    });
    expect(decodeShareState(result.param)).not.toBeNull();
  });

  it("is accepted by decodeShareState for the overflowed state", () => {
    const result = liveShareParam({ camera: CAMERA, layers: ALL_LAYERS, filters: heavyFilters() });
    expect(result.param!.length).toBeLessThanOrEqual(MAX_PARAM_LENGTH);
    expect(decodeShareState(result.param)).not.toBeNull();
  });
});

describe("empty layers and empty filters still carry the camera", () => {
  it("encodes a param decodeShareState accepts, with a null layer list", () => {
    const result = liveShareParam({ camera: CAMERA, layers: [], filters: {} });
    expect(result.dropped).toBe("nothing");
    const decoded = decodeShareState(result.param);
    expect(decoded).not.toBeNull();
    expect(decoded!.camera).toEqual(CAMERA);
    expect(decoded!.layers).toBeNull();
    expect(decoded!.filters).toBeNull();
  });
});
