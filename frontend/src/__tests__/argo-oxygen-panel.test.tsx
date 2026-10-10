// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";
import { cleanup, render, screen, fireEvent } from "@testing-library/react";
import { OxygenDeoxRow } from "../components/controls/sections/oceanClimatology/OxygenDeoxRow";
import { useMapStore } from "../store/mapStore";
import i18n from "../i18n";
import pl from "../../public/locales/pl/panels.json";
import de from "../../public/locales/de/panels.json";
import fr from "../../public/locales/fr/panels.json";

const oxygenMeta = {
  views: [
    { key: "recent", label: "Recent O₂ (2014–2018)", units: "µmol/kg", vmin: 0, vmax: 350, cmap: "oxy",
      ramp: [{ pos: 0, hex: "#000000" }, { pos: 1, hex: "#ffffff" }], depths: [0, 500, 2000], diverging: false },
    { key: "change", label: "Deoxygenation Δ (vs 1971-2000)", units: "µmol/kg", vmin: -60, vmax: 60, cmap: "diverging",
      ramp: [{ pos: 0, hex: "#ff0000" }, { pos: 1, hex: "#0000ff" }], depths: [0, 500, 2000], diverging: true },
  ],
  depths: [0, 500, 2000], attribution: "ISAS20",
};
const noop = () => {};
const renderRow = (extra = {}) => render(
  <OxygenDeoxRow expandedFilter="oxygen-deox" setExpandedFilter={noop} toggleExpand={noop} toggle={noop}
                 oxygenMeta={oxygenMeta} argoYearBounds={{ min: 2003, max: 2026 }} {...extra} />);
const pointsOnState = () => useMapStore.setState({
  oxygenDisplayMode: "points", activeLayers: new Set(["oxygen-deox", "argo-oxygen-points"]),
} as any);

describe("oxygen-deox panel: Measurements", () => {
  beforeEach(() => useMapStore.setState({
    activeLayers: new Set(["oxygen-deox"]), enabledLayerIds: null, oxygenDisplayMode: "field",
    oxygenView: "change", oxygenDepth: 500, argoOxygenYearRange: null,
  } as any));
  afterEach(cleanup);

  it("offers a third display option that turns the points on", () => {
    renderRow();
    fireEvent.click(screen.getByRole("button", { name: /measurements/i }));
    expect(useMapStore.getState().oxygenDisplayMode).toBe("points");
    expect(useMapStore.getState().activeLayers.has("argo-oxygen-points")).toBe(true);
  });

  it("does not offer Measurements while the layer is disabled or hidden", () => {
    useMapStore.setState({ enabledLayerIds: new Set(["oxygen-deox"]) } as any);
    renderRow();
    expect(screen.queryByRole("button", { name: /measurements/i })).toBeNull();
    expect(screen.queryByText(/Argo oxygen profiles/i)).toBeNull();      // nor its version note
  });

  it("in Measurements the view select is disabled, the scale is the Recent one and a note says why", () => {
    pointsOnState();
    renderRow();
    const view = screen.getByRole("combobox", { name: /view/i }) as HTMLSelectElement;
    expect(view.disabled).toBe(true);
    expect(screen.getByText(/absolute O₂/i)).toBeTruthy();                 // recentScaleNote (en)
    expect(screen.getByText("350")).toBeTruthy();                         // Recent vmax, not the Δ's 60
    expect(screen.queryByText("60")).toBeNull();
    expect(useMapStore.getState().oxygenView).toBe("change");              // the user's field view is kept
  });

  it("in Field mode the view select is enabled and the scale follows the chosen view", () => {
    renderRow();
    expect((screen.getByRole("combobox", { name: /view/i }) as HTMLSelectElement).disabled).toBe(false);
    expect(screen.queryByText(/absolute O₂/i)).toBeNull();
    expect(screen.getByText("60")).toBeTruthy();                          // the Δ scale
    expect(screen.queryByText("350")).toBeNull();
  });

  it("the depth note names the window of the selected depth, and loading is shown", () => {
    pointsOnState();
    renderRow({ argoLoading: true });
    expect(screen.getByText(/no good adjusted oxygen value in the 450–550 m range/i)).toBeTruthy();
    expect(screen.getByText(/loading measurements/i)).toBeTruthy();
  });

  it("the year range narrows and resets to all years", () => {
    pointsOnState();
    renderRow();
    fireEvent.change(screen.getByRole("combobox", { name: /from/i }), { target: { value: "2014" } });
    expect(useMapStore.getState().argoOxygenYearRange).toEqual([2014, 2026]);
    fireEvent.change(screen.getByRole("combobox", { name: /from/i }), { target: { value: "2003" } });
    expect(useMapStore.getState().argoOxygenYearRange).toBeNull();
  });

  it("an empty year range is not a failure", () => {
    pointsOnState();
    useMapStore.setState({ argoOxygenYearRange: [2003, 2003] } as any);
    renderRow({ argoEmpty: true });
    expect(screen.getByText(/no profiles in this year range/i)).toBeTruthy();
    expect(screen.queryByText(/unavailable/i)).toBeNull();
  });
});

describe("the Measurements note quotes the name the View select shows, in every locale", () => {
  beforeEach(() => {
    useMapStore.setState({ activeLayers: new Set(["oxygen-deox"]), enabledLayerIds: null, oxygenDisplayMode: "field",
      oxygenView: "recent", oxygenDepth: 500, argoOxygenYearRange: null } as any);
    for (const [lng, b] of Object.entries({ pl, de, fr })) i18n.addResourceBundle(lng, "panels", b, true, true);
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response("{}"))) as unknown as typeof fetch);
  });
  afterEach(async () => { cleanup(); await i18n.changeLanguage("en"); vi.unstubAllGlobals(); });

  it.each([["en", "Recent O₂ (2014–2018)"], ["pl", "Bieżący O₂ (2014–2018)"], ["de", "Aktueller O₂ (2014–2018)"], ["fr", "O₂ récent (2014–2018)"]])(
    "%s: the select's option is %s and the note names it", async (lng, label) => {
      await i18n.changeLanguage(lng);
      pointsOnState();
      renderRow();
      const select = screen.getAllByRole("combobox")[0] as HTMLSelectElement;
      expect(Array.from(select.options).map((o) => o.textContent)).toContain(label);
      expect(document.getElementById("argo-recent-note")?.textContent).toContain(label);
    });
});
