// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// FirePanel now carries daynight, version, scan and track from FIRMS.
// ⛔ These tests RENDER, and assert on labels unique to this panel's new
// rows — "Version" and "Day / Night" appear nowhere else in FirePanel.
import { describe, it, expect, afterEach } from "vitest";
import { render, cleanup, screen } from "@testing-library/react";
import { FirePanel } from "../components/panels/land/FirePanel";

afterEach(() => cleanup());

const panel = (props: Record<string, unknown>) =>
  render(<FirePanel properties={props as never} />);

const FULL = {
  id: 1, latitude: 55.09597, longitude: 21.8019, brightness: 301.75,
  confidence: "Nominal", frp: 0.62, instrument: "VIIRS", satellite: "N",
  acq_date: "2026-09-23", daynight: "N", version: "2.0NRT",
  scan: 0.46, track: 0.39,
};

const MINIMAL = {
  id: 2, latitude: 10, longitude: 20, brightness: 300, confidence: "High",
  frp: 1, instrument: "VIIRS", satellite: "N20", acq_date: "2026-09-23",
};

describe("FirePanel — the extended FIRMS fields it now carries", () => {
  it("shows Day/Night as 'Night' and the raw version string", () => {
    panel(FULL);
    expect(screen.getByText("Day / Night")).toBeTruthy();
    expect(screen.getByText("Night")).toBeTruthy();
    expect(screen.getByText("Version")).toBeTruthy();
    expect(screen.getByText("2.0NRT")).toBeTruthy();
    expect(screen.getByText("Pixel size")).toBeTruthy();
    expect(screen.getByText("0.46 × 0.39 km")).toBeTruthy();
  });

  it("renders no empty rows when a feature lacks the new fields", () => {
    panel(MINIMAL);
    expect(screen.queryByText("Day / Night")).toBeNull();
    expect(screen.queryByText("Version")).toBeNull();
    expect(screen.queryByText("Pixel size")).toBeNull();
  });
});
