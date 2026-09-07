// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect, useRef } from "react";
import { useMapStore } from "../store/mapStore";

export function LayerLoadingProgress() {
  const layerProgress = useMapStore(s => s.layerProgress);
  const clearLayerProgress = useMapStore(s => s.clearLayerProgress);
  const timersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  // Auto-dismiss 5s after a layer finishes
  useEffect(() => {
    for (const [name, entry] of layerProgress) {
      if (entry.done && !timersRef.current.has(name)) {
        timersRef.current.set(
          name,
          setTimeout(() => {
            clearLayerProgress(name);
            timersRef.current.delete(name);
          }, 5000),
        );
      }
    }
    // Cleanup timers for entries removed externally
    for (const [name, timer] of timersRef.current) {
      if (!layerProgress.has(name)) {
        clearTimeout(timer);
        timersRef.current.delete(name);
      }
    }
  }, [layerProgress, clearLayerProgress]);

  if (layerProgress.size === 0) return null;

  const entries = Array.from(layerProgress.entries());

  return (
    <div className="fixed bottom-8 left-4 z-panel flex flex-col gap-1.5 pointer-events-none w-56">
      {entries.map(([name, { received, total, done }]) => {
        const pct = total > 0 ? Math.min(Math.round((received / total) * 100), 100) : 0;
        const indeterminate = total === 0 && !done;
        return (
          <div
            key={name}
            className={`bg-surface-overlay border border-white/10 rounded-lg px-3 py-2 transition-opacity duration-700 ${
              done ? "opacity-40" : "opacity-100"
            }`}
          >
            <div className="flex items-center justify-between mb-1">
              <span className="text-white/70 text-[14px] truncate mr-2">{name}</span>
              <span className="text-white/70 text-[13px] font-mono shrink-0">
                {done ? "\u2713" : indeterminate ? "" : `${pct}%`}
              </span>
            </div>
            <div className="h-[3px] bg-white/10 rounded-full overflow-hidden">
              {indeterminate ? (
                <div className="h-full w-1/3 bg-white/40 rounded-full animate-pulse" />
              ) : (
                <div
                  className="h-full w-full bg-white/60 rounded-full transition-transform duration-300 origin-left"
                  style={{ transform: `scaleX(${(done ? 100 : pct) / 100})` }}
                />
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
