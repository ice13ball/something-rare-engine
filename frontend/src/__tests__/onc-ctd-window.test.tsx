// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// The portal mirrors its sources 1:1 (Michal, 2026-09-10). ONC's numbers are
// never modified — and by the same rule, we must not add a fact ONC did not
// give. `onc_ctd_profiles.cast_time` was one we added: it is the first pressure
// sample inside the 7-day window WE request, so on production it sat exactly
// 7.00 days before every sync, on all 84 rows. The chart printed it as
// "Cast: <t> UTC".
//
// And these are not casts. Measured 2026-09-10:
//     RCNW4    10,080 samples across 1968.3 – 1969.5 m   (1.2 m)
//     PVIP.C1 100,000 samples across   98.1 –   98.2 m   (0.1 m)
//     27 of 28 device-locations span under 5 m of pressure.
// They are moored instruments at a fixed depth. Nothing is filtered out and no
// value is touched — the panel simply states the window ONC covered and the
// depth its instrument sat at, and lets the reader see it.
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, cleanup, screen, waitFor } from "@testing-library/react";
import { OncPanel } from "../components/panels/ocean/OncPanel";

const STATION = {
  location_code: "RCNW4", name: "Clayoquot Slope", depth_m: 1970,
  lat: 48.67, lon: -126.85, latest_sensors: {},
  sensors_fetched_at: "2026-09-10T00:00:00Z",
};

/** A moored ONC instrument: 1.2 m of pressure noise, not a water column. */
const MOORED = {
  device_code: "SBECTD37SIP16431",
  cast_time: "2026-09-03T20:15:02+00:00",     // our window's left edge
  sample_start: "2026-09-03T20:15:02+00:00",
  sample_end: "2026-09-10T20:15:02+00:00",
  n_samples: 10080,
  depth_min_m: 1968.3,
  depth_max_m: 1969.5,
  profile: {
    depth: [1968.3, 1968.9, 1969.5],
    temperature: [3.1, 3.1, 3.1],
    salinity: [34.5, 34.5, 34.5],
  },
};

function routeCtd(payload: unknown) {
  vi.stubGlobal("fetch", vi.fn((url: string) =>
    Promise.resolve({
      ok: true,
      json: () => Promise.resolve(String(url).includes("/onc/ctd/") ? payload : {}),
    } as Response)));
}

const renderPanel = () => render(<OncPanel properties={STATION as never} />);

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("OncPanel — ONC CTD sample window", () => {
  it("states the window ONC covered, both ends of it", async () => {
    routeCtd([MOORED]);
    renderPanel();
    await waitFor(() => expect(screen.getByText(/2026-09-03 20:15/)).toBeTruthy());
    // ⛔ Both ends. Showing only the start is how the old label read as a
    // moment in time when it was really the edge of a seven-day window.
    expect(screen.getByText(/2026-09-10 20:15/)).toBeTruthy();
  });

  it("never calls a moored sample window a cast", async () => {
    routeCtd([MOORED]);
    renderPanel();
    await waitFor(() => expect(screen.getByText(/2026-09-03 20:15/)).toBeTruthy());
    expect(screen.queryByText(/\bCast\b/)).toBeNull();
  });

  it("shows the depth the instrument sat at, so 1.2 m cannot read as a profile", async () => {
    routeCtd([MOORED]);
    renderPanel();
    await waitFor(() => expect(screen.getByText(/1968\.3 – 1969\.5 m/)).toBeTruthy());
    expect(screen.getByText("10,080")).toBeTruthy();
  });

  it("says nothing about a window for a row ingested before we recorded one", async () => {
    // ⛔ Falling back to cast_time here would put our own request time back on
    // screen wearing an honest label, which is worse than saying nothing.
    routeCtd([{ ...MOORED, sample_start: null, sample_end: null,
                n_samples: null, depth_min_m: null, depth_max_m: null }]);
    renderPanel();
    await waitFor(() => expect(screen.getByText("Clayoquot Slope")).toBeTruthy());
    expect(screen.queryByText(/2026-09-03 20:15/)).toBeNull();
    expect(screen.queryByText(/\bCast\b/)).toBeNull();
  });

  it("still plots every ONC value it was given — nothing is filtered", async () => {
    routeCtd([MOORED]);
    const { container } = renderPanel();
    await waitFor(() => expect(screen.getByText(/1968\.3 – 1969\.5 m/)).toBeTruthy());
    // Three depths x two variables must all reach the chart.
    const paths = container.querySelectorAll("svg path");
    expect(paths.length).toBeGreaterThanOrEqual(2);
  });
});
