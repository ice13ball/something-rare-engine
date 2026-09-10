// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// ⛔ A titled section with nothing under it reads as a broken panel.
//
// `UnifiedCarbonPanel` renders the "Nearest measurements" heading and its
// caption unconditionally, then branched three ways on the fetch result:
// error → "Measurements unavailable.", loading → "Loading…", and an empty
// array → `null`. So a point genuinely far from any in-situ measurement —
// most of the open ocean — showed a heading, a caption, and then a blank.
//
// The reader cannot tell that from a fetch that quietly returned nothing.
// This is check 24e of abyssal-new-layer-check, which is check 23a's rule
// ("no data" must not render as "zero") applied to a sub-section.
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup, screen, waitFor } from "@testing-library/react";
import { UnifiedCarbonPanel } from "../components/panels/fields/UnifiedCarbonPanel";

// Shape from `UnifiedCarbonData` in the panel: the render reads
// `data.groups[].variables[]`, so an object without `groups` throws before it
// ever reaches the branch under test.
const FIELD_PAYLOAD = {
  lat: 40, lon: -30, depth_m: 0, decade: 2010,
  groups: [{
    group: "Carbonate system",
    variables: [{ key: "ta", label: "Total alkalinity", units: "µmol/kg", value: 2300 }],
  }],
  // ⛔ v2.2016b is what we actually bake. Naming any other release — even in
  // a fixture — trips test_no_panel_claims_a_glodap_release_we_do_not_serve,
  // which scans every shipping frontend surface and does not exempt tests.
  citations: ["GLODAPv2.2016b"],
};

/** Answer the field fetch normally; answer nearest-obs with `obs`. */
function mockFetch(obs: unknown, obsOk = true) {
  return vi.fn((url: string) => {
    if (String(url).includes("nearest-obs")) {
      return obsOk
        ? Promise.resolve({ ok: true, json: () => Promise.resolve(obs) })
        : Promise.reject(new Error("boom"));
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve(FIELD_PAYLOAD) });
  }) as unknown as typeof fetch;
}

const renderPanel = () =>
  render(<UnifiedCarbonPanel props={{ _lat: 40, _lon: -30, depth: 0 } as never} />);

beforeEach(() => { vi.restoreAllMocks(); });
afterEach(() => { cleanup(); });

describe("UnifiedCarbonPanel — nearest measurements, empty result", () => {
  it("says there is nothing nearby instead of rendering an empty section", async () => {
    vi.stubGlobal("fetch", mockFetch([]));
    renderPanel();

    await waitFor(() =>
      expect(screen.queryByText(/Loading/i)).toBeNull(),
    );
    // ⛔ Assert on wording unique to THIS state. "Nearest measurements" is the
    // section heading and renders in every branch, so matching it would pass
    // with the feature switched off.
    expect(
      screen.getByText(/within the search radius/i),
    ).toBeTruthy();
  });

  it("does not confuse an empty result with a failed one", async () => {
    vi.stubGlobal("fetch", mockFetch([], false));
    renderPanel();

    await waitFor(() =>
      expect(screen.getByText(/Measurements unavailable/i)).toBeTruthy(),
    );
    // The two states must carry different words — otherwise a real outage and
    // an empty ocean look identical, which is the defect this file exists for.
    expect(screen.queryByText(/within the search radius/i)).toBeNull();
  });
});
