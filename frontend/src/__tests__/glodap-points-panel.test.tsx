// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";

import { OceanCarbonRow } from "../components/controls/sections/oceanClimatology/OceanCarbonRow";
import { useMapStore } from "../store/mapStore";
import { carbonDrawing } from "../utils/glodapPoints";
import { nextActiveForLink } from "../components/map3d/linkLayerActivation";
import { collectShareableDisplay, applyShareableDisplay } from "../types/displayRegistry";
import { encodeShareState, decodeShareState } from "../utils/shareState";

const ramp = [{ pos: 0, hex: "#fdedb0" }, { pos: 1, hex: "#3e184e" }];
const meta = {
  variables: ["dic", "cant"].map((key) => ({ key, label: key, units: "µmol/kg", vmin: 0, vmax: 1, cmap: "x", baseline: "b", depths: [0, 200], ramp })),
  depths: [0, 200],
};
// The panel's own `toggle` prop is what flips a layer in the app (Map3DControls: store toggle + analytics).
const toggle = (id: string) => useMapStore.getState().toggleLayer(id as any);
const row = (bounds: { min: number; max: number } | null = { min: 1972, max: 2023 }, loading = false) => (
  <OceanCarbonRow expandedFilter="ocean-carbon" setExpandedFilter={() => {}} toggleExpand={() => {}} toggle={toggle}
    carbonMeta={meta} glodapYearBounds={bounds} glodapLoading={loading} />
);
// Measurements is the third option of the Field / Hexagons / Measurements display switch (2026-10-06).
const MEASUREMENTS = "Measurements";
const option = (name: string) => screen.queryByRole("button", { name }) as HTMLButtonElement | null;
const choose = (name: string) => fireEvent.click(screen.getByRole("button", { name }));
const modeNow = () => useMapStore.getState().carbonDisplayMode;
const hasPoints = () => useMapStore.getState().activeLayers.has("glodap-points");
/** What Map3D would draw for the store's current state (the same function Map3D calls). */
const drawn = () => {
  const s = useMapStore.getState();
  return carbonDrawing(s.activeLayers.has("ocean-carbon"), s.carbonDisplayMode, s.activeLayers.has("glodap-points"));
};

beforeEach(() => {
  useMapStore.getState().resetAllFilters();
  useMapStore.setState({ activeLayers: new Set(["ocean-carbon"]), carbonVariable: "dic", carbonDepth: 200,
    carbonDisplayMode: "field", enabledLayerIds: null } as any);
});
afterEach(cleanup);

