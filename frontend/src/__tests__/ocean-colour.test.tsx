// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// ocean-colour-satellite: the frontend seams that compile cleanly and then render
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
  effectiveOceanColourMonth, effectiveOceanColourVariable, type OceanColourMeta,
} from "../types/oceanColour";
import { OceanColourPanel, formatOceanColourValue, formatValidFraction } from "../components/panels/fields/OceanColourPanel";

const PRODUCTS = {
  my: { id: "M", title: "Multi-year product", label: "multi-year (reprocessed)", doi: "10.48670/moi-00281",
        doi_url: "https://doi.org/10.48670/moi-00281", url: "https://example.org/m" },
  nrt: { id: "N", title: "Near-real-time product", label: "near-real-time", doi: "10.48670/moi-00279",
         doi_url: "https://doi.org/10.48670/moi-00279", url: "https://example.org/n" },
};
const META = {
  layer: "ocean-colour-satellite",
  months: ["2025-09", "2025-10", "2026-08"],
  latest: "2026-08",
  month_products: { "2025-09": "my", "2025-10": "my", "2026-08": "nrt" },
  variables: [
    { key: "chl", label: "Chlorophyll-a (satellite)", unit: "mg m-3", field: "chl_mg_m3" },
    { key: "pp", label: "Primary production (satellite, column)", unit: "mg m-2 day-1", field: "pp_mg_m2_day" },
  ],
  grid: null,
  products: PRODUCTS,
  licence_url: "",
  attribution: "Generated using E.U. Copernicus Marine Service Information; https://doi.org/10.48670/moi-00281; https://doi.org/10.48670/moi-00279",
  caveat: "Satellite observations.",
} as unknown as OceanColourMeta;

beforeAll(() => {
  const en = JSON.parse(fs.readFileSync(path.resolve(__dirname, "../../public/locales/en/panels.json"), "utf8"));
  i18n.addResourceBundle("en", "panels", en, true, true);
});

describe("deck ids of the sliced field", () => {
  it("every tile id resolves to the toggle id, so order_idx applies", () => {
    for (let i = 0; i < 54; i++) {
      expect(toggleIdForDeckLayer(`ocean-colour-satellite-bitmap-pp-2026-08-${i}`)).toBe("ocean-colour-satellite");
    }
  });
  it("does not swallow the model layer's tiles", () => {
    expect(toggleIdForDeckLayer("ocean-nutrients-model-bitmap-chl-2026-08-3")).toBe("ocean-nutrients-model");
  });
  it("sorts right after the model layer, below the point layers, default off", () => {
    const row = LAYER_DEFAULTS.find((l) => l.id === "ocean-colour-satellite");
    const model = LAYER_DEFAULTS.find((l) => l.id === "ocean-nutrients-model");
    expect(row?.default_on).toBe(false);
    expect(row!.order_idx).toBe(model!.order_idx + 1);
    expect(row!.order_idx).toBeLessThan(800);
  });
});

describe("share link", () => {
  it("accepts a calendar month and nothing else", () => {
    for (const ok of ["2026-08", "1997-09"]) expect(isValidDisplayValue("oceanColourMonth", ok)).toBe(true);
    for (const bad of ["2026-13", "2026-00", "latest", "2026-08-01", "../x", null]) {
      expect(isValidDisplayValue("oceanColourMonth", bad)).toBe(false);
    }
    expect(isValidDisplayValue("oceanColourVariable", "pp")).toBe(true);
    expect(isValidDisplayValue("oceanColourVariable", "../../etc")).toBe(false);
  });
  it("carries the month only when the sender chose one", () => {
    expect(DISPLAY_FIELDS.oceanColourMonth.default).toBeNull();
    useMapStore.setState({ oceanColourMonth: null, oceanColourVariable: "chl" });
    expect(collectShareableDisplay(useMapStore.getState())).not.toHaveProperty("oceanColourMonth");
    useMapStore.setState({ oceanColourMonth: "2025-10", oceanColourVariable: "pp" });
    expect(collectShareableDisplay(useMapStore.getState())).toMatchObject({ oceanColourMonth: "2025-10", oceanColourVariable: "pp" });
    useMapStore.setState({ oceanColourMonth: null, oceanColourVariable: "chl" });
  });
  it("a point link rebuilds the id a click writes", () => {
    const lat = -14.123456789, lon = -79.5;
    expect(pointTargetFor("ocean-colour-satellite", lon, lat, undefined)?.id).toBe(`ocean-colour-satellite:${lat},${lon}`);
    expect(pointTargetFor("ocean-colour-satellite", lon, lat, 100)).toBeNull();
  });
});

