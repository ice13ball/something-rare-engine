// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// `/v1/map/onc` returns each location's `description` (785 of 1,980 carry
// one, measured 2026-09-23) and the server-rendered page shows it to search
// robots, but the panel a person opens on click never rendered it
// (layer audit, 2026-09-22). The text is ONC's own, passed through as is.
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup, screen } from "@testing-library/react";
import { OncPanel } from "../components/panels/ocean/OncPanel";

const station = (overrides: Record<string, unknown> = {}) => ({
  location_code: "TESTDESC",
  name: "Test Description Station",
  depth_m: 100,
  lat: 48.3,
  lon: -126.1,
  latest_sensors: null,
  sensors_fetched_at: "2026-09-10T00:00:00Z",
  device_categories: [],
  ...overrides,
});

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve({}) } as Response)));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("OncPanel description", () => {
  it("renders the station's description as plain text", () => {
    // A real value from production (CF427), with ONC's own double spaces.
    const description =
      " Station Name Alias: BI-9.A  Description: Cast sampling station with 200m radius.  ";
    render(<OncPanel properties={station({ description }) as never} />);
    expect(screen.getByText(/Cast sampling station with 200m radius\./)).toBeInTheDocument();
  });

  it("renders no empty description label when the station has none", () => {
    render(<OncPanel properties={station({ description: null }) as never} />);
    expect(screen.queryByText("Description")).not.toBeInTheDocument();
  });
});
