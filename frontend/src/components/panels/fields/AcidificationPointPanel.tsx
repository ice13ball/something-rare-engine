// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { WarningBanner } from "../shared/primitives";
import { API } from "../shared/tokens";
import { Section, Badge } from "../shared/primitives";

export interface AcidificationPointData {
  lat: number;
  lon: number;
  depth_m: number;
  aragonite: number | null;
  calcite: number | null;
  horizon_m: number | null;
  horizon_shift_m: number | null;
  always_supersaturated: boolean;
  horizon_no_data: boolean;
  citation: string | null;
  qc?: { n: number; median: number | null; iqr: [number | null, number | null]; max_abs: number | null } | null;
}

export function AcidificationPointPanel({ props: p }: { props: Record<string, unknown> }) {
  const { t } = useTranslation("panels");
  const lat   = p._lat  as number;
  const lon   = p._lon  as number;
  const depth = p.depth as number;

  const [data, setData]       = useState<AcidificationPointData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    setData(null);
    const ctrl = new AbortController();
    let aborted = false;
    fetch(
      `${API}/api/v1/acidification/point?lat=${lat}&lon=${lon}&depth=${depth}`,
      { signal: ctrl.signal },
    )
      .then(r => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then(d => { if (!aborted) { setData(d); setLoading(false); } })
      .catch(() => { if (!aborted) setLoading(false); });
    return () => { aborted = true; ctrl.abort(); };
  }, [lat, lon, depth]);

  if (loading) return <p className="text-white/60 text-xs animate-pulse">Loading…</p>;
  if (!data)   return <p className="text-white/60 text-xs">No data found.</p>;

  const horizonText = data.always_supersaturated
    ? "Always supersaturated (no corrosive water)"
    : data.horizon_no_data
      ? "No data"
      : data.horizon_m != null
        ? `${data.horizon_m.toFixed(0)} m`
        : "No data";

  const medianStr = data.qc?.median != null ? Math.abs(data.qc.median).toFixed(3) : "—";

  return (
    <>
      <WarningBanner color="orange">
        Ω fields are GLODAP's authoritative mapped climatology; the aragonite saturation-horizon depth is platform-derived.{" "}
        {t("acid.shiftCaveat", { median: medianStr })}
      </WarningBanner>
      <Badge label="Ocean Acidification (GLODAP)" color="text-rose-300 border-rose-500/40" />
      <p className="text-sm text-white/80 mb-3">
        Nearest GLODAP cell · {lat.toFixed(2)}°, {lon.toFixed(2)}° · {depth} m
      </p>

      <Section title="Saturation state">
        <div className="overflow-x-auto rounded border border-white/10">
          <table className="w-full text-[11px] font-mono">
            <thead className="sticky top-0 bg-black/70 text-white/70">
              <tr>
                <th className="text-left px-2 py-1 font-normal">Variable</th>
                <th className="text-right px-2 py-1 font-normal">Ω</th>
              </tr>
            </thead>
            <tbody>
              <tr className="odd:bg-white/[0.025]">
                <td className="px-2 py-0.5 text-white/85">Aragonite (ΩA)</td>
                <td className="px-2 py-0.5 text-right text-rose-300">
                  {data.aragonite != null ? data.aragonite.toFixed(2) : "—"}
                </td>
              </tr>
              <tr className="odd:bg-white/[0.025]">
                <td className="px-2 py-0.5 text-white/85">Calcite (ΩC)</td>
                <td className="px-2 py-0.5 text-right text-rose-300">
                  {data.calcite != null ? data.calcite.toFixed(2) : "—"}
                </td>
              </tr>
              <tr className="odd:bg-white/[0.025]">
                <td className="px-2 py-0.5 text-white/85">Aragonite saturation horizon</td>
                <td className="px-2 py-0.5 text-right text-rose-300">{horizonText}</td>
              </tr>
              {data.horizon_shift_m != null && (
                <tr className="odd:bg-white/[0.025]">
                  <td className="px-2 py-0.5 text-white/85">{t("acid.horizonShift")}</td>
                  <td className="px-2 py-0.5 text-right text-rose-300">{`${Math.round(data.horizon_shift_m)} m`}</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <p className="text-[11px] text-white/60 mt-1">
          Ω &lt; 1 → corrosive; aragonite dissolves.
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
          href="https://glodap.info"
          target="_blank"
          rel="noopener noreferrer"
          className="text-rose-400 hover:underline"
        >
          GLODAP v2.2016b Mapped Climatology <span aria-hidden="true">↗</span>
        </a>
      </p>
    </>
  );
}

