// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import {
  coastdomInRangeCount, coastdomPassesYearRange, coastdomYearBounds, decodeYearRange,
  effectiveCoastdomRange, encodeYearRange, filterSamplesByYear, sampleYear,
} from "../utils/coastdomYearFilter";
import { useMapStore } from "../store/mapStore";
import { applyShareableFilters, collectShareableFilters } from "../types/filterRegistry";
import { decodeShareState, encodeShareState } from "../utils/shareState";
import { CoastdomPanel } from "../components/panels/ocean/CoastdomPanel";

const feat = (n_samples: number, year_counts?: Record<string, number>, n_undated = 0) => ({
  type: "Feature", geometry: { type: "Point", coordinates: [0, 0] },
  properties: { n_samples, n_undated, ...(year_counts ? { year_counts } : {}) },
});
// A: 1978 only; B: 2010+2022 + 2 undated; C: only undated; D: 2011 x3
const A = feat(1, { "1978": 1 });
const B = feat(6, { "2010": 1, "2022": 3 }, 2);
const C = feat(2, {}, 2);
const D = feat(3, { "2011": 3 });
const ALL = [A, B, C, D];

afterEach(() => { cleanup(); vi.unstubAllGlobals(); useMapStore.getState().resetAllFilters(); });

describe("bounds and effective range", () => {
  it("derives min/max from year_counts keys (strings)", () => {
    expect(coastdomYearBounds(ALL)).toEqual({ min: 1978, max: 2022 });
  });
  it("no year_counts anywhere -> no bounds -> cannot filter", () => {
    expect(coastdomYearBounds([feat(5), feat(2)])).toBeNull();
    expect(coastdomYearBounds([])).toBeNull();
    expect(coastdomYearBounds(null)).toBeNull();
  });
  it("a range covering the full bounds is the identity (null)", () => {
    const b = { min: 1978, max: 2022 };
    expect(effectiveCoastdomRange(null, b)).toBeNull();
    expect(effectiveCoastdomRange([1978, 2022], b)).toBeNull();
    expect(effectiveCoastdomRange([1900, 2100], b)).toBeNull();
    expect(effectiveCoastdomRange([1979, 2022], b)).toEqual([1979, 2022]);
  });
  it("missing year_counts (old cached payload) -> range ignored", () => {
    expect(effectiveCoastdomRange([2010, 2011], null)).toBeNull();
  });
});

describe("default range never hides anything", () => {
  it("default filtered set === unfiltered set, incl. undated-only positions", () => {
    const range = effectiveCoastdomRange(useMapStore.getState().coastdomYearRange, coastdomYearBounds(ALL));
    expect(range).toBeNull();
    const kept = ALL.filter((f) => coastdomPassesYearRange(f.properties, range));
    expect(kept).toEqual(ALL);
    expect(kept).toContain(C);
    for (const f of ALL) expect(coastdomInRangeCount(f.properties, range)).toBe(f.properties.n_samples);
  });
  it("full range chosen explicitly is the same as the default", () => {
    const r = effectiveCoastdomRange([1978, 2022], coastdomYearBounds(ALL));
    expect(ALL.filter((f) => coastdomPassesYearRange(f.properties, r))).toEqual(ALL);
  });
  it("features without year_counts always pass, even with a range", () => {
    expect(coastdomPassesYearRange(feat(4).properties, [2010, 2011])).toBe(true);
    expect(coastdomInRangeCount(feat(4).properties, [2010, 2011])).toBe(4);
  });
});

describe("narrowed range", () => {
  it("bounds are inclusive on both ends", () => {
    expect(coastdomInRangeCount(B.properties, [2010, 2010])).toBe(1);
    expect(coastdomInRangeCount(B.properties, [2022, 2022])).toBe(3);
    expect(coastdomInRangeCount(B.properties, [2011, 2021])).toBe(0);
    expect(coastdomInRangeCount(B.properties, [2010, 2022])).toBe(4);   // undated (2) excluded
  });
  it("shows a position iff it has >=1 sample in range; undated-only never", () => {
    const r: [number, number] = [2010, 2022];
    const kept = ALL.filter((f) => coastdomPassesYearRange(f.properties, r));
    expect(kept).toEqual([B, D]);
    expect(coastdomPassesYearRange(C.properties, r)).toBe(false);
  });
});

