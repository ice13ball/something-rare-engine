// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// `useLiveShareUrl` is what makes "copy the URL from the address bar" a way to
// share a view. Four things about WHEN it writes decide whether that is a
// feature or a trap, and each is tested below:
//
//   1. Not on arrival. A visitor who lands and reads keeps a clean
//      something-rare.com in the bar and in their history.
//   2. Not mid-drag. Writing while the map is still moving would leave the bar
//      holding a frame the user never stopped on.
//   3. Yes, once they settle — this is the whole point.
//   4. Not twice for the same view, however many store events arrive.
//
// ⛔ (2) is the reason this uses the interaction-end signal rather than a
// timer. A 4-second debounce was considered and rejected: it leaves a
// four-second window in which the bar holds the PREVIOUS view, and someone who
// frames a shot and hits ⌘L ⌘C lands inside it. A link that is wrong and looks
// right is the failure this codebase treats as worse than no feature.
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";

import { useMapStore } from "../store/mapStore";

import { useLiveShareUrl } from "../components/map3d/useLiveShareUrl";
import { decodeShareState } from "../utils/shareState";
import type { LayerId } from "../types/layers";

const LAYERS = new Set(["argo", "contracts"] as unknown as LayerId[]);
const AT_HOME = { longitude: -30, latitude: 20, zoom: 3, pitch: 45, bearing: 0 };
const MOVED = { longitude: 105.4, latitude: -6.1, zoom: 9, pitch: 45, bearing: 0 };

const shareParam = () => new URLSearchParams(window.location.search).get("s");

/**
 * Render the hook and drive it like the component does.
 *
 * `restored` defaults to true: every test below except the restore one is
 * about behaviour AFTER the page has finished opening.
 */
function mount(view: Record<string, unknown>, interacting: boolean, restored = true) {
  return renderHook(
    ({ v, i, r }: { v: Record<string, unknown>; i: boolean; r: boolean }) =>
      useLiveShareUrl(v, LAYERS, i, r),
    { initialProps: { v: view, i: interacting, r: restored } },
  );
}

let replaceSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  window.history.replaceState({}, "", "/");
  replaceSpy = vi.spyOn(window.history, "replaceState");
  vi.useFakeTimers();
});
afterEach(() => { vi.useRealTimers(); replaceSpy.mockRestore(); });

describe("useLiveShareUrl — when the address bar is allowed to change", () => {
  it("writes nothing on arrival, so a plain visit keeps a plain URL", () => {
    mount(AT_HOME, false);
    vi.advanceTimersByTime(5000);
    expect(shareParam()).toBeNull();
  });

  it("writes nothing while the map is still being moved", () => {
    const { rerender } = mount(AT_HOME, false);
    rerender({ v: MOVED, i: true, r: true });          // dragging
    vi.advanceTimersByTime(5000);
    expect(shareParam()).toBeNull();
  });

  it("writes the new view once the drag ends", () => {
    const { rerender } = mount(AT_HOME, false);
    rerender({ v: MOVED, i: true, r: true });
    vi.advanceTimersByTime(5000);
    // ⛔ Positive control: prove it was still silent right up to the release,
    // so the assertion below is about the release and not about elapsed time.
    expect(shareParam()).toBeNull();

    rerender({ v: MOVED, i: false, r: true });   // released
    vi.advanceTimersByTime(2500);

    const param = shareParam();
    expect(param).not.toBeNull();
    const decoded = decodeShareState(param)!;
    expect(decoded.camera).toEqual(MOVED);
    expect(decoded.layers).toEqual([...LAYERS]);
  });

  it("does not write again when a store event leaves the shared view unchanged", () => {
    // ⛔ The version of this test that only re-rendered with the SAME props
    // proved nothing: React skips the effect when the dependencies are
    // identical, so no write was even scheduled and deleting the
    // already-written check left every test green. The real path is the store
    // subscription, which fires on ANY store change — selecting a feature,
    // opening a panel — none of which belongs in the link.
    const { rerender } = mount(AT_HOME, false);
    rerender({ v: MOVED, i: false, r: true });
    vi.advanceTimersByTime(2500);
    const after = replaceSpy.mock.calls.length;
    expect(after).toBeGreaterThan(0);          // it did write once

    for (let i = 0; i < 5; i++) {
      act(() => { useMapStore.setState({ selectedFeatures: [] }); });
      vi.advanceTimersByTime(3000);
    }
    expect(replaceSpy.mock.calls.length).toBe(after);
  });

  it("leaves any other query parameter alone", () => {
    window.history.replaceState({}, "", "/?lang=pl");
    const { rerender } = mount(AT_HOME, false);
    rerender({ v: MOVED, i: false, r: true });
    vi.advanceTimersByTime(2500);
    const params = new URLSearchParams(window.location.search);
    expect(params.get("lang")).toBe("pl");
    expect(params.get("s")).not.toBeNull();
  });

  it("writes nothing while the page is still restoring its own opening view", () => {
    // ⛔ The camera is resolved before the first render, but the LAYERS land an
    // effect later. Freezing the baseline in between made a returning
    // visitor's own restored layers read as a change they had made, and the
    // bar filled with a blob on arrival for everyone who had used the site
    // before. Seen in production 2026-09-14, which is why this test exists.
    const { rerender } = mount(AT_HOME, false, false);
    rerender({ v: MOVED, i: false, r: false });     // restore still landing
    vi.advanceTimersByTime(6000);
    expect(shareParam()).toBeNull();

    // ...and the view it settled on becomes the baseline, not a change.
    rerender({ v: MOVED, i: false, r: true });
    vi.advanceTimersByTime(6000);
    expect(shareParam()).toBeNull();
  });

  it("a store event during the restore does not write either", () => {
    // ⛔ The store subscription schedules writes without going through the
    // camera/layers effect, so this is the path the single `restored` guard in
    // `publish` has to cover — and the only test that makes that guard go red
    // when it is removed.
    mount(AT_HOME, false, false);
    for (let i = 0; i < 3; i++) {
      act(() => { useMapStore.setState({ selectedFeatures: [] }); });
      vi.advanceTimersByTime(3000);
    }
    expect(shareParam()).toBeNull();
    expect(replaceSpy.mock.calls.length).toBe(0);
  });
});