describe("Measurements option of the ocean-carbon display switch", () => {
  it("always shows the version note; there is no separate checkbox any more", () => {
    render(row());
    expect(screen.getByText(/Field: GLODAPv2\.2016b mapped climatology, TCO₂ and pH normalised to 2002/)).toBeTruthy();
    expect(screen.queryByLabelText(/GLODAPv3 bottles/)).toBeNull();      // the old checkbox label
    expect(screen.getAllByRole("checkbox")).toHaveLength(1);              // only the layer row's own toggle
    expect([...screen.getAllByRole("button")].map((b) => b.textContent)
      .filter((t) => ["Field", "Hexagons", MEASUREMENTS].includes(t ?? ""))).toEqual(["Field", "Hexagons", MEASUREMENTS]);
  });

  it("choosing Measurements draws the points and removes the field and the hex view; Field and Hexagons remove the points", () => {
    render(row());
    expect(drawn()).toEqual({ field: true, hexes: false, points: false });
    expect(hasPoints()).toBe(false);

    choose(MEASUREMENTS);
    expect(modeNow()).toBe("points");
    expect(hasPoints()).toBe(true);
    expect(useMapStore.getState().activeLayers.has("ocean-carbon")).toBe(true);
    expect(drawn()).toEqual({ field: false, hexes: false, points: true });
    expect(option(MEASUREMENTS)!.getAttribute("aria-pressed")).toBe("true");

    choose("Hexagons");
    expect(modeNow()).toBe("hexes");
    expect(hasPoints()).toBe(false);
    expect(drawn()).toEqual({ field: false, hexes: true, points: false });

    choose(MEASUREMENTS);
    choose("Field");
    expect(modeNow()).toBe("field");
    expect(hasPoints()).toBe(false);
    expect(drawn()).toEqual({ field: true, hexes: false, points: false });
  });

  it("turning the field layer itself off draws nothing, in every mode", () => {
    choose_mode_then_off("points");
    choose_mode_then_off("hexes");
    choose_mode_then_off("field");
    function choose_mode_then_off(m: "field" | "hexes" | "points") {
      useMapStore.getState().setCarbonDisplayMode(m);
      act(() => useMapStore.getState().toggleLayer("ocean-carbon" as any));
      expect(drawn()).toEqual({ field: false, hexes: false, points: false });
      act(() => useMapStore.getState().toggleLayer("ocean-carbon" as any));
    }
  });

  it("keeps the selectors, the colour scale and the notes visible in Measurements mode", () => {
    render(row());
    choose(MEASUREMENTS);
    expect(screen.getByText("Variable")).toBeTruthy();
    expect(screen.getByText("Depth")).toBeTruthy();
    expect(screen.getByText(/^Scale/)).toBeTruthy();
    expect(screen.getByText(/Field: GLODAPv2\.2016b mapped climatology/)).toBeTruthy();
    expect(screen.getByText(/Grey: no acceptable/)).toBeTruthy();
    expect(screen.getByLabelText("From")).toBeTruthy();
  });

  it("year range, grey note and loading note appear only in Measurements mode", () => {
    const { rerender } = render(row());
    expect(screen.queryByLabelText("From")).toBeNull();
    expect(screen.queryByText(/Grey: no acceptable/)).toBeNull();
    act(() => useMapStore.getState().setCarbonDisplayMode("points"));
    rerender(row(null, true));
    expect(screen.getByText("Loading measurements…")).toBeTruthy();
    expect(screen.queryByLabelText("From")).toBeNull(); // no bounds until the document has loaded
    rerender(row());
    expect(screen.queryByText("Loading measurements…")).toBeNull();
    expect(screen.getByText("Grey: no acceptable (WOCE flag 2) bottle in the 175–225 m range around this depth.")).toBeTruthy();
    act(() => useMapStore.getState().setCarbonDisplayMode("hexes"));
    rerender(row());
    expect(screen.queryByLabelText("From")).toBeNull();
    expect(screen.queryByText(/Grey: no acceptable/)).toBeNull();
  });

  it("says the points are grey for Cant instead of the window note", () => {
    useMapStore.getState().setCarbonDisplayMode("points");
    useMapStore.setState({ carbonVariable: "cant" } as any);
    render(row());
    expect(screen.getByText(/Bottles carry no anthropogenic CO₂/)).toBeTruthy();
    expect(screen.queryByText(/Grey: no acceptable/)).toBeNull();
  });

  it("year selects write the range; the full span is stored as null; Reset clears it", () => {
    useMapStore.getState().setCarbonDisplayMode("points");
    render(row());
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "1990" } });
    expect(useMapStore.getState().glodapYearRange).toEqual([1990, 2023]);
    fireEvent.change(screen.getByLabelText("To"), { target: { value: "2000" } });
    expect(useMapStore.getState().glodapYearRange).toEqual([1990, 2000]);
    // Crossing the ends swaps them rather than storing an empty range.
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2010" } });
    expect(useMapStore.getState().glodapYearRange).toEqual([2000, 2010]);
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "1972" } });
    fireEvent.change(screen.getByLabelText("To"), { target: { value: "2023" } });
    expect(useMapStore.getState().glodapYearRange).toBeNull();
    act(() => useMapStore.getState().setGlodapYearRange([1990, 2000]));
    fireEvent.click(screen.getByText("Reset"));
    expect(useMapStore.getState().glodapYearRange).toBeNull();
  });
});

