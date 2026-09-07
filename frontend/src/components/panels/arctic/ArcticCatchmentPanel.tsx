// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect, useState } from "react";

import { API } from "../shared/tokens";
import { Row, Section, Badge, PanelHeader } from "../shared/primitives";
import { MiniBar } from "./shared";

// ── Arctic Catchments panel (ARCADE v1) ──────────────────────────────────────

interface ArcticCatchmentParams {
  soc_depth:  (number | null)[];
  pf_classes: { cont: number | null; disc: number | null; isol: number | null; spor: number | null };
  iwp_frac:   number | null;
  etot_mean:  number | null;
  ptot_mean:  number | null;
  total_prec: number | null;
  t_2m_min:   number | null;
  t_2m_max:   number | null;
  ndvi_mean:  number | null;
}

interface ArcticCatchmentDetail {
  gid:          number;
  name:         string | null;
  stream_order: number | null;
  continent:    string | null;
  area_km2:     number | null;
  center_lat:   number | null;
  center_lon:   number | null;
  ocs_mean:     number | null;
  oc_tot:       number | null;
  runoff_mean:  number | null;
  pf_frac:      number | null;
  t_2m_mean:    number | null;
  params:       ArcticCatchmentParams | null;
}

/** Convert Kelvin → °C string; return "—" for null. */
function kelvinToC(k: number | null): string {
  if (k == null) return "—";
  return `${(k - 273.15).toFixed(1)} °C`;
}


/** 6-layer SOC depth bar chart: depth labels vs SOC stock (t/ha). */
function SocDepthChart({ values }: { values: (number | null)[] }) {
  const DEPTH_LABELS = ["0–5 cm", "5–15 cm", "15–30 cm", "30–60 cm", "60–100 cm", "100–200 cm"];
  const clean = values
    .map((v, i) => ({ v, i }))
    .filter((x): x is { v: number; i: number } => x.v != null);
  if (clean.length === 0) return null;
  const max = Math.max(...clean.map(x => x.v), 1);
  return (
    <div className="mt-2 space-y-1">
      {clean.map(({ v, i }) => (
        <div key={i} className="flex items-center gap-2">
          <span className="text-[10px] text-white/50 w-24 shrink-0">{DEPTH_LABELS[i] ?? `Layer ${i + 1}`}</span>
          <div className="flex-1">
            <MiniBar pct={v / max} color="#34d399" />
          </div>
          <span className="text-[10px] text-white/75 w-12 text-right">{v.toFixed(0)}</span>
        </div>
      ))}
    </div>
  );
}

