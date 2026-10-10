// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
import { describe, expect, it, vi, beforeEach } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useLayerFetcher } from "../components/map3d/useLayerFetcher";
import { useArgoOxygenDocs } from "../components/map3d/useArgoOxygenDocs";
import { LAYER_DEFAULTS, sortDeckLayers } from "../utils/layerConfig";
import {
  ARGO_FAILED_NAME, fileArgoDoc, mergeYearBounds, selectArgoDoc, touchArgoDepth, type ArgoOxygenDoc,
} from "../utils/argoOxygenPoints";

const mockFetch = vi.fn();
vi.mock("../utils/fetchWithProgress", () => ({
  fetchWithProgress: (...args: unknown[]) => mockFetch(...args),
}));

const docAt = (depth: number, years = [2010]): ArgoOxygenDoc => ({
  product: "BGC-Argo DOXY", depth, window: [depth, depth], units: "µmol/kg", n: years.length,
  floats: ["aoml_1900722"], fi: years.map(() => 0), cycle: years.map((_, i) => i + 1), descending: [],
  lon: years.map(() => 1), lat: years.map(() => 2), year: years, value: years.map(() => 200),
});

type Pending = { depth: number; resolve: (d: unknown) => void; reject: (e: Error) => void };
let pending: Pending[];
beforeEach(() => {
  mockFetch.mockReset();
  pending = [];
  mockFetch.mockImplementation((url: string) => new Promise((resolve, reject) => {
    pending.push({ depth: Number(String(url).split("/").pop()), resolve, reject });
  }));
});
const requested = () => pending.map((p) => p.depth);
const answer = async (depth: number, d: ArgoOxygenDoc = docAt(depth)) => {
  const p = pending.find((x) => x.depth === depth)!;
  await act(async () => { p.resolve(d); });
};
const fail = async (depth: number) => {
  const p = pending.find((x) => x.depth === depth)!;
  await act(async () => { p.reject(new Error("500")); });
};
const mount = (depth: number, drawing = true) => renderHook(
  ({ depth: dp, drawing }) => {
    const fetcher = useLayerFetcher();
    return { fetcher, argo: useArgoOxygenDocs(drawing, dp, fetcher.fetchJsonGuarded) };
  },
  { initialProps: { depth, drawing } },
);

describe("selectArgoDoc", () => {
  it("returns the selected depth's own document, and only while Measurements is on", () => {
    const docs = { 200: docAt(200), 500: docAt(500) };
    expect(selectArgoDoc(docs, 500, true)?.depth).toBe(500);
    expect(selectArgoDoc(docs, 500, false)).toBeUndefined();
    expect(selectArgoDoc(docs, 1000, true)).toBeUndefined();           // loading: empty, never the previous depth
    expect(selectArgoDoc({ 500: docAt(200) }, 500, true)).toBeUndefined();   // a mis-filed document is never drawn
  });
  it("slow 200 m answer after the user moved to 500 m: 500 m is not drawn from it", () => {
    const afterSwitch = fileArgoDoc({}, docAt(200), touchArgoDepth([200], 500)).docs;   // 200 arrives late
    expect(selectArgoDoc(afterSwitch, 500, true)).toBeUndefined();
    const both = fileArgoDoc(afterSwitch, docAt(500), [500, 200]).docs;
    expect(selectArgoDoc(both, 500, true)?.depth).toBe(500);
  });
});

describe("fileArgoDoc eviction", () => {
  it("keeps the current depth and the last two visited; reports what it dropped", () => {
    let docs: Record<number, ArgoOxygenDoc> = {};
    let recent: number[] = [];
    let dropped: number[] = [];
    for (const d of [0, 50, 100, 200]) {
      recent = touchArgoDepth(recent, d);
      ({ docs, dropped } = fileArgoDoc(docs, docAt(d), recent));
    }
    expect(Object.keys(docs).map(Number).sort((a, b) => a - b)).toEqual([50, 100, 200]);
    expect(dropped).toEqual([0]);
  });
  it("never evicts the selected depth, even when an older document arrives last", () => {
    const { docs, dropped } = fileArgoDoc({ 500: docAt(500), 50: docAt(50), 100: docAt(100) }, docAt(0), [500, 50, 100, 0]);
    expect(Object.keys(docs).map(Number).sort((a, b) => a - b)).toEqual([50, 100, 500]);
    expect(dropped).toEqual([0]);           // the late arrival itself is the oldest: filed, then dropped
  });
  it("merges the year span per arriving document", () => {
    const a = mergeYearBounds(null, docAt(0, [2005, 2010]));
    expect(a).toEqual({ min: 2005, max: 2010 });
    expect(mergeYearBounds(a, docAt(50, [2008]))).toBe(a);
    expect(mergeYearBounds(a, docAt(50, [2003, 2026]))).toEqual({ min: 2003, max: 2026 });
  });
});

