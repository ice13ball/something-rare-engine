// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useState, useEffect } from "react";
import { API } from "../shared/tokens";
import { Section, Badge } from "../shared/primitives";

export interface WoaPointVariable {
  key: string;
  label: string;
  units: string;
  baseline: string;
  value: number | null;
}

export interface WoaPointData {
  lat: number;
  lon: number;
  depth: number;
  variables: WoaPointVariable[];
}

export function WoaPointPanel({ props: p }: { props: Record<string, unknown> }) {
  const lat   = p._lat   as number;
  const lon   = p._lon   as number;
  const depth = p.depth  as number;

  const [data, setData]       = useState<WoaPointData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    setData(null);
    const ctrl = new AbortController();
    let aborted = false;
    fetch(
      `${API}/api/v1/woa/point?lat=${lat}&lon=${lon}&depth=${depth}&month=0`,
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
      <Badge label="WOA Climatology" color="text-cyan-300 border-cyan-500/40" />
      <p className="text-sm text-white/80 mb-3">
        Nearest 1° cell · {lat.toFixed(2)}°, {lon.toFixed(2)}° · {depth} m
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
                  <th className="text-right px-2 py-1 font-normal">Baseline</th>
                </tr>
              </thead>
              <tbody>
                {data.variables.map(v => (
                  <tr key={v.key} className="odd:bg-white/[0.025]">
                    <td className="px-2 py-0.5 text-white/85">{v.label}</td>
                    <td className="px-2 py-0.5 text-right text-cyan-300">
                      {v.value != null ? v.value.toFixed(2) : "—"}
                    </td>
                    <td className="px-2 py-0.5 text-right text-white/70">{v.units}</td>
                    <td className="px-2 py-0.5 text-right text-white/60">{v.baseline}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-[11px] text-white/60 mt-1">
            Nearest 1° WOA cell — climatological average, not a point measurement. Baselines vary by variable.
          </p>
        </Section>
      )}

      <p className="text-[11px] text-white/65 mt-2">
        Source:{" "}
        <a
          href="https://www.ncei.noaa.gov/products/world-ocean-atlas"
          target="_blank"
          rel="noopener noreferrer"
          className="text-cyan-400 hover:underline"
        >
          NOAA NCEI — World Ocean Atlas 2023 <span aria-hidden="true">↗</span>
        </a>
      </p>
    </>
  );
}

