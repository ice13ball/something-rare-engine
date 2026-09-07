// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";

import {
  Row, Section, Badge, PanelHeader,
} from "../shared/primitives";
import { T } from "../shared/tokens";

// ── SIOS time-series chart ────────────────────────────────────────────────────
function SiosTimeSeriesChart({ series, title, units }: {
  series: [number, number][];
  title: string;
  units: string;
}) {
  const sorted = [...series].sort((a, b) => a[0] - b[0]);
  const times  = sorted.map(([t]) => t);
  const vals   = sorted.map(([, v]) => v);

  const tMin = times[0], tMax = times[times.length - 1];
  const tRange = Math.max(tMax - tMin, 1);

  const vMin = Math.min(...vals), vMax = Math.max(...vals);
  const vRange = Math.max(vMax - vMin, 1);
  const vPad = vRange * 0.05;
  const vLo = vMin - vPad, vHi = vMax + vPad, vSpan = vHi - vLo;

  const W = 300, H = 175, PAD_L = 50, PAD_R = 14, PAD_T = 16, PAD_B = 40;
  const drawW = W - PAD_L - PAD_R;
  const drawH = H - PAD_T - PAD_B;

  const px = (t: number) => PAD_L + ((t - tMin) / tRange) * drawW;
  const py = (v: number) => PAD_T + drawH - ((v - vLo) / vSpan) * drawH;

  const fmtT = (ms: number) => new Date(ms).toISOString().slice(0, 7); // YYYY-MM
  const fmtV = (v: number) => Math.abs(v) >= 100 ? Math.round(v).toString() : v.toFixed(1);

  const points = sorted.map(([t, v]) => `${px(t).toFixed(1)},${py(v).toFixed(1)}`).join(" ");
  const midT = (tMin + tMax) / 2;
  const midV = (vMin + vMax) / 2;

  return (
    <div>
      {title && <p className="text-[11px] text-white/65 mb-1 truncate">{title}</p>}
      <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet"
        className="block bg-black/40 rounded-md mb-2 border border-white/10">
        <line x1={PAD_L} y1={PAD_T} x2={PAD_L} y2={PAD_T + drawH} stroke="white" strokeOpacity={0.18} strokeWidth={0.8} />
        <line x1={PAD_L} y1={PAD_T + drawH} x2={PAD_L + drawW} y2={PAD_T + drawH} stroke="white" strokeOpacity={0.18} strokeWidth={0.8} />
        {[vMin, midV, vMax].map((v, i) => {
          const y = py(v);
          return (
            <g key={`y${i}`}>
              <line x1={PAD_L} y1={y} x2={PAD_L + drawW} y2={y} stroke="white" strokeOpacity={0.06} strokeWidth={0.6} />
              <line x1={PAD_L - 4} y1={y} x2={PAD_L} y2={y} stroke="white" strokeOpacity={0.35} strokeWidth={0.8} />
              <text x={PAD_L - 7} y={y + 3} textAnchor="end" fill="rgba(255,255,255,0.55)" fontSize="9">{fmtV(v)}</text>
            </g>
          );
        })}
        {[tMin, midT, tMax].map((t, i) => {
          const x = px(t);
          return (
            <g key={`x${i}`}>
              <line x1={x} y1={PAD_T + drawH} x2={x} y2={PAD_T + drawH + 4} stroke="white" strokeOpacity={0.35} strokeWidth={0.8} />
              <text x={x} y={PAD_T + drawH + 13} textAnchor="middle" fill="rgba(255,255,255,0.55)" fontSize="8">{fmtT(t)}</text>
            </g>
          );
        })}
        {units && (
          <text transform={`translate(11 ${PAD_T + drawH / 2}) rotate(-90)`} textAnchor="middle" fill="rgba(255,255,255,0.5)" fontSize="9">{units}</text>
        )}
        <polyline points={points} fill="none" stroke="rgb(125 211 252)" strokeOpacity={0.9} strokeWidth={1.6} strokeLinejoin="round" />
      </svg>
    </div>
  );
}

