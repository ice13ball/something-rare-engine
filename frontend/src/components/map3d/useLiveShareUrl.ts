// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

/**
 * Keeps `?s=` in the address bar in step with what the map is showing, so a
 * reader can share a view by copying the URL instead of finding the button.
 *
 * ⭐ The trigger is "the user stopped moving the map", not a fixed timer.
 * `Map3D` already maintains exactly that signal: `isInteracting` goes false
 * 150 ms after the last view change. A 4-second debounce was considered and
 * rejected — it leaves a four-second window in which the bar holds the
 * PREVIOUS view, and someone who frames a view and hits ⌘L ⌘C lands inside it.
 * The link would then be wrong and look right, which is the failure this
 * codebase treats as worse than no feature at all. Settling on the real
 * interaction-end signal narrows that window to ~0.15 s, which you could only
 * hit by copying mid-drag.
 *
 * ⚠️ The button in the footer stays the authoritative path: it reads live state
 * with no delay at all. The address bar is a convenience layered on top.
 *
 * Measured on Chromium 2026-09-14: 400 consecutive `history.replaceState`
 * calls completed in 29 ms with no error, so there is no throttle to respect
 * there. Safari has historically refused frequent calls and could NOT be
 * measured here (no Safari in this harness), so `MIN_WRITE_INTERVAL_MS` stays
 * as a ceiling regardless — it costs nothing and removes a class of bug we
 * cannot otherwise rule out.
 */
import { useEffect, useRef } from "react";

import { useMapStore } from "../../store/mapStore";
import { collectShareableFilters } from "../../types/filterRegistry";
import type { LayerId } from "../../types/layers";
import { liveShareParam } from "../../utils/liveShareUrl";

/** No more than one address-bar write per this many ms. See the Safari note above. */
const MIN_WRITE_INTERVAL_MS = 2000;

function currentParam(
  viewState: Record<string, unknown>,
  activeLayers: Set<LayerId>,
): string | null {
  const vs = viewState as Record<string, number>;
  if (typeof vs.longitude !== "number" || typeof vs.latitude !== "number") return null;
  return liveShareParam({
    camera: {
      longitude: vs.longitude,
      latitude: vs.latitude,
      zoom: vs.zoom,
      pitch: vs.pitch ?? 0,
      bearing: vs.bearing ?? 0,
    },
    layers: [...activeLayers],
    filters: collectShareableFilters(useMapStore.getState()),
  }).param;
}

/** Replace only `s`, leaving any other query parameter alone. */
function writeParam(param: string): void {
  const params = new URLSearchParams(window.location.search);
  params.set("s", param);
  window.history.replaceState({}, "", `${window.location.pathname}?${params.toString()}`);
}

export function useLiveShareUrl(
  viewState: Record<string, unknown>,
  activeLayers: Set<LayerId>,
  isInteracting: boolean,
): void {
  const lastWritten = useRef<string | null>(null);
  const lastWriteAt = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  /**
   * The view as it was when the map mounted. Until something actually differs
   * from it we write nothing, so a visitor who lands on the site and reads it
   * keeps a clean `something-rare.com` in the bar and a clean entry in their
   * history. The bar starts carrying state the moment they change something —
   * which is also the moment it becomes worth sharing.
   */
  const baseline = useRef<string | null | undefined>(undefined);

  /**
   * Whether the map is being moved RIGHT NOW, readable from inside the timer.
   *
   * ⛔ Checking `isInteracting` only when the write is SCHEDULED is not enough,
   * and the guard test caught it: a write scheduled while the map was still
   * fired a second or two later, mid-drag, and published a frame the user
   * never stopped on. The question "has the user settled?" has to be asked
   * when the write happens, not when it was queued.
   */
  const interacting = useRef(isInteracting);
  interacting.current = isInteracting;

  const publish = useRef(() => {});
  publish.current = () => {
    if (interacting.current) return;           // still moving — the settle will re-schedule
    const param = currentParam(viewState, activeLayers);
    if (baseline.current === undefined) baseline.current = param;
    if (param === null || param === baseline.current || param === lastWritten.current) return;
    writeParam(param);
    lastWritten.current = param;
    lastWriteAt.current = Date.now();
  };

  const schedule = useRef(() => {});
  schedule.current = () => {
    if (timer.current) return;                       // one pending write is enough
    const wait = Math.max(0, MIN_WRITE_INTERVAL_MS - (Date.now() - lastWriteAt.current));
    timer.current = setTimeout(() => {
      timer.current = null;
      publish.current();
    }, wait);
  };

  // Camera and layers: wait until the drag/zoom has actually finished.
  useEffect(() => {
    if (baseline.current === undefined) baseline.current = currentParam(viewState, activeLayers);
    if (isInteracting) return;
    schedule.current();
  }, [isInteracting, viewState, activeLayers]);

  // Filters live in the store, not in props. Any store change schedules a write;
  // `publish` drops it when the resulting param is unchanged, so selecting a
  // feature or opening a panel costs nothing.
  useEffect(() => useMapStore.subscribe(() => schedule.current()), []);

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
}
