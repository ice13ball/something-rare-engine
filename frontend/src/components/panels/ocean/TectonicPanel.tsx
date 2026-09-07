// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { sourceLinkFor } from "../../../utils/sourceUrl";

import { Row, Section, Badge, PanelHeader, SourceAttribution } from "../shared/primitives";

// ── Tectonic plate panel ──────────────────────────────────────────────────────

const BOUNDARY_TYPES: Record<string, string> = {
  CTF: "Continental Transform Fault",
  CRB: "Continental Rift Boundary",
  CCB: "Continental Convergent Boundary",
  OCB: "Oceanic Convergent Boundary",
  OTF: "Oceanic Transform Fault",
  OSR: "Oceanic Spreading Ridge",
  SUB: "Subduction Zone",
};

export function TectonicPanel({ properties: p }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation("panels");
  // Boundaries have PlateA/PlateB/Type; plates have PlateName
  const name = p.PlateName ?? (p.PlateA && p.PlateB ? `${p.PlateA} / ${p.PlateB}` : null);
  const rawType = p.Type != null ? String(p.Type) : null;
  const expandedType = rawType ? (BOUNDARY_TYPES[rawType] ?? rawType) : null;
  return (
    <>
      <Badge label={t("tectonic.panelBadge")} color="text-amber-300 border-amber-500/40" />
      <PanelHeader>{String(name ?? "—")}</PanelHeader>
      <Section title={t("tectonic.detailsSectionTitle")}>
        {p.PlateName != null && <Row label={t("tectonic.plateLabel")}        value={String(p.PlateName)} />}
        {p.PlateA != null && <Row label={t("tectonic.plateALabel")}           value={String(p.PlateA)} />}
        {p.PlateB != null && <Row label={t("tectonic.plateBLabel")}           value={String(p.PlateB)} />}
        {expandedType != null && <Row label={t("tectonic.boundaryTypeLabel")} value={expandedType} />}
      </Section>
      <SourceAttribution link={sourceLinkFor("bird-tectonic", p)} />
    </>
  );
}

