// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect, useState } from "react";
import type { Coverage } from "../components/panels/shared/TemporalFrame";
import { DECK_TO_TOGGLE } from "./layerConfig";

const API = import.meta.env.VITE_API_BASE_URL ?? "";

/**
 * One fetch of the per-layer time frames, shared by the Legend and every popup.
 *
 * Module-level cache and a single in-flight promise: the Legend and a detail panel
 * can mount in either order, or together, and this must not become two requests
 * for a table of ~20 rows that changes when someone edits a Python file.
 */
let cache: Record<string, Coverage> | null = null;
let inflight: Promise<Record<string, Coverage>> | null = null;

function load(): Promise<Record<string, Coverage>> {
  if (cache) return Promise.resolve(cache);
  if (!inflight) {
    // ⛔ Through /api/v1 (the BFF proxy), never a bare /v1 — without the proxy the
    // request lands in the SPA shell and fails silently.
    inflight = fetch(`${API}/api/v1/layers/temporal-coverage`)
      .then(r => (r.ok ? r.json() : {}))
      .then((d: Record<string, Coverage>) => { cache = d; return d; })
      .catch(() => ({} as Record<string, Coverage>))
      .finally(() => { inflight = null; });
  }
  return inflight;
}

export function useTemporalCoverage(): Record<string, Coverage> {
  const [coverage, setCoverage] = useState<Record<string, Coverage>>(cache ?? {});
  useEffect(() => {
    let alive = true;
    load().then(d => { if (alive) setCoverage(d); });
    return () => { alive = false; };
  }, []);
  return coverage;
}

/**
 * The frame for a clicked feature's layer.
 *
 * ⚠️ A popup knows the DECK layer id it was drawn from — "argo-floats-3d",
 * "cumulative-human-impact-raster", "hydrothermal-vents-inactive" — and the frames
 * are keyed by the canonical layer id ("argo", "cumulative-human-impact",
 * "hydrothermal-vents"). Looking up the deck id directly finds nothing and shows
 * nothing, with no error anywhere. DECK_TO_TOGGLE already holds that translation;
 * the direct id is the fallback for layers drawn under their own name.
 */
export function coverageForDeckLayer(
  coverage: Record<string, Coverage>, deckLayerId: string,
): Coverage | undefined {
  return coverage[DECK_TO_TOGGLE[deckLayerId] ?? deckLayerId] ?? coverage[deckLayerId];
}
