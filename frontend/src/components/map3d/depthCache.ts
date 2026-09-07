// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// Module-level depth cache keyed by (lat,lon) rounded to 0.01° (~1km).
// Three tiers altogether: this L1 dict (sub-µs, lost on page reload) →
// L2 localStorage (instant cross-session) → L3 backend bathymetry_cache
// (~1 ms cross-user). Open-Topo-Data is only hit on a full L1+L2+L3 miss.
export type DepthCacheVal = number | "loading" | "land";
export const depthCache: Map<string, DepthCacheVal> = new Map();
export const depthCacheKey = (lat: number, lon: number) =>
  `${lat.toFixed(2)},${lon.toFixed(2)}`;

const DEPTH_LS_KEY = "abyssal_bathymetry_cache_v1";
export const DEPTH_LS_MAX_ENTRIES = 5000;  // ~150 KB serialized JSON
let depthLsLoaded = false;
let depthLsDirty = false;
let depthLsFlushTimer: number | null = null;

/** Hydrate the L1 dict from localStorage on first use. */
export function loadDepthCacheFromLS(): void {
  if (depthLsLoaded || typeof localStorage === "undefined") return;
  depthLsLoaded = true;
  try {
    const raw = localStorage.getItem(DEPTH_LS_KEY);
    if (!raw) return;
    const obj = JSON.parse(raw) as Record<string, number | "land">;
    for (const [k, v] of Object.entries(obj)) {
      depthCache.set(k, v);
    }
  } catch { /* ignore — corrupted cache just resets */ }
}

/** Debounced writeback of resolved entries to localStorage (skip "loading"). */
export function scheduleDepthCacheFlush(): void {
  depthLsDirty = true;
  if (depthLsFlushTimer != null) return;
  depthLsFlushTimer = window.setTimeout(() => {
    depthLsFlushTimer = null;
    if (!depthLsDirty) return;
    depthLsDirty = false;
    try {
      const obj: Record<string, number | "land"> = {};
      let count = 0;
      for (const [k, v] of depthCache) {
        if (v === "loading") continue;
        obj[k] = v as number | "land";
        if (++count >= DEPTH_LS_MAX_ENTRIES) break;
      }
      localStorage.setItem(DEPTH_LS_KEY, JSON.stringify(obj));
    } catch { /* quota exceeded → next flush will retry */ }
  }, 2000);
}

// Tiles whose lookup failed → epoch ms before which we won't retry. Kept
// separate from depthCache (never persisted to localStorage) so a transient
// Open-Topo-Data outage isn't remembered across sessions, but hover-driven
// retry storms against their rate limit are throttled within this one.
export const depthFailedUntil: Map<string, number> = new Map();
const DEPTH_RETRY_BACKOFF_MS = 60_000;

export function markDepthLookupFailed(key: string): void {
  depthCache.delete(key);
  depthFailedUntil.set(key, Date.now() + DEPTH_RETRY_BACKOFF_MS);
}

/** Returns formatted depth string from cache (or null if not ready / land). */
export function depthLineFromCache(lat: number, lon: number): string | null {
  loadDepthCacheFromLS();
  const v = depthCache.get(depthCacheKey(lat, lon));
  if (typeof v === "number") {
    return `<span style="color:#94a3b8">Seafloor:</span> ${Math.abs(Math.round(v)).toLocaleString()} m`;
  }
  return null;
}
