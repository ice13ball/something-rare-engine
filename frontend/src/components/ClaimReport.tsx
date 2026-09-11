// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect, useState, useRef } from "react";
import { useParams, Link } from "react-router-dom";
import { Helmet } from "react-helmet-async";

import { ClaimHeader } from "./report/ClaimHeader";
import { ExecutiveSummary } from "./report/ExecutiveSummary";
import type { StatCard } from "./report/ExecutiveSummary";
import { MonitoringEvidence } from "./report/MonitoringEvidence";
import { SensorChart } from "./report/SensorChart";
import { AlarmLog } from "./report/AlarmLog";
import { FindingsSection } from "./report/FindingsSection";
import { EvidenceSummary } from "./report/EvidenceSummary";
import { ImpactReportMap } from "./ImpactReportMap";

import type { SensorPoint, AlarmEntry, Finding } from "./ImpactReport";
import type { ReportData } from "./ImpactReport";

// ── Claim Report Type Definitions ─────────────────────────────────────────

export interface ClaimReportData {
  report_id: string;
  report_type: "claim";
  generated_at: string;
  isa_id: string;
  claim: {
    isa_id: string;
    contractor_name: string;
    resource_type: string | null;
    area_km2: number | null;
    act_date: string | null;
    expiry_date: string | null;
    is_high_risk: boolean | null;
    jurisdiction_text: string | null;
    centroid_lon: number | null;
    centroid_lat: number | null;
  };
  executive_summary: {
    risk_rating: "Critical" | "High" | "Moderate" | "Low";
    narrative: string;
    key_stats: Record<string, number>;
  };
  environmental_context: {
    vents: Array<{
      name: string;
      status: string;
      depth_m: number | null;
      lat: number;
      lon: number;
      distance_km: number;
    }>;
    seamounts: Array<{
      summit_depth_m: number | null;
      height_m: number | null;
      area_km2: number | null;
      lat: number;
      lon: number;
      distance_km: number;
    }>;
    chess_sites: Array<{
      locality: string;
      habitat_type: string;
      species_count: number;
      depth_m: number | null;
      distance_km: number;
    }>;
    species: {
      curated: Array<{
        species: string;
        phylum: string;
        vernacular_name?: string | null;
        image_url?: string | null;
        records: number;
        endangered: boolean;
        iucn_category?: string;
      }>;
      total_count: number;
    };
    unesco_eez: {
      nearest_unesco: { name: string; distance_km: number | null } | null;
      nearest_eez: { country: string; distance_km: number | null } | null;
    };
  };
  monitoring_evidence: {
    profiles: Array<{
      profile_id: string;
      platform_id: string;
      date: string;
      lon: number;
      lat: number;
      distance_to_claim_km: number;
      alarms: string[];
      [key: string]: unknown;
    }>;
    unique_floats: string[];
    date_range: { start: string | null; end: string | null };
  };
  sensor_timelines: Record<
    string,
    Array<{
      date: string;
      value: number;
      threshold: number | null;
      alarmed: boolean;
      claim_distance_km: number | null;
    }>
  >;
  alarm_log: Array<{
    alarm_id: number;
    profile_id: string;
    date: string;
    type: string;
    value: number | null;
    threshold: number | null;
    severity: string;
    distance_km: number | null;
    platform_id?: string;
    [key: string]: unknown;
  }>;
  plume_attributions: Array<{
    profile_id: string;
    platform_id?: string;
    date?: string;
    backtrack_origin: [number, number];
    source_claim_id: string;
    source_claim_name: string;
    distance_to_source_km: number | null;
    speed_cms: number;
    measurements?: {
      oxygen_umol_kg: number | null;
      ph: number | null;
      temp_c: number | null;
      salinity: number | null;
      deep_temp_c: number | null;
      depth_m: number | null;
    };
  }>;
  findings: Array<{
    number: number;
    type: string;
    severity: string;
    observation: string;
    threshold_detail: string;
    spatial_link: string;
    environmental_context: string;
    refs: Record<string, string>;
  }>;
  evidence_summary: {
    narrative: string;
    finding_counts: Record<string, number>;
    recommended_actions: string[];
  };
  claim_polygon: GeoJSON.FeatureCollection | null;
  methodology: {
    alarm_thresholds: Record<string, unknown>;
    scoring_formula: string;
    environmental_radius: Record<string, number>;
    data_sources: string[];
  };
  appendices: {
    full_species_list: Array<{
      species: string;
      phylum: string;
      vernacular_name?: string | null;
      image_url?: string | null;
      records: number;
      endangered: boolean;
      iucn_category?: string;
    }>;
    full_vent_list: Array<{
      name: string;
      status: string;
      depth_m: number | null;
    }>;
    full_seamount_list: Array<{
      summit_depth_m: number | null;
      height_m: number | null;
      area_km2: number | null;
    }>;
    claim_polygon: GeoJSON.FeatureCollection | null;
  };
}

