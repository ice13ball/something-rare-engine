// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

// Map3D.tsx pulls in deck.gl + maplibre at module scope, which need a real WebGL
// context (unavailable in jsdom) and drag in wgsl_reflect, which errors under
// vitest's ESM interop. None of that is exercised by the pure helpers under
// test here, so the whole rendering stack is stubbed out just enough to let
// the module load.

// Imported from the extracted modules, NOT through Map3D.tsx. That is the
// point of the extraction: importing Map3D pulls in deck.gl and MapLibre,
// which fail under jsdom at IMPORT time even though none of their code runs —
// so testing one pure function used to require stubbing the whole rendering
// stack. These modules have no such dependency.
import { rampColor, divergingRampColor, hexToRgbTriple } from "../components/map3d/colors";
import { decodeCurrentArrows, lruPut, _currentsFieldLRU } from "../components/map3d/currents";
import {
  depthCacheKey, loadDepthCacheFromLS, scheduleDepthCacheFlush,
  markDepthLookupFailed, depthLineFromCache, DEPTH_LS_MAX_ENTRIES,
} from "../components/map3d/depthCache";
import {
  expandBox, walkCoords, bboxToView, getBBoxCenter,
  approxViewBbox, bboxContains, expandBoxBuffer,
} from "../components/map3d/geometry";
import { makeSetFilter } from "../components/map3d/filters";

// ── colour maths ────────────────────────────────────────────────────────────

describe("hexToRgbTriple", () => {
  it("parses a hex string with leading #", () => {
    expect(hexToRgbTriple("#ff0000")).toEqual([255, 0, 0]);
  });
  it("parses a hex string without leading # (String.replace('#','') is a no-op)", () => {
    expect(hexToRgbTriple("00ff00")).toEqual([0, 255, 0]);
  });
  it("is case-insensitive (parseInt base16)", () => {
    expect(hexToRgbTriple("#00FF00")).toEqual([0, 255, 0]);
    expect(hexToRgbTriple("#00ff00")).toEqual([0, 255, 0]);
  });
  it("parses a mixed value", () => {
    expect(hexToRgbTriple("#3366cc")).toEqual([0x33, 0x66, 0xcc]);
  });
});

describe("rampColor", () => {
  const stops = [
    { pos: 0, hex: "#000000" },
    { pos: 0.5, hex: "#808080" },
    { pos: 1, hex: "#ffffff" },
  ];

  it("clamps below the domain to the low stop", () => {
    expect(rampColor(-100, 0, 10, stops)).toEqual([0, 0, 0, 170]);
  });
  it("clamps above the domain to the high stop", () => {
    expect(rampColor(1000, 0, 10, stops)).toEqual([255, 255, 255, 170]);
  });
  it("returns the low stop exactly at vmin", () => {
    expect(rampColor(0, 0, 10, stops)).toEqual([0, 0, 0, 170]);
  });
  it("returns the high stop exactly at vmax", () => {
    expect(rampColor(10, 0, 10, stops)).toEqual([255, 255, 255, 170]);
  });
  it("interpolates at the midpoint", () => {
    expect(rampColor(5, 0, 10, stops)).toEqual([128, 128, 128, 170]);
  });
  it("respects a custom alpha", () => {
    expect(rampColor(5, 0, 10, stops, 99)[3]).toBe(99);
  });
  it("falls back to grey when stops is empty", () => {
    expect(rampColor(5, 0, 10, [])).toEqual([150, 150, 150, 170]);
  });
  it("does not divide by zero when vmin === vmax", () => {
    // (vmax-vmin)||1 guard — value equals vmin so t=0 regardless
    expect(rampColor(5, 5, 5, stops)).toEqual([0, 0, 0, 170]);
  });
});

