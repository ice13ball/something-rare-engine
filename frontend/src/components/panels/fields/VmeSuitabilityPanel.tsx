// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useState, useEffect } from "react";
import { useMapStore } from "../../../store/mapStore";
import { useTranslation } from "react-i18next";
import { WarningBanner } from "../shared/primitives";
import { API } from "../shared/tokens";
import { Section, Badge } from "../shared/primitives";

export interface VmePredictor { key: string; label: string; value: number | null; units: string | null; }
export interface VmePointData {
  lat: number;
  lon: number;
  suitability: number | null;
  uncertainty: number | null;
  extrapolated: boolean;
  top_predictors: VmePredictor[];
  citation: string | null;
}

export function VmeSuitabilityPanel({ props: p }: { props: Record<string, unknown> }) {
  const { t } = useTranslation("panels");
  const openLegendForLayer = useMapStore((s) => s.openLegendForLayer);
  const lat = p._lat as number, lon = p._lon as number;
  const [data, setData] = useState<VmePointData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true); setData(null);
    const ctrl = new AbortController(); let aborted = false;
    fetch(`${API}/api/v1/vme/point?lat=${lat}&lon=${lon}`, { signal: ctrl.signal })
      .then(r => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then(d => { if (!aborted) { setData(d); setLoading(false); } })
      .catch(() => { if (!aborted) setLoading(false); });
    return () => { aborted = true; ctrl.abort(); };
  }, [lat, lon]);

  return (
    <>
      <WarningBanner color="orange">
        MODELED, not observed. Relative habitat suitability for VME indicator corals —
        not probability of presence, not evidence that species are here.
      </WarningBanner>

      <Badge label="VME Suitability (modeled)" color="text-violet-300 border-violet-500/40" />
      <p className="text-sm text-white/80 mb-2">
        {lat.toFixed(2)}°, {lon.toFixed(2)}°
      </p>

      {loading ? (
        <p className="text-white/60 text-xs animate-pulse">Loading…</p>
      ) : !data ? (
        <p className="text-white/60 text-xs">No data found.</p>
      ) : (
        <>
          <Section title="Model output">
            <div className="overflow-x-auto rounded border border-white/10">
              <table className="w-full text-[11px] font-mono">
                <tbody>
                  <tr className="odd:bg-white/[0.025]">
                    <td className="px-2 py-0.5 text-white/85">Suitability</td>
                    <td className="px-2 py-0.5 text-right text-violet-300">
                      {data.suitability != null ? data.suitability.toFixed(3) : "no data here"}
                    </td>
                  </tr>
                  <tr className="odd:bg-white/[0.025]">
                    <td className="px-2 py-0.5 text-white/85">Uncertainty</td>
                    <td className="px-2 py-0.5 text-right text-violet-300">
                      {data.uncertainty != null ? data.uncertainty.toFixed(3) : "no data here"}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            {data.extrapolated && (
              <p className="text-[11px] text-orange-300 mt-1">
                Environment at this location is extrapolated beyond the sampled predictor range —
                treat the estimate with extra caution.
              </p>
            )}
          </Section>

          {data.top_predictors && data.top_predictors.length > 0 && (
            <Section title="Top predictors">
              <div className="overflow-x-auto rounded border border-white/10">
                <table className="w-full text-[11px] font-mono">
                  <tbody>
                    {data.top_predictors.map(pr => (
                      <tr key={pr.key} className="odd:bg-white/[0.025]">
                        <td className="px-2 py-0.5 text-white/85">{pr.label}</td>
                        <td className="px-2 py-0.5 text-right text-white/70">
                          {pr.value != null ? pr.value.toFixed(2) : "—"}{pr.units ? ` ${pr.units}` : ""}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Section>
          )}

          <p className="text-[11px] text-white/60 mt-2 leading-relaxed">
            A MaxEnt model trained on NOAA DSCRTP coral occurrences and seafloor environmental predictors
            (GEBCO, WOA23, ISAS20, GLODAP, substrate).
          </p>
          <button
            onClick={() => openLegendForLayer("vme-suitability")}
            className="mt-2 text-[12px] text-cyan-300/90 hover:text-cyan-200 underline decoration-dotted"
          >
            {t("vme.fullMethodology", { defaultValue: "Full methodology & data sources →" })}
          </button>

          {data.citation && (
            <div className="mt-3 rounded border border-orange-500/30 bg-orange-500/10 px-2 py-1.5">
              <p className="text-[10px] font-semibold text-orange-300 mb-0.5">Citation required</p>
              <p className="text-[11px] text-white/75 leading-relaxed break-words">{data.citation}</p>
            </div>
          )}
        </>
      )}
    </>
  );
}

// ── Coral Acidification Exposure (VME suitability × aragonite horizons) ──────
