// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useLayerFetcher } from "../components/map3d/useLayerFetcher";
import { useMapStore } from "../store/mapStore";
import { fetchWithProgress } from "../utils/fetchWithProgress";

vi.mock("../utils/fetchWithProgress", () => ({
  fetchWithProgress: vi.fn(),
}));

const mockedFetch = vi.mocked(fetchWithProgress);

describe("useLayerFetcher", () => {
  beforeEach(() => {
    mockedFetch.mockReset();
    useMapStore.setState({ layerProgress: new Map() } as never);
  });

  it("success: calls setter with payload, marks done, returns null", async () => {
    const payload = { type: "FeatureCollection", features: [] } as const;
    mockedFetch.mockResolvedValue(payload);
    const setLayerProgress = vi.spyOn(useMapStore.getState(), "setLayerProgress");
    const markLayerDone = vi.spyOn(useMapStore.getState(), "markLayerDone");
    const { result } = renderHook(() => useLayerFetcher());
    const setter = vi.fn();

    let ret: string | null = "unset";
    await act(async () => {
      ret = await result.current.fetchLayer("/api/v1/map/x", setter, "Layer X");
    });

    expect(setter).toHaveBeenCalledWith(payload);
    expect(markLayerDone).toHaveBeenCalledWith("Layer X");
    expect(ret).toBeNull();
    setLayerProgress.mockRestore();
    markLayerDone.mockRestore();
  });

  it("failure: marks done, returns layer name, setter NOT called", async () => {
    mockedFetch.mockRejectedValue(new Error("boom"));
    const markLayerDone = vi.spyOn(useMapStore.getState(), "markLayerDone");
    const { result } = renderHook(() => useLayerFetcher());
    const setter = vi.fn();

    let ret: string | null = null;
    await act(async () => {
      ret = await result.current.fetchLayer("/api/v1/map/x", setter, "Layer X");
    });

    expect(setter).not.toHaveBeenCalled();
    expect(markLayerDone).toHaveBeenCalledWith("Layer X");
    expect(ret).toBe("Layer X");
    markLayerDone.mockRestore();
  });

  it("one-shot guard: two fetchGuarded calls with same ref -> exactly one fetch", async () => {
    mockedFetch.mockResolvedValue({ type: "FeatureCollection", features: [] });
    const { result } = renderHook(() => useLayerFetcher());
    const ref = { current: false };
    const setter = vi.fn();

    await act(async () => {
      result.current.fetchGuarded(ref, "/api/v1/map/x", setter, "Layer X");
      result.current.fetchGuarded(ref, "/api/v1/map/x", setter, "Layer X");
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(mockedFetch).toHaveBeenCalledTimes(1);
  });

  it("retry reset: after a failed fetchGuarded, ref resets to false and a second call fetches again", async () => {
    mockedFetch.mockRejectedValueOnce(new Error("boom"));
    mockedFetch.mockResolvedValueOnce({ type: "FeatureCollection", features: [] });
    const { result } = renderHook(() => useLayerFetcher());
    const ref = { current: false };
    const setter = vi.fn();

    await act(async () => {
      result.current.fetchGuarded(ref, "/api/v1/map/x", setter, "Layer X");
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(ref.current).toBe(false);
    expect(mockedFetch).toHaveBeenCalledTimes(1);

    await act(async () => {
      result.current.fetchGuarded(ref, "/api/v1/map/x", setter, "Layer X");
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(mockedFetch).toHaveBeenCalledTimes(2);
  });

  it("failedLayers accumulates via fetchGuarded on failure only", async () => {
    mockedFetch.mockRejectedValueOnce(new Error("boom"));
    mockedFetch.mockResolvedValueOnce({ type: "FeatureCollection", features: [] });
    const { result } = renderHook(() => useLayerFetcher());
    const setter = vi.fn();

    await act(async () => {
      result.current.fetchGuarded({ current: false }, "/api/v1/map/fail", setter, "Fail Layer");
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(result.current.failedLayers).toEqual(["Fail Layer"]);

    await act(async () => {
      result.current.fetchGuarded({ current: false }, "/api/v1/map/ok", setter, "OK Layer");
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(result.current.failedLayers).toEqual(["Fail Layer"]);
  });

  it("progress: setLayerProgress receives the received/total it is given", async () => {
    mockedFetch.mockImplementation(async (_url: string, onProgress?: (r: number, t: number) => void) => {
      onProgress?.(50, 200);
      return { type: "FeatureCollection", features: [] };
    });
    const setLayerProgress = vi.spyOn(useMapStore.getState(), "setLayerProgress");
    const { result } = renderHook(() => useLayerFetcher());
    const setter = vi.fn();

    await act(async () => {
      await result.current.fetchLayer("/api/v1/map/x", setter, "Layer X");
    });

    expect(setLayerProgress).toHaveBeenCalledWith("Layer X", 50, 200);
    setLayerProgress.mockRestore();
  });
});
