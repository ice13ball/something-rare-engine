// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { sourceLinkFor } from "../../../utils/sourceUrl";

import { Row, Section, Badge, PanelHeader, BodyText, SourceAttribution } from "../shared/primitives";

export function EezPanel({ properties: p }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation("panels");
  return (
    <>
      <Badge label={t("eez.panelBadge")} color="text-yellow-300 border-yellow-500/40" />
      <PanelHeader>{String(p.geoname ?? p.GEONAME ?? "—")}</PanelHeader>
      <Section title={t("eez.detailsSectionTitle")}>
        {(p.sovereign1 ?? p.SOVEREIGN1) != null && <Row label={t("eez.sovereignStateLabel")} value={String(p.sovereign1 ?? p.SOVEREIGN1)} />}
        {(p.iso_ter1 ?? p.ISO_TER1) != null && <Row label={t("eez.isoCodeLabel")} value={String(p.iso_ter1 ?? p.ISO_TER1)} />}
        {p.area_km2 != null && <Row label={t("eez.areaLabel")} value={`${Math.round(Number(p.area_km2)).toLocaleString()} km²`} />}
      </Section>
      <BodyText>{t("eez.body")}</BodyText>
      <SourceAttribution link={sourceLinkFor("marineregions-eez", p)} />
    </>
  );
}

