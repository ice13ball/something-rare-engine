// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import React, { useState } from "react";
import { Link } from "react-router-dom";

// Most-threatened first. Mirrors the server sort in concession_report.py.
const IUCN_ORDER: Record<string, number> = { CR: 0, EN: 1, VU: 2, NT: 3, LC: 4, DD: 5, NE: 6 };

export type ConcessionV2Data = {
  schema_version: "neutral-v1-concession";
  generated_at: string;
  concession: {
    isa_id: string;
    contractor: string | null;
    resource_type: string | null;
    area_km2: number | null;
    jurisdiction: string | null;
    issued: string | null;
    expires: string | null;
    centroid_lat: number | null;
    centroid_lon: number | null;
  };
  seamounts: Array<{
    peak_id: string | null;
    name: string | null;
    summit_depth_m: number | null;
    height_m: number | null;
    area_km2: number | null;
    distance_km: number | null;
  }>;
  species: Array<{
    scientific_name: string | null;
    iucn_category: string;
    record_count: number | null;
  }>;
  species_inside_count?: number | null;
  species_search_radius_km?: number;
  vents: Array<{
    vent_id: string | null;
    name: string | null;
    distance_km: number | null;
    depth_m: number | null;
  }>;
  plume_attributions: Array<{
    platform_id: string;
    profile_id: string | null;
    profile_date: string | null;
    origin_lat: number | null;
    origin_lon: number | null;
    speed_cms: number | null;
    source_dataset: string | null;
    oxygen_umol_kg: number | null;
    ph: number | null;
    surface_temp_c: number | null;
    surface_salinity: number | null;
    max_depth_m: number | null;
    intersects_concession: true;
  }>;
  monitoring_floats: number;
};

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4 py-1 border-b border-white/5 last:border-0">
      <dt className="text-white/70 text-sm">{label}</dt>
      <dd className="text-white/95 text-sm font-mono text-right">{value}</dd>
    </div>
  );
}

function Section({ title, count, children }: { title: string; count: number; children: React.ReactNode }) {
  return (
    <section className="mt-6">
      <h3 className="text-white/90 font-semibold mb-2">
        {title} <span className="text-white/65 font-normal">({count})</span>
      </h3>
      {count === 0 ? <p className="text-white/65 text-sm">None recorded.</p> : children}
    </section>
  );
}

function CollapsibleSection({
  title, count, summary, defaultOpen = false, children,
}: {
  title: string; count: number; summary?: React.ReactNode; defaultOpen?: boolean; children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="mt-6">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        disabled={count === 0}
        className="w-full flex items-center gap-2 text-left text-white/90 font-semibold disabled:cursor-default"
      >
        <span className={`text-white/65 transition-transform ${open ? "rotate-90" : ""}`}>▸</span>
        {title} <span className="text-white/65 font-normal">({count})</span>
      </button>
      {summary && <div className="mt-1 ml-5">{summary}</div>}
      {count === 0 ? (
        <p className="text-white/65 text-sm mt-2 ml-5">None recorded.</p>
      ) : (
        open && <div className="mt-2">{children}</div>
      )}
    </section>
  );
}

