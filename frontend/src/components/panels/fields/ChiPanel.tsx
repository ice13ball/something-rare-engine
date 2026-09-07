// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useState, useEffect } from "react";
import { WarningBanner } from "../shared/primitives";
import { API } from "../shared/tokens";
import { Section, Badge } from "../shared/primitives";

export interface ChiPointData {
  lat: number;
  lon: number;
  impact: number | null;
  citation: string | null;
}

export function ChiPanel({ props: p }: { props: Record<string, unknown> }) {
  const lat = p._lat as number;
  const lon = p._lon as number;

  const [data, setData]       = useState<ChiPointData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    setData(null);
    const ctrl = new AbortController();
    let aborted = false;
    fetch(`${API}/api/v1/chi/point?lat=${lat}&lon=${lon}`, { signal: ctrl.signal })
      .then(r => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then(d => { if (!aborted) { setData(d); setLoading(false); } })
      .catch(() => { if (!aborted) setLoading(false); });
    return () => { aborted = true; ctrl.abort(); };
  }, [lat, lon]);

  if (loading) return <p className="text-white/60 text-xs animate-pulse">Loading…</p>;
  if (!data)   return <p className="text-white/60 text-xs">No data found.</p>;

  return (
    <>
      <WarningBanner color="orange">
        A modelled dimensionless index of total human pressure — the sum of ~10 anthropogenic
        stressors across six categories, present-state only. Seabed mining is only a minor
        component, and ISA claim areas sit in relatively low-impact abyssal zones. This is
        context, not accusation: a concession polygon is not a causal source of this impact.
      </WarningBanner>
      <Badge label="Cumulative Human Impact (modelled)" color="text-amber-300 border-amber-500/40" />
      <p className="text-sm text-white/80 mb-3">
        Nearest cell · {lat.toFixed(2)}°, {lon.toFixed(2)}°
      </p>

      <Section title="Cumulative impact index">
        <div className="overflow-x-auto rounded border border-white/10">
          <table className="w-full text-[11px] font-mono">
            <tbody>
              <tr className="odd:bg-white/[0.025]">
                <td className="px-2 py-0.5 text-white/85">Cumulative human impact</td>
                <td className="px-2 py-0.5 text-right text-amber-300">
                  {data.impact != null ? data.impact.toFixed(3) : "No data here"}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="text-[11px] text-white/60 mt-1">
          Dimensionless index — higher = greater total human pressure. Present-state; no future projection.
        </p>
      </Section>

      {data.citation && (
        <div className="mt-3 rounded border border-orange-500/30 bg-orange-500/10 px-2 py-1.5">
          <p className="text-[10px] font-semibold text-orange-300 mb-0.5">Citation required</p>
          <p className="text-[11px] text-white/75 leading-relaxed break-words">{data.citation}</p>
        </div>
      )}

      <p className="text-[11px] text-white/65 mt-2">
        Source:{" "}
        <a
          href="https://doi.org/10.1126/science.adv2906"
          target="_blank"
          rel="noopener noreferrer"
          className="text-amber-400 hover:underline"
        >
          NCEAS / Halpern et al. 2025, Science <span aria-hidden="true">↗</span>
        </a>
      </p>
    </>
  );
}

// ── Unified Marine Carbon point panel ─────────────────────────────────────────
