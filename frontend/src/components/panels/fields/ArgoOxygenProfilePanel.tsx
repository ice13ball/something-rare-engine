// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

/**
 * Click panel for one BGC-Argo DOXY profile (`/api/v1/argo-oxygen/profile/{key}`, backend/domains/argo_oxygen_points.py).
 *
 * ⛔ The chart draws DOXY_ADJUSTED with QC 1/2 of an A/D profile only. Raw real-time values (mode R, or any raw
 * value) and adjusted values flagged 3/4/5/8 are COUNTED, never plotted as measurements.
 * ⛔ The comparison is the ISAS20 Recent mean only. No Δ: one profile has no 1971–2000 baseline.
 * ⛔ The y axis is depth in metres (converted from pressure); pressure is shown beside it, never as depth.
 * ⛔ Missing (404: refreshed away) and broken (anything else: retry) never share a state.
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { API } from "../shared/tokens";
import { PanelHeader, Row, Section, WarningBanner } from "../shared/primitives";
import { useMapStore } from "../../../store/mapStore";
import { ARGO_DEPTH_WINDOW_BOUNDS, argoWindowLabel } from "../../../utils/argoOxygenPoints";
import { tickDecimals } from "./GlodapCastPanel";

type Levels = { pres_dbar: number[]; depth_m: number[]; doxy_adj: (number | null)[]; doxy_adj_qc: (number | null)[];
                doxy_raw: (number | null)[]; doxy_raw_qc: (number | null)[] };
export type ArgoProfilePayload = {
  profile_key: string; argo_profile_id: string; dac: string; platform_number: string; cycle_number: number;
  direction: "A" | "D"; lat: number | null; lon: number | null; position_qc: number | null;
  profile_time: string | null; juld_qc: number | null; year: number | null; doxy_mode: string; pres_source: string;
  n_levels_source: number; n_levels: number; n_good: number; drawable: boolean; units: string; levels: Levels;
  at_depth: Record<string, [number, number] | null>; depth_windows?: Record<string, [number, number]>;
  field_recent: Record<string, number | null>;
  field_product: string; product: string; good_qc: number[]; source_url: string; float_url: string;
  source_home: string; citation: string; citations: string[];
};
const ADJUSTED = new Set(["A", "D"]);

/** [depth_m, value] of the values the map may colour: adjusted, QC 1/2, A/D profile. */
export function goodSeries(lv: Levels, mode: string): [number, number][] {
  if (!ADJUSTED.has(mode)) return [];
  const out: [number, number][] = [];
  lv.depth_m.forEach((d, i) => {
    const v = lv.doxy_adj[i], q = lv.doxy_adj_qc[i];
    if (v !== null && v !== undefined && (q === 1 || q === 2)) out.push([d, v]);
  });
  return out;
}

/** What the chart leaves out, by reason (stored levels only; the source counts are n_levels_source / n_good). */
export function otherCounts(lv: Levels, mode: string): { adjustedFlagged: number; rawOnly: number } {
  let adjustedFlagged = 0, rawOnly = 0;
  lv.depth_m.forEach((_, i) => {
    const v = lv.doxy_adj[i], q = lv.doxy_adj_qc[i];
    if (v !== null && v !== undefined) { if (!(ADJUSTED.has(mode) && (q === 1 || q === 2))) adjustedFlagged++; }
    else if (lv.doxy_raw[i] !== null && lv.doxy_raw[i] !== undefined) rawOnly++;
  });
  return { adjustedFlagged, rawOnly };
}

export const modeLabelKey = (mode: string) =>
  mode === "D" ? "argoProfile.mode.delayed" : mode === "A" ? "argoProfile.mode.adjusted" : "argoProfile.mode.realtime";

const presSourceKey = (s: string) =>
  s === "adjusted" ? "argoProfile.presSource.adjusted" : s === "mixed" ? "argoProfile.presSource.mixed" : "argoProfile.presSource.raw";

/** `YYYY-MM-DD HH:MM UTC` (the source stores the profile time to the second; the minute is what a reader needs),
 *  or null when the profile has no usable time. UTC always, never the viewer's zone. */
export function profileMoment(iso: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  const s = d.toISOString();
  return `${s.slice(0, 10)} ${s.slice(11, 16)} UTC`;
}

const fmt1 = (v: number) => v.toFixed(1);

