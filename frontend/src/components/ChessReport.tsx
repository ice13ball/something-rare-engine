// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { Helmet } from "react-helmet-async";

const API = import.meta.env.VITE_API_BASE_URL ?? "";

const HABITAT_LABELS: Record<string, string> = {
  seep:       "Cold Seep",
  whale_fall: "Whale Fall",
  omz:        "OMZ / Other",
};
const HABITAT_COLORS: Record<string, string> = {
  seep:       "#00c896",
  whale_fall: "#dc3282",
  omz:        "#6464ff",
};

interface ChessReportData {
  locality: string;
  habitat_type: string;
  lat: number;
  lon: number;
  depth_m: number | null;
  species_count: number;
  phyla: string[];
  species_list: Array<{ species: string; phylum: string; depth_m: number | null; institution: string }>;
  nearby_claims: Array<{ isa_id: string; contractor_name: string; resource_type: string | null; distance_km: number }>;
  nearby_vents: Array<{ name: string; status: string; depth_m: number | null; distance_km: number }>;
  generated_at: string;
}

export function ChessReport() {
  const { locality: rawLocality } = useParams<{ locality: string }>();
  const locality = rawLocality ? decodeURIComponent(rawLocality) : "";
  const [report, setReport] = useState<ChessReportData | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    if (!locality) return;
    fetch(`${API}/api/v1/reports/chess-site/${encodeURIComponent(locality)}`)
      .then(r => { if (!r.ok) { setNotFound(true); return null; } return r.json(); })
      .then(d => { if (d) setReport(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [locality]);

  const habitatColor = report ? (HABITAT_COLORS[report.habitat_type] ?? "#888") : "#888";
  const habitatLabel = report ? (HABITAT_LABELS[report.habitat_type] ?? "Chemosynthetic Site") : "";

  if (loading) return (
    <div className="min-h-screen bg-[#0a0e14] flex items-center justify-center">
      <p className="text-white/60 animate-pulse text-sm">Loading site report…</p>
    </div>
  );

  if (notFound || !report) return (
    <div className="min-h-screen bg-[#0a0e14] flex flex-col items-center justify-center gap-4">
      <p className="text-white/70 text-sm">Report not found for "{locality}"</p>
      <Link to="/" className="text-teal-400 text-sm hover:underline">← Back to map</Link>
    </div>
  );

  return (
    <>
      <Helmet>
        <title>{report.locality} — Chemosynthetic Site Report · Abyssal Claims</title>
        <meta name="description" content={`${habitatLabel} at ${report.locality}. ${report.species_count} species from ${report.phyla.length} phyla. ${report.nearby_claims.length} nearby mining claims.`} />
        {/*
          Canonical is /report/chess:<locality> — the address the report hub and
          sitemap-core.xml carry, and the one with a server-rendered page behind
          it. ReportRouter now sends visitors here from there; without this tag
          the pair would compete and neither would name a winner.
        */}
        <link rel="canonical" href={`https://something-rare.com/report/chess:${encodeURIComponent(report.locality)}`} />
      </Helmet>

      <div className="min-h-screen bg-[#0a0e14] text-white/90 font-sans">
        <div className="max-w-3xl mx-auto px-4 py-10">

          {/* Back */}
          <Link to={`/?fly=${report.lon},${report.lat},10`} className="text-white/60 hover:text-white/80 text-sm transition-colors mb-6 inline-block">
            ← Back to map
          </Link>

          {/* Header */}
          <div className="mb-8">
            <div className="text-[13px] font-mono uppercase tracking-widest mb-1" style={{ color: habitatColor }}>
              {habitatLabel}
            </div>
            <h1 className="text-2xl font-semibold text-white mb-1">{report.locality}</h1>
            <p className="text-white/60 text-sm">
              {report.lat.toFixed(3)}°, {report.lon.toFixed(3)}°
              {report.depth_m != null && ` · ${report.depth_m.toFixed(0)} m depth`}
            </p>
          </div>

          {/* Key stats */}
          <div className="grid grid-cols-3 gap-3 mb-8">
            {[
              { label: "Species", value: report.species_count },
              { label: "Phyla", value: report.phyla.length },
              { label: "Nearby Claims", value: report.nearby_claims.length },
            ].map(s => (
              <div key={s.label} className="bg-white/[0.03] border border-white/10 rounded-xl p-4 text-center">
                <div className="text-2xl font-semibold text-white">{s.value}</div>
                <div className="text-[13px] text-white/65 uppercase tracking-widest mt-1">{s.label}</div>
              </div>
            ))}
          </div>

          {/* Phyla */}
          {report.phyla.length > 0 && (
            <div className="mb-6 bg-white/[0.03] border border-white/10 rounded-xl p-4">
              <h2 className="text-[13px] uppercase tracking-widest text-white/65 mb-3">Phyla Present</h2>
              <div className="flex flex-wrap gap-2">
                {report.phyla.map(p => (
                  <span key={p} className="px-2 py-1 rounded-md text-[14px] border border-white/10 text-white/80"
                    style={{ backgroundColor: `${habitatColor}15` }}>
                    {p}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Species table */}
          {report.species_list.length > 0 && (
            <div className="mb-6 bg-white/[0.03] border border-white/10 rounded-xl overflow-hidden">
              <h2 className="text-[13px] uppercase tracking-widest text-white/65 p-4 pb-2">
                Species ({report.species_list.length})
              </h2>
              <div className="max-h-72 overflow-y-auto">
                <table className="w-full text-[14px]">
                  <thead className="sticky top-0 bg-[#0a0e14] border-b border-white/10">
                    <tr className="text-white/60 text-left">
                      <th className="px-4 py-2 font-normal">Species</th>
                      <th className="px-4 py-2 font-normal">Phylum</th>
                      <th className="px-4 py-2 font-normal text-right">Depth</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.species_list.map((s, i) => (
                      <tr key={i} className="border-t border-white/[0.04] hover:bg-white/[0.03]">
                        <td className="px-4 py-1.5 italic text-white/85">{s.species || "—"}</td>
                        <td className="px-4 py-1.5 text-white/65">{s.phylum || "—"}</td>
                        <td className="px-4 py-1.5 text-white/65 text-right">{s.depth_m != null ? `${s.depth_m} m` : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Nearby mining claims */}
          {report.nearby_claims.length > 0 ? (
            <div className="mb-6 bg-white/[0.03] border border-white/10 rounded-xl overflow-hidden">
              <h2 className="text-[13px] uppercase tracking-widest text-white/65 p-4 pb-2">
                Nearby Mining Claims (50 km)
              </h2>
              <table className="w-full text-[14px]">
                <thead className="border-b border-white/10">
                  <tr className="text-white/60 text-left">
                    <th className="px-4 py-2 font-normal">Contractor</th>
                    <th className="px-4 py-2 font-normal">Type</th>
                    <th className="px-4 py-2 font-normal text-right">Distance</th>
                  </tr>
                </thead>
                <tbody>
                  {report.nearby_claims.map(c => (
                    <tr key={c.isa_id} className="border-t border-white/[0.04] hover:bg-white/[0.03]">
                      <td className="px-4 py-1.5 text-white/85">{c.contractor_name}</td>
                      <td className="px-4 py-1.5 text-white/65">{c.resource_type ?? "—"}</td>
                      <td className="px-4 py-1.5 text-white/65 text-right">{c.distance_km.toFixed(1)} km</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="mb-6 bg-white/[0.03] border border-white/10 rounded-xl p-4">
              <h2 className="text-[13px] uppercase tracking-widest text-white/65 mb-1">Nearby Mining Claims</h2>
              <p className="text-white/60 text-sm">No active mining claims within 50 km.</p>
            </div>
          )}

          {/* Nearby vents */}
          {report.nearby_vents.length > 0 && (
            <div className="mb-6 bg-white/[0.03] border border-white/10 rounded-xl overflow-hidden">
              <h2 className="text-[13px] uppercase tracking-widest text-white/65 p-4 pb-2">
                Nearby Hydrothermal Vents (50 km)
              </h2>
              <table className="w-full text-[14px]">
                <thead className="border-b border-white/10">
                  <tr className="text-white/60 text-left">
                    <th className="px-4 py-2 font-normal">Vent</th>
                    <th className="px-4 py-2 font-normal">Status</th>
                    <th className="px-4 py-2 font-normal text-right">Distance</th>
                  </tr>
                </thead>
                <tbody>
                  {report.nearby_vents.map((v, i) => (
                    <tr key={i} className="border-t border-white/[0.04] hover:bg-white/[0.03]">
                      <td className="px-4 py-1.5 text-white/85">{v.name}</td>
                      <td className="px-4 py-1.5">
                        <span className={`text-[13px] ${v.status === "Active" ? "text-orange-400" : "text-white/60"}`}>
                          {v.status}
                        </span>
                      </td>
                      <td className="px-4 py-1.5 text-white/65 text-right">{v.distance_km.toFixed(1)} km</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Footer */}
          <div className="mt-8 pt-6 border-t border-white/10 text-[13px] text-white/55 space-y-1">
            <p>Data source: <a href="https://www.gbif.org/dataset/dc5abc9f-84d5-4046-a3ef-9ab24ae53756" className="underline hover:text-white/70">ChEssBase via GBIF</a> · CC BY 4.0</p>
            <p>Generated {new Date(report.generated_at).toLocaleString()}</p>
            <p><Link to="/" className="underline hover:text-white/70">Abyssal Claims</Link> · something-rare.com</p>
          </div>

        </div>
      </div>
    </>
  );
}
