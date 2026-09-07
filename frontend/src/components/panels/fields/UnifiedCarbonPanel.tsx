// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useState, useEffect } from "react";
import { useMapStore } from "../../../store/mapStore";
import { useTranslation } from "react-i18next";
import { API } from "../shared/tokens";
import { Section, Badge } from "../shared/primitives";

export interface UnifiedGroup {
  group: string;
  variables: {
    key: string; label: string; units: string; value: number | null;
    value_label?: string | null; depth_invariant?: boolean;
  }[];
}
export interface UnifiedCarbonData { lat: number; lon: number; depth_m: number; decade: number; groups: UnifiedGroup[]; citations: string[]; }

export interface NearestObsRow {
  source: string;
  label: string;
  id: string | number;
  distance_km: number;
  summary: string;
  lat: number;
  lon: number;
  deck_layer_id: string;
}

export function UnifiedCarbonPanel({ props: p }: { props: Record<string, unknown> }) {
  const { t } = useTranslation("panels");
  const flyTo = useMapStore((s) => s.flyTo);
  const lat = p._lat as number, lon = p._lon as number, depth = p.depth as number;
  const [data, setData] = useState<UnifiedCarbonData | null>(null);
  const [loading, setLoading] = useState(true);
  // Independent from the field fetch above — a nearest-obs failure must never blank
  // the modeled field readout (see Task 5 brief).
  const [nearestObs, setNearestObs] = useState<NearestObsRow[] | null>(null);
  const [nearestObsError, setNearestObsError] = useState(false);

  useEffect(() => {
    setLoading(true); setData(null);
    const ctrl = new AbortController(); let aborted = false;
    fetch(`${API}/api/v1/carbon/unified-point?lat=${lat}&lon=${lon}&depth=${depth}`, { signal: ctrl.signal })
      .then(r => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then(d => { if (!aborted) { setData(d); setLoading(false); } })
      .catch(() => { if (!aborted) setLoading(false); });
    return () => { aborted = true; ctrl.abort(); };
  }, [lat, lon, depth]);

  useEffect(() => {
    setNearestObs(null); setNearestObsError(false);
    const ctrl = new AbortController(); let aborted = false;
    fetch(`${API}/api/v1/carbon/nearest-obs?lat=${lat}&lon=${lon}`, { signal: ctrl.signal })
      .then(r => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then(d => { if (!aborted) setNearestObs(Array.isArray(d?.observations) ? d.observations : []); })
      .catch(() => { if (!aborted) setNearestObsError(true); });
    return () => { aborted = true; ctrl.abort(); };
  }, [lat, lon]);

  if (loading) return <p className="text-white/60 text-xs animate-pulse">Loading…</p>;
  if (!data)   return <p className="text-white/60 text-xs">No data found.</p>;

  const allNull = data.groups.every(g => g.variables.every(v => v.value == null));

  return (
    <>
      <Badge label="Marine Carbon (co-located)" color="text-emerald-300 border-emerald-500/40" />
      <p className="text-sm text-white/80 mb-2">
        Nearest cells · {lat.toFixed(2)}°, {lon.toFixed(2)}° · {depth} m
      </p>
      <div className="mb-3 rounded border border-orange-500/30 bg-orange-500/10 px-2 py-1.5">
        <p className="text-[11px] text-white/75 leading-relaxed">
          Co-located samples from four independent climatologies at different native
          resolutions, periods and depths — not a single combined measurement. Surface
          CO₂ is always sampled at the surface (latest decade) regardless of the depth shown.
        </p>
      </div>

      {allNull ? (
        <p className="text-white/65 text-xs">No data here (land or unsampled).</p>
      ) : data.groups.map(g => {
        // depth_invariant vars (horizon/shift/seafloor depth/substrate) don't change with
        // the panel's depth selector — a single shared caption per group, not per-row
        // clutter, names exactly which rows above it are fixed.
        const invariantLabels = g.variables.filter(v => v.depth_invariant).map(v => v.label);
        return (
          <Section key={g.group} title={g.group}>
            <div className="overflow-x-auto rounded border border-white/10">
              <table className="w-full text-[11px] font-mono">
                <tbody>
                  {g.variables.map(v => {
                    const hasLabel = typeof v.value_label === "string" && v.value_label.trim().length > 0;
                    return (
                      <tr key={v.key} className="odd:bg-white/[0.025]">
                        <td className="px-2 py-0.5 text-white/85">{v.label}</td>
                        <td className="px-2 py-0.5 text-right text-emerald-300">
                          {hasLabel ? v.value_label : (v.value != null ? v.value.toFixed(3) : "no data here")}
                        </td>
                        <td className="px-2 py-0.5 text-right text-white/70">{hasLabel ? "" : v.units}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {invariantLabels.length > 0 && (
              <p className="text-[10px] text-white/50 mt-1 italic">
                {t("unifiedCarbon.depthInvariantNote", {
                  defaultValue: "{{fields}} — fixed values; do not change with the depth selector.",
                  fields: invariantLabels.join(", "),
                })}
              </p>
            )}
          </Section>
        );
      })}

      <Section title={t("unifiedCarbon.nearestObs.title", { defaultValue: "Nearest measurements" })}>
        <p className="text-[10px] text-white/50 mb-1.5 italic">
          {t("unifiedCarbon.nearestObs.caption", {
            defaultValue: "Nearest real in-situ measurement per source — not necessarily representative of this exact point.",
          })}
        </p>
        {nearestObsError ? (
          <p className="text-white/50 text-[11px]">
            {t("unifiedCarbon.nearestObs.unavailable", { defaultValue: "Measurements unavailable." })}
          </p>
        ) : nearestObs === null ? (
          <p className="text-white/40 text-[11px] animate-pulse">Loading…</p>
        ) : nearestObs.length === 0 ? null : (
          <div className="overflow-x-auto rounded border border-white/10">
            <table className="w-full text-[11px] font-mono">
              <tbody>
                {nearestObs.map(o => (
                  <tr key={o.source} className="odd:bg-white/[0.025]">
                    <td className="px-2 py-0.5">
                      {flyTo ? (
                        <button
                          onClick={() => flyTo(o.lon, o.lat)}
                          className="text-emerald-300/90 hover:text-emerald-200 underline decoration-dotted text-left"
                        >
                          {o.label}
                        </button>
                      ) : (
                        <span className="text-white/85">{o.label}</span>
                      )}
                    </td>
                    <td className="px-2 py-0.5 text-right text-white/90 font-semibold whitespace-nowrap">
                      {o.distance_km} km
                    </td>
                    <td className="px-2 py-0.5 text-white/70">{o.summary}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      {data.citations && data.citations.filter(Boolean).length > 0 && (
        <div className="mt-3 rounded border border-white/10 bg-white/[0.03] px-2 py-1.5">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-white/55 mb-1">Attribution</p>
          {data.citations.filter(Boolean).map((c, i) => (
            <p key={i} className="text-[11px] text-white/70 leading-relaxed break-words mb-1 last:mb-0">{c}</p>
          ))}
        </div>
      )}
    </>
  );
}

// ── VME Suitability (modeled) point panel ─────────────────────────────────────
