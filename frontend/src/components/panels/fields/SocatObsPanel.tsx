// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

/**
 * Click panel for one SOCAT v2026 surface-ocean observation (`/api/v1/socat/obs/{obs_key}`, backend/domains/socat_points.py),
 * and — for a map dot that stands for several observations — the list behind it (`/api/v1/socat/cell/{z}/{x}/{y}/{q}`).
 *
 * ⛔ Missing and broken never share a state: 404 = "no longer in the data (a re-import may drop a cruise)", anything
 * else = unavailable, with a retry. Never an empty panel.
 * ⛔ A value is `null`, never 0: 0 °C and salinity 0 are values, a missing sample is "—".
 * ⛔ The observations are v2026 measurements; the Surface Ocean CO₂ field is a GRIDDED decadal mean (a different
 * product). The panel says so and shows the field's value beside the observation, never in place of it.
 * ⛔ Time is UTC, always, and shown as such.
 */
import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { API } from "../shared/tokens";
import { PanelHeader, Row, Section } from "../shared/primitives";
import { useMapStore } from "../../../store/mapStore";
import { useSocatSelection } from "../../../store/socatSelection";

type Num = number | null;
export type SocatSegment = {
  ord0: number; n_obs: number; index: number; time: string[];
  lon: Num[]; lat: Num[]; fco2_uatm: Num[]; sst_c: Num[]; sal_pss78: Num[]; fco2_flag: number[];
};
export type SocatCruise = {
  expocode: string; platform_name: string | null; dataset_name: string | null; pis: string | string[] | null;
  qc_flag: string; version: string | null; source_doi: string | null; source_reference: string | null;
  metadata_docs: string | null; first_time: string | null; last_time: string | null; n_obs: number;
};
export type SocatObsPayload = {
  obs_key: string; expocode: string; ordinal: number; time: string; lon: number; lat: number;
  fco2_uatm: Num; sst_c: Num; sal_pss78: Num; fco2_src: number | null; fco2_src_note: string; fco2_flag: number;
  segment: SocatSegment; field: { fco2_decadal_uatm: Num }; cruise: SocatCruise;
  citation: string; citations?: string[]; acknowledgement: string; source_url: string; metadata_url: string;
  licence: string; product: string;
};
export type SocatMean = { fco2_uatm: Num; sst_c: Num; sal_pss78: Num };
export type SocatCellPayload = {
  z: number; x: number; y: number; q: number; year: number; version: string;
  n_obs: number; n_cruises: number; mean: { fco2_uatm: Num; sst_c: Num; sal_pss78: Num };
  cruises: { expocode: string; platform_name: string | null; qc_flag: string; n_obs: number; obs_key: string; first_time: string; last_time: string }[];
  cruises_truncated: boolean;
  observations: { obs_key: string; time: string; lon: number; lat: number; fco2_uatm: Num; sst_c: Num; sal_pss78: Num }[];
  observations_truncated: boolean;
};

/** The variable of the Surface CO₂ field -> the observation column and its decimals. Density has no per-observation value: fCO₂ is shown. */
const COLUMN: Record<string, { col: "fco2_uatm" | "sst_c" | "sal_pss78"; decimals: number; units: string }> = {
  fco2: { col: "fco2_uatm", decimals: 1, units: "µatm" },
  sst: { col: "sst_c", decimals: 2, units: "°C" },
  salinity: { col: "sal_pss78", decimals: 2, units: "" },
};
export const socatColumnFor = (variable: string) => COLUMN[variable] ?? COLUMN.fco2;

/** `2020-01-02T03:04:05Z` -> `2020-01-02 03:04:05 UTC` (the server sends UTC, always). */
export function utcLabel(iso: string): string {
  return `${iso.slice(0, 10)} ${iso.slice(11, 19)} UTC`;
}

/** Edge of one cell of the 256x256 grid over a tile of zoom `z`, in metres at the equator (the "~N m" of the cell line). */
export function cellSizeMetres(z: number): number {
  return Math.round(40075016.686 / 2 ** z / 256);
}