function ArgoProfileChart({ good, field, window: win, units, label, depthLabel, ariaLabel }: {
  good: [number, number][]; field: [number, number][]; window: [number, number] | null;
  units: string; label: string; depthLabel: string; ariaLabel: string;
}) {
  const W = 300, H = 240, L = 50, R = 14, T = 16, B = 46, dw = W - L - R, dh = H - T - B;
  // The depth axis follows the profile: a field curve reaching 2000 m must not squash a 300 m profile. A field
  // depth just below the profile's last level (a float stops at 495.8 m, the field's level is 500 m) still counts.
  const bottom = Math.max(...good.map(([d]) => d), 10);
  const fld = field.filter(([d]) => d <= bottom * 1.05 + 10);
  const maxD = Math.max(bottom, ...fld.map(([d]) => d));
  const all = [...good, ...fld];
  const minV = Math.min(...all.map(([, v]) => v)), maxV = Math.max(...all.map(([, v]) => v));
  const rv = Math.max(maxV - minV, 1e-6);
  const px = (v: number) => L + ((v - minV) / rv) * dw;
  const py = (d: number) => T + (Math.min(d, maxD) / maxD) * dh;
  const dec = tickDecimals(rv);
  return (
    <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} className="block bg-black/40 rounded-md mb-2 border border-white/10"
      role="img" aria-label={ariaLabel} data-testid="argo-profile-chart">
      {win && win[0] <= maxD && (
        <rect data-testid="argo-depth-window" x={L} y={py(win[0])} width={dw} height={Math.max(py(win[1]) - py(win[0]), 1.5)}
          fill="rgb(251 191 36)" fillOpacity={0.14} />)}
      <line x1={L} y1={T} x2={L} y2={T + dh} stroke="white" strokeOpacity={0.18} />
      <line x1={L} y1={T + dh} x2={L + dw} y2={T + dh} stroke="white" strokeOpacity={0.18} />
      {[0, maxD / 2, maxD].map((d, i) => (
        <text key={`d${i}`} x={L - 6} y={py(d) + 3} textAnchor="end" fontSize="9" fill="rgba(255,255,255,0.55)">{Math.round(d)}</text>))}
      {[minV, (minV + maxV) / 2, maxV].map((v, i) => (
        <text key={`v${i}`} x={px(v)} y={T + dh + 14} textAnchor="middle" fontSize="9" fill="rgba(255,255,255,0.55)">{v.toFixed(dec)}</text>))}
      {fld.length > 1 && (
        <polyline data-testid="argo-field-curve" points={fld.map(([d, v]) => `${px(v)},${py(d)}`).join(" ")}
          fill="none" stroke="rgb(52 211 153)" strokeDasharray="4 3" strokeWidth={1.2} />)}
      {fld.map(([d, v], i) => <circle key={`f${i}`} cx={px(v)} cy={py(d)} r={2.2} fill="none" stroke="rgb(52 211 153)" strokeWidth={1} />)}
      <polyline points={good.map(([d, v]) => `${px(v)},${py(d)}`).join(" ")} fill="none"
        stroke="rgb(248 250 252)" strokeOpacity={0.85} strokeWidth={1.4} />
      {good.map(([d, v], i) => <circle key={i} cx={px(v)} cy={py(d)} r={2} fill="rgb(248 250 252)" />)}
      <text transform={`translate(11 ${T + dh / 2}) rotate(-90)`} textAnchor="middle" fontSize="10" fill="rgba(255,255,255,0.5)">{depthLabel}</text>
      <text x={L + dw / 2} y={H - 6} textAnchor="middle" fontSize="10" fill="rgba(255,255,255,0.5)">{label}{units ? ` (${units})` : ""}</text>
    </svg>
  );
}

