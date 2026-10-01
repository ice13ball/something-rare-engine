// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect, useState } from "react";
import { API } from "./tokens";

/** The current version row of GET /v1/map/aoc2025-poc/meta. */
export interface Aoc2025PocVersion {
  version_id: number;
  doi: string;
  source_url: string;
  sha256: string;
  rows_in_source: number;
  citation: string;
  license: string;
  fetched_at: string;
  units: Record<string, string>;
  metadata_url: string;
  temporal_extent_discrepancy: string;
}

let pending: Promise<Aoc2025PocVersion | null> | null = null;

function load(): Promise<Aoc2025PocVersion | null> {
  if (!pending) {
    pending = fetch(`${API}/api/v1/map/aoc2025-poc/meta`)
      .then((r) => (r && r.ok ? r.json() : Promise.reject(new Error("meta unavailable"))))
      .then((d) => (d?.version ?? null) as Aoc2025PocVersion | null)
      .catch((e) => { pending = null; throw e; });   // a failure is retried, never cached
  }
  return pending;
}

/** The current AOC2025 POC version, or null while loading / on failure / before any sync. */
export function useAoc2025PocMeta(): Aoc2025PocVersion | null {
  const [v, setV] = useState<Aoc2025PocVersion | null>(null);
  useEffect(() => {
    let cancelled = false;
    load()
      .then((version) => { if (!cancelled) setV(version); })
      .catch(() => { if (!cancelled) setV(null); });
    return () => { cancelled = true; };
  }, []);
  return v;
}
