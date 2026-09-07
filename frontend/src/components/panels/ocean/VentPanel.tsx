// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { tEnum } from "../../../utils/translateEnum";

import { API } from "../shared/tokens";
import { fmt } from "../shared/format";
import { Row, Section, PanelHeader, Subtitle } from "../shared/primitives";
import { SeafloorDepthRow } from "../shared/chips";

interface VentDetail {
  id: number;
  name: string;
  status: string;
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
  latitude: number;
  longitude: number;
  source_url: string | null;
  created_at: string | null;
  chess_count: number;
  chess_species: Array<{ species: string; phylum: string; depth_m: number | null; institution: string }>;
}

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

  const STATUS_COLOR: Record<string, string> = {
    Active:   "text-orange-400",
    Inactive: "text-blue-300",
    Extinct:  "text-white/60",
  };

  const depthRange = data.min_depth_m != null && data.depth_m != null && data.min_depth_m !== data.depth_m
    ? `${data.min_depth_m.toFixed(0)}–${data.depth_m.toFixed(0)} m`
    : fmt(data.depth_m, 0, " m");

  const tempDisplay = data.max_temp_c != null
    ? `${data.max_temp_c.toFixed(0)} °C${data.temp_category ? ` (${data.temp_category})` : ""}`
    : data.temp_category ?? null;

  return (
    <>
      <PanelHeader>{data.name}</PanelHeader>
      <Subtitle className={`mb-1 ${STATUS_COLOR[data.status] ?? "text-white/70"}`}>
        {tEnum(t, "status", data.status)} hydrothermal vent
      </Subtitle>
      {data.region && (
        <p className="text-[13px] text-white/60 mb-4">
          {data.region}{data.ocean ? ` · ${data.ocean} Ocean` : ""}
        </p>
      )}

      <Section title={t("vent.physicalSectionTitle")}>
        <Row label={t("vent.depthLabel")}   value={depthRange} />
        {tempDisplay && <Row label={t("vent.maxTempLabel")} value={tempDisplay} />}
        {data.tectonic_setting && <Row label={t("vent.tectonicLabel")} value={data.tectonic_setting} />}
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