export function ArgoOxygenProfilePanel({ id }: { id: string }) {
  const { t } = useTranslation("panels");
  const oxygenDepth = useMapStore((s) => s.oxygenDepth);
  const [data, setData] = useState<ArgoProfilePayload | null>(null);
  const [state, setState] = useState<"loading" | "missing" | "error" | "ok">("loading");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const ctrl = new AbortController();
    setState("loading");
    setData(null);
    fetch(`${API}/api/v1/argo-oxygen/profile/${encodeURIComponent(id)}`, { signal: ctrl.signal })
      .then((r) => {
        if (r.status === 404) { setState("missing"); return null; }
        if (!r.ok) throw new Error(String(r.status));       // 503 + Retry-After lands here, with every other failure
        return r.json();
      })
      .then((j) => { if (j) { setData(j as ArgoProfilePayload); setState("ok"); } })
      .catch((e) => { if (e?.name !== "AbortError") setState("error"); });
    return () => ctrl.abort();
  }, [id, attempt]);

  if (state === "loading") return <p className="text-white/60 text-xs animate-pulse">{t("argoProfile.loading")}</p>;
  if (state === "missing") return <p className="text-white/70 text-sm" role="status">{t("argoProfile.missing")}</p>;
  if (state === "error" || !data) {
    return (
      <div role="alert">
        <p className="text-amber-300/90 text-sm mb-2">{t("argoProfile.unavailable")}</p>
        <button type="button" onClick={() => setAttempt((n) => n + 1)}
          className="text-xs text-cyan-300 border border-cyan-500/40 rounded px-2 py-1 hover:bg-cyan-500/10">
          {t("argoProfile.retry")}
        </button>
      </div>
    );
  }

  const good = goodSeries(data.levels, data.doxy_mode);
  const other = otherCounts(data.levels, data.doxy_mode);
  const key = String(oxygenDepth);
  const pick = data.at_depth?.[key] ?? null;
  const fieldHere = data.field_recent?.[key] ?? null;
  const win = data.depth_windows?.[key] ?? ARGO_DEPTH_WINDOW_BOUNDS[oxygenDepth] ?? null;
  // The dashed comparison: the ISAS20 Recent mean at the display depths that have a value here, in metres.
  const fieldPoints = Object.entries(data.field_recent ?? {})
    .filter(([, v]) => v !== null && v !== undefined)
    .map(([d, v]) => [Number(d), v as number] as [number, number])
    .sort((a, b) => a[0] - b[0]);
  // Pressure beside the depth, never instead of it: the level the pick came from.
  const pickIdx = pick ? data.levels.depth_m.findIndex((d) => d === pick[1]) : -1;
  const pickPres = pickIdx >= 0 ? data.levels.pres_dbar[pickIdx] : null;
  const units = data.units ?? "µmol/kg";
  const when = profileMoment(data.profile_time);
  const credits = data.citations?.length ? data.citations : [data.citation].filter(Boolean);
  const dir = t(data.direction === "D" ? "argoProfile.descending" : "argoProfile.ascending");

  return (
    <div data-testid="argo-profile-panel">
      <PanelHeader>{t("argoProfile.title", { wmo: data.platform_number, cycle: data.cycle_number })}</PanelHeader>
      <p className="text-white/65 text-xs mb-3">{dir} · {data.product}</p>

      {!data.drawable && <WarningBanner color="orange">{t("argoProfile.notDrawn")}</WarningBanner>}

      {good.length > 0 ? (
        <>
          <ArgoProfileChart good={good} field={fieldPoints} window={win} units={units}
            label={t("argoProfile.oxygen")} depthLabel={t("argoProfile.depthAxis")} ariaLabel={t("argoProfile.chartAria")} />
          <p className="text-white/60 text-[11px] mb-3">{t("argoProfile.chartCaption")}</p>
        </>
      ) : (
        <p className="text-white/65 text-xs mb-3" data-testid="argo-no-good">{t("argoProfile.noChart")}</p>
      )}

      <Section title={t("argoProfile.atDepth", { depth: oxygenDepth })}>
        <Row label={t("argoProfile.profileValue")}
          value={pick
            ? t(pickPres !== null ? "argoProfile.pickValue" : "argoProfile.pickValueNoPres",
                { value: fmt1(pick[0]), units, depth: fmt1(pick[1]), pres: pickPres !== null ? fmt1(pickPres) : "" })
            : t("argoProfile.noValue", { window: argoWindowLabel(oxygenDepth) })} />
        <Row label={t("argoProfile.fieldRecent")}
          value={fieldHere !== null && fieldHere !== undefined ? `${fmt1(fieldHere)} ${units}` : "—"} />
      </Section>

      <Section title={t("argoProfile.sectionProfile")}>
        <Row label={t("argoProfile.float")} value={
          <a href={data.float_url} target="_blank" rel="noopener noreferrer" className="text-cyan-300 hover:underline">
            {data.platform_number} <span aria-hidden="true">↗</span>
          </a>} />
        <Row label={t("argoProfile.dac")} value={data.dac} />
        <Row label={t("argoProfile.cycle")} value={String(data.cycle_number)} />
        <Row label={t("argoProfile.date")} value={when ?? t("argoProfile.noDate")} />
        {data.lat !== null && data.lon !== null && (
          <Row label={t("argoProfile.position")}
            value={`${data.lat.toFixed(3)}°, ${data.lon.toFixed(3)}°${data.position_qc !== null && data.position_qc !== undefined ? ` · ${t("argoProfile.positionQc", { qc: data.position_qc })}` : ""}`} />)}
        <Row label={t("argoProfile.dataMode")} value={t(modeLabelKey(data.doxy_mode))} />
        <Row label={t("argoProfile.pressure")} value={t(presSourceKey(data.pres_source))} />
        <Row label={t("argoProfile.levels")} value={t("argoProfile.goodCount", { good: data.n_good, total: data.n_levels_source })} />
        {other.adjustedFlagged > 0 && (
          <p className="text-white/55 text-[11px] leading-snug mt-1">{t("argoProfile.flaggedCount", { count: other.adjustedFlagged, stored: data.n_levels })}</p>)}
        {other.rawOnly > 0 && (
          <p className="text-white/55 text-[11px] leading-snug mt-1">{t("argoProfile.rawCount", { count: other.rawOnly, stored: data.n_levels })}</p>)}
      </Section>

      <Section title={t("argoProfile.sectionSource")}>
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs mb-2">
          <a href={data.source_url} target="_blank" rel="noopener noreferrer" className="text-cyan-300 hover:underline">
            {t("argoProfile.dataFile")} <span aria-hidden="true">↗</span>
          </a>
          <a href={data.source_home} target="_blank" rel="noopener noreferrer" className="text-cyan-300 hover:underline">
            {t("argoProfile.sourceHome")} <span aria-hidden="true">↗</span>
          </a>
        </div>
        <p className="text-white/55 text-[11px] leading-snug mb-1">{t("argoProfile.fieldProductLabel", { product: data.field_product })}</p>
        {credits.map((c) => <p key={c} className="text-white/55 text-[11px] leading-snug mb-1">{c}</p>)}
      </Section>
    </div>
  );
}
