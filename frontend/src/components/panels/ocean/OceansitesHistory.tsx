// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { API, T } from "../shared/tokens";
import { Row, Section, ExternalLink } from "../shared/primitives";

// The historical record of a mooring, read from the OceanSITES GDAC archive.
// Shape of GET /v1/oceansites/{ref}/history (backend/domains/oceansites_history.py).
//
// ⛔ A series is identified by (standard_name, depth_m, units) — NOT by the first
// two. TAO 0N140W has eastward velocity at 45 m in both cm/s and m/s: two series,
// same quantity, same depth, different units. Merging them would put m/s values
// on a cm/s line. Units are shown exactly as the archive declares them.
// ⛔ The points are every N-th REAL measurement, not averages: never compute one.
// ⛔ qc_withheld (the source's own quality flag), missing (no value recorded) and
// duplicates_dropped (overlapping files) are three different counts. Do not sum.

export interface HistorySeries {
  variable: string;
  standard_name: string;
  long_name: string | null;
  units: string | null;
  depth_m: number | null;   // null: a file that declares no depth — shown without one, never as "null m"
  depths_available: number[];
  points: [string, number][];
  n_total_measurements: number;
  stride_max: number;
  qc_withheld: number;
  missing: number;
  duplicates_dropped: number;
}

export interface HistoryResponse {
  ref: string;
  start: string | null;
  end: string | null;
  n_catalogue_files: number;
  n_files_read: number;
  citation: string;
  citations: string[];
  files: { file: string; data_mode: string; start: string | null; end: string | null }[];
  series: HistorySeries[];
}

type LoadState =
  | { kind: "loading" }
  | { kind: "error" }
  | { kind: "ok"; data: HistoryResponse };

// Collapsed to the first few variables: TAO moorings carry 19 series by default.
const COLLAPSED_GROUPS = 4;
const GDAC_THREDDS = "https://tds0.ifremer.fr/thredds/catalog/CORIOLIS-OCEANSITES-GDAC-OBS/DATA";

function variableLabelKey(standardName: string) {
  switch (standardName) {
    case "sea_water_temperature":           return "oceansites.historyVarSeaWaterTemperature" as const;
    case "sea_surface_temperature":         return "oceansites.historyVarSeaSurfaceTemperature" as const;
    case "sea_water_practical_salinity":    return "oceansites.historyVarPracticalSalinity" as const;
    case "sea_water_salinity":              return "oceansites.historyVarSalinity" as const;
    case "mass_concentration_of_oxygen_in_sea_water":
    case "moles_of_oxygen_per_unit_mass_in_sea_water":
    case "mole_concentration_of_dissolved_molecular_oxygen_in_sea_water":
                                            return "oceansites.historyVarOxygen" as const;
    case "eastward_sea_water_velocity":     return "oceansites.historyVarEastwardVelocity" as const;
    case "northward_sea_water_velocity":    return "oceansites.historyVarNorthwardVelocity" as const;
    case "mass_concentration_of_chlorophyll_in_sea_water":
                                            return "oceansites.historyVarChlorophyll" as const;
    default:                                return null;
  }
}

// Four significant figures, no trailing zeros: 14.415147 → 14.42, 0.0123456 → 0.01235.
function fmt(v: number): string {
  return String(Number(v.toPrecision(4)));
}

const day = (iso: string | null | undefined) => (iso ? String(iso).slice(0, 10) : "—");

function dataPoints(s: HistorySeries): [string, number][] {
  return (Array.isArray(s.points) ? s.points : []).filter(
    p => Array.isArray(p) && typeof p[1] === "number" && Number.isFinite(p[1]),
  );
}

