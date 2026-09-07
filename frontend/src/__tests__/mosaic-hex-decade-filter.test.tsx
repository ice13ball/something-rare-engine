// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// Testujemy czystą funkcję decyzyjną, nie deck.gl — warstwa jest tylko jej konsumentem.
import { describe, it, expect } from "vitest";
import type { MosaicHexProps } from "../components/map3d/mosaicHexFilter";
import { hexPassesDecadeFilter, hexVisibleCount } from "../components/map3d/mosaicHexFilter";
import { MOSAIC_DECADES } from "../utils/mosaicVars";

const hexes: Array<{ properties: MosaicHexProps }> = [
  { properties: { count: 3, by_decade: { "1980": 3 } } },
  { properties: { count: 2, by_decade: { "2010": 2 } } },
  { properties: { count: 4, by_decade: { "1980": 1, "2010": 3 } } },
];

it("shows everything when no decade is selected", () => {
  expect(hexVisibleCount(hexes, new Set())).toBe(3);
});

it("changes the number of visible hexes when a decade is selected", () => {
  const all = hexVisibleCount(hexes, new Set());
  const only1980 = hexVisibleCount(hexes, new Set(["1980"]));
  expect(only1980).toBeLessThan(all); // <- the assertion the old code fails
  expect(only1980).toBe(2);
});

it("keeps a mixed hex visible if any of its decades is selected", () => {
  expect(hexPassesDecadeFilter(hexes[2].properties, new Set(["2010"]))).toBe(true);
});

it("hides a hex whose only decade is deselected", () => {
  expect(hexPassesDecadeFilter(hexes[0].properties, new Set(["2010"]))).toBe(false);
});

// Decades present in mosaic_cores on production, counted 2026-09-04.
const PRODUCTION_DECADES = [1900, 1950, 1960, 1970, 1980, 1990, 2000, 2010, 2020];

it("offers a bucket for every decade the data actually contains", () => {
  for (const d of PRODUCTION_DECADES) expect(MOSAIC_DECADES).toContain(d);
});

it("keeps an undated hex reachable through its own bucket", () => {
  const undatedHex = { count: 4, by_decade: {}, n_undated: 4 };
  expect(hexPassesDecadeFilter(undatedHex, new Set(["undated"]))).toBe(true);
  expect(hexPassesDecadeFilter(undatedHex, new Set(["2010"]))).toBe(false);
});

it("does not hide an undated hex when no filter is active", () => {
  expect(hexPassesDecadeFilter({ count: 4, by_decade: {}, n_undated: 4 }, new Set())).toBe(true);
});

describe("hexPassesDecadeFilter / undated", () => {
  it("does not treat a hex with by_decade entries but zero n_undated as undated-selectable", () => {
    const hex = { count: 3, by_decade: { "1980": 3 }, n_undated: 0 };
    expect(hexPassesDecadeFilter(hex, new Set(["undated"]))).toBe(false);
  });
});
