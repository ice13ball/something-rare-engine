// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const MAP3D = readFileSync(resolve(__dirname, "../components/Map3D.tsx"), "utf8");

/**
 * handleClick is a useCallback. Its dependency array carries no *DecadeFilters,
 * so a closed-over filter Set stays frozen at the first render's empty value and
 * every guard built on it silently always passes — a dead guard that reads as a
 * live one. The handler already dodges this for selectionMode by going through
 * useMapStore.getState(); the hex guards must do the same.
 */
describe("hex click guards read the filter from the store, not the closure", () => {
  // Non-greedy up to the guard's closing "))", so a nested getState() call is not truncated.
  const guards = [...MAP3D.matchAll(/hexPassesDecadeFilter\(p,\s*(.+?)\)\)\s*return/g)].map(m => m[1].trim());

  it("finds all three hex click guards", () => {
    expect(guards.length).toBe(3);
  });

  it("none of them reads a closed-over filter variable", () => {
    const closedOver = guards.filter(g => !g.includes("useMapStore.getState()"));
    expect(closedOver).toEqual([]);
  });

  it("handleClick's dependency array still lacks the filters — which is why getState is required", () => {
    // If someone later adds the filters to the dependency array, this test should
    // be revisited: the closure would then be safe and getState optional. Until
    // then, the absence is exactly what makes the store read mandatory.
    const deps = MAP3D.match(/\}, \[setSelectedFeature, claimPassesFilter[^\]]*\]\)/)?.[0] ?? "";
    expect(deps).not.toBe("");
    expect(deps).not.toMatch(/DecadeFilters/);
  });
});