// Inline SVG, no chart dependency. x follows the timestamps (the points are
// strided, so spacing is uneven and the line must not pretend otherwise); a
// constant series is drawn flat in the middle rather than dividing by zero.
export function Sparkline({ points, label }: { points: [string, number][]; label: string }) {
  const W = 120, H = 28, PAD = 2;
  const ts = points.map(p => Date.parse(p[0]));
  const vs = points.map(p => p[1]);
  const t0 = Math.min(...ts), t1 = Math.max(...ts);
  const v0 = Math.min(...vs), v1 = Math.max(...vs);
  const x = (t: number) => (t1 === t0 ? W / 2 : PAD + ((t - t0) / (t1 - t0)) * (W - 2 * PAD));
  const y = (v: number) => (v1 === v0 ? H / 2 : H - PAD - ((v - v0) / (v1 - v0)) * (H - 2 * PAD));
  const path = points.map((_, i) => `${x(ts[i]).toFixed(1)},${y(vs[i]).toFixed(1)}`).join(" ");
  return (
    <svg
      role="img"
      aria-label={label}
      data-testid="oceansites-sparkline"
      viewBox={`0 0 ${W} ${H}`}
      width={W}
      height={H}
      className="shrink-0 text-cyan-300"
    >
      {points.length === 1
        ? <circle cx={x(ts[0])} cy={y(vs[0])} r={2} fill="currentColor" />
        : <polyline points={path} fill="none" stroke="currentColor" strokeWidth={1.2} strokeLinejoin="round" />}
    </svg>
  );
}

function SeriesRow({ s, variable }: { s: HistorySeries; variable: string }) {
  const { t } = useTranslation(["panels"]);
  const pts = dataPoints(s);
  const times = pts.map(p => p[0]).sort();
  const first = times[0], last = times[times.length - 1];
  const vals = pts.map(p => p[1]);
  const flags: string[] = [];
  if (s.qc_withheld > 0) flags.push(t("oceansites.historyQcWithheld", { count: s.qc_withheld }));
  if (s.missing > 0) flags.push(t("oceansites.historyMissing", { count: s.missing }));
  if (s.duplicates_dropped > 0) flags.push(t("oceansites.historyDuplicates", { count: s.duplicates_dropped }));
  return (
    <div className="py-1.5 border-b border-white/5 last:border-0" data-testid="oceansites-series">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          {s.depth_m != null && <p className="text-white/90 text-[14px] font-mono">{s.depth_m} m</p>}
          <p className="text-white/65 text-[13px]">{day(first)} – {day(last)}</p>
        </div>
        {pts.length > 0 && (
          <Sparkline
            points={pts}
            label={s.depth_m != null
              ? t("oceansites.historySparkLabel", { variable, depth: s.depth_m, start: day(first), end: day(last) })
              : t("oceansites.historySparkLabelNoDepth", { variable, start: day(first), end: day(last) })}
          />
        )}
      </div>
      {vals.length > 0 && (
        <p className="text-white/70 text-[13px] font-mono">
          {t("oceansites.historyRange", { min: fmt(Math.min(...vals)), max: fmt(Math.max(...vals)) })}
        </p>
      )}
      <p className="text-white/60 text-[13px]">
        {t("oceansites.historyPlotted", { plotted: pts.length, total: s.n_total_measurements })}
      </p>
      {flags.map(f => <p key={f} className="text-orange-300/80 text-[13px]">{f}</p>)}
    </div>
  );
}

interface Group { key: string; label: string; units: string | null; series: HistorySeries[] }

function groupSeries(series: HistorySeries[], labelOf: (s: HistorySeries) => string): Group[] {
  const groups = new Map<string, Group>();
  for (const s of series) {
    const key = `${s.standard_name}|${s.units ?? ""}`;
    let g = groups.get(key);
    if (!g) { g = { key, label: labelOf(s), units: s.units, series: [] }; groups.set(key, g); }
    g.series.push(s);
  }
  for (const g of groups.values()) g.series.sort((a, b) => (a.depth_m ?? Infinity) - (b.depth_m ?? Infinity));  // no-depth series last
  return [...groups.values()];
}

