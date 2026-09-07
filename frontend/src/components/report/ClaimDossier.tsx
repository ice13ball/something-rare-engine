// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useState } from "react";
import type {
  ClaimDossierData,
  AlarmEntry,
  VentEntry,
  SeamountEntry,
  SpeciesEntry,
  PlumeAttribution,
} from "../ImpactReport";

// ── IUCN Badge Config ─────────────────────────────────────────────────────────

const IUCN_PILL: Record<string, { label: string; cls: string }> = {
  CR: { label: "Critically Endangered", cls: "bg-red-500/20 text-red-400 border-red-500/30" },
  EN: { label: "Endangered", cls: "bg-red-500/20 text-red-400 border-red-500/30" },
  VU: { label: "Vulnerable", cls: "bg-orange-500/20 text-orange-400 border-orange-500/30" },
  NT: { label: "Near Threatened", cls: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30" },
  LC: { label: "Least Concern", cls: "bg-gray-500/20 text-gray-400 border-gray-500/30" },
};

// ── Helpers ──────────────────────────────────────────────────────────────────

function riskLabel(score: number): { label: string; color: string } {
  if (score > 5) return { label: "Critical", color: "red" };
  if (score > 2) return { label: "High", color: "orange" };
  if (score > 0.5) return { label: "Moderate", color: "yellow" };
  return { label: "Low", color: "green" };
}

const th = "text-left text-xs text-white/30 font-medium uppercase tracking-wider pb-1.5";
const td = "text-[13px] text-white/60 py-1";

// ── VentTable ────────────────────────────────────────────────────────────────

function VentTable({ vents }: { vents: VentEntry[] }) {
  if (vents.length === 0) {
    return (
      <p className="text-[13px] text-white/30 italic">
        No hydrothermal vents within 50 km.
      </p>
    );
  }

  const statusColor = (s: string) => {
    const lower = s.toLowerCase();
    if (lower === "active") return "text-red-400";
    if (lower === "inactive") return "text-yellow-400";
    return "text-white/30";
  };

  return (
    <table className="w-full text-left">
      <thead>
        <tr>
          <th className={th}>Name</th>
          <th className={th}>Status</th>
          <th className={`${th} text-right`}>Depth</th>
        </tr>
      </thead>
      <tbody>
        {vents.map((v, i) => (
          <tr key={i} className="border-t border-white/5">
            <td className={td}>{v.name}</td>
            <td className={`${td} ${statusColor(v.status)}`}>{v.status}</td>
            <td className={`${td} text-right`}>{v.depth_m?.toLocaleString() ?? "—"} m</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ── SeamountTable ────────────────────────────────────────────────────────────

function SeamountTable({ seamounts }: { seamounts: SeamountEntry[] }) {
  if (seamounts.length === 0) {
    return (
      <p className="text-[13px] text-white/30 italic">
        No seamounts within 10 km.
      </p>
    );
  }

  return (
    <table className="w-full text-left">
      <thead>
        <tr>
          <th className={`${th} text-right`}>Summit Depth</th>
          <th className={`${th} text-right`}>Height</th>
          <th className={`${th} text-right`}>Base Area</th>
        </tr>
      </thead>
      <tbody>
        {seamounts.map((s, i) => (
          <tr key={i} className="border-t border-white/5">
            <td className={`${td} text-right`}>{s.summit_depth_m?.toLocaleString() ?? "—"} m</td>
            <td className={`${td} text-right`}>{s.height_m?.toLocaleString() ?? "—"} m</td>
            <td className={`${td} text-right`}>{s.area_km2?.toFixed(1) ?? "—"} km²</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ── SpeciesPanel ─────────────────────────────────────────────────────────────

function SpeciesPanel({
  species,
  totalCount,
}: {
  species: SpeciesEntry[];
  totalCount: number;
}) {
  const [expanded, setExpanded] = useState(false);

  if (species.length === 0) {
    return (
      <p className="text-[13px] text-white/30 italic">
        No species records available.
      </p>
    );
  }

  const visible = expanded ? species : species.slice(0, 8);
  const hiddenCount = species.length - 8;
  const appendixCount = totalCount - species.length;

  return (
    <div>
      <table className="w-full text-left">
        <thead>
          <tr>
            <th className={th}>Species</th>
            <th className={th}>Phylum</th>
            <th className={`${th} text-right`}>Records</th>
            <th className={`${th} text-right`}>Status</th>
          </tr>
        </thead>
        <tbody>
          {visible.map((s, i) => (
            <tr
              key={i}
              className={`border-t border-white/5 ${
                s.iucn_category && ["CR","EN","VU"].includes(s.iucn_category) ? "bg-red-500/5" : ""
              }`}
            >
              <td className={`${td} italic`}>{s.species}</td>
              <td className={td}>{s.phylum}</td>
              <td className={`${td} text-right`}>{s.records.toLocaleString()}</td>
              <td className={`${td} text-right`}>
                {s.iucn_category && IUCN_PILL[s.iucn_category] && (
                  <span className={`inline-block px-1.5 py-0.5 rounded text-xs font-medium border ${IUCN_PILL[s.iucn_category].cls}`}>
                    {IUCN_PILL[s.iucn_category].label}
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {!expanded && hiddenCount > 0 && (
        <button
          onClick={() => setExpanded(true)}
          className="mt-2 text-xs text-white/60 hover:text-white/80 transition-colors"
        >
          Show {hiddenCount} more species
        </button>
      )}

      {appendixCount > 0 && (
        <p className="mt-2 text-xs text-white/25">
          {appendixCount} additional common species in appendix CSV
        </p>
      )}
    </div>
  );
}

// ── ProximityBadges ──────────────────────────────────────────────────────────

function ProximityBadges({
  nearestUnesco,
  nearestEez,
}: {
  nearestUnesco: { name: string; distance_km: number | null } | null;
  nearestEez: { country: string; distance_km: number | null } | null;
}) {
  if (!nearestUnesco && !nearestEez) return null;

  return (
    <div className="flex flex-wrap gap-2 mt-3">
      {nearestUnesco && (
        <span className="inline-block px-2 py-0.5 rounded-full text-xs font-medium bg-blue-500/20 text-blue-400 border border-blue-500/30">
          UNESCO: {nearestUnesco.name}{nearestUnesco.distance_km != null ? ` (${nearestUnesco.distance_km.toFixed(0)} km)` : ""}
        </span>
      )}
      {nearestEez && (
        <span className="inline-block px-2 py-0.5 rounded-full text-xs font-medium bg-teal-500/20 text-teal-400 border border-teal-500/30">
          EEZ: {nearestEez.country}{nearestEez.distance_km != null ? ` (${nearestEez.distance_km.toFixed(0)} km)` : ""}
        </span>
      )}
    </div>
  );
}

// ── ClaimEvidence ────────────────────────────────────────────────────────────

function ClaimEvidence({
  riskScore,
  attributedAlarmIds,
  alarmLog,
  plumeEvidence,
}: {
  riskScore: ClaimDossierData["risk_score"];
  attributedAlarmIds: number[];
  alarmLog: AlarmEntry[];
  plumeEvidence: PlumeAttribution[];
}) {
  const attributedAlarms = alarmLog.filter((_, i) => attributedAlarmIds.includes(i));

  return (
    <div className="space-y-4">
      {/* Risk score breakdown */}
      <div>
        <h5 className="text-xs text-white/40 font-medium uppercase tracking-wider mb-2">
          Risk Score Breakdown
        </h5>
        <div className="grid grid-cols-4 gap-3">
          {[
            { label: "Alarm", value: riskScore.alarm_component },
            { label: "Proximity", value: riskScore.proximity_component },
            { label: "Environment", value: riskScore.environmental_component },
            { label: "Plume", value: riskScore.plume_component },
          ].map((item) => (
            <div
              key={item.label}
              className="bg-white/5 rounded-lg p-2.5 text-center"
            >
              <div className="text-xs text-white/30 mb-1">{item.label}</div>
              <div className="text-sm text-white/70 font-medium">
                {item.value.toFixed(2)}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Attributed alarms */}
      {attributedAlarms.length > 0 && (
        <div>
          <h5 className="text-xs text-white/40 font-medium uppercase tracking-wider mb-2">
            Attributed Alarms ({attributedAlarms.length})
          </h5>
          <div className="space-y-1">
            {attributedAlarms.map((a, i) => (
              <div
                key={i}
                className="flex items-center gap-3 text-xs text-white/50 bg-white/5 rounded px-2.5 py-1.5"
              >
                <span className="text-white/30 font-mono">{a.date}</span>
                <span className="text-white/60">{a.type}</span>
                <span className="ml-auto">
                  {a.value?.toFixed(2) ?? "—"} vs {a.threshold?.toFixed(2) ?? "—"}
                </span>
                <span className="text-white/30">
                  {a.distance_km?.toFixed(1) ?? "?"} km
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Plume backtrack evidence */}
      {plumeEvidence.length > 0 && (
        <div>
          <h5 className="text-xs text-white/40 font-medium uppercase tracking-wider mb-2">
            Plume Backtrack Evidence ({plumeEvidence.length})
          </h5>
          <div className="space-y-1">
            {plumeEvidence.map((p, i) => (
              <div
                key={i}
                className="flex items-center gap-3 text-xs text-white/50 bg-white/5 rounded px-2.5 py-1.5"
              >
                <span className="text-white/30 font-mono">{p.profile_id}</span>
                <span className="text-white/60">{p.source_claim_name}</span>
                <span className="ml-auto">
                  {p.distance_to_source_km?.toFixed(1) ?? "?"} km
                </span>
                <span className="text-white/30">
                  {p.hours_backtracked}h @ {p.speed_cms?.toFixed(1) ?? "?"} cm/s
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main ClaimDossier ────────────────────────────────────────────────────────

interface Props {
  dossier: ClaimDossierData;
  index: number;
  alarmLog: AlarmEntry[];
}

export function ClaimDossier({ dossier, index, alarmLog }: Props) {
  const { claim, spatial_relationship, vents, seamounts, species, unesco_eez, risk_score, attributed_alarms, plume_evidence } = dossier;
  const risk = riskLabel(risk_score.total);

  return (
    <section
      id={`claim-${claim.isa_id}`}
      className="bg-surface-scrim backdrop-blur-md border border-white/10 rounded-xl p-5 mb-6 print:bg-white print:border-gray-200"
    >
      {/* Section heading */}
      <h3 className="text-sm font-semibold text-white/90 mb-4 print:text-gray-900">
        4.{index + 1} Claim Dossier — {claim.contractor_name}
      </h3>

      {/* Claim header */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-4">
        {[
          { label: "ISA ID", value: claim.isa_id },
          { label: "Resource", value: claim.resource_type ?? "Unknown" },
          { label: "Area", value: claim.area_km2 != null ? `${claim.area_km2.toLocaleString()} km²` : "—" },
        ].map((item) => (
          <div key={item.label} className="bg-white/5 rounded-lg p-2.5">
            <div className="text-xs text-white/30 mb-0.5">{item.label}</div>
            <div className="text-[13px] text-white/70">{item.value}</div>
          </div>
        ))}
      </div>

      {/* Spatial relationship */}
      <div className="flex flex-wrap items-center gap-4 mb-3 text-[13px] text-white/50">
        <span>
          Min distance: <span className="text-white/70 font-medium">{spatial_relationship.min_distance_km.toFixed(1)} km</span>
        </span>
        <span>
          Profiles within 50 km: <span className="text-white/70 font-medium">{spatial_relationship.profiles_within_50km}</span>
        </span>
      </div>

      {/* Proximity badges */}
      <ProximityBadges
        nearestUnesco={unesco_eez.nearest_unesco}
        nearestEez={unesco_eez.nearest_eez}
      />

      {/* Risk score + severity */}
      <div className="flex items-center gap-3 mt-4 mb-5">
        <span className="text-[13px] text-white/50">
          Risk Score: <span className="text-white/80 font-semibold">{risk_score.total.toFixed(2)}</span>
        </span>
        <span
          className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium bg-${risk.color}-500/20 text-${risk.color}-400 border border-${risk.color}-500/30`}
        >
          {risk.label}
        </span>
      </div>

      {/* Environmental context */}
      <h4 className="text-xs text-white/40 font-medium uppercase tracking-wider mb-3">
        Environmental Context
      </h4>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
        <div>
          <h5 className="text-xs text-white/30 mb-2">Hydrothermal Vents</h5>
          <VentTable vents={vents} />
        </div>
        <div>
          <h5 className="text-xs text-white/30 mb-2">Seamounts</h5>
          <SeamountTable seamounts={seamounts} />
        </div>
      </div>

      <div className="mb-5">
        <h5 className="text-xs text-white/30 mb-2">Species Records</h5>
        <SpeciesPanel species={species.curated} totalCount={species.total_species_count} />
      </div>

      {/* Evidence divider */}
      <div className="border-t border-white/10 pt-4">
        <h4 className="text-xs text-white/40 font-medium uppercase tracking-wider mb-3">
          Claim Evidence
        </h4>
        <ClaimEvidence
          riskScore={risk_score}
          attributedAlarmIds={attributed_alarms}
          alarmLog={alarmLog}
          plumeEvidence={plume_evidence}
        />
      </div>
    </section>
  );
}
