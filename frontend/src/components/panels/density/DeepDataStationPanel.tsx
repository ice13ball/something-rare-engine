// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { Linkify } from "../../../utils/linkify";
import { latLonFromProps } from "../shared/format";
import { Row, Section, Badge, PanelHeader, WarningBanner, SourceFooter } from "../shared/primitives";
import { SeafloorDepthRow } from "../shared/chips";

// ── DeepData sampling station panel (TIER 2 — platform-derived analysis) ────
// This panel ALWAYS leads with a "Platform-derived analysis" banner.
// The raw contractor records live in the deepdata_occurrences table and are
// surfaced only via the density panel — never modified by us.

export function DeepDataStationPanel({ properties: p }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation("panels");
  const code = (p.contractor_code as string | undefined) ?? null;
  const slug = (p.archive_slug as string | undefined) ?? null;
  const stationId = (p.station_id as string | undefined) ?? null;
  const occCount = Number(p.occurrence_count ?? 0);
  const speciesCount = p.species_count != null ? Number(p.species_count) : null;
  const protocol = (p.sampling_protocol as string | undefined) ?? null;
  const locationId = (p.location_id as string | undefined) ?? null;
  const eventIdRaw = (p.event_id_raw as string | undefined) ?? null;
  const horizons = (p.sediment_horizons as string[] | undefined) ?? null;
  const topSpecies = (p.top_species as string[] | undefined) ?? null;
  const topPhyla = (p.top_phyla as string[] | undefined) ?? null;
  const depthMin = p.depth_m_min != null ? Number(p.depth_m_min) : null;
  const depthMax = p.depth_m_max != null ? Number(p.depth_m_max) : null;
  const firstDate = (p.first_event_date as string | undefined) ?? null;
  const lastDate  = (p.last_event_date  as string | undefined) ?? null;
  const archiveTitle    = (p.archive_title as string | undefined) ?? null;
  const archiveCitation = (p.archive_citation as string | undefined) ?? null;
  const archiveLicense  = (p.archive_license as string | undefined) ?? null;
  const archiveRights   = (p.archive_rights_holder as string | undefined) ?? null;
  const archivePubDate  = (p.archive_pub_date as string | undefined) ?? null;

  return (
    <>
      <Badge label={t("deepDataStation.panelBadge")} color="text-pink-300 border-pink-500/40" />
      <PanelHeader>
        {locationId ?? eventIdRaw ?? stationId ?? "Station"}
      </PanelHeader>

      <WarningBanner color="orange">
        {t("deepDataStation.warningBanner")}
      </WarningBanner>

      <Section title={t("deepDataStation.stationSectionTitle")}>
        <Row label={t("deepDataStation.contractorLabel")} value={code ?? <span className="text-white/65 italic">Unparsed</span>} />
        {protocol     && <Row label={t("deepDataStation.samplingGearLabel")} value={protocol} />}
        {locationId   && <Row label={t("deepDataStation.locationIdLabel")}   value={locationId} />}
        {(depthMin != null || depthMax != null) && (
          <Row
            label={t("deepDataStation.depthLabel")}
            value={
              depthMin != null && depthMax != null && depthMin !== depthMax
                ? `${Math.round(depthMin)}–${Math.round(depthMax)} m`
                : `${Math.round((depthMin ?? depthMax)!)} m`
            }
          />
        )}
        {(() => { const c = latLonFromProps(p); return c && <SeafloorDepthRow lat={c[0]} lon={c[1]} />; })()}
        <Row label={t("deepDataStation.occurrencesLabel")} value={occCount.toLocaleString()} />
        {speciesCount != null && <Row label={t("deepDataStation.distinctSpeciesLabel")} value={speciesCount.toLocaleString()} />}
        {firstDate && lastDate && (
          <Row
            label={t("deepDataStation.sampledLabel")}
            value={firstDate.slice(0, 10) === lastDate.slice(0, 10)
              ? firstDate.slice(0, 10)
              : `${firstDate.slice(0, 10)} → ${lastDate.slice(0, 10)}`}
          />
        )}
      </Section>

      {topPhyla && topPhyla.length > 0 && (
        <Section title={t("deepDataStation.phylaObservedSectionTitle")}>
          <p className="text-white/80 text-xs leading-relaxed">
            {topPhyla.join(" · ")}
          </p>
        </Section>
      )}

      {topSpecies && topSpecies.length > 0 && (
        <Section title={`Top species${speciesCount && speciesCount > topSpecies.length ? ` (showing ${topSpecies.length} of ${speciesCount})` : ""}`}>
          <ul className="text-white/75 text-xs leading-relaxed space-y-0.5 list-none">
            {topSpecies.map((s, i) => (
              <li key={i} className="italic">{s}</li>
            ))}
          </ul>
          <p className="text-white/60 text-[11px] mt-1.5">
            Most-frequent identifications across {occCount.toLocaleString()} raw record{occCount === 1 ? "" : "s"}.
          </p>
        </Section>
      )}

      {horizons && horizons.length > 0 && (
        <Section title={t("deepDataStation.sedimentHorizonsSectionTitle")}>
          <p className="text-white/80 text-xs leading-relaxed">
            {horizons.join(" · ")}
          </p>
          <p className="text-white/60 text-[11px] mt-1">
            Parsed from eventID; sub-core depth slices in cm.
          </p>
        </Section>
      )}

      {eventIdRaw && (
        <Section title={t("deepDataStation.auditTrailSectionTitle")}>
          <p className="text-white/65 text-[11px] font-mono break-all leading-relaxed">
            {eventIdRaw}
          </p>
          <p className="text-white/60 text-[11px] mt-1">
            Verbatim eventID from the contractor's submission.
          </p>
        </Section>
      )}

      {(archiveCitation || archiveTitle) && (
        <Section title={t("deepDataStation.citationSectionTitle")}>
          {archiveTitle && <p className="text-white/85 text-xs italic mb-1.5">{archiveTitle}</p>}
          {archiveCitation && (
            <p className="text-white/75 text-xs leading-relaxed"><Linkify text={archiveCitation} /></p>
          )}
          <div className="mt-2 space-y-0.5">
            {archiveRights  && <Row label={t("deepDataStation.rightsHolderLabel")} value={archiveRights} />}
            {archiveLicense && <Row label={t("deepDataStation.licenseLabel")}      value={archiveLicense} />}
            {archivePubDate && <Row label={t("deepDataStation.publishedLabel")}    value={String(archivePubDate).slice(0, 10)} />}
          </div>
        </Section>
      )}

      {slug && (
        <p className="text-white/65 text-[11px] mt-2 flex gap-3">
          <a
            href={`https://datasets.obis.org/hosted/isa/${slug}/index.html`}
            target="_blank"
            rel="noopener noreferrer"
            className="underline decoration-white/20 hover:decoration-white/60 hover:text-white/85"
          >
            Dataset page ↗
          </a>
          <a
            href={`https://datasets.obis.org/hosted/isa/${slug}/${slug}.zip`}
            target="_blank"
            rel="noopener noreferrer"
            className="underline decoration-white/20 hover:decoration-white/60 hover:text-white/85"
          >
            Download DwC archive ↗
          </a>
        </p>
      )}

      <SourceFooter>
        Source: ISA DeepData (data.isa.org.jm) via OBIS-hosted DwC archives
        (datasets.obis.org/hosted/isa). Per-dataset citation and license shown above.
        Platform-aggregated analysis — not raw contractor records.
      </SourceFooter>
    </>
  );
}
