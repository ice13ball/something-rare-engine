// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

/**
 * Click panel for one GLODAPv3 bottle cast (`/api/v1/glodap/cast/{cast_key}`, backend/domains/glodap_points.py).
 *
 * ⛔ The chart draws WOCE flag 2 only. A flag-0 value (interpolated / calculated) is counted in the metadata
 * and never plotted as if it were a measurement. Flag-9 samples carry no value at all.
 * ⛔ 13,004 casts are date-only: the time of day appears ONLY when `time_precision === "minute"`. A date-only
 * cast must never gain a "00:00".
 * ⛔ Missing and broken never share a state: 404 = "this cast no longer exists" (a re-import may drop a cast),
 * anything else = unavailable, with a retry. Never a blank panel.
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { API } from "../shared/tokens";
import { PanelHeader, Row, Section, WarningBanner } from "../shared/primitives";
import { useMapStore } from "../../../store/mapStore";
import { glodapWindowLabel, GLODAP_DEPTH_WINDOW_BOUNDS } from "../../../utils/glodapPoints";

/** Field variable (the ocean-carbon store key) -> the bottle column it is compared with. Cant has no bottle:
 *  the chart falls back to DIC, with a caption — nothing else uses this fallback. */
export const BOTTLE_FOR_FIELD: Record<string, string> = { dic: "tco2", talk: "talk", ph: "phtsinsitutp", cant: "tco2" };
/** Bottle column -> the field variable drawn as the dashed comparison curve. Cant is deliberately absent. */
const FIELD_FOR_BOTTLE: Record<string, string> = { tco2: "dic", talk: "talk", phtsinsitutp: "ph" };
const FIELD_UNITS: Record<string, string> = { dic: "µmol/kg", talk: "µmol/kg", cant: "µmol/kg", ph: "" };
/** Field variable -> the i18n key of its name (`glodapCast.var.*`). */
const FIELD_NAME_KEY: Record<string, string> = { dic: "tco2", talk: "talk", ph: "phtsinsitutp", cant: "cant" };

type Var = { values: (number | null)[]; flags: number[]; qc: number | null; units: string };
export type CastPayload = {
  cast_key: string; expocode: string; station: string; cast_no: number | null; ship_name: string | null;
  lat: number; lon: number; obs_date: string; obs_time: string | null; time_precision: "minute" | "day";
  doi: string | null; bottom_depth_m: number | null; pos_spread_km: number | null; depth_m: number[];
  variables: Record<string, Var>;
  /** field key -> standard depth (m) -> [bottle value, bottle depth] picked inside that depth's window */
  levels: Record<string, Record<string, [number, number]>>;
  /** field key -> standard depth (m) -> the mapped climatology at the cast position */
  field: Record<string, Record<string, number | null>>;
  citation: string; citations?: string[]; source_url: string; product: string; field_product: string;
};

/** Flag-2 samples as chart data; everything else that still has a value is only listed. Depth-ordered as stored. */
export function profileSamples(p: Pick<CastPayload, "depth_m" | "variables">, col: string) {
  const good: [number, number][] = [];
  const other: [number, number, number][] = [];
  const v = p.variables[col];
  if (!v) return { good, other };
  p.depth_m.forEach((d, i) => {
    const val = v.values[i];
    const f = v.flags[i];
    if (val === null || val === undefined || d === null || d === undefined) return;
    if (f === 2) good.push([d, val]);
    else other.push([d, val, f]);
  });
  return { good, other };
}

/**
 * The flag-2 bottle the map would use at a standard depth, for variables the server does not pre-compute
 * (`levels` exists only for DIC, TA and pH): closest to the standard depth inside its window, as
 * backend `pick_level`. Null = no acceptable bottle in the window.
 */
export function bottleInWindow(good: [number, number][], stdDepth: number): [number, number] | null {
  const w = GLODAP_DEPTH_WINDOW_BOUNDS[stdDepth];
  if (!w) return null;
  let best: [number, number] | null = null;
  for (const [d, v] of good) {
    if (d < w[0] || d > w[1]) continue;
    if (best === null || Math.abs(d - stdDepth) < Math.abs(best[0] - stdDepth)
      || (Math.abs(d - stdDepth) === Math.abs(best[0] - stdDepth) && d < best[0])) best = [d, v];
  }
  return best === null ? null : [best[1], best[0]];     // [value, depth], as `levels`
}

