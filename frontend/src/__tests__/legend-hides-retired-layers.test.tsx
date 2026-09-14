// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// Retiring a layer server-side (layer_config.status = 'disabled') removed it
// from the map and from the legend's Reference tab for free — Reference maps
// over LAYER_STRUCT and has always gated on `enabledLayerIds`.
//
// ⛔ The Dates & Freshness and Verify Data tabs are hand-written <li> lists
// with no registry behind them. When AIS was retired on 2026-09-14 they went
// on documenting "Live Vessels (AIS)" as a live 60-minute feed and "Dark
// Vessels (SAR×AIS)" as a 6-hourly correlation — in production, after both
// layers were already gone from the map. A reader would have gone looking for
// a layer the platform no longer serves, and read a cross-check procedure for
// data it no longer has.
//
// Nothing can hold a hand-written list to a registry it does not consult, so
// this test holds the RENDER to the store instead: with a layer absent from
// `enabledLayerIds`, its copy must not appear in ANY tab.
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup, screen, fireEvent } from "@testing-library/react";
import { LegendPanel } from "../components/LegendPanel";
import { useMapStore } from "../store/mapStore";

const RETIRED = ["ais-live", "vessel-events"];
// Anything still served. Its presence is the POSITIVE CONTROL: without it,
// "the AIS copy is absent" would also pass on a panel that rendered nothing.
const STILL_SERVED = ["argo", "hydrothermal-vents", "seamounts", "contracts"];

const AIS_COPY = [/Live Vessels \(AIS\)/, /Dark Vessels \(SAR/, /AISStream/i];

function openPanel(enabled: Set<string> | null) {
  useMapStore.getState().setEnabledLayerIds(enabled);
  return render(<LegendPanel onClose={() => {}} />);
}

// ⚠️ The test i18n instance bundles only some namespaces, so the tab buttons
// render as their raw keys ("tabs.dates"). That is fine here: every string this
// test asserts on is hardcoded English JSX, which is exactly the copy that had
// no registry behind it and is the reason this file exists.
const tab = (key: string) => {
  const b = screen.getAllByRole("button").find((x) => (x.textContent ?? "").trim() === key);
  if (!b) throw new Error(`tab not found: ${key}`);
  fireEvent.click(b);
};

beforeEach(() => {
  // jsdom ships no matchMedia; the panel asks it for the reduced-motion
  // preference on mount. Answer "no preference" — irrelevant to this test.
  vi.stubGlobal("matchMedia", vi.fn(() => ({
    matches: false, media: "", onchange: null,
    addListener: () => {}, removeListener: () => {},
    addEventListener: () => {}, removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia);
  // The panel fetches sync dates; an empty object is a valid, boring answer.
  vi.stubGlobal("fetch", vi.fn(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve({}) }),
  ) as unknown as typeof fetch);
});
afterEach(() => { cleanup(); useMapStore.getState().setEnabledLayerIds(null); vi.restoreAllMocks(); });

describe("the legend never documents a layer the platform stopped serving", () => {
  // Each tab needs its OWN positive control — a string that must be on screen
  // when that tab rendered properly. Without one, "the AIS copy is absent"
  // also passes on a tab that rendered nothing at all.
  const TABS: [string, RegExp][] = [
    ["tabs.layers", /layers\.argo/],
    ["tabs.dates", /Seabed Substrate/],
    ["tabs.verify", /Bathymetry/],
  ];

  it.each(TABS)("%s: AIS copy is gone once the layers are retired", (key, control) => {
    openPanel(new Set(STILL_SERVED));
    tab(key);
    const text = document.body.textContent ?? "";

    // ⛔ Positive control FIRST.
    expect(text.length).toBeGreaterThan(500);
    expect(text).toMatch(control);

    for (const pattern of AIS_COPY) expect(text).not.toMatch(pattern);
  });

  it("still shows the AIS copy while those layers ARE served", () => {
    openPanel(new Set([...STILL_SERVED, ...RETIRED]));
    tab("tabs.dates");
    expect(document.body.textContent ?? "").toMatch(/Live Vessels \(AIS\)/);
  });

  it("shows everything when the config has not loaded (null means unknown, not empty)", () => {
    // A failed or pending layer-config fetch must not blank the documentation.
    openPanel(null);
    tab("tabs.verify");
    expect(document.body.textContent ?? "").toMatch(/Dark Vessels \(SAR/);
  });
});