/** The segment as a [lon, lat] path, samples without a position dropped. Never crosses the antimeridian (cut by the importer). */
export function segmentPath(seg: Pick<SocatSegment, "lon" | "lat">): [number, number][] {
  const out: [number, number][] = [];
  seg.lon.forEach((lo, i) => {
    const la = seg.lat[i];
    if (lo !== null && lo !== undefined && la !== null && la !== undefined) out.push([lo, la]);
  });
  return out;
}

/** A DOI / handle / URL as a link; `N/A` and empty give null. */
export function sourceDoiUrl(doi: string | null | undefined): string | null {
  const d = (doi ?? "").trim();
  if (!d || /^n\/?a$/i.test(d)) return null;
  if (/^https?:\/\//i.test(d)) return d;
  return `https://doi.org/${d.replace(/^doi:\s*/i, "")}`;
}

/** The NCEI accession link of a cruise: the source reference when it is a URL, else null. */
export function accessionUrl(ref: string | null | undefined): string | null {
  const r = (ref ?? "").trim();
  return /^https?:\/\//i.test(r) ? r : null;
}

const fmt = (v: Num | undefined, decimals: number) => (v === null || v === undefined ? "—" : v.toFixed(decimals));

function Sparkline({ times, values, index, label }: { times: string[]; values: Num[]; index: number; label: string }) {
  const pts: [number, number, number][] = [];
  values.forEach((v, i) => {
    const t = Date.parse(times[i]);
    if (v !== null && v !== undefined && Number.isFinite(t)) pts.push([t, v, i]);
  });
  if (pts.length < 2) return null;
  const W = 300, H = 90, L = 8, R = 8, T = 8, B = 8, dw = W - L - R, dh = H - T - B;
  const t0 = pts[0][0], t1 = pts[pts.length - 1][0];
  const vmin = Math.min(...pts.map((p) => p[1])), vmax = Math.max(...pts.map((p) => p[1]));
  const px = (t: number) => L + (t1 === t0 ? 0 : ((t - t0) / (t1 - t0)) * dw);
  const py = (v: number) => T + dh - (vmax === vmin ? dh / 2 : ((v - vmin) / (vmax - vmin)) * dh);
  const sel = pts.find((p) => p[2] === index);
  return (
    <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} className="block bg-black/40 rounded-md mb-1 border border-white/10"
      role="img" aria-label={label} data-testid="socat-sparkline">
      <polyline points={pts.map((p) => `${px(p[0])},${py(p[1])}`).join(" ")} fill="none" stroke="rgb(125 211 252)" strokeOpacity={0.9} strokeWidth={1.2} />
      {sel && <circle data-testid="socat-sparkline-picked" cx={px(sel[0])} cy={py(sel[1])} r={4} fill="none" stroke="rgb(251 191 36)" strokeWidth={1.6} />}
    </svg>
  );
}

type Load = "loading" | "missing" | "error" | "ok";

