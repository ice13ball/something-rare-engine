// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";

import { AocPocPanel } from "../components/panels/ocean/AocPocPanel";
import { AOC_POC_META, AOC_POC_SAMPLES } from "./detailPanelFetchFixtures";

function ok(body: unknown) {
  return Promise.resolve({ ok: true, json: async () => body } as Response);
}

beforeEach(() => vi.setSystemTime(new Date("2026-09-25T12:00:00Z")));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); });

const STATION_PROPS = {
  station: "TEST", n_samples: 1, depth_min_db: 5, depth_max_db: 5,
  date_min: "2025-05-21T15:25:00+02:00", date_max: "2025-05-21T15:30:00+02:00",
};

function stubFetch() {
  vi.stubGlobal("fetch", vi.fn((url: string) => (url.includes("samples") ? ok(AOC_POC_SAMPLES) : ok(AOC_POC_META))));
}

describe("AocPocPanel", () => {
  it("renders every measurement value fully, with no parenthesised provenance in the labels", async () => {
    stubFetch();
    render(<AocPocPanel properties={STATION_PROPS} />);
    // Every served measurement value in the fixture sample is visible verbatim.
    expect(await screen.findByText("5")).toBeTruthy();
    expect(await screen.findByText("4.652")).toBeTruthy();
    expect(await screen.findByText("34.5031")).toBeTruthy();
    expect(await screen.findByText("0.4349")).toBeTruthy();
    expect(await screen.findByText("3.421")).toBeTruthy();
    expect(await screen.findByText("-22.321")).toBeTruthy();
    expect(await screen.findByText("0.500199883")).toBeTruthy();
    expect(await screen.findByText("0.085944997")).toBeTruthy();

    const text = document.body.textContent ?? "";
    // Labels carry only a short unit, never the raw backend provenance text
    // (the one mention of SeaDataNet/"dataset abstract" allowed is the footnote below).
    expect(text).not.toContain("(from the dataset abstract; not in the data file)");
    expect(text).not.toContain("profiling pressure sensor");
    expect(text.match(/SeaDataNet/g)?.length ?? 0).toBe(1);
    // The short labels and units are present instead.
    expect(text).toContain("Depth, nominal (dbar)");
    expect(text).toContain("Pressure (dbar)");
    expect(text).toContain("Temperature (°C)");
    expect(text).toContain("Salinity (PSU)");
    expect(text).toContain("POC (mg dm⁻³)*");
    expect(text).toContain("PN (mg dm⁻³)*");
    // Footnotes carry the provenance instead, once each.
    expect(text).toContain("* Unit from the dataset abstract; the data file does not state it.");
    expect(text).toContain("PRESPR01, D13CMOP11, D15NEAM1");
  });

  it("renders the observation window and each sample header in UTC, never the local zone", async () => {
    stubFetch();
    render(<AocPocPanel properties={STATION_PROPS} />);
    // Source offset +02:00 must be normalized to its UTC wall-clock time.
    expect(await screen.findByText(/2025-05-21 13:25 UTC – 2025-05-21 13:30 UTC/)).toBeTruthy();
    // Sample header: fixture's sample_date is "2025-05-19T04:30:00Z".
    await waitFor(() => expect(screen.getByText(/2025-05-19 04:30 UTC/)).toBeTruthy());
    const text = document.body.textContent ?? "";
    expect(text).not.toContain("15:25");
    expect(text).not.toContain("+02:00");
  });
});
