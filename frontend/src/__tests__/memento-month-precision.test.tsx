// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// MEMENTO's source pads a month-only record to day 01 at midnight. The cast
// row and the sample row both carry `time_precision`, filled at ingest since
// the layer shipped — but `/memento/by-id` never selected it, so the panel
// sliced `sample_time` to ten characters and printed a precise sampling DAY
// for records that never had one.
//
// Measured on the production database 2026-09-15:
//     casts   minute 154,550 · month   875  (0.56%)
//     samples minute 211,466 · month 6,805  (3.12%)
//
// ⛔ 17 casts really were sampled on the 1st at midnight, so the padded ones
// cannot be spotted from the timestamp — only the column can tell them apart.
// That is why this is a backend field and not a frontend heuristic.
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup, screen, waitFor } from "@testing-library/react";

import { MementoPanel } from "../components/panels/arctic/MementoPanel";

const BASE = {
  cast_id: 4242, set_name: "M77/1", station: "12",
  lat: -10.5, lon: -80.2, decade: 2000, n_samples: 1,
  min_depth_m: 0, max_depth_m: 120,
  has_ch4: true, has_n2o: false, ch4_surf: 3.2, n2o_surf: null,
  samples: [{
    depth_m: 0, sample_time: "2009-01-01T00:00:00+00:00", time_precision: "month",
    ch4: 3.2, n2o: null, n2o_perc: null, o2: 210, temp: 18.1, sal: 35.0, params: {},
  }],
};

function mockWith(extra: Record<string, unknown>) {
  vi.stubGlobal("fetch", vi.fn(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve({ ...BASE, ...extra }) }),
  ) as unknown as typeof fetch);
}

beforeEach(() => { vi.restoreAllMocks(); });
afterEach(() => { cleanup(); });

describe("MementoPanel — a padded month must not read as a sampling day", () => {
  it("prints the month alone, and says the source had no more", async () => {
    mockWith({ sample_time: "2009-01-01T00:00:00+00:00", time_precision: "month" });
    render(<MementoPanel id={4242} />);
    await waitFor(() => expect(screen.getByText("Date")).toBeTruthy());
    expect(screen.getByText("2009-01")).toBeTruthy();
    expect(screen.getByText(/month only at source/i)).toBeTruthy();
    // ⛔ The whole point: the day the source invented must be ABSENT, not
    // merely accompanied by a caveat a reader may skip.
    expect(screen.queryByText("2009-01-01")).toBeNull();
  });

  it("keeps the full day when the source really recorded one", async () => {
    // Positive control. Without it, a panel that printed the month for
    // EVERYTHING would pass the test above.
    mockWith({ sample_time: "2009-01-10T22:58:00+00:00", time_precision: "minute" });
    render(<MementoPanel id={4242} />);
    await waitFor(() => expect(screen.getByText("Date")).toBeTruthy());
    expect(screen.getByText("2009-01-10")).toBeTruthy();
    expect(screen.queryByText(/month only at source/i)).toBeNull();
  });

  it("treats a genuine 1st-of-month cast as the full day it is", async () => {
    // ⛔ The trap a frontend-only fix would have fallen into: 17 casts really
    // are day 01 at midnight. Guessing from the timestamp would relabel them.
    mockWith({ sample_time: "2009-01-01T00:00:00+00:00", time_precision: "minute" });
    render(<MementoPanel id={4242} />);
    await waitFor(() => expect(screen.getByText("Date")).toBeTruthy());
    expect(screen.getByText("2009-01-01")).toBeTruthy();
    expect(screen.queryByText(/month only at source/i)).toBeNull();
  });

  it("says nothing about precision when there is no date at all", async () => {
    mockWith({ sample_time: null, time_precision: null });
    render(<MementoPanel id={4242} />);
    await waitFor(() => expect(screen.getByText("Cast details")).toBeTruthy());
    expect(screen.queryByText("Date")).toBeNull();
    expect(screen.queryByText(/month only at source/i)).toBeNull();
  });
});
