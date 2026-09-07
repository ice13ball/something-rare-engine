// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { sourceLinkFor } from "../../../utils/sourceUrl";

import { Row, Section, Badge, PanelHeader, SourceAttribution } from "../shared/primitives";

export function AuCablePanel({ properties: p }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation("panels");
  const cable  = p.cable  != null ? String(p.cable)  : "—";
  const abbrev = p.abbrev != null ? String(p.abbrev) : null;
  return (
    <>
      <Badge label={t("auCable.panelBadge")} color="text-amber-300 border-amber-500/40" />
      <PanelHeader>{cable}</PanelHeader>
      {abbrev != null && (
        <Section title={t("auCable.detailsSectionTitle")}>
          <Row label={t("auCable.abbrevLabel")} value={abbrev} />
        </Section>
      )}
      <SourceAttribution link={sourceLinkFor("au-cables", p)} />
    </>
  );
}

