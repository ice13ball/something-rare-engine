// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useState, useEffect } from "react";
import { WarningBanner } from "../shared/primitives";
import { API } from "../shared/tokens";
import { Row, Section, Badge } from "../shared/primitives";

export interface OxygenPointData {
  lat: number;
  lon: number;
  depth: number;
  recent_o2: number | null;
  baseline_o2: number | null;
  delta_o2: number | null;
  units: string;
}

export function OxygenPointPanel({ props: p }: { props: Record<string, unknown> }) {
  const lat   = p._lat   as number;
  const lon   = p._lon   as number;
  const depth = p.depth  as number;

  const [data, setData]       = useState<OxygenPointData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    setData(null);
    const ctrl = new AbortController();
    let aborted = false;
    fetch(
      `${API}/api/v1/oxygen/point?lat=${lat}&lon=${lon}&depth=${depth}`,
      { signal: ctrl.signal },
    )
      .then(r => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then(d => { if (!aborted) { setData(d); setLoading(false); } })
      .catch(() => { if (!aborted) setLoading(false); });
    return () => { aborted = true; ctrl.abort(); };
  }, [lat, lon, depth]);

  if (loading) return <p className="text-white/60 text-xs animate-pulse">Loading…</p>;
  if (!data)   return <p className="text-white/60 text-xs">No data found.</p>;

  const noData = data.recent_o2 == null && data.baseline_o2 == null;
  const units  = data.units ?? "µmol/kg";

  const fmtO2 = (v: number | null) =>
    v != null ? `${v.toFixed(1)} ${units}` : "—";

  const deltaLabel = () => {
    if (data.delta_o2 == null) return "—";
    if (data.delta_o2 < 0) return `${data.delta_o2.toFixed(1)} ${units} (loss)`;
    if (data.delta_o2 > 0) return `+${data.delta_o2.toFixed(1)} ${units} (gain)`;
    return `0.0 ${units}`;
  };

  return (
    <>
      <Badge label="Ocean Oxygen" color="text-cyan-300 border-cyan-500/40" />
      <p className="text-sm text-white/80 mb-3">
        Nearest 0.5° cell · {lat.toFixed(2)}°, {lon.toFixed(2)}° · {depth} m
      </p>

      <WarningBanner color="orange">
        The recent field (Argo optodes, 2014–2018) and the ~1980s baseline (ship Winkler/CTD) differ in instrument and method, so some apparent change reflects that difference, not a real oxygen trend.
      </WarningBanner>

      {noData ? (
        <p className="text-white/65 text-xs mt-2">No data here (land or unsampled).</p>
      ) : (
        <Section title="Dissolved oxygen">
          <Row label="Recent O₂ (2014–2018)"  value={fmtO2(data.recent_o2)} />
          <Row label="~1980s baseline"          value={fmtO2(data.baseline_o2)} />
          <Row label="Δ change"                 value={deltaLabel()} />
        </Section>
      )}

      <p className="text-[11px] text-white/65 mt-2">
        Source:{" "}
        <a
          href="https://doi.org/10.17882/52367"
          target="_blank"
          rel="noopener noreferrer"
          className="text-cyan-400 hover:underline"
        >
          ISASO2 — SEANOE 10.17882/52367 <span aria-hidden="true">↗</span>
        </a>
      </p>
    </>
  );
}

