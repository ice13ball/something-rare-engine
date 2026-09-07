// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { sourceLinkFor } from "../../../utils/sourceUrl";

import { Row, Section, Badge, PanelHeader, SourceAttribution } from "../shared/primitives";

export function NoaaCablePanel({ properties: p }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation("panels");
  const cableSystem = String(p.cable_system ?? p.short_name ?? "—");
  const owner       = p.owner       != null ? String(p.owner)       : null;
  const status      = p.status      != null ? String(p.status)      : null;
  const region      = p.region      != null ? String(p.region)      : null;
  const shortName   = p.short_name  != null ? String(p.short_name)  : null;
  return (
    <>
      <Badge label={t("noaaCable.panelBadge")} color="text-amber-300 border-amber-500/40" />
      <PanelHeader>{cableSystem}</PanelHeader>
      <Section title={t("noaaCable.detailsSectionTitle")}>
        {shortName != null && <Row label={t("noaaCable.shortNameLabel")} value={shortName} />}
        {owner     != null && <Row label={t("noaaCable.ownerLabel")}     value={owner} />}
        {status    != null && <Row label={t("noaaCable.statusLabel")}    value={<span className="capitalize">{status}</span>} />}
        {region    != null && <Row label={t("noaaCable.regionLabel")}    value={region} />}
      </Section>
      <SourceAttribution link={sourceLinkFor("noaa-cables", p)} />
    </>
  );
}

