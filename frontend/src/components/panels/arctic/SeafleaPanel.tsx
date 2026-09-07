// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { seepTypeLabel } from "../../../utils/seepTypes";

import { Row, Section, PanelHeader, WarningBanner } from "../shared/primitives";

// ── Methane Seeps (SEAFLEA) ───────────────────────────────────────────────────
export function SeafleaPanel({ properties: p }: { properties: Record<string, unknown> }) {
  const types  = Array.isArray(p.feature_types) ? (p.feature_types as string[]) : [];
  const raw    = (p.type_raw ?? {}) as Record<string, string>;
  const year   = typeof p.obs_year === "number" ? p.obs_year : null;
  const depth  = typeof p.depth_m  === "number" ? p.depth_m  : null;
  const uncert = typeof p.loc_uncert_m === "number" ? p.loc_uncert_m : null;
  // Pockmark morphometry (only ~12% of pockmarks carry it). Depth is stored
  // negative in the source (depression below surrounding seafloor) — show magnitude.
  const pmDepth  = typeof p.pockmark_depth_m  === "number" ? p.pockmark_depth_m  : null;
  const pmRadius = typeof p.pockmark_radius_m === "number" ? p.pockmark_radius_m : null;
  const srcUrl = p.source_url ? String(p.source_url) : null;
  return (
    <>
      <PanelHeader>Methane Seep</PanelHeader>
      <WarningBanner color="orange">
        Survey-biased coverage. SEAFLEA compiles 32 published studies, not a systematic global
        survey — one Gulf of Mexico survey supplies 59% of its 10,385 records, and the central
        North Sea has none. Where this layer shows nothing, nobody has looked; that is not
        evidence of no seep.
      </WarningBanner>
      <Section title="Feature types">
        {types.length === 0 && <Row label="" value="Unclassified" />}
        {types.map((tk) => {
          const r         = raw[tk] ?? "";
          const uncertain = r.startsWith("U(");
          return (
            <Row key={tk} label={seepTypeLabel(tk)}
              value={uncertain ? `${r} (uncertain)` : (r || "✓")} />
          );
        })}
      </Section>
      <Section title="Observation">
        <Row label="Depth"  value={depth  != null ? `${depth} m` : "—"} />
        <Row label="Year"   value={year   != null ? String(year) : "not recorded"} />
        {uncert != null && <Row label="Location uncertainty" value={`${uncert} m`} />}
      </Section>
      {(pmDepth != null || pmRadius != null) && (
        <Section title="Pockmark dimensions">
          {pmDepth  != null && <Row label="Depth"  value={`${Math.abs(pmDepth)} m below seafloor`} />}
          {pmRadius != null && <Row label="Radius" value={`${pmRadius} m`} />}
        </Section>
      )}
      {p.source_ref && (
        <Section title="Source">
          <p className="text-white/70 text-xs">{String(p.source_ref)}</p>
          {srcUrl && (
            <a href={srcUrl} target="_blank" rel="noreferrer" className="text-cyan-400 text-xs underline">
              {srcUrl}
            </a>
          )}
        </Section>
      )}
      <p className="text-white/50 text-[11px] mt-3">
        SEAFLEA is a frozen Feb-2019 compilation; not updated since.
      </p>
    </>
  );
}
