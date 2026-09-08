// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { thawCategoryLabel } from "../../../utils/thawTypes";

import { Row, Section, PanelHeader } from "../shared/primitives";
import { SampleDate } from "../shared/SampleDate";

export function PermafrostThawPanel({ properties: p }: { properties: Record<string, unknown> }) {
  const cat = thawCategoryLabel(p.feature_category as string | null | undefined);
  const ftype = p.feature_type ? String(p.feature_type) : null;
  const thaw = p.thaw_type ? String(p.thaw_type) : null;
  const name = p.feature_name ? String(p.feature_name) : null;
  const doi = p.source_doi ? String(p.source_doi) : null;
  const doiUrl = doi ? (doi.startsWith("http") ? doi : `https://doi.org/${doi}`) : null;
  const authors = p.authors ? String(p.authors) : null;
  const method = p.data_source_type ? String(p.data_source_type) : null;
  const imagery = p.imagery ? String(p.imagery) : null;
  // The imagery window the source publishes for THIS feature. ⛔ Not a sampling
  // day: a thaw slump is mapped from imagery spanning a period, and the source
  // says so. Bare years stay years — obs_start/obs_end are filled only where full
  // dates were given, so the string handed to SampleDate is exactly what we were
  // told, never a year widened into 1 January.
  const precision = (p.date_precision as string | null) ?? null;
  const num = (v: unknown) => (v == null ? null : Number(v));
  const bound = (iso: unknown, year: unknown) =>
    iso ? String(iso) : year != null ? String(year) : null;
  const winStart = bound(p.obs_start, p.obs_start_year);
  const winEnd = bound(p.obs_end, p.obs_end_year);
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
