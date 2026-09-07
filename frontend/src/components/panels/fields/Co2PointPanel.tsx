// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useState, useEffect } from "react";
import { API } from "../shared/tokens";
import { Section, Badge } from "../shared/primitives";

export interface Co2PointVariable {
  key: string;
  label: string;
  units: string;
  value: number | null;
}

export interface Co2PointData {
  lat: number;
  lon: number;
  decade: number | string;
  decade_label?: string;
  variables: Co2PointVariable[];
  citation: string | null;
}

export function Co2PointPanel({ props: p }: { props: Record<string, unknown> }) {
  const lat    = p._lat   as number;
  const lon    = p._lon   as number;
  const decade = p.decade as number | string;

  const [data, setData]       = useState<Co2PointData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    setData(null);
    const ctrl = new AbortController();
    let aborted = false;
    fetch(
      `${API}/api/v1/co2/point?lat=${lat}&lon=${lon}&decade=${decade}`,
      { signal: ctrl.signal },
    )
      .then(r => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then(d => { if (!aborted) { setData(d); setLoading(false); } })
      .catch(() => { if (!aborted) setLoading(false); });
    return () => { aborted = true; ctrl.abort(); };
  }, [lat, lon, decade]);

  if (loading) return <p className="text-white/60 text-xs animate-pulse">Loading…</p>;
  if (!data)   return <p className="text-white/60 text-xs">No data found.</p>;

  const allNull = data.variables.every(v => v.value == null);

  return (
    <>
      <Badge label="Surface Ocean CO₂ (SOCAT)" color="text-sky-300 border-sky-500/40" />
      <p className="text-sm text-white/80 mb-3">
        Decade: {data.decade_label ?? "—"} · {lat.toFixed(2)}°, {lon.toFixed(2)}°
      </p>

      {allNull ? (
        <p className="text-white/65 text-xs">No data here (sparse SOCAT coverage).</p>
      ) : (
        <Section title="Variables">
          <div className="overflow-x-auto rounded border border-white/10">
            <table className="w-full text-[11px] font-mono">
              <thead className="sticky top-0 bg-black/70 text-white/70">
                <tr>
                  <th className="text-left px-2 py-1 font-normal">Variable</th>
                  <th className="text-right px-2 py-1 font-normal">Value</th>
                  <th className="text-right px-2 py-1 font-normal">Units</th>
                </tr>
              </thead>
              <tbody>
                {data.variables.map(v => (
                  <tr key={v.key} className="odd:bg-white/[0.025]">
                    <td className="px-2 py-0.5 text-white/85">{v.label}</td>
                    <td className="px-2 py-0.5 text-right text-sky-300">
                      {v.value != null ? v.value.toFixed(3) : "—"}
                    </td>
                    <td className="px-2 py-0.5 text-right text-white/70">{v.units}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-[11px] text-white/60 mt-1">
            Decadal average for this 1° cell — SOCAT coverage is sparse; many cells have no data.
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
          href="https://www.socat.info"
          target="_blank"
          rel="noopener noreferrer"
          className="text-sky-400 hover:underline"
        >
          SOCAT v2026 <span aria-hidden="true">↗</span>
        </a>
      </p>
    </>
  );
}

// ── Oxygen deox point panel ───────────────────────────────────────────────────
