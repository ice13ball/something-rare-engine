// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect, useState } from "react";
import { API } from "./tokens";

export interface SvalbardFjordsPpDiscrepancy {
  key: string;
  metadata_says: string | null;
  data_shows: string;
}

/** The current version row of GET /v1/map/svalbard-fjords-pp/meta. */
export interface SvalbardFjordsPpVersion {
  version_id: number;
  doi: string;
  source_url: string;
  metadata_url: string;
  sha256: string;
  rows_in_source: number;
  citation: string;
  licence: string;
  fetched_at: string;
  units: Record<string, string>;
  counts: {
    rows: number;
    expositions: number;
    positions: number;
    named_stations: number;
    per_region: Record<string, { rows: number; expositions: number }>;
  };
  date_range: { first_date: string | null; last_date: string | null };
  column_notes: {
    ca_mg_m3: string;
    water_mass: { expansions: Record<string, string>; attribution: string };
    salinity: string;
  };
  discrepancies: SvalbardFjordsPpDiscrepancy[];
}

let pending: Promise<SvalbardFjordsPpVersion | null> | null = null;

function load(): Promise<SvalbardFjordsPpVersion | null> {
  if (!pending) {
    pending = fetch(`${API}/api/v1/map/svalbard-fjords-pp/meta`)
      .then((r) => (r && r.ok ? r.json() : Promise.reject(new Error("meta unavailable"))))
      .then((d) => (d?.version ?? null) as SvalbardFjordsPpVersion | null)
      .catch((e) => { pending = null; throw e; });   // a failure is retried, never cached
  }
  return pending;
}

/** The current Svalbard Fjords PP version, or null while loading / on failure / before any sync. */
export function useSvalbardFjordsPpMeta(): SvalbardFjordsPpVersion | null {
  const [v, setV] = useState<SvalbardFjordsPpVersion | null>(null);
  useEffect(() => {
    let cancelled = false;
    load()
      .then((version) => { if (!cancelled) setV(version); })
      .catch(() => { if (!cancelled) setV(null); });
    return () => { cancelled = true; };
  }, []);
  return v;
}
