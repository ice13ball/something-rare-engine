// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// Coverage for the "points" field on the share-link envelope (`p`): a link
// can re-open a spot on a continuous field (WOA depth slice, VME suitability
// cell, ...). See shareState.ts `validatePoints` and pointFromLink.ts for the
// read/write halves this file exercises together.
import { describe, it, expect } from "vitest";

import { encodeShareState, decodeShareState, MAX_OPEN_OBJECTS } from "../utils/shareState";
import { pointTargetFor, pointObjectsFor, isPointLayer } from "../components/map3d/pointFromLink";
import { POINT_LAYERS, NOT_POINT } from "../types/pointRegistry";

const CAMERA = { longitude: 12.5, latitude: -3.25, zoom: 6, pitch: 45, bearing: 0 };

// Base64url <-> JSON helpers, same technique as share-open-objects.test.ts —
// decode an encoded envelope to plain JSON, tamper it by hand, then re-encode
// so decodeShareState sees exactly the malformed shape we intend.
function toEnvelope(encoded: string): any {
  const b64 = encoded.replace(/-/g, "+").replace(/_/g, "/");
  const padded = b64 + "=".repeat((4 - (b64.length % 4)) % 4);
  return JSON.parse(decodeURIComponent(escape(atob(padded))));
}

function fromEnvelope(payload: any): string {
  return btoa(unescape(encodeURIComponent(JSON.stringify(payload))))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

describe("round-trip", () => {
  // sabotaż: delete the `p` assignment in encodeShareState → ten test
  it("encodes and decodes one point with its depth", () => {
    const encoded = encodeShareState({
      camera: CAMERA,
      layers: [],
      filters: {},
      openObjects: [],
      points: [["ocean-carbon", -140.25, 12.5, 1000]],
      display: {},
    });
    const decoded = decodeShareState(encoded)!;
    expect(decoded.points).toEqual([["ocean-carbon", -140.25, 12.5, 1000]]);
  });
});

describe("exact precision", () => {
  // sabotaż: round the coordinate to 5 decimals anywhere on the path → ten test
  it("preserves full-precision coordinates, not just close ones", () => {
    const lon = -140.123456789012;
    const lat = 12.987654321098;
    const encoded = encodeShareState({
      camera: CAMERA,
      layers: [],
      filters: {},
      openObjects: [],
      points: [["ocean-carbon", lon, lat, 1000]],
      display: {},
    });
    const decoded = decodeShareState(encoded)!;
    const [, decodedLon, decodedLat] = decoded.points![0];
    expect(decodedLon === lon).toBe(true);
    expect(decodedLat === lat).toBe(true);
  });
});

describe("range check", () => {
  // sabotaż: remove the lat/lon range check in validatePoints → ten test
  it("drops an entry whose lat/lon were swapped and so is out of range", () => {
    const encoded = encodeShareState({
      camera: CAMERA,
      layers: [],
      filters: {},
      openObjects: [],
      // lon slot carries 12.5, lat slot carries -140.25 — out of range for a latitude.
      points: [["ocean-carbon", 12.5, -140.25, 1000]],
      display: {},
    });
    const decoded = decodeShareState(encoded)!;
    expect(decoded.points).toBeNull();
  });
});

describe("one bad entry does not cost the good ones", () => {
  // sabotaż: make validatePoints reject the whole list instead of the entry → ten test
  it("drops only the entry naming an unknown layer id", () => {
    const encoded = encodeShareState({
      camera: CAMERA,
      layers: [],
      filters: {},
      openObjects: [],
      points: [
        ["ocean-carbon", -140.25, 12.5, 1000],
        ["not-a-real-layer", 1, 2, 3],
        ["vme-suitability", -10, 20, undefined],
      ], display: {} });
    const decoded = decodeShareState(encoded)!;
    // Positive control: assert the survivors are non-empty AND are exactly
    // the right two, in order — "not null" alone would also pass if the
    // validator dropped everything, or kept the bad entry too.
    expect(decoded.points).not.toBeNull();
    expect(decoded.points!.length).toBe(2);
    expect(decoded.points).toEqual([
      ["ocean-carbon", -140.25, 12.5, 1000],
      ["vme-suitability", -10, 20],
    ]);
  });
});

describe("a corrupt `p` must not damage the other fields", () => {
  // sabotaż: make a bad `p` return null for the whole ShareState → ten test
  it("camera and layers still decode when every point entry is malformed", () => {
    const encoded = encodeShareState({
      camera: CAMERA,
      layers: ["contracts"] as any,
      filters: {},
      openObjects: [],
      points: [["ocean-carbon", -140.25, 12.5, 1000]],
      display: {},
    });
    const payload = toEnvelope(encoded);
    // Every entry in `p` is broken: bad layer id, then out-of-range lat/lon.
    payload.p = [["not-a-real-layer", 1, 2], ["ocean-carbon", 999, 999]];
    const tampered = fromEnvelope(payload);

    const decoded = decodeShareState(tampered)!;
    expect(decoded.camera).toEqual(CAMERA);
    expect(decoded.layers).toEqual(["contracts"]);
    expect(decoded.points).toBeNull();
  });
});

describe("the cap is joint with openObjects", () => {
  // sabotaž: give validatePoints its own independent cap of MAX_OPEN_OBJECTS → ten test
  it(`3 openObjects + 2 points leaves points null`, () => {
    const encoded = encodeShareState({
      camera: CAMERA,
      layers: [],
      filters: {},
      openObjects: [
        ["contracts", "feature-1"],
        ["contracts", "feature-2"],
        ["contracts", "feature-3"],
      ],
      points: [
        ["ocean-carbon", -140.25, 12.5, 1000],
        ["vme-suitability", -10, 20, undefined],
      ], display: {} });
    const decoded = decodeShareState(encoded)!;
    expect(decoded.openObjects).not.toBeNull();
    expect(decoded.openObjects!.length).toBe(MAX_OPEN_OBJECTS);
    expect(decoded.points).toBeNull();
  });

  it(`1 openObject + 3 points leaves ${MAX_OPEN_OBJECTS - 1} points`, () => {
    const encoded = encodeShareState({
      camera: CAMERA,
      layers: [],
      filters: {},
      openObjects: [["contracts", "feature-1"]],
      points: [
        ["ocean-carbon", -140.25, 12.5, 1000],
        ["vme-suitability", -10, 20, undefined],
        ["cumulative-human-impact", -50, 30, undefined],
      ], display: {} });
    const decoded = decodeShareState(encoded)!;
    expect(decoded.openObjects).not.toBeNull();
    expect(decoded.openObjects!.length).toBe(1);
    expect(decoded.points).not.toBeNull();
    expect(decoded.points!.length).toBe(MAX_OPEN_OBJECTS - 1);
    expect(decoded.points).toEqual([
      ["ocean-carbon", -140.25, 12.5, 1000],
      ["vme-suitability", -10, 20],
    ]);
  });
});

describe("duplicates collapse, extra keeps them apart", () => {
  // sabotaż: drop the extra from the dedup key → ten test
  it("the same spot named twice at the same depth yields one entry", () => {
    const encoded = encodeShareState({
      camera: CAMERA,
      layers: [],
      filters: {},
      openObjects: [],
      points: [
        ["ocean-carbon", -140.25, 12.5, 1000],
        ["ocean-carbon", -140.25, 12.5, 1000],
      ], display: {} });
    const decoded = decodeShareState(encoded)!;
    expect(decoded.points).not.toBeNull();
    expect(decoded.points).toEqual([["ocean-carbon", -140.25, 12.5, 1000]]);
  });

  it("the same spot at two different depths yields two entries", () => {
    const encoded = encodeShareState({
      camera: CAMERA,
      layers: [],
      filters: {},
      openObjects: [],
      points: [
        ["ocean-carbon", -140.25, 12.5, 0],
        ["ocean-carbon", -140.25, 12.5, 1000],
      ], display: {} });
    const decoded = decodeShareState(encoded)!;
    expect(decoded.points).not.toBeNull();
    expect(decoded.points!.length).toBe(2);
    expect(decoded.points).toEqual([
      ["ocean-carbon", -140.25, 12.5, 0],
      ["ocean-carbon", -140.25, 12.5, 1000],
    ]);
  });
});

describe("pointTargetFor selector guard", () => {
  // sabotaż: remove either of the two `extra` guards in pointTargetFor → ten test
  it("refuses a depth layer without its selector", () => {
    expect(pointTargetFor("ocean-carbon", 1, 2, undefined)).toBeNull();
  });

  it("refuses a selector-free layer given an unwanted extra", () => {
    expect(pointTargetFor("vme-suitability", 1, 2, 500)).toBeNull();
  });

  it("refuses a layer that is not point-addressable at all", () => {
    expect(pointTargetFor("contracts", 1, 2, undefined)).toBeNull();
  });
});

describe("pointTargetFor rebuilds the click id byte-identically", () => {
  // sabotaż: change idPrefix for vme-suitability to the layer id, or swap lat/lon in the id → ten test
  it("ocean-carbon: <layer>:<lat>,<lon>,<depth>", () => {
    expect(pointTargetFor("ocean-carbon", -140.25, 12.5, 1000)?.id).toBe(
      "ocean-carbon:12.5,-140.25,1000",
    );
  });

  it("vme-suitability: idPrefix 'vme', no selector", () => {
    expect(pointTargetFor("vme-suitability", -140.25, 12.5, undefined)?.id).toBe(
      "vme:12.5,-140.25",
    );
  });

  it("ocean-co2-surface: <layer>:<lat>,<lon>,<decade>", () => {
    expect(pointTargetFor("ocean-co2-surface", -140.25, 12.5, 5)?.id).toBe(
      "ocean-co2-surface:12.5,-140.25,5",
    );
  });

  // sabotaż: round the coordinate anywhere before the id is built → ten test
  //
  // ⛔ The clauses above all use coordinates that survive rounding unchanged,
  // so none of them can see a rounding step added to this path. Full precision
  // is the whole reason the id a link rebuilds still matches the id a click
  // produces: round it and the reader gets a SECOND panel for the same spot
  // the moment they click it, with nothing to explain why.
  it("keeps every digit — a rounded id no longer matches a clicked one", () => {
    const lon = -140.123456789012;
    const lat = 12.987654321098;
    expect(pointTargetFor("cumulative-human-impact", lon, lat, undefined)?.id).toBe(
      `cumulative-human-impact:${lat},${lon}`,
    );
    expect(pointTargetFor("ocean-carbon", lon, lat, 1000)?.id).toBe(
      `ocean-carbon:${lat},${lon},1000`,
    );
  });
});

describe("pointTargetFor rebuilds properties the panel reads", () => {
  // sabotaż: rename the properties key from the registry's `extra` to a hardcoded "depth" → ten test
  it("ocean-carbon carries _lat/_lon/depth", () => {
    expect(pointTargetFor("ocean-carbon", -140.25, 12.5, 1000)?.properties).toEqual({
      _lat: 12.5,
      _lon: -140.25,
      depth: 1000,
    });
  });

  it("ocean-co2-surface carries _lat/_lon/decade, not depth", () => {
    expect(pointTargetFor("ocean-co2-surface", -140.25, 12.5, 5)?.properties).toEqual({
      _lat: 12.5,
      _lon: -140.25,
      decade: 5,
    });
  });

  it("vme-suitability carries only _lat/_lon, no third key", () => {
    expect(pointTargetFor("vme-suitability", -140.25, 12.5, undefined)?.properties).toEqual({
      _lat: 12.5,
      _lon: -140.25,
    });
  });
});

describe("pointObjectsFor drops selections missing a required value", () => {
  // sabotaż: remove the finite-number checks in pointObjectsFor → ten test
  it("drops a selection missing _lon entirely", () => {
    expect(
      pointObjectsFor([{ layer: "ocean-carbon", properties: { _lat: 12.5 } }]),
    ).toEqual([]);
  });

  it("drops a selection with coordinates but no required depth", () => {
    expect(
      pointObjectsFor([
        { layer: "ocean-carbon", properties: { _lat: 12.5, _lon: -140.25 } },
      ]),
    ).toEqual([]);
  });

  it("keeps a selector-free layer needing only coordinates", () => {
    expect(
      pointObjectsFor([
        { layer: "vme-suitability", properties: { _lat: 12.5, _lon: -140.25 } },
      ]),
    ).toEqual([["vme-suitability", -140.25, 12.5]]);
  });

  // sabotaż: remove either finite-number check on the coordinate → ten test
  //
  // ⛔ The two "drops" clauses above both use `ocean-carbon`, whose missing
  // depth is refused first — so the coordinate checks were doing nothing that
  // any test could see. A layer with no selector is the only case that reaches
  // them. Without it a selection carrying a half-coordinate would be written
  // into someone's address bar as `[..., undefined, 12.5]`, which JSON turns
  // into null and the reader silently drops.
  it("drops a selector-free layer with only half a coordinate", () => {
    expect(
      pointObjectsFor([{ layer: "vme-suitability", properties: { _lat: 12.5 } }]),
    ).toEqual([]);
    expect(
      pointObjectsFor([{ layer: "vme-suitability", properties: { _lon: -140.25 } }]),
    ).toEqual([]);
    expect(
      pointObjectsFor([
        { layer: "cumulative-human-impact", properties: { _lat: 12.5, _lon: Number.NaN } },
      ]),
    ).toEqual([]);
  });
});

describe("pointObjectsFor ignores non-point panels", () => {
  // sabotaż: make pointObjectsFor fall back to the layer string when the registry misses → ten test
  it("emits nothing for a layer absent from the point registry", () => {
    expect(
      pointObjectsFor([
        { layer: "hydrothermal-vents-active", properties: { _lat: 1, _lon: 2 } },
      ]),
    ).toEqual([]);
  });
});

describe("registry shape", () => {
  // sabotaż: move an id from one list to the other (this also breaks tsc, which is fine — the test must ALSO go red) → ten test
  it("has 9 point layers and 12 opted-out layers", () => {
    expect(Object.keys(POINT_LAYERS).length).toBe(9);
    expect(NOT_POINT.length).toBe(12);
  });

  it("shares no id between the two lists", () => {
    const pointKeys = Object.keys(POINT_LAYERS);
    const notPointKeys = NOT_POINT as readonly string[];
    // Positive control: both sides must be non-empty before a disjointness
    // claim about them means anything.
    expect(pointKeys.length).toBeGreaterThan(0);
    expect(notPointKeys.length).toBeGreaterThan(0);
    for (const key of pointKeys) {
      expect(notPointKeys).not.toContain(key);
    }
  });

  it("isPointLayer agrees with the registry", () => {
    for (const key of Object.keys(POINT_LAYERS)) {
      expect(isPointLayer(key)).toBe(true);
    }
    expect(isPointLayer("contracts")).toBe(false);
  });
});