export function ArcticCatchmentPanel({ gid }: { gid: number | string }) {
  const [data, setData]       = useState<ArcticCatchmentDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    setData(null);
    const ctrl = new AbortController();
    let aborted = false;
    fetch(`${API}/api/v2/spatial/arctic-catchments/by-id/${gid}`, { signal: ctrl.signal })
      .then(r => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then(d => { if (!aborted) { setData(d); setLoading(false); } })
      .catch(() => { if (!aborted) setLoading(false); });
    return () => { aborted = true; ctrl.abort(); };
  }, [gid]);

  if (loading) return <p className="text-white/60 text-xs animate-pulse">Loading…</p>;
  if (!data)   return <p className="text-white/60 text-xs">No data found.</p>;

  const title = data.name ?? `Catchment #${data.gid}`;
  const p = data.params;

  const pfClasses: Array<{ key: keyof ArcticCatchmentParams["pf_classes"]; label: string; color: string }> = [
    { key: "cont", label: "Continuous",    color: "#60a5fa" },
    { key: "disc", label: "Discontinuous", color: "#34d399" },
    { key: "isol", label: "Isolated",      color: "#fbbf24" },
    { key: "spor", label: "Sporadic",      color: "#f87171" },
  ];

  return (
    <>
      <Badge label="ARCADE v1" color="text-sky-300 border-sky-500/40" />
      <PanelHeader>{title}</PanelHeader>

      {/* ── Header block ── */}
      <Section title="Location">
        {data.continent    != null && <Row label="Continent"    value={data.continent} />}
        {data.area_km2     != null && <Row label="Area"         value={`${data.area_km2.toFixed(2)} km²`} />}
        {data.stream_order != null && <Row label="Stream order" value={String(data.stream_order)} />}
        {data.center_lat   != null && data.center_lon != null && (
          <Row label="Centre" value={`${data.center_lat.toFixed(3)}°, ${data.center_lon.toFixed(3)}°`} />
        )}
      </Section>

      {/* ── Carbon ── */}
      <Section title="Soil Carbon">
        {data.ocs_mean != null && <Row label="OCS mean"    value={`${data.ocs_mean.toFixed(1)} t/ha`} />}
        {data.oc_tot   != null && (
          <Row label="Total OC" value={`${data.oc_tot.toExponential(2)} Gt`} />
        )}
        {p && p.soc_depth.some(v => v != null) && (
          <div className="mt-1">
            <p className="text-white/50 text-[11px] mb-1">SOC by depth (t/ha)</p>
            <SocDepthChart values={p.soc_depth} />
          </div>
        )}
      </Section>

      {/* ── Water ── */}
      <Section title="Water">
        {data.runoff_mean != null && <Row label="Runoff (mean)"  value={data.runoff_mean.toFixed(3)} />}
        {p?.ptot_mean     != null && <Row label="Total precip."  value={`${p.ptot_mean.toFixed(1)} mm`} />}
        {p?.etot_mean     != null && <Row label="Evapotransp."   value={`${p.etot_mean.toFixed(1)} mm`} />}
      </Section>

      {/* ── Climate ── */}
      <Section title="Climate">
        <Row label="Mean air temp" value={kelvinToC(data.t_2m_mean)} />
        {p?.t_2m_min != null && <Row label="Min air temp"  value={kelvinToC(p.t_2m_min)} />}
        {p?.t_2m_max != null && <Row label="Max air temp"  value={kelvinToC(p.t_2m_max)} />}
        {p?.ndvi_mean != null && <Row label="NDVI (mean)"  value={p.ndvi_mean.toFixed(3)} />}
      </Section>

      {/* ── Permafrost ── */}
      <Section title="Permafrost">
        {data.pf_frac != null && (
          <Row label="Permafrost cover" value={`${(data.pf_frac * 100).toFixed(1)} %`} />
        )}
        {p?.pf_classes && (
          <div className="mt-1 space-y-1">
            {pfClasses.map(cls => {
              const raw = p.pf_classes[cls.key];
              const val = raw ?? 0;
              return (
                <div key={cls.key} className="flex items-center gap-2">
                  <span className="text-[10px] text-white/50 w-24 shrink-0">{cls.label}</span>
                  <div className="flex-1"><MiniBar pct={val} color={cls.color} /></div>
                  <span className="text-[10px] text-white/75 w-10 text-right">
                    {raw == null ? "—" : `${(val * 100).toFixed(0)} %`}
                  </span>
                </div>
              );
            })}
          </div>
        )}
        {p?.iwp_frac != null && (
          <Row label="Ice-wedge polygon" value={`${(p.iwp_frac * 100).toFixed(1)} %`} />
        )}
      </Section>

      {/* ── Citation ── */}
      <p className="text-[11px] text-white/65 mt-2">
        Source:{" "}
        <a href="https://doi.org/10.34894/U9HSPV" target="_blank" rel="noopener noreferrer" className="text-teal-400 hover:underline">
          ARCADE v1 (DataVerse doi:10.34894/U9HSPV) ↗
        </a>
        <span className="block text-white/50 mt-0.5">
          Pan-Arctic catchment dataset — soil carbon, permafrost, hydrology, and climate.
        </span>
      </p>
    </>
  );
}
