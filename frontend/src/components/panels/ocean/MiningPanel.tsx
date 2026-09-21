// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useMapStore } from "../../../store/mapStore";
import type { VentConflict } from "../../../store/mapStore";
import { getResourceImpact } from "../../../utils/resourceImpact";
import { tEnum } from "../../../utils/translateEnum";
import { sourceLinkFor } from "../../../utils/sourceUrl";
import { isActiveVentStatus } from "../../../utils/ventStatus";

import { API, T } from "../shared/tokens";
import { fmt, fmtDate } from "../shared/format";
import { Row, Section, PanelHeader, Subtitle, BodyText, WarningBanner, SourceAttribution } from "../shared/primitives";
import { SeafloorDepthRow, BathymetryConfidenceBlock } from "../shared/chips";

interface MiningDetail {
  isa_id: string;
  contractor_name: string;
  resource_type: string | null;
  area_km2: number | null;
  act_date: string | null;
  expiry_date: string | null;
  is_high_risk: boolean;
  jurisdiction_text: string | null;
  nearest_eez_country: string | null;
  nearest_eez_dist_km: number | null;
  nearest_unesco_site: string | null;
  nearest_unesco_dist_km: number | null;
  centroid_lon: number | null;
  centroid_lat: number | null;
}

function ExpandToggle({ label, expanded, onToggle, color }: {
  label: string; expanded: boolean; onToggle: () => void; color: string;
}) {
  return (
    <button onClick={onToggle} className={`${T.expand} ${color}`}>
      <span className={`transition-transform inline-block ${expanded ? "rotate-90" : ""}`}>▶</span>
      {label}
    </button>
  );
}

