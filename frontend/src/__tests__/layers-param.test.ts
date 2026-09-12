// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// A link either says something we understand, or it says nothing.
//
// `?layers=` used to validate against `LAYER_CONFIGS` and silently drop every
// token that missed. Two separate defects came out of that on 2026-09-12:
//
//  - `LAYER_CONFIGS` holds 38 of the 44 sea layers, so `?layers=wod-oxygen`
//    named a real, served layer and was discarded as if it were a typo;
//  - discarding is itself wrong. A partly-understood link applied the surviving
//    subset as though the author had chosen it, so a typo, a link from a newer
//    release, and a validation bug all produced the same silent wrong answer.
//
// ⛔ The asymmetry in the last two describes is deliberate and is the whole
// design: input from outside is rejected whole; our own saved state is
// forgiving, because an unknown id there means "a layer we retired", not
// "someone typed this wrong".
import { describe, it, expect } from "vitest";

import { parseLayersParam, _VALID_LAYER_ID_COUNT } from "../utils/layersParam";
import { SEA_LAYER_IDS } from "../types/layers";
import { LAND_LAYER_IDS } from "../types/landLayers";

describe("the valid-id set covers every layer, not a subset of them", () => {
  it("holds all sea and land ids", () => {
    // ⛔ Anchored on the real registries rather than a number typed here, so the
    // check keeps meaning something when a layer ships.
    expect(_VALID_LAYER_ID_COUNT).toBe(SEA_LAYER_IDS.length + LAND_LAYER_IDS.length);
  });

  it("accepts the six layers the old LAYER_CONFIGS-based check dropped", () => {
    for (const id of [
      "wod-oxygen", "geotraces", "oxygen-deox",
      "ocean-acidification", "sios-svalbard", "arctic-catchments",
    ]) {
      expect(parseLayersParam(id), `${id} must be nameable in a link`).toEqual([id]);
    }
  });
});

describe("an unknown token rejects the whole list", () => {
  it("returns null rather than the surviving subset", () => {
    expect(parseLayersParam("contracts,not-a-layer")).toBeNull();
  });

  it("rejects even when the unknown token is last and everything else is real", () => {
    expect(parseLayersParam("contracts,argo,seamounts,typo")).toBeNull();
  });

  it("still accepts a list where every token is real", () => {
    expect(parseLayersParam("contracts,argo")).toEqual(["contracts", "argo"]);
  });
});

describe("nothing to act on", () => {
  it("ignores an absent or empty parameter", () => {
    expect(parseLayersParam(null)).toBeNull();
    expect(parseLayersParam("")).toBeNull();
    expect(parseLayersParam(",, ,")).toBeNull();
  });

  it("tolerates whitespace around real ids", () => {
    expect(parseLayersParam(" contracts , argo ")).toEqual(["contracts", "argo"]);
  });

  it("discards an over-long value before doing any work", () => {
    expect(parseLayersParam("contracts,".repeat(400))).toBeNull();
  });
});
