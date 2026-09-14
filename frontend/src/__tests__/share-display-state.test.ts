// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// Coverage for the `displayRegistry.ts` subject — the per-layer scalar
// selectors (depth, decade, variable, field/hexes) a share link carries — and
// its wiring into the `d` field of shareState.ts. This is where the registry's
// two sharpest edges live: a default that drifts from the real store silently
// changes what a link carries (see the `default` doc comment in
// displayRegistry.ts), and `slug`/`isoDate`/`depth` values are interpolated
// straight into a request PATH, so validation here is a security boundary,
// not cosmetics.
import { describe, it, expect, beforeEach, afterEach } from "vitest";

import {
  DISPLAY_FIELDS,
  DISPLAY_OPT_OUT_FIELDS,
  DISPLAY_LOOKUP,
  isValidDisplayValue,
  collectShareableDisplay,
  applyShareableDisplay,
} from "../types/displayRegistry";
import { encodeShareState, decodeShareState } from "../utils/shareState";
import { useMapStore } from "../store/mapStore";

const CAMERA = { longitude: 12.5, latitude: -3.25, zoom: 6, pitch: 45, bearing: 0 };

// Captured once, before any test mutates the store, so clause 2 compares the
// registry's `default` field against what the app ACTUALLY starts with — not
// against whatever a previous test left behind.
const INITIAL_STORE_STATE = useMapStore.getState();

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
  // sabotaż: delete the `d` assignment in encodeShareState → ten test
  it("encodes and decodes a changed WOA depth and variable", () => {
    const encoded = encodeShareState({
      camera: CAMERA,
      layers: [],
      filters: {},
      openObjects: [],
      points: [],
      display: { woaDepth: 2000, woaVariable: "aou" },
    });
    const decoded = decodeShareState(encoded)!;
    expect(decoded.display).toEqual({ woaDepth: 2000, woaVariable: "aou" });
  });
});

describe("registry defaults match the real store", () => {
  // sabotaż: change any `default` in DISPLAY_FIELDS so it no longer matches
  // the store's initial value → ten test
  //
  // ⛔ The single most important test in this file. If a default drifts from
  // the live store, `collectShareableDisplay` starts emitting values that are
  // actually the recipient's default too (wasted bytes, and a link that stops
  // working the day the code's default changes), or — worse — starts SKIPPING
  // a value the sender genuinely changed because it now matches a stale
  // "default" the store no longer starts with.
  it("has a non-zero number of fields to check", () => {
    expect(Object.keys(DISPLAY_FIELDS).length).toBeGreaterThan(0);
  });

  it("every DISPLAY_FIELDS default equals the store's real initial value", () => {
    for (const [field, cfg] of Object.entries(DISPLAY_FIELDS)) {
      expect(
        (INITIAL_STORE_STATE as unknown as Record<string, unknown>)[field],
      ).toBe(cfg.default);
    }
  });
});

describe("nothing is emitted when nothing changed", () => {
  // sabotaż: make collectShareableDisplay emit unconditionally → ten test
  it("collectShareableDisplay on the pristine store returns {}", () => {
    expect(collectShareableDisplay(useMapStore.getState())).toEqual({});
  });
});

describe("only what changed is emitted", () => {
  let snapshot: ReturnType<typeof useMapStore.getState>;
  beforeEach(() => {
    snapshot = useMapStore.getState();
  });
  afterEach(() => {
    useMapStore.setState(snapshot);
  });

  // sabotaż: make collectShareableDisplay always include every field → ten test
  it("emits exactly the two fields that were set, nothing else", () => {
    useMapStore.setState({ woaDepth: 1500, co2Decade: 7 } as any);
    const out = collectShareableDisplay(useMapStore.getState());
    expect(Object.keys(out).sort()).toEqual(["co2Decade", "woaDepth"]);
    expect(out.woaDepth).toBe(1500);
    expect(out.co2Decade).toBe(7);
  });
});

