// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

/**
 * Click panel for one World Ocean Database 2023 cast (`/api/v1/wod/cast/{id}`, backend/domains/wod_casts.py) and,
 * for a map dot that stands for several casts, the list behind it (`/api/v1/wod/cell/{z}/{x}/{y}/{q}`).
 *
 * ⛔ Missing and broken never share a state: 404 = "no longer in the data (a reload may drop a cast)", anything
 * else = unavailable, with a retry. Never an empty panel.
 * ⛔ A value is `null`, never 0: 0 °C and N* = 0 are values, a missing level is "—" / "no good value".
 * ⛔ The cast is a MEASUREMENT; the WOA23 field beside it is an objectively analysed annual mean — a different
 * product, shown next to the cast and never in place of it.
 * ⛔ Time is UTC, and only as precise as the source: a zero fraction is "time not recorded", never 00:00; a month
 * or year source date is shown as that, never as the 1st.
 * ⛔ Only WOD flag 0 (accepted) is drawn on the chart and picked at a depth. Other flags are listed, never plotted.
 */
import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { API } from "../shared/tokens";
import { PanelHeader, Row, Section } from "../shared/primitives";
import { useMapStore } from "../../../store/mapStore";
import { useWodSelection } from "../../../store/wodSelection";
import { WOD_DEPTHS, WOD_PICK_VARS, WOD_WINDOWS, wodWindowLabel } from "../../../utils/wodCasts";
import { GlodapProfileChart } from "./GlodapCastPanel";

type Num = number | null;
type Level = [Num, number, number];                    // [depth m, value, WOD flag]
export type WodCastPayload = {
  cast_id: number; instrument: string | null; dataset: string | null; cruise: string | null; orig_cruise: string | null;
  platform: string | null; vehicle: string | null; wmo_id: string | number | null; institute: string | null;
  project: string | null; country: string | null; t_instrument: string | null; o2_instrument: string | null;
  real_time: boolean | string | null;
  date: string | null; time: string | null; time_precision: string | null; lat: number; lon: number;
  access_no: number | null; accession_url: string | null; source_file_url: string | null;
  /** WOD variable code (t s o p i n) -> its levels, non-null values only, every flag */
  levels: Record<string, Level[]>;
  depth_flag: number[]; pflag: number[]; n_src: number[];
  /** variable -> the value at each of the 8 display depths (server pick) */
  picks: Record<string, Num[]>;
  field: { variable: string; selected_depth: number | null; values: Record<string, Num> };
  /** source variable ("z", "Temperature", ...) -> flag -> meaning word */
  flag_meanings: Record<string, Record<string, string>>;
  product: string; licence: string; citation: string; source_url: string;
};
export type WodCellCast = {
  cast_id: number; instrument: string | null; dataset: string | null; date: string | null; time_precision: string | null;
  year: number; cruise: string | null; wmo_id: string | number | null; platform: string | null; vehicle: string | null;
  lat: number; lon: number;
};
export type WodCellPayload = {
  z: number; x: number; y: number; q: number; version: string; years: [number, number] | null;
  n_casts: number; year_min: number | null; year_max: number | null; casts: WodCellCast[]; truncated: boolean;
};

/** Variable -> WOD code of its levels, source variable name (for flag meanings), units and decimals shown. */
const VAR: Record<string, { code: string; nc: string; units: string }> = {
  temperature: { code: "t", nc: "Temperature", units: "°C" },
  salinity: { code: "s", nc: "Salinity", units: "" },
  oxygen: { code: "o", nc: "Oxygen", units: "µmol/kg" },
  phosphate: { code: "p", nc: "Phosphate", units: "µmol/kg" },
  silicate: { code: "i", nc: "Silicate", units: "µmol/kg" },
  nitrate: { code: "n", nc: "Nitrate", units: "µmol/kg" },
  nstar: { code: "x", nc: "Nitrate", units: "µmol/kg" },
};
const NSTAR_K = 16;                                     // == backend NSTAR_K
const CODE_ORDER = ["t", "s", "o", "p", "i", "n"];       // == backend VARS order: indexes `n_src` and `pflag`
const GOOD_FLAG = 0;