describe("useArgoOxygenDocs wiring (real useLayerFetcher, controlled network)", () => {
  it("a slow 200 m answer arriving after 500 m was selected never replaces 500 m", async () => {
    const { result, rerender } = mount(200);
    await waitFor(() => expect(requested()).toEqual([200]));
    rerender({ depth: 500, drawing: true });
    await waitFor(() => expect(requested()).toEqual([200, 500]));
    expect(result.current.argo.doc).toBeUndefined();                    // nothing drawn while 500 m loads
    await answer(500);
    expect(result.current.argo.doc?.depth).toBe(500);
    await answer(200);                                                  // the slow one, last
    expect(result.current.argo.doc?.depth).toBe(500);
    expect(Object.keys(result.current.argo.docs).map(Number).sort((a, b) => a - b)).toEqual([200, 500]);
  });

  it("slow 200 m (HTTP 200) and 500 m failing (HTTP 500): the banner names the layer, 500 m stays empty, 200 m is not drawn for it", async () => {
    const { result, rerender } = mount(200);
    await waitFor(() => expect(requested()).toEqual([200]));
    rerender({ depth: 500, drawing: true });
    await waitFor(() => expect(requested()).toEqual([200, 500]));
    await fail(500);
    await waitFor(() => expect(result.current.fetcher.failedLayers).toEqual([ARGO_FAILED_NAME]));
    expect(result.current.argo.doc).toBeUndefined();
    await answer(200);                                                  // the slow success arrives after the failure
    expect(result.current.argo.doc).toBeUndefined();                    // 500 m is still selected: never draw 200 m's values
    rerender({ depth: 200, drawing: true });
    expect(result.current.argo.doc?.depth).toBe(200);                   // and it is there when the user goes back
  });

  it("Retry does not refetch a depth that is already loaded, but does refetch a failed one", async () => {
    const { result, rerender } = mount(500);
    await waitFor(() => expect(requested()).toEqual([500]));
    await answer(500);
    expect(result.current.argo.doc?.depth).toBe(500);

    act(() => { result.current.fetcher.retryGuardedLayers(); });
    await new Promise((r) => setTimeout(r, 30));
    expect(requested()).toEqual([500]);                                 // still one request: no 2.6 MiB re-download
    expect(result.current.argo.doc?.depth).toBe(500);

    rerender({ depth: 1000, drawing: true });
    await waitFor(() => expect(requested()).toEqual([500, 1000]));
    await fail(1000);
    await waitFor(() => expect(result.current.fetcher.failedLayers).toEqual([ARGO_FAILED_NAME]));
    act(() => { result.current.fetcher.retryGuardedLayers(); });
    await waitFor(() => expect(requested()).toEqual([500, 1000, 1000]));   // the failed depth IS refetched
  });

  it("keeps at most the current depth and the last two decoded; an evicted depth is fetched again on a revisit", async () => {
    const { result, rerender } = mount(0);
    for (const d of [0, 50, 100, 200]) {
      if (d !== 0) rerender({ depth: d, drawing: true });
      await waitFor(() => expect(requested().filter((x) => x === d)).toHaveLength(1));
      await answer(d);
    }
    expect(Object.keys(result.current.argo.docs).map(Number).sort((a, b) => a - b)).toEqual([50, 100, 200]);
    expect(result.current.argo.bounds).toEqual({ min: 2010, max: 2010 });
    rerender({ depth: 100, drawing: true });                            // still held: no request
    await new Promise((r) => setTimeout(r, 30));
    expect(requested().filter((x) => x === 100)).toHaveLength(1);
    rerender({ depth: 0, drawing: true });                              // evicted: fetched again
    await waitFor(() => expect(requested().filter((x) => x === 0)).toHaveLength(2));
  });

  it("fetches nothing while Measurements is off", async () => {
    const { rerender } = mount(500, false);
    await new Promise((r) => setTimeout(r, 30));
    expect(requested()).toEqual([]);
    rerender({ depth: 500, drawing: true });                            // turning Measurements on fetches
    await waitFor(() => expect(requested()).toEqual([500]));
  });
});

describe("argo-oxygen-points deck layer order (real nested layersRaw shape)", () => {
  it("sorts after every oxygen-deox bitmap tile, which arrive as a nested array", () => {
    const layers = [{ id: "argo-oxygen-points" }, [{ id: "oxygen-deox-bitmap-recent-500-0" }, { id: "oxygen-deox-bitmap-recent-500-1" }]];
    const sorted = sortDeckLayers(layers, LAYER_DEFAULTS).map((l: any) => l.id);
    expect(sorted).toHaveLength(3);
    expect(sorted[sorted.length - 1]).toBe("argo-oxygen-points");
  });
});
