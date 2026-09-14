// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// A share link is input from outside the same way `?layers=` is — see
// layers-param.test.ts for the sibling story. The extra wrinkle here is that
// `?s=` carries THREE independent things (camera, layers, filters) in one
// envelope, so a defect in one field must not corrupt the others, and the
// whole envelope must not silently reinterpret an old shape as a new one.
import { describe, it, expect, vi } from "vitest";

import {
  encodeShareState,
  decodeShareState,
  buildShareUrl,
  SHARE_STATE_VERSION,
} from "../utils/shareState";

const CAMERA = { longitude: 12.5, latitude: -3.25, zoom: 6, pitch: 45, bearing: 0 };

describe("round-trip", () => {
  it("encodes and decodes camera + layers + filters", () => {
    const encoded = encodeShareState({
      camera: CAMERA,
      layers: ["contracts", "argo"] as any,
      filters: { ventStatusFilters: ["Active"] }, openObjects: [], points: [] });
    const decoded = decodeShareState(encoded)!;
    expect(decoded.camera).toEqual(CAMERA);
    expect(decoded.layers).toEqual(["contracts", "argo"]);
    expect(decoded.filters).toEqual({ ventStatusFilters: ["Active"] });
  });

  it("omits empty layers/filters from the payload (short links)", () => {
    const encoded = encodeShareState({ camera: CAMERA, layers: [], filters: {}, openObjects: [], points: [] });
    const decoded = decodeShareState(encoded)!;
    expect(decoded.camera).toEqual(CAMERA);
    expect(decoded.layers).toBeNull();
    expect(decoded.filters).toBeNull();
  });
});

describe("requirement 1 — version gate", () => {
  it("rejects the whole envelope on version mismatch, never reinterprets it", () => {
    const encoded = encodeShareState({ camera: CAMERA, layers: ["contracts"] as any, filters: {}, openObjects: [], points: [] });
    const payload = JSON.parse(decodeURIComponent(escape(atob(encoded.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (encoded.length % 4)) % 4)))));
    payload.v = SHARE_STATE_VERSION + 1;
    const tampered = btoa(unescape(encodeURIComponent(JSON.stringify(payload)))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    expect(decodeShareState(tampered)).toBeNull();
  });
});

describe("requirement 2 — unknown layer id rejects the whole layer list, camera survives", () => {
  it("a bad layer list does not discard a good camera", () => {
    const encoded = encodeShareState({ camera: CAMERA, layers: ["contracts", "not-a-real-layer"] as any, filters: {}, openObjects: [], points: [] });
    const decoded = decodeShareState(encoded)!;
    expect(decoded.camera).toEqual(CAMERA);
    expect(decoded.layers).toBeNull();
  });
});

describe("requirement 4 — length cap checked before parsing", () => {
  it("discards an over-long value that is otherwise perfectly valid", () => {
    // ⛔ The payload must be wrong ONLY in its length. An earlier version of
    // this test used `"x".repeat(10000)`, which is also not valid base64/JSON —
    // so it returned null with the cap and without it, and deleting the cap
    // left every test green. A guard that cannot go red is not a guard.
    const bloated = encodeShareState({
      camera: CAMERA,
      layers: ["contracts"] as any,
      // Real shape, real field name, just far too many values to fit a URL.
      filters: { aisFlagFilters: Array.from({ length: 900 }, (_, i) => `FLAG${i}`) },
      openObjects: [], points: [],
    });
    expect(bloated.length).toBeGreaterThan(4000);
    expect(decodeShareState(bloated)).toBeNull();

    // Same shape, small enough to fit: proof the rejection above was the cap
    // and not something wrong with how this payload was built.
    const slim = encodeShareState({
      camera: CAMERA,
      layers: ["contracts"] as any,
      filters: { aisFlagFilters: ["FLAG0"] }, openObjects: [], points: [] });
    expect(slim.length).toBeLessThan(4000);
    expect(decodeShareState(slim)).not.toBeNull();
  });

  it("does not even attempt to parse an over-long value", () => {
    // "checked BEFORE parsing" is the actual requirement — a cap applied after
    // JSON.parse would still return null and look identical from outside.
    const bloated = encodeShareState({
      camera: CAMERA,
      layers: ["contracts"] as any,
      filters: { aisFlagFilters: Array.from({ length: 900 }, (_, i) => `FLAG${i}`) },
      openObjects: [], points: [],
    });
    const parse = vi.spyOn(JSON, "parse");
    try {
      expect(decodeShareState(bloated)).toBeNull();
      expect(parse).not.toHaveBeenCalled();
    } finally {
      parse.mockRestore();
    }
  });

  it("ignores an absent value", () => {
    expect(decodeShareState(null)).toBeNull();
  });

  it("rejects a malformed (non-base64/non-JSON) value gracefully", () => {
    expect(decodeShareState("!!!not-base64!!!")).toBeNull();
  });
});

describe("buildShareUrl", () => {
  it("produces a URL carrying a single ?s= param", () => {
    const url = buildShareUrl("https://something-rare.com", "/", {
      camera: CAMERA,
      layers: ["contracts"] as any,
      filters: {}, openObjects: [], points: [] });
    expect(url.startsWith("https://something-rare.com/?s=")).toBe(true);
    const parsed = new URL(url);
    expect([...parsed.searchParams.keys()]).toEqual(["s"]);
  });
});