export function OceansitesHistory({ properties: p }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation(["panels"]);
  const ref = p.ref != null ? String(p.ref) : "";
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [showAll, setShowAll] = useState(false);

  // Once per station, when the panel opens. ⛔ `${API}/api/v1/...` (the BFF
  // proxy); the bare `/v1/...` path silently fails in the SPA.
  useEffect(() => {
    if (!ref) return;
    const ctl = new AbortController();
    setState({ kind: "loading" });
    fetch(`${API}/api/v1/oceansites/${encodeURIComponent(ref)}/history`, { signal: ctl.signal })
      .then(r => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d: HistoryResponse) => {
        if (!d || !Array.isArray(d.series)) throw new Error("malformed");
        setState({ kind: "ok", data: d });
      })
      .catch(() => { if (!ctl.signal.aborted) setState({ kind: "error" }); });
    return () => ctl.abort();
  }, [ref]);

  const labelOf = (s: HistorySeries) => {
    const key = variableLabelKey(s.standard_name);
    return key ? t(key) : (s.long_name || s.standard_name.replace(/_/g, " "));
  };

  const data = state.kind === "ok" ? state.data : null;
  const groups = data ? groupSeries(data.series, labelOf) : [];
  const shown = showAll ? groups : groups.slice(0, COLLAPSED_GROUPS);
  const siteDir = data?.files?.[0]?.file?.split("/")[1];
  const threddsUrl = `${GDAC_THREDDS}/${siteDir ? `${encodeURIComponent(siteDir)}/` : ""}catalog.html`;
  const citations = data ? (data.citations?.length ? data.citations : [data.citation]).filter(Boolean) : [];

  return (
    <Section title={t("oceansites.historySectionTitle")}>
      {p.history_start != null && p.history_end != null && (
        <Row label={t("oceansites.historySpanLabel")}
             value={`${day(String(p.history_start))} – ${day(String(p.history_end))}`} />
      )}
      <Row label={t("oceansites.historyFilesLabel")} value={String(Number(p.history_files))} />
      {data && data.series.length > 0 && (
        <Row label={t("oceansites.historyFilesReadLabel")} value={String(data.n_files_read)} />
      )}

      {state.kind === "loading" && (
        <p className="text-white/65 text-[13px] italic mt-1">{t("oceansites.historyLoading")}</p>
      )}
      {state.kind === "error" && (
        <p className="text-orange-300 text-[13px] mt-1" role="alert">{t("oceansites.historyError")}</p>
      )}
      {data && data.series.length === 0 && (
        <p className="text-white/65 text-[13px] italic mt-1">{t("oceansites.historyEmpty")}</p>
      )}

      {data && data.series.length > 0 && (
        <>
          <p className={`${T.hint} mt-2`}>{t("oceansites.historyNotAverages")}</p>
          {shown.map(g => {
            const available = g.series[0].depths_available?.length ?? 0;
            const distinct = new Set(g.series.map(s => s.depth_m).filter(d => d != null)).size;  // depths_available lists numeric depths only
            return (
              <div key={g.key} className="mt-3" data-testid="oceansites-variable">
                <p className="text-white/90 text-[14px] font-sans">{g.label}</p>
                <p className="text-white/65 text-[13px]">
                  {g.units ? t("oceansites.historyUnits", { units: g.units }) : t("oceansites.historyNoUnits")}
                  {available > distinct && <> · {t("oceansites.historyDepthsShown", { shown: distinct, total: available })}</>}
                </p>
                {g.series.map(s => (
                  <SeriesRow key={`${s.variable}|${s.depth_m}|${s.units ?? ""}`} s={s} variable={g.label} />
                ))}
              </div>
            );
          })}
          {groups.length > COLLAPSED_GROUPS && (
            <button
              type="button"
              onClick={() => setShowAll(v => !v)}
              className="mt-3 text-cyan-300 hover:text-cyan-200 text-[13px] underline underline-offset-2"
            >
              {showAll ? t("oceansites.historyShowFewer") : t("oceansites.historyShowAll", { count: groups.length })}
            </button>
          )}
          <div className="mt-3 pt-2 border-t border-white/5">
            <p className="text-white/65 text-[13px] uppercase tracking-widest mb-1">{t("oceansites.historyCitationTitle")}</p>
            {citations.map(c => <p key={c} className="text-white/70 text-[13px] leading-relaxed mb-1">{c}</p>)}
          </div>
        </>
      )}

      {data && (
        <div className="mt-2">
          <ExternalLink href={threddsUrl} label={t("oceansites.historyBrowse")} />
        </div>
      )}
    </Section>
  );
}