/** Decimals for three ticks (min, mid, max) over `range`, so neighbours never print alike: 34.6-34.9 -> 2. */
export function tickDecimals(range: number): number {
  const step = Math.max(range, 1e-9) / 2;
  return Math.min(4, Math.max(0, Math.ceil(-Math.log10(step)) + 1));
}

/** `{ date, time }` — `time` is null for a date-only cast, never "00:00". */
export function castMoment(p: Pick<CastPayload, "obs_date" | "obs_time" | "time_precision">): { date: string; time: string | null } {
  if (p.time_precision === "minute" && p.obs_time) {
    const d = new Date(p.obs_time);
    if (!Number.isNaN(d.getTime())) {
      const iso = d.toISOString();                       // UTC, always — never the viewer's zone
      return { date: iso.slice(0, 10), time: `${iso.slice(11, 16)} UTC` };
    }
  }
  return { date: p.obs_date.slice(0, 10), time: null };
}

/** The cruise DOI as a link; the source stores either a bare DOI or a full URL. */
export function doiUrl(doi: string | null | undefined): string | null {
  const d = (doi ?? "").trim();
  if (!d) return null;
  if (/^https?:\/\//i.test(d)) return d;
  return `https://doi.org/${d.replace(/^doi:\s*/i, "")}`;
}

/** The credits the panel must show. The NVS (CC BY 4.0) attribution is a licence condition of the SHIP NAME,
 *  so it travels only when a ship name is on screen. Falls back to the combined string for an older payload. */
export function creditsFor(p: Pick<CastPayload, "citations" | "citation" | "ship_name">): string[] {
  const list = p.citations && p.citations.length > 0 ? p.citations : [p.citation].filter(Boolean);
  const isShipCredit = (c: string) => /vocab\.nerc\.ac\.uk/i.test(c);
  return p.ship_name ? list : list.filter((c) => !isShipCredit(c));
}

export function GlodapProfileChart({ samples, fieldPoints, picked, units, label, depthLabel = "Depth (m)", ariaLabel }: {
  samples: [number, number][]; fieldPoints: [number, number][]; picked: [number, number] | null;
  units: string; label: string; depthLabel?: string; ariaLabel?: string;
}) {
  if (samples.length < 1) return null;
  const W = 300, H = 230, L = 50, R = 14, T = 16, B = 46, dw = W - L - R, dh = H - T - B;
  // The depth axis follows the cast. A field curve that reaches 4000 m would squash a 100 m cast into a line,
  // so the comparison is clipped to the depths the bottles actually cover.
  const maxD = Math.max(...samples.map(([d]) => d), 10);
  const field = fieldPoints.filter(([d]) => d <= maxD);
  const all = [...samples, ...field];
  const minV = Math.min(...all.map(([, v]) => v)), maxV = Math.max(...all.map(([, v]) => v));
  const rv = Math.max(maxV - minV, 1e-6);
  const px = (v: number) => L + ((v - minV) / rv) * dw;
  const py = (d: number) => T + (d / maxD) * dh;
  const dec = tickDecimals(rv);
  const fmt = (v: number) => v.toFixed(dec);
  return (
    <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} className="block bg-black/40 rounded-md mb-2 border border-white/10"
      role="img" aria-label={ariaLabel ?? `${label} profile`} data-testid="glodap-profile-chart">
      <line x1={L} y1={T} x2={L} y2={T + dh} stroke="white" strokeOpacity={0.18} />
      <line x1={L} y1={T + dh} x2={L + dw} y2={T + dh} stroke="white" strokeOpacity={0.18} />
      {[0, maxD / 2, maxD].map((d, i) => (
        <text key={`d${i}`} x={L - 6} y={py(d) + 3} textAnchor="end" fontSize="9" fill="rgba(255,255,255,0.55)">{Math.round(d)}</text>))}
      {[minV, (minV + maxV) / 2, maxV].map((v, i) => (
        <text key={`v${i}`} x={px(v)} y={T + dh + 14} textAnchor="middle" fontSize="9" fill="rgba(255,255,255,0.55)">{fmt(v)}</text>))}
      {field.length > 1 && (
        <polyline data-testid="glodap-field-curve" points={field.map(([d, v]) => `${px(v)},${py(d)}`).join(" ")}
          fill="none" stroke="rgb(52 211 153)" strokeDasharray="4 3" strokeWidth={1.2} />)}
      {field.map(([d, v], i) => <circle key={`f${i}`} cx={px(v)} cy={py(d)} r={2.2} fill="none" stroke="rgb(52 211 153)" strokeWidth={1} />)}
      <polyline points={samples.map(([d, v]) => `${px(v)},${py(d)}`).join(" ")} fill="none"
        stroke="rgb(248 250 252)" strokeOpacity={0.85} strokeWidth={1.4} />
      {samples.map(([d, v], i) => <circle key={i} cx={px(v)} cy={py(d)} r={2} fill="rgb(248 250 252)" />)}
      {picked && <circle data-testid="glodap-picked" cx={px(picked[1])} cy={py(picked[0])} r={4.5} fill="none" stroke="rgb(251 191 36)" strokeWidth={1.6} />}
      <text transform={`translate(11 ${T + dh / 2}) rotate(-90)`} textAnchor="middle" fontSize="10" fill="rgba(255,255,255,0.5)">{depthLabel}</text>
      <text x={L + dw / 2} y={H - 6} textAnchor="middle" fontSize="10" fill="rgba(255,255,255,0.5)">{label}{units ? ` (${units})` : ""}</text>
    </svg>
  );
}

