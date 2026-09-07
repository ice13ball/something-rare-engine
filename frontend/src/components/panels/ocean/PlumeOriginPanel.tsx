// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { sourceLinkFor } from "../../../utils/sourceUrl";

import { fmtDate } from "../shared/format";
import { Row, Section, PanelHeader, Subtitle, SourceAttribution } from "../shared/primitives";

export function PlumeOriginPanel({ properties: p }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation("panels");
  return (
    <>
      <PanelHeader>{t("plume.panelTitle")}</PanelHeader>
      <Subtitle className="text-orange-400 mb-4 font-mono">{String(p.profile_id ?? "—")}</Subtitle>
      <Section title={t("plume.backtrackSectionTitle")}>
        <Row label={t("plume.platformLabel")}   value={String(p.platform_id ?? "—")} />
        <Row label={t("plume.dateLabel")}        value={p.profile_date ? fmtDate(String(p.profile_date)) : "—"} />
        <Row label={t("plume.stepsLabel")}       value={String(p.steps_completed ?? "—")} />
        <Row label={t("plume.speedLabel")}       value={p.speed_cms != null ? `${Number(p.speed_cms).toFixed(1)} cm/s` : "—"} />
        <Row label={t("plume.contractorLabel")}  value={String(p.contractor_name ?? t("plume.unknownContractor"))} />
      </Section>
      <Section title={t("plume.coordinatesSectionTitle")}>
        <Row label={t("plume.lonLabel")} value={p.origin_lon != null ? `${Number(p.origin_lon).toFixed(5)}°` : "—"} />
        <Row label={t("plume.latLabel")} value={p.origin_lat != null ? `${Number(p.origin_lat).toFixed(5)}°` : "—"} />
      </Section>
      <SourceAttribution link={sourceLinkFor("cmems-plume", p)} />
    </>
  );
}

