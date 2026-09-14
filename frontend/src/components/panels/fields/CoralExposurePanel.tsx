// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { WarningBanner } from "../shared/primitives";
import { API } from "../shared/tokens";
import { Section, Badge } from "../shared/primitives";

export interface CoralExposurePointData {
  found: boolean;
  cell_id?: string;
  taxon_set?: string;
  suitability?: number | null;
  uncertainty?: number | null;
  seafloor_m?: number | null;
  horizon_today_m?: number | null;
  horizon_pi_m?: number | null;
  state?: string;
  citation?: string | null;
}

export interface CoralExposureThreshold { cutoff: number; n_cells: number; exposed_pct: number | null; newly_pct: number | null; }
export interface CoralExposureSummary {
  weighted: { exposed: number | null; newly: number | null; total_weight: number };
  thresholds: CoralExposureThreshold[];
  counts?: Record<string, number>;
  citation?: string | null;
}

export function CoralExposurePanel({ props: p }: { props: Record<string, unknown> }) {
  const { t } = useTranslation("panels");
  const lat = p._lat as number, lon = p._lon as number;

  // Two independent fetches (point + regional summary) rather than one combined
  // effect: a failure on either must not blank the other's already-loaded content —
  // the summary in particular is the same for every click and shouldn't disappear
  // just because the per-cell lookup errored (or vice versa).
  const [point, setPoint] = useState<CoralExposurePointData | null>(null);
  const [pointLoading, setPointLoading] = useState(true);
  const [summary, setSummary] = useState<CoralExposureSummary | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(true);

  useEffect(() => {
    setPointLoading(true); setPoint(null);
    const ctrl = new AbortController(); let aborted = false;
    fetch(`${API}/api/v1/coral-exposure/point?lat=${lat}&lon=${lon}`, { signal: ctrl.signal })
      .then(r => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then(d => { if (!aborted) { setPoint(d); setPointLoading(false); } })
      .catch(() => { if (!aborted) setPointLoading(false); });
    return () => { aborted = true; ctrl.abort(); };
  }, [lat, lon]);

  useEffect(() => {
    setSummaryLoading(true); setSummary(null);
    const ctrl = new AbortController(); let aborted = false;
    fetch(`${API}/api/v1/coral-exposure/summary`, { signal: ctrl.signal })
      .then(r => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then(d => { if (!aborted) { setSummary(d); setSummaryLoading(false); } })
      .catch(() => { if (!aborted) setSummaryLoading(false); });
    return () => { aborted = true; ctrl.abort(); };
    // Regional summary is location-independent (whole-layer rollup) — only fetch once per mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // A null horizon means two different things depending on `state`. classify() (backend)
  // sets state = "no_data" whenever ANY of seafloor/today-horizon/pi-horizon is missing —
  // so if state !== "no_data", both horizons were valid and a null one can only mean the
  // water column never crossed Ω=1 (math.inf on the backend). If state === "no_data", the
  // horizons can't be trusted at all, and must not be rendered as a confident "always
  // supersaturated" claim. Reuses the same "no data" wording as `pct`/VME suitability below.
  const horizonText = (v: number | null | undefined, state: string | undefined) =>
    state === "no_data" ? "no data" : v == null ? "Never (always supersaturated)" : `${Math.round(v)} m`;
  const pct = (v: number | null | undefined) => (v == null ? "no data" : `${v.toFixed(1)}%`);

  return (
    <>
      <WarningBanner color="orange">{t("coralExposure.caveat")}</WarningBanner>

      <Badge label="Coral Acidification Exposure (modeled)" color="text-rose-300 border-rose-500/40" />
      <p className="text-sm text-white/80 mb-3">
        {lat.toFixed(2)}°, {lon.toFixed(2)}°
      </p>

      {pointLoading ? (
        <p className="text-white/60 text-xs animate-pulse">Loading…</p>
      ) : !point || !point.found ? (
        <p className="text-white/60 text-xs">No data at this location.</p>
      ) : (
        <Section title="This cell">
          <div className="overflow-x-auto rounded border border-white/10">
            <table className="w-full text-[11px] font-mono">
              <tbody>
                <tr className="odd:bg-white/[0.025]">
                  <td className="px-2 py-0.5 text-white/85">State</td>
                  <td className="px-2 py-0.5 text-right text-rose-300">
                    {point.state ? t(`coralExposure.state.${point.state}` as any) : "—"}
                  </td>
                </tr>
                <tr className="odd:bg-white/[0.025]">
                  <td className="px-2 py-0.5 text-white/85">Seafloor depth</td>
                  <td className="px-2 py-0.5 text-right text-rose-300">
                    {point.seafloor_m != null ? `${Math.round(point.seafloor_m)} m` : "—"}
                  </td>
                </tr>
                <tr className="odd:bg-white/[0.025]">
                  <td className="px-2 py-0.5 text-white/85">Aragonite horizon (today)</td>
                  <td className="px-2 py-0.5 text-right text-rose-300">{horizonText(point.horizon_today_m, point.state)}</td>
                </tr>
                <tr className="odd:bg-white/[0.025]">
                  <td className="px-2 py-0.5 text-white/85">Aragonite horizon (preindustrial)</td>
                  <td className="px-2 py-0.5 text-right text-rose-300">{horizonText(point.horizon_pi_m, point.state)}</td>
                </tr>
                <tr className="odd:bg-white/[0.025]">
                  <td className="px-2 py-0.5 text-white/85">VME suitability</td>
                  <td className="px-2 py-0.5 text-right text-rose-300">
                    {point.suitability != null ? point.suitability.toFixed(3) : "no data here"}
                  </td>
                </tr>
                {/* ⛔ Never show the suitability score without this. It is the SAME
                    MaxEnt model's own uncertainty for the SAME cell, populated on
                    every row the endpoint can return, and it reaches 0.474 on a
                    0–1 scale — a bare "0.837" reads as a measurement when it is a
                    model output with a wide band. VmeSuitabilityPanel has always
                    shown this pair together; this panel sent the field over the
                    wire and dropped it on the floor. */}
                <tr className="odd:bg-white/[0.025]">
                  <td className="px-2 py-0.5 text-white/85">VME uncertainty</td>
                  <td className="px-2 py-0.5 text-right text-rose-300">
                    {point.uncertainty != null ? point.uncertainty.toFixed(3) : "no data here"}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </Section>
      )}

      <Section title="Regional summary (suitability-weighted)">
        {summaryLoading ? (
          <p className="text-white/60 text-xs animate-pulse">Loading…</p>
        ) : !summary ? (
          <p className="text-white/60 text-xs">Summary unavailable.</p>
        ) : (
          <>
            <div className="overflow-x-auto rounded border border-white/10 mb-2">
              <table className="w-full text-[11px] font-mono">
                <tbody>
                  <tr className="odd:bg-white/[0.025]">
                    <td className="px-2 py-0.5 text-white/85">Exposed (any corrosive)</td>
                    <td className="px-2 py-0.5 text-right text-rose-300">
                      {summary.weighted.exposed != null ? `${(summary.weighted.exposed * 100).toFixed(1)}%` : "no data"}
                    </td>
                  </tr>
                  <tr className="odd:bg-white/[0.025]">
                    <td className="px-2 py-0.5 text-white/85">Newly corrosive (since preindustrial)</td>
                    <td className="px-2 py-0.5 text-right text-rose-300">
                      {summary.weighted.newly != null ? `${(summary.weighted.newly * 100).toFixed(1)}%` : "no data"}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p className="text-[11px] text-white/60 mb-1">Threshold sensitivity (suitability cutoff):</p>
            <div className="overflow-x-auto rounded border border-white/10">
              <table className="w-full text-[11px] font-mono">
                <thead className="sticky top-0 bg-black/70 text-white/70">
                  <tr>
                    <th className="text-left px-2 py-1 font-normal">Cutoff</th>
                    <th className="text-right px-2 py-1 font-normal">Cells</th>
                    <th className="text-right px-2 py-1 font-normal">Exposed</th>
                    <th className="text-right px-2 py-1 font-normal">Newly</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.thresholds.map(row => (
                    <tr key={row.cutoff} className="odd:bg-white/[0.025]">
                      <td className="px-2 py-0.5 text-white/85">≥ {row.cutoff.toFixed(1)}</td>
                      <td className="px-2 py-0.5 text-right text-white/70">{row.n_cells}</td>
                      <td className="px-2 py-0.5 text-right text-rose-300">{pct(row.exposed_pct)}</td>
                      <td className="px-2 py-0.5 text-right text-rose-300">{pct(row.newly_pct)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </Section>

      {(point?.citation ?? summary?.citation) && (
        <div className="mt-3 rounded border border-orange-500/30 bg-orange-500/10 px-2 py-1.5">
          <p className="text-[10px] font-semibold text-orange-300 mb-0.5">Citation required</p>
          <p className="text-[11px] text-white/75 leading-relaxed break-words">{point?.citation ?? summary?.citation}</p>
        </div>
      )}

      <p className="text-[11px] text-white/65 mt-2">
        Source:{" "}
        <a
          href="https://www.glodap.info"
          target="_blank"
          rel="noopener noreferrer"
          className="text-rose-400 hover:underline"
        >
          GLODAP v2.2016b + VME MaxEnt SDM <span aria-hidden="true">↗</span>
        </a>
      </p>
    </>
  );
}

// ── Surface Ocean CO₂ (SOCAT) point panel ────────────────────────────────────
