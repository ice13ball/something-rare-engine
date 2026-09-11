// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useMapStore } from "../../../store/mapStore";
import { sourceLinkFor } from "../../../utils/sourceUrl";

import { API } from "../shared/tokens";
import { latLonFromProps } from "../shared/format";
import { Row, Section, PanelHeader, Subtitle, SourceAttribution } from "../shared/primitives";
import { SeafloorDepthRow } from "../shared/chips";

export function ChessPanel({ properties: p }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation("panels");
  const [expanded, setExpanded] = useState(false);

  const HABITAT_LABELS: Record<string, string> = {
    seep:       "COLD SEEP",
    whale_fall: "WHALE FALL",
    omz:          "UNCLASSIFIED",   // legacy value, pre-2026-09-11 rows
    unclassified: "UNCLASSIFIED",
  };
  const HABITAT_COLORS: Record<string, string> = {
    seep:       "text-teal-400",
    whale_fall: "text-pink-400",
    omz:          "text-indigo-400",
    unclassified: "text-indigo-400",
  };

  const habitat      = String(p.habitat_type ?? "unclassified");
  const locality     = String(p.locality ?? "Unknown site");
  const speciesCount = Number(p.species_count ?? 0);
  const depthM       = p.depth_m != null ? `${Number(p.depth_m).toFixed(0)} m` : "—";
  const phyla        = (p.phyla as string[] | null) ?? [];
  const speciesList  = (p.species_list as Array<{ species: string; phylum: string; depth_m: number | null; institution: string }> | null) ?? [];

  const habitatLabel = HABITAT_LABELS[habitat] ?? "CHEMOSYNTHETIC SITE";
  const habitatColor = HABITAT_COLORS[habitat] ?? "text-white/70";

  return (
    <>
      <PanelHeader>{locality}</PanelHeader>
      <Subtitle className={`mb-4 font-mono text-[13px] ${habitatColor}`}>
        {habitatLabel}
      </Subtitle>

      <Section title={t("chess.siteSectionTitle")}>
        <Row label={t("chess.depthLabel")}   value={depthM} />
        <Row label={t("chess.speciesLabel")} value={String(speciesCount)} />
        <Row label={t("chess.phylaLabel")}   value={String(phyla.length)} />
        {phyla.length > 0 && (
          <Row label={t("chess.topPhylaLabel")} value={phyla.slice(0, 3).join(", ")} />
        )}
        {(() => { const c = latLonFromProps(p); return c && <SeafloorDepthRow lat={c[0]} lon={c[1]} />; })()}
      </Section>

      {speciesList.length > 0 && (
        <Section title="">
          <button
            onClick={() => setExpanded(e => !e)}
            className="flex items-center gap-1.5 text-white/70 hover:text-white/90 text-[14px] transition-colors"
          >
            <span>{speciesList.length} species</span>
            <span className="text-xs">{expanded ? "▲" : "▼"}</span>
          </button>
          {expanded && (
            <ul className="mt-1 space-y-1 max-h-48 overflow-y-auto pr-1">
              {speciesList.map((s, i) => (
                <li key={i} className="text-[13px] text-white/80">
                  <span className="italic">{s.species || "—"}</span>
                  {s.phylum ? <span className="text-white/60 ml-1">({s.phylum})</span> : null}
                  {s.depth_m != null ? <span className="text-white/60 ml-1">· {s.depth_m} m</span> : null}
                </li>
              ))}
            </ul>
          )}
        </Section>
      )}

      <div className="mt-3">
        <button
          onClick={() => {
            const { startReportJob, reportJobs } = useMapStore.getState();
            if (reportJobs.some(j => j.platformId === locality && j.status === "generating")) return;
            startReportJob(locality, "chess");
            const ctrl = new AbortController();
            setTimeout(() => ctrl.abort(), 120_000);
            fetch(`${API}/api/v1/reports/chess-site`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ locality }),
              signal: ctrl.signal,
            }).then(r => {
              if (!r.ok) useMapStore.getState().updateReportJob(locality, "failed", `Server ${r.status}`);
            }).catch(e => {
              const msg = e?.name === "AbortError" ? "Request timed out (120s) — backend may be under load" : "Network error — check connection";
              useMapStore.getState().updateReportJob(locality, "failed", msg);
            });
          }}
          className="w-full text-center py-2 text-[14px] rounded-lg bg-teal-500/10 border border-teal-500/30 text-teal-400 hover:bg-teal-500/20 transition-colors"
        >
          {t("chess.generateReportButton")}
        </button>
      </div>
      <SourceAttribution link={sourceLinkFor("chess-species", p)} />
    </>
  );
}