export function MiningPanel({ id }: { id: string }) {
  const { t } = useTranslation(["panels", "enums"]);
  const [data, setData] = useState<MiningDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [speciesExpanded, setSpeciesExpanded] = useState(false);
  const [argoExpanded, setArgoExpanded] = useState(false);
  const [oncExpanded, setOncExpanded] = useState(false);
  const [oceansitesExpanded, setOceansitesExpanded] = useState(false);
  const [noiseExpanded, setNoiseExpanded] = useState(false);
  const [chessExpanded, setChessExpanded] = useState(false);
  const { ventConflicts, plumeHistoryQueue, riskAreas, flyTo, ventsData, fetchPlumeHistory } = useMapStore();
  const [tracingHistory, setTracingHistory] = useState(false);

  useEffect(() => {
    setLoading(true);
    setData(null);
    fetch(`${API}/api/v2/spatial/feature/mining_contracts/${encodeURIComponent(id)}`)
      .then(r => r.ok ? r.json() : null)
      .then(setData)
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) return <p className="text-white/60 text-xs animate-pulse">Loading…</p>;
  if (!data) return <p className="text-white/60 text-xs">No data found.</p>;

  const RESOURCE_COLOR: Record<string, string> = {
    "Polymetallic Manganese Nodules":    "text-cyan-400",
    "Polymetallic Sulphides":            "text-yellow-400",
    "Cobalt-Rich Ferromanganese Crusts": "text-pink-400",
  };

  const conflicts: VentConflict[] = ventConflicts[data.isa_id] ?? [];
  const historyCount = plumeHistoryQueue.find(h => h.contractorName === data.contractor_name)?.data.features.length ?? 0;
  const risk = riskAreas.find(r => r.isaId === data.isa_id);
  const species = risk
    ? [...new Map(risk.hotspots.filter(h => h?.scientific_name).map(h => [h.scientific_name, h])).values()]
    : [];
  const argoFloats = risk?.argoFloats ?? [];
  const oncStations = risk?.oncStations ?? [];
  const oceansitesMoorings = risk?.oceansitesMoorings ?? [];
  const noiseCells = risk?.noiseCells ?? [];
  const chessSites = risk?.chessSites ?? [];

  const getVentCoords = (ventName: string): [number, number] | null => {
    const feat = ventsData?.features.find(f => f.properties?.name === ventName);
    return feat?.geometry ? ((feat.geometry as any).coordinates as [number, number]) : null;
  };

  return (
    <>
      <PanelHeader>{data.contractor_name}</PanelHeader>
      {data.resource_type && (
        <Subtitle className={`mb-3 ${RESOURCE_COLOR[data.resource_type] ?? "text-white/70"}`}>
          {tEnum(t, "resourceType", data.resource_type)}
        </Subtitle>
      )}

      {data.nearest_unesco_dist_km != null && data.nearest_unesco_dist_km < 200 && (
        <WarningBanner color="red">{t("concession.unescoHighSensitivityWarning", { dist: Math.round(data.nearest_unesco_dist_km) })}</WarningBanner>
      )}

      {historyCount > 0 && (
        <WarningBanner color="orange">{t("concession.plumeHistoryWarning", { count: historyCount })}</WarningBanner>
      )}

      {data.contractor_name && (
        <button
          type="button"
          disabled={tracingHistory || historyCount > 0}
          onClick={async () => {
            if (!fetchPlumeHistory) return;
            setTracingHistory(true);
            try { await fetchPlumeHistory(data.contractor_name); }
            finally { setTracingHistory(false); }
          }}
          className="w-full text-left text-[13px] py-1.5 px-2 mb-2 rounded border border-orange-400/30 bg-orange-400/10 hover:bg-orange-400/20 disabled:opacity-50 disabled:cursor-not-allowed text-orange-200 transition-colors"
        >
          {historyCount > 0
            ? t("concession.plumeHistoryLoaded", { count: historyCount })
            : tracingHistory ? t("concession.plumeHistoryTracing")
            : t("concession.plumeHistoryTrack")}
        </button>
      )}

      <Section title={t("concession.contractSectionTitle")}>
        <Row label={t("concession.isaIdLabel")}  value={data.isa_id} />
        <Row label={t("concession.areaLabel")}   value={fmt(data.area_km2, 0, " km²")} />
        <Row label={t("concession.issuedLabel")} value={fmtDate(data.act_date)} />
        <Row label={t("concession.expiresLabel")} value={fmtDate(data.expiry_date)} />
        {data.centroid_lat != null && data.centroid_lon != null &&
          <SeafloorDepthRow lat={data.centroid_lat} lon={data.centroid_lon} />}
      </Section>

      <Section title={t("concession.jurisdictionSectionTitle")}>
        <Row label={t("concession.jurisdictionZoneLabel")}  value={data.jurisdiction_text ?? "—"} />
        <Row label={t("concession.nearestEezLabel")}        value={data.nearest_eez_country ?? "—"} />
        <Row label={t("concession.eezDistanceLabel")}       value={fmt(data.nearest_eez_dist_km, 1, " km")} />
      </Section>

      {data.nearest_unesco_site && (
        <Section title={t("concession.unescoHeritageSectionTitle")}>
          <Row label={t("concession.unescoSiteLabel")}     value={data.nearest_unesco_site} />
          <Row label={t("concession.unescoDistanceLabel")} value={fmt(data.nearest_unesco_dist_km, 1, " km")} />
        </Section>
      )}

      {/* Biodiversity species — only when records fall strictly inside the
          claim (species = booleanPointInPolygon hits). Do NOT show on the
          is_high_risk flag alone: a claim can be flagged while having zero
          records on it, and asserting "biodiversity recorded in this area"
          with nothing inside is misleading. */}
      {species.length > 0 && (
        <div className="mb-4 border-t border-orange-500/20 pt-3">
          <p className="text-orange-300 text-[14px] font-medium mb-1">
            {t("concession.biodiversitySpeciesCount", { count: species.length })}
          </p>
          {data.resource_type && (
            <BodyText className="mb-2">
              {getResourceImpact(t as (key: string, opts?: Record<string, unknown>) => string, data.resource_type) || t("concession.biodiversityOverlapGeneric")}
            </BodyText>
          )}
          <ExpandToggle
            label={t("concession.affectedSpeciesToggle", { count: species.length })}
            expanded={speciesExpanded}
            onToggle={() => setSpeciesExpanded(v => !v)}
            color="text-orange-400/70 hover:text-orange-300"
          />
          {speciesExpanded && (
            <ul className="space-y-2 max-h-36 overflow-y-auto custom-scrollbar">
              {species.map((s: any) => (
                <li key={s.scientific_name} className="text-[14px]">
                  <span className="text-white italic">{s.scientific_name}</span>
                  {s.vernacular_name && <span className="text-white/60 ml-1">({s.vernacular_name})</span>}
                  {s.phylum && <div className="text-white/60 text-[13px]">{[s.phylum, s.class_name].filter(Boolean).join(" › ")}</div>}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Vent conflicts */}
      {conflicts.length > 0 && (
        <div className="mb-4 border-t border-red-500/20 pt-3">
          <p className="text-red-300 text-[14px] font-medium mb-1">
            {t("concession.ventConflictsCount", { count: conflicts.length })}
          </p>
          <BodyText className="mb-2">{t("concession.ventConflictsBody")}</BodyText>
          <ul className="space-y-1">
            {conflicts.map((v, i) => {
              const coords = getVentCoords(v.vent_name);
              return (
                <li key={i} className="text-[14px] flex items-start gap-1.5">
                  <span className={`mt-0.5 flex-shrink-0 w-1.5 h-1.5 rounded-full ${isActiveVentStatus(v.vent_status) ? "bg-red-400" : "bg-white/30"}`} />
                  <span>
                    {flyTo && coords ? (
                      <button onClick={() => flyTo(coords[0], coords[1])} className="text-white/90 hover:text-white underline decoration-dotted">
                        {v.vent_name}
                      </button>
                    ) : (
                      <span className="text-white/90">{v.vent_name}</span>
                    )}
                    <span className="text-white/60 ml-1.5">{v.vent_status}</span>
                    {v.depth_m != null && <span className="text-white/55 ml-1.5">{v.depth_m.toLocaleString()} m</span>}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {/* Argo floats */}
      {argoFloats.length > 0 && (
        <div className="mb-4 border-t border-pink-500/20 pt-3">
          <p className="text-pink-300 text-[14px] font-medium mb-1">
            {t("concession.argoFloatsCount", { count: argoFloats.length })}
          </p>
          <BodyText className="mb-2">{t("concession.argoFloatsBody")}</BodyText>
          <ExpandToggle
            label={t("concession.argoFloatsToggle")}
            expanded={argoExpanded}
            onToggle={() => setArgoExpanded(v => !v)}
            color="text-pink-400/70 hover:text-pink-300"
          />
          {argoExpanded && (
            <ul className="space-y-1.5 max-h-28 overflow-y-auto custom-scrollbar">
              {argoFloats.map((f: any, i: number) => {
                const p = f.properties;
                const zones: { name: string; dist_km: number }[] = p.mining_zones ?? [];
                const distKm = zones.find(z => z.name === data.contractor_name)?.dist_km;
                const temp = p.surface_temp_c != null ? `${Number(p.surface_temp_c).toFixed(1)}°C` : null;
                const coords = f.geometry?.coordinates as [number, number] | undefined;
                return (
                  <li key={p.profile_id || i} className="text-[14px] text-white/85">
                    {flyTo && coords ? (
                      <button onClick={() => flyTo(coords[0], coords[1])} className="text-pink-300/80 font-mono hover:text-pink-200 underline decoration-dotted">
                        {p.platform_id}
                      </button>
                    ) : (
                      <span className="text-pink-300/80 font-mono">{p.platform_id}</span>
                    )}
                    {distKm != null && <span className="ml-1.5 text-pink-400/60">{Math.round(distKm)} km</span>}
                    {temp && <span className="ml-1.5">{temp}</span>}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}

      {/* ONC observatories nearby */}
      {oncStations.length > 0 && (
        <div className="mb-4 border-t border-teal-500/20 pt-3">
          <p className="text-teal-300 text-[14px] font-medium mb-1">
            {t("concession.oncStationsCount", { count: oncStations.length })}
          </p>
          <BodyText className="mb-2">{t("concession.oncStationsBody")}</BodyText>
          <ExpandToggle
            label={t("concession.oncStationsToggle")}
            expanded={oncExpanded}
            onToggle={() => setOncExpanded(v => !v)}
            color="text-teal-400/70 hover:text-teal-300"
          />
          {oncExpanded && (
            <ul className="space-y-1 max-h-28 overflow-y-auto custom-scrollbar">
              {oncStations.map((f: any, i: number) => {
                const p = f.properties;
                const coords = f.geometry?.coordinates as [number, number] | undefined;
                return (
                  <li key={p.location_code ?? i} className="text-[14px] flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-teal-400 flex-shrink-0" />
                    {flyTo && coords ? (
                      <button onClick={() => flyTo(coords[0], coords[1])} className="text-white/90 hover:text-white underline decoration-dotted">
                        {p.name || p.location_code}
                      </button>
                    ) : (
                      <span className="text-white/90">{p.name || p.location_code}</span>
                    )}
                    {p.depth_m != null && <span className="text-white/60 ml-auto">{Math.round(p.depth_m).toLocaleString()} m</span>}
                  </li>
                );
              })}
            </ul>
          )}
          <p className="text-white/55 text-[13px] mt-1.5">Source: ONC Oceans 3.0 — CC BY 4.0</p>
        </div>
      )}

      {/* OceanSITES moorings nearby */}
      {oceansitesMoorings.length > 0 && (
        <div className="mb-4 border-t border-cyan-500/20 pt-3">
          <p className="text-cyan-300 text-[14px] font-medium mb-1">
            {t("concession.oceansitesMooringsCount", { count: oceansitesMoorings.length })}
          </p>
          <BodyText className="mb-2">{t("concession.oceansitesMooringsBody")}</BodyText>
          <ExpandToggle
            label={t("concession.oceansitesMooringsToggle")}
            expanded={oceansitesExpanded}
            onToggle={() => setOceansitesExpanded(v => !v)}
            color="text-cyan-400/70 hover:text-cyan-300"
          />
          {oceansitesExpanded && (
            <ul className="space-y-1 max-h-28 overflow-y-auto custom-scrollbar">
              {oceansitesMoorings.map((f: any, i: number) => {
                const p = f.properties;
                const coords = f.geometry?.coordinates as [number, number] | undefined;
                return (
                  <li key={p.ref ?? i} className="text-[14px] flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 flex-shrink-0" />
                    {flyTo && coords ? (
                      <button onClick={() => flyTo(coords[0], coords[1])} className="text-white/90 hover:text-white underline decoration-dotted">
                        {p.name || p.ref}
                      </button>
                    ) : (
                      <span className="text-white/90">{p.name || p.ref}</span>
                    )}
                    {p.network && <span className="text-white/60 ml-1 text-[13px]">{p.network}</span>}
                  </li>
                );
              })}
            </ul>
          )}
          <p className="text-white/55 text-[13px] mt-1.5">Source: OceanSITES / NDBC — CC BY</p>
        </div>
      )}

      {/* Noise risk cells nearby */}
      {noiseCells.length > 0 && (
        <div className="mb-4 border-t border-orange-500/20 pt-3">
          <p className="text-white/85 text-[14px] font-medium mb-1">
            {t("concession.noiseCellsCount", { count: noiseCells.length })}
          </p>
          <BodyText className="mb-2">{t("concession.noiseCellsBody")}</BodyText>
          <ExpandToggle
            label={t("concession.noiseCellsToggle")}
            expanded={noiseExpanded}
            onToggle={() => setNoiseExpanded(v => !v)}
            color="text-orange-400/70 hover:text-orange-300"
          />
          {noiseExpanded && (
            <ul className="space-y-1 max-h-28 overflow-y-auto custom-scrollbar">
              {noiseCells.slice(0, 8).map((f: any, i: number) => {
                const p = f.properties;
                const LEVEL_COLOR: Record<string, string> = {
                  critical: "text-red-400", high: "text-orange-400",
                  moderate: "text-yellow-400", low: "text-green-400",
                  minimal: "text-white/60", data_gap: "text-slate-400",
                };
                return (
                  <li key={p.cell_key ?? i} className="text-[14px] flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-orange-400 flex-shrink-0" />
                    <span className={`font-medium ${LEVEL_COLOR[p.risk_level] ?? "text-white/70"}`}>
                      {(p.risk_level ?? "unknown").toUpperCase().replace("_", " ")}
                    </span>
                    <span className="text-white/65 text-[13px]">index {Number(p.risk_index ?? 0).toFixed(2)}</span>
                    {p.max_species && <span className="text-white/60 text-[13px] truncate">{p.max_species}</span>}
                  </li>
                );
              })}
            </ul>
          )}
          <p className="text-white/55 text-[13px] mt-1.5">Source: ICES Registry · EMODnet Physics · OBIS-SEAMAP</p>
        </div>
      )}

      {chessSites.length > 0 && (
        <Section title={t("concession.chemosynthetProximitySectionTitle")}>
          <Row
            label={t("concession.riskContributionLabel")}
            // habitat_type is gone (it was our own regex over locality, not a
            // source field) — every site now contributes the old fallback
            // weight, same cap as before.
            value={`+${Math.min(chessSites.length * 0.05, 0.30).toFixed(2)}`}
          />
          <button
            onClick={() => setChessExpanded((e: boolean) => !e)}
            className="text-white/65 hover:text-white/85 text-[14px] mt-1 transition-colors"
          >
            {chessSites.length} site{chessSites.length !== 1 ? "s" : ""} within 10 km {chessExpanded ? "▲" : "▼"}
          </button>
          {chessExpanded && (
            <ul className="mt-1 space-y-1">
              {chessSites.map((s: any, i: number) => {
                const props = s.properties ?? {};
                return (
                  <li key={i} className="text-[13px] text-white/80">
                    <span>{props.locality ?? "Unknown site"}</span>
                  </li>
                );
              })}
            </ul>
          )}
        </Section>
      )}

      <Section title={t("concession.coordinatesSectionTitle")}>
        <Row label={t("concession.lonLabel")} value={fmt(data.centroid_lon, 5, "°")} />
        <Row label={t("concession.latLabel")} value={fmt(data.centroid_lat, 5, "°")} />
      </Section>

      {data.isa_id && (
        <button
          onClick={() => {
            const { startReportJob, reportJobs } = useMapStore.getState();
            if (reportJobs.some(j => j.platformId === data.isa_id && j.status === "generating")) return;
            startReportJob(data.isa_id, "claim");
            const ctrl = new AbortController();
            setTimeout(() => ctrl.abort(), 120_000);
            fetch(`${API}/api/v1/reports/claim-impact`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ isa_id: data.isa_id }),
              signal: ctrl.signal,
            }).then(r => {
              if (!r.ok) useMapStore.getState().updateReportJob(data.isa_id, "failed", `Server ${r.status}`);
            }).catch(e => {
              const msg = e?.name === "AbortError" ? "Request timed out (120s) — backend may be under load" : "Network error — check connection";
              useMapStore.getState().updateReportJob(data.isa_id, "failed", msg);
            });
          }}
          className="w-full mt-2 text-center py-1.5 px-3 text-[14px] rounded-lg bg-white/[0.06] border border-white/15 text-white/85 hover:bg-white/10 hover:text-white/95 transition-colors"
        >
          {t("concession.generateReportButton")}
        </button>
      )}
      <BathymetryConfidenceBlock featureType="isa_contract" fid={String(id)} />
      <SourceAttribution link={sourceLinkFor("isa-contract", { id })} />
    </>
  );
}

