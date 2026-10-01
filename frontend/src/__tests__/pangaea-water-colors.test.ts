// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
import { describe, expect, it } from "vitest";
import { COASTDOM_COUNT_BINS, coastdomCountColor, gppRadiusPx, hexToRgbTriple } from "../components/map3d/colors";

describe("CoastDOM colour is a sample count, never a value", () => {
  it.each([[1, 0], [5, 1], [9, 1], [10, 2], [99, 2], [100, 3], [1415, 3]])("%i samples → bin %i", (n, bin) => {
    const [r, g, b] = hexToRgbTriple(COASTDOM_COUNT_BINS[bin].hex);
    expect(coastdomCountColor(n)).toEqual([r, g, b, 220]);
  });
});

describe("Greenland Sea GPP marker size", () => {
  it("grows with the areal rate and never vanishes", () => {
    expect(gppRadiusPx(2710.94, 2710.94)).toBe(16);
    expect(gppRadiusPx(335, 2710.94)).toBeGreaterThan(4);
    expect(gppRadiusPx(null, 2710.94)).toBe(4);
    expect(gppRadiusPx(100, 0)).toBe(4);
  });
});