describe("path injection is refused", () => {
  // sabotaż: relax the `slug` regex in CHECKS.slug → ten test
  //
  // `woaVariable` lands straight in a request path
  // (`/api/v1/woa/${woaVariable}/${woaDepth}.png`). The client holds no
  // allow-list for its legal values (those live in the backend's /meta), so
  // this shape check is the only thing standing between a stranger's link and
  // the path we fetch — a traversal segment or an unexpected character here
  // is not a formatting nit, it is what we ask the browser to GET.
  it("refuses a path-traversal attempt", () => {
    expect(isValidDisplayValue("woaVariable", "../../../etc/passwd")).toBe(false);
  });

  it("refuses uppercase", () => {
    expect(isValidDisplayValue("woaVariable", "Oxygen")).toBe(false);
  });

  it("refuses a value over the length bound", () => {
    expect(isValidDisplayValue("woaVariable", "a".repeat(25))).toBe(false);
  });

  it("refuses a space", () => {
    expect(isValidDisplayValue("woaVariable", "oxy gen")).toBe(false);
  });

  it("refuses the empty string", () => {
    expect(isValidDisplayValue("woaVariable", "")).toBe(false);
  });

  it("accepts plain lowercase slugs", () => {
    expect(isValidDisplayValue("woaVariable", "oxygen")).toBe(true);
    expect(isValidDisplayValue("woaVariable", "o2sat")).toBe(true);
  });
});

describe("a value outside a closed union is refused", () => {
  // sabotaž: add "raster" to woaDisplayMode's `values` tuple → ten test
  it("refuses a mode not in the union", () => {
    expect(isValidDisplayValue("woaDisplayMode", "raster")).toBe(false);
  });

  it("accepts a mode in the union", () => {
    expect(isValidDisplayValue("woaDisplayMode", "hexes")).toBe(true);
  });
});

describe("an unknown field name is refused", () => {
  // sabotaž: make isValidDisplayValue fall through to `true` for a missing lookup → ten test
  it("rejects a field the registry has never heard of", () => {
    expect(isValidDisplayValue("notAField", 1)).toBe(false);
  });
});

describe("opt-out fields are refused even when a link carries them", () => {
  // sabotaž: drop the isValidDisplayValue re-check inside validateDisplay → ten test
  //
  // These fields are UI chrome, not view state — `exportFormat` decides what
  // the RECIPIENT's own export button produces, `currentsPlaying` would walk
  // the recipient's map off the moment the sender parked on, `mapTapCount` is
  // pure mobile plumbing. A link that could set any of them would let a
  // sender silently reach into state that is supposed to belong to the reader.
  it("drops opt-out fields, keeps the one valid field", () => {
    const encoded = encodeShareState({
      camera: CAMERA,
      layers: [],
      filters: {},
      openObjects: [],
      points: [],
      display: { woaDepth: 1500 },
    });
    const payload = toEnvelope(encoded);
    payload.d = {
      woaDepth: 1500,
      exportFormat: "csv",
      mapTapCount: 99,
      currentsPlaying: true,
    };
    const tampered = fromEnvelope(payload);
    const decoded = decodeShareState(tampered)!;
    expect(decoded.display).toEqual({ woaDepth: 1500 });
  });
});

describe("a bad `d` does not damage camera, layers or points", () => {
  // sabotaž: make a bad `d` return null for the whole ShareState → ten test
  it("camera and layers still decode when every `d` entry is invalid", () => {
    const encoded = encodeShareState({
      camera: CAMERA,
      layers: ["contracts"] as any,
      filters: {},
      openObjects: [],
      points: [],
      display: { woaDepth: 1500 },
    });
    const payload = toEnvelope(encoded);
    payload.d = { woaVariable: "../etc", woaDisplayMode: "raster" };
    const tampered = fromEnvelope(payload);
    const decoded = decodeShareState(tampered)!;
    expect(decoded.camera).toEqual(CAMERA);
    expect(decoded.layers).toEqual(["contracts"]);
    expect(decoded.display).toBeNull();
  });
});

