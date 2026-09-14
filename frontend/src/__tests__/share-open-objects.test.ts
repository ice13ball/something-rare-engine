// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// Coverage for the "open objects" field on the share-link envelope (`o`):
// a link can re-open the detail panels the sender had open. See shareState.ts
// `validateOpenObjects` for why this validator drops bad entries individually
// instead of rejecting the whole list (modeled on `validateFilters`, not on
// `validateLayers`).
import { describe, it, expect } from "vitest";

import { encodeShareState, decodeShareState, MAX_OPEN_OBJECTS } from "../utils/shareState";

const CAMERA = { longitude: 12.5, latitude: -3.25, zoom: 6, pitch: 45, bearing: 0 };

// Base64url <-> JSON helpers, same technique as share-state.test.ts's
// "requirement 1 — version gate" — decode an encoded envelope to plain JSON,
// tamper it by hand, then re-encode so decodeShareState sees exactly the
// malformed shape we intend.
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
  it("encodes and decodes two open objects", () => {
    const encoded = encodeShareState({
      camera: CAMERA,
      layers: [],
      filters: {},
      openObjects: [
        ["contracts", "feature-1"],
        ["argo", "feature-2"],
      ],
    });
    const decoded = decodeShareState(encoded)!;
    expect(decoded.openObjects).toEqual([
      ["contracts", "feature-1"],
      ["argo", "feature-2"],
    ]);
  });
});

describe("one bad entry does not cost the good ones", () => {
  it("drops only the entry naming an unknown layer id", () => {
    const encoded = encodeShareState({
      camera: CAMERA,
      layers: [],
      filters: {},
      openObjects: [
        ["contracts", "feature-1"],
        ["argo", "feature-2"],
      ],
    });
    const payload = toEnvelope(encoded);
    // Insert a bad entry alongside the two good ones.
    payload.o = [["not-a-real-layer", "feature-x"], ...payload.o];
    const tampered = fromEnvelope(payload);

    const decoded = decodeShareState(tampered)!;
    // Positive control: assert the survivors are non-empty AND are exactly
    // the right two — "not null" alone would also pass if the validator
    // dropped everything, or kept the bad entry too.
    expect(decoded.openObjects).not.toBeNull();
    expect(decoded.openObjects!.length).toBe(2);
    expect(decoded.openObjects).toEqual([
      ["contracts", "feature-1"],
      ["argo", "feature-2"],
    ]);
  });
});

describe("a corrupt `o` must not damage the other fields", () => {
  it("camera, layers and filters still decode when `o` is garbage", () => {
    const encoded = encodeShareState({
      camera: CAMERA,
      layers: ["contracts"] as any,
      filters: { ventStatusFilters: ["Active"] },
      openObjects: [["contracts", "feature-1"]],
    });
    const payload = toEnvelope(encoded);
    payload.o = "not-an-array"; // corrupt in place of the real shape
    const tampered = fromEnvelope(payload);

    const decoded = decodeShareState(tampered)!;
    expect(decoded.camera).toEqual(CAMERA);
    expect(decoded.layers).toEqual(["contracts"]);
    expect(decoded.filters).toEqual({ ventStatusFilters: ["Active"] });
    expect(decoded.openObjects).toBeNull();
  });
});

describe("duplicates collapse", () => {
  it("the same [layer, id] named twice yields one entry", () => {
    const encoded = encodeShareState({
      camera: CAMERA,
      layers: [],
      filters: {},
      openObjects: [
        ["contracts", "feature-1"],
        ["contracts", "feature-1"],
      ],
    });
    const decoded = decodeShareState(encoded)!;
    expect(decoded.openObjects).not.toBeNull();
    expect(decoded.openObjects).toEqual([["contracts", "feature-1"]]);
  });
});

describe("cap", () => {
  it(`caps five valid entries at ${MAX_OPEN_OBJECTS}`, () => {
    const payload = toEnvelope(
      encodeShareState({ camera: CAMERA, layers: [], filters: {}, openObjects: [] }),
    );
    payload.o = [
      ["contracts", "feature-1"],
      ["contracts", "feature-2"],
      ["contracts", "feature-3"],
      ["contracts", "feature-4"],
      ["contracts", "feature-5"],
    ];
    const encoded = fromEnvelope(payload);

    const decoded = decodeShareState(encoded)!;
    expect(decoded.openObjects).not.toBeNull();
    expect(decoded.openObjects!.length).toBe(MAX_OPEN_OBJECTS);
    expect(decoded.openObjects).toEqual([
      ["contracts", "feature-1"],
      ["contracts", "feature-2"],
      ["contracts", "feature-3"],
    ]);
  });
});

describe("empty array", () => {
  it("encodes to no `o` key at all", () => {
    const encoded = encodeShareState({
      camera: CAMERA,
      layers: [],
      filters: {},
      openObjects: [],
    });
    const payload = toEnvelope(encoded);
    expect(Object.prototype.hasOwnProperty.call(payload, "o")).toBe(false);

    const decoded = decodeShareState(encoded)!;
    expect(decoded.openObjects).toBeNull();
  });
});