export function SocatObsPanel({ obsKey, cell, year, k, lod, lodMean, version }: {
  obsKey: string; cell?: string; year?: number; k?: number; lod?: boolean; lodMean?: SocatMean; version?: string;
}) {
  const { t } = useTranslation("panels");
  const co2Variable = useMapStore((s) => s.co2Variable);
  const col = socatColumnFor(co2Variable);

  // The observation shown: the dot's first one, or the row chosen from the cell list.
  const [shownKey, setShownKey] = useState(obsKey);
  useEffect(() => { setShownKey(obsKey); }, [obsKey]);

  const [obs, setObs] = useState<SocatObsPayload | null>(null);
  const [obsState, setObsState] = useState<Load>("loading");
  const [obsAttempt, setObsAttempt] = useState(0);
  useEffect(() => {
    const ctrl = new AbortController();
    setObsState("loading");
    setObs(null);
    fetch(`${API}/api/v1/socat/obs/${encodeURIComponent(shownKey)}`, { signal: ctrl.signal })
      .then((r) => {
        if (r.status === 404) { setObsState("missing"); return null; }
        if (!r.ok) throw new Error(String(r.status));       // 503 + Retry-After lands here, with every other failure
        return r.json();
      })
      .then((j) => { if (j) { setObs(j as SocatObsPayload); setObsState("ok"); } })
      .catch((e) => { if (e?.name !== "AbortError") setObsState("error"); });
    return () => ctrl.abort();
  }, [shownKey, obsAttempt]);

  // The segment of the shown observation is drawn on the map (Map3D's `socat-selected-segment`); gone with the panel.
  useEffect(() => {
    if (obsState === "ok" && obs) useSocatSelection.getState().setSelection(segmentPath(obs.segment), [obs.lon, obs.lat]);
    else useSocatSelection.getState().setSelection(null, null);
  }, [obs, obsState]);
  useEffect(() => () => useSocatSelection.getState().setSelection(null, null), []);

  // A map dot of several observations (z >= 9 and k > 1) lists them; k == 1 and the LOD tracks go straight to /obs.
  const wantsCell = !lod && !!cell && year !== undefined && (k ?? 1) > 1;
  const [cellData, setCellData] = useState<SocatCellPayload | null>(null);
  const [cellState, setCellState] = useState<Load>("loading");
  const [cellAttempt, setCellAttempt] = useState(0);
  useEffect(() => {
    if (!wantsCell) return;
    const ctrl = new AbortController();
    setCellState("loading");
    setCellData(null);
    const v = version ? `&v=${encodeURIComponent(version)}` : "";
    fetch(`${API}/api/v1/socat/cell/${cell}?year=${year}${v}`, { signal: ctrl.signal })
      .then((r) => {
        if (r.status === 404) { setCellState("missing"); return null; }
        if (!r.ok) throw new Error(String(r.status));
        return r.json();
      })
      .then((j) => { if (j) { setCellData(j as SocatCellPayload); setCellState("ok"); } })
      .catch((e) => { if (e?.name !== "AbortError") setCellState("error"); });
    return () => ctrl.abort();
  }, [wantsCell, cell, year, version, cellAttempt]);

  const retryButton = (onClick: () => void) => (
    <button type="button" onClick={onClick}
      className="text-xs text-cyan-300 border border-cyan-500/40 rounded px-2 py-1 hover:bg-cyan-500/10">
      {t("socatObs.retry")}
    </button>
  );

  const meanText = (v: Num | undefined) => (v === null || v === undefined ? "—" : `${v.toFixed(col.decimals)}${col.units ? ` ${col.units}` : ""}`);

  let cellBlock: ReactNode = null;
  if (wantsCell) {
    if (cellState === "loading") cellBlock = <p className="text-white/60 text-xs animate-pulse mb-3">{t("socatObs.cell.loading")}</p>;
    else if (cellState === "missing") cellBlock = <p className="text-white/70 text-xs mb-3" role="status">{t("socatObs.cell.missing")}</p>;
    else if (cellState === "error" || !cellData) {
      cellBlock = (
        <div role="alert" className="mb-3">
          <p className="text-amber-300/90 text-xs mb-2">{t("socatObs.cell.error")}</p>
          {retryButton(() => setCellAttempt((n) => n + 1))}
        </div>
      );
    } else {
      cellBlock = (
        <div className="mb-3" data-testid="socat-cell-list">
          <p className="text-white/80 text-xs mb-2">
            {t("socatObs.cell.summary", { k: cellData.n_obs, c: cellData.n_cruises, size: cellSizeMetres(cellData.z), year: cellData.year })}
          </p>
          <Row label={t("socatObs.cell.meanLabel", { variable: t(`socatObs.${col.col === "fco2_uatm" ? "fco2" : col.col === "sst_c" ? "sst" : "salinity"}`) })}
            value={meanText(cellData.mean[col.col])} />
          <p className="text-white/55 text-[11px] leading-snug mb-2">{t(co2Variable === "density" ? "socatObs.cell.meanNoteDensity" : "socatObs.cell.meanNote", { k: cellData.n_obs, year: cellData.year })}</p>
          <Section title={t("socatObs.cell.cruises")}>
            <ul className="text-xs">
              {cellData.cruises.map((c) => (
                <li key={c.expocode}>
                  <button type="button" onClick={() => setShownKey(c.obs_key)}
                    className={`w-full text-left py-1 border-b border-white/5 hover:bg-white/5 ${shownKey === c.obs_key ? "text-cyan-300" : "text-white/80"}`}>
                    {c.expocode}{c.platform_name ? ` · ${c.platform_name}` : ""} · {t("socatObs.cell.cruiseObs", { n: c.n_obs })}
                  </button>
                </li>
              ))}
            </ul>
            {cellData.cruises_truncated && (
              <p className="text-white/55 text-[11px] mt-1">{t("socatObs.cell.cruisesTruncated", { shown: cellData.cruises.length, c: cellData.n_cruises })}</p>)}
          </Section>
          <Section title={t("socatObs.cell.observations")}>
            <ul className="text-xs max-h-40 overflow-y-auto">
              {cellData.observations.map((o) => (
                <li key={o.obs_key}>
                  <button type="button" onClick={() => setShownKey(o.obs_key)}
                    className={`w-full flex justify-between gap-3 text-left py-1 border-b border-white/5 hover:bg-white/5 ${shownKey === o.obs_key ? "text-cyan-300" : "text-white/80"}`}>
                    <span>{utcLabel(o.time)}</span>
                    <span>{fmt(o[col.col], col.decimals)}{col.units ? ` ${col.units}` : ""}</span>
                  </button>
                </li>
              ))}
            </ul>
            {cellData.observations_truncated && (
              <p className="text-white/55 text-[11px] mt-1">{t("socatObs.cell.observationsTruncated", { shown: cellData.observations.length, k: cellData.n_obs })}</p>)}
          </Section>
        </div>
      );
    }
  }

  const lodLine = lod ? (
    <div className="mb-3" data-testid="socat-lod-note">
      <p className="text-white/70 text-xs mb-1">{t("socatObs.lod", { k: k ?? 0 })}</p>
      {lodMean && <Row label={t("socatObs.lodMeanLabel", { variable: t(`socatObs.${col.col === "fco2_uatm" ? "fco2" : col.col === "sst_c" ? "sst" : "salinity"}`) })} value={meanText(lodMean[col.col])} />}
    </div>
  ) : null;

  let body: ReactNode;
  if (obsState === "loading") body = <p className="text-white/60 text-xs animate-pulse">{t("socatObs.loading")}</p>;
  else if (obsState === "missing") body = <p className="text-white/70 text-sm" role="status">{t("socatObs.missing")}</p>;
  else if (obsState === "error" || !obs) {
    body = (
      <div role="alert">
        <p className="text-amber-300/90 text-sm mb-2">{t("socatObs.error")}</p>
        {retryButton(() => setObsAttempt((n) => n + 1))}
      </div>
    );
  } else {
    const c = obs.cruise;
    const seg = obs.segment;
    const serie = seg[col.col];
    // Meanings: NCEI accession 0315110 (https://www.ncei.noaa.gov/data/oceans/ncei/ocads/metadata/0315110.html), fetched
    // 2026-10-09: "Data sets are assigned flags of A and B for an estimated accuracy of better than 2 μatm, flag of C
    // (and D) for an accuracy of better than 5 μatm and a flag of E for an accuracy of better than 10 μatm." (en keys socatObs.qcMeaning.*)
    const qcMeaning = t(`socatObs.qcMeaning.${c.qc_flag}`, { defaultValue: "" });
    const pis = Array.isArray(c.pis) ? c.pis.join("; ") : c.pis;
    const doi = sourceDoiUrl(c.source_doi);
    const accession = accessionUrl(c.source_reference);
    const credits = obs.citations && obs.citations.length > 0 ? obs.citations : [obs.citation];
    body = (
      <div data-testid="socat-obs-panel">
        <PanelHeader>{c.platform_name ? `${c.platform_name} · ${c.expocode}` : c.expocode}</PanelHeader>
        <p className="text-white/65 text-xs mb-3">{t("socatObs.productNote")}</p>
        <Section title={t("socatObs.sectionValues")}>
          <Row label={t("socatObs.fco2")} value={`${fmt(obs.fco2_uatm, 1)} µatm`} />
          <Row label={t("socatObs.sst")} value={`${fmt(obs.sst_c, 2)} °C`} />
          <Row label={t("socatObs.salinity")} value={fmt(obs.sal_pss78, 2)} />
          <Row label={t("socatObs.time")} value={utcLabel(obs.time)} />
          <Row label={t("socatObs.position")} value={`${obs.lat.toFixed(4)}°, ${obs.lon.toFixed(4)}°`} />
          <Row label={t("socatObs.fco2Src")} value={obs.fco2_src === null || obs.fco2_src === undefined ? "—" : t("socatObs.fco2SrcValue", { code: obs.fco2_src })} />
        </Section>
        <p className="text-white/55 text-[11px] leading-snug mb-3">{obs.fco2_src_note}</p>
        {lodLine}
        {cellBlock}
        <Section title={t("socatObs.sectionSeries", { variable: t(`socatObs.var.${col.col}`) })}>
          <Sparkline times={seg.time} values={serie} index={seg.index} label={t(`socatObs.var.${col.col}`)} />
          <p className="text-white/55 text-[11px] mb-1">{t("socatObs.seriesNote", { n: seg.n_obs })}</p>
        </Section>
        <Section title={t("socatObs.sectionField")}>
          <Row label={t("socatObs.fieldLabel")}
            value={obs.field?.fco2_decadal_uatm === null || obs.field?.fco2_decadal_uatm === undefined
              ? t("socatObs.fieldNone") : `${obs.field.fco2_decadal_uatm.toFixed(1)} µatm`} />
          <p className="text-white/55 text-[11px] leading-snug mt-1">{t("socatObs.fieldNote")}</p>
        </Section>
        <Section title={t("socatObs.sectionCruise")}>
          <Row label={t("socatObs.expocode")} value={c.expocode} />
          {c.platform_name && <Row label={t("socatObs.platform")} value={c.platform_name} />}
          {pis && <Row label={t("socatObs.pis")} value={pis} />}
          <Row label={t("socatObs.qc")} value={qcMeaning ? `${c.qc_flag} — ${qcMeaning}` : c.qc_flag} />
          {c.version && <Row label={t("socatObs.version")} value={c.version} />}
        </Section>
        <p className="text-white/55 text-[11px] leading-snug mb-3">{t("socatObs.qcNote")}</p>
        <Section title={t("socatObs.sectionSource")}>
          <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs mb-2">
            <a href={obs.source_url} target="_blank" rel="noopener noreferrer" className="text-cyan-300 hover:underline">
              {t("socatObs.socatLink")} <span aria-hidden="true">↗</span>
            </a>
            {doi && (
              <a href={doi} target="_blank" rel="noopener noreferrer" className="text-cyan-300 hover:underline">
                {t("socatObs.sourceDoi")} <span aria-hidden="true">↗</span>
              </a>)}
            {accession && (
              <a href={accession} target="_blank" rel="noopener noreferrer" className="text-cyan-300 hover:underline">
                {t("socatObs.accession")} <span aria-hidden="true">↗</span>
              </a>)}
          </div>
          {credits.map((cr) => <p key={cr} className="text-white/55 text-[11px] leading-snug mb-1">{cr}</p>)}
          <p className="text-white/55 text-[11px] leading-snug mt-2">{obs.acknowledgement}</p>
        </Section>
      </div>
    );
  }

  return (
    <>
      {obsState !== "ok" && lodLine}
      {obsState !== "ok" && cellBlock}
      {body}
    </>
  );
}
