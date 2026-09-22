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
import { VENT_STATUS_VALUES } from "../types/layers";

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

// ⛔ The failure this exists to stop: on 2026-09-21 the vent status vocabulary
// changed from the invented "Active"/"Inactive"/"Extinct" to InterRidge's own
// strings. Every link shared before that date still carries the old words.
// Applied verbatim they match no feature, so the layer reads as toggled on and
// completely empty — a state a reader cannot tell apart from an outage.
describe("a link carrying a retired filter value never blanks a layer", () => {
  afterEach(() => {
    useMapStore.getState().resetAllFilters();
  });

  it("keeps the default when every vent status in the link is retired", () => {
    applyShareableFilters({ ventStatusFilters: ["Active", "Inactive", "Extinct"] });
    const live = useMapStore.getState().ventStatusFilters;
    expect([...live]).toEqual([...VENT_STATUS_VALUES]);
  });

  it("keeps only the values that still exist when a link mixes old and new", () => {
    applyShareableFilters({ ventStatusFilters: ["Active", "inactive"] });
    expect([...useMapStore.getState().ventStatusFilters]).toEqual(["inactive"]);
  });

  it("still honours a link whose vent statuses are all current", () => {
    applyShareableFilters({ ventStatusFilters: ["active, confirmed"] });
    expect([...useMapStore.getState().ventStatusFilters]).toEqual(["active, confirmed"]);
  });

  it("keeps the default when every concession risk in the link is retired", () => {
    applyShareableFilters({ claimRiskFilters: ["high", "critical"] });
    expect(useMapStore.getState().claimRiskFilters.size).toBe(0);
  });

  it("does not vet fields whose values come from the data, not from a list", () => {
    // A contractor absent from today's rows is "matches nothing right now",
    // not a stale link — vetting it would silently rewrite a valid filter.
    applyShareableFilters({ hiddenContractors: ["Nobody Ltd::polymetallic nodules"] });
    expect([...useMapStore.getState().hiddenContractors]).toEqual([
      "Nobody Ltd::polymetallic nodules",
    ]);
  });

  // ⛔ The failure this stops: on 2026-09-22 `risk_class` (Extreme/Very
  // High/High/Significant/Medium/Low/Unclassified — this platform's own
  // six-tier collapse of the source's rating) was deleted from the API. A
  // link shared before that date still carries those words against
  // tailingsRiskFilters, which now holds hazard_raw values instead.
  it("keeps the default when the link's only tailings hazard value is retired risk_class vocabulary", () => {
    // "Unclassified" is the one risk_class word with no hazard_raw equivalent —
    // every other risk_class tier (Extreme/Very High/High/Significant/Medium/Low)
    // happens to already be a literal hazard_raw string, so it stays valid.
    applyShareableFilters({ tailingsRiskFilters: ["Unclassified"] });
    expect(useMapStore.getState().tailingsRiskFilters.size).toBe(0);
  });

  it("keeps only the current hazard_raw values, including the current 'other' bucket, when a link mixes old and new", () => {
    applyShareableFilters({ tailingsRiskFilters: ["Unclassified", "Low", "other"] });
    expect([...useMapStore.getState().tailingsRiskFilters]).toEqual(["Low", "other"]);
  });
});
