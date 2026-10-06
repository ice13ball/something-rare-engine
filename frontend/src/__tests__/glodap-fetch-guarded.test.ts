// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// `fetchJsonGuarded` through the REAL fetchWithProgress (only `fetch` is stubbed): the API answers
// 503 while GLODAP is "not loaded / temporarily unavailable", and that must name the layer in
// failedLayers — never leave it silently empty — after the helper's own 2 retries.
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useLayerFetcher } from "../components/map3d/useLayerFetcher";
import { useMapStore } from "../store/mapStore";

const NAME = "GLODAP Measurements";
const PATH = "/api/v1/glodap/casts";
const doc = { product: "GLODAPv3 (2026)", n: 0, keys: [], lon: [], lat: [], year: [], values: {} };

const res = (status: number, body?: unknown) => ({
  ok: status >= 200 && status < 300,
  status,
  statusText: status === 503 ? "Service Unavailable" : "OK",
  headers: { get: () => null },       // no Content-Length -> fetchWithProgress' json() branch
  body: null,
  json: async () => body,
});

/** Let the helper's 2 s + 4 s backoff elapse. */
const settle = () => act(async () => { await vi.advanceTimersByTimeAsync(10_000); });

describe("fetchJsonGuarded", () => {
  const fetchMock = vi.fn();
  beforeEach(() => {
    vi.useFakeTimers();
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(console, "warn").mockImplementation(() => {});
    useMapStore.setState({ layerProgress: new Map() } as never);
  });
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

  it("a 503 (after the 2 automatic retries) names the layer in failedLayers and never calls the setter", async () => {
    fetchMock.mockResolvedValue(res(503));
    const markLayerDone = vi.spyOn(useMapStore.getState(), "markLayerDone");
    const { result } = renderHook(() => useLayerFetcher());
    const setter = vi.fn();
    const ref = { current: false };

    await act(async () => { result.current.fetchJsonGuarded(ref, PATH, setter, NAME); });
    await settle();

    expect(fetchMock).toHaveBeenCalledTimes(3);              // 1 + 2 retries
    expect(String(fetchMock.mock.calls[0][0])).toContain(PATH);
    expect(setter).not.toHaveBeenCalled();
    expect(result.current.failedLayers).toEqual([NAME]);
    expect(markLayerDone).toHaveBeenCalledWith(NAME);
  });

  it("a blip the retries absorb raises no banner", async () => {
    fetchMock.mockResolvedValueOnce(res(503)).mockResolvedValue(res(200, doc));
    const { result } = renderHook(() => useLayerFetcher());
    const setter = vi.fn();

    await act(async () => { result.current.fetchJsonGuarded({ current: false }, PATH, setter, NAME); });
    await settle();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(setter).toHaveBeenCalledWith(doc);
    expect(result.current.failedLayers).toEqual([]);
  });

  it("the latch resets on failure, a later call re-fetches, and its success clears the name", async () => {
    fetchMock.mockResolvedValueOnce(res(503)).mockResolvedValueOnce(res(503)).mockResolvedValueOnce(res(503))
      .mockResolvedValue(res(200, doc));
    const { result } = renderHook(() => useLayerFetcher());
    const setter = vi.fn();
    const ref = { current: false };

    await act(async () => { result.current.fetchJsonGuarded(ref, PATH, setter, NAME); });
    await settle();
    expect(ref.current).toBe(false);
    expect(result.current.failedLayers).toEqual([NAME]);

    await act(async () => { result.current.fetchJsonGuarded(ref, PATH, setter, NAME); });
    await settle();
    expect(fetchMock).toHaveBeenCalledTimes(4);
    expect(setter).toHaveBeenCalledWith(doc);
    expect(result.current.failedLayers).toEqual([]);
    expect(ref.current).toBe(true);                          // loaded: stays latched
  });

  it("one-shot: two calls with the same ref issue one request", async () => {
    fetchMock.mockResolvedValue(res(200, doc));
    const { result } = renderHook(() => useLayerFetcher());
    const ref = { current: false };
    await act(async () => {
      result.current.fetchJsonGuarded(ref, PATH, vi.fn(), NAME);
      result.current.fetchJsonGuarded(ref, PATH, vi.fn(), NAME);
    });
    await settle();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("feeds the loading bar and finishes it on success", async () => {
    fetchMock.mockResolvedValue(res(200, doc));
    const setLayerProgress = vi.spyOn(useMapStore.getState(), "setLayerProgress");
    const markLayerDone = vi.spyOn(useMapStore.getState(), "markLayerDone");
    const { result } = renderHook(() => useLayerFetcher());
    await act(async () => { result.current.fetchJsonGuarded({ current: false }, PATH, vi.fn(), NAME); });
    await settle();
    expect(setLayerProgress).toHaveBeenCalledWith(NAME, expect.any(Number), expect.any(Number));
    expect(markLayerDone).toHaveBeenCalledWith(NAME);
  });
});
