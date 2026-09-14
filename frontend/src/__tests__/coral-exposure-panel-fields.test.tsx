// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// From the 2026-09-14 readiness audit of coral-acid-exposure, the same defect
// class as mosaic-sediment's 24d: a field the endpoint SELECTs, sends, and the
// panel types — then never renders.
//
// `/v1/coral-exposure/point` returns the whole row (`out = dict(r)`), so
// `uncertainty` crosses the wire on every click. It is populated on 3,837 of
// 3,837 live cells and reaches 0.474 on a 0–1 scale. Showing "suitability
// 0.837" alone presents a MaxEnt output with a wide band as though it were a
// measurement — and the sibling VmeSuitabilityPanel has always shown the same
// field, of the same model, right below the score.
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup, screen, waitFor } from "@testing-library/react";
import { CoralExposurePanel } from "../components/panels/fields/CoralExposurePanel";
import { CORAL_EXPOSURE_POINT, CORAL_EXPOSURE_SUMMARY } from "./detailPanelFetchFixtures";

/** The panel fires two independent fetches; route each by URL. */
function mockRoutes(point: unknown, summary: unknown) {
  vi.stubGlobal("fetch", vi.fn((url: string) =>
    Promise.resolve({
      ok: true,
      json: () => Promise.resolve(String(url).includes("/summary") ? summary : point),
    }),
  ) as unknown as typeof fetch);
}

const PROPS = { props: { _lat: -63.6, _lon: 169.8 } };

beforeEach(() => { vi.restoreAllMocks(); });
afterEach(() => { cleanup(); });

describe("CoralExposurePanel — the uncertainty it already fetches", () => {
  it("renders the model's uncertainty beside its suitability score", async () => {
    mockRoutes(CORAL_EXPOSURE_POINT, CORAL_EXPOSURE_SUMMARY);
    render(<CoralExposurePanel {...PROPS} />);

    // ⛔ Assert on the LABEL, which appears nowhere else in this panel. The
    // value alone ("0.100") could be matched by a threshold percentage in the
    // regional summary below and would pass with the row deleted.
    await waitFor(() => expect(screen.getByText("VME uncertainty")).toBeTruthy());
    expect(screen.getByText("0.100")).toBeTruthy();

    // The pair is the point: a score shown without its band is the defect.
    expect(screen.getByText("VME suitability")).toBeTruthy();
  });

  it("says 'no data here' rather than a blank when the source omits it", async () => {
    mockRoutes({ ...CORAL_EXPOSURE_POINT, uncertainty: null }, CORAL_EXPOSURE_SUMMARY);
    render(<CoralExposurePanel {...PROPS} />);

    await waitFor(() => expect(screen.getByText("VME uncertainty")).toBeTruthy());
    // Two rows can carry this wording (suitability may also be absent); here
    // only uncertainty is null, so exactly one must.
    expect(screen.getAllByText("no data here")).toHaveLength(1);
  });
});
