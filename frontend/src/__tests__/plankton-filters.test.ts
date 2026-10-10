// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
import { beforeEach, describe, expect, it } from "vitest";
import { useMapStore } from "../store/mapStore";
import { applyShareableFilters, collectShareableFilters } from "../types/filterRegistry";
import { applyShareableDisplay, collectShareableDisplay } from "../types/displayRegistry";

const s = () => useMapStore.getState();
const state = () => [s().planktonGroupFilters.size, s().planktonDecadeFilters.size, s().planktonDepthFilters.size,
  s().planktonShowEdna];
const narrow = () => {
  s().togglePlanktonGroupFilter("diatoms");
  s().togglePlanktonDecadeFilter("2010");
  s().togglePlanktonDepthFilter("3");
  s().togglePlanktonShowEdna();
};

beforeEach(() => s().resetAllFilters());

describe("plankton filters in the store", () => {
  it("start as 'everything' and resetAllFilters brings every one of them back", () => {
    expect(state()).toEqual([0, 0, 0, true]);
    narrow();
    expect(state()).toEqual([4, 9, 3, false]);  // a click hides one value of each
    s().resetAllFilters();
    expect(state()).toEqual([0, 0, 0, true]);
  });

  it("resetPlanktonFilters resets only the plankton filters", () => {
    narrow();
    s().toggleWodDecadeFilter("2010");
    s().resetPlanktonFilters();
    expect(state()).toEqual([0, 0, 0, true]);
    expect(s().wodDecadeFilters.size).toBe(1);
  });

  it("travel in a share link, and a value outside the vocabulary is dropped, not applied", () => {
    useMapStore.setState({ planktonGroupFilters: new Set(["copepoda"]), planktonDecadeFilters: new Set(["2010"]) });
    const f = collectShareableFilters(s());
    expect(f.planktonGroupFilters).toEqual(["copepoda"]);
    expect(f.planktonDecadeFilters).toEqual(["2010"]);
    s().resetAllFilters();
    applyShareableFilters({ planktonGroupFilters: ["copepoda", "jellyfish"], planktonDecadeFilters: ["1930"],
                            planktonDepthFilters: ["3"] });
    expect([...s().planktonGroupFilters]).toEqual(["copepoda"]);
    expect(s().planktonDecadeFilters.size).toBe(0);
    expect([...s().planktonDepthFilters]).toEqual(["3"]);
  });

  it("default filters add nothing to the link", () => {
    const f = collectShareableFilters(s());
    expect(f.planktonGroupFilters).toBeUndefined();
    expect(f.planktonDecadeFilters).toBeUndefined();
    expect(f.planktonDepthFilters).toBeUndefined();
  });

  it("eDNA off travels as a display field, and only when it differs from the default", () => {
    expect(collectShareableDisplay(s()).planktonShowEdna).toBeUndefined();
    s().togglePlanktonShowEdna();
    expect(collectShareableDisplay(s()).planktonShowEdna).toBe(false);
    s().resetAllFilters();
    applyShareableDisplay({ planktonShowEdna: false });
    expect(s().planktonShowEdna).toBe(false);
  });
});