describe("divergingRampColor", () => {
  const stops = [
    { pos: 0, hex: "#0000ff" },   // blue (low)
    { pos: 0.5, hex: "#ffffff" }, // neutral (center)
    { pos: 1, hex: "#ff0000" },   // red (high)
  ];

  it("puts the neutral colour exactly at center, not at (vmin+vmax)/2", () => {
    // domain [0,10], center=2 — linear midpoint would be 5, diverging puts it at 2
    expect(divergingRampColor(2, 0, 2, 10, stops)).toEqual([255, 255, 255, 170]);
  });
  it("clamps below vmin to the low stop", () => {
    expect(divergingRampColor(-100, 0, 2, 10, stops)).toEqual([0, 0, 255, 170]);
  });
  it("clamps above vmax to the high stop", () => {
    expect(divergingRampColor(1000, 0, 2, 10, stops)).toEqual([255, 0, 0, 170]);
  });
  it("colours values equidistant either side of center distinctly", () => {
    // center=2, domain [0,10]: value 1 is 1 below center (half-range 2),
    // value 3 is 1 above center (half-range 8) — NOT symmetric in color space,
    // but both must differ from the neutral midpoint and from each other.
    const below = divergingRampColor(1, 0, 2, 10, stops);
    const above = divergingRampColor(3, 0, 2, 10, stops);
    const neutral = divergingRampColor(2, 0, 2, 10, stops);
    expect(below).not.toEqual(neutral);
    expect(above).not.toEqual(neutral);
    expect(below).not.toEqual(above);
  });
});

// ── geometry / bbox family ─────────────────────────────────────────────────

describe("expandBox", () => {
  it("grows a box to include a new coordinate", () => {
    const box = { minLon: 0, maxLon: 1, minLat: 0, maxLat: 1 };
    expandBox(box, [5, -3]);
    expect(box).toEqual({ minLon: 0, maxLon: 5, minLat: -3, maxLat: 1 });
  });
});

describe("walkCoords", () => {
  it("walks a Polygon coordinate array (ring of points)", () => {
    const box = { minLon: Infinity, maxLon: -Infinity, minLat: Infinity, maxLat: -Infinity };
    const polygon = [[[0, 0], [2, 0], [2, 3], [0, 3], [0, 0]]];
    walkCoords(polygon, box);
    expect(box).toEqual({ minLon: 0, maxLon: 2, minLat: 0, maxLat: 3 });
  });
  it("walks a MultiPolygon coordinate array", () => {
    const box = { minLon: Infinity, maxLon: -Infinity, minLat: Infinity, maxLat: -Infinity };
    const multi = [
      [[[0, 0], [1, 0], [1, 1], [0, 0]]],
      [[[10, 10], [12, 10], [12, 12], [10, 10]]],
    ];
    walkCoords(multi, box);
    expect(box).toEqual({ minLon: 0, maxLon: 12, minLat: 0, maxLat: 12 });
  });
  it("does nothing on non-array input", () => {
    const box = { minLon: Infinity, maxLon: -Infinity, minLat: Infinity, maxLat: -Infinity };
    walkCoords(null, box);
    walkCoords(undefined, box);
    walkCoords("garbage", box);
    expect(box).toEqual({ minLon: Infinity, maxLon: -Infinity, minLat: Infinity, maxLat: -Infinity });
  });
});

describe("bboxToView", () => {
  it("returns a default view for an empty (infinite) box", () => {
    expect(bboxToView({ minLon: Infinity, maxLon: -Infinity, minLat: Infinity, maxLat: -Infinity }))
      .toEqual({ longitude: 0, latitude: 10, zoom: 2 });
  });
  it("computes center and a zoom level from span", () => {
    const box = { minLon: -10, maxLon: 10, minLat: -5, maxLat: 5 };
    const view = bboxToView(box);
    expect(view.longitude).toBe(0);
    expect(view.latitude).toBe(0);
    expect(view.zoom).toBe(5); // span=20 -> >10 -> zoom 5
  });
  it("steps zoom down as span grows (boundary values)", () => {
    // span thresholds: >40->3, >20->4, >10->5, >5->6, >2->7, >1->8, >0.5->9, else 10
    expect(bboxToView({ minLon: 0, maxLon: 41, minLat: 0, maxLat: 0 }).zoom).toBe(3);
    expect(bboxToView({ minLon: 0, maxLon: 21, minLat: 0, maxLat: 0 }).zoom).toBe(4);
    expect(bboxToView({ minLon: 0, maxLon: 11, minLat: 0, maxLat: 0 }).zoom).toBe(5);
    expect(bboxToView({ minLon: 0, maxLon: 6, minLat: 0, maxLat: 0 }).zoom).toBe(6);
    expect(bboxToView({ minLon: 0, maxLon: 3, minLat: 0, maxLat: 0 }).zoom).toBe(7);
    expect(bboxToView({ minLon: 0, maxLon: 1.5, minLat: 0, maxLat: 0 }).zoom).toBe(8);
    expect(bboxToView({ minLon: 0, maxLon: 0.6, minLat: 0, maxLat: 0 }).zoom).toBe(9);
    expect(bboxToView({ minLon: 0, maxLon: 0.1, minLat: 0, maxLat: 0 }).zoom).toBe(10);
  });
});

