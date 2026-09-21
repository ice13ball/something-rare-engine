// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { tEnum } from "../../../utils/translateEnum";
import { isActiveVentStatus, isConfirmedVentStatus } from "../../../utils/ventStatus";

import { API } from "../shared/tokens";
import { fmt } from "../shared/format";
import { Row, Section, PanelHeader, Subtitle, Badge } from "../shared/primitives";
import { SeafloorDepthRow } from "../shared/chips";

interface VentDetail {
  id: number;
  name: string;
  // InterRidge's own Activity value, verbatim: "active, confirmed" |
  // "active, inferred" | "inactive" | null (source leaves Activity blank).
  status: string | null;
  depth_m: number | null;
  min_depth_m: number | null;
  max_temp_c: number | null;
  temp_category: string | null;
  ocean: string | null;
  region: string | null;
  jurisdiction: string | null;
  tectonic_setting: string | null;
  discovery_year: string | null;
  biology_notes: string | null;
  // Added 2026-09-21 to the SELECT — ingested since 2026-04 but never served
  // before. InterRidge's own free-text field description (664/721 records);
  // it is where the source's own status inconsistencies surface (e.g. a vent
  // recorded "active, confirmed" whose description says "not active in
  // 2002") — the evidence a reader needs to judge the status value above it.
  description_notes: string | null;
  latitude: number;
  longitude: number;
  source_url: string | null;
  created_at: string | null;
  chess_count: number;
  chess_species: Array<{ species: string; phylum: string; depth_m: number | null; institution: string }>;
  // Added 2026-09-21 — now selected by /v2/spatial/feature/hydrothermal_vents/{id}
  // (backend/routers/spatial_v2.py). `discovery_references` is the per-vent
  // citation InterRidge publishes for all 721 records.
  name_aliases: string | null;
  vent_sites: string | null;
  full_spreading_rate_mm_a: number | null;
  discovery_references: string | null;
  other_references: string | null;
}

// InterRidge's own Activity value, verbatim: "active, confirmed" |
// "active, inferred" | "inactive". ⛔ Keyed on the exact raw string, but with
// an explicit fallback below — a status InterRidge hasn't published yet (or
// left null) must still render with a visible colour, not silently fall
// through unstyled.
const STATUS_COLOR: Record<string, string> = {
  "active, confirmed": "text-orange-400",
  "active, inferred":  "text-orange-300/70",
  "inactive":          "text-blue-300",
};
const STATUS_COLOR_FALLBACK = "text-white/60";

