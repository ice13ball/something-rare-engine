// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect, useState, useRef } from "react";
import { useParams, Link } from "react-router-dom";
import { Helmet } from "react-helmet-async";

import { ReportHeader } from "./report/ReportHeader";
import { ExecutiveSummary } from "./report/ExecutiveSummary";
import { MethodologySection } from "./report/MethodologySection";
import { TrailSection } from "./report/TrailSection";
import { ClaimDossier } from "./report/ClaimDossier";
import { FindingsSection } from "./report/FindingsSection";
import { EvidenceSummary } from "./report/EvidenceSummary";
import { AppendixSection } from "./report/AppendixSection";

// ── v2 Type Definitions ─────────────────────────────────────────────────────

export interface SensorPoint {
  date: string;
  value: number;
  claim_distance_km: number | null;
  threshold: number | null;
  alarmed: boolean;
}

export interface TrailProfile {
  profile_id: string;
  date: string;
  lon: number;
  lat: number;
  depth_m: number | null;
  surface_temp: number | null;
  surface_salinity: number | null;
  deep_temp: number | null;
  deep_salinity: number | null;
  oxygen: number | null;
  ph: number | null;
  nearest_claim_id: string | null;
  nearest_claim_name: string | null;
  distance_to_claim_km: number | null;
  alarms: string[];
  alarm_severities: Record<string, number>;
}

export interface AlarmEntry {
  alarm_id: number;
  profile_id: string;
  date: string;
  lon: number;
  lat: number;
  type: string;
  value: number | null;
  threshold: number | null;
  severity: string;
  nearest_claim_id: string | null;
  nearest_claim_name: string | null;
  distance_km: number | null;
}

export interface VentEntry {
  name: string;
  status: string;
  depth_m: number | null;
}

export interface SeamountEntry {
  summit_depth_m: number | null;
  height_m: number | null;
  area_km2: number | null;
}

export interface SpeciesEntry {
  species: string;
  phylum: string;
  records: number;
  endangered: boolean;
  iucn_category?: string;
}

export interface PlumeAttribution {
  profile_id: string;
  backtrack_origin: [number, number];
  source_claim_id: string | null;
  source_claim_name: string;
  distance_to_source_km: number;
  speed_cms: number;
  hours_backtracked: number;
}

export interface ClaimDossierData {
  claim: {
    isa_id: string;
    contractor_name: string;
    resource_type: string | null;
    area_km2: number | null;
    expiry_date: string | null;
    is_high_risk: boolean | null;
  };
  spatial_relationship: {
    min_distance_km: number;
    profiles_within_50km: number;
  };
  vents: VentEntry[];
  seamounts: SeamountEntry[];
  species: {
    curated: SpeciesEntry[];
    total_species_count: number;
  };
  unesco_eez: {
    nearest_unesco: { name: string; distance_km: number | null } | null;
    nearest_eez: { country: string; distance_km: number | null } | null;
  };
  attributed_alarms: number[];
  plume_evidence: PlumeAttribution[];
  risk_score: {
    total: number;
    alarm_component: number;
    proximity_component: number;
    plume_component: number;
    environmental_component: number;
  };
}

export interface Finding {
  number: number;
  type: string;
  severity: "Critical" | "High" | "Moderate" | "Low";
  observation: string;
  threshold_detail: string;
  spatial_link: string;
  environmental_context: string;
  refs: {
    profile_id: string;
    claim_id: string;
    alarm_id?: string;
  };
}

export interface ReportData {
  report_id: string;
  generated_at: string;
  platform_id: string;
  executive_summary: {
    risk_rating: "Critical" | "High" | "Moderate" | "Low";
    headline: string;
    key_stats: Record<string, number | string>;
    narrative: string;
  };
  methodology: {
    alarm_thresholds: Record<string, unknown>;
    scoring_formula: string;
    plume_backtrack: { hours: number; integration_depth_m: number; source: string };
    data_sources: string[];
    notes: string;
  };
  trail: {
    profiles: TrailProfile[];
    total_distance_km: number;
    date_range: { start: string; end: string };
  };
  sensor_timelines: Record<string, SensorPoint[]>;
  alarm_log: AlarmEntry[];
  claim_dossiers: ClaimDossierData[];
  claim_polygons: GeoJSON.FeatureCollection | null;
  plume_attributions: PlumeAttribution[];
  findings: Finding[];
  evidence_summary: {
    narrative: string;
    finding_counts: Record<string, number>;
    recommended_actions: string[];
  };
  appendices: {
    full_sensor_data: TrailProfile[];
    full_species_list: SpeciesEntry[];
    plume_coordinates: { profile_id: string; origin: [number, number]; speed_cms: number | null }[];
    claim_polygons: GeoJSON.FeatureCollection | null;
  };
}

