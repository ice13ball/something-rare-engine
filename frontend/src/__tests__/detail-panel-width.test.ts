// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
import { describe, expect, it } from "vitest";

import { detailPanelWidth } from "../components/DetailPanel";

describe("detailPanelWidth", () => {
  it("clamps to the 320px floor on a typical laptop viewport", () => {
    expect(detailPanelWidth(1024)).toBe(320);
  });

  it("scales with viewport width inside the clamp range", () => {
    expect(detailPanelWidth(1366)).toBe(355);
  });

  it("clamps to the 460px ceiling on a large desktop viewport", () => {
    expect(detailPanelWidth(1920)).toBe(460);
  });

  it("keeps the 320px floor on a phone where it still fits", () => {
    expect(detailPanelWidth(375)).toBe(320);
  });

  it("goes below 320px only when the viewport itself is too narrow", () => {
    expect(detailPanelWidth(320)).toBe(288);
  });
});