// ── IUCN badge config ─────────────────────────────────────────────────────

const IUCN_PILL: Record<string, { label: string; cls: string }> = {
  CR: { label: "Critically Endangered", cls: "bg-red-500/20 text-red-400 border-red-500/30" },
  EN: { label: "Endangered", cls: "bg-red-500/20 text-red-400 border-red-500/30" },
  VU: { label: "Vulnerable", cls: "bg-orange-500/20 text-orange-400 border-orange-500/30" },
  NT: { label: "Near Threatened", cls: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30" },
  LC: { label: "Least Concern", cls: "bg-gray-500/20 text-gray-400 border-gray-500/30" },
};

// ── Sensor chart config ───────────────────────────────────────────────────

const SENSOR_CONFIG: Record<string, { title: string; unit: string; color: string }> = {
  temperature: { title: "Temperature", unit: "\u00B0C", color: "#f97316" },
  salinity: { title: "Salinity", unit: "PSU", color: "#06b6d4" },
  oxygen: { title: "Dissolved Oxygen", unit: "\u00B5mol/kg", color: "#22c55e" },
  ph: { title: "pH", unit: "", color: "#7c9bb5" },
  turbidity: { title: "Turbidity", unit: "NTU", color: "#eab308" },
};

// ── Helpers to adapt claim data to existing component interfaces ──────────

function toAlarmEntries(
  alarms: ClaimReportData["alarm_log"],
  isaId: string,
  contractorName: string,
): AlarmEntry[] {
  return alarms.map(a => ({
    alarm_id: a.alarm_id,
    profile_id: a.profile_id,
    date: a.date,
    lon: 0,
    lat: 0,
    type: a.type,
    value: a.value,
    threshold: a.threshold,
    severity: a.severity,
    nearest_claim_id: isaId,
    nearest_claim_name: contractorName,
    distance_km: a.distance_km,
  }));
}

function toFindings(findings: ClaimReportData["findings"]): Finding[] {
  return findings.map(f => ({
    number: f.number,
    type: f.type,
    severity: f.severity as Finding["severity"],
    observation: f.observation,
    threshold_detail: f.threshold_detail,
    spatial_link: f.spatial_link,
    environmental_context: f.environmental_context,
    refs: {
      profile_id: f.refs?.profile_id ?? "",
      claim_id: f.refs?.claim_id ?? "",
      alarm_id: f.refs?.alarm_id,
    },
  }));
}

function toExecutiveSummary(
  es: ClaimReportData["executive_summary"],
): ReportData["executive_summary"] {
  return {
    risk_rating: es.risk_rating,
    headline: "",
    key_stats: es.key_stats,
    narrative: es.narrative,
  };
}

function toEvidenceSummary(
  es: ClaimReportData["evidence_summary"],
): ReportData["evidence_summary"] {
  return {
    narrative: es.narrative,
    finding_counts: es.finding_counts,
    recommended_actions: es.recommended_actions,
  };
}

// ── Main Component ────────────────────────────────────────────────────────

const API = import.meta.env.VITE_API_BASE_URL ?? "";

const CLAIM_STAT_CARDS: StatCard[] = [
  { key: "vent_count", label: "Hydrothermal Vents", color: "red" },
  { key: "plume_attribution_count", label: "Plume Origins", color: "orange" },
  { key: "endangered_species_count", label: "Threatened Species (IUCN)", color: "amber" },
  { key: "alarm_count", label: "Sensor Alarms", color: "cyan" },
];

export function ClaimReport() {
  const { isaId } = useParams<{ isaId: string }>();
  const [data, setData] = useState<ClaimReportData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const reportRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isaId) return;
    setLoading(true);
    setError(null);

    const fetchReport = () =>
      fetch(`${API}/api/v1/reports/claim-impact/${isaId}`).then(r => {
        if (r.status === 404) return null;
        if (!r.ok) throw new Error(`${r.status}`);
        return r.json();
      });

    const triggerAndPoll = async () => {
      await fetch(`${API}/api/v1/reports/claim-impact`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ isa_id: isaId }),
      });
      const poll = (): Promise<unknown> =>
        new Promise(resolve => setTimeout(resolve, 4000))
          .then(() =>
            fetch(`${API}/api/v1/reports/claim-impact/${isaId}/status`),
          )
          .then(r => r.json())
          .then(d => {
            if (d.status === "ready") return fetchReport();
            if (d.status === "failed")
              throw new Error(d.error || "Generation failed");
            return poll();
          });
      return poll();
    };

    fetchReport()
      .then(result => result ?? triggerAndPoll())
      .then(setData)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [isaId]);

  if (loading)
    return (
      <div className="min-h-screen bg-[#0a0e14] flex items-center justify-center">
        <div className="text-center">
          <p className="text-white/60 animate-pulse mb-2">
            Generating claim impact report...
          </p>
          <p className="text-white/45 text-xs">
            Compiling environmental context, monitoring evidence, and risk
            assessment
          </p>
        </div>
      </div>
    );

  if (error || !data)
    return (
      <div className="min-h-screen bg-[#0a0e14] flex flex-col items-center justify-center gap-4">
        <p className="text-red-400/70 text-sm">
          Report generation failed{error ? `: ${error}` : ""}
        </p>
        <Link to="/" className="text-white/80 hover:text-white/90 text-sm">
          &larr; Back to map
        </Link>
      </div>
    );

  const d = data;
  const env = d.environmental_context;
  const alarmCount = d.alarm_log.length;

  // Build profile markers for the mini-map
  const mapProfiles = d.monitoring_evidence.profiles.map(p => ({
    lon: p.lon,
    lat: p.lat,
    alarms: p.alarms,
    alarm_severities: {} as Record<string, number>,
    nearest_claim_id: d.isa_id,
  }));

  return (
    <>
      <Helmet>
        <title>
          Claim Report &mdash; {d.claim.contractor_name} ({d.isa_id}) | Abyssal
          Claims
        </title>
      </Helmet>

      <div className="min-h-screen bg-[#0a0e14] text-white/90 font-sans print:bg-white print:text-gray-900">
        <div ref={reportRef} className="max-w-[900px] mx-auto p-6">
          {/* 1. Claim Header */}
          <ClaimHeader
            isaId={d.isa_id}
            contractorName={d.claim.contractor_name}
            resourceType={d.claim.resource_type}
            areaKm2={d.claim.area_km2}
            actDate={d.claim.act_date}
            expiryDate={d.claim.expiry_date}
            jurisdiction={d.claim.jurisdiction_text}
            centroidLon={d.claim.centroid_lon}
            centroidLat={d.claim.centroid_lat}
            riskRating={d.executive_summary.risk_rating}
            generatedAt={d.generated_at}
            reportRef={reportRef}
            onExportJSON={() => {
              const blob = new Blob([JSON.stringify(d, null, 2)], { type: "application/json" });
              const link = document.createElement("a");
              link.download = `claim-report-${d.isa_id}.json`;
              link.href = URL.createObjectURL(blob);
              link.click();
              URL.revokeObjectURL(link.href);
            }}
          />

          {/* 2. Executive Summary */}
          <ExecutiveSummary
            summary={toExecutiveSummary(d.executive_summary)}
            statCards={CLAIM_STAT_CARDS}
          />

          {/* 3. Environmental Context */}
          <section className="mb-8 space-y-5">
            <h2 className="text-[13px] font-semibold text-white/90 print:text-gray-900">
              Environmental Context
            </h2>

            {/* Vents table */}
            {env.vents.length > 0 && (
              <div className="bg-white/[0.03] border border-white/10 rounded-xl p-5 print:bg-gray-50 print:border-gray-200">
                <h3 className="text-[13px] font-medium text-white/80 mb-3 print:text-gray-700">
                  Hydrothermal Vents ({env.vents.length})
                </h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs border-collapse">
                    <thead>
                      <tr className="text-white/60 border-b border-white/5">
                        <th className="py-1 px-2 text-left font-medium">Name</th>
                        <th className="py-1 px-2 text-left font-medium">Status</th>
                        <th className="py-1 px-2 text-right font-medium">Depth</th>
                        <th className="py-1 px-2 text-right font-medium">Distance</th>
                      </tr>
                    </thead>
                    <tbody>
                      {env.vents.map((v, i) => (
                        <tr
                          key={i}
                          className="border-b border-white/[0.03] hover:bg-white/[0.02]"
                        >
                          <td className="py-1 px-2 text-white/80">{v.name}</td>
                          <td className="py-1 px-2 text-white/65">{v.status}</td>
                          <td className="py-1 px-2 text-right text-white/65">
                            {v.depth_m != null ? `${v.depth_m.toLocaleString()} m` : "\u2014"}
                          </td>
                          <td className="py-1 px-2 text-right text-white/60">
                            {v.distance_km.toFixed(0)} km
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Seamounts table */}
            {env.seamounts.length > 0 && (
              <div className="bg-white/[0.03] border border-white/10 rounded-xl p-5 print:bg-gray-50 print:border-gray-200">
                <h3 className="text-[13px] font-medium text-white/80 mb-3 print:text-gray-700">
                  Seamounts ({env.seamounts.length})
                </h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs border-collapse">
                    <thead>
                      <tr className="text-white/60 border-b border-white/5">
                        <th className="py-1 px-2 text-right font-medium">Summit Depth</th>
                        <th className="py-1 px-2 text-right font-medium">Height</th>
                        <th className="py-1 px-2 text-right font-medium">Area</th>
                        <th className="py-1 px-2 text-right font-medium">Distance</th>
                      </tr>
                    </thead>
                    <tbody>
                      {env.seamounts.map((s, i) => (
                        <tr
                          key={i}
                          className="border-b border-white/[0.03] hover:bg-white/[0.02]"
                        >
                          <td className="py-1 px-2 text-right text-white/70">
                            {s.summit_depth_m != null
                              ? `${s.summit_depth_m.toLocaleString()} m`
                              : "\u2014"}
                          </td>
                          <td className="py-1 px-2 text-right text-white/70">
                            {s.height_m != null
                              ? `${s.height_m.toLocaleString()} m`
                              : "\u2014"}
                          </td>
                          <td className="py-1 px-2 text-right text-white/65">
                            {s.area_km2 != null
                              ? `${s.area_km2.toFixed(1)} km\u00B2`
                              : "\u2014"}
                          </td>
                          <td className="py-1 px-2 text-right text-white/60">
                            {s.distance_km.toFixed(0)} km
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Chemosynthetic Sites */}
            {env.chess_sites?.length > 0 && (
              <div className="bg-white/[0.03] border border-white/10 rounded-xl p-5 print:bg-gray-50 print:border-gray-200">
                <h3 className="text-[13px] font-medium text-white/80 mb-3 print:text-gray-700">
                  Chemosynthetic Sites within 50 km ({env.chess_sites.length})
                </h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs border-collapse">
                    <thead>
                      <tr className="text-white/60 border-b border-white/5">
                        <th className="py-1 px-2 text-left font-medium">Locality</th>
                        <th className="py-1 px-2 text-left font-medium">Habitat</th>
                        <th className="py-1 px-2 text-right font-medium">Species</th>
                        <th className="py-1 px-2 text-right font-medium">Depth</th>
                        <th className="py-1 px-2 text-right font-medium">Distance</th>
                      </tr>
                    </thead>
                    <tbody>
                      {env.chess_sites.map((cs, i) => {
                        const habitatLabel: Record<string, string> = { seep: "Cold Seep", whale_fall: "Whale Fall", omz: "Unclassified", unclassified: "Unclassified" };
                        const habitatColor: Record<string, string> = { seep: "text-teal-400", whale_fall: "text-pink-400", omz: "text-indigo-400", unclassified: "text-indigo-400" };
                        return (
                          <tr key={i} className="border-b border-white/[0.03] hover:bg-white/[0.02]">
                            <td className="py-1 px-2 text-white/80">{cs.locality}</td>
                            <td className={`py-1 px-2 text-xs ${habitatColor[cs.habitat_type] ?? "text-white/65"}`}>
                              {habitatLabel[cs.habitat_type] ?? cs.habitat_type}
                            </td>
                            <td className="py-1 px-2 text-right text-white/70">{cs.species_count}</td>
                            <td className="py-1 px-2 text-right text-white/65">
                              {cs.depth_m != null ? `${cs.depth_m.toLocaleString()} m` : "—"}
                            </td>
                            <td className="py-1 px-2 text-right text-white/60">
                              {cs.distance_km === 0 ? "within claim" : `${cs.distance_km.toFixed(1)} km`}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Species gallery — top 20 curated */}
            {env.species.curated.length > 0 && (
              <div className="bg-white/[0.03] border border-white/10 rounded-xl p-5 print:bg-gray-50 print:border-gray-200">
                <h3 className="text-[13px] font-medium text-white/80 mb-3 print:text-gray-700">
                  Species Near This Claim — IUCN Status ({env.species.total_count} total)
                </h3>
                <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
                  {env.species.curated.slice(0, 20).map((sp, i) => (
                    <div
                      key={i}
                      className="relative rounded-lg border border-white/10 overflow-hidden bg-black/30 print:bg-gray-100 print:border-gray-200"
                    >
                      {sp.image_url ? (
                        <img
                          src={sp.image_url}
                          alt={sp.species}
                          className="w-full h-24 object-cover opacity-80"
                          loading="lazy"
                          onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                        />
                      ) : (
                        <div className="w-full h-24 bg-white/[0.03] flex items-center justify-center">
                          <span className="text-white/40 text-[20px]">🐚</span>
                        </div>
                      )}
                      <div className="p-2">
                        <p className="text-xs text-white/85 italic leading-tight truncate print:text-gray-800">
                          {sp.species}
                        </p>
                        {sp.vernacular_name && (
                          <p className="text-xs text-white/60 truncate print:text-gray-500">
                            {sp.vernacular_name}
                          </p>
                        )}
                        <div className="flex items-center gap-1.5 mt-1">
                          <span className="text-[8px] text-white/50 print:text-gray-400">{sp.phylum}</span>
                          <span className="text-[8px] text-white/45 print:text-gray-300">{sp.records} rec.</span>
                          {sp.iucn_category && IUCN_PILL[sp.iucn_category] && (
                            <span className={`px-1 py-0.5 rounded text-[7px] font-medium border ${IUCN_PILL[sp.iucn_category].cls}`}>
                              {IUCN_PILL[sp.iucn_category].label}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* UNESCO / EEZ proximity */}
            {(env.unesco_eez.nearest_unesco || env.unesco_eez.nearest_eez) && (
              <div className="flex flex-wrap gap-3">
                {env.unesco_eez.nearest_unesco && (
                  <div className="inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-blue-500/10 border border-blue-500/20 text-xs">
                    <span className="text-blue-400 font-medium">UNESCO</span>
                    <span className="text-white/70">
                      {env.unesco_eez.nearest_unesco.name}
                    </span>
                    {env.unesco_eez.nearest_unesco.distance_km != null && (
                      <span className="text-white/55">
                        {env.unesco_eez.nearest_unesco.distance_km.toFixed(0)} km
                      </span>
                    )}
                  </div>
                )}
                {env.unesco_eez.nearest_eez && (
                  <div className="inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-xs">
                    <span className="text-emerald-400 font-medium">EEZ</span>
                    <span className="text-white/70">
                      {env.unesco_eez.nearest_eez.country}
                    </span>
                    {env.unesco_eez.nearest_eez.distance_km != null && (
                      <span className="text-white/55">
                        {env.unesco_eez.nearest_eez.distance_km.toFixed(0)} km
                      </span>
                    )}
                  </div>
                )}
              </div>
            )}
          </section>

          {/* Plume Backtrack Evidence */}
          {d.plume_attributions.length > 0 && (
            <section className="mb-8">
              <div className="bg-white/[0.03] border border-white/10 rounded-xl p-5 print:bg-gray-50 print:border-gray-200">
                <h3 className="text-[13px] font-medium text-white/80 mb-3 print:text-gray-700">
                  Plume Backtrack Evidence ({d.plume_attributions.length})
                </h3>
                <p className="text-xs text-white/60 mb-3">
                  Ocean current backtracking linked these plume origins to {d.claim.contractor_name}&rsquo;s concession area.
                  Sensor readings were captured at the time of each detection.
                </p>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs border-collapse">
                    <thead>
                      <tr className="text-white/60 border-b border-white/5">
                        <th className="py-1 px-2 text-left font-medium">Float</th>
                        <th className="py-1 px-2 text-left font-medium">Date</th>
                        <th className="py-1 px-2 text-right font-medium">Depth (m)</th>
                        <th className="py-1 px-2 text-right font-medium">O&#x2082; (&micro;mol/kg)</th>
                        <th className="py-1 px-2 text-right font-medium">pH</th>
                        <th className="py-1 px-2 text-right font-medium">Temp (&deg;C)</th>
                        <th className="py-1 px-2 text-right font-medium">Salinity</th>
                        <th className="py-1 px-2 text-right font-medium">Speed (cm/s)</th>
                        <th className="py-1 px-2 text-right font-medium">Distance</th>
                      </tr>
                    </thead>
                    <tbody>
                      {d.plume_attributions.map((p, i) => {
                        const m = p.measurements;
                        return (
                        <tr
                          key={i}
                          className="border-b border-white/[0.03] hover:bg-white/[0.02]"
                        >
                          <td className="py-1 px-2">
                            <span className="text-cyan-400/70 font-mono">{p.platform_id ?? "—"}</span>
                          </td>
                          <td className="py-1 px-2 text-white/65">
                            {p.date ? new Date(p.date).toLocaleDateString() : "—"}
                          </td>
                          <td className="py-1 px-2 text-right text-white/70">
                            {m?.depth_m != null ? m.depth_m.toFixed(0) : "—"}
                          </td>
                          <td className={`py-1 px-2 text-right ${m?.oxygen_umol_kg != null && m.oxygen_umol_kg < 150 ? "text-red-400" : "text-white/70"}`}>
                            {m?.oxygen_umol_kg != null ? m.oxygen_umol_kg.toFixed(1) : "—"}
                          </td>
                          <td className={`py-1 px-2 text-right ${m?.ph != null && m.ph < 7.8 ? "text-amber-400" : "text-white/70"}`}>
                            {m?.ph != null ? m.ph.toFixed(3) : "—"}
                          </td>
                          <td className="py-1 px-2 text-right text-white/70">
                            {m?.temp_c != null ? m.temp_c.toFixed(1) : "—"}
                          </td>
                          <td className="py-1 px-2 text-right text-white/70">
                            {m?.salinity != null ? m.salinity.toFixed(2) : "—"}
                          </td>
                          <td className="py-1 px-2 text-right text-white/70">
                            {p.speed_cms.toFixed(1)}
                          </td>
                          <td className="py-1 px-2 text-right text-white/60">
                            {p.distance_to_source_km != null
                              ? `${p.distance_to_source_km.toFixed(0)} km`
                              : "—"}
                          </td>
                        </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>
          )}

          {/* 4. Monitoring Evidence */}
          <MonitoringEvidence
            uniqueFloats={d.monitoring_evidence.unique_floats}
            profiles={d.monitoring_evidence.profiles}
            alarmCount={alarmCount}
            dateRange={d.monitoring_evidence.date_range}
          />

          {/* 5. Sensor Charts */}
          {Object.keys(d.sensor_timelines).length > 0 && (
            <section className="mb-8 space-y-3">
              <h2 className="text-[13px] font-semibold text-white/90 print:text-gray-900">
                Sensor Timelines
              </h2>
              {Object.entries(d.sensor_timelines).map(([key, points]) => {
                const cfg = SENSOR_CONFIG[key] ?? {
                  title: key,
                  unit: "",
                  color: "#94a3b8",
                };
                return (
                  <SensorChart
                    key={key}
                    title={cfg.title}
                    unit={cfg.unit}
                    data={points as SensorPoint[]}
                    color={cfg.color}
                  />
                );
              })}
            </section>
          )}

          {/* 6. Alarm Log */}
          {d.alarm_log.length > 0 && (
            <section className="mb-8">
              <h2 className="text-[13px] font-semibold text-white/90 mb-3 print:text-gray-900">
                Alarm Log
              </h2>
              <AlarmLog
                alarms={toAlarmEntries(
                  d.alarm_log,
                  d.isa_id,
                  d.claim.contractor_name,
                )}
              />
            </section>
          )}

          {/* 7. Findings */}
          <FindingsSection findings={toFindings(d.findings)} />

          {/* 8. Evidence Summary */}
          <EvidenceSummary
            summary={toEvidenceSummary(d.evidence_summary)}
            riskRating={d.executive_summary.risk_rating}
          />

          {/* 9. Report Mini-Map */}
          {(mapProfiles.length > 0 || d.claim_polygon) && (
            <section className="mb-8">
              <h2 className="text-[13px] font-semibold text-white/90 mb-3 print:text-gray-900">
                Spatial Overview
              </h2>
              <div className="rounded-xl overflow-hidden border border-white/10 h-[360px]">
                <ImpactReportMap
                  profiles={mapProfiles}
                  claimPolygons={d.claim_polygon}
                />
              </div>
            </section>
          )}

          {/* Back to map */}
          <div className="mt-8 text-center print:hidden">
            <Link
              to={d.claim.centroid_lon != null && d.claim.centroid_lat != null ? `/?fly=${d.claim.centroid_lon},${d.claim.centroid_lat},8` : "/"}
              className="text-white/80 hover:text-white/90 text-sm"
            >
              &larr; Back to map
            </Link>
          </div>

          {/* Footer / Source */}
          <div className="mt-12 pt-4 border-t border-white/5 text-center space-y-1">
            <p className="text-xs text-white/60 print:text-gray-500">
              Source: <span className="font-medium">Abyssal Claims</span> &mdash; something-rare.com
            </p>
            <p className="text-xs text-white/45 print:text-gray-400">
              Report {d.report_id} | Generated {d.generated_at} | Data: ISA, InterRidge, OBIS, Argo, CMEMS
            </p>
          </div>
        </div>
      </div>
    </>
  );
}