describe("getBBoxCenter", () => {
  it("computes a view from a list of GeoJSON-like features", () => {
    const features = [
      { geometry: { coordinates: [[[0, 0], [2, 0], [2, 2], [0, 0]]] } },
      { geometry: { coordinates: [[[10, 10], [12, 10], [12, 12], [10, 10]]] } },
    ];
    const view = getBBoxCenter(features);
    expect(view.longitude).toBe(6);
    expect(view.latitude).toBe(6);
  });
  it("ignores features with no geometry.coordinates", () => {
    const view = getBBoxCenter([{ geometry: null }]);
    expect(view).toEqual({ longitude: 0, latitude: 10, zoom: 2 });
  });

  it("documents CURRENT antimeridian behaviour (does not unwrap ±180°)", () => {
    // A feature straddling the antimeridian (e.g. lon 179 and lon -179, both
    // "close" on a globe) is walked as plain min/max lon — this treats them as
    // ~358° apart instead of ~2° apart. This is NOT a fix, just a record of
    // today's behaviour (project has been bitten by this wrap before).
    const features = [
      { geometry: { coordinates: [[[179, 10], [179.5, 10], [179.5, 11], [179, 10]]] } },
      { geometry: { coordinates: [[[-179.5, 10], [-179, 10], [-179, 11], [-179.5, 10]]] } },
    ];
    const view = getBBoxCenter(features);
    // naive center of [-179.5, 179.5] is ~0, not ~179.75/-180 (the true geographic center)
    expect(view.longitude).toBeCloseTo(0, 5);
    // span is treated as ~359°, clamped into the lowest zoom bucket
    expect(view.zoom).toBe(3);
  });
});

describe("approxViewBbox", () => {
  it("computes a box around the current view state at zoom 2, pitch 0", () => {
    const box = approxViewBbox({ longitude: 10, latitude: 20, zoom: 2, pitch: 0 });
    // span = 360/4 = 90; halfLon = min(180, 90*1.5*1) = 135; halfLat = min(90, 90*1*1)=90
    expect(box.minLon).toBe(10 - 135);
    expect(box.maxLon).toBe(10 + 135);
    expect(box.minLat).toBe(20 - 90); // not clamped at lat=20
    expect(box.maxLat).toBe(90);      // clamped: 20+90=110 -> 90
  });
  it("widens the box under pitch", () => {
    const flat = approxViewBbox({ longitude: 0, latitude: 0, zoom: 5, pitch: 0 });
    const pitched = approxViewBbox({ longitude: 0, latitude: 0, zoom: 5, pitch: 45 });
    expect(pitched.maxLon - pitched.minLon).toBeGreaterThan(flat.maxLon - flat.minLon);
  });
  it("defaults missing fields", () => {
    const box = approxViewBbox({});
    expect(Number.isFinite(box.minLon)).toBe(true);
  });
});

describe("bboxContains", () => {
  it("true when outer fully contains inner", () => {
    const outer = { minLon: -10, maxLon: 10, minLat: -10, maxLat: 10 };
    const inner = { minLon: -5, maxLon: 5, minLat: -5, maxLat: 5 };
    expect(bboxContains(outer, inner)).toBe(true);
  });
  it("false when inner extends past outer", () => {
    const outer = { minLon: -10, maxLon: 10, minLat: -10, maxLat: 10 };
    const inner = { minLon: -5, maxLon: 15, minLat: -5, maxLat: 5 };
    expect(bboxContains(outer, inner)).toBe(false);
  });
});

describe("expandBoxBuffer", () => {
  it("grows a box symmetrically about its center by factor", () => {
    const b = { minLon: -2, maxLon: 2, minLat: -1, maxLat: 1 };
    const grown = expandBoxBuffer(b, 2);
    expect(grown).toEqual({ minLon: -4, maxLon: 4, minLat: -2, maxLat: 2 });
  });
  it("clamps latitude to [-90,90]", () => {
    const b = { minLon: -1, maxLon: 1, minLat: -80, maxLat: 80 };
    const grown = expandBoxBuffer(b, 3);
    expect(grown.minLat).toBe(-90);
    expect(grown.maxLat).toBe(90);
  });
});

// ── binary decode ────────────────────────────────────────────────────────

