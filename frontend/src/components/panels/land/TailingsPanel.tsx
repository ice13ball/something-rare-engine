// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { tEnum } from "../../../utils/translateEnum";
import { Row, Section, Badge, PanelHeader, WarningBanner, ExternalLink, ExternalLinks, SourceAttribution } from "../shared/primitives";
import { sourceLinkFor } from "../../../utils/sourceUrl";

const RISK_COLORS: Record<string, string> = {
  Extreme: "text-red-300 border-red-500/50 bg-red-500/10",
  "Very High": "text-red-400 border-red-600/40 bg-red-500/5",
  High: "text-orange-400 border-orange-500/40 bg-orange-500/5",
  Significant: "text-amber-400 border-amber-500/40 bg-amber-500/5",
  Medium: "text-yellow-400 border-yellow-500/40 bg-yellow-500/5",
  Low: "text-green-400 border-green-500/40 bg-green-500/5",
};

export function TailingsPanel({ properties: p }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation(["panels", "enums"]);
  const mine = String(p.mine_name ?? "");
  const dam = String(p.dam_name ?? "");
  const name = dam || mine;
  const lat = p.latitude != null ? Number(p.latitude) : null;
  const lon = p.longitude != null ? Number(p.longitude) : null;
  const country = p.country != null ? String(p.country) : null;
  const risk = p.risk_class != null ? String(p.risk_class) : null;
  const hasRisk = risk && risk !== "Unclassified";
  const riskStyle = hasRisk ? RISK_COLORS[risk] ?? "" : "";
  // Names like "DE_12062492_01_1060" or "尾矿库" are codes/generic — not useful for text search
  const isCode = !name || /^[A-Z]{2}_\d/.test(name) || /^\d+$/.test(name) || name === "尾矿库";
  const hasCoords = lat != null && lon != null;
  // The WAPHA shapefile publishes ONE attribute (Name). Everything else on such a
  // row — country included — is platform-derived or absent.
  const isWapha = p.data_source !== "grid" && p.data_source !== "grid-enriched";
  return (
    <>
      <Badge label={t("tailings.panelBadge")} color="text-red-400 border-red-600/40" />
      <PanelHeader>{name || "—"}</PanelHeader>
      {hasRisk && (
        <div className={`inline-block px-2 py-0.5 rounded text-xs font-semibold border mb-3 ${riskStyle}`}>
          {risk} Risk
        </div>
      )}
      {isWapha && <WarningBanner color="orange">{t("tailings.waphaCaveat")}</WarningBanner>}
      <Section title={t("tailings.detailsSectionTitle")}>
        {p.owner_company != null && <Row label={t("tailings.ownerLabel")}    value={String(p.owner_company)} />}
        {p.operator != null && <Row label={t("tailings.operatorLabel")}       value={String(p.operator)} />}
        {p.mine_name != null && <Row label={t("tailings.mineLabel")}          value={mine} />}
        {country != null && <Row label={t("tailings.countryLabel")}           value={country} />}
        {p.status != null && <Row label={t("tailings.statusLabel")}           value={tEnum(t, "status", String(p.status))} />}
      </Section>
      {(p.height_m != null || p.volume_m3 != null || p.raise_type != null || p.construction_year != null) && (
        <Section title={t("tailings.damSpecsSectionTitle")}>
          {p.raise_type != null && <Row label={t("tailings.constructionLabel")} value={String(p.raise_type)} />}
          {p.height_m != null && <Row label={t("tailings.heightLabel")}         value={`${p.height_m} m`} />}
          {p.volume_m3 != null && <Row label={t("tailings.storageLabel")}       value={`${Number(p.volume_m3).toLocaleString()} m³`} />}
          {p.construction_year != null && <Row label={t("tailings.builtLabel")} value={String(p.construction_year)} />}
        </Section>
      )}
      {hasRisk && (
        <Section title={t("tailings.hazardAssessmentSectionTitle")}>
          <Row label={t("tailings.riskLevelLabel")} value={risk} />
          {p.hazard_raw != null && String(p.hazard_raw) !== risk && (
            <Row label={t("tailings.originalRatingLabel")} value={String(p.hazard_raw)} />
          )}
        </Section>
      )}
      {hasCoords && (
        <Section title={t("tailings.locationSectionTitle")}>
          <Row label={t("tailings.coordinatesLabel")} value={`${lat.toFixed(4)}°, ${lon.toFixed(4)}°`} />
        </Section>
      )}
      <SourceAttribution
        link={
          p.data_source === "grid" || p.data_source === "grid-enriched"
            ? sourceLinkFor("tailings", p)
            : sourceLinkFor("wapha-tsf", p)
        }
      />
      <ExternalLinks>
        {hasCoords && <ExternalLink href={`https://www.google.com/maps/@${lat},${lon},2000m/data=!3m1!1e3`} label="Satellite view" />}
        {(p.data_source === "grid" || p.data_source === "grid-enriched") && (
          <ExternalLink href="https://tailing.grida.no/disclosures" label="Global Tailings Portal" />
        )}
        {!isCode && name && <ExternalLink href={`https://www.google.com/search?q=${encodeURIComponent(`"${name}" tailings dam`)}`} label="Search online" />}
        {!isCode && name && country && <ExternalLink href={`https://www.google.com/search?q=${encodeURIComponent(`"${name}" ${country} tailings mining`)}`} label={`Search in ${country}`} />}
      </ExternalLinks>
    </>
  );
}

