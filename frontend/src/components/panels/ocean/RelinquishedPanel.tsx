// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { sourceLinkFor } from "../../../utils/sourceUrl";
import { tEnum } from "../../../utils/translateEnum";

import { Row, Section, Badge, PanelHeader, BodyText, SourceAttribution } from "../shared/primitives";
import { BathymetryConfidenceBlock } from "../shared/chips";

export function RelinquishedPanel({ properties: p }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation(["panels", "enums"]);
  return (
    <>
      <Badge label={t("relinquished.panelBadge")} color="text-rose-300 border-rose-500/40" />
      <PanelHeader>{String(p.ContractID ?? p.isa_id ?? t("relinquished.unknownFallback"))}</PanelHeader>
      <Section title={t("relinquished.detailsSectionTitle")}>
        {p.contractor_name != null && <Row label={t("relinquished.relinquishedByLabel")} value={String(p.contractor_name)} />}
        {(p.AreaKM2 ?? p.area_km2) != null && <Row label={t("relinquished.areaLabel")} value={`${Number(p.AreaKM2 ?? p.area_km2).toLocaleString()} km²`} />}
        <Row label={t("relinquished.statusLabel")} value="Inactive" />
        {(p.AreaType ?? p.resource_type) != null && <Row label={t("relinquished.typeLabel")} value={tEnum(t, "resourceType", String(p.AreaType ?? p.resource_type))} />}
      </Section>
      <BodyText>{t("relinquished.body")}</BodyText>
      {p?.arcgis_id != null && <BathymetryConfidenceBlock featureType="isa_relinquished" fid={String(p.arcgis_id)} />}
      <SourceAttribution link={sourceLinkFor("isa-relinquished", p)} />
    </>
  );
}

