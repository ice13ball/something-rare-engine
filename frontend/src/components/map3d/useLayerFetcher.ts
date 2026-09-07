// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useCallback, useState, type MutableRefObject } from "react";
import type { FeatureCollection } from "geojson";
import { useMapStore } from "../../store/mapStore";
import { fetchWithProgress } from "../../utils/fetchWithProgress";

const API = import.meta.env.VITE_API_BASE_URL ?? "";

/**
 * Layer-fetch machinery extracted from Map3D.tsx.
 *
 * fetchGuarded's ref reset on failure is deliberate: it lets a transient
 * backend blip retry instead of permanently blanking the layer — the next
 * toggle/render retries instead of staying stuck on the failed attempt.
 */
export function useLayerFetcher() {
  const [failedLayers, setFailedLayers] = useState<string[]>([]);

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
      if (ref.current) return;
      ref.current = true;
      fetchLayer(path, setter, name).then(failed => {
        if (failed) {
          ref.current = false;
          setFailedLayers(prev => [...prev, failed]);
        }
      });
    },
    [fetchLayer],
  );

  return { fetchLayer, fetchGuarded, failedLayers, setFailedLayers };
}
