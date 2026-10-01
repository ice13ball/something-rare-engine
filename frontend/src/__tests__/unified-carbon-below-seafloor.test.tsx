// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// Depth below the seafloor (GEBCO) is not "missing data" — the panel must say so, and
// label only the non-depth_invariant null rows "below seafloor" instead of "no data
// here". An always-supersaturated column (status=column_supersaturated) and an
// undefined horizon shift (status=no_horizon) get their own explanatory text, which
// takes precedence over both "no data here" and "below seafloor".
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup, screen, waitFor } from "@testing-library/react";
import { UnifiedCarbonPanel } from "../components/panels/fields/UnifiedCarbonPanel";

function payload(depth: number, seafloorValue: number | null, opts?: {
  dicValue?: number | null;
  horizonStatus?: string | null;
  shiftStatus?: string | null;
}) {
  const dicValue = opts?.dicValue ?? null;
  return {
    lat: 10, lon: 20, depth_m: depth, decade: 5,
    groups: [
      {
        group: "Interior carbon (GLODAP)",
        variables: [
          { key: "dic", label: "Dissolved Inorganic Carbon", units: "µmol/kg", value: dicValue, status: null },
        ],
      },
      {
        group: "Acidification (GLODAP + platform)",
        variables: [
          {
            key: "arag_horizon", label: "Aragonite saturation-horizon depth", units: "m",
            value: null, depth_invariant: true, status: opts?.horizonStatus ?? null,
          },
          {
            key: "arag_horizon_shift", label: "Horizon shift since preindustrial", units: "m",
            value: null, depth_invariant: true, status: opts?.shiftStatus ?? null,
          },
        ],
      },
      {
        group: "Seafloor",
        variables: [
          { key: "seafloor_depth", label: "Seafloor depth (GEBCO)", units: "m", value: seafloorValue, depth_invariant: true, status: null },
        ],
      },
    ],
    citations: [],
  };
}

function mockFetch(fieldPayload: unknown) {
  return vi.fn((url: string) => {
    if (String(url).includes("nearest-obs")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ observations: [] }) });
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve(fieldPayload) });
  }) as unknown as typeof fetch;
}

const renderPanel = (depth: number) =>
  render(<UnifiedCarbonPanel props={{ _lat: 10, _lon: 20, depth } as never} />);

beforeEach(() => { vi.restoreAllMocks(); });
afterEach(() => { cleanup(); });

describe("UnifiedCarbonPanel — below-seafloor depth", () => {
  it("depth below seafloor: shows notice, labels a null non-invariant row 'below seafloor', not the invariant one", async () => {
    vi.stubGlobal("fetch", mockFetch(payload(2000, 1455)));
    renderPanel(2000);

    await waitFor(() => expect(screen.getByText(/below the seafloor/i)).toBeTruthy());
    expect(screen.getByText(/1455 m, GEBCO/)).toBeTruthy();

    // dic is not depth_invariant and null -> "below seafloor"
    expect(screen.getByText("below seafloor")).toBeTruthy();
  });

  it("a depth-dependent row WITH a value still shows the value, not 'below seafloor'", async () => {
    vi.stubGlobal("fetch", mockFetch(payload(2000, 1455, { dicValue: 2100.123 })));
    renderPanel(2000);

    await waitFor(() => expect(screen.getByText(/below the seafloor/i)).toBeTruthy());
    expect(screen.getByText("2100.123")).toBeTruthy();
    expect(screen.queryByText("below seafloor")).toBeNull();
  });

  it("depth above seafloor: no notice, null rows say 'no data here'", async () => {
    vi.stubGlobal("fetch", mockFetch(payload(1000, 1455)));
    renderPanel(1000);

    await waitFor(() => expect(screen.getByText("Dissolved Inorganic Carbon")).toBeTruthy());
    expect(screen.queryByText(/below the seafloor/i)).toBeNull();
    expect(screen.queryByText("below seafloor")).toBeNull();
    expect(screen.getAllByText("no data here").length).toBeGreaterThan(0);
  });

  it("seafloor_depth null (land/unknown): makes no below-seafloor claim", async () => {
    vi.stubGlobal("fetch", mockFetch(payload(2000, null, { dicValue: 2100 })));
    renderPanel(2000);

    await waitFor(() => expect(screen.getByText("Dissolved Inorganic Carbon")).toBeTruthy());
    expect(screen.queryByText(/below the seafloor/i)).toBeNull();
    expect(screen.queryByText("below seafloor")).toBeNull();
  });

  it("status column_supersaturated / no_horizon render their own text, ahead of 'no data here'", async () => {
    vi.stubGlobal("fetch", mockFetch(payload(0, 1455, {
      horizonStatus: "column_supersaturated",
      shiftStatus: "no_horizon",
    })));
    renderPanel(0);

    await waitFor(() => expect(screen.getByText(/column supersaturated/i)).toBeTruthy());
    expect(screen.getByText(/no horizon in this column/i)).toBeTruthy();
  });
});
