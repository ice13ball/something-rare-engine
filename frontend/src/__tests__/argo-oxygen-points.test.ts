// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
import { describe, expect, it, beforeEach } from "vitest";
import { rampColor } from "../components/map3d/colors";
import {
  argoProfileKey, argoOxygenPoints, argoOxygenColor, oxygenDrawing, oxygenNeedsFieldTiles, withArgoDoc,
  argoYearBounds, ARGO_NO_VALUE_RGBA, ARGO_DEPTH_WINDOW_BOUNDS, type ArgoOxygenDoc,
} from "../utils/argoOxygenPoints";
import { useMapStore } from "../store/mapStore";
import { collectShareableFilters, applyShareableFilters, ARGO_OXYGEN_YEAR_RANGE_KEY } from "../types/filterRegistry";

const doc: ArgoOxygenDoc = {
  product: "BGC-Argo DOXY", depth: 500, window: [450, 550], units: "µmol/kg", n: 3,
  floats: ["aoml_1900722", "coriolis_3902120"], fi: [0, 0, 1], cycle: [1, 2, 2], descending: [2],
  lon: [73.389, 73.528, 10.5], lat: [-40.316, -40.39, -23.93], year: [2006, 2006, 2018], value: [200, null, 190],
};
const meta = { views: [
  { key: "recent", vmin: 0, vmax: 350, ramp: [{ pos: 0, hex: "#000000" }, { pos: 1, hex: "#ffffff" }] },
  { key: "change", vmin: -60, vmax: 60, ramp: [{ pos: 0, hex: "#ff0000" }, { pos: 1, hex: "#0000ff" }] },
] };

describe("argo oxygen points", () => {
  it("argoProfileKey matches the backend for 000, 042, 1000 and descending", () => {
    expect(argoProfileKey("aoml_1901466", 0, false)).toBe("aoml_1901466_000");
    expect(argoProfileKey("aoml_1900722", 42, false)).toBe("aoml_1900722_042");
    expect(argoProfileKey("aoml_5904479", 1000, false)).toBe("aoml_5904479_1000");
    expect(argoProfileKey("coriolis_3902120", 2, true)).toBe("coriolis_3902120_002D");
  });

  it("builds keys from the document, grey points first, inclusive year range", () => {
    const pts = argoOxygenPoints(doc, null);
    expect(pts.map((p) => p.key)).toEqual(["aoml_1900722_002", "aoml_1900722_001", "coriolis_3902120_002D"]);
    expect(argoOxygenPoints(doc, [2018, 2018]).map((p) => p.key)).toEqual(["coriolis_3902120_002D"]);
    expect(argoOxygenPoints(doc, [1990, 1991])).toEqual([]);
  });

  it("colours in the Recent ramp whatever field view is selected (never the change ramp)", () => {
    const want = rampColor(200, 0, 350, meta.views[0].ramp, 235);
    expect(argoOxygenColor(200, meta)).toEqual(want);
    expect(argoOxygenColor(200, meta)).not.toEqual(rampColor(200, -60, 60, meta.views[1].ramp, 235));
    expect(argoOxygenColor(null, meta)).toEqual(ARGO_NO_VALUE_RGBA);
    expect(argoOxygenColor(200, { views: [meta.views[1]] })).toEqual(ARGO_NO_VALUE_RGBA);   // no recent view: grey
  });

  it("Measurements replace the field and the hexes, and no field tiles are fetched for them", () => {
    expect(oxygenDrawing(true, "points", true)).toEqual({ field: false, hexes: false, points: true });
    expect(oxygenDrawing(true, "points", false)).toEqual({ field: false, hexes: false, points: false });
    expect(oxygenDrawing(true, "field", true)).toEqual({ field: true, hexes: false, points: false });
    expect(oxygenNeedsFieldTiles(true, "points")).toBe(false);
    expect(oxygenNeedsFieldTiles(true, "field")).toBe(true);
    expect(oxygenNeedsFieldTiles(true, "hexes")).toBe(true);      // unchanged behaviour of the hex view
  });

  it("points use the document of the selected depth only", () => {
    // the 500 m document arrives AFTER the user switched to 1000 m: it is filed under 500, never under 1000
    const docs = withArgoDoc({}, { ...doc, depth: 500 });
    expect(docs[1000]).toBeUndefined();
    expect(docs[500].depth).toBe(500);
  });

  it("the same key reopens the same profile after a year filter reorders the points", () => {
    const all = argoOxygenPoints(doc, null);
    const filtered = argoOxygenPoints(doc, [2018, 2018]);
    const key = all.find((p) => p.i === 2)!.key;
    expect(filtered[0].key).toBe(key);
    expect(filtered[0].i).toBe(2);                      // the doc row is stable; the PICK index (0) is not
  });

  it("windows mirror the backend DEPTH_WINDOWS and year bounds span every loaded document", () => {
    expect(Object.keys(ARGO_DEPTH_WINDOW_BOUNDS).map(Number)).toEqual([0, 50, 100, 200, 500, 1000, 1500, 2000]);
    expect(ARGO_DEPTH_WINDOW_BOUNDS[2000]).toEqual([1900, 2100]);
    expect(argoYearBounds([doc, { ...doc, depth: 0, year: [2003, 2026, 2010] }])).toEqual({ min: 2003, max: 2026 });
    expect(argoYearBounds([])).toBeNull();
  });
});

