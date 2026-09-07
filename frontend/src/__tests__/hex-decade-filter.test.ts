// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { it, expect } from "vitest";
import type { HexDecadeProps } from "../components/map3d/hexDecadeFilter";
import { hexPassesDecadeFilter, hexFilteredCount } from "../components/map3d/hexDecadeFilter";

const hexes: HexDecadeProps[] = [
  { count: 3, by_decade: { "1980": 3 }, n_undated: 0 },
  { count: 2, by_decade: { "2010": 2 }, n_undated: 0 },
  { count: 4, by_decade: { "1980": 1, "2010": 3 }, n_undated: 0 },
];

it("shows everything when nothing is selected", () => {
  expect(hexes.filter(h => hexPassesDecadeFilter(h, new Set())).length).toBe(3);
});

it("changes how many hexes are visible when a decade is selected", () => {
  const all = hexes.filter(h => hexPassesDecadeFilter(h, new Set())).length;
  const only1980 = hexes.filter(h => hexPassesDecadeFilter(h, new Set(["1980"]))).length;
  expect(only1980).toBeLessThan(all);   // <- the assertion the old code fails
  expect(only1980).toBe(2);
});

it("counts only the selected decades", () => {
  expect(hexFilteredCount(hexes[2], new Set(["2010"]))).toBe(3);
  expect(hexFilteredCount(hexes[2], new Set())).toBe(4);
});

it("keeps an undated hex reachable through its own bucket", () => {
  const undated = { count: 5, by_decade: {}, n_undated: 5 };
  expect(hexPassesDecadeFilter(undated, new Set(["undated"]))).toBe(true);
  expect(hexPassesDecadeFilter(undated, new Set(["2010"]))).toBe(false);
});