/** The variable the cast is asked for: the WOA variable when casts carry it, else dissolved O₂ (AOU, O₂ saturation). */
export const castVariableFor = (woaVariable: string): { variable: string; measured: boolean } =>
  (WOD_PICK_VARS as readonly string[]).includes(woaVariable)
    ? { variable: woaVariable, measured: true }
    : { variable: "oxygen", measured: false };

export const wodUnitsFor = (variable: string): string => VAR[variable]?.units ?? "";

/** The cast's levels of one variable. N* = nitrate - 16 phosphate at the same depth, both accepted (as the server's pick). */
export function wodLevelsFor(levels: Record<string, Level[]> | undefined, variable: string): Level[] {
  if (!levels) return [];
  if (variable !== "nstar") return levels[VAR[variable]?.code ?? ""] ?? [];
  const phosphate = new Map<number, number>();
  for (const [d, v, f] of levels.p ?? []) if (d !== null && f === GOOD_FLAG) phosphate.set(d, v);
  const out: Level[] = [];
  for (const [d, v, f] of levels.n ?? []) {
    const p = d === null ? undefined : phosphate.get(d);
    if (d !== null && f === GOOD_FLAG && p !== undefined) out.push([d, Number((v - NSTAR_K * p).toPrecision(7)), GOOD_FLAG]);
  }
  return out;
}

/** Accepted levels as chart data [depth, value], depth-ordered. */
export const goodSamples = (lv: Level[]): [number, number][] =>
  lv.filter(([d, , f]) => d !== null && f === GOOD_FLAG).map(([d, v]) => [d as number, v] as [number, number])
    .sort((a, b) => a[0] - b[0]);

/**
 * The accepted level the dot uses at a display depth: the server's pick (`picks`, depth-flag aware) located among the
 * levels by its value inside the depth's window (nearest to the depth wins a tie between equal values).
 * `value` is set when the server has one even if no level can be located (the levels are thinned to 100).
 */
export function pickedAt(
  payload: Pick<WodCastPayload, "levels" | "picks">, variable: string, depth: number,
): { value: number; depth: number | null } | null {
  const di = (WOD_DEPTHS as readonly number[]).indexOf(depth);
  const value = di < 0 ? null : payload.picks?.[variable]?.[di] ?? null;
  if (value === null) return null;
  const w = WOD_WINDOWS[depth];
  let best: number | null = null;
  for (const [d, v, f] of wodLevelsFor(payload.levels, variable)) {
    // A tolerance, not ===: N* is derived here from two levels and can differ from the server's in the 7th digit.
    if (d === null || f !== GOOD_FLAG || Math.abs(v - value) > 1e-4 * Math.max(1, Math.abs(value)) || !w || d < w[0] || d > w[1]) continue;
    if (best === null || Math.abs(d - depth) < Math.abs(best - depth)) best = d;
  }
  return { value, depth: best };
}

/** The flag's meaning word ("accepted_value" -> "accepted value"), or null when the source did not say. */
export function flagMeaning(meanings: WodCastPayload["flag_meanings"] | undefined, variable: string, flag: number): string | null {
  const word = meanings?.[VAR[variable]?.nc ?? ""]?.[String(flag)] ?? meanings?.z?.[String(flag)];
  return word ? word.replace(/_/g, " ") : null;
}

/** `2020-01-02` with its honest precision; `time` (UTC) only when the source had one. null parts are absent, never zero. */
export function castMoment(p: Pick<WodCastPayload, "date" | "time" | "time_precision">): { date: string | null; time: string | null; precision: string | null } {
  const date = p.date ? p.date.slice(0, 10) : null;
  if (!date) return { date: null, time: null, precision: p.time_precision };
  if (p.time_precision === "year") return { date: date.slice(0, 4), time: null, precision: "year" };
  if (p.time_precision === "month") return { date: date.slice(0, 7), time: null, precision: "month" };
  if (p.time_precision === "second" && p.time) return { date, time: `${p.time} UTC`, precision: "second" };
  return { date, time: null, precision: p.time_precision };
}

