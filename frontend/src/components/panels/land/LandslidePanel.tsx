// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { Row, Section, Badge, PanelHeader, ExternalLink, ExternalLinks, SourceAttribution } from "../shared/primitives";
import { sourceLinkFor } from "../../../utils/sourceUrl";

export function LandslidePanel({ properties: p }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation("panels");
  const sourceUrl = p.source ? String(p.source) : null;
  const isUrl = sourceUrl && (sourceUrl.startsWith("http://") || sourceUrl.startsWith("https://"));
  return (
    <>
      <Badge label={t("landslide.panelBadge")} color="text-amber-700 border-amber-800/40" />
      <PanelHeader>{String(p.event_type ?? "Landslide")}</PanelHeader>
      <Section title={t("landslide.detailsSectionTitle")}>
        {p.event_date != null && <Row label={t("landslide.dateLabel")}       value={String(p.event_date)} />}
        {p.country != null && <Row label={t("landslide.countryLabel")}       value={String(p.country)} />}
        {p.location != null && <Row label={t("landslide.locationLabel")}     value={String(p.location)} />}
        {p.trigger != null && <Row label={t("landslide.triggerLabel")}       value={String(p.trigger)} />}
        {p.fatalities != null && Number(p.fatalities) > 0 && <Row label={t("landslide.fatalitiesLabel")} value={String(p.fatalities)} />}
        {sourceUrl && !isUrl && <Row label={t("landslide.sourceLabel")} value={sourceUrl} />}
      </Section>
      <SourceAttribution link={sourceLinkFor("coolr-landslides", p)} />
      <ExternalLinks>
        {isUrl && <ExternalLink href={sourceUrl} label="Source report" />}
        <ExternalLink href="https://coolr.sci.gsfc.nasa.gov" label="NASA COOLR" />
      </ExternalLinks>
    </>
  );
}

