// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useState, useEffect } from "react";
import { API } from "../shared/tokens";
import { Section, Badge } from "../shared/primitives";

export interface CarbonPointVariable {
  key: string;
  label: string;
  units: string;
  value: number | null;
  n_observations?: number | null;
}

export interface CarbonPointData {
  lat: number;
  lon: number;
  depth_m: number;
  variables: CarbonPointVariable[];
  citation: string | null;
}

export function CarbonPointPanel({ props: p }: { props: Record<string, unknown> }) {
  const lat   = p._lat  as number;
  const lon   = p._lon  as number;
  const depth = p.depth as number;

  const [data, setData]       = useState<CarbonPointData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    setData(null);
    const ctrl = new AbortController();
    let aborted = false;
    fetch(
      `${API}/api/v1/carbon/point?lat=${lat}&lon=${lon}&depth=${depth}`,
      { signal: ctrl.signal },
    )
      .then(r => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then(d => { if (!aborted) { setData(d); setLoading(false); } })
      .catch(() => { if (!aborted) setLoading(false); });
    return () => { aborted = true; ctrl.abort(); };
  }, [lat, lon, depth]);

  if (loading) return <p className="text-white/60 text-xs animate-pulse">Loading…</p>;
  if (!data)   return <p className="text-white/60 text-xs">No data found.</p>;

  const allNull = data.variables.every(v => v.value == null);

  return (
    <>
      <Badge label="Ocean Carbon (GLODAP)" color="text-emerald-300 border-emerald-500/40" />
      <p className="text-sm text-white/80 mb-3">
        Nearest GLODAP cell · {lat.toFixed(2)}°, {lon.toFixed(2)}° · {depth} m
      </p>

      {allNull ? (
        <p className="text-white/65 text-xs">No data here (land or unsampled).</p>
      ) : (
        <Section title="Variables">
          <div className="overflow-x-auto rounded border border-white/10">
            <table className="w-full text-[11px] font-mono">
              <thead className="sticky top-0 bg-black/70 text-white/70">
                <tr>
                  <th className="text-left px-2 py-1 font-normal">Variable</th>
                  <th className="text-right px-2 py-1 font-normal">Value</th>
                  <th className="text-right px-2 py-1 font-normal">Units</th>
                  <th className="text-right px-2 py-1 font-normal">Obs</th>
                </tr>
              </thead>
              <tbody>
                {data.variables.map(v => (
                  <tr key={v.key} className="odd:bg-white/[0.025]">
                    <td className="px-2 py-0.5 text-white/85">{v.label}</td>
                    <td className="px-2 py-0.5 text-right text-emerald-300">
                      {v.value != null ? v.value.toFixed(3) : "—"}
                    </td>
                    <td className="px-2 py-0.5 text-right text-white/70">{v.units}</td>
                    <td className="px-2 py-0.5 text-right text-white/60">
                      {v.n_observations != null ? v.n_observations.toFixed(0) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-[11px] text-white/60 mt-1">
            Nearest GLODAP v2.2016b gridded cell — climatological average, not a point measurement.
            "Obs" is how many source measurements back that cell (Input_N), where known.
          </p>
        </Section>
      )}

      {data.citation && (
        <div className="mt-3 rounded border border-orange-500/30 bg-orange-500/10 px-2 py-1.5">
          <p className="text-[10px] font-semibold text-orange-300 mb-0.5">Citation required</p>
          <p className="text-[11px] text-white/75 leading-relaxed break-words">{data.citation}</p>
        </div>
      )}

      <p className="text-[11px] text-white/65 mt-2">
        Source:{" "}
        <a
          href="https://www.glodap.info"
          target="_blank"
          rel="noopener noreferrer"
          className="text-emerald-400 hover:underline"
        >
          GLODAP v2.2016b Mapped Climatology <span aria-hidden="true">↗</span>
        </a>
      </p>
    </>
  );
}

// ── Ocean Acidification (GLODAP Ω) point panel ────────────────────────────────
