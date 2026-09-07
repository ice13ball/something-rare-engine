// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { sourceLinkFor } from "../../../utils/sourceUrl";

import { Row, Section, Badge, PanelHeader, SourceAttribution } from "../shared/primitives";

export function PortPanel({ properties: p }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation("panels");
  return (
    <>
      <Badge label={t("port.panelBadge")} color="text-blue-300 border-blue-500/40" />
      <PanelHeader>{String(p.city ?? "—")}</PanelHeader>
      <Section title={t("port.detailsSectionTitle")}>
        {p.state != null && <Row label={t("port.stateLabel")}   value={String(p.state)} />}
        {p.country != null && <Row label={t("port.countryLabel")} value={String(p.country)} />}
      </Section>
      <SourceAttribution link={sourceLinkFor("tayljordan-ports", p)} />
    </>
  );
}