/** `CTD · XCTD`: the instrument (OSD, CTD, PFL) and the dataset when it adds something. */
export function instrumentLabel(p: Pick<WodCastPayload, "instrument" | "dataset">): string {
  const inst = (p.instrument ?? "").toUpperCase();
  const ds = (p.dataset ?? "").trim();
  if (inst && ds && ds.toUpperCase() !== inst) return `${inst} · ${ds}`;
  return inst || ds;
}

const fmt = (v: Num | undefined) => (v === null || v === undefined ? "—" : String(Number(v.toPrecision(6))));
const withUnits = (v: number, units: string) => `${fmt(v)}${units ? ` ${units}` : ""}`;

type Load = "loading" | "missing" | "error" | "ok";

function momentText(m: ReturnType<typeof castMoment>, words: { none: string; year: string; month: string; time: string }): string {
  if (!m.date) return words.none;
  if (m.time) return `${m.date} ${m.time}`;
  if (m.precision === "year") return `${m.date} (${words.year})`;
  if (m.precision === "month") return `${m.date} (${words.month})`;
  return `${m.date} (${words.time})`;
}

export function WodCastPanel({ castId, cell, k, years, version }: {
  castId: string; cell?: string; k?: number; years?: readonly [number, number]; version?: string;
}) {
  const { t } = useTranslation("panels");
  const woaVariable = useMapStore((s) => s.woaVariable);
  const woaDepth = useMapStore((s) => s.woaDepth);
  const { variable, measured } = castVariableFor(woaVariable);
  const depthKnown = (WOD_DEPTHS as readonly number[]).includes(woaDepth);

  // The cast shown: the dot's representative one, or the row chosen from the cell list.
  const [shownId, setShownId] = useState(castId);
  useEffect(() => { setShownId(castId); }, [castId]);

  const [cast, setCast] = useState<WodCastPayload | null>(null);
  const [castState, setCastState] = useState<Load>("loading");
  const [castAttempt, setCastAttempt] = useState(0);
  useEffect(() => {
    const ctrl = new AbortController();
    setCastState("loading");
    setCast(null);
    const depth = depthKnown ? `&depth=${woaDepth}` : "";
    fetch(`${API}/api/v1/wod/cast/${encodeURIComponent(shownId)}?var=${encodeURIComponent(variable)}${depth}`, { signal: ctrl.signal })
      .then((r) => {
        if (r.status === 404) { setCastState("missing"); return null; }
        if (!r.ok) throw new Error(String(r.status));       // 503 + Retry-After lands here, with every other failure
        return r.json();
      })
      .then((j) => { if (j) { setCast(j as WodCastPayload); setCastState("ok"); } })
      .catch((e) => { if (e?.name !== "AbortError") setCastState("error"); });
    return () => ctrl.abort();
  }, [shownId, variable, woaDepth, depthKnown, castAttempt]);

  // The position of the shown cast is ringed on the map (Map3D's `wod-selected-cast`); gone with the panel.
  useEffect(() => {
    if (castState === "ok" && cast) useWodSelection.getState().setFocus([cast.lon, cast.lat]);
    else useWodSelection.getState().setFocus(null);
  }, [cast, castState]);
  useEffect(() => () => useWodSelection.getState().setFocus(null), []);

  // A dot of several casts (k > 1) lists them; a single cast goes straight to /cast.
  const wantsCell = !!cell && (k ?? 1) > 1;
  const [cellData, setCellData] = useState<WodCellPayload | null>(null);
  const [cellState, setCellState] = useState<Load>("loading");
  const [cellAttempt, setCellAttempt] = useState(0);
  const y0 = years?.[0], y1 = years?.[1];
  useEffect(() => {
    if (!wantsCell) return;
    const ctrl = new AbortController();
    setCellState("loading");
    setCellData(null);
    const qs = [
      y0 !== undefined && y1 !== undefined ? `y0=${y0}&y1=${y1}` : "",
      version ? `v=${encodeURIComponent(version)}` : "",
    ].filter(Boolean).join("&");
    fetch(`${API}/api/v1/wod/cell/${cell}${qs ? `?${qs}` : ""}`, { signal: ctrl.signal })
      .then((r) => {
        if (r.status === 404) { setCellState("missing"); return null; }
        if (!r.ok) throw new Error(String(r.status));
        return r.json();
      })
      .then((j) => { if (j) { setCellData(j as WodCellPayload); setCellState("ok"); } })
      .catch((e) => { if (e?.name !== "AbortError") setCellState("error"); });
    return () => ctrl.abort();
  }, [wantsCell, cell, y0, y1, version, cellAttempt]);

  const retryButton = (onClick: () => void) => (
    <button type="button" onClick={onClick}
      className="text-xs text-cyan-300 border border-cyan-500/40 rounded px-2 py-1 hover:bg-cyan-500/10">
      {t("wodCast.retry")}
    </button>
  );

  const identity = (c: Pick<WodCellCast, "cruise" | "wmo_id" | "platform" | "vehicle">) =>
    [c.cruise ? `${t("wodCast.cruiseShort")} ${c.cruise}` : null, c.wmo_id ? `WMO ${c.wmo_id}` : null, c.platform ?? c.vehicle]
      .filter(Boolean).join(" · ");

  let cellBlock: ReactNode = null;
  if (wantsCell) {
    if (cellState === "loading") cellBlock = <p className="text-white/60 text-xs animate-pulse mb-3">{t("wodCast.cell.loading")}</p>;
    else if (cellState === "missing") cellBlock = <p className="text-white/70 text-xs mb-3" role="status">{t("wodCast.cell.missing")}</p>;
    else if (cellState === "error" || !cellData) {
      cellBlock = (
        <div role="alert" className="mb-3">
          <p className="text-amber-300/90 text-xs mb-2">{t("wodCast.cell.error")}</p>
          {retryButton(() => setCellAttempt((n) => n + 1))}
        </div>
      );
    } else {
      cellBlock = (
        <div className="mb-3" data-testid="wod-cell-list">
          <p className="text-white/80 text-xs mb-1">
            {t("wodCast.cell.summary", { k: cellData.n_casts, from: cellData.year_min ?? "—", to: cellData.year_max ?? "—" })}
          </p>
          <p className="text-white/55 text-[11px] leading-snug mb-2">{t("wodCast.cell.meanNote")}</p>
          <ul className="text-xs max-h-48 overflow-y-auto">
            {cellData.casts.map((c) => (
              <li key={c.cast_id}>
                <button type="button" onClick={() => setShownId(String(c.cast_id))}
                  className={`w-full text-left py-1 border-b border-white/5 hover:bg-white/5 ${shownId === String(c.cast_id) ? "text-cyan-300" : "text-white/80"}`}>
                  <span className="block">
                    {castMoment({ date: c.date, time: null, time_precision: c.time_precision }).date ?? String(c.year)} · {instrumentLabel(c)}
                  </span>
                  <span className="block text-white/55 text-[11px]">
                    {[identity(c), `${c.lat.toFixed(2)}°, ${c.lon.toFixed(2)}°`].filter(Boolean).join(" · ")}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {cellData.truncated && (
            <p className="text-white/55 text-[11px] mt-1">{t("wodCast.cell.truncated", { shown: cellData.casts.length, k: cellData.n_casts })}</p>)}
        </div>
      );
    }
  }

  let body: ReactNode;
  if (castState === "loading") body = <p className="text-white/60 text-xs animate-pulse">{t("wodCast.loading")}</p>;
  else if (castState === "missing") body = <p className="text-white/70 text-sm" role="status">{t("wodCast.missing")}</p>;
  else if (castState === "error" || !cast) {
    body = (
      <div role="alert">
        <p className="text-amber-300/90 text-sm mb-2">{t("wodCast.error")}</p>
        {retryButton(() => setCastAttempt((n) => n + 1))}
      </div>
    );
  } else {
    const varName = t(`wodCast.var.${variable}`, { defaultValue: variable });
    const units = wodUnitsFor(variable);
    const lv = wodLevelsFor(cast.levels, variable);
    const good = goodSamples(lv);
    const pick = depthKnown ? pickedAt(cast, variable, woaDepth) : null;
    const fieldPoints = Object.entries(cast.field?.values ?? {})
      .filter(([, val]) => val !== null && val !== undefined)
      .map(([d, val]) => [Number(d), val as number] as [number, number])
      .sort((a, b) => a[0] - b[0]);
    const fieldHere = depthKnown ? cast.field?.values?.[String(woaDepth)] ?? null : null;
    const when = castMoment(cast);
    const code = VAR[variable]?.code ?? "";
    const srcIndex = CODE_ORDER.indexOf(code);
    const nSrc = srcIndex >= 0 ? cast.n_src?.[srcIndex] : undefined;
    const isFloat = !!cast.wmo_id;
    const header = instrumentLabel(cast) || String(cast.cast_id);
    const realTime = cast.real_time === null || cast.real_time === undefined || cast.real_time === ""
      ? null : typeof cast.real_time === "boolean" ? t(cast.real_time ? "wodCast.realTimeYes" : "wodCast.realTimeNo") : cast.real_time;
    const tableRows = lv.filter(([d]) => d !== null);
    body = (
      <div data-testid="wod-cast-panel">
        <PanelHeader>{header}</PanelHeader>
        <p className="text-white/65 text-xs mb-3">{t("wodCast.productNote", { product: cast.product })}</p>
        {!measured && (
          <p className="text-amber-300/80 text-[11px] leading-snug mb-2" data-testid="wod-unmeasured-note">{t("wodCast.unmeasuredNote")}</p>)}

        {good.length > 0 ? (
          <>
            <GlodapProfileChart samples={good} fieldPoints={fieldPoints}
              picked={pick && pick.depth !== null ? [pick.depth, pick.value] : null}
              units={units} label={varName} depthLabel={t("wodCast.depthAxis")}
              ariaLabel={t("wodCast.chartAria", { variable: varName })} />
            <p className="text-white/60 text-[11px] mb-3">
              {t("wodCast.legend")}{fieldPoints.length > 0 ? ` ${t("wodCast.legendField")}` : ""}
            </p>
          </>
        ) : (
          <p className="text-white/65 text-xs mb-3" data-testid="wod-no-acceptable">{t("wodCast.noAcceptable", { variable: varName })}</p>
        )}

        <Section title={t("wodCast.sectionValues")}>
          {depthKnown ? (
            <Row label={t("wodCast.atDepth", { variable: varName, depth: woaDepth })}
              value={pick
                ? (pick.depth !== null
                  ? t("wodCast.measuredAt", { value: withUnits(pick.value, units), z: fmt(pick.depth) })
                  : withUnits(pick.value, units))
                : t("wodCast.noValueInWindow", { window: wodWindowLabel(woaDepth) })} />
          ) : (
            <p className="text-white/60 text-[11px] mb-1">{t("wodCast.depthNotDrawn", { depth: woaDepth })}</p>)}
          <Row label={t("wodCast.fieldHere", { variable: varName, depth: woaDepth })}
            value={fieldHere !== null && fieldHere !== undefined ? withUnits(fieldHere, units) : t("wodCast.noField")} />
          <p className="text-white/55 text-[11px] leading-snug mt-1">{t("wodCast.fieldNote")}</p>
        </Section>

        <Section title={t("wodCast.sectionCast")}>
          <Row label={t("wodCast.instrument")} value={header} />
          <Row label={t("wodCast.date")} value={momentText(when, {
            none: t("wodCast.dateNone"), year: t("wodCast.yearPrecision"), month: t("wodCast.monthPrecision"), time: t("wodCast.timeNone"),
          })} />
          <Row label={t("wodCast.position")} value={`${cast.lat.toFixed(4)}°, ${cast.lon.toFixed(4)}°`} />
          {cast.cruise && <Row label={t("wodCast.cruise")} value={cast.cruise} />}
          {cast.orig_cruise && cast.orig_cruise !== cast.cruise && <Row label={t("wodCast.origCruise")} value={cast.orig_cruise} />}
          {cast.platform && <Row label={t("wodCast.platform")} value={cast.platform} />}
          {cast.vehicle && <Row label={t("wodCast.vehicle")} value={cast.vehicle} />}
          {isFloat && <Row label={t("wodCast.wmo")} value={String(cast.wmo_id)} />}
          {isFloat && realTime && <Row label={t("wodCast.realTime")} value={realTime} />}
          {cast.country && <Row label={t("wodCast.country")} value={cast.country} />}
          {cast.institute && <Row label={t("wodCast.institute")} value={cast.institute} />}
          {cast.project && <Row label={t("wodCast.project")} value={cast.project} />}
          {cast.t_instrument && <Row label={t("wodCast.tInstrument")} value={cast.t_instrument} />}
          {cast.o2_instrument && <Row label={t("wodCast.o2Instrument")} value={cast.o2_instrument} />}
        </Section>

        {tableRows.length > 0 && (
          <details className="mb-3 text-xs" data-testid="wod-level-table">
            <summary className="cursor-pointer text-cyan-300">
              {t("wodCast.levelsSummary", { variable: varName })}
              {nSrc !== undefined && variable !== "nstar" ? ` — ${t("wodCast.levelsShown", { n: tableRows.length, m: nSrc })}` : ""}
            </summary>
            <table className="w-full mt-1">
              <thead>
                <tr className="text-white/55 text-left">
                  <th className="font-normal">{t("wodCast.colDepth")}</th>
                  <th className="font-normal">{t("wodCast.colValue")}</th>
                  <th className="font-normal">{t("wodCast.colFlag")}</th>
                </tr>
              </thead>
              <tbody>
                {tableRows.map(([d, v, f]) => {
                  const meaning = flagMeaning(cast.flag_meanings, variable, f);
                  return (
                    <tr key={`${d}-${f}-${v}`} className={f === GOOD_FLAG ? "text-white/80" : "text-white/50"}>
                      <td>{fmt(d)}</td>
                      <td>{fmt(v)}</td>
                      <td>{meaning ? `${f} — ${meaning}` : String(f)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </details>
        )}

        <Section title={t("wodCast.sectionSource")}>
          <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs mb-2">
            {cast.accession_url && (
              <a href={cast.accession_url} target="_blank" rel="noopener noreferrer" className="text-cyan-300 hover:underline">
                {t("wodCast.accession")} <span aria-hidden="true">↗</span>
              </a>)}
            {cast.source_file_url && (
              <a href={cast.source_file_url} target="_blank" rel="noopener noreferrer" className="text-cyan-300 hover:underline">
                {t("wodCast.sourceFile")} <span aria-hidden="true">↗</span>
              </a>)}
            <a href={cast.source_url} target="_blank" rel="noopener noreferrer" className="text-cyan-300 hover:underline">
              {t("wodCast.wodLink")} <span aria-hidden="true">↗</span>
            </a>
          </div>
          <p className="text-white/55 text-[11px] leading-snug mb-1">{cast.citation}</p>
          <p className="text-white/55 text-[11px] leading-snug mt-2">{cast.licence}</p>
        </Section>
      </div>
    );
  }

  return (
    <>
      {cellBlock}
      {body}
    </>
  );
}
