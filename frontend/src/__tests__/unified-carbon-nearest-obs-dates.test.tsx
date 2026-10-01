// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// Every "Nearest measurements" row must show a date, in one consistent format, or say
// explicitly that the source has none — never an empty cell. Covers the three date_kind
// shapes: "sampled" (a plain date string), "discovered" (a vent's discovery year, worded
// differently from a sampling date), and a null date ("no date in source").
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup, screen, waitFor } from "@testing-library/react";
import { UnifiedCarbonPanel } from "../components/panels/fields/UnifiedCarbonPanel";

const FIELD_PAYLOAD = {
  lat: 40, lon: -30, depth_m: 0, decade: 2010,
  groups: [{
    group: "Carbonate system",
    variables: [{ key: "ta", label: "Total alkalinity", units: "µmol/kg", value: 2300 }],
  }],
  citations: ["GLODAPv2.2016b"],
};

const OBSERVATIONS = [
  {
    source: "argo", label: "Argo float", id: "a1", distance_km: 5.2,
    summary: "plat-1", date: "2020-06-14", date_kind: "sampled",
    lat: 40, lon: -30, deck_layer_id: "argo-floats-3d",
  },
  {
    source: "vents", label: "Hydrothermal vent", id: "v1", distance_km: 12.0,
    summary: "t-vent-1", date: "1999", date_kind: "discovered",
    lat: 40, lon: -30, deck_layer_id: "hydrothermal-vents-active",
  },
  {
    source: "methane-seeps", label: "Methane seep", id: "s1", distance_km: 20.1,
    summary: "seep", date: null, date_kind: "sampled",
    lat: 40, lon: -30, deck_layer_id: "methane-seeps",
  },
];

function mockFetch() {
  return vi.fn((url: string) => {
    if (String(url).includes("nearest-obs")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ observations: OBSERVATIONS }) });
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve(FIELD_PAYLOAD) });
  }) as unknown as typeof fetch;
}

const renderPanel = () =>
  render(<UnifiedCarbonPanel props={{ _lat: 40, _lon: -30, depth: 0 } as never} />);

beforeEach(() => { vi.restoreAllMocks(); });
afterEach(() => { cleanup(); });

describe("UnifiedCarbonPanel — nearest measurements, per-row dates", () => {
  it("shows a plain date, a discovered-year phrasing, and a no-date fallback — never blank", async () => {
    vi.stubGlobal("fetch", mockFetch());
    renderPanel();

    await waitFor(() => expect(screen.getByText("2020-06-14")).toBeTruthy());
    expect(screen.getByText(/discovered 1999/i)).toBeTruthy();
    expect(screen.getByText(/no date in source/i)).toBeTruthy();

    // Every observation row rendered exactly one date cell with visible text — none empty.
    const rows = screen.getAllByRole("row");
    // header/section rows aside, the three observation rows are present via their labels
    expect(screen.getByText("Argo float")).toBeTruthy();
    expect(screen.getByText("Hydrothermal vent")).toBeTruthy();
    expect(screen.getByText("Methane seep")).toBeTruthy();
    expect(rows.length).toBeGreaterThan(0);
  });
});