describe("decodeCurrentArrows", () => {
  const meta = {
    bounds: [-10, -10, 10, 10] as [number, number, number, number],
    imageUnscale: [-1, 1] as [number, number],
  } as any;

  it("returns [] for an empty buffer", () => {
    const rgba = { data: new Uint8ClampedArray(0), width: 0, height: 0 };
    expect(decodeCurrentArrows(rgba, meta)).toEqual([]);
  });

  it("skips transparent (alpha=0) texels", () => {
    // 1x1 image, alpha channel 0 -> land/no-data, skipped
    const rgba = { data: new Uint8ClampedArray([128, 128, 0, 0]), width: 1, height: 1 };
    expect(decodeCurrentArrows(rgba, meta)).toEqual([]);
  });

  it("decodes a single opaque texel above the still-water threshold", () => {
    // width=8,height=8 so stepPx=4 samples (0,0) only within this tiny image.
    // R=255,G=255 -> u=v=umax=1 (span=2, umin=-1): u=(255/255)*2-1=1
    const w = 8, h = 8;
    const data = new Uint8ClampedArray(w * h * 4);
    const i = 0; // (0,0)
    data[i] = 255;     // R -> u = 1
    data[i + 1] = 255; // G -> v = 1
    data[i + 2] = 0;
    data[i + 3] = 255; // opaque
    const rgba = { data, width: w, height: h };
    const out = decodeCurrentArrows(rgba, meta);
    // Only (0,0) and possibly (4,0),(0,4),(4,4) sampled; only (0,0) is non-zero/opaque.
    expect(out.length).toBe(1);
    const arrow = out[0];
    // lon = west + (0/8)*(east-west) = -10; lat = north - (0/8)*(north-south) = 10
    expect(arrow.source).toEqual([-10, 10]);
    expect(arrow.speed).toBeCloseTo(Math.hypot(1, 1), 5);
    // target = source + u*lenDeg, v*lenDeg with lenDeg=1.2
    expect(arrow.target[0]).toBeCloseTo(-10 + 1 * 1.2, 5);
    expect(arrow.target[1]).toBeCloseTo(10 + 1 * 1.2, 5);
  });

  it("skips near-still cells (speed < 0.05)", () => {
    const w = 4, h = 4;
    const data = new Uint8ClampedArray(w * h * 4);
    // R=G=127 -> u=v=(127/255)*2-1 ≈ -0.00392, speed ≈ 0.0055 < 0.05
    data[0] = 127; data[1] = 127; data[2] = 0; data[3] = 255;
    const rgba = { data, width: w, height: h };
    expect(decodeCurrentArrows(rgba, meta)).toEqual([]);
  });
});

// ── LRU cache ───────────────────────────────────────────────────────────

describe("lruPut / _currentsFieldLRU", () => {
  beforeEach(() => {
    _currentsFieldLRU.clear();
  });

  it("stores an entry retrievable by key", () => {
    const entry = { field: {} as any, arrows: [] };
    lruPut("k1", entry);
    expect(_currentsFieldLRU.get("k1")).toBe(entry);
  });

  it("evicts the oldest entry once capacity (24) is exceeded", () => {
    for (let i = 0; i < 25; i++) {
      lruPut(`k${i}`, { field: {} as any, arrows: [] });
    }
    expect(_currentsFieldLRU.size).toBe(24);
    expect(_currentsFieldLRU.has("k0")).toBe(false); // oldest evicted
    expect(_currentsFieldLRU.has("k24")).toBe(true); // newest kept
  });

  it("re-putting an existing key refreshes its recency (moves it to the end)", () => {
    for (let i = 0; i < 24; i++) {
      lruPut(`k${i}`, { field: {} as any, arrows: [] });
    }
    // k0 is currently oldest; touch it again
    lruPut("k0", { field: {} as any, arrows: [] });
    // Adding one more new key should now evict k1 (the new oldest), not k0
    lruPut("k24", { field: {} as any, arrows: [] });
    expect(_currentsFieldLRU.has("k0")).toBe(true);
    expect(_currentsFieldLRU.has("k1")).toBe(false);
  });
});

// ── depth cache ───────────────────────────────────────────────────────────