// ── Main Report Component ───────────────────────────────────────────────────

const API = import.meta.env.VITE_API_BASE_URL ?? "";

export function ImpactReport() {
  const { platformId } = useParams<{ platformId: string }>();
  const [data, setData] = useState<ReportData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const reportRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!platformId) return;
    setLoading(true);
    setError(null);

    // Try GET (cached report). If 404, trigger generation then poll.
    const fetchReport = () =>
      fetch(`${API}/api/v1/reports/impact/${platformId}`)
        .then(r => {
          if (r.status === 404) return null; // not cached yet
          if (!r.ok) throw new Error(`${r.status}`);
          return r.json();
        });

    const triggerAndPoll = async () => {
      // Kick off generation
      await fetch(`${API}/api/v1/reports/impact`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ platform_id: platformId }),
      });
      // Poll status until ready
      const poll = (): Promise<unknown> =>
        new Promise(resolve => setTimeout(resolve, 4000))
          .then(() => fetch(`${API}/api/v1/reports/impact/${platformId}/status`))
          .then(r => r.json())
          .then(d => {
            if (d.status === "ready") return fetchReport();
            if (d.status === "failed") throw new Error(d.error || "Generation failed");
            return poll(); // still generating
          });
      return poll();
    };

    fetchReport()
      .then(data => data ?? triggerAndPoll())
      .then(setData)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [platformId]);

  if (loading) return (
    <div className="min-h-screen bg-[#0a0e14] flex items-center justify-center">
      <div className="text-center">
        <p className="text-white/30 animate-pulse mb-2">Generating evidence report...</p>
        <p className="text-white/15 text-xs">Compiling sensor data, claim dossiers, and plume attributions</p>
      </div>
    </div>
  );

  if (error || !data) return (
    <div className="min-h-screen bg-[#0a0e14] flex flex-col items-center justify-center gap-4">
      <p className="text-red-400/70 text-sm">Report generation failed{error ? `: ${error}` : ""}</p>
      <Link to="/" className="text-white/60 hover:text-white/80 text-sm">← Back to map</Link>
    </div>
  );

  const d = data;

  return (
    <>
      <Helmet>
        <title>Impact Report — Float {d.platform_id} | Abyssal Claims</title>
        <meta name="description" content={`Environmental impact evidence report for Argo float ${d.platform_id}. ${d.findings.length} findings across ${d.claim_dossiers.length} mining concession(s).`} />
      </Helmet>
      <div className="min-h-screen bg-[#0a0e14] text-white/80 font-sans print:bg-white print:text-gray-900">
        <div ref={reportRef} className="max-w-[900px] mx-auto p-6">

          <ReportHeader data={d} reportRef={reportRef} />

          <ExecutiveSummary summary={d.executive_summary} />

          <MethodologySection methodology={d.methodology} />

          <TrailSection
            trail={d.trail}
            sensorTimelines={d.sensor_timelines}
            alarmLog={d.alarm_log}
            claimPolygons={d.claim_polygons}
            plumeAttributions={d.plume_attributions}
          />

          {d.claim_dossiers.map((dossier, i) => (
            <ClaimDossier
              key={dossier.claim.isa_id}
              dossier={dossier}
              index={i}
              alarmLog={d.alarm_log}
            />
          ))}

          <FindingsSection findings={d.findings} />

          <EvidenceSummary
            summary={d.evidence_summary}
            riskRating={d.executive_summary.risk_rating}
          />

          <AppendixSection
            appendices={d.appendices}
            platformId={d.platform_id}
          />

          {/* Footer */}
          <div className="mt-12 pt-4 border-t border-white/5 text-center text-xs text-white/15">
            Report {d.report_id} | Generated {d.generated_at}
          </div>

        </div>
      </div>
    </>
  );
}
