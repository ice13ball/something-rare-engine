// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// The earthquake section rendered only when `earthquakes.length > 0`, and the
// fetch's `.catch` set the same empty array a genuine 200-with-no-events sets.
// Three different situations therefore produced one identical blank:
//
//   still loading .......... earthquakes === null
//   no quakes in 200 km/30d  earthquakes === []   (from a 200)
//   the endpoint failed .... earthquakes === []   (from the catch)
//
// A reader looking at a station above the Cascadia margin could not tell a
// quiet month from a broken endpoint. Same rule the SEO layer runs on:
// "missing" and "broken" must never share a code path.
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, cleanup, screen, waitFor } from "@testing-library/react";
import { OncPanel } from "../components/panels/ocean/OncPanel";

const STATION = {
  location_code: "BACAX", name: "Barkley Canyon Axis", depth_m: 985,
  lat: 48.31, lon: -126.05, latest_sensors: {},
  sensors_fetched_at: "2026-09-10T00:00:00Z",
};

const QUAKE = {
  usgs_id: "us7000abcd", occurred_at: "2026-09-08T04:11:00Z",
  magnitude: 4.2, depth_km: 12.0, place: "60 km W of Ucluelet", distance_km: 58,
};

/** Answer the earthquake route one way and every other route emptily. */
function routeQuakes(answer: (url: string) => Promise<unknown>) {
  vi.stubGlobal("fetch", vi.fn((url: string) =>
    String(url).includes("earthquakes-near")
      ? answer(String(url))
      : Promise.resolve({ ok: true, json: () => Promise.resolve({}) } as Response)));
}

const renderPanel = () => render(<OncPanel properties={STATION as never} />);

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("OncPanel — nearby earthquakes", () => {
  it("lists the events when the source has some", async () => {
    routeQuakes(() => Promise.resolve({ ok: true, json: () => Promise.resolve([QUAKE]) } as Response));
    renderPanel();
    await waitFor(() => expect(screen.getByText("60 km W of Ucluelet")).toBeTruthy());
    expect(screen.getByText("M4.2")).toBeTruthy();
    expect(screen.queryByText(/no earthquakes recorded/i)).toBeNull();
    expect(screen.queryByText(/could not be loaded/i)).toBeNull();
  });

  it("says the seafloor was quiet rather than hiding the section", async () => {
    routeQuakes(() => Promise.resolve({ ok: true, json: () => Promise.resolve([]) } as Response));
    renderPanel();
    await waitFor(() => expect(screen.getByText(/no earthquakes recorded/i)).toBeTruthy());
    expect(screen.queryByText(/could not be loaded/i)).toBeNull();
  });

  it("blames our fetch, not the seafloor, when the endpoint answers 500", async () => {
    routeQuakes(() => Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve([]) } as Response));
    renderPanel();
    await waitFor(() => expect(screen.getByText(/could not be loaded/i)).toBeTruthy());
    // ⛔ The decisive assertion: an outage must NOT read as an empty window.
    expect(screen.queryByText(/no earthquakes recorded/i)).toBeNull();
  });

  it("blames our fetch when the request throws outright", async () => {
    routeQuakes(() => Promise.reject(new Error("network down")));
    renderPanel();
    await waitFor(() => expect(screen.getByText(/could not be loaded/i)).toBeTruthy());
    expect(screen.queryByText(/no earthquakes recorded/i)).toBeNull();
  });

  it("stays silent while the request is still in flight", async () => {
    routeQuakes(() => new Promise(() => { /* never settles */ }));
    renderPanel();
    await waitFor(() => expect(screen.getByText("Barkley Canyon Axis")).toBeTruthy());
    // ⛔ Asserting only that neither MESSAGE shows is not enough: with the
    // initial state set to "ok" the section still rendered, as a bare heading
    // with nothing under it, and this test stayed green. The heading is what
    // proves the section is genuinely absent.
    expect(screen.queryByText(/^Earthquakes/i)).toBeNull();
    expect(screen.queryByText(/no earthquakes recorded/i)).toBeNull();
    expect(screen.queryByText(/could not be loaded/i)).toBeNull();
  });

  it("shows the heading once the answer is in, whatever the answer is", async () => {
    // The mirror of the test above — without it, "never render the section"
    // would satisfy the loading assertion and break the other three quietly.
    routeQuakes(() => Promise.resolve({ ok: true, json: () => Promise.resolve([]) } as Response));
    renderPanel();
    await waitFor(() => expect(screen.getByText(/^Earthquakes/i)).toBeTruthy());
  });
});
