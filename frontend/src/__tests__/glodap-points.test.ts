// frontend/src/__tests__/glodap-points.test.ts
import { describe, it, expect } from "vitest";
import { glodapPoints, glodapColor, GLODAP_NO_VALUE_RGBA, glodapYearBounds, type GlodapCastsDoc } from "../utils/glodapPoints";
import { rampColor } from "../components/map3d/colors";
import { LAYER_DEFAULTS, sortDeckLayers, toggleIdForDeckLayer } from "../utils/layerConfig";

const ramp = [{ pos: 0, hex: "#fdedb0" }, { pos: 0.5, hex: "#dd6d7c" }, { pos: 1, hex: "#3e184e" }];
const dicMeta = { key: "dic", units: "µmol/kg", vmin: 1900, vmax: 2400, ramp };
// Shape of backend/domains/glodap_points.py `_assemble_casts`: dic/talk/ph only (no `cant` key), one
// column per depth window, null where no WOCE-2 bottle fell in the window.
const doc: GlodapCastsDoc = {
  product: "GLODAPv3 (2026)", n: 3,
  keys: ["A_1_1", "B_2_1", "C_3_1"], lon: [-179.99, 10, 180], lat: [0, 50, -60], year: [1975, 2003, 2020],
  values: { dic: { "0": [2100, null, 310.5], "200": [null, null, null] }, talk: { "0": [null, null, null] }, ph: { "0": [null, 10.21, null] } },
};

describe("GLODAP points take the field's colour, never their own", () => {
  it("colours a value with exactly the field's ramp (unit/scale guard)", () => {
    expect(glodapColor(2100, dicMeta).slice(0, 3)).toEqual(rampColor(2100, 1900, 2400, ramp).slice(0, 3));
  });
  it("out-of-ramp values clamp to the ramp ends", () => {
    expect(glodapColor(310.5, dicMeta).slice(0, 3)).toEqual(rampColor(1900, 1900, 2400, ramp).slice(0, 3));
    expect(glodapColor(2664.2, dicMeta).slice(0, 3)).toEqual(rampColor(2400, 1900, 2400, ramp).slice(0, 3));
    expect(glodapColor(2664.2, dicMeta).every(Number.isFinite)).toBe(true);
    expect(glodapColor(310.5, dicMeta)[3]).toBeGreaterThan(0);
  });
  it("null (no acceptable bottle in the window) is grey, never a ramp colour", () => {
    expect(glodapColor(null, dicMeta)).toEqual(GLODAP_NO_VALUE_RGBA);
  });
  it("is grey, not transparent or NaN, while the field's ramp has not loaded yet", () => {
    expect(glodapColor(2100, undefined)).toEqual(GLODAP_NO_VALUE_RGBA);
  });
  it("cant colours every point grey", () => {
    const pts = glodapPoints(doc, "cant", 0, null);
    expect(pts).toHaveLength(3);
    expect(pts.every((p) => p.value === null)).toBe(true);
  });
  it("a depth the document does not carry colours every point grey", () => {
    const pts = glodapPoints(doc, "dic", 4000, null);
    expect(pts).toHaveLength(3);
    expect(pts.every((p) => p.value === null)).toBe(true);
  });
});

describe("year range and draw order", () => {
  it("keeps all years by default and filters by an inclusive range", () => {
    expect(glodapPoints(doc, "dic", 0, null)).toHaveLength(3);
    expect(glodapPoints(doc, "dic", 0, [2000, 2020]).map((p) => p.key).sort()).toEqual(["B_2_1", "C_3_1"]);
    expect(glodapPoints(doc, "dic", 0, [1900, 1901])).toEqual([]);
  });
  it("puts grey points first so coloured ones draw on top", () => {
    const pts = glodapPoints(doc, "dic", 0, null);
    const firstColoured = pts.findIndex((p) => p.value !== null);
    expect(firstColoured).toBeGreaterThan(0);
    expect(pts.slice(firstColoured).every((p) => p.value !== null)).toBe(true);
  });
  it("keeps antimeridian longitudes inside [-180, 180]", () => {
    for (const p of glodapPoints(doc, "dic", 0, null)) expect(Math.abs(p.position[0])).toBeLessThanOrEqual(180);
  });
  it("derives year bounds from the document", () => {
    expect(glodapYearBounds(doc)).toEqual({ min: 1975, max: 2020 });
    expect(glodapYearBounds(null)).toBeNull();
  });
});