describe("whatever switches glodap-points on also selects Measurements (so the field does not come back on top)", () => {
  it("the layer toggle, setActiveLayers and a link/search activation all land in Measurements mode", () => {
    useMapStore.getState().setCarbonDisplayMode("hexes");
    act(() => useMapStore.getState().toggleLayer("glodap-points" as any));
    expect(modeNow()).toBe("points");
    expect(drawn()).toEqual({ field: false, hexes: false, points: true });
    act(() => useMapStore.getState().toggleLayer("glodap-points" as any));
    expect(modeNow()).toBe("field");                       // switched off elsewhere: the field returns, no blank map
    expect(drawn().field).toBe(true);

    // the effect that opens a link's panel: OPENABLE glodap-points + alsoActivate ocean-carbon, merged onto the live set
    useMapStore.getState().setCarbonDisplayMode("hexes");
    const live = useMapStore.getState().activeLayers as ReadonlySet<string>;
    const next = nextActiveForLink(live, [["glodap-points", "49UF20150620_4511_1"]], [], () => true, () => false,
      (l) => (l === "glodap-points" ? ["ocean-carbon"] : []));
    act(() => useMapStore.getState().setActiveLayers(next as any));
    expect(modeNow()).toBe("points");
    expect(drawn()).toEqual({ field: false, hexes: false, points: true });

    // a layer list restored wholesale (saved session / link `layers`)
    act(() => useMapStore.getState().setActiveLayers(new Set(["ocean-carbon"]) as any));
    expect(modeNow()).toBe("field");
    act(() => useMapStore.getState().setActiveLayers(new Set(["ocean-carbon", "glodap-points"]) as any));
    expect(modeNow()).toBe("points");
    act(() => useMapStore.getState().disableAllLayers());
    expect(modeNow()).toBe("field");
  });

  it("a share link round-trips the mode: sender in Measurements, recipient lands in Measurements, with no field underneath", () => {
    useMapStore.getState().setActiveLayers(new Set(["ocean-carbon", "glodap-points"]) as any);
    expect(modeNow()).toBe("points");
    const display = collectShareableDisplay(useMapStore.getState());
    expect(display.carbonDisplayMode).toBe("points");
    const raw = encodeShareState({
      camera: { longitude: 0, latitude: 0, zoom: 2, pitch: 0, bearing: 0 },
      layers: ["ocean-carbon", "glodap-points"], filters: {}, openObjects: [], points: [], display,
    } as any);
    const decoded = decodeShareState(raw);
    expect(decoded?.display?.carbonDisplayMode).toBe("points");   // validateDisplay must not drop the new value

    // the recipient: a fresh store, the bootstrap order (display first, then the layer list)
    useMapStore.setState({ activeLayers: new Set(), carbonDisplayMode: "field" } as any);
    applyShareableDisplay(decoded!.display!);
    useMapStore.getState().setActiveLayers(new Set(decoded!.layers!) as any);
    expect(modeNow()).toBe("points");
    expect(drawn()).toEqual({ field: false, hexes: false, points: true });
  });

  it("an OLD link (glodap-points in the layers, no display field) opens in Measurements too", () => {
    useMapStore.getState().setActiveLayers(new Set(["ocean-carbon", "glodap-points"]) as any);
    expect(modeNow()).toBe("points");
    expect(drawn().field).toBe(false);
  });

  it("Field and Hexagons are not written to a link as Measurements, and the default stays out of it", () => {
    expect(collectShareableDisplay(useMapStore.getState()).carbonDisplayMode).toBeUndefined();
    useMapStore.getState().setCarbonDisplayMode("hexes");
    expect(collectShareableDisplay(useMapStore.getState()).carbonDisplayMode).toBe("hexes");
  });
});

describe("Measurements switch respects layer_config and HIDDEN_LAYERS", () => {
  const enabledWithout = (...ids: string[]) =>
    new Set(["ocean-carbon", "glodap-points"].filter((i) => !ids.includes(i)));

  it("is offered while glodap-points is enabled, and while the config has not loaded (null = allow all)", () => {
    useMapStore.setState({ enabledLayerIds: enabledWithout() } as any);
    const { unmount } = render(row());
    expect(option(MEASUREMENTS)).toBeTruthy();
    unmount();
    useMapStore.setState({ enabledLayerIds: null } as any);
    render(row());
    expect(option(MEASUREMENTS)).toBeTruthy();
  });

  it("is not rendered at all, nor its version note, when glodap-points is disabled or hidden", () => {
    // layer_config disabled/retired and HIDDEN_LAYERS both end up as "not in enabledLayerIds"
    // (utils/layerConfig applyHiddenLayers); the other panel controls stay.
    useMapStore.setState({ enabledLayerIds: enabledWithout("glodap-points") } as any);
    render(row());
    expect(option(MEASUREMENTS)).toBeNull();
    expect(screen.queryByText(/Field: GLODAPv2\.2016b mapped climatology/)).toBeNull();
    expect(screen.getByText("Variable")).toBeTruthy();
    expect(option("Field")).toBeTruthy();                  // the other two options stay
    expect(option("Hexagons")).toBeTruthy();
  });

  it("the store refuses Measurements for a disabled layer, so a stale click cannot draw it", () => {
    useMapStore.setState({ enabledLayerIds: enabledWithout("glodap-points") } as any);
    act(() => useMapStore.getState().setCarbonDisplayMode("points"));
    expect(modeNow()).toBe("field");
    expect(hasPoints()).toBe(false);
    expect(drawn()).toEqual({ field: true, hexes: false, points: false });
  });

  it("a layer that is hidden after it was on loses its option and falls back to the field", () => {
    act(() => useMapStore.getState().setCarbonDisplayMode("points"));
    act(() => useMapStore.getState().setEnabledLayerIds(enabledWithout("glodap-points")));
    expect(useMapStore.getState().activeLayers.has("glodap-points")).toBe(false);
    expect(modeNow()).toBe("field");
    expect(drawn().field).toBe(true);
    render(row());
    expect(option(MEASUREMENTS)).toBeNull();
    expect(screen.queryByLabelText("From")).toBeNull();
  });
});