// ── SIOS Svalbard ─────────────────────────────────────────────────────────────
export function SiosPanel({ properties: p }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation("panels");

  const title        = String(p.title        ?? "SIOS Dataset");
  const platformLong = String(p.platform_long ?? "");
  const platformUrl  = p.platform_url ? String(p.platform_url) : null;
  const institution  = p.institution ? String(p.institution) : null;
  const piName       = p.pi_name     ? String(p.pi_name)     : null;
  const license      = p.license     ? String(p.license)     : null;
  const licenseUrl   = p.license_url ? String(p.license_url) : null;
  const timeStart    = p.time_start  ? String(p.time_start).slice(0, 10) : null;
  const timeEnd      = p.time_end    ? String(p.time_end).slice(0, 10)   : null;
  const keywords     = Array.isArray(p.keywords) ? (p.keywords as string[]) : [];
  const activityType = p.activity_type ? String(p.activity_type) : null;
  const isoTopic     = p.iso_topic    ? String(p.iso_topic)    : null;
  const abstract     = p.abstract     ? String(p.abstract)     : null;

  // Data access URLs (each rendered only when present)
  const urlOpendap  = p.url_opendap  ? String(p.url_opendap)  : null;
  const urlHttp     = p.url_http     ? String(p.url_http)      : null;
  const urlWms      = p.url_wms      ? String(p.url_wms)       : null;
  const urlLanding  = p.url_landing  ? String(p.url_landing)   : null;
  const hasLinks    = !!(urlOpendap || urlHttp || urlWms || urlLanding);

  // OPeNDAP time-series (populated by the backend when the dataset has a fetchable variable)
  const series         = Array.isArray(p.series) ? (p.series as [number, number][]) : null;
  const seriesVar      = p.series_var       ? String(p.series_var)       : null;
  const seriesUnits    = p.series_units     ? String(p.series_units)     : null;
  const seriesLongName = p.series_long_name ? String(p.series_long_name) : null;
  const hasChart       = series !== null && series.length >= 2;

  // Solid numbers derived from the series (latest reading + min/max/mean).
  const seriesStats = hasChart
    ? (() => {
        const vals = series!.map((d) => d[1]);
        const n = vals.length;
        const mean = vals.reduce((a, b) => a + b, 0) / n;
        const [lastT, lastV] = series![n - 1];
        return { n, mean, min: Math.min(...vals), max: Math.max(...vals), lastT, lastV };
      })()
    : null;
  const fmtNum = (x: number) =>
    !Number.isFinite(x) ? "—" : Math.abs(x) >= 100 || Number.isInteger(x) ? x.toFixed(0) : x.toFixed(2);
  const fmtDay = (ms: number) => new Date(ms).toISOString().slice(0, 10);
  const withUnit = (x: number) => `${fmtNum(x)}${seriesUnits ? " " + seriesUnits : ""}`;

  return (
    <>
      <Badge
        label={t("siosSvalbard.panelBadge")}
        color="text-cyan-300 border-cyan-500/40"
      />
      <PanelHeader>{title}</PanelHeader>

      <Section title={t("siosSvalbard.platformSectionTitle")}>
        {platformLong && (
          <div className="py-1.5 border-b border-white/5">
            <span className={T.rowLabel}>{t("siosSvalbard.platformLabel")}</span>{" "}
            {platformUrl ? (
              <a href={platformUrl} target="_blank" rel="noreferrer" className="text-cyan-400 text-xs underline break-all">
                {platformLong}
              </a>
            ) : (
              <span className={T.rowValue}>{platformLong}</span>
            )}
          </div>
        )}
        {institution && <Row label={t("siosSvalbard.institutionLabel")} value={institution} />}
        {piName      && <Row label={t("siosSvalbard.piLabel")}          value={piName} />}
        {activityType && <Row label={t("siosSvalbard.activityLabel")}   value={activityType} />}
        {isoTopic    && <Row label={t("siosSvalbard.isoTopicLabel")}    value={isoTopic} />}
      </Section>

      {(timeStart || timeEnd) && (
        <Section title={t("siosSvalbard.timeSectionTitle")}>
          <Row
            label={t("siosSvalbard.timeSpanLabel")}
            value={[timeStart, timeEnd].filter(Boolean).join(" – ") || "—"}
          />
        </Section>
      )}

      {keywords.length > 0 && (
        <Section title={t("siosSvalbard.variablesSectionTitle")}>
          <div className="flex flex-wrap gap-1 mt-1">
            {keywords.map((kw) => (
              <span key={kw} className="text-[11px] bg-white/10 rounded px-1.5 py-0.5 text-white/80">
                {kw}
              </span>
            ))}
          </div>
        </Section>
      )}

      {abstract && (
        <Section title={t("siosSvalbard.abstractSectionTitle")}>
          <p className="text-white/70 text-xs leading-relaxed line-clamp-5">{abstract}</p>
        </Section>
      )}

      {hasChart && (
        <Section title={t("siosSvalbard.measurementsSectionTitle")}>
          <SiosTimeSeriesChart
            series={series!}
            title={seriesLongName ?? seriesVar ?? ""}
            units={seriesUnits ?? ""}
          />
          {seriesStats && (
            <div className="mt-2">
              <Row label={t("siosSvalbard.statLatest")} value={`${withUnit(seriesStats.lastV)} (${fmtDay(seriesStats.lastT)})`} />
              <Row label={t("siosSvalbard.statMean")}   value={withUnit(seriesStats.mean)} />
              <Row label={t("siosSvalbard.statMin")}    value={withUnit(seriesStats.min)} />
              <Row label={t("siosSvalbard.statMax")}    value={withUnit(seriesStats.max)} />
              <Row label={t("siosSvalbard.statSamples")} value={String(seriesStats.n)} />
            </div>
          )}
        </Section>
      )}

      {hasLinks && (
        <Section title={t("siosSvalbard.accessSectionTitle")}>
          {urlLanding && (
            <a href={urlLanding} target="_blank" rel="noreferrer" className="block text-cyan-400 text-xs underline mb-1">
              {t("siosSvalbard.landingLink")}
            </a>
          )}
          {urlOpendap && (
            <a href={`${urlOpendap}.html`} target="_blank" rel="noreferrer" className="block text-cyan-400 text-xs underline mb-1">
              {t("siosSvalbard.opendapLink")}
            </a>
          )}
          {urlHttp && (
            <a href={urlHttp} target="_blank" rel="noreferrer" className="block text-cyan-400 text-xs underline mb-1">
              {t("siosSvalbard.httpLink")}
            </a>
          )}
          {urlWms && (
            <a href={urlWms} target="_blank" rel="noreferrer" className="block text-cyan-400 text-xs underline mb-1">
              {t("siosSvalbard.wmsLink")}
            </a>
          )}
        </Section>
      )}

      {license && (
        <Section title={t("siosSvalbard.licenseLabel")}>
          {licenseUrl ? (
            <a href={licenseUrl} target="_blank" rel="noreferrer" className="text-cyan-400 text-xs underline">
              {license}
            </a>
          ) : (
            <span className="text-white/70 text-xs">{license}</span>
          )}
        </Section>
      )}

      <p className="text-white/50 text-[11px] mt-3">
        {t("siosSvalbard.provenanceLine")}
      </p>
    </>
  );
}
