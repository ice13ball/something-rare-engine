// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { Row, Section, Badge, PanelHeader, ExternalLink, ExternalLinks, SourceAttribution } from "../shared/primitives";
import { sourceLinkFor } from "../../../utils/sourceUrl";

export function DamPanel({ properties: p }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation("panels");
  const raw = String(p.dam_name ?? "").trim();

  // ⛔ `dam_name` does not hold a name. The loaded source is GOODD
  // (GOOD2_dams.shp, 2019), whose only fields are DAM_ID, Count_ID, Latitud and
  // Longitud — its DAM_ID landed in this column. Measured on production
  // 2026-09-10: 38,667 rows, every dam_name a bare sequential integer starting
  // at 1000000, and river / country / height_m / purpose / year_built /
  // volume_mcm 100% NULL because GOODD does not publish them.
  //
  // An internal id shown as a name is worse than an empty field: it looks like
  // data. Labelled as the id it is.
  const isBareId = /^\d+$/.test(raw);
  const name = isBareId ? "" : raw;
  return (
    <>
      <Badge label={t("dam.panelBadge")} color="text-indigo-300 border-indigo-500/40" />
      <PanelHeader>{name || (raw ? t("dam.goodIdHeader", { id: raw }) : "—")}</PanelHeader>
      <Section title={t("dam.detailsSectionTitle")}>
        {isBareId && <Row label={t("dam.goodIdLabel")} value={raw} />}
        {p.river != null && <Row label={t("dam.riverLabel")}       value={String(p.river)} />}
        {p.country != null && <Row label={t("dam.countryLabel")}   value={String(p.country)} />}
        {p.height_m != null && <Row label={t("dam.heightLabel")}   value={`${p.height_m} m`} />}
        {p.purpose != null && <Row label={t("dam.purposeLabel")}   value={String(p.purpose)} />}
        {p.year_built != null && <Row label={t("dam.yearBuiltLabel")} value={String(p.year_built)} />}
        {p.volume_mcm != null && <Row label={t("dam.volumeLabel")} value={`${Number(p.volume_mcm).toLocaleString()} MCM`} />}
      </Section>
      {/* ⛔ Say what this source is, rather than letting six empty rows imply a
          failed fetch. GOODD georeferences dams; it does not describe them. */}
      {isBareId && (
        <p className="text-xs text-white/65 italic mt-1">{t("dam.locationOnlyNote")}</p>
      )}
      <SourceAttribution link={sourceLinkFor("global-dam-watch", p)} />
      <ExternalLinks>
        {/* A Wikipedia search for "1000000 dam" cannot succeed. Offered only
            when there is a real name to search for. */}
        {name && <ExternalLink href={`https://en.wikipedia.org/w/index.php?search=${encodeURIComponent(name + " dam")}`} label="Wikipedia" />}
        <ExternalLink href="https://www.globaldamwatch.org" label="Global Dam Watch" />
      </ExternalLinks>
    </>
  );
}