describe("points are drawn above the ocean-carbon field", () => {
  it("the deck id resolves to a real toggle with a real order (an unmapped id would sort to 9999 and pass the test below by accident)", () => {
    const order = new Map(LAYER_DEFAULTS.map((l) => [l.id, l.order_idx]));
    expect(toggleIdForDeckLayer("glodap-points")).toBe("glodap-points");
    expect(order.get("glodap-points")).toBeLessThan(9999);
    expect(order.get("glodap-points")!).toBeGreaterThan(order.get(toggleIdForDeckLayer("ocean-carbon-bitmap-dic-0-0"))!);
  });
  it("sorts the points deck layer after every ocean-carbon bitmap tile (real layersRaw shape: the field is a nested array)", () => {
    const layers = [{ id: "glodap-points" }, [{ id: "ocean-carbon-bitmap-dic-0-0" }, { id: "ocean-carbon-bitmap-dic-0-1" }]];
    const sorted = sortDeckLayers(layers, LAYER_DEFAULTS).map((l: any) => l.id);
    expect(sorted).toHaveLength(3);
    expect(sorted.indexOf("glodap-points")).toBeGreaterThan(sorted.indexOf("ocean-carbon-bitmap-dic-0-1"));
    expect(sorted[sorted.length - 1]).toBe("glodap-points");
  });
});

import { useMapStore } from "../store/mapStore";
import { collectShareableFilters, applyShareableFilters } from "../types/filterRegistry";
import { decodeShareState, encodeShareState } from "../utils/shareState";
import { GLODAP_DEPTH_WINDOWS, GLODAP_DEPTH_WINDOW_BOUNDS, glodapWindowLabel } from "../utils/glodapPoints";

describe("GLODAP year range in the store and the share link", () => {
  it("defaults to all years (null) and resets with the other filters", () => {
    expect(useMapStore.getState().glodapYearRange).toBeNull();
    useMapStore.getState().setGlodapYearRange([1990, 2000]);
    useMapStore.getState().resetAllFilters();
    expect(useMapStore.getState().glodapYearRange).toBeNull();
  });
  it("the default (null) is not written to a link", () => {
    expect(collectShareableFilters(useMapStore.getState()).glodapYearRange).toBeUndefined();
  });
  it("round-trips through the share link, including the encoded ?s= envelope", () => {
    useMapStore.getState().setGlodapYearRange([1985, 2010]);
    const f = collectShareableFilters(useMapStore.getState());
    expect(f.glodapYearRange).toEqual(["1985", "2010"]);
    const raw = encodeShareState({
      camera: { longitude: 0, latitude: 0, zoom: 2, pitch: 0, bearing: 0 },
      layers: ["ocean-carbon", "glodap-points"], filters: f, openObjects: [], points: [], display: {},
    } as any);
    const decoded = decodeShareState(raw);
    // shareState.validateFilters silently drops a key it does not know — this is the guard against that.
    expect(decoded?.filters?.glodapYearRange).toEqual(["1985", "2010"]);
    useMapStore.getState().resetAllFilters();
    applyShareableFilters(decoded!.filters!);
    expect(useMapStore.getState().glodapYearRange).toEqual([1985, 2010]);
  });
  it("a reversed range is normalised and a malformed one is dropped (never hides data)", () => {
    useMapStore.getState().resetAllFilters();
    applyShareableFilters({ glodapYearRange: ["2010", "1985"] });
    expect(useMapStore.getState().glodapYearRange).toEqual([1985, 2010]);
    useMapStore.getState().resetAllFilters();
    for (const bad of [["2010"], ["a", "b"], "2010", [1985, 2010], ["19850", "2010"]]) {
      applyShareableFilters({ glodapYearRange: bad as any });
      expect(useMapStore.getState().glodapYearRange).toBeNull();
    }
  });
});

describe("GLODAP depth window labels", () => {
  it("cover exactly the standard depths the backend matches bottles in (DEPTH_WINDOWS)", () => {
    expect(Object.keys(GLODAP_DEPTH_WINDOWS)).toEqual(["0", "200", "500", "1000", "2000", "3000", "4000"]);
  });
  it("the numeric bounds spell the same windows as the labels", () => {
    expect(Object.keys(GLODAP_DEPTH_WINDOW_BOUNDS)).toEqual(Object.keys(GLODAP_DEPTH_WINDOWS));
    for (const [d, [lo, hi]] of Object.entries(GLODAP_DEPTH_WINDOW_BOUNDS)) {
      expect(GLODAP_DEPTH_WINDOWS[Number(d)]).toBe(`${lo}–${hi} m`);
    }
  });
  it("falls back to the plain depth for one without a window", () => {
    expect(glodapWindowLabel(200)).toBe("175–225 m");
    expect(glodapWindowLabel(750)).toBe("750 m");
  });
});
