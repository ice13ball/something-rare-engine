// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useCallback, useRef, useState, type MutableRefObject } from "react";
import type { FeatureCollection } from "geojson";
import { useMapStore } from "../../store/mapStore";
import { fetchWithProgress } from "../../utils/fetchWithProgress";

const API = import.meta.env.VITE_API_BASE_URL ?? "";

/**
 * Layer-fetch machinery extracted from Map3D.tsx.
 *
 * ⛔ A FAILURE NOTICE MUST BE ABLE TO GO AWAY BY ITSELF.
 *
 * Two classes of layer used to recover differently, and only one of them was
 * right. Tile layers clear their own name on a later successful load
 * (`onTileLayerLoad` in Map3D). The 31 GeoJSON layers that come through
 * `fetchGuarded` did not: a name pushed into `failedLayers` stayed there for the
 * rest of the session even after the very next fetch succeeded, so one blip —
 * a backend restart lasting seconds — pinned "OceanSITES Moorings unavailable"
 * under a map that was in fact fully loaded. Reported from production
 * 2026-09-11, while the endpoint answered 200 with 679,250 characters on every
 * probe, alone and in a 16-way concurrent burst.
 *
 * "Retry" was the other half of the same defect. It cleared the list and bumped
 * the TILE cache version, which re-requests tiles — but nothing re-triggered the
 * GeoJSON effects, because they depend on `activeLayers` and `fetchGuarded` and
 * neither changed. So Retry made the message disappear without fetching
 * anything: the layer stayed empty and now said nothing was wrong.
 *
 * `retryNonce` is what fixes that half. It is deliberately part of
 * `fetchGuarded`'s dependency list so that bumping it gives the callback a new
 * identity, which re-runs every effect in useLayerData that lists it — the only
 * handle those effects expose.
 */
export function useLayerFetcher() {
  const [failedLayers, setFailedLayers] = useState<string[]>([]);
  const [retryNonce, setRetryNonce] = useState(0);

  // Every guard ref handed to fetchGuarded, so a retry can un-latch all of them.
  const guardedRefs = useRef(new Set<MutableRefObject<boolean>>());

  const setLayerProgress = useMapStore(s => s.setLayerProgress);
  const markLayerDone = useMapStore(s => s.markLayerDone);

  const fetchLayer = useCallback(
    async (path: string, setter: (d: FeatureCollection) => void, name: string): Promise<string | null> => {
      try {
        const data = await fetchWithProgress(
          `${API}${path}`,
          (received, total) => setLayerProgress(name, received, total),
        );
        setter(data);
        markLayerDone(name);
        // The layer is on screen; nothing about it is unavailable any more.
        setFailedLayers(prev => (prev.includes(name) ? prev.filter(n => n !== name) : prev));
        return null;
      } catch {
        markLayerDone(name);
        return name;
      }
    },
    [setLayerProgress, markLayerDone],
  );

  // Guarded one-shot layer fetch. Sets the ref so we fetch once, but on failure
  // resets it so a transient backend blip doesn't permanently blank the layer —
  // the next toggle/render retries instead of staying stuck on the failed attempt.
  const fetchGuarded = useCallback(
    (
      ref: MutableRefObject<boolean>,
      path: string,
      setter: (d: FeatureCollection) => void,
      name: string,
    ) => {
      guardedRefs.current.add(ref);
      if (ref.current) return;
      ref.current = true;
      fetchLayer(path, setter, name).then(failed => {
        if (failed) {
          ref.current = false;
          setFailedLayers(prev => (prev.includes(failed) ? prev : [...prev, failed]));
        }
      });
    },
    // ⛔ retryNonce is listed on purpose and is not read in the body: changing it
    // is how "Retry" forces useLayerData's effects to run again. Removing it
    // turns Retry back into a button that only hides the message.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [fetchLayer, retryNonce],
  );

  /**
   * Guarded one-shot fetch of a plain JSON document that is not a FeatureCollection (the GLODAP
   * casts column document). Same latch, same `failedLayers` behaviour as `fetchGuarded`: any
   * non-2xx — the API answers 503 while the product is "not loaded / temporarily unavailable" —
   * un-latches the ref and names the layer in `failedLayers`, so the layer is never silently
   * empty; a later success clears the name again.
   */
  const fetchJsonGuarded = useCallback(
    <T,>(ref: MutableRefObject<boolean>, path: string, setter: (d: T) => void, name: string) => {
      guardedRefs.current.add(ref);
      if (ref.current) return;
      ref.current = true;
      // fetchWithProgress: the loading bar and its 2 automatic retries (2 s, 4 s) — a short backend
      // blip must not raise the "unavailable" banner. It throws on any non-2xx, 503 included.
      fetchWithProgress(`${API}${path}`, (received, total) => setLayerProgress(name, received, total))
        .then((d: T) => {
          setter(d);
          markLayerDone(name);
          setFailedLayers(prev => (prev.includes(name) ? prev.filter(n => n !== name) : prev));
        })
        .catch(() => {
          markLayerDone(name);
          ref.current = false;
          setFailedLayers(prev => (prev.includes(name) ? prev : [...prev, name]));
        });
    },
    // ⛔ retryNonce on purpose, as in fetchGuarded: it is how "Retry" re-runs the calling effect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [setLayerProgress, markLayerDone, retryNonce],
  );

  /** Un-latch every guarded layer and make the effects re-run. */
  const retryGuardedLayers = useCallback(() => {
    guardedRefs.current.forEach(ref => { ref.current = false; });
    setRetryNonce(n => n + 1);
  }, []);

  return { fetchLayer, fetchGuarded, fetchJsonGuarded, failedLayers, setFailedLayers, retryGuardedLayers };
}
