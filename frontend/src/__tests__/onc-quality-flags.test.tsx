// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// ONC publishes a quality flag with every sample. Measured over 75 readings
// from 25 stations on 2026-09-10: 7% carried flag 3 ("bad but potentially
// correctable") and 1% flag 4 ("bad") — roughly one displayed reading in
// twelve had already been marked doubtful by the people who collected it,
// and the panel showed it exactly like a good one.
//
// ⛔ The value stays on screen. ONC's doubt is shown BESIDE it. Hiding
// flagged readings would put "we have no reading" and "we have a doubtful
// reading" back on one code path — the confusion this layer just spent a
// day untangling.
//
// ⛔ Flags 7 (averaged) and 8 (interpolated) are processing notes, NOT
// errors. Marking them would cry wolf on most of a healthy station, so the
// "does not mark" test below is as load-bearing as the "does mark" one.
// Scale: https://wiki.oceannetworks.ca/display/DP/Quality+Assurance+Quality+Control
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup, screen } from "@testing-library/react";
import { OncPanel } from "../components/panels/ocean/OncPanel";

const station = (sensors: Record<string, unknown>) => ({
  location_code: "TESTQC",
  name: "Test Station",
  depth_m: 100,
  lat: 48.3,
  lon: -126.1,
  latest_sensors: sensors,
  sensors_fetched_at: "2026-09-10T00:00:00Z",
});

const reading = (value: number, qc: number | null | undefined) => ({
  value, unit: "mL/L", label: "Oxygen", time: "2026-09-09T00:00:00.000Z",
  ...(qc === undefined ? {} : { qc }),
});

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve({}) } as Response)));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const renderWith = (qc: number | null | undefined) =>
  render(<OncPanel properties={station({ oxygen: reading(7.7, qc) }) as never} />);

describe("ONC quality flags in the panel", () => {
  it("marks a reading ONC flagged as bad (4)", () => {
    renderWith(4);
    expect(screen.queryByTitle(/quality flag 4/i)).not.toBeNull();
  });

  it("marks a reading ONC flagged as bad-but-correctable (3)", () => {
    renderWith(3);
    expect(screen.queryByTitle(/quality flag 3/i)).not.toBeNull();
  });

  it("still shows the value of a flagged reading", () => {
    // ⛔ The measurement survives; only its presentation changes.
    renderWith(4);
    expect(screen.getByText(/7\.70/)).toBeTruthy();
  });

  it("does not mark a good reading (1)", () => {
    renderWith(1);
    expect(screen.queryByTitle(/quality flag/i)).toBeNull();
  });

  it("does not mark an averaged reading (7)", () => {
    // Averaging is a processing note, not a defect.
    renderWith(7);
    expect(screen.queryByTitle(/quality flag/i)).toBeNull();
  });

  it("does not mark an interpolated reading (8)", () => {
    renderWith(8);
    expect(screen.queryByTitle(/quality flag/i)).toBeNull();
  });

  it("does not mark a reading ONC never evaluated (0)", () => {
    // 0 means "no QC performed" — an absence of judgement, not a bad verdict.
    renderWith(0);
    expect(screen.queryByTitle(/quality flag/i)).toBeNull();
  });

  it("does not mark a reading cached before we kept flags", () => {
    // Older rows carry no `qc` key at all. That is not doubt.
    renderWith(undefined);
    expect(screen.queryByTitle(/quality flag/i)).toBeNull();
  });
});
