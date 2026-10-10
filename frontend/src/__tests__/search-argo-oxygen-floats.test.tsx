// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
/**
 * Global search finds a BGC-Argo float by WMO number (the `/v1/argo-oxygen/floats` document shape,
 * backend/domains/argo_oxygen_points.py `_build_floats`) and selecting it opens the float's latest drawn profile by its
 * stable `profile_key`. 1902751 is two floats (two DACs): both are listed, each opening its own profile.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { FeatureCollection } from "geojson";

import i18n from "../i18n";
import { SearchBar } from "../components/SearchBar";
import { useMapStore } from "../store/mapStore";
import plCommon from "../../public/locales/pl/common.json";
import frCommon from "../../public/locales/fr/common.json";
import deCommon from "../../public/locales/de/common.json";

const flt = (wmo: string, dac: string, key: string, last: string, n: number, lon: number, lat: number) => ({
  type: "Feature" as const,
  geometry: { type: "Point" as const, coordinates: [lon, lat] },
  properties: { wmo, dac, last_profile_key: key, last_date: last, n_profiles: n },
});
const FLOATS: FeatureCollection = {
  type: "FeatureCollection",
  features: [
    flt("1902751", "coriolis", "coriolis_1902751_142", "2024-03-09", 142, -30.5, 40.25),
    flt("1902751", "meds", "meds_1902751_007", "2019-11-02", 7, -60.5, 45.0),
    flt("6903000", "aoml", "aoml_6903000_001", "2025-01-01", 1, 10.0, -20.0),
  ],
};

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve([]) })) as unknown as typeof fetch);
  useMapStore.setState({ activeLayers: new Set(["argo-oxygen-points", "oxygen-deox"]) as never, enabledLayerIds: null });
});
afterEach(async () => {
  cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); useMapStore.setState({ flyTo: null, selectedFeatures: [] } as never);
  await i18n.changeLanguage("en");
});

const type = (q: string) => {
  render(<SearchBar dataRef={{ current: { argoOxygenFloats: FLOATS } }} dataVersion={1} />);
  fireEvent.change(screen.getByRole("textbox"), { target: { value: q } });
  act(() => { vi.advanceTimersByTime(250); });
};

// The test i18n instance bundles English `common` only (the other locales are fetched over HTTP in production), so the
// bundles are added here — from the same files production serves.
const COMMON = { pl: plCommon, fr: frCommon, de: deCommon } as const;

describe("BGC-Argo float search — the profile count is a real plural", () => {
  const counts: FeatureCollection = {
    type: "FeatureCollection",
    features: [1, 2, 5, 22, 25].map((n, i) =>
      flt(`690310${i}`, "aoml", `aoml_690310${i}_001`, "2025-01-01", n, 10.0 + i, -20.0)),
  };
  const secondaries = async (lng: string) => {
    await i18n.changeLanguage(lng);
    render(<SearchBar dataRef={{ current: { argoOxygenFloats: counts } }} dataVersion={1} />);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "69031" } });
    act(() => { vi.advanceTimersByTime(250); });
    return screen.getAllByText(/^AOML · 2025-01-01 · /).map(el => el.textContent!.split(" · ")[2]);
  };

  // pl: one (1), few (2–4, 22), many (5, 25)
  const EXPECTED: Record<string, string[]> = {
    en: ["1 profile", "2 profiles", "5 profiles", "22 profiles", "25 profiles"],
    fr: ["1 profil", "2 profils", "5 profils", "22 profils", "25 profils"],
    de: ["1 Profil", "2 Profile", "5 Profile", "22 Profile", "25 Profile"],
    pl: ["1 profil", "2 profile", "5 profili", "22 profile", "25 profili"],
  };
  for (const lng of Object.keys(EXPECTED)) {
    it(lng, async () => {
      for (const [l, bundle] of Object.entries(COMMON)) i18n.addResourceBundle(l, "common", bundle, true, true);
      expect(await secondaries(lng)).toEqual(EXPECTED[lng]);
    });
  }
});

describe("BGC-Argo float search", () => {
  it("finds a float by WMO and shows DAC, last date and profile count", () => {
    type("6903000");
    expect(screen.getByText("BGC-Argo O₂ floats")).toBeInTheDocument();
    expect(screen.getByText("Float 6903000")).toBeInTheDocument();
    expect(screen.getByText("AOML · 2025-01-01 · 1 profile")).toBeInTheDocument();
  });

  it("lists both floats that share a WMO across DACs", () => {
    type("1902751");
    expect(screen.getAllByText("Float 1902751")).toHaveLength(2);
    expect(screen.getByText("CORIOLIS · 2024-03-09 · 142 profiles")).toBeInTheDocument();
    expect(screen.getByText("MEDS · 2019-11-02 · 7 profiles")).toBeInTheDocument();
  });

  it("selecting a result opens that float's latest profile by its stable key (not the WMO), switching the field on with it", () => {
    useMapStore.setState({ activeLayers: new Set(["argo-oxygen-points"]) as never });
    const flyTo = vi.fn();
    useMapStore.setState({ flyTo } as never);
    type("1902751");
    fireEvent.click(screen.getByText("CORIOLIS · 2024-03-09 · 142 profiles"));
    expect(flyTo).toHaveBeenCalledWith(-30.5, 40.25);
    expect(useMapStore.getState().activeLayers.has("oxygen-deox" as never)).toBe(true);
    act(() => { vi.advanceTimersByTime(900); });
    const sel = useMapStore.getState().selectedFeatures[0];
    expect(sel?.id).toBe("coriolis_1902751_142");
    expect(sel?.layer).toBe("argo-oxygen-points");
  });
});
