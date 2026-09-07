// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";

const API = import.meta.env.VITE_API_BASE_URL ?? "";

interface VentReportData {
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
  chess_count: number;
  chess_species: Array<{ species: string; phylum: string; depth_m: number | null; institution: string }>;
  nearby_claims: Array<{ isa_id: string; contractor_name: string; resource_type: string; distance_km: number }>;
}

const STATUS_COLOR: Record<string, string> = {
  Active:   "text-orange-400",
  Inactive: "text-blue-300",
  Extinct:  "text-white/60",
};

export function VentReport() {
  const { ventId } = useParams<{ ventId: string }>();
  const navigate = useNavigate();
  const [data, setData] = useState<VentReportData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${API}/api/v1/seo/vent-report/${ventId}`)
      .then(r => r.ok ? r.json() : null)
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [ventId]);

  if (loading) {
    return (
      <div className="min-h-screen bg-[#0a0e14] flex items-center justify-center">
        <p className="text-white/60 animate-pulse">Loading report…</p>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="min-h-screen bg-[#0a0e14] flex items-center justify-center">
        <p className="text-white/60">Vent not found.</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#0a0e14] text-white px-6 py-8 max-w-4xl mx-auto">
      <button
        onClick={() => navigate(`/?fly=${data.longitude},${data.latitude},10`)}
        className="mb-6 text-white/65 hover:text-white/85 text-sm transition-colors"
      >
        ← Back to map
      </button>

      <h1 className="text-2xl font-bold mb-1">{data.name}</h1>
      <p className={`text-sm ${STATUS_COLOR[data.status] ?? "text-white/70"}`}>
        {data.status} Hydrothermal Vent
      </p>
      {data.region && (
        <p className="text-sm text-white/60 mb-8">
          {data.region}{data.ocean ? ` · ${data.ocean} Ocean` : ""}
          {data.jurisdiction ? ` · ${data.jurisdiction}` : ""}
        </p>
      )}
      {!data.region && <div className="mb-8" />}

      <section className="mb-8 p-4 bg-white/5 rounded-xl border border-white/10">
        <h2 className="text-xs uppercase tracking-widest text-white/65 mb-3">Physical</h2>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 text-sm">
          <div>
            <p className="text-white/65 text-xs mb-0.5">Depth</p>
            <p>{data.min_depth_m != null && data.depth_m != null && data.min_depth_m !== data.depth_m
              ? `${data.min_depth_m.toFixed(0)}–${data.depth_m.toFixed(0)} m`
              : data.depth_m != null ? `${data.depth_m.toFixed(0)} m` : "—"}</p>
          </div>
          <div>
            <p className="text-white/65 text-xs mb-0.5">Max Temperature</p>
            <p>{data.max_temp_c != null
              ? `${data.max_temp_c.toFixed(0)} °C${data.temp_category ? ` (${data.temp_category})` : ""}`
              : data.temp_category ?? "—"}</p>
          </div>
          <div>
            <p className="text-white/65 text-xs mb-0.5">Tectonic Setting</p>
            <p>{data.tectonic_setting ?? "—"}</p>
          </div>
          <div>
            <p className="text-white/65 text-xs mb-0.5">Latitude</p>
            <p>{data.latitude.toFixed(5)}°</p>
          </div>
          <div>
            <p className="text-white/65 text-xs mb-0.5">Longitude</p>
            <p>{data.longitude.toFixed(5)}°</p>
          </div>
          {data.discovery_year && (
            <div>
              <p className="text-white/65 text-xs mb-0.5">Discovered</p>
              <p className="text-sm">{data.discovery_year}</p>
            </div>
          )}
        </div>
      </section>

      {data.biology_notes && (
        <section className="mb-8 p-4 bg-white/5 rounded-xl border border-white/10">
          <h2 className="text-xs uppercase tracking-widest text-white/65 mb-3">Biology Notes</h2>
          <p className="text-sm text-white/80 leading-relaxed">{data.biology_notes}</p>
        </section>
      )}

      <section className="mb-8">
        <h2 className="text-xs uppercase tracking-widest text-white/65 mb-3">
          ChEssBase Species ({data.chess_count})
        </h2>
        {data.chess_species.length === 0 ? (
          <p className="text-white/60 text-sm">No ChEssBase species records within 5 km.</p>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-white/10">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-white/65 text-left border-b border-white/10 text-xs uppercase tracking-widest">
                  <th className="px-4 py-2">Species</th>
                  <th className="px-4 py-2">Phylum</th>
                  <th className="px-4 py-2">Depth</th>
                  <th className="px-4 py-2">Institution</th>
                </tr>
              </thead>
              <tbody>
                {data.chess_species.map((s, i) => (
                  <tr key={i} className="border-b border-white/5 hover:bg-white/[0.03]">
                    <td className="px-4 py-2 italic">{s.species || "—"}</td>
                    <td className="px-4 py-2 text-white/80">{s.phylum || "—"}</td>
                    <td className="px-4 py-2 text-white/80">
                      {s.depth_m != null ? `${s.depth_m} m` : "—"}
                    </td>
                    <td className="px-4 py-2 text-white/80">{s.institution || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="mb-8">
        <h2 className="text-xs uppercase tracking-widest text-white/65 mb-3">
          Nearby Mining Claims (within 100 km)
        </h2>
        {data.nearby_claims.length === 0 ? (
          <p className="text-white/60 text-sm">No active mining claims within 100 km.</p>
        ) : (
          <div className="space-y-2">
            {data.nearby_claims.map((c, i) => (
              <div key={i} className="flex items-center justify-between p-3 bg-white/5 rounded-xl border border-white/10 text-sm">
                <div>
                  <p className="font-medium">{c.contractor_name}</p>
                  <p className="text-white/65 text-xs">{c.resource_type} · {c.isa_id}</p>
                </div>
                <p className="text-white/80 text-xs flex-shrink-0 ml-4">{c.distance_km} km</p>
              </div>
            ))}
          </div>
        )}
      </section>

      {data.source_url && (
        <section>
          <h2 className="text-xs uppercase tracking-widest text-white/65 mb-3">Source</h2>
          <a
            href={data.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-white/80 hover:text-white/90 text-sm transition-colors"
          >
            InterRidge Database ↗
          </a>
        </section>
      )}
    </div>
  );
}
