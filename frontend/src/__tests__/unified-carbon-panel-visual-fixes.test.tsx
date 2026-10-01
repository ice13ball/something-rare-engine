// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// Two visual defects at 1366px viewport / ~355px panel:
// 1. Unit cell must only print a unit alongside a genuine numeric value — never next to
//    status text, "below seafloor", or "no data here" (value_label rows already omit it).
// 2. "Nearest measurements" rows must not carry the summary in the same <tr> as distance/
//    date — it wraps below instead, so the table fits a 320px panel without horizontal scroll.
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup, screen, waitFor, fireEvent } from "@testing-library/react";
import { UnifiedCarbonPanel } from "../components/panels/fields/UnifiedCarbonPanel";
import { useMapStore } from "../store/mapStore";

const FIELD_PAYLOAD = {
  lat: 10, lon: 20, depth_m: 2000, decade: 5,
  groups: [
    {
      group: "Interior carbon (GLODAP)",
      variables: [
        { key: "dic", label: "Dissolved Inorganic Carbon", units: "µmol/kg", value: 2100.123, status: null },
      ],
    },
    {
      group: "Acidification (GLODAP + platform)",
      variables: [
        {
          key: "arag_horizon", label: "Aragonite saturation-horizon depth", units: "m",
          value: null, depth_invariant: true, status: "no_horizon",
        },
        {
          key: "omega_a", label: "Aragonite saturation state", units: "unitless",
          value: null, status: "column_supersaturated",
        },
        {
          key: "co2_surface", label: "Surface CO2", units: "µatm",
          value: null, status: null,
        },
      ],
    },
    {
      group: "Seafloor",
      variables: [
        { key: "seafloor_depth", label: "Seafloor depth (GEBCO)", units: "m", value: 1455, depth_invariant: true, status: null },
      ],
    },
  ],
  citations: [],
};

const OBSERVATIONS = [
  {
    source: "argo", label: "Argo float", id: "a1", distance_km: 5.2,
    summary: "A long free-text summary describing the sampling context in enough detail to overflow four narrow table columns.",
    date: "2020-06-14", date_kind: "sampled",
    lat: 10, lon: 20, deck_layer_id: "argo-floats-3d",
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
  render(<UnifiedCarbonPanel props={{ _lat: 10, _lon: 20, depth: 2000 } as never} />);

beforeEach(() => { vi.restoreAllMocks(); });
afterEach(() => { cleanup(); });

describe("UnifiedCarbonPanel — unit cell only next to a numeric value", () => {
  it("status text, below-seafloor, and 'no data here' rows render without their unit; a numeric row keeps it", async () => {
    vi.stubGlobal("fetch", mockFetch());
    renderPanel();

    await waitFor(() => expect(screen.getByText("2100.123")).toBeTruthy());

    // Numeric row: unit is present.
    const dicRow = screen.getByText("2100.123").closest("tr")!;
    expect(dicRow.textContent).toContain("µmol/kg");

    // status=no_horizon row: no unit next to it.
    const noHorizonText = screen.getByText(/not defined — no horizon in this column/i);
    const noHorizonRow = noHorizonText.closest("tr")!;
    expect(noHorizonRow.textContent).not.toContain("m)");
    expect(noHorizonRow.querySelector("td:last-child")!.textContent).toBe("");

    // status=column_supersaturated row: no unit next to it.
    const supersatText = screen.getByText(/column supersaturated/i);
    const supersatRow = supersatText.closest("tr")!;
    expect(supersatRow.querySelector("td:last-child")!.textContent).toBe("");

    // depth below seafloor for a non-invariant, non-status, null row -> "below seafloor", no unit.
    const belowSeafloorCell = screen.getByText("below seafloor");
    const belowSeafloorRow = belowSeafloorCell.closest("tr")!;
    expect(belowSeafloorRow.querySelector("td:last-child")!.textContent).toBe("");
  });
});

describe("UnifiedCarbonPanel — nearest measurements layout", () => {
  it("renders the summary outside the distance/date row, and the label still flies to the observation", async () => {
    const flyTo = vi.fn();
    useMapStore.getState().setFlyTo(flyTo);
    vi.stubGlobal("fetch", mockFetch());
    renderPanel();

    await waitFor(() => expect(screen.getByText("Argo float")).toBeTruthy());

    const summary = screen.getByText(/A long free-text summary/i);
    const summaryRow = summary.closest("tr")!;
    expect(summaryRow.textContent).not.toContain("5.2 km");
    expect(summaryRow.textContent).not.toContain("2020-06-14");

    const labelButton = screen.getByText("Argo float");
    const distanceCell = screen.getByText(/5.2 km/);
    expect(distanceCell.closest("tr")).not.toBe(summaryRow);
    expect(labelButton.closest("tr")).toBe(distanceCell.closest("tr"));

    fireEvent.click(labelButton);
    expect(flyTo).toHaveBeenCalledWith(20, 10);
    useMapStore.getState().setFlyTo(null as unknown as (lon: number, lat: number) => void);
  });
});
