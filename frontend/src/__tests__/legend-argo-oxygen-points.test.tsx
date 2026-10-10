// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
/**
 * The BGC-Argo oxygen points layer has ONE legend entry, `id: "argo-oxygen-points"`, and LegendPanel resolves its
 * text as `layers.${id}.*` — a key with a dash. Text filed under a camel-cased `argoOxygenPoints` renders as
 * the raw key and no key-parity script notices. This renders the real panel against the real legend
 * bundles of all four locales and reads what is on screen.
 *
 * ⚠️ The test i18n instance bundles English `common`/`panels` only (the legend namespace is fetched over
 * HTTP in production), so the legend bundles are added here — from the same files production serves.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";

import i18n from "../i18n";
import { LegendPanel } from "../components/LegendPanel";
import { useMapStore } from "../store/mapStore";
import en from "../../public/locales/en/legend.json";
import pl from "../../public/locales/pl/legend.json";
import fr from "../../public/locales/fr/legend.json";
import de from "../../public/locales/de/legend.json";
import enPanels from "../../public/locales/en/panels.json";
import plPanels from "../../public/locales/pl/panels.json";
import frPanels from "../../public/locales/fr/panels.json";
import dePanels from "../../public/locales/de/panels.json";

const BUNDLES = { en, pl, fr, de } as const;
const PANELS = { en: enPanels, pl: plPanels, fr: frPanels, de: dePanels } as const;
type Loc = keyof typeof BUNDLES;

beforeEach(() => {
  for (const [lng, bundle] of Object.entries(BUNDLES)) i18n.addResourceBundle(lng, "legend", bundle, true, true);
  vi.stubGlobal("matchMedia", vi.fn(() => ({
    matches: false, media: "", onchange: null,
    addListener: () => {}, removeListener: () => {},
    addEventListener: () => {}, removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia);
  vi.stubGlobal("fetch", vi.fn(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve({}) }),
  ) as unknown as typeof fetch);
});
afterEach(async () => {
  cleanup();
  useMapStore.getState().setEnabledLayerIds(null);
  await i18n.changeLanguage("en");
  vi.restoreAllMocks();
});

const open = async (lng: Loc, enabled: string[] | null) => {
  await i18n.changeLanguage(lng);
  useMapStore.getState().setEnabledLayerIds(enabled ? new Set(enabled) : null);
  return render(<LegendPanel onClose={() => {}} />);
};

describe.each(Object.keys(BUNDLES) as Loc[])("BGC-Argo oxygen points legend, %s", (lng) => {
  const L = BUNDLES[lng].layers["argo-oxygen-points"];

  it("the Reference row shows translated copy, not the i18n key, with the source, DOI, licence and acknowledgement", async () => {
    await open(lng, ["oxygen-deox", "argo-oxygen-points"]);
    const row = document.getElementById("legend-layer-argo-oxygen-points");
    expect(row).not.toBeNull();
    const text = row!.textContent ?? "";
    expect(text).toContain(L.label);
    expect(text).toContain(L.description);
    expect(text).toContain(L.limitations);
    expect(text).toMatch(/Argo GDAC/);
    expect(text).toMatch(/10\.17882\/42182/);
    expect(text).toContain("CC BY 4.0");
    // Argo requires its acknowledgement verbatim, in every locale.
    expect(text).toContain("made freely available by the International Argo Program");
    expect(text).not.toContain("layers.argo-oxygen-points");
    expect(within(row!).getByRole("link", { name: /Argo GDAC — Argo \(2000\)/ })).toHaveAttribute(
      "href", "https://doi.org/10.17882/42182");
  });

  it("the copy names the panel exactly as the toggle shows it in this locale, never the English name", async () => {
    const toggle = PANELS[lng].layers.oxygenDeox.toggle;                 // the label the user clicks in the left panel
    expect(L.description).toContain(lng === "en" ? "Ocean Oxygen" : toggle);
    expect(PANELS[lng].tooltip.descriptions["argo-oxygen-points"]).toContain(
      lng === "en" ? "Ocean Oxygen" : toggle);
    if (lng !== "en") {
      expect(L.description).not.toContain("Ocean Oxygen");
      expect(PANELS[lng].tooltip.descriptions["argo-oxygen-points"]).not.toContain("Ocean Oxygen");
      expect(L.description).toContain(PANELS[lng].controls.fieldLayer.measurements);   // and the option, as the select shows it
    }
    await open(lng, ["oxygen-deox", "argo-oxygen-points"]);
    expect(document.getElementById("legend-layer-argo-oxygen-points")!.textContent).toContain(L.description);
  });

  it("the layer has exactly one legend row", async () => {
    await open(lng, ["oxygen-deox", "argo-oxygen-points"]);
    expect(document.querySelectorAll("#legend-layer-argo-oxygen-points")).toHaveLength(1);
  });

  it("the Verify tab names the GDAC file, the Euro-Argo float page, the QC rule and the field's vintage", async () => {
    await open(lng, ["oxygen-deox", "argo-oxygen-points"]);
    fireEvent.click(screen.getByRole("button", { name: BUNDLES[lng].tabs.verify }));
    const text = document.body.textContent ?? "";
    expect(text).toContain(BUNDLES[lng].verify.argoOxygenPoints_title);
    expect(text).toContain(BUNDLES[lng].verify.argoOxygenPoints);
    for (const needle of ["data-argo.ifremer.fr/dac/<DAC>/<WMO>/", "/profiles/SD<WMO>_<cycle>.nc", "fleetmonitoring.euro-argo.eu/float/<WMO>",
      "CYCLE_NUMBER", "DOXY_ADJUSTED_QC 1", "PRES_ADJUSTED", "UNESCO 1983", "175", "225", "ISAS20", "10.17882/42182", "CC BY 4.0",
      "made freely available by the International Argo Program"]) {
      expect(BUNDLES[lng].verify.argoOxygenPoints).toContain(needle);
    }
    expect(text).not.toContain("verify.argoOxygenPoints");
  });

  it("the Dates tab lists the layer as weekly, with the date the worker last loaded it", async () => {
    // The key is the one the worker writes to sync_log (`argo-doxy`); the panel reads it from /api/v1/sync/status.
    vi.stubGlobal("fetch", vi.fn(() =>
      Promise.resolve({ ok: true, json: () => Promise.resolve({ "argo-doxy": "2026-10-07" }) })) as unknown as typeof fetch);
    await open(lng, ["oxygen-deox", "argo-oxygen-points"]);
    fireEvent.click(screen.getByRole("button", { name: BUNDLES[lng].tabs.dates }));
    const item = (await screen.findAllByText(/BGC-Argo Oxygen Measurements/)).find((el) => el.closest("li"))!.closest("li")!;
    expect(item.textContent).toMatch(/weekly/i);
    await vi.waitFor(() => expect(item.textContent).toContain("(2026-10-07)"));
  });

  it("retiring the layer takes its copy out of all three tabs", async () => {
    await open(lng, ["argo", "oxygen-deox"]);
    expect(document.getElementById("legend-layer-argo-oxygen-points")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: BUNDLES[lng].tabs.verify }));
    expect(document.body.textContent).not.toContain(BUNDLES[lng].verify.argoOxygenPoints);
    fireEvent.click(screen.getByRole("button", { name: BUNDLES[lng].tabs.dates }));
    expect(document.body.textContent).not.toMatch(/BGC-Argo Oxygen Measurements/);
  });
});
