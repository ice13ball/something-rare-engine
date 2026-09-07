// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { Row, Section, Badge, PanelHeader, ExternalLink, ExternalLinks, SourceAttribution } from "../shared/primitives";
import { sourceLinkFor } from "../../../utils/sourceUrl";

export function WaterRiskPanel({ properties: p }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation("panels");
  const cat = Number(p.w_awr_min_tot_cat ?? -1);
  const riskColors: Record<number, string> = {
    0: "text-green-400", 1: "text-yellow-400", 2: "text-orange-400",
    3: "text-red-400", 4: "text-red-600",
  };
  return (
    <>
      <Badge label={t("waterRisk.panelBadge")} color="text-sky-300 border-sky-500/40" />
      <PanelHeader>{String(p.name_0 ?? "—")}{p.name_1 ? ` — ${p.name_1}` : ""}</PanelHeader>
      <Section title={t("waterRisk.riskSectionTitle")}>
        {p.w_awr_min_tot_label != null && (
          <Row label={t("waterRisk.overallRiskLabel")} value={
            <span className={riskColors[cat] ?? "text-white/70"}>{String(p.w_awr_min_tot_label)}</span>
          } />
        )}
        {p.w_awr_min_tot_score != null && <Row label={t("waterRisk.riskScoreLabel")} value={`${Number(p.w_awr_min_tot_score).toFixed(2)} / 5`} />}
      </Section>
      <Section title={t("waterRisk.keyIndicatorsSectionTitle")}>
        {p.bws_score != null && <Row label={t("waterRisk.waterStressLabel")}    value={`${Number(p.bws_score).toFixed(2)} / 5`} />}
        {p.bws_label != null && <Row label="" value={String(p.bws_label)} />}
        {p.bwd_score != null && <Row label={t("waterRisk.waterDepletionLabel")} value={`${Number(p.bwd_score).toFixed(2)} / 5`} />}
        {p.drr_score != null && <Row label={t("waterRisk.droughtRiskLabel")}    value={`${Number(p.drr_score).toFixed(2)} / 5`} />}
        {p.rfr_score != null && <Row label={t("waterRisk.floodRiskLabel")}      value={`${Number(p.rfr_score).toFixed(2)} / 5`} />}
      </Section>
      {p.area_km2 != null && (
        <Section title={t("waterRisk.geographySectionTitle")}>
          <Row label={t("waterRisk.areaLabel")} value={`${Number(p.area_km2).toLocaleString()} km²`} />
        </Section>
      )}
      <SourceAttribution link={sourceLinkFor("wri-aqueduct", p)} />
      <ExternalLinks>
        <ExternalLink href="https://www.wri.org/applications/aqueduct/water-risk-atlas/" label="WRI Water Risk Atlas" />
      </ExternalLinks>
    </>
  );
}
