// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect, useState } from "react";

import { thawCategoryLabel } from "../../../utils/thawTypes";

import { API } from "../shared/tokens";
import { Row, Section, PanelHeader } from "../shared/primitives";
import { SampleDate } from "../shared/SampleDate";

// Detail-only fields, split off the bulk GeoJSON on 2026-09-08 to keep that
// payload under Cloud Run's 32 MiB proxy limit (47,239 features; imagery +
// authors + source_doi + data_source_type + obs_start/obs_end were ~10.3 MiB
// of it). Fetched lazily on click from GET .../permafrost-thaw/by-id/{unique_id}.
interface PermafrostThawDetail {
  imagery: string | null;
  authors: string | null;
  source_doi: string | null;
  data_source_type: string | null;
  obs_start: string | null;
  obs_end: string | null;
}

export function PermafrostThawPanel({ properties: p }: { properties: Record<string, unknown> }) {
  const uniqueId = p.unique_id != null ? String(p.unique_id) : null;
  // ⛔ Sent with the id, not for convenience: the row's real key is
  // (source, unique_id) — that is what the unique index is on. unique_id happens
  // to be globally unique today; the day it stops being so, a lookup without
  // source would return another feature's provenance with no error anywhere.
  const featureSource = p.source != null ? String(p.source) : null;
  // ⛔ Everything above must render from the bulk `p` properties alone — a
  // failed or slow /by-id fetch degrades to fewer rows shown, never a blank
  // panel or a spinner that can hang forever (the bulk fetch already put this
  // data in the browser; there is nothing to wait on for it).
  const [detail, setDetail] = useState<PermafrostThawDetail | null>(null);

  useEffect(() => {
    setDetail(null);
    if (!uniqueId) return;
    const ctrl = new AbortController();
    let aborted = false;
    const q = featureSource ? `?source=${encodeURIComponent(featureSource)}` : "";
    fetch(`${API}/api/v2/map/permafrost-thaw/by-id/${encodeURIComponent(uniqueId)}${q}`, { signal: ctrl.signal })
      .then(r => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then(d => { if (!aborted) setDetail(d); })
      .catch(() => { /* silent: detail rows are simply omitted below */ });
    return () => { aborted = true; ctrl.abort(); };
  }, [uniqueId, featureSource]);

  const cat = thawCategoryLabel(p.feature_category as string | null | undefined);
  const ftype = p.feature_type ? String(p.feature_type) : null;
  const thaw = p.thaw_type ? String(p.thaw_type) : null;
  const name = p.feature_name ? String(p.feature_name) : null;
  const doi = detail?.source_doi ? String(detail.source_doi) : null;
  const doiUrl = doi ? (doi.startsWith("http") ? doi : `https://doi.org/${doi}`) : null;
  const authors = detail?.authors ? String(detail.authors) : null;
  const method = detail?.data_source_type ? String(detail.data_source_type) : null;
  const imagery = detail?.imagery ? String(detail.imagery) : null;
  // The imagery window the source publishes for THIS feature. ⛔ Not a sampling
  // day: a thaw slump is mapped from imagery spanning a period, and the source
  // says so. Bare years stay years — obs_start/obs_end are filled only where full
  // dates were given, so the string handed to SampleDate is exactly what we were
  // told, never a year widened into 1 January. The full ISO bounds live behind
  // /by-id; until they arrive (or if they never do) this falls back to the year
  // form that ships in bulk, which is a coarser but still honest rendering.
  const precision = (p.date_precision as string | null) ?? null;
  const num = (v: unknown) => (v == null ? null : Number(v));
  const bound = (iso: unknown, year: unknown) =>
    iso ? String(iso) : year != null ? String(year) : null;
  const winStart = bound(detail?.obs_start, p.obs_start_year);
  const winEnd = bound(detail?.obs_end, p.obs_end_year);
  // ⛔ A different fact, deliberately labelled apart: when the digitisation was
  // contributed (2024 for 2020 imagery in ARTS), never when anything was observed.
  const contributed = p.contribution_date ? String(p.contribution_date) : null;
  return (
    <>
      <PanelHeader>Permafrost Thaw Feature</PanelHeader>
      {p.source && (
        <div className="text-white/60 text-[11px] mb-1">
          {p.source === "arts_panarctic" ? "Pan-Arctic Slumps (ARTS)" : "Alaska Thaw DB"}
        </div>
      )}
      <Section title="Feature">
        <Row label="Category" value={cat} />
        {ftype && ftype.toLowerCase() !== cat.toLowerCase() && <Row label="Reported as" value={ftype} />}
        {thaw && <Row label="Thaw type" value={thaw === "abrupt" ? "Abrupt" : "Non-abrupt"} />}
        {name && <Row label="Site" value={name} />}
      </Section>
      <Section title="Source">
        {authors && <Row label="Authors" value={authors} />}
        {method && <Row label="Method" value={method} />}
        {doiUrl && (
          <a href={doiUrl} target="_blank" rel="noreferrer" className="text-cyan-400 text-xs underline">
            {doi}
          </a>
        )}
        {precision && precision !== "none" && (
          <Row
            label="Observed"
            value={
              <SampleDate
                precision={precision as "day" | "month" | "year" | "campaign" | "none"}
                year={num(p.obs_start_year)}
                campaignStart={winStart}
                campaignEnd={winEnd}
              />
            }
          />
        )}
        {contributed && <Row label="Digitised (contributed)" value={contributed} />}
        {imagery && <Row label="Imagery" value={imagery} />}
      </Section>
      <p className="text-white/50 text-[11px] mt-3">
        {p.source === "arts_panarctic"
          ? "Circumpolar retrogressive thaw slumps. Point = centroid of a digitised polygon; observations are unevenly sampled. whrc/ARTS v6.0.0 (Yang et al. 2025, Sci. Data), CC0."
          : "Observed occurrences, unevenly sampled — denser near roads and field sites; absence of points ≠ absence of thaw. Alaska only. Webb et al. 2026 (ESSD), CC-BY 4.0."}
      </p>
    </>
  );
}