export function VentPanel({ id }: { id: number }) {
  const { t } = useTranslation(["panels", "enums"]);
  const [data, setData] = useState<VentDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [chessExpanded, setChessExpanded] = useState(false);

  useEffect(() => {
    setLoading(true);
    setData(null);
    fetch(`${API}/api/v2/spatial/feature/hydrothermal_vents/${id}`)
      .then(r => r.ok ? r.json() : null)
      .then(setData)
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) return <p className="text-white/60 text-xs animate-pulse">Loading…</p>;
  if (!data) return <p className="text-white/60 text-xs">No data found.</p>;

  const isActive = isActiveVentStatus(data.status);
  const isConfirmed = isConfirmedVentStatus(data.status);
  const statusColorClass = data.status ? (STATUS_COLOR[data.status] ?? STATUS_COLOR_FALLBACK) : STATUS_COLOR_FALLBACK;

  const depthRange = data.min_depth_m != null && data.depth_m != null && data.min_depth_m !== data.depth_m
    ? `${data.min_depth_m.toFixed(0)}–${data.depth_m.toFixed(0)} m`
    : fmt(data.depth_m, 0, " m");

  const tempDisplay = data.max_temp_c != null
    ? `${data.max_temp_c.toFixed(0)} °C${data.temp_category ? ` (${data.temp_category})` : ""}`
    : data.temp_category ?? null;

  return (
    <>
      <PanelHeader>{data.name}</PanelHeader>
      {/* The raw InterRidge status stays visible verbatim — never translated
          away (see ventStatus.ts). The Badge below is an ADDED explanatory
          label (enums.json), not a replacement for it. */}
      <Subtitle className={`mb-1 ${statusColorClass}`}>
        {data.status ? `${data.status} hydrothermal vent` : t("vent.panelTitle")}
      </Subtitle>
      {isActive && (
        <Badge
          label={tEnum(t, "status", data.status)}
          color={isConfirmed ? "text-orange-400 border-orange-500/40" : "text-orange-300/70 border-orange-400/25"}
        />
      )}
      {data.region && (
        <p className="text-[13px] text-white/60 mb-4">
          {data.region}{data.ocean ? ` · ${data.ocean} Ocean` : ""}
        </p>
      )}

      {(data.name_aliases || data.vent_sites) && (
        <Section title={t("vent.namingSectionTitle")}>
          {data.name_aliases && <Row label={t("vent.aliasesLabel")} value={data.name_aliases} />}
          {data.vent_sites && <Row label={t("vent.subSitesLabel")} value={data.vent_sites} />}
        </Section>
      )}

      <Section title={t("vent.physicalSectionTitle")}>
        <Row label={t("vent.depthLabel")}   value={depthRange} />
        {tempDisplay && <Row label={t("vent.maxTempLabel")} value={tempDisplay} />}
        {data.tectonic_setting && <Row label={t("vent.tectonicLabel")} value={data.tectonic_setting} />}
        {data.full_spreading_rate_mm_a != null &&
          <Row label={t("vent.spreadingRateLabel")} value={fmt(data.full_spreading_rate_mm_a, 1, " mm/a")} />}
        <Row label={t("vent.lonLabel")}     value={fmt(data.longitude, 5, "°")} />
        <Row label={t("vent.latLabel")}     value={fmt(data.latitude, 5, "°")} />
        {data.latitude != null && data.longitude != null &&
          <SeafloorDepthRow lat={Number(data.latitude)} lon={Number(data.longitude)} />}
      </Section>

      {(data.jurisdiction || data.discovery_year) && (
        <Section title={t("vent.contextSectionTitle")}>
          {data.jurisdiction && <Row label={t("vent.jurisdictionLabel")} value={data.jurisdiction} />}
          {data.discovery_year && <Row label={t("vent.discoveredLabel")} value={data.discovery_year} />}
        </Section>
      )}

      {data.description_notes && (
        <Section title={t("vent.descriptionNotesSectionTitle")}>
          <p className="text-[13px] text-white/70 leading-relaxed">{data.description_notes}</p>
        </Section>
      )}

      {data.biology_notes && (
        <Section title={t("vent.biologySectionTitle")}>
          <p className="text-[13px] text-white/70 leading-relaxed">{data.biology_notes}</p>
        </Section>
      )}

      {(data.chess_count ?? 0) > 0 && (
        <div className="mb-4">
          <button
            onClick={() => setChessExpanded(e => !e)}
            className="flex items-center gap-1.5 text-teal-400 hover:text-teal-300 text-[14px] transition-colors"
          >
            <span>{data.chess_count} ChEssBase species</span>
            <span className="text-xs">{chessExpanded ? "▲" : "▼"}</span>
          </button>
          {chessExpanded && (
            <ul className="mt-1 space-y-1 max-h-40 overflow-y-auto pr-1">
              {data.chess_species.map((s, i) => (
                <li key={i} className="text-[13px] text-white/80">
                  <span className="italic">{s.species || "—"}</span>
                  {s.phylum ? <span className="text-white/60 ml-1">({s.phylum})</span> : null}
                  {s.depth_m != null ? <span className="text-white/60 ml-1">· {s.depth_m} m</span> : null}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {(data.discovery_references || data.other_references) && (
        <Section title={t("vent.referencesSectionTitle")}>
          {data.discovery_references && (
            <div className="mb-2">
              <p className="text-white/50 text-[11px] uppercase tracking-wide mb-0.5">{t("vent.discoveryReferenceLabel")}</p>
              <p className="text-[13px] text-white/75 leading-relaxed">{data.discovery_references}</p>
            </div>
          )}
          {data.other_references && (
            <div>
              <p className="text-white/50 text-[11px] uppercase tracking-wide mb-0.5">{t("vent.otherReferencesLabel")}</p>
              <p className="text-[13px] text-white/75 leading-relaxed">{data.other_references}</p>
            </div>
          )}
        </Section>
      )}

      <Section title={t("vent.sourceSectionTitle")}>
        <p className="text-[13px] text-white/60">InterRidge Vents Database v3.4 (Beaulieu & Szafrański 2020)</p>
        {/* Don't use data.source_url — backend stores the raw CSV download URL
            (vent_fields_all_*.csv), which forces a file download instead of
            opening a page. The dataset DOI resolves to a clean HTML landing
            page on doi.pangaea.de that lists all vents and metadata. There
            is no per-vent permalink — the entire dataset is one table. */}
        <a
          href="https://doi.org/10.1594/PANGAEA.917894"
          target="_blank"
          rel="noopener noreferrer"
          className="text-cyan-400 hover:text-cyan-300 text-[13px] transition-colors"
          title={t("vent.pangaeaLinkTitle")}
        >
          PANGAEA ↗
        </a>
      </Section>

      <div className="mt-3">
        <a
          href={`/vent-report/${id}`}

          className="block w-full text-center py-2 text-[14px] rounded-lg bg-orange-500/10 border border-orange-500/30 text-orange-400 hover:bg-orange-500/20 transition-colors"
        >
          {t("vent.generateReportButton")}
        </a>
      </div>
    </>
  );
}

