// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { SvalbardFjordsPpPanel } from "../components/panels/ocean/SvalbardFjordsPpPanel";
import { SVALBARD_FJORDS_PP_META, SVALBARD_FJORDS_PP_SAMPLES } from "./detailPanelFetchFixtures";

function ok(body: unknown) {
  return Promise.resolve({ ok: true, json: async () => body } as Response);
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

// No _lat/_lon: that is how the panel arrives from search and from a share link.
const POSITION_PROPS = {
  position_id: "K:TEST:78.97:11.74", station: "TEST", region_code: "K", fjord_part: "Inner",
  n_expositions: 2, first_date: "2010-07-01", last_date: "2011-07-02",
};

const TWO_VISITS = {
  ...SVALBARD_FJORDS_PP_SAMPLES,
  expositions: [
    ...SVALBARD_FJORDS_PP_SAMPLES.expositions,
    { exposition_no: "2", date: "2011-07-02", fjord_part: "Inner", pi_mgc_m2_day: null,
      samples: [{ depth_m: 0, temperature_degc: null, salinity: 33.9, ca_mg_m3: 0.8, pe_mgc_m3_h: 0.7, water_mass: "SW" }] },
  ],
};

function stubFetch(samples: unknown = TWO_VISITS) {
  vi.stubGlobal("fetch", vi.fn((url: string) =>
    (url.includes("samples") ? ok(samples) : ok(SVALBARD_FJORDS_PP_META))));
}

describe("SvalbardFjordsPpPanel", () => {
  it("shows the coordinates the source wrote, taken from position_id, without a click point", async () => {
    stubFetch();
    render(<SvalbardFjordsPpPanel properties={POSITION_PROPS} />);
    expect(await screen.findByText("78.97, 11.74")).toBeTruthy();
  });

  it("attaches daily production to each visit and says so when a visit has none", async () => {
    stubFetch();
    render(<SvalbardFjordsPpPanel properties={POSITION_PROPS} />);
    expect(await screen.findByText(/Daily integrated production: 123\.4 mgC m⁻² d⁻¹/)).toBeTruthy();
    expect(await screen.findByText("Not reported for this visit")).toBeTruthy();
    // Dates render as the ISO strings the API sends, one section per visit.
    expect(screen.getByText(/^2010-07-01 · Inner$/)).toBeTruthy();
    expect(screen.getByText(/^2011-07-02 · Inner$/)).toBeTruthy();
  });

  it("labels every column with its unit and shows a missing value as a dash, never 0", async () => {
    stubFetch();
    render(<SvalbardFjordsPpPanel properties={POSITION_PROPS} />);
    await screen.findByText("Not reported for this visit");
    const text = document.body.textContent ?? "";
    for (const label of ["Depth", "Temp.", "Salinity", "mg m⁻³", "mgC m⁻³ h⁻¹", "Water mass"]) {
      expect(text).toContain(label);
    }
    // Two missing cells in the fixture: Ca at 10 m (visit 1) and temperature at 0 m (visit 2).
    expect(screen.getAllByText("—").length).toBe(2);
  });

  it("carries the IO PAN licence and never an open-licence claim", async () => {
    stubFetch();
    render(<SvalbardFjordsPpPanel properties={POSITION_PROPS} />);
    expect(await screen.findByText(/© Institute of Oceanology PAS \(IO PAN\)/)).toBeTruthy();
    expect(document.body.textContent ?? "").not.toMatch(/CC[- ]?BY/);
  });

  it("renders a long Ca value in full, never rounded or truncated", async () => {
    stubFetch({
      ...SVALBARD_FJORDS_PP_SAMPLES,
      expositions: [
        { exposition_no: "1", date: "2019-07-01", fjord_part: "Inner", pi_mgc_m2_day: null,
          samples: [{ depth_m: 5, temperature_degc: 3.1, salinity: 33.2, ca_mg_m3: 0.564099201, pe_mgc_m3_h: 1.2, water_mass: "SW" }] },
      ],
    });
    render(<SvalbardFjordsPpPanel properties={POSITION_PROPS} />);
    expect(await screen.findByText("0.564099201")).toBeTruthy();
  });
});
