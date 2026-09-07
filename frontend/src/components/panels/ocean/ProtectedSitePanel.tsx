// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { sourceLinkFor } from "../../../utils/sourceUrl";

import { Row, Section, Badge, PanelHeader, BodyText, SourceAttribution } from "../shared/primitives";

export function ProtectedSitePanel({ properties: p }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation("panels");
  return (
    <>
      <Badge label={t("protectedSite.panelBadge")} color="text-emerald-300 border-emerald-500/40" />
      <PanelHeader>{String(p.name ?? p.NAME ?? "—")}</PanelHeader>
      <Section title={t("protectedSite.detailsSectionTitle")}>
        {(p.country ?? p.COUNTRY) != null && <Row label={t("protectedSite.countryLabel")} value={String(p.country ?? p.COUNTRY)} />}
        {p.area_km2 != null && <Row label={t("protectedSite.areaLabel")} value={`${Math.round(Number(p.area_km2)).toLocaleString()} km²`} />}
      </Section>
      <BodyText>{t("protectedSite.body")}</BodyText>
      <SourceAttribution link={sourceLinkFor("unesco-mab", p)} />
    </>
  );
}

