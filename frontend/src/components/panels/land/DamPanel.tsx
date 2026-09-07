// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { Row, Section, Badge, PanelHeader, ExternalLink, ExternalLinks, SourceAttribution } from "../shared/primitives";
import { sourceLinkFor } from "../../../utils/sourceUrl";

export function DamPanel({ properties: p }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation("panels");
  const name = String(p.dam_name ?? "");
  return (
    <>
      <Badge label={t("dam.panelBadge")} color="text-indigo-300 border-indigo-500/40" />
      <PanelHeader>{name || "—"}</PanelHeader>
      <Section title={t("dam.detailsSectionTitle")}>
        {p.river != null && <Row label={t("dam.riverLabel")}       value={String(p.river)} />}
        {p.country != null && <Row label={t("dam.countryLabel")}   value={String(p.country)} />}
        {p.height_m != null && <Row label={t("dam.heightLabel")}   value={`${p.height_m} m`} />}
        {p.purpose != null && <Row label={t("dam.purposeLabel")}   value={String(p.purpose)} />}
        {p.year_built != null && <Row label={t("dam.yearBuiltLabel")} value={String(p.year_built)} />}
        {p.volume_mcm != null && <Row label={t("dam.volumeLabel")} value={`${Number(p.volume_mcm).toLocaleString()} MCM`} />}
      </Section>
      <SourceAttribution link={sourceLinkFor("global-dam-watch", p)} />
      <ExternalLinks>
        {name && <ExternalLink href={`https://en.wikipedia.org/w/index.php?search=${encodeURIComponent(name + " dam")}`} label="Wikipedia" />}
        <ExternalLink href="https://www.globaldamwatch.org" label="Global Dam Watch" />
      </ExternalLinks>
    </>
  );
}

