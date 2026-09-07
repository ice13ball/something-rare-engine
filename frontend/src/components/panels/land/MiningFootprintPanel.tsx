// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { latLonFromProps } from "../shared/format";
import { Row, Section, Badge, PanelHeader, ExternalLink, ExternalLinks, SourceAttribution } from "../shared/primitives";
import { sourceLinkFor } from "../../../utils/sourceUrl";

export function MiningFootprintPanel({ properties: p }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation("panels");
  const coords = latLonFromProps(p);
  const ftype = String(p.ftype ?? "Mine Site");
  const country = p.country != null ? String(p.country) : null;
  return (
    <>
      <Badge label={t("miningFootprint.panelBadge")} color="text-red-300 border-red-500/40" />
      <PanelHeader>{ftype}</PanelHeader>
      <Section title={t("miningFootprint.detailsSectionTitle")}>
        {country != null && <Row label={t("miningFootprint.countryLabel")}     value={country} />}
        {p.ftype != null && <Row label={t("miningFootprint.featureTypeLabel")} value={ftype} />}
        {p.area_km2 != null && <Row label={t("miningFootprint.areaLabel")}     value={`${Number(p.area_km2).toLocaleString()} km²`} />}
        {p.source != null && <Row label={t("miningFootprint.sourceLabel")}     value={String(p.source)} />}
      </Section>
      <SourceAttribution link={sourceLinkFor("maus-mining-footprint", p)} />
      <ExternalLinks>
        {coords && <ExternalLink href={`https://www.google.com/maps/@${coords[0]},${coords[1]},2000m/data=!3m1!1e3`} label="Satellite view" />}
        {country != null && <ExternalLink href={`https://www.google.com/search?q=${encodeURIComponent(`${ftype} mining ${country}`)}`} label="Search online" />}
        {country != null && <ExternalLink href={`https://en.wikipedia.org/w/index.php?search=${encodeURIComponent(`${ftype} mining ${country}`)}`} label="Wikipedia" />}
      </ExternalLinks>
    </>
  );
}
