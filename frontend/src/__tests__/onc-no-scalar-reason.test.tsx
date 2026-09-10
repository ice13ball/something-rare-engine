// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// ⛔ "We fetched nothing" and "there is nothing to fetch" must not share one
// message. 1,338 ONC locations show no readings; for 960 of them that is not
// our failure — the instruments there publish no scalar measurement at all.
//
// Measured on production across every location, 2026-09-10:
//
//     DRIFTER only ......... 723 stations, 0 with readings
//     AISRECEIVER only ..... 114 stations, 0 with readings
//     HYDROPHONE only ....... 61 stations, 0 with readings
//     ADAPTER / CAMLIGHTS ... 49 stations, 0 with readings
//     ------------------------------------------------------
//     the list above ....... 960 stations, 0 counterexamples
//
// ⚠️ Two categories were considered and REJECTED, and the tests below pin
// both rejections, because a wrong explanation is worse than none:
//   - JB / Junction Box: PBY, SGDLS and YPVPF.J1 really do publish pressure.
//   - ACCELEROMETER: ZEBA.W1 returns "JMA Intensity Amplitude". ONC has data
//     there; our property allowlist just does not know it. That is our gap,
//     not their absence.
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup, screen } from "@testing-library/react";
import { OncPanel } from "../components/panels/ocean/OncPanel";

const station = (categories: string[]) => ({
  location_code: "TESTCAT",
  name: "Test Station",
  depth_m: 100,
  lat: 48.3,
  lon: -126.1,
  latest_sensors: null,
  sensors_fetched_at: "2026-09-10T00:00:00Z",
  device_categories: categories,
});

const renderWith = (categories: string[]) =>
  render(<OncPanel properties={station(categories) as never} />);

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve({}) } as Response)));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("why an ONC station shows no readings", () => {
  it("says a drifting buoy publishes a position, not a measurement", () => {
    renderWith(["DRIFTER"]);
    // ⛔ NOT /drifting buoy/ — the layer's own description blurb, rendered at
    // the bottom of this same panel, says "cabled seafloor nodes alongside
    // drifting buoys". That phrase matched with the feature switched OFF, so
    // the test passed for the wrong reason until a sabotage run exposed it.
    // Assert on wording unique to the message under test.
    expect(screen.getAllByText(/publishes its position/i).length).toBeGreaterThan(0);
  });

  it("says an AIS receiver listens to vessels, not the ocean", () => {
    renderWith(["AISRECEIVER"]);
    expect(screen.getAllByText(/vessel transmissions/i).length).toBeGreaterThan(0);
  });

  it("says a hydrophone's audio is a data product, not a scalar reading", () => {
    renderWith(["HYDROPHONE"]);
    expect(screen.getAllByText(/audio/i).length).toBeGreaterThan(0);
  });

  it("accepts ONC's long-form category names too", () => {
    // The map merges SHORT codes from Oceans 3.0 with LONG names from the
    // ArcGIS feed, so one location can carry both spellings.
    renderWith(["Camera Lights", "CAMLIGHTS"]);
    expect(screen.getAllByText(/no measuring sensor/i).length).toBeGreaterThan(0);
  });

  it("generalises when several kinds of non-scalar instrument are present", () => {
    renderWith(["DRIFTER", "AISRECEIVER"]);
    expect(screen.getAllByText(/none of the instruments/i).length).toBeGreaterThan(0);
  });

  // ── the rejections ──────────────────────────────────────────────────────

  it("does NOT claim a junction box carries no sensor", () => {
    // PBY, SGDLS and YPVPF.J1 publish pressure. Claiming otherwise is a lie
    // about the source, not a tidier message.
    renderWith(["JB", "Junction Box"]);
    expect(screen.queryAllByText(/no measuring sensor/i).length).toBe(0);
    expect(screen.getAllByText(/no cached readings/i).length).toBeGreaterThan(0);
  });

  it("does NOT claim an accelerometer publishes nothing", () => {
    // ZEBA.W1 returns JMA Intensity Amplitude. Our allowlist is the gap.
    renderWith(["ACCELEROMETER"]);
    expect(screen.getAllByText(/no cached readings/i).length).toBeGreaterThan(0);
  });

  it("keeps quiet when one category is unexplained", () => {
    // A drifter that also carries a CTD is not a position-only station.
    renderWith(["DRIFTER", "CTD"]);
    expect(screen.getAllByText(/no cached readings/i).length).toBeGreaterThan(0);
  });

  it("keeps quiet when the station lists no categories at all", () => {
    renderWith([]);
    expect(screen.getAllByText(/no cached readings/i).length).toBeGreaterThan(0);
  });
});
