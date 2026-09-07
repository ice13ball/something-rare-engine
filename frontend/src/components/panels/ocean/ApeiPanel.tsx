// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { tEnum } from "../../../utils/translateEnum";
import { sourceLinkFor } from "../../../utils/sourceUrl";

import { Row, Section, Badge, PanelHeader, BodyText, SourceAttribution } from "../shared/primitives";
import { BathymetryConfidenceBlock } from "../shared/chips";

export function ApeiPanel({ properties: p }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation(["panels", "enums"]);
  return (
    <>
      <Badge label={t("apei.panelBadge")} color="text-emerald-300 border-emerald-500/40" />
      <PanelHeader>{String(p.NAME ?? p.Remarks ?? "Area of Particular Environmental Interest")}</PanelHeader>
      <Section title={t("apei.detailsSectionTitle")}>
        {(p.AreaKM2 ?? p.Area_km2 ?? p.Shape__Area) != null && (
          <Row label={t("apei.areaLabel")} value={`${Number(p.AreaKM2 ?? p.Area_km2 ?? p.Shape__Area).toLocaleString()} km²`} />
        )}
        {(p.Status ?? p.STATUS) != null && <Row label={t("apei.statusLabel")} value={tEnum(t, "status", String(p.Status ?? p.STATUS))} />}
      </Section>
      <BodyText>{t("apei.body")}</BodyText>
      {p?.arcgis_id != null && <BathymetryConfidenceBlock featureType="isa_apei" fid={String(p.arcgis_id)} />}
      <SourceAttribution link={sourceLinkFor("isa-apei", p)} />
    </>
  );
}

