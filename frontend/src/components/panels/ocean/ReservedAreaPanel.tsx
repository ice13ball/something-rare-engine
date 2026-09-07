// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { tEnum } from "../../../utils/translateEnum";
import { sourceLinkFor } from "../../../utils/sourceUrl";

import { Row, Section, Badge, PanelHeader, BodyText, SourceAttribution } from "../shared/primitives";
import { BathymetryConfidenceBlock } from "../shared/chips";

export function ReservedAreaPanel({ properties: p }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation(["panels", "enums"]);
  return (
    <>
      <Badge label={t("reservedArea.panelBadge")} color="text-emerald-300 border-emerald-500/40" />
      <PanelHeader>{String(p.ContractID ?? p.isa_id ?? "Reserved Area")}</PanelHeader>
      <Section title={t("reservedArea.detailsSectionTitle")}>
        {(p.AreaKM2 ?? p.area_km2) != null && <Row label={t("reservedArea.areaLabel")} value={`${Number(p.AreaKM2 ?? p.area_km2).toLocaleString()} km²`} />}
        {(p.Status ?? p.STATUS) != null && <Row label={t("reservedArea.statusLabel")} value={tEnum(t, "status", String(p.Status ?? p.STATUS))} />}
        {(p.AreaType) != null && <Row label={t("reservedArea.typeLabel")} value={tEnum(t, "resourceType", String(p.AreaType))} />}
      </Section>
      <BodyText>{t("reservedArea.body")}</BodyText>
      {p?.arcgis_id != null && <BathymetryConfidenceBlock featureType="isa_reserved" fid={String(p.arcgis_id)} />}
      <SourceAttribution link={sourceLinkFor("isa-reserved", p)} />
    </>
  );
}

