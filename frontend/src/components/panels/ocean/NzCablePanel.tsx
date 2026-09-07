// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { sourceLinkFor } from "../../../utils/sourceUrl";

import { Row, Section, Badge, PanelHeader, WarningBanner, SourceAttribution } from "../shared/primitives";

export function NzCablePanel({ properties: p }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation("panels");
  const fidn      = p.fidn != null ? String(p.fidn) : "—";
  const objnam    = p.objnam    != null ? String(p.objnam)    : null;
  const catcbl    = p.catcbl    != null ? String(p.catcbl)    : null;
  const status    = p.status    != null ? String(p.status)    : null;
  const condtn    = p.condtn    != null ? String(p.condtn)    : null;
  const burdep    = p.burdep    != null ? Number(p.burdep)    : null;
  const datsta    = p.datsta    != null ? String(p.datsta)    : null;
  const datend    = p.datend    != null ? String(p.datend)    : null;
  const inform    = p.inform    != null ? String(p.inform)    : null;

  const header = objnam ?? `${t("nzCable.fallbackHeader")} ${fidn}`;
  const hasAnyDetail =
    catcbl != null || status != null || condtn != null ||
    burdep != null || datsta != null || datend != null || inform != null;

  return (
    <>
      <Badge label={t("nzCable.panelBadge")} color="text-amber-300 border-amber-500/40" />
      <PanelHeader>{header}</PanelHeader>
      {hasAnyDetail && (
        <Section title={t("nzCable.detailsSectionTitle")}>
          {catcbl != null && <Row label={t("nzCable.cableTypeLabel")}   value={catcbl} />}
          {status != null && <Row label={t("nzCable.statusLabel")}      value={status} />}
          {condtn != null && <Row label={t("nzCable.conditionLabel")}   value={condtn} />}
          {burdep != null && <Row label={t("nzCable.burialDepthLabel")} value={`${burdep.toFixed(1)} m`} />}
          {datsta != null && <Row label={t("nzCable.installedLabel")}   value={datsta} />}
          {datend != null && <Row label={t("nzCable.retiredLabel")}     value={datend} />}
          {inform != null && <Row label={t("nzCable.notesLabel")}       value={inform} />}
        </Section>
      )}
      <WarningBanner color="orange">{t("nzCable.dataNoteBody")}</WarningBanner>
      <SourceAttribution link={sourceLinkFor("nz-cables", p)} />
    </>
  );
}

