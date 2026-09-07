// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { latLonFromProps } from "../shared/format";
import { Row, Section, Badge, PanelHeader, ExternalLink, ExternalLinks, SourceAttribution } from "../shared/primitives";
import { sourceLinkFor } from "../../../utils/sourceUrl";

export function FirePanel({ properties: p }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation("panels");
  const coords = latLonFromProps(p);
  return (
    <>
      <Badge label={t("fire.panelBadge")} color="text-orange-300 border-orange-500/40" />
      <PanelHeader>{t("fire.panelTitle")}</PanelHeader>
      <Section title={t("fire.detailsSectionTitle")}>
        {p.acq_date != null && <Row label={t("fire.dateLabel")}       value={String(p.acq_date)} />}
        {p.confidence != null && <Row label={t("fire.confidenceLabel")} value={String(p.confidence)} />}
        {p.brightness != null && <Row label={t("fire.brightnessLabel")} value={`${Number(p.brightness).toFixed(1)} K`} />}
        {p.frp != null && <Row label={t("fire.frpLabel")}             value={`${Number(p.frp).toFixed(1)} MW`} />}
        {p.instrument != null && <Row label={t("fire.instrumentLabel")} value={String(p.instrument)} />}
      </Section>
      <SourceAttribution link={sourceLinkFor("firms", p)} />
      <ExternalLinks>
        {coords && <ExternalLink href={`https://firms.modaps.eosdis.nasa.gov/map/#d:24hrs;@${coords[1]},${coords[0]},12z`} label="NASA FIRMS map" />}
      </ExternalLinks>
    </>
  );
}

