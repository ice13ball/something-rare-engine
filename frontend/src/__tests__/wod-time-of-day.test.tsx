// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// WOD encodes the sampling time as a FRACTION OF A DAY. The ingest added that
// fraction to a `date` object, and `date + timedelta` keeps only whole days —
// so a cast at 06:02 UTC and one at 23:58 the same day became identical.
//
// Measured on the real wod_osd_2015.nc (8,987 casts) 2026-09-10:
//     fraction != 0 (time recorded) .... 8,450 = 94.0%
//     fraction == 0 (no time) .........    537 =  6.0%
//
// Three states must read differently in the panel: a recorded time, a source
// that recorded none, and a row not yet re-ingested. Collapsing the last two
// would invent a midnight cast for 6% of a 978,476-row layer.
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup, screen, waitFor } from "@testing-library/react";
import { WodOxygenPanel } from "../components/panels/fields/WodOxygenPanel";

const BASE = {
  id: 1, wod_cast_id: "274849", lat: 60.1, lon: -20.4,
  profile_date: "2015-07-14", decade: 2010,
  cruise: "AU006994", dataset: "OSD", country: "AUSTRALIA",
  probe_type: null, max_depth_m: 1000, n_levels: 6,
  o2_profile: [[0, 280.1], [1000, 190.4]], o2_units: "umol/kg",
  qc_flag: 0, qc_note: null,
};

function mockWith(extra: Record<string, unknown>) {
  vi.stubGlobal("fetch", vi.fn(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve({ ...BASE, ...extra }) }),
  ) as unknown as typeof fetch);
}

// ⛔ The panel takes `id`, not `props` — a copy-paste from UnifiedCarbonPanel
// (which really does take `props`) left `id` undefined here, and every
// assertion below still passed because the stubbed fetch ignores its URL.
// tsc caught it; the URL assertion in the last test is what keeps it caught.
const renderPanel = (id: number | string = 274849) =>
  render(<WodOxygenPanel id={id} />);

beforeEach(() => { vi.restoreAllMocks(); });
afterEach(() => { cleanup(); });

describe("WodOxygenPanel — time of day", () => {
  it("shows the time the source recorded", async () => {
    mockWith({ profile_time: "2015-07-14T06:02:00+00:00", time_precision: "time" });
    renderPanel();
    await waitFor(() => expect(screen.getByText("Time (UTC)")).toBeTruthy());
    expect(screen.getByText("06:02:00")).toBeTruthy();
  });

  it("says the source recorded no time, rather than showing midnight", async () => {
    mockWith({ profile_time: null, time_precision: "day" });
    renderPanel();
    await waitFor(() => expect(screen.getByText("Time (UTC)")).toBeTruthy());
    expect(screen.getByText(/not recorded at source/i)).toBeTruthy();
    expect(screen.queryByText("00:00:00")).toBeNull();
  });

  it("says nothing at all for a row that has not been re-ingested", async () => {
    // ⛔ null precision is OUR gap, not the source's. Claiming "not recorded at
    // source" here would blame NOAA for a column we only just started filling.
    mockWith({ profile_time: null, time_precision: null });
    renderPanel();
    await waitFor(() => expect(screen.getByText("Date")).toBeTruthy());
    expect(screen.queryByText("Time (UTC)")).toBeNull();
    expect(screen.queryByText(/not recorded at source/i)).toBeNull();
  });

  // The stubbed fetch answers any URL, so nothing above notices a panel that
  // never received its id. This one does: it reads the URL the panel asked for.
  it("asks for the cast it was given, not for `undefined`", async () => {
    mockWith({ profile_time: null, time_precision: "day" });
    renderPanel(981234);
    await waitFor(() => expect(screen.getByText("Date")).toBeTruthy());
    const url = String((globalThis.fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls[0][0]);
    expect(url).toContain("/wod-oxygen/by-id/981234");
  });
});
