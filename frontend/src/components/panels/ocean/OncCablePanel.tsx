// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { sourceLinkFor } from "../../../utils/sourceUrl";

import { Row, Section, Badge, PanelHeader, SourceAttribution } from "../shared/primitives";

export function OncCablePanel({ properties: p }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation("panels");
  const lengthM = p.length_m != null ? Number(p.length_m) : null;
  return (
    <>
      <Badge label={t("oncCable.panelBadge")} color="text-cyan-300 border-cyan-500/40" />
      <PanelHeader>{String(p.ext_id ?? "NEPTUNE/VENUS backbone")}</PanelHeader>
      <Section title={t("oncCable.detailsSectionTitle")}>
        {p.status != null && <Row label={t("oncCable.statusLabel")} value={String(p.status)} />}
        {lengthM != null && <Row label={t("oncCable.lengthLabel")} value={lengthM >= 1000 ? `${(lengthM / 1000).toFixed(1)} km` : `${Math.round(lengthM)} m`} />}
        {p.comments != null && <Row label={t("oncCable.notesLabel")} value={String(p.comments)} />}
      </Section>
      <SourceAttribution link={sourceLinkFor("onc-cables", p)} />
    </>
  );
}