describe("panel-side filtering", () => {
  it("sampleYear reads the calendar year", () => {
    expect(sampleYear("2017-04-15")).toBe(2017);
    expect(sampleYear(null)).toBeNull();
    expect(sampleYear("garbage")).toBeNull();
  });
  it("null range keeps all incl. undated; a range drops undated and out-of-range", () => {
    const s = [{ sample_date: "2009-12-31" }, { sample_date: "2010-01-01" }, { sample_date: "2022-12-31" }, { sample_date: null }];
    expect(filterSamplesByYear(s, null)).toHaveLength(4);
    expect(filterSamplesByYear(s, [2010, 2022]).map((x) => x.sample_date)).toEqual(["2010-01-01", "2022-12-31"]);
  });
  it("CoastdomPanel lists only in-range samples and prints 'X of Y'; unchanged when not narrowed", async () => {
    const mk = (row_no: number, sample_date: string | null) => ({ row_no, sample_date, depth_m: 1, location: "X" });
    const samples = [mk(1, "2005-01-01"), mk(2, "2015-06-01"), mk(3, null)];
    vi.stubGlobal("fetch", vi.fn((url: string) => Promise.resolve({
      ok: true, json: async () => (url.includes("samples") ? { samples } : { versions: [] }),
    } as Response)));
    const props = { lat: 1, lon: 2, location: "X", n_samples: 3 };

    const { container, unmount } = render(<CoastdomPanel properties={props} />);
    expect(await screen.findByText(/no date in source/)).toBeTruthy();
    expect(container.textContent).toContain("2005-01-01");
    expect(container.textContent).not.toMatch(/of 3 samples in/);
    unmount();

    useMapStore.setState({ coastdomYearBounds: { min: 2005, max: 2015 }, coastdomYearRange: [2010, 2015] });
    const r2 = render(<CoastdomPanel properties={props} />);
    expect(await screen.findByText("1 of 3 samples in 2010–2015")).toBeTruthy();
    expect(r2.container.textContent).toContain("2015-06-01");
    expect(r2.container.textContent).not.toContain("2005-01-01");
    expect(r2.container.textContent).not.toMatch(/no date in source/);
  });
});

describe("store + share link", () => {
  it("resetAllFilters clears the range", () => {
    useMapStore.getState().setCoastdomYearRange([2010, 2015]);
    useMapStore.getState().resetAllFilters();
    expect(useMapStore.getState().coastdomYearRange).toBeNull();
  });
  it("default (null) is not written to a link", () => {
    expect(collectShareableFilters(useMapStore.getState()).coastdomYearRange).toBeUndefined();
  });
  it("round trip: store -> f -> encoded ?s= -> decoded -> store", () => {
    useMapStore.getState().setCoastdomYearRange([2010, 2022]);
    const f = collectShareableFilters(useMapStore.getState());
    expect(f.coastdomYearRange).toEqual(["2010", "2022"]);
    const raw = encodeShareState({
      camera: { longitude: 0, latitude: 0, zoom: 2, pitch: 0, bearing: 0 },
      layers: ["coastdom"], filters: f, openObjects: [], points: [], display: {},
    } as any);
    const decoded = decodeShareState(raw);
    expect(decoded?.filters?.coastdomYearRange).toEqual(["2010", "2022"]);
    useMapStore.getState().resetAllFilters();
    expect(useMapStore.getState().coastdomYearRange).toBeNull();
    applyShareableFilters(decoded!.filters!);
    expect(useMapStore.getState().coastdomYearRange).toEqual([2010, 2022]);
  });
  it("a malformed range in a link is dropped, never hides data", () => {
    for (const bad of [["2010"], ["a", "b"], "2010", [2010, 2022], ["20100", "2022"]]) {
      applyShareableFilters({ coastdomYearRange: bad as any });
      expect(useMapStore.getState().coastdomYearRange).toBeNull();
    }
    expect(decodeYearRange(["2022", "2010"])).toEqual([2010, 2022]);
    expect(encodeYearRange(null)).toBeNull();
  });
});
