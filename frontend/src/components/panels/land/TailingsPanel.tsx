// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { Row, Section, Badge, PanelHeader, WarningBanner, ExternalLink, ExternalLinks, SourceAttribution } from "../shared/primitives";
import { sourceLinkFor } from "../../../utils/sourceUrl";

// ⛔ WITHDRAWN 2026-09-23 (Michal's decision): tailing.grida.no/about asks for
// permission to download the TSF dataset; we never obtained it. The backend
// no longer sends any Global Tailings Portal-derived field (hazard rating,
// classification system, owner, operator, dam specs, safety-review answers,
// closure plans, disclosure link/notes, partners) on ANY row — see
// backend/domains/land/common.py TAILINGS_SERVED_WHERE / TAILINGS_PORTAL_COLUMNS.
// Every property this panel can read is therefore WAPHA-origin or
// platform-derived: id, dam_name, country, data_source, latitude, longitude.
function str(v: unknown): string | null {
  return v != null ? String(v) : null;
}

export function TailingsPanel({ properties: p }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation(["panels", "enums"]);
  const name = String(p.dam_name ?? "");
  const lat = p.latitude != null ? Number(p.latitude) : null;
  const lon = p.longitude != null ? Number(p.longitude) : null;
  const country = str(p.country);
  // Names like "DE_12062492_01_1060" or "尾矿库" are codes/generic — not useful for text search
  const isCode = !name || /^[A-Z]{2}_\d/.test(name) || /^\d+$/.test(name) || name === "尾矿库";
  const hasCoords = lat != null && lon != null;

  return (
    <>
      <Badge label={t("tailings.panelBadge")} color="text-red-400 border-red-600/40" />
      <PanelHeader>{name || "—"}</PanelHeader>
      <WarningBanner color="orange">{t("tailings.waphaCaveat")}</WarningBanner>
      <Section title={t("tailings.detailsSectionTitle")}>
        {country != null && <Row label={t("tailings.countryLabel")} value={country} />}
      </Section>
      {hasCoords && (
        <Section title={t("tailings.locationSectionTitle")}>
          <Row label={t("tailings.coordinatesLabel")} value={`${lat.toFixed(4)}°, ${lon.toFixed(4)}°`} />
        </Section>
      )}
      <SourceAttribution link={sourceLinkFor("tailings", p)} />
      <ExternalLinks>
        {hasCoords && <ExternalLink href={`https://www.google.com/maps/@${lat},${lon},2000m/data=!3m1!1e3`} label="Satellite view" />}
        {!isCode && name && <ExternalLink href={`https://www.google.com/search?q=${encodeURIComponent(`"${name}" tailings dam`)}`} label="Search online" />}
        {!isCode && name && country && <ExternalLink href={`https://www.google.com/search?q=${encodeURIComponent(`"${name}" ${country} tailings mining`)}`} label={`Search in ${country}`} />}
      </ExternalLinks>
    </>
  );
}