describe("store: Measurements mode for oxygen-deox", () => {
  beforeEach(() => {
    useMapStore.setState({ activeLayers: new Set(["oxygen-deox"]), enabledLayerIds: null,
                           oxygenDisplayMode: "field", oxygenView: "change", carbonDisplayMode: "field" } as any);
  });

  it("choosing Measurements switches the points layer on and keeps the user's field view", () => {
    useMapStore.getState().setOxygenDisplayMode("points");
    const s = useMapStore.getState();
    expect(s.activeLayers.has("argo-oxygen-points")).toBe(true);
    expect(s.oxygenView).toBe("change");                   // untouched: back to Field restores Δ
    s.setOxygenDisplayMode("field");
    expect(useMapStore.getState().activeLayers.has("argo-oxygen-points")).toBe(false);
    expect(useMapStore.getState().oxygenView).toBe("change");
  });

  it("a link or the layer list that turns the points on lands in Measurements; glodap is independent", () => {
    useMapStore.getState().toggleLayer("argo-oxygen-points");
    expect(useMapStore.getState().oxygenDisplayMode).toBe("points");
    expect(useMapStore.getState().carbonDisplayMode).toBe("field");
    useMapStore.getState().toggleLayer("argo-oxygen-points");
    expect(useMapStore.getState().oxygenDisplayMode).toBe("field");
  });

  it("every layer-writing action normalises the mode, and ocean-carbon's own mode is unaffected", () => {
    useMapStore.getState().setActiveLayers(new Set(["oxygen-deox", "argo-oxygen-points"]) as any);   // a share link
    expect(useMapStore.getState().oxygenDisplayMode).toBe("points");
    useMapStore.getState().setEnabledLayerIds(new Set(["oxygen-deox"]) as any);                      // the layer is hidden here
    expect(useMapStore.getState().activeLayers.has("argo-oxygen-points")).toBe(false);
    expect(useMapStore.getState().oxygenDisplayMode).toBe("field");
    useMapStore.setState({ enabledLayerIds: null, oxygenDisplayMode: "points" } as any);              // a stale mode, no layer
    useMapStore.getState().toggleLayer("woa-climatology");
    expect(useMapStore.getState().oxygenDisplayMode).toBe("field");
    useMapStore.getState().setOxygenDisplayMode("points");
    useMapStore.getState().disableAllLayers();
    expect(useMapStore.getState().oxygenDisplayMode).toBe("field");
    useMapStore.getState().toggleLayer("glodap-points");                                              // glodap leaves oxygen alone
    expect(useMapStore.getState().carbonDisplayMode).toBe("points");
    expect(useMapStore.getState().oxygenDisplayMode).toBe("field");
  });

  it("Measurements cannot be chosen while the layer is disabled or hidden", () => {
    useMapStore.setState({ enabledLayerIds: new Set(["oxygen-deox"]) } as any);
    useMapStore.getState().setOxygenDisplayMode("points");
    expect(useMapStore.getState().oxygenDisplayMode).toBe("field");
  });

  it("the year range round-trips through a share link and resets with the filters", () => {
    useMapStore.getState().setArgoOxygenYearRange([2014, 2018]);
    const f = collectShareableFilters(useMapStore.getState());
    expect(f[ARGO_OXYGEN_YEAR_RANGE_KEY]).toEqual(["2014", "2018"]);
    useMapStore.getState().resetAllFilters();
    expect(useMapStore.getState().argoOxygenYearRange).toBeNull();
    applyShareableFilters(f);
    expect(useMapStore.getState().argoOxygenYearRange).toEqual([2014, 2018]);
  });
});
