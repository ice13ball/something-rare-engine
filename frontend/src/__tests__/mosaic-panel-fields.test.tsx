// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// Two defects from the 2026-09-10 audit of mosaic-sediment, both invisible in
// a diff and both about what the panel does NOT say:
//
//   24d — `decade`, `toc_surf`, `tn_surf` and `d13c_surf` were SELECTed by
//         the endpoint and typed in the panel's own interface, and never
//         rendered. Populated on 70.2% / 65.8% / 27.5% / 22.0% of live rows.
//         We pay to fetch and store them and then hide them.
//
//   24e — the whole Samples section hung off `samples.length > 0 &&`, so a
//         core whose fetch failed and a core the source genuinely has no
//         sections for rendered identically: nothing.
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup, screen, waitFor } from "@testing-library/react";
import { MosaicPanel } from "../components/panels/arctic/MosaicPanel";
import { MOSAIC_RESPONSE } from "./detailPanelFetchFixtures";

function mockWith(body: unknown) {
  vi.stubGlobal("fetch", vi.fn(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve(body) }),
  ) as unknown as typeof fetch);
}

beforeEach(() => { vi.restoreAllMocks(); });
afterEach(() => { cleanup(); });

describe("MosaicPanel — fields the endpoint returns", () => {
  it("renders the four surface/decade fields it already fetches", async () => {
    mockWith(MOSAIC_RESPONSE);
    render(<MosaicPanel coreId={1} />);

    // ⛔ Assert on the LABELS, which exist nowhere else in this panel. The
    // numbers alone would also match the Samples table rows above and pass
    // with the feature off.
    await waitFor(() => expect(screen.getByText("Decade")).toBeTruthy());
    expect(screen.getByText("TOC, surface")).toBeTruthy();
    expect(screen.getByText("TN, surface")).toBeTruthy();
    expect(screen.getByText(/δ¹³C, surface/)).toBeTruthy();
    // and the values reach the row, not just the label
    expect(screen.getByText("2010s")).toBeTruthy();
  });

  it("hides a surface field the source did not populate, rather than showing a blank", async () => {
    mockWith({ ...MOSAIC_RESPONSE, core: { ...MOSAIC_RESPONSE.core, tn_surf: null } });
    render(<MosaicPanel coreId={1} />);

    await waitFor(() => expect(screen.getByText("TOC, surface")).toBeTruthy());
    expect(screen.queryByText("TN, surface")).toBeNull();
  });
});

describe("MosaicPanel — a core with no sections", () => {
  it("says the source records none instead of rendering nothing", async () => {
    mockWith({ ...MOSAIC_RESPONSE, samples: [] });
    render(<MosaicPanel coreId={1} />);

    await waitFor(() =>
      expect(screen.getByText(/No sections recorded for this core/i)).toBeTruthy(),
    );
    // The section header must be there too — an explanation with no heading
    // is as hard to read as a heading with no explanation.
    expect(screen.getByText("Samples")).toBeTruthy();
  });

  it("still shows the sample count when there are sections", async () => {
    mockWith(MOSAIC_RESPONSE);
    render(<MosaicPanel coreId={1} />);

    await waitFor(() => expect(screen.getByText(/^Samples \(\d+\)$/)).toBeTruthy());
    expect(screen.queryByText(/No sections recorded/i)).toBeNull();
  });
});