export function ConcessionDossierV2({ data }: { data: ConcessionV2Data }) {
  const c = data.concession;

  // Most-threatened first, then most-recorded, then alphabetical.
  const sortedSpecies = [...data.species].sort(
    (a, b) =>
      (IUCN_ORDER[a.iucn_category] ?? 99) - (IUCN_ORDER[b.iucn_category] ?? 99) ||
      (b.record_count ?? 0) - (a.record_count ?? 0) ||
      (a.scientific_name ?? "").localeCompare(b.scientific_name ?? ""),
  );
  const iucnBreakdown = sortedSpecies.reduce<Record<string, number>>((acc, s) => {
    acc[s.iucn_category] = (acc[s.iucn_category] ?? 0) + 1;
    return acc;
  }, {});
  const radiusKm = data.species_search_radius_km ?? 10;
  const insideCount = data.species_inside_count;
  const breakdownSummary = (
    <div className="space-y-1">
      <p className="text-xs text-white/70">
        <span className="font-mono text-white/85">{insideCount ?? "n/a"}</span> inside boundary
        {" · "}
        <span className="font-mono text-white/85">{data.species.length}</span> within {radiusKm} km
      </p>
      <div className="flex flex-wrap gap-2 text-xs text-white/70">
        {Object.keys(iucnBreakdown)
          .sort((a, b) => (IUCN_ORDER[a] ?? 99) - (IUCN_ORDER[b] ?? 99))
          .map(cat => (
            <span key={cat} className="font-mono">{cat} {iucnBreakdown[cat]}</span>
          ))}
      </div>
    </div>
  );

  return (
    <div className="rounded-lg border border-white/10 bg-slate-900/40 p-5">
      <header className="mb-4">
        <h2 className="text-white font-mono text-lg">{c.isa_id}</h2>
        {c.contractor && <p className="text-white/85">{c.contractor}</p>}
        {c.resource_type && <p className="text-white/70 text-sm">{c.resource_type}</p>}
      </header>

      <dl>
        {c.area_km2 != null && <Row label="Area" value={`${c.area_km2.toLocaleString()} km²`} />}
        {c.jurisdiction && <Row label="Jurisdiction" value={c.jurisdiction} />}
        {c.issued && <Row label="Issued" value={c.issued} />}
        {c.expires && <Row label="Expires" value={c.expires} />}
        {c.centroid_lat != null && c.centroid_lon != null && (
          <Row label="Centroid" value={`${c.centroid_lat.toFixed(2)}°, ${c.centroid_lon.toFixed(2)}°`} />
        )}
      </dl>

      <Section title="Seamounts within 10 km" count={data.seamounts.length}>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-white/70 text-left">
              <th className="font-normal py-1">Name / ID</th>
              <th className="font-normal py-1 text-right">Summit depth</th>
              <th className="font-normal py-1 text-right">Height</th>
              <th className="font-normal py-1 text-right">Area</th>
              <th className="font-normal py-1 text-right">Distance</th>
            </tr>
          </thead>
          <tbody>
            {data.seamounts.map((s, i) => (
              <tr key={i} className="text-white/90 border-t border-white/5">
                <td className="py-1 font-mono">
                  {s.peak_id != null ? (
                    <Link to={`/?focus=seamount:${encodeURIComponent(String(s.peak_id))}`} className="text-cyan-300 hover:text-cyan-200 underline decoration-dotted" title="Show on the map">
                      {s.name || s.peak_id}
                    </Link>
                  ) : (s.name || "—")}
                </td>
                <td className="py-1 text-right font-mono">{s.summit_depth_m != null ? `${s.summit_depth_m} m` : "—"}</td>
                <td className="py-1 text-right font-mono">{s.height_m != null ? `${s.height_m} m` : "—"}</td>
                <td className="py-1 text-right font-mono">{s.area_km2 != null ? `${s.area_km2} km²` : "—"}</td>
                <td className="py-1 text-right font-mono">{s.distance_km != null ? `${s.distance_km} km` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section title="Hydrothermal vents within 50 km" count={data.vents.length}>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-white/70 text-left">
              <th className="font-normal py-1">Name / ID</th>
              <th className="font-normal py-1 text-right">Depth</th>
              <th className="font-normal py-1 text-right">Distance</th>
            </tr>
          </thead>
          <tbody>
            {data.vents.map((v, i) => (
              <tr key={i} className="text-white/90 border-t border-white/5">
                <td className="py-1 font-mono">
                  {v.name ? (
                    <Link to={`/?focus=vent:${encodeURIComponent(v.name)}`} className="text-cyan-300 hover:text-cyan-200 underline decoration-dotted" title="Show on the map">
                      {v.name}
                    </Link>
                  ) : (v.vent_id || "—")}
                </td>
                <td className="py-1 text-right font-mono">{v.depth_m != null ? `${v.depth_m} m` : "—"}</td>
                <td className="py-1 text-right font-mono">{v.distance_km != null ? `${v.distance_km} km` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <CollapsibleSection
        title={`Species recorded within ~${radiusKm} km (IUCN-categorised)`}
        count={data.species.length}
        summary={data.species.length > 0 ? breakdownSummary : undefined}
        defaultOpen={false}
      >
        <div className="max-h-96 overflow-y-auto custom-scrollbar border border-white/5 rounded">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-[#0a0e14]">
              <tr className="text-white/70 text-left">
                <th className="font-normal py-1 px-2">Scientific name</th>
                <th className="font-normal py-1 px-2">IUCN</th>
                <th className="font-normal py-1 px-2 text-right">Records</th>
              </tr>
            </thead>
            <tbody>
              {sortedSpecies.map((s, i) => (
                <tr key={i} className="text-white/90 border-t border-white/5">
                  <td className="py-1 px-2 italic">{s.scientific_name || "—"}</td>
                  <td className="py-1 px-2 font-mono">{s.iucn_category}</td>
                  <td className="py-1 px-2 text-right font-mono">{s.record_count ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CollapsibleSection>

      <Section title="Argo plume backtracks intersecting this concession" count={data.plume_attributions.length}>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-white/70 text-left">
              <th className="font-normal py-1">Float</th>
              <th className="font-normal py-1">Profile date</th>
              <th className="font-normal py-1 text-right">Backtrack origin</th>
              <th className="font-normal py-1 text-right">O₂ (µmol/kg)</th>
              <th className="font-normal py-1 text-right">pH</th>
              <th className="font-normal py-1 text-right">SST (°C)</th>
              <th className="font-normal py-1">Source</th>
            </tr>
          </thead>
          <tbody>
            {data.plume_attributions.map((p, i) => (
              <tr key={i} className="text-white/90 border-t border-white/5">
                <td className="py-1 font-mono">
                  <Link to={`/?focus=${encodeURIComponent(p.platform_id)}`} className="text-cyan-300 hover:text-cyan-200 underline decoration-dotted" title="Show this float on the map">
                    {p.platform_id}
                  </Link>
                </td>
                <td className="py-1 font-mono">{p.profile_date ?? "—"}</td>
                <td className="py-1 text-right font-mono">
                  {p.origin_lat != null && p.origin_lon != null ? `${p.origin_lat}°, ${p.origin_lon}°` : "—"}
                </td>
                <td className="py-1 text-right font-mono">{p.oxygen_umol_kg ?? "—"}</td>
                <td className="py-1 text-right font-mono">{p.ph ?? "—"}</td>
                <td className="py-1 text-right font-mono">{p.surface_temp_c ?? "—"}</td>
                <td className="py-1 font-mono text-white/70">{p.source_dataset ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <p className="mt-6 text-white/65 text-sm">
        Argo floats with profiles within 200 km in the last 90 days:{" "}
        <span className="font-mono text-white/85">{data.monitoring_floats}</span>
      </p>
    </div>
  );
}