describe("depth cache", () => {
  let store: Record<string, string>;

  beforeEach(() => {
    store = {};
    vi.stubGlobal("localStorage", {
      getItem: (k: string) => (k in store ? store[k] : null),
      setItem: (k: string, v: string) => { store[k] = v; },
      removeItem: (k: string) => { delete store[k]; },
      clear: () => { store = {}; },
    });
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("depthCacheKey rounds lat/lon to 0.01 degrees", () => {
    expect(depthCacheKey(12.3456, -7.8912)).toBe("12.35,-7.89");
  });

  it("loadDepthCacheFromLS seeds the L1 cache and depthLineFromCache reads a hit", () => {
    store["abyssal_bathymetry_cache_v1"] = JSON.stringify({ "1.00,2.00": -500 });
    const line = depthLineFromCache(1.0, 2.0);
    expect(line).toContain("500");
    expect(line).toContain("Seafloor");
  });

  it("depthLineFromCache returns null on a miss", () => {
    expect(depthLineFromCache(99.99, 99.99)).toBeNull();
  });

  it("markDepthLookupFailed then an immediate retry is still considered failed (backoff)", () => {
    const lat = 55.5, lon = 10.5;
    markDepthLookupFailed(depthCacheKey(lat, lon));
    // depthLineFromCache should NOT show a resolved value right after failure
    expect(depthLineFromCache(lat, lon)).toBeNull();
    // Retrying immediately (0ms elapsed) is still within the 60s backoff window.
    // markDepthLookupFailed does not itself expose a "should retry" getter directly,
    // but re-calling it should not throw and should keep the entry absent from depthCache.
    markDepthLookupFailed(depthCacheKey(lat, lon));
    expect(depthLineFromCache(lat, lon)).toBeNull();
  });

  it("scheduleDepthCacheFlush debounces writes via a 2s timer and persists resolved entries", () => {
    // loadDepthCacheFromLS only hydrates once per module lifetime (depthLsLoaded
    // is a one-shot flag), so re-seeding localStorage and calling it again here
    // would be a no-op — it was already consumed by an earlier test in this file.
    // Instead, seed the L1 depthCache indirectly via depthLineFromCache's own
    // load-then-read path from an EARLIER, not-yet-loaded key is unavailable at
    // this point, so we rely on markDepthLookupFailed's sibling: prime a value
    // through a fresh flush call and confirm any dirty write lands in storage.
    scheduleDepthCacheFlush();
    // Nothing written synchronously — it's debounced.
    expect(store["abyssal_bathymetry_cache_v1"]).toBeUndefined();
    vi.advanceTimersByTime(2000);
    expect(store["abyssal_bathymetry_cache_v1"]).toBeDefined();
    // The previously-seeded hit ("1.00,2.00" -> -500, from an earlier test)
    // is still resident in the shared module-level depthCache and must survive
    // the flush since flush persists every resolved (non-"loading") entry.
    const written = JSON.parse(store["abyssal_bathymetry_cache_v1"]);
    expect(written["1.00,2.00"]).toBe(-500);
  });

  it("loadDepthCacheFromLS is idempotent — a later call after hydration is a safe no-op", () => {
    // depthLsLoaded is a one-shot module flag; by this point in the suite the
    // first real hydrate already ran (via depthLineFromCache above), so a direct
    // call here must not throw and must not clobber what's already in depthCache.
    expect(() => loadDepthCacheFromLS()).not.toThrow();
    expect(depthLineFromCache(1.0, 2.0)).toContain("500");
  });
});

describe("DEPTH_LS_MAX_ENTRIES", () => {
  it("is the documented cap of 5000", () => {
    expect(DEPTH_LS_MAX_ENTRIES).toBe(5000);
  });
});

// ── predicates ──────────────────────────────────────────────────────────

describe("makeSetFilter", () => {
  it("returns undefined for an empty Set — project convention: empty means show all", () => {
    expect(makeSetFilter(new Set(), "status")).toBeUndefined();
  });

  it("matches a feature whose property is in the Set", () => {
    const filter = makeSetFilter(new Set(["active"]), "status");
    expect(filter).toBeDefined();
    expect(filter!({ properties: { status: "active" } })).toBe(true);
  });

  it("rejects a feature whose property is not in the Set", () => {
    const filter = makeSetFilter(new Set(["active"]), "status");
    expect(filter!({ properties: { status: "retired" } })).toBe(false);
  });

  it("rejects a feature with null properties", () => {
    const filter = makeSetFilter(new Set(["active"]), "status");
    expect(filter!({ properties: null })).toBe(false);
  });

  it("rejects a feature with missing properties object", () => {
    const filter = makeSetFilter(new Set(["active"]), "status");
    expect(filter!({})).toBe(false);
  });
});
