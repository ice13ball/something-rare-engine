// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { tEnum } from "../../../utils/translateEnum";
import { Row, Section, Badge, PanelHeader, BodyText, WarningBanner, ExternalLink, ExternalLinks, SourceAttribution } from "../shared/primitives";
import { sourceLinkFor } from "../../../utils/sourceUrl";
import { TAILINGS_HAZARD, TAILINGS_HAZARD_OTHER } from "../../../styles/colorStandards";

// Read verbatim from the properties bag, never risk_class — that field was
// this platform's own six-tier collapse of the source's rating, deleted
// backend and frontend 2026-09-22. Never "clean" a value (e.g. "No"/"no" both
// occur in history_stability_concerns) — render the source's exact string.
function str(v: unknown): string | null {
  return v != null ? String(v) : null;
}

export function TailingsPanel({ properties: p }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation(["panels", "enums"]);
  const mine = String(p.mine_name ?? "");
  const dam = String(p.dam_name ?? "");
  const name = dam || mine;
  const lat = p.latitude != null ? Number(p.latitude) : null;
  const lon = p.longitude != null ? Number(p.longitude) : null;
  const country = str(p.country);
  const hazardRaw = str(p.hazard_raw);
  const classificationSystem = str(p.classification_system);
  const hazardColor = hazardRaw ? (TAILINGS_HAZARD[hazardRaw] ?? TAILINGS_HAZARD_OTHER) : null;
  // Names like "DE_12062492_01_1060" or "尾矿库" are codes/generic — not useful for text search
  const isCode = !name || /^[A-Z]{2}_\d/.test(name) || /^\d+$/.test(name) || name === "尾矿库";
  const hasCoords = lat != null && lon != null;
  // The WAPHA shapefile publishes ONE attribute (Name). Everything else on such a
  // row — country included — is platform-derived or absent.
  const isWapha = p.data_source !== "grid" && p.data_source !== "grid-enriched";

  const disclosureOrigin = str(p.disclosure_origin);
  const historyStabilityConcerns = str(p.history_stability_concerns);
  const downstreamImpact = str(p.downstream_impact);
  const recentIndependentExpertReview = str(p.recent_independent_expert_review);
  const extremeWeatherSecure = str(p.extreme_weather_secure);
  const currentlyApprovedDesign = str(p.currently_approved_design);
  const internalExternalEngSupport = str(p.internal_external_eng_support);
  const relevantEngineeringRecords = str(p.relevant_engineering_records);
  const hasSafetyReview = historyStabilityConcerns != null || downstreamImpact != null
    || recentIndependentExpertReview != null || extremeWeatherSecure != null
    || currentlyApprovedDesign != null || internalExternalEngSupport != null
    || relevantEngineeringRecords != null;

  const closurePlanDam = str(p.closure_plan_dam);
  const closurePlanLongTermMonitoring = str(p.closure_plan_long_term_monitoring);
  const hasClosurePlan = closurePlanDam != null || closurePlanLongTermMonitoring != null;

  const partners = str(p.partners);
  const hasGovernance = disclosureOrigin != null || partners != null;

  const disclosureNotes = str(p.disclosure_notes);
  const disclosureLink = str(p.disclosure_link);
  const plannedStorage5Years = typeof p.planned_storage_5_years === "number" ? p.planned_storage_5_years : null;

  return (
    <>
      <Badge label={t("tailings.panelBadge")} color="text-red-400 border-red-600/40" />
      <PanelHeader>{name || "—"}</PanelHeader>
      {hazardRaw && hazardColor && (
        <div className="mb-1">
          <span
            className="inline-block px-2 py-0.5 rounded text-xs font-semibold border"
            style={{
              color: `rgb(${hazardColor.join(", ")})`,
              borderColor: `rgba(${hazardColor.join(", ")}, 0.5)`,
              background: `rgba(${hazardColor.join(", ")}, 0.12)`,
            }}
          >
            {hazardRaw}
          </span>
        </div>
      )}
      {classificationSystem && (
        <p className="text-white/50 text-[11px] mb-3">{t("tailings.classificationSystemLabel")}: {classificationSystem}</p>
      )}
      {isWapha && <WarningBanner color="orange">{t("tailings.waphaCaveat")}</WarningBanner>}
      <Section title={t("tailings.detailsSectionTitle")}>
        {p.owner_company != null && <Row label={t("tailings.ownerLabel")}    value={String(p.owner_company)} />}
        {p.operator != null && <Row label={t("tailings.operatorLabel")}       value={String(p.operator)} />}
        {p.mine_name != null && <Row label={t("tailings.mineLabel")}          value={mine} />}
        {country != null && <Row label={t("tailings.countryLabel")}           value={country} />}
        {p.status != null && <Row label={t("tailings.statusLabel")}           value={tEnum(t, "status", String(p.status))} />}
      </Section>
      {(p.height_m != null || p.volume_m3 != null || p.raise_type != null || p.construction_year != null || plannedStorage5Years != null) && (
        <Section title={t("tailings.damSpecsSectionTitle")}>
          {p.raise_type != null && <Row label={t("tailings.constructionLabel")} value={String(p.raise_type)} />}
          {p.height_m != null && <Row label={t("tailings.heightLabel")}         value={`${p.height_m} m`} />}
          {p.volume_m3 != null && <Row label={t("tailings.storageLabel")}       value={`${Number(p.volume_m3).toLocaleString()} m³`} />}
          {plannedStorage5Years != null && <Row label={t("tailings.plannedStorage5YearsLabel")} value={`${plannedStorage5Years.toLocaleString()} m³`} />}
          {p.construction_year != null && <Row label={t("tailings.builtLabel")} value={String(p.construction_year)} />}
        </Section>
      )}
      {hasSafetyReview && (
        <Section title={t("tailings.safetyReviewSectionTitle")}>
          {historyStabilityConcerns != null && <Row label={t("tailings.historyStabilityConcernsLabel")} value={historyStabilityConcerns} />}
          {downstreamImpact != null && <Row label={t("tailings.downstreamImpactLabel")} value={downstreamImpact} />}
          {recentIndependentExpertReview != null && <Row label={t("tailings.recentIndependentExpertReviewLabel")} value={recentIndependentExpertReview} />}
          {extremeWeatherSecure != null && <Row label={t("tailings.extremeWeatherSecureLabel")} value={extremeWeatherSecure} />}
          {currentlyApprovedDesign != null && <Row label={t("tailings.currentlyApprovedDesignLabel")} value={currentlyApprovedDesign} />}
          {internalExternalEngSupport != null && <Row label={t("tailings.internalExternalEngSupportLabel")} value={internalExternalEngSupport} />}
          {relevantEngineeringRecords != null && <Row label={t("tailings.relevantEngineeringRecordsLabel")} value={relevantEngineeringRecords} />}
        </Section>
      )}
      {hasClosurePlan && (
        <Section title={t("tailings.closurePlanningSectionTitle")}>
          {closurePlanDam != null && <Row label={t("tailings.closurePlanDamLabel")} value={closurePlanDam} />}
          {closurePlanLongTermMonitoring != null && <Row label={t("tailings.closurePlanLongTermMonitoringLabel")} value={closurePlanLongTermMonitoring} />}
        </Section>
      )}
      {hasGovernance && (
        <Section title={t("tailings.governanceSectionTitle")}>
          {disclosureOrigin != null && <Row label={t("tailings.disclosureOriginLabel")} value={disclosureOrigin} />}
          {partners != null && <Row label={t("tailings.partnersLabel")} value={partners} />}
        </Section>
      )}
      {disclosureNotes != null && (
        <Section title={t("tailings.disclosureNotesSectionTitle")}>
          <BodyText className="text-white/70 whitespace-pre-line">{disclosureNotes}</BodyText>
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
        {disclosureLink != null && <ExternalLink href={disclosureLink} label={t("tailings.disclosureLinkLabel")} />}
        {(p.data_source === "grid" || p.data_source === "grid-enriched") && (
          <ExternalLink href="https://tailing.grida.no/disclosures" label="Global Tailings Portal" />
        )}
        {!isCode && name && <ExternalLink href={`https://www.google.com/search?q=${encodeURIComponent(`"${name}" tailings dam`)}`} label="Search online" />}
        {!isCode && name && country && <ExternalLink href={`https://www.google.com/search?q=${encodeURIComponent(`"${name}" ${country} tailings mining`)}`} label={`Search in ${country}`} />}
      </ExternalLinks>
    </>
  );
}

