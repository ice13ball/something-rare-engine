// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// ocean-nutrients-model: the frontend seams that compile cleanly and then render
// nothing — sort order of sliced tiles, link round-trip, month fallback, and the
// point panel's refusal to show a missing value as a number.
import { describe, it, expect, beforeAll, beforeEach, afterEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import fs from "node:fs";
import path from "node:path";
import i18n from "../i18n";
import { useMapStore } from "../store/mapStore";
import { toggleIdForDeckLayer, LAYER_DEFAULTS } from "../utils/layerConfig";
import { isValidDisplayValue, collectShareableDisplay, DISPLAY_FIELDS } from "../types/displayRegistry";
import { pointTargetFor } from "../components/map3d/pointFromLink";
import {
  effectiveBgcMonth, effectiveBgcVariable, wrapLongitude, type BgcModelMeta,
} from "../types/bgcModel";
import { formatScaleTick } from "../components/controls/sections/oceanClimatology/OceanNutrientsModelRow";
import { NutrientsModelPanel, formatNutrientValue } from "../components/panels/fields/NutrientsModelPanel";

const META = {
  layer: "ocean-nutrients-model",
  months: ["2025-09", "2025-10", "2026-08"],
  latest: "2026-08",
  variables: [
    { key: "no3", label: "Nitrate", unit: "mmol m-3", field: "no3_mmol_m3" },
    { key: "chl", label: "Chlorophyll-a", unit: "mg m-3", field: "chl_mg_m3" },
  ],
  grid: null,
  product: { title: "Global Ocean Biogeochemistry Analysis and Forecast", url: "https://example.org/p",
             doi: "10.48670/moi-00015", doi_url: "https://doi.org/10.48670/moi-00015", id: "P", licence_url: "" },
  attribution: "Generated using E.U. Copernicus Marine Service Information; https://doi.org/10.48670/moi-00015",
  caveat: "Model output, not measurements.",
} as unknown as BgcModelMeta;

beforeAll(() => {
  const en = JSON.parse(fs.readFileSync(path.resolve(__dirname, "../../public/locales/en/panels.json"), "utf8"));
  i18n.addResourceBundle("en", "panels", en, true, true);
});

describe("deck ids of the sliced field", () => {
  it("every tile id resolves to the toggle id, so order_idx applies", () => {
    for (let i = 0; i < 54; i++) {
      expect(toggleIdForDeckLayer(`ocean-nutrients-model-bitmap-nstar-2026-08-${i}`)).toBe("ocean-nutrients-model");
    }
  });
  it("leaves exact-map and unknown ids alone", () => {
    expect(toggleIdForDeckLayer("argo-glow")).toBe("argo");
    expect(toggleIdForDeckLayer("woa-climatology-bitmap-oxygen-500-0")).toBe("woa-climatology-bitmap-oxygen-500-0");
  });
  it("the layer sorts below the point layers (low order_idx), default off", () => {
    const row = LAYER_DEFAULTS.find((l) => l.id === "ocean-nutrients-model");
    expect(row?.default_on).toBe(false);
    expect(row!.order_idx).toBeLessThan(800);
  });
});

describe("share link", () => {
  it("accepts a calendar month and nothing else", () => {
    for (const ok of ["2026-08", "2021-10", "2025-12"]) expect(isValidDisplayValue("nutrientsMonth", ok)).toBe(true);
    for (const bad of ["2026-13", "2026-00", "2026-8", "latest", "2026-08-01", "../x", 202608, null]) {
      expect(isValidDisplayValue("nutrientsMonth", bad)).toBe(false);
    }
  });
  it("the variable lands in a request path, so only a plain token passes", () => {
    expect(isValidDisplayValue("nutrientsVariable", "nstar")).toBe(true);
    expect(isValidDisplayValue("nutrientsVariable", "../../etc")).toBe(false);
  });
  it("carries the month only when the sender chose one, 'latest' travels as nothing", () => {
    expect(DISPLAY_FIELDS.nutrientsMonth.default).toBeNull();
    useMapStore.setState({ nutrientsMonth: null, nutrientsVariable: "no3" });
    expect(collectShareableDisplay(useMapStore.getState())).not.toHaveProperty("nutrientsMonth");
    useMapStore.setState({ nutrientsMonth: "2025-10", nutrientsVariable: "chl" });
    expect(collectShareableDisplay(useMapStore.getState())).toMatchObject({ nutrientsMonth: "2025-10", nutrientsVariable: "chl" });
    useMapStore.setState({ nutrientsMonth: null, nutrientsVariable: "no3" });
  });
  it("a point link rebuilds the id a click writes", () => {
    const lat = -14.123456789, lon = -79.5;
    const clickId = `ocean-nutrients-model:${lat},${lon}`;
    expect(pointTargetFor("ocean-nutrients-model", lon, lat, undefined)?.id).toBe(clickId);
    expect(pointTargetFor("ocean-nutrients-model", lon, lat, 100)).toBeNull(); // takes no extra number
  });
});

describe("what the product still offers wins over what the store remembers", () => {
  it("falls back to the latest month and the first variable", () => {
    expect(effectiveBgcMonth(META, "2025-10")).toBe("2025-10");
    expect(effectiveBgcMonth(META, "2020-01")).toBe("2026-08"); // pruned since the link was made
    expect(effectiveBgcMonth(META, null)).toBe("2026-08");
    expect(effectiveBgcMonth(null, "2025-10")).toBeNull();
    expect(effectiveBgcVariable(META, "chl")).toBe("chl");
    expect(effectiveBgcVariable(META, "nppv")).toBe("no3");
  });
  it("wraps longitudes the way a repeated world hands them out", () => {
    expect(wrapLongitude(190)).toBe(-170);
    expect(wrapLongitude(-190)).toBe(170);
    expect(wrapLongitude(-79.5)).toBe(-79.5);
    expect(wrapLongitude(180)).toBe(-180);
  });
  it("formats scale ticks and values without noise", () => {
    expect(formatScaleTick(0.03)).toBe("0.03");
    expect(formatScaleTick(10)).toBe("10");
    expect(formatScaleTick(0)).toBe("0");
    expect(formatScaleTick(-15)).toBe("-15");
    expect(formatNutrientValue(0.0123456)).toBe("0.012");
    expect(formatNutrientValue(12.345)).toBe("12.3");
    expect(formatNutrientValue(-8.3367)).toBe("-8.34");
  });
});

describe("point panel", () => {
  const realFetch = globalThis.fetch;
  beforeEach(() => { useMapStore.setState({ nutrientsMonth: null }); });
  afterEach(() => { globalThis.fetch = realFetch; vi.restoreAllMocks(); });

  function stubFetch(point: (u: URL) => Record<string, unknown>) {
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://x");
      // Only the layer's own /point requests reach `point` (and its call counts):
      // i18next lazily fetches /locales/<lng>/<ns>.json through this same stub in a
      // full run, which made "asks for the month" count 5 calls instead of 4.
      const body = url.pathname.endsWith("/meta") ? META
        : url.pathname.endsWith("/point") ? point(url) : {};
      return { ok: true, status: 200, json: async () => body } as Response;
    }) as unknown as typeof fetch;
  }

  it("shows the exact values with units under the model warning", async () => {
    stubFetch((u) => {
      const v = u.searchParams.get("var")!;
      const field = { no3: "no3_mmol_m3", chl: "chl_mg_m3", nppv: "nppv_mg_m3_day", nstar: "nstar_mmol_m3" }[v]!;
      const unit = { no3: "mmol m-3", chl: "mg m-3", nppv: "mg m-3 day-1", nstar: "mmol m-3" }[v]!;
      return { var: v, status: "ok", value_field: field, [field]: v === "nstar" ? -8.3367 : 1.2345, unit };
    });
    render(<NutrientsModelPanel props={{ _lat: -14, _lon: -79.5 }} />);
    await waitFor(() => expect(screen.getByText("-8.34")).toBeInTheDocument());
    expect(document.body.textContent).toContain("Model output (PISCES, Copernicus Marine), not measurements.");
    expect(document.body.textContent).toContain("mg m-3 day-1");
    expect(document.body.textContent).toContain("2026-08"); // latest, since nothing was chosen
  });

  it("asks for the month the map is showing", async () => {
    useMapStore.setState({ nutrientsMonth: "2025-10" });
    const seen: string[] = [];
    stubFetch((u) => {
      seen.push(u.searchParams.get("month")!);
      return { var: "no3", status: "ok", value_field: "no3_mmol_m3", no3_mmol_m3: 1, unit: "mmol m-3" };
    });
    render(<NutrientsModelPanel props={{ _lat: 1, _lon: 2 }} />);
    await waitFor(() => expect(seen.length).toBe(4));
    expect(new Set(seen)).toEqual(new Set(["2025-10"]));
  });

  it("says no data for land or ice, and never renders a zero", async () => {
    stubFetch(() => ({ var: "no3", status: "no_data", value_field: "no3_mmol_m3", no3_mmol_m3: null, unit: "mmol m-3" }));
    render(<NutrientsModelPanel props={{ _lat: 50, _lon: 10 }} />);
    await waitFor(() => expect(document.body.textContent).toContain("No model value here (land or sea ice)."));
    expect(document.body.textContent).not.toMatch(/\b0(\.0+)?\b\s*mmol/);
  });

  it("says outside the grid for a point south of 80°S", async () => {
    stubFetch(() => ({ var: "no3", status: "not_covered", value_field: "no3_mmol_m3", no3_mmol_m3: null, unit: "mmol m-3" }));
    render(<NutrientsModelPanel props={{ _lat: -85, _lon: 10 }} />);
    await waitFor(() => expect(document.body.textContent).toContain("Outside the model grid, which ends at 80°S."));
  });
});
