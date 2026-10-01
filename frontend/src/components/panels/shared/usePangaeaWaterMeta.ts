// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect, useState } from "react";
import { API } from "./tokens";

/** One row of GET /v1/pangaea-water/meta. `units` maps each served field to the
 *  exact PANGAEA header string, e.g. doc_umol_l → "DOC [µmol/l]". */
export interface PangaeaVersion {
  version_id: number;
  layer_id: string;
  is_current: boolean;
  doi: string;
  date_published: string | null;
  sha256: string;
  rows_in_source: number;
  rows_unmappable: number;
  data_points: number;
  citation: string | null;
  related_citation: string | null;
  license: string | null;
  ingested_at: string;
  units: Record<string, string>;
}

let pending: Promise<PangaeaVersion[]> | null = null;

function load(): Promise<PangaeaVersion[]> {
  if (!pending) {
    pending = fetch(`${API}/api/v1/pangaea-water/meta`)
      .then((r) => (r && r.ok ? r.json() : Promise.reject(new Error("meta unavailable"))))
      .then((d) => (Array.isArray(d?.versions) ? (d.versions as PangaeaVersion[]) : []))
      .catch((e) => { pending = null; throw e; });   // a failure is retried, never cached
  }
  return pending;
}

/** The CURRENT version of one layer, or null while loading / on failure. */
export function usePangaeaWaterMeta(layerId: string): PangaeaVersion | null {
  const [v, setV] = useState<PangaeaVersion | null>(null);
  useEffect(() => {
    let cancelled = false;
    load()
      .then((all) => { if (!cancelled) setV(all.find((x) => x.layer_id === layerId && x.is_current) ?? null); })
      .catch(() => { if (!cancelled) setV(null); });
    return () => { cancelled = true; };
  }, [layerId]);
  return v;
}
