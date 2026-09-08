// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect, useState } from "react";

import { useMapStore } from "../../../store/mapStore";
import { GEOTRACES_ELEMENTS } from "../../../utils/geotracesElements";
import type { GeotracesElementKey } from "../../../utils/geotracesElements";

import { API } from "../shared/tokens";
import { Row, Section, Badge, PanelHeader, WarningBanner } from "../shared/primitives";

// ── GEOTRACES trace-metals panels ────────────────────────────────────────────

interface GeotracesSample {
  depth_m: number | null;
  sample_time: string | null;
  mn_d: number | null;
  fe_d: number | null;
  co_d: number | null;
  ni_d: number | null;
  cu_d: number | null;
  mn_d_qc: number | null;
  fe_d_qc: number | null;
  co_d_qc: number | null;
  ni_d_qc: number | null;
  cu_d_qc: number | null;
  params: Record<string, unknown>;
  sample_id?: number | string;
}

interface GeotracesStationDetail {
  station_id: string;
  cruise: string | null;
  station: string | null;
  sample_time: string | null;
  decade: number | null;
  lat: number;
  lon: number;
  n_samples: number;
  min_depth_m: number | null;
  max_depth_m: number | null;
  bottom_depth_m: number | null;
  samples: GeotracesSample[];
}

interface GeotracesParam {
  param_code: string;
  label: string | null;
  unit: string | null;
  family: string | null;
  n_values: number;
}

interface GeotracesMeasurement {
  param_code: string;
  value: number | null;
  stddev: number | null;
  qc_flag: number | null;
}

interface GeotracesResponse {
  station: GeotracesStationDetail;
  units: Record<string, string>;
  samples: GeotracesSample[];
  measurements?: Record<string, GeotracesMeasurement[]>;
  params?: GeotracesParam[];
  truncated?: boolean;
}

function GeotracesDepthChart({
  samples,
  element,
  unit,
  elementColor: elHex,
}: {
  samples: GeotracesSample[];
  element: GeotracesElementKey;
  unit: string;
  elementColor: string;
}) {
  const key = `${element}_d` as keyof GeotracesSample;
  const valid = samples.filter(s => s[key] != null && s.depth_m != null) as (GeotracesSample & { depth_m: number })[];
  if (valid.length < 1) return null;

  const W = 300, H = 210, PAD_L = 52, PAD_R = 14, PAD_T = 16, PAD_B = 46;
  const drawW = W - PAD_L - PAD_R;
  const drawH = H - PAD_T - PAD_B;

  const allDepths = valid.map(s => s.depth_m);
  const minD = Math.min(...allDepths), maxD = Math.max(...allDepths);
  const rangeD = Math.max(maxD - minD, 1);
  const py = (d: number) => PAD_T + ((d - minD) / rangeD) * drawH;

  const vals = valid.map(s => s[key] as number);
  const minV = Math.min(...vals), maxV = Math.max(...vals);
  const rangeV = Math.max(maxV - minV, 1);
  const px = (v: number) => PAD_L + ((v - minV) / rangeV) * drawW;

  const midD = (minD + maxD) / 2;
  const midV = (minV + maxV) / 2;
  const fmtV = (v: number) => v < 10 ? v.toFixed(2) : Math.round(v).toString();

  const linePts = valid.map(s => `${px(s[key] as number).toFixed(1)},${py(s.depth_m).toFixed(1)}`).join(" ");

  return (
    <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet"
      className="block bg-black/40 rounded-md mb-3 border border-white/10">
      <line x1={PAD_L} y1={PAD_T} x2={PAD_L} y2={PAD_T + drawH} stroke="white" strokeOpacity={0.18} strokeWidth={0.8} />
      <line x1={PAD_L} y1={PAD_T + drawH} x2={PAD_L + drawW} y2={PAD_T + drawH} stroke="white" strokeOpacity={0.18} strokeWidth={0.8} />
      {/* depth axis labels */}
      <text x={PAD_L - 4} y={PAD_T + 4}       textAnchor="end" fontSize={9} fill="white" fillOpacity={0.5}>{minD.toFixed(0)}</text>
      <text x={PAD_L - 4} y={PAD_T + drawH / 2 + 3} textAnchor="end" fontSize={9} fill="white" fillOpacity={0.5}>{midD.toFixed(0)}</text>
      <text x={PAD_L - 4} y={PAD_T + drawH + 2}  textAnchor="end" fontSize={9} fill="white" fillOpacity={0.5}>{maxD.toFixed(0)}</text>
      <text x={PAD_L - 4} y={PAD_T + drawH + 14} textAnchor="end" fontSize={9} fill="white" fillOpacity={0.4}>m</text>
      {/* value axis labels */}
      <text x={PAD_L}            y={PAD_T + drawH + 14} textAnchor="middle" fontSize={9} fill="white" fillOpacity={0.5}>{fmtV(minV)}</text>
      <text x={PAD_L + drawW / 2} y={PAD_T + drawH + 14} textAnchor="middle" fontSize={9} fill="white" fillOpacity={0.5}>{fmtV(midV)}</text>
      <text x={PAD_L + drawW}     y={PAD_T + drawH + 14} textAnchor="middle" fontSize={9} fill="white" fillOpacity={0.5}>{fmtV(maxV)}</text>
      {/* axis label */}
      <text x={PAD_L + drawW / 2} y={PAD_T + drawH + 28} textAnchor="middle" fontSize={9} fill="white" fillOpacity={0.55}>{unit}</text>
      {valid.length >= 2 && (
        <polyline points={linePts} fill="none" stroke={elHex} strokeOpacity={0.9} strokeWidth={1.6} strokeLinejoin="round" />
      )}
      {valid.map((s, i) => (
        <circle key={i} cx={px(s[key] as number)} cy={py(s.depth_m)} r={2} fill={elHex} />
      ))}
    </svg>
  );
}

