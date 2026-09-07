// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { sourceLinkFor } from "../../../utils/sourceUrl";

import { Row, Section, Badge, PanelHeader, SourceAttribution } from "../shared/primitives";

export function OoiCablePanel({ properties: p }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation("panels");
  const lengthM    = p.length_m         != null ? Number(p.length_m)         : null;
  const deepest    = p.deepest_node_m   != null ? Number(p.deepest_node_m)   : null;
  const shallowest = p.shallowest_node_m != null ? Number(p.shallowest_node_m) : null;
  const nodeCount  = p.node_count       != null ? Number(p.node_count)       : null;
  const depthLabel = deepest != null && shallowest != null
    ? deepest === shallowest
      ? `${deepest.toLocaleString()} m`
      : `${shallowest.toLocaleString()} – ${deepest.toLocaleString()} m`
    : null;
  return (
    <>
      <Badge label={t("ooiCable.panelBadge")} color="text-fuchsia-300 border-fuchsia-500/40" />
      <PanelHeader>{String(p.line_name ?? p.ext_id ?? "RCA Backbone")}</PanelHeader>
      <Section title={t("ooiCable.cableSectionTitle")}>
        {lengthM   != null && <Row label={t("ooiCable.routeLengthLabel")} value={`${(lengthM / 1000).toFixed(0)} km — straight-line between nodes`} />}
        {nodeCount != null && <Row label={t("ooiCable.nodePrimaryLabel")} value={`${nodeCount} seafloor junction boxes`} />}
        {depthLabel        && <Row label={t("ooiCable.seafloorDepthLabel")} value={depthLabel} />}
      </Section>
      <Section title={t("ooiCable.observatorySectionTitle")}>
        {p.operator     != null && <Row label={t("ooiCable.observatoryLabel")} value={String(p.operator)} />}
        {p.commissioned != null && <Row label={t("ooiCable.onlineSinceLabel")} value={String(p.commissioned)} />}
      </Section>
      <SourceAttribution link={sourceLinkFor("ooi-cables", p)} />
      <p className="text-white/60 text-[12px] leading-relaxed mt-1">
        Route geometry is approximate (straight-line between Primary Nodes).
      </p>
    </>
  );
}

