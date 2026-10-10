// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
import { describe, expect, it, beforeEach } from "vitest";
import { rampColor } from "../components/map3d/colors";
import {
  argoOxygenColor, oxygenDrawing, oxygenNeedsFieldTiles, ARGO_NO_VALUE_RGBA, ARGO_DEPTH_WINDOW_BOUNDS,
} from "../utils/argoOxygenPoints";
import { useMapStore } from "../store/mapStore";
import { collectShareableFilters, applyShareableFilters, ARGO_OXYGEN_YEAR_RANGE_KEY } from "../types/filterRegistry";

const meta = { views: [
  { key: "recent", vmin: 0, vmax: 350, ramp: [{ pos: 0, hex: "#000000" }, { pos: 1, hex: "#ffffff" }] },
  { key: "change", vmin: -60, vmax: 60, ramp: [{ pos: 0, hex: "#ff0000" }, { pos: 1, hex: "#0000ff" }] },
] };

describe("argo oxygen points", () => {
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

  it("windows mirror the backend DEPTH_WINDOWS", () => {
    expect(Object.keys(ARGO_DEPTH_WINDOW_BOUNDS).map(Number)).toEqual([0, 50, 100, 200, 500, 1000, 1500, 2000]);
    expect(ARGO_DEPTH_WINDOW_BOUNDS[2000]).toEqual([1900, 2100]);
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
