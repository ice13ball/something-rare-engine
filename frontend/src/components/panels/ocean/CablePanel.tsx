// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { sourceLinkFor } from "../../../utils/sourceUrl";

import { Row, Section, Badge, PanelHeader, SourceAttribution } from "../shared/primitives";

// Upstream (EMODnet, layer pcablesnve) encodes "unknown" as 0, not as null —
// verified against the raw WFS on 2026-08-27. The ingest now nulls those two
// fields, so this is the second line of defence, for rows written before the
// fix and for any future contributor that ships the same encoding.
//
// ⚠️ `!= null` does NOT catch it. 0 is not null, so NorNed rendered "0 kV,
// installed 0" and read as measured. Neither value can exist: no cable was
// commissioned in year 0, and one at 0 kV carries no current.
const measured = (v: unknown) => v != null && Number(v) !== 0;

export function CablePanel({ properties: p }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation("panels");
  return (
    <>
      <Badge label={t("cable.panelBadge")} color="text-amber-300 border-amber-500/40" />
      <PanelHeader>{String(p.name ?? "—")}</PanelHeader>
      <Section title={t("cable.detailsSectionTitle")}>
        {p.operator != null && <Row label={t("cable.operatorLabel")}   value={String(p.operator)} />}
        {p.cable_type != null && <Row label={t("cable.cableTypeLabel")} value={String(p.cable_type)} />}
        {measured(p.voltage_kv) && <Row label={t("cable.voltageLabel")}  value={`${Number(p.voltage_kv).toFixed(0)} kV`} />}
        {p.status != null && <Row label={t("cable.statusLabel")}    value={String(p.status)} />}
        {measured(p.inst_year) && <Row label={t("cable.installedLabel")} value={String(p.inst_year)} />}
        {p.length_km != null && <Row label={t("cable.lengthLabel")}  value={`${Math.round(Number(p.length_km)).toLocaleString()} km`} />}
        {p.location != null && <Row label={t("cable.locationLabel")} value={String(p.location)} />}
        {p.source_layer != null && <Row label={t("cable.contributorLabel")} value={String(p.source_layer)} />}
      </Section>
      <SourceAttribution link={sourceLinkFor("emodnet-cables", p)} />
    </>
  );
}

