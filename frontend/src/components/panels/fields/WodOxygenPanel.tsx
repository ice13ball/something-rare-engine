// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useState, useEffect } from "react";
import { API } from "../shared/tokens";
import { Row, Section, Badge, PanelHeader, WarningBanner } from "../shared/primitives";
import { SeafloorDepthRow } from "../shared/chips";

export interface WodByIdDetail {
  id: number;
  wod_cast_id: string | null;
  lat: number;
  lon: number;
  max_depth_m: number | null;
  profile_date: string | null;
  profile_time: string | null;
  /** "time" = the source recorded a time of day; "day" = it did not.
   *  null = this row predates the 2026-09-10 re-ingest. */
  time_precision: string | null;
  decade: number | null;
  cruise: string | null;
  dataset: string | null;
  country: string | null;
  probe_type: string | null;
  n_levels: number | null;
  o2_units: string | null;
  qc_flag: number | null;
  qc_note: string | null;
  o2_profile: [number, number][];  // [[depth_m, o2_value], …]
}

export function WodO2Chart({ profile, units }: { profile: [number, number][]; units: string | null }) {
  if (!profile || profile.length < 2) return null;

  const W = 300, H = 210, PAD_L = 50, PAD_R = 14, PAD_T = 16, PAD_B = 46;
  const drawW = W - PAD_L - PAD_R;
  const drawH = H - PAD_T - PAD_B;

  const depths = profile.map(([d]) => d);
  const vals   = profile.map(([, v]) => v);
  const minD = Math.min(...depths), maxD = Math.max(...depths);
  const minV = Math.min(...vals),   maxV = Math.max(...vals);
  const rangeD = Math.max(maxD - minD, 1);
  const rangeV = Math.max(maxV - minV, 1);

  // depth increases downward on Y, O2 on X
  const px = (v: number) => PAD_L + ((v - minV) / rangeV) * drawW;
  const py = (d: number) => PAD_T + ((d - minD) / rangeD) * drawH;

  const points = profile.map(([d, v]) => `${px(v).toFixed(1)},${py(d).toFixed(1)}`).join(" ");

  const midV = (minV + maxV) / 2;
  const midD = (minD + maxD) / 2;
  const fmtV = (v: number) => (v < 10 ? v.toFixed(1) : Math.round(v).toString());

  return (
    <svg
      width="100%" height={H} viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="xMidYMid meet"
      className="block bg-black/40 rounded-md mb-3 border border-white/10"
    >
      {/* axes */}
      <line x1={PAD_L} y1={PAD_T} x2={PAD_L} y2={PAD_T + drawH} stroke="white" strokeOpacity={0.18} strokeWidth={0.8} />
      <line x1={PAD_L} y1={PAD_T + drawH} x2={PAD_L + drawW} y2={PAD_T + drawH} stroke="white" strokeOpacity={0.18} strokeWidth={0.8} />

      {/* Y ticks (depth) + faint gridlines */}
      {[minD, midD, maxD].map((d, i) => {
        const y = py(d);
        return (
          <g key={`d${i}`}>
            <line x1={PAD_L} y1={y} x2={PAD_L + drawW} y2={y} stroke="white" strokeOpacity={0.06} strokeWidth={0.6} />
            <line x1={PAD_L - 4} y1={y} x2={PAD_L} y2={y} stroke="white" strokeOpacity={0.35} strokeWidth={0.8} />
            <text x={PAD_L - 7} y={y + 3} textAnchor="end" fill="rgba(255,255,255,0.55)" fontSize="9">{Math.round(d)}</text>
          </g>
        );
      })}

      {/* X ticks (O2) */}
      {[minV, midV, maxV].map((v, i) => {
        const x = px(v);
        return (
          <g key={`v${i}`}>
            <line x1={x} y1={PAD_T + drawH} x2={x} y2={PAD_T + drawH + 4} stroke="white" strokeOpacity={0.35} strokeWidth={0.8} />
            <text x={x} y={PAD_T + drawH + 14} textAnchor="middle" fill="rgba(255,255,255,0.55)" fontSize="9">{fmtV(v)}</text>
          </g>
        );
      })}

      {/* axis TITLES (so it's obvious which axis is which) */}
      <text transform={`translate(11 ${PAD_T + drawH / 2}) rotate(-90)`} textAnchor="middle" fill="rgba(255,255,255,0.5)" fontSize="10">Depth (m)</text>
      <text x={PAD_L + drawW / 2} y={H - 6} textAnchor="middle" fill="rgba(255,255,255,0.5)" fontSize="10">
        Dissolved O₂ ({units ?? "µmol/kg"})
      </text>

      {/* profile polyline + point markers */}
      <polyline points={points} fill="none" stroke="rgb(34 211 238)" strokeOpacity={0.9} strokeWidth={1.6} strokeLinejoin="round" />
      {profile.map(([d, v], i) => (
        <circle key={`p${i}`} cx={px(v)} cy={py(d)} r={2} fill="rgb(34 211 238)" />
      ))}
    </svg>
  );
}

