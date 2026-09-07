// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useLayerData } from "../components/map3d/useLayerData";
import type { LayerId } from "../types/layers";
import type { FeatureCollection } from "geojson";
import type { MutableRefObject } from "react";

type Guarded = (
  ref: MutableRefObject<boolean>,
  path: string,
  setter: (d: FeatureCollection) => void,
  name: string,
) => void;

describe("useLayerData", () => {
  let fetchGuarded: ReturnType<typeof vi.fn<Guarded>>;

  beforeEach(() => {
    fetchGuarded = vi.fn<Guarded>();
  });

  it("fetches a layer once on first activation", () => {
    const active = new Set<LayerId>(["eez"]);
    const { rerender } = renderHook(({ a }) => useLayerData(a, fetchGuarded), {
      initialProps: { a: active },
    });

    expect(fetchGuarded).toHaveBeenCalledTimes(1);
    expect(fetchGuarded.mock.calls[0][1]).toBe("/api/v1/map/eez");
    expect(fetchGuarded.mock.calls[0][3]).toBe("EEZ Boundaries");

    // re-render with the same (new but equal-content) Set — a real ref
    // guard call is idempotent regardless of how many times the effect fires,
    // so simulate two consecutive activations to show it isn't literally
    // resetting the guard on every render.
    rerender({ a: new Set<LayerId>(["eez"]) });
    expect(fetchGuarded).toHaveBeenCalledTimes(2); // effect deps changed (new Set), calls fetchGuarded again — the ref guard itself lives in the real fetchGuarded implementation, verified in useLayerFetcher.test.ts
  });

  it("does not call fetchGuarded for a layer that is not active", () => {
    const active = new Set<LayerId>([]);
    renderHook(() => useLayerData(active, fetchGuarded));
    expect(fetchGuarded).not.toHaveBeenCalled();
  });

  it("passes distinct refs per layer so a failed fetch stays independently retryable", () => {
    const active = new Set<LayerId>(["eez", "seamounts"]);
    renderHook(() => useLayerData(active, fetchGuarded));

    const refs = fetchGuarded.mock.calls.map(c => c[0]);
    expect(refs.length).toBe(2);
    expect(refs[0]).not.toBe(refs[1]);
    // Each ref starts false (untried) — useLayerFetcher.test.ts covers the
    // reset-on-failure retry behaviour of fetchGuarded itself.
    for (const ref of refs) expect(ref.current).toBe(false);
  });

  it("returns state setters wired to the right layer (setter identity round-trip)", () => {
    const active = new Set<LayerId>(["seamounts"]);
    const { result } = renderHook(() => useLayerData(active, fetchGuarded));
    expect(result.current.seamountsData).toBeNull();

    const setter = fetchGuarded.mock.calls.find(c => c[1] === "/api/v1/map/seamounts")?.[2];
    expect(setter).toBeTypeOf("function");
    act(() => setter!({ type: "FeatureCollection", features: [] }));
    expect(result.current.seamountsData).toEqual({ type: "FeatureCollection", features: [] });
  });
});
