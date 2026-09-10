// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// The backend has returned wigos_id, country, sensor_models, deploy_ship and
// deployment_count on /v1/map/oceansites since the deployments ingest landed,
// and the panel read none of them. Nothing was broken and nothing raised —
// the fields simply arrived and were dropped on the floor.
//
// ⛔ sensor_models repeats models ON PURPOSE: a mooring carries the same
// instrument at several depths, so "SEABIRD_SBE37" seven times is seven real
// instruments. Deduplicating would quietly discard the size of the array.
// The raw string reaches 1,837 characters (mean 265) on production, which no
// side panel can show — hence group-and-count, the same multiset made legible.
import { describe, it, expect, afterEach } from "vitest";
import { render, cleanup, screen } from "@testing-library/react";
import { OceansitesPanel } from "../components/panels/ocean/OceansitesPanel";

afterEach(cleanup);

const station = (extra: Record<string, unknown> = {}) => ({
  ref: "5100007",
  name: "Test Mooring",
  status: "active",
  network: "OceanSITES",
  latest_obs: null,
  ...extra,
});

const renderWith = (extra: Record<string, unknown> = {}) =>
  render(<OceansitesPanel properties={station(extra) as never} />);

describe("OceanSITES station fields", () => {
  it("shows the WIGOS identifier when the source has one", () => {
    renderWith({ wigos_id: "0-22000-60-5100007" });
    expect(screen.getAllByText("0-22000-60-5100007").length).toBeGreaterThan(0);
  });

  it("shows the country", () => {
    renderWith({ country: "United States" });
    expect(screen.getAllByText("United States").length).toBeGreaterThan(0);
  });

  it("shows the ship the mooring was deployed from", () => {
    renderWith({ deploy_ship: "BLUE FIN" });
    expect(screen.getAllByText("BLUE FIN").length).toBeGreaterThan(0);
  });

  it("shows how many times the station was deployed", () => {
    renderWith({ deployment_count: 61 });
    expect(screen.getAllByText("61").length).toBeGreaterThan(0);
  });

  it("counts repeated instrument models instead of listing them again", () => {
    renderWith({ sensor_models: "SEABIRD_SBE37, SEABIRD_SBE37, DRUCK_8100, SEABIRD_SBE37" });
    expect(screen.getAllByText(/SEABIRD_SBE37 ×3/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/DRUCK_8100/).length).toBeGreaterThan(0);
  });

  it("does not add a count to a model that appears once", () => {
    renderWith({ sensor_models: "DRUCK_8100" });
    expect(screen.queryAllByText(/DRUCK_8100 ×/).length).toBe(0);
  });

  it("keeps every distinct model, not just the commonest", () => {
    // ⛔ Grouping must not become filtering.
    renderWith({ sensor_models: "A_ONE, A_ONE, B_TWO, C_THREE" });
    for (const model of ["A_ONE", "B_TWO", "C_THREE"]) {
      expect(screen.getAllByText(new RegExp(model)).length).toBeGreaterThan(0);
    }
  });

  // ── absence is not a failure ─────────────────────────────────────────────

  it("omits the WIGOS row entirely when the source has no identifier", () => {
    // ⚠️ Only 340 of 1,072 stations carry one. An em dash on the other 732
    // would read as "we failed to fetch it" rather than "there is none".
    renderWith({});
    expect(screen.queryAllByText(/WIGOS/i).length).toBe(0);
  });

  it("omits the instruments row when the source lists none", () => {
    renderWith({ sensor_models: "" });
    expect(screen.queryAllByText(/Instruments/i).length).toBe(0);
  });

  it("omits the deployment count when the source reports zero", () => {
    renderWith({ deployment_count: 0 });
    expect(screen.queryAllByText(/Deployments/i).length).toBe(0);
  });
});