const fmtField = (v: number, key: string) => (key === "ph" ? v.toFixed(3) : v.toFixed(1));

export function GlodapCastPanel({ id }: { id: string }) {
  const { t } = useTranslation("panels");
  const carbonVariable = useMapStore((s) => s.carbonVariable);
  const carbonDepth = useMapStore((s) => s.carbonDepth);
  const [data, setData] = useState<CastPayload | null>(null);
  const [state, setState] = useState<"loading" | "missing" | "error" | "ok">("loading");
  const [attempt, setAttempt] = useState(0);
  const [col, setCol] = useState(BOTTLE_FOR_FIELD[carbonVariable] ?? "tco2");
  useEffect(() => { setCol(BOTTLE_FOR_FIELD[carbonVariable] ?? "tco2"); }, [carbonVariable]);

  useEffect(() => {
    const ctrl = new AbortController();
    setState("loading");
    setData(null);
    fetch(`${API}/api/v1/glodap/cast/${encodeURIComponent(id)}`, { signal: ctrl.signal })
      .then((r) => {
        if (r.status === 404) { setState("missing"); return null; }
        if (!r.ok) throw new Error(String(r.status));       // 503 + Retry-After lands here, with every other failure
        return r.json();
      })
      .then((j) => { if (j) { setData(j as CastPayload); setState("ok"); } })
      .catch((e) => { if (e?.name !== "AbortError") setState("error"); });
    return () => ctrl.abort();
  }, [id, attempt]);

  if (state === "loading") return <p className="text-white/60 text-xs animate-pulse">{t("glodapCast.loading")}</p>;
  if (state === "missing") return <p className="text-white/70 text-sm" role="status">{t("glodapCast.missing")}</p>;
  if (state === "error" || !data) {
    return (
      <div role="alert">
        <p className="text-amber-300/90 text-sm mb-2">{t("glodapCast.error")}</p>
        <button type="button" onClick={() => setAttempt((n) => n + 1)}
          className="text-xs text-cyan-300 border border-cyan-500/40 rounded px-2 py-1 hover:bg-cyan-500/10">
          {t("glodapCast.retry")}
        </button>
      </div>
    );
  }

  const v = data.variables[col];
  const s = profileSamples(data, col);
  const fieldKey = FIELD_FOR_BOTTLE[col];
  const colName = t(`glodapCast.var.${col}`, { defaultValue: col });
  const fieldPoints = fieldKey
    ? Object.entries(data.field?.[fieldKey] ?? {})
        .filter(([, val]) => val !== null && val !== undefined)
        .map(([d, val]) => [Number(d), val as number] as [number, number])
        .sort((a, b) => a[0] - b[0])
    : [];
  // DIC, TA and pH: the server's pre-computed level. Every other variable: the same rule, computed here.
  const lvl = fieldKey ? data.levels?.[fieldKey]?.[String(carbonDepth)] ?? null : bottleInWindow(s.good, carbonDepth);
  // The field value the MAP is showing at this spot (the selected variable, which for Cant has no bottle).
  const mapVar = FIELD_NAME_KEY[carbonVariable] ? carbonVariable : "dic";
  const fieldHere = data.field?.[mapVar]?.[String(carbonDepth)] ?? null;
  const when = castMoment(data);
  const doi = doiUrl(data.doi);
  const credits = creditsFor(data);
  const qcText = v?.qc === 1 ? t("glodapCast.qc1") : v?.qc === 0 ? t("glodapCast.qc0") : t("glodapCast.noQc");

  return (
    <div data-testid="glodap-cast-panel">
      <PanelHeader>{data.ship_name ? `${data.ship_name} · ${data.expocode}` : data.expocode}</PanelHeader>
      <p className="text-white/65 text-xs mb-3">{t("glodapCast.productNote", { points: data.product, field: data.field_product })}</p>

      <label className="flex items-center gap-2 text-xs text-white/80 mb-2">
        {t("glodapCast.variable")}
        <select value={col} onChange={(e) => setCol(e.target.value)}
          className="bg-black/40 border border-white/15 rounded px-1 py-0.5 text-white/90">
          {Object.keys(data.variables).map((k) => <option key={k} value={k}>{t(`glodapCast.var.${k}`, { defaultValue: k })}</option>)}
        </select>
      </label>
      {carbonVariable === "cant" && col === "tco2" && (
        <WarningBanner color="orange">{t("glodapCast.cantFallback")}</WarningBanner>)}

      {s.good.length > 0 ? (
        <>
          <GlodapProfileChart samples={s.good} fieldPoints={fieldPoints} picked={lvl ? [lvl[1], lvl[0]] : null}
            units={v?.units ?? ""} label={colName} depthLabel={t("glodapCast.depthAxis")}
            ariaLabel={t("glodapCast.chartAria", { variable: colName })} />
          <p className="text-white/60 text-[11px] mb-3">
            {t("glodapCast.legend")}{fieldPoints.length > 0 ? ` ${t("glodapCast.legendField")}` : ""}
          </p>
        </>
      ) : (
        <p className="text-white/65 text-xs mb-3" data-testid="glodap-no-acceptable">{t("glodapCast.noAcceptable", { variable: colName })}</p>
      )}

      <Section title={t("glodapCast.sectionValues")}>
        <Row label={t("glodapCast.atDepth", { variable: colName, depth: carbonDepth })}
          value={lvl ? `${Number(lvl[0].toPrecision(7))}${v?.units ? ` ${v.units}` : ""} @ ${lvl[1]} m` : t("glodapCast.noBottleInWindow", { window: glodapWindowLabel(carbonDepth) })} />
        <Row label={t("glodapCast.fieldHere", { variable: t(`glodapCast.var.${FIELD_NAME_KEY[mapVar]}`, { defaultValue: mapVar }), depth: carbonDepth })}
          value={fieldHere !== null && fieldHere !== undefined
            ? `${fmtField(fieldHere, mapVar)}${FIELD_UNITS[mapVar] ? ` ${FIELD_UNITS[mapVar]}` : ""}`
            : t("glodapCast.noField")} />
      </Section>

      <Section title={t("glodapCast.sectionCast")}>
        <Row label={t("glodapCast.cruise")} value={data.expocode} />
        {data.ship_name && <Row label={t("glodapCast.ship")} value={data.ship_name} />}
        <Row label={t("glodapCast.stationCast")} value={`${data.station} / ${data.cast_no ?? t("glodapCast.castNotGiven")}`} />
        <Row label={t("glodapCast.date")} value={when.time ? `${when.date} ${when.time}` : `${when.date} (${t("glodapCast.dayPrecision")})`} />
        <Row label={t("glodapCast.position")} value={`${data.lat.toFixed(3)}°, ${data.lon.toFixed(3)}°`} />
        {data.pos_spread_km !== null && data.pos_spread_km > 10 && (
          <Row label={t("glodapCast.spreadLabel")} value={t("glodapCast.spread", { km: Math.round(data.pos_spread_km) })} />)}
        {data.bottom_depth_m !== null && data.bottom_depth_m !== undefined && (
          <Row label={t("glodapCast.bottomDepth")} value={`${Math.round(data.bottom_depth_m)} m`} />)}
        <Row label={t("glodapCast.flags")} value={t("glodapCast.flagCounts", { good: s.good.length, other: s.other.length })} />
        <Row label={t("glodapCast.qc")} value={qcText} />
      </Section>

      <Section title={t("glodapCast.sectionSource")}>
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs mb-2">
          <a href={data.source_url} target="_blank" rel="noopener noreferrer" className="text-cyan-300 hover:underline">
            {t("glodapCast.source")} <span aria-hidden="true">↗</span>
          </a>
          {doi && (
            <a href={doi} target="_blank" rel="noopener noreferrer" className="text-cyan-300 hover:underline">
              {t("glodapCast.cruiseDoi")} <span aria-hidden="true">↗</span>
            </a>)}
        </div>
        {credits.map((c) => <p key={c} className="text-white/55 text-[11px] leading-snug mb-1">{c}</p>)}
      </Section>
    </div>
  );
}
