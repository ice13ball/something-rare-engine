// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
/**
 * The GLODAPv3 points layer has ONE legend entry, `id: "glodap-points"`, and LegendPanel resolves its
 * text as `layers.${id}.*` — a key with a dash. Text filed under a camel-cased `glodapPoints` renders as
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

const BUNDLES = { en, pl, fr, de } as const;
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

describe.each(Object.keys(BUNDLES) as Loc[])("GLODAPv3 points legend, %s", (lng) => {
  const L = BUNDLES[lng].layers["glodap-points"];

  it("the Reference row shows translated copy, not the i18n key", async () => {
    await open(lng, ["ocean-carbon", "glodap-points"]);
    const row = document.getElementById("legend-layer-glodap-points");
    expect(row).not.toBeNull();
    const text = row!.textContent ?? "";
    expect(text).toContain(L.label);
    expect(text).toContain(L.description);
    expect(text).toContain(L.limitations);
    // The dataset's licence terms are on the row: accession, DOI and licence.
    expect(text).toContain("0315582");
    expect(text).toContain("doi:10.25921/m6tp-mj50");
    expect(text).toContain("CC BY 4.0");
    expect(text).not.toContain("layers.glodap-points");
    // Ship names carry their own credit (NVS C17, CC BY 4.0).
    expect(within(row!).getByRole("link", { name: /C17/ })).toHaveAttribute(
      "href", "https://vocab.nerc.ac.uk/collection/C17/current/");
  });

  it("the Verify tab names the cross-check, the vintage gap and the ship-name credit", async () => {
    await open(lng, ["ocean-carbon", "glodap-points"]);
    fireEvent.click(screen.getByRole("button", { name: BUNDLES[lng].tabs.verify }));
    const text = document.body.textContent ?? "";
    expect(text).toContain(BUNDLES[lng].verify.glodapPoints_title);
    expect(text).toContain(BUNDLES[lng].verify.glodapPoints);
    // A bare host is not a cross-check: the text gives the CCHDO cruise URL pattern and the NCEI cruise table.
    for (const needle of ["cchdo.ucsd.edu/cruise/<EXPOCODE>", "oceans/GLODAPv3/cruise_table_v3.html", "EXPOCODE", "200 m", "GLODAPv2.2016b", "C17", "CC BY 4.0", "0315582"]) {
      expect(BUNDLES[lng].verify.glodapPoints).toContain(needle);
    }
    expect(text).not.toContain("verify.glodapPoints");
  });

  it("the Dates tab lists the layer, with the date the worker last loaded it", async () => {
    // The key is the one the worker writes to sync_log (`glodap-bottles`); the panel reads it from /api/v1/sync/status.
    const syncDatesUrl = vi.fn();
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      syncDatesUrl(url);
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ "glodap-bottles": "2026-10-07" }) });
    }) as unknown as typeof fetch);
    await open(lng, ["ocean-carbon", "glodap-points"]);
    fireEvent.click(screen.getByRole("button", { name: BUNDLES[lng].tabs.dates }));
    const item = (await screen.findAllByText("GLODAPv3 Bottle Measurements")).find((el) => el.closest("li"))!.closest("li")!;
    expect(item.textContent).toContain("GLODAPv3, 2026");
    await vi.waitFor(() => expect(item.textContent).toContain("(2026-10-07)"));
  });

  it("retiring the layer takes its copy out of all three tabs", async () => {
    await open(lng, ["argo", "ocean-carbon"]);
    expect(document.getElementById("legend-layer-glodap-points")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: BUNDLES[lng].tabs.verify }));
    expect(document.body.textContent).not.toContain(BUNDLES[lng].verify.glodapPoints);
    fireEvent.click(screen.getByRole("button", { name: BUNDLES[lng].tabs.dates }));
    expect(document.body.textContent).not.toContain("GLODAPv3 Bottle Measurements");
  });
});
