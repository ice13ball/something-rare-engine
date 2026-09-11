// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// A failure notice must be able to go away by itself.
//
// Reported from production 2026-09-11: "Some layers unavailable — OceanSITES
// Moorings" stayed on screen while the endpoint answered 200 with 679,250
// characters on every probe, alone and in a 16-way concurrent burst. The fetch
// was fine. The NOTICE could not un-say itself: a name pushed into
// `failedLayers` was never removed on a later success, so one backend restart
// lasting seconds pinned the warning for the rest of the session.
//
// Tile layers already did this correctly (`onTileLayerLoad` filters the name
// out). The 31 GeoJSON layers behind `fetchGuarded` did not — two classes of
// layer, two behaviours, one of them wrong.
//
// ⛔ "Retry" was the other half. It cleared the list and bumped the TILE cache,
// which re-requests tiles, while nothing re-triggered the GeoJSON effects. The
// button hid the message without fetching anything: the layer stayed empty and
// stopped saying so.
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useLayerFetcher } from "../components/map3d/useLayerFetcher";

const mockFetch = vi.fn();
vi.mock("../utils/fetchWithProgress", () => ({
  fetchWithProgress: (...args: unknown[]) => mockFetch(...args),
}));

const EMPTY = { type: "FeatureCollection", features: [] };

beforeEach(() => { mockFetch.mockReset(); });

describe("a layer that recovers stops being listed as unavailable", () => {
  it("removes the name from failedLayers when a later fetch succeeds", async () => {
    const { result } = renderHook(() => useLayerFetcher());
    const ref = { current: false };
    const setter = vi.fn();

    mockFetch.mockRejectedValueOnce(new Error("backend restarting"));
    act(() => {
      result.current.fetchGuarded(ref, "/api/v1/map/oceansites", setter, "OceanSITES Moorings");
    });
    await waitFor(() => expect(result.current.failedLayers).toContain("OceanSITES Moorings"));

    // The blip is over; the very next fetch works.
    mockFetch.mockResolvedValueOnce(EMPTY);
    act(() => {
      result.current.fetchGuarded(ref, "/api/v1/map/oceansites", setter, "OceanSITES Moorings");
    });
    await waitFor(() => expect(setter).toHaveBeenCalledWith(EMPTY));

    expect(result.current.failedLayers).not.toContain("OceanSITES Moorings");
    expect(result.current.failedLayers).toEqual([]);
  });

  it("does not list the same layer twice when it fails again", async () => {
    const { result } = renderHook(() => useLayerFetcher());
    const ref = { current: false };

    for (let i = 0; i < 2; i++) {
      mockFetch.mockRejectedValueOnce(new Error("still down"));
      act(() => {
        result.current.fetchGuarded(ref, "/api/v1/map/oceansites", vi.fn(), "OceanSITES Moorings");
      });
      await waitFor(() => expect(result.current.failedLayers.length).toBeGreaterThan(0));
    }
    expect(result.current.failedLayers).toEqual(["OceanSITES Moorings"]);
  });

  it("retryGuardedLayers un-latches a LATCHED guard and fetches again", async () => {
    // ⛔ The ref must be tested while it is actually latched. A FAILED fetch
    // already resets it inside fetchGuarded, so asserting on that path passes
    // even with the un-latching deleted — the first version of this test did
    // exactly that and stayed green through the sabotage. A SUCCEEDED layer is
    // the state where the latch is real.
    const { result } = renderHook(() => useLayerFetcher());
    const ref = { current: false };
    const setter = vi.fn();

    mockFetch.mockResolvedValueOnce(EMPTY);
    act(() => {
      result.current.fetchGuarded(ref, "/api/v1/map/oceansites", setter, "OceanSITES Moorings");
    });
    await waitFor(() => expect(setter).toHaveBeenCalledTimes(1));
    expect(ref.current).toBe(true);           // latched: a second call is a no-op

    const before = result.current.fetchGuarded;
    act(() => { result.current.retryGuardedLayers(); });

    expect(ref.current).toBe(false);          // un-latched by the retry
    // The callback identity must change too, or useLayerData's effects — which
    // list it in their deps — never run again and nothing is re-fetched.
    await waitFor(() => expect(result.current.fetchGuarded).not.toBe(before));

    // Proof it really re-fetches rather than returning early.
    mockFetch.mockResolvedValueOnce(EMPTY);
    act(() => {
      result.current.fetchGuarded(ref, "/api/v1/map/oceansites", setter, "OceanSITES Moorings");
    });
    await waitFor(() => expect(setter).toHaveBeenCalledTimes(2));
  });

  it("a successful first fetch never lists the layer at all", async () => {
    const { result } = renderHook(() => useLayerFetcher());
    mockFetch.mockResolvedValueOnce(EMPTY);
    const setter = vi.fn();
    act(() => {
      result.current.fetchGuarded({ current: false }, "/api/v1/map/claims", setter, "ISA Claims");
    });
    await waitFor(() => expect(setter).toHaveBeenCalled());
    expect(result.current.failedLayers).toEqual([]);
  });
});