export function WodOxygenPanel({ id }: { id: number | string }) {
  const [data, setData]       = useState<WodByIdDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    setData(null);
    const ctrl = new AbortController();
    let aborted = false;
    fetch(`${API}/api/v2/spatial/wod-oxygen/by-id/${id}`, { signal: ctrl.signal })
      .then(r => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then(d => { if (!aborted) { setData(d); setLoading(false); } })
      .catch(() => { if (!aborted) setLoading(false); });
    return () => { aborted = true; ctrl.abort(); };
  }, [id]);

  if (loading) return <p className="text-white/60 text-xs animate-pulse">Loading…</p>;
  if (!data)   return <p className="text-white/60 text-xs">No data found.</p>;

  const units = data.o2_units ?? "µmol/kg";
  const profile = data.o2_profile ?? [];
  const dateStr = data.profile_date ? String(data.profile_date).slice(0, 10) : null;
  const year = dateStr ? dateStr.slice(0, 4) : null;

  return (
    <>
      <Badge label="WOD O₂ Profile" color="text-cyan-300 border-cyan-500/40" />
      <PanelHeader>{data.cruise ?? `WOD cast ${data.wod_cast_id ?? data.id}`}</PanelHeader>

      {/* Collection year/date in plain text — no need to read the dot colour */}
      {dateStr && (
        <p className="text-sm text-white/90 mb-2">
          Collected <span className="font-semibold">{dateStr}</span>
          {year && <span className="text-white/70"> · {year.slice(0, 3)}0s</span>}
        </p>
      )}

      <WarningBanner color="orange">
        Raw World Ocean Database profile — heterogeneous instruments and QC across a century; shown as published, not a homogenised product.
      </WarningBanner>

      <WodO2Chart profile={profile} units={units} />

      {/* Solid data — every measured level in text */}
      {profile.length > 0 && (
        <Section title={`Measured levels (${profile.length})`}>
          <div className="max-h-44 overflow-y-auto rounded border border-white/10">
            <table className="w-full text-[11px] font-mono">
              <thead className="sticky top-0 bg-black/70 text-white/70">
                <tr>
                  <th className="text-left px-2 py-1 font-normal">Depth (m)</th>
                  <th className="text-right px-2 py-1 font-normal">O₂ ({units})</th>
                </tr>
              </thead>
              <tbody>
                {profile.map(([d, v], i) => (
                  <tr key={i} className="odd:bg-white/[0.025]">
                    <td className="px-2 py-0.5 text-white/85">{d}</td>
                    <td className="px-2 py-0.5 text-right text-cyan-300">{v.toFixed(1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}

      <Section title="Profile details">
        {dateStr           != null && <Row label="Date"        value={dateStr} />}
        {/* ⛔ Three states, three sentences. WOD encodes the time as a fraction
            of a day and we used to drop it; 94% of casts carry one, 6% carry an
            exact whole day, which is "not recorded" and must not read as
            midnight. A row we have not re-ingested yet says neither. */}
        {data.time_precision === "time" && data.profile_time != null && (
          <Row label="Time (UTC)" value={String(data.profile_time).slice(11, 19)} />
        )}
        {data.time_precision === "day" && (
          <Row label="Time (UTC)" value={<span className="text-white/50">not recorded at source</span>} />
        )}
        {data.decade       != null && <Row label="Decade"      value={`${data.decade}s`} />}
        {data.cruise       != null && <Row label="Cruise"      value={String(data.cruise)} />}
        {data.country      != null && <Row label="Country"     value={String(data.country)} />}
        {data.dataset      != null && <Row label="Dataset"     value={String(data.dataset)} />}
        {data.probe_type   != null && <Row label="Instrument"  value={String(data.probe_type)} />}
        <Row label="O₂ units" value={units} />
        {/* "Deepest sample" is how deep the cast went, NOT how deep the sea is.
            The GEBCO row below makes that difference visible instead of implied. */}
        {data.max_depth_m  != null && (
          <Row label="Deepest sample"
               value={<span title="Deepest level with a valid O₂ reading — not the seafloor">
                 {Math.round(data.max_depth_m).toLocaleString()} m
               </span>} />
        )}
        <SeafloorDepthRow lat={data.lat} lon={data.lon} />
        {data.n_levels     != null && <Row label="Levels"      value={String(data.n_levels)} />}
        <Row label="Lat / Lon" value={`${data.lat.toFixed(4)}°, ${data.lon.toFixed(4)}°`} />
        {data.wod_cast_id  != null && <Row label="WOD cast ID" value={String(data.wod_cast_id)} />}
        {data.qc_flag      != null && <Row label="QC flag"     value={String(data.qc_flag)} />}
        {data.qc_note      != null && <Row label="QC note"     value={String(data.qc_note)} />}
      </Section>

      {/* Source link */}
      <p className="text-[11px] text-white/65 mt-2">
        Source:{" "}
        <a
          href="https://www.ncei.noaa.gov/products/world-ocean-database"
          target="_blank"
          rel="noopener noreferrer"
          className="text-cyan-400 hover:underline"
        >
          NOAA NCEI — World Ocean Database 2023 <span aria-hidden="true">↗</span>
        </a>
        {data.wod_cast_id != null && (
          <span className="block text-white/60">Cross-check cast #{data.wod_cast_id} via WODselect.</span>
        )}
      </p>
    </>
  );
}