describe("numbers out of range are refused", () => {
  // sabotaž: widen the bounds in CHECKS.depth → ten test
  it("refuses a negative depth", () => {
    expect(isValidDisplayValue("woaDepth", -1)).toBe(false);
  });

  it("refuses a depth past the deepest ocean bound", () => {
    expect(isValidDisplayValue("woaDepth", 99999)).toBe(false);
  });

  it("refuses a non-integer depth", () => {
    expect(isValidDisplayValue("woaDepth", 1.5)).toBe(false);
  });

  it("refuses a depth sent as a string", () => {
    expect(isValidDisplayValue("woaDepth", "500")).toBe(false);
  });

  it("accepts zero and an in-range depth", () => {
    expect(isValidDisplayValue("woaDepth", 0)).toBe(true);
    expect(isValidDisplayValue("woaDepth", 2000)).toBe(true);
  });
});

describe("applyShareableDisplay writes valid values and ignores invalid ones", () => {
  let snapshot: ReturnType<typeof useMapStore.getState>;
  beforeEach(() => {
    snapshot = useMapStore.getState();
  });
  afterEach(() => {
    useMapStore.setState(snapshot);
  });

  // sabotaž: remove the isValidDisplayValue guard inside applyShareableDisplay → ten test
  it("takes the valid depth, keeps the display mode unchanged", () => {
    const before = useMapStore.getState().woaDisplayMode;
    applyShareableDisplay({ woaDepth: 1500, woaDisplayMode: "nonsense" });
    const after = useMapStore.getState();
    expect(after.woaDepth).toBe(1500);
    expect(after.woaDisplayMode).toBe(before);
  });
});

describe("currentsDate shape", () => {
  // sabotaž: loosen the isoDate regex in CHECKS.isoDate → ten test
  it("accepts YYYY-MM-DD", () => {
    expect(isValidDisplayValue("currentsDate", "2026-09-14")).toBe(true);
  });

  it("refuses DD/MM/YYYY", () => {
    expect(isValidDisplayValue("currentsDate", "14/09/2026")).toBe(false);
  });

  it("refuses unpadded month/day", () => {
    expect(isValidDisplayValue("currentsDate", "2026-9-14")).toBe(false);
  });

  it("refuses the word 'latest'", () => {
    expect(isValidDisplayValue("currentsDate", "latest")).toBe(false);
  });
});

describe("the registry's shape is real", () => {
  // sabotaž: add or remove an entry from DISPLAY_FIELDS or DISPLAY_OPT_OUT_FIELDS
  // without updating this test → ten test
  it("has 32 covered fields and 8 opted-out fields", () => {
    expect(Object.keys(DISPLAY_FIELDS).length).toBe(32);
    expect(DISPLAY_OPT_OUT_FIELDS.length).toBe(8);
  });

  it("shares no name between DISPLAY_FIELDS and DISPLAY_OPT_OUT_FIELDS", () => {
    const covered = Object.keys(DISPLAY_FIELDS);
    const optedOut = DISPLAY_OPT_OUT_FIELDS as readonly string[];
    // Positive control: both sides must be non-empty before a disjointness
    // claim about them means anything.
    expect(covered.length).toBeGreaterThan(0);
    expect(optedOut.length).toBeGreaterThan(0);
    for (const key of covered) {
      expect(optedOut).not.toContain(key);
    }
  });

  // sabotaž: give one entry both `values` and `check`, or neither → ten test
  it("every field has exactly one of `values` or `check`", () => {
    for (const [field, cfg] of Object.entries(DISPLAY_FIELDS)) {
      const hasValues = "values" in cfg && cfg.values !== undefined;
      const hasCheck = "check" in cfg && cfg.check !== undefined;
      expect(hasValues !== hasCheck, `${field} must have exactly one of values/check`).toBe(true);
    }
  });

  it("DISPLAY_LOOKUP is the same object as DISPLAY_FIELDS", () => {
    expect(DISPLAY_LOOKUP).toBe(DISPLAY_FIELDS as any);
  });
});