export function GeotracesStationPanel({ id }: { id: number | string }) {
  const [data, setData]   = useState<GeotracesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const geotracesElement  = useMapStore(s => s.geotracesElement);

  useEffect(() => {
    setLoading(true);
    setData(null);
    const ctrl = new AbortController();
    let aborted = false;
    fetch(`${API}/api/v2/spatial/geotraces/by-id/${id}`, { signal: ctrl.signal })
      .then(r => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then(d => { if (!aborted) { setData(d); setLoading(false); } })
      .catch(() => { if (!aborted) setLoading(false); });
    return () => { aborted = true; ctrl.abort(); };
  }, [id]);

  if (loading) return <p className="text-white/60 text-xs animate-pulse">Loading…</p>;
  if (!data)   return <p className="text-white/60 text-xs">No data found.</p>;

  const { station, units, samples } = data;
  const dateStr = station.sample_time ? String(station.sample_time).slice(0, 10) : null;
  const elKey   = geotracesElement ?? "mn";
  const unitKey = `${elKey}_d`;
  const unit    = units[unitKey] ?? "";
  const elInfo  = GEOTRACES_ELEMENTS.find(e => e.key === elKey);
  const elHexColor = elInfo?.hex ?? "#94a3b8";

  // QC flag: SeaDataNet "good" = 1, below detection = 2; anything else gets a badge
  const qcBadge = (flag: number | null) => {
    if (flag == null || flag === 1 || flag === 2) return null;
    const label = flag === 6 ? "below detection" : `QC ${flag}`;
    return (
      <span className="ml-1 rounded px-1 py-0 text-[9px] font-semibold bg-amber-500/20 text-amber-300 border border-amber-500/30">
        {label}
      </span>
    );
  };

  const fmtMetal = (v: number | null) => v == null ? "—" : v < 10 ? v.toFixed(3) : v.toFixed(1);

  const ELEMENTS: Array<{ key: string; label: string; qcKey: keyof GeotracesSample }> = [
    { key: "mn_d", label: "Mn", qcKey: "mn_d_qc" },
    { key: "fe_d", label: "Fe", qcKey: "fe_d_qc" },
    { key: "co_d", label: "Co", qcKey: "co_d_qc" },
    { key: "ni_d", label: "Ni", qcKey: "ni_d_qc" },
    { key: "cu_d", label: "Cu", qcKey: "cu_d_qc" },
  ];

  return (
    <>
      <WarningBanner color="orange">
        GEOTRACES Intermediate Data Product 2025 (CC-BY 4.0). Research-grade trace-metal values; SeaDataNet quality flags shown, below-detection values labelled.
      </WarningBanner>

      <Badge label="GEOTRACES" color="text-purple-300 border-purple-500/40" />
      <PanelHeader>{station.cruise ?? station.station ?? `Station ${station.station_id}`}</PanelHeader>

      <GeotracesDepthChart samples={samples} element={elKey} unit={unit} elementColor={elHexColor} />

      {samples.length > 0 && (
        <Section title={`Samples (${samples.length})`}>
          <div className="max-h-44 overflow-y-auto rounded border border-white/10">
            <table className="w-full text-[11px] font-mono">
              <thead className="sticky top-0 bg-black/80">
                <tr>
                  <th className="px-2 py-0.5 text-left text-white/50 font-normal">Depth (m)</th>
                  <th className="px-2 py-0.5 text-right text-white/50 font-normal">Mn ({units["mn_d"] ?? ""})</th>
                  <th className="px-2 py-0.5 text-right text-white/50 font-normal">Fe ({units["fe_d"] ?? ""})</th>
                  <th className="px-2 py-0.5 text-right text-white/50 font-normal">Co ({units["co_d"] ?? ""})</th>
                  <th className="px-2 py-0.5 text-right text-white/50 font-normal">Ni ({units["ni_d"] ?? ""})</th>
                  <th className="px-2 py-0.5 text-right text-white/50 font-normal">Cu ({units["cu_d"] ?? ""})</th>
                </tr>
              </thead>
              <tbody>
                {samples.map((s, i) => (
                  <tr key={i} className="odd:bg-white/[0.025]">
                    <td className="px-2 py-0.5 text-white/85">{s.depth_m ?? "—"}</td>
                    {ELEMENTS.map(el => (
                      <td key={el.key} className="px-2 py-0.5 text-right text-white/75">
                        {fmtMetal(s[el.key as keyof GeotracesSample] as number | null)}
                        {qcBadge(s[el.qcKey] as number | null)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}

      {data.measurements != null && (() => {
        const paramByCode = Object.fromEntries((data.params ?? []).map(p => [p.param_code, p]));
        const depthBySampleId = Object.fromEntries(
          samples.map(s => [String(s.sample_id), s.depth_m])
        );
        const rows = Object.entries(data.measurements as Record<string, GeotracesMeasurement[]>).flatMap(
          ([sampleId, meas]) => meas.map(m => ({ ...m, sample_id: sampleId, depth_m: depthBySampleId[sampleId] ?? null }))
        );
        if (rows.length === 0) return null;

        const byFamily = new Map<string, typeof rows>();
        for (const r of rows) {
          const fam = paramByCode[r.param_code]?.family ?? "other";
          if (!byFamily.has(fam)) byFamily.set(fam, []);
          byFamily.get(fam)!.push(r);
        }

        return (
          <details className="mb-4">
            <summary className="text-white/70 text-xs font-semibold cursor-pointer select-none uppercase tracking-wide">
              All measured parameters ({rows.length})
            </summary>
            {data.truncated && (
              <p className="text-amber-300 text-[11px] mt-2 mb-1">
                Showing a truncated subset — not the full parameter list for this station.
              </p>
            )}
            <div className="mt-2 space-y-3">
              {[...byFamily.entries()].map(([family, famRows]) => (
                <div key={family}>
                  <p className="text-white/50 text-[10px] uppercase tracking-wide mb-1">{family}</p>
                  <div className="max-h-40 overflow-y-auto rounded border border-white/10">
                    <table className="w-full text-[11px] font-mono">
                      <thead className="sticky top-0 bg-black/80">
                        <tr>
                          <th className="px-2 py-0.5 text-left text-white/50 font-normal">Depth (m)</th>
                          <th className="px-2 py-0.5 text-left text-white/50 font-normal">Param</th>
                          <th className="px-2 py-0.5 text-right text-white/50 font-normal">Value</th>
                        </tr>
                      </thead>
                      <tbody>
                        {famRows.map((r, i) => {
                          const p = paramByCode[r.param_code];
                          return (
                            <tr key={i} className="odd:bg-white/[0.025]">
                              <td className="px-2 py-0.5 text-white/85">{r.depth_m ?? "—"}</td>
                              <td className="px-2 py-0.5 text-white/75">{p?.label ?? r.param_code}</td>
                              <td className="px-2 py-0.5 text-right text-white/75">
                                {r.value == null ? "—" : fmtMetal(r.value)}
                                {p?.unit ? ` ${p.unit}` : ""}
                                {qcBadge(r.qc_flag)}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              ))}
            </div>
          </details>
        );
      })()}

      <Section title="Station details">
        {station.cruise   != null && <Row label="Cruise"      value={String(station.cruise)} />}
        {station.station  != null && <Row label="Station"     value={String(station.station)} />}
        {dateStr          != null && <Row label="Date"        value={dateStr} />}
        {station.decade   != null && <Row label="Decade"      value={`${station.decade}s`} />}
        <Row label="Lat / Lon"    value={`${station.lat.toFixed(4)}°, ${station.lon.toFixed(4)}°`} />
        <Row label="Samples"      value={String(station.n_samples)} />
        {(station.min_depth_m != null || station.max_depth_m != null) && (
          <Row label="Depth range" value={`${station.min_depth_m ?? "?"} – ${station.max_depth_m ?? "?"} m`} />
        )}
        {station.bottom_depth_m != null && (
          <Row label="Bottom depth" value={`${station.bottom_depth_m} m`} />
        )}
      </Section>

      <p className="text-[11px] text-white/65 mt-2">
        Data:{" "}
        <a href="https://doi.org/10.5285/42c92148-8d03-8be6-e063-7086abc09f0c" target="_blank" rel="noopener noreferrer" className="text-teal-400 hover:underline">
          GEOTRACES IDP2025 ↗
        </a>
        {" · "}
        <a href="https://www.bodc.ac.uk/geotraces/data/idp2025/documents/IDP2025_FairDataUseStatement.pdf" target="_blank" rel="noopener noreferrer" className="text-teal-400 hover:underline">
          Fair Data Use Statement ↗
        </a>
        {" · "}
        <a href="https://eGEOTRACES.org" target="_blank" rel="noopener noreferrer" className="text-teal-400 hover:underline">
          eGEOTRACES ↗
        </a>
      </p>
    </>
  );
}
