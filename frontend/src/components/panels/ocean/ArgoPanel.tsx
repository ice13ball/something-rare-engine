// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useMapStore } from "../../../store/mapStore";
import { analytics } from "../../../utils/analytics";
import { oxygenThreshold, phThreshold, oxygenExpected, phExpected, phImplausible } from "../../../utils/argoAlarms";
import { sourceLinkFor } from "../../../utils/sourceUrl";

import { API, T } from "../shared/tokens";
import { fmtDate, latLonFromProps } from "../shared/format";
import { Row, Section, PanelHeader, Subtitle, BodyText, WarningBanner, SourceAttribution, InfoHint } from "../shared/primitives";
import { QcChip, SensorFaultChip, SeafloorDepthRow } from "../shared/chips";
import { argoQcNote, WoaSections } from "./shared";

export function ArgoPanel({ properties }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation("panels");
  const p = properties;
  const fmtN = (v: unknown, d = 2, unit = "") =>
    v == null ? "—" : `${Number(v).toFixed(d)}${unit}`;

  const { tracePlume } = useMapStore();
  const [tracing, setTracing] = useState(false);

  const handleTrace = async () => {
    if (!tracePlume) return;
    setTracing(true);
    const platformId = String(p.platform_id ?? p.platform_number ?? "");
    analytics.trackEvent("trace_plume", { platform_id: platformId });
    await tracePlume(platformId);
    setTracing(false);
  };

  // Anomaly detection helpers
  const depth = (p.max_depth_m as number | null) ?? null;

  const isO2Anomaly = p.oxygen_umol_kg != null && Number(p.oxygen_umol_kg) < oxygenThreshold(depth);
  const isPhFault = phImplausible(p.ph as number | null | undefined);
  const isPhAnomaly = !isPhFault && p.ph != null && Number(p.ph) < phThreshold(depth);
  const o2Hint = t("argo.oxygenHint", { threshold: oxygenThreshold(depth), depth: depth != null ? Math.round(depth) : "—" });
  const phHint = t("argo.phHint", { threshold: phThreshold(depth).toFixed(2) });
  const anomalyValue = (text: string, expected: string | null) => (
    <span>
      <span className="text-red-400 font-medium">{text}</span>
      {expected && <span className="text-white/60 text-xs ml-1">expected {expected}</span>}
    </span>
  );

  return (
    <>
      <PanelHeader>{t("argo.panelTitle")}</PanelHeader>
      <Subtitle className="text-cyan-400 mb-4 font-mono">{String(p.platform_id ?? p.platform_number ?? "—")}</Subtitle>

      <Section title={t("argo.profileSectionTitle")}>
        <Row label={t("argo.profileIdLabel")} value={String(p.profile_id ?? "—")} />
        <Row label={t("argo.dateLabel")}       value={p.profile_date ? fmtDate(String(p.profile_date)) : "—"} />
        <Row label={t("argo.maxDepthLabel")}   value={fmtN(p.max_depth_m, 0, " m")} />
        {(() => {
          const c = latLonFromProps(p);
          return c && <SeafloorDepthRow lat={c[0]} lon={c[1]} />;
        })()}
      </Section>

      <Section title={t("argo.oceanPropertiesSectionTitle")}>
        <Row label={t("argo.surfaceTempLabel")}     value={fmtN(p.surface_temp_c, 2, " °C")} />
        <Row label={t("argo.surfaceSalinityLabel")} value={fmtN(p.surface_salinity, 3, " PSU")} />
        <Row label={t("argo.deepTempLabel")}        value={<span>{fmtN(p.deep_temp_c, 2, " °C")}<QcChip qc={p.temp_qc} /></span>} />
        <Row label={t("argo.deepSalinityLabel")}    value={<span>{fmtN(p.deep_salinity, 3, " PSU")}<QcChip qc={p.sal_qc} /></span>} />
        <Row label={t("argo.deepPressureLabel")}    value={fmtN(p.deep_pressure_m, 0, " dbar")} />
        {p.oxygen_umol_kg != null && <Row label={<>{t("argo.oxygenLabel")}<InfoHint text={o2Hint} /></>} value={<span>{isO2Anomaly
          ? anomalyValue(fmtN(p.oxygen_umol_kg, 1, " µmol/kg"), oxygenExpected(depth))
          : fmtN(p.oxygen_umol_kg, 1, " µmol/kg")}<QcChip qc={p.oxygen_qc} /></span>} />}
        {p.ph != null && <Row label={<>{t("argo.phLabel")}<InfoHint text={phHint} /></>} value={<span>{isPhFault
          ? <span className="text-red-400 font-medium line-through decoration-red-400/40">{fmtN(p.ph, 3)}</span>
          : isPhAnomaly
            ? anomalyValue(fmtN(p.ph, 3), phExpected(depth))
            : fmtN(p.ph, 3)}{isPhFault
              ? <SensorFaultChip label={t("argo.sensorFaultChip")} />
              : <QcChip qc={p.ph_qc} />}</span>} />}
      </Section>

      <WoaSections p={p} t={t} />

      {argoQcNote(p, t) && (
        <WarningBanner color="orange">{argoQcNote(p, t)}</WarningBanner>
      )}

      {p.near_mining && (
        <WarningBanner color="red">
          {t("argo.nearMiningWarning")}{p.mining_zone ? `: ${p.mining_zone}` : ""}
          {p.mining_dist_km != null ? ` · ${fmtN(p.mining_dist_km, 0, " km")}` : ""}
        </WarningBanner>
      )}

      <div className="mt-2">
        <button
          onClick={handleTrace}
          disabled={tracing}
          className="w-full py-2 text-[14px] rounded-lg bg-white/[0.06] border border-white/15 text-white/85 hover:bg-white/10 hover:text-white/95 transition-colors disabled:opacity-40"
        >
          {tracing ? t("argo.tracingPlumesButton") : t("argo.trackPlumesButton")}
        </button>
        {!!(p.platform_id ?? p.platform_number) && (
          <button
            onClick={() => {
              const pid = String(p.platform_id ?? p.platform_number);
              const { startReportJob, reportJobs } = useMapStore.getState();
              if (reportJobs.some(j => j.platformId === pid && j.status === "generating")) return;
              startReportJob(pid);
              const ctrl = new AbortController();
              setTimeout(() => ctrl.abort(), 120_000);
              fetch(`${API}/api/v1/reports/impact`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ platform_id: pid }),
                signal: ctrl.signal,
              }).then(r => {
                if (!r.ok) useMapStore.getState().updateReportJob(pid, "failed", `Server ${r.status}`);
              }).catch(e => {
                const msg = e?.name === "AbortError" ? "Request timed out (120s) — backend may be under load" : "Network error — check connection";
                useMapStore.getState().updateReportJob(pid, "failed", msg);
              });
            }}
            className="w-full mt-2 text-center py-1.5 px-3 text-[14px] rounded-lg bg-white/[0.06] border border-white/15 text-white/85 hover:bg-white/10 hover:text-white/95 transition-colors"
          >
            {t("argo.generateReportButton")}
          </button>
        )}
      </div>

      <div className="mt-3 pt-2 border-t border-white/5">
        <p className={T.sectionH}>{t("argo.aboutSectionTitle")}</p>
        <BodyText>{t("argo.aboutBody")}</BodyText>
      </div>
      <SourceAttribution link={sourceLinkFor("argo-float", p)} />
    </>
  );
}

