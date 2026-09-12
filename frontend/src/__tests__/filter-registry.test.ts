// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// Requirement 5's compile-time guard (AssertComplete/AssertDisjoint over the
// store's Set<string> fields) can't itself go red in a runtime test — a
// missing field fails `tsc`, not `vitest`. What CAN be asserted at runtime is
// the behavioural half: exportCheckedLayers never leaks into a link, and an
// unknown/malformed filter key is dropped rather than poisoning the rest.
import { describe, it, expect, afterEach } from "vitest";

import {
  SHAREABLE_FILTER_FIELDS,
  isShareableFilterField,
  collectShareableFilters,
  applyShareableFilters,
} from "../types/filterRegistry";
import { useMapStore } from "../store/mapStore";

describe("exportCheckedLayers is UI state, never shareable", () => {
  it("is not in the shareable field list", () => {
    expect(SHAREABLE_FILTER_FIELDS as readonly string[]).not.toContain("exportCheckedLayers");
    expect(isShareableFilterField("exportCheckedLayers")).toBe(false);
  });

  it("collectShareableFilters ignores exportCheckedLayers even if it holds values", () => {
    useMapStore.setState({ exportCheckedLayers: new Set(["contracts"]) } as any);
    const out = collectShareableFilters(useMapStore.getState());
    expect(out.exportCheckedLayers).toBeUndefined();
  });
});

describe("only non-empty filter sets are collected", () => {
  it("omits empty sets so a typical link stays short", () => {
    const out = collectShareableFilters(useMapStore.getState());
    // ventStatusFilters defaults non-empty; most others default empty.
    expect(out.claimRiskFilters).toBeUndefined();
  });

  it("includes a field once it has values", () => {
    useMapStore.setState({ claimRiskFilters: new Set(["high"]) } as any);
    const out = collectShareableFilters(useMapStore.getState());
    expect(out.claimRiskFilters).toEqual(["high"]);
  });
});

describe("applying a decoded filter payload", () => {
  afterEach(() => {
    useMapStore.setState({ iucnFilters: new Set() } as any);
  });

  it("applies a known field", () => {
    applyShareableFilters({ iucnFilters: ["EN", "CR"] });
    expect([...useMapStore.getState().iucnFilters]).toEqual(["EN", "CR"]);
  });

  it("drops an unknown key without throwing", () => {
    expect(() => applyShareableFilters({ notARealField: ["x"] })).not.toThrow();
  });

  it("drops a malformed value (not a string array) for a known key", () => {
    applyShareableFilters({ iucnFilters: [1, 2] as any });
    expect(useMapStore.getState().iucnFilters.size).toBe(0);
  });
});