describe("what the product still offers wins over what the store remembers", () => {
  it("falls back to the latest month and the first variable", () => {
    expect(effectiveOceanColourMonth(META, "2025-10")).toBe("2025-10");
    expect(effectiveOceanColourMonth(META, "2020-01")).toBe("2026-08");
    expect(effectiveOceanColourMonth(META, null)).toBe("2026-08");
    expect(effectiveOceanColourMonth(null, "2025-10")).toBeNull();
    expect(effectiveOceanColourVariable(META, "pp")).toBe("pp");
    expect(effectiveOceanColourVariable(META, "no3")).toBe("chl");
  });
  it("formats values and valid fractions without noise", () => {
    expect(formatOceanColourValue(0.0123456)).toBe("0.012");
    expect(formatOceanColourValue(324.2)).toBe("324");
    expect(formatValidFraction(1)).toBe("100 %");
    expect(formatValidFraction(0.5)).toBe("50 %");
  });
});

describe("point panel", () => {
  const realFetch = globalThis.fetch;
  beforeEach(() => { useMapStore.setState({ oceanColourMonth: null }); });
  afterEach(() => { globalThis.fetch = realFetch; vi.restoreAllMocks(); });

  function stubFetch(point: (u: URL) => Record<string, unknown>) {
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://x");
      const body = url.pathname.endsWith("/meta") ? META : point(url);
      return { ok: true, status: 200, json: async () => body } as Response;
    }) as unknown as typeof fetch;
  }

  const okPoint = (u: URL) => {
    const v = u.searchParams.get("var")!;
    const field = { chl: "chl_mg_m3", pp: "pp_mg_m2_day" }[v]!;
    const unit = { chl: "mg m-3", pp: "mg m-2 day-1" }[v]!;
    return { var: v, status: "ok", value_field: field, [field]: v === "pp" ? 324.2 : 0.1234, unit,
             valid_fraction: 0.5, product_key: "nrt", product_label: "near-real-time" };
  };

  it("shows the values with units, the valid fraction and the product that supplied the month", async () => {
    stubFetch(okPoint);
    render(<OceanColourPanel props={{ _lat: -14, _lon: -79.5 }} />);
    await waitFor(() => expect(screen.getByText("324")).toBeInTheDocument());
    const text = document.body.textContent ?? "";
    expect(text).toContain("mg m-2 day-1");
    expect(text).toContain("50 %");
    expect(text).toContain("2026-08");
    expect(text).toContain("Source product: near-real-time");
    expect(text).toContain("cannot be compared with the surface volumetric rate");
  });

  it("asks for the month the map is showing", async () => {
    useMapStore.setState({ oceanColourMonth: "2025-10" });
    const seen: string[] = [];
    stubFetch((u) => { seen.push(u.searchParams.get("month")!); return okPoint(u); });
    render(<OceanColourPanel props={{ _lat: 1, _lon: 2 }} />);
    await waitFor(() => expect(seen.length).toBe(2));
    expect(new Set(seen)).toEqual(new Set(["2025-10"]));
  });

  it("says no observation for a cloudy or dark cell, and never renders a zero", async () => {
    stubFetch(() => ({ var: "chl", status: "no_data", value_field: "chl_mg_m3", chl_mg_m3: null, unit: "mg m-3",
                       valid_fraction: 0, product_key: "my", product_label: "multi-year (reprocessed)" }));
    render(<OceanColourPanel props={{ _lat: 80, _lon: 10 }} />);
    await waitFor(() => expect(document.body.textContent).toContain("No satellite observation this month (cloud, sea ice, polar night or land)."));
    expect(document.body.textContent).not.toMatch(/\b0(\.0+)?\b\s*mg/);
  });

  it("says outside the grid for a point the grid does not reach", async () => {
    stubFetch(() => ({ var: "chl", status: "not_covered", value_field: "chl_mg_m3", chl_mg_m3: null, unit: "mg m-3",
                       valid_fraction: null, product_key: "my", product_label: "x" }));
    render(<OceanColourPanel props={{ _lat: 89.95, _lon: 10 }} />);
    await waitFor(() => expect(document.body.textContent).toContain("Outside the grid, which ends at 89.875° latitude."));
  });
});
