// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { latLonFromProps } from "../shared/format";
import { Row, Section, Badge, PanelHeader, ExternalLink, ExternalLinks, SourceAttribution } from "../shared/primitives";
import { sourceLinkFor } from "../../../utils/sourceUrl";

export function FirePanel({ properties: p }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation("panels");
  const coords = latLonFromProps(p);
  return (
    <>
      <Badge label={t("fire.panelBadge")} color="text-orange-300 border-orange-500/40" />
      <PanelHeader>{t("fire.panelTitle")}</PanelHeader>
      <Section title={t("fire.detailsSectionTitle")}>
        {/* ⛔ FIRMS publishes acq_time (HHMM UTC) beside acq_date on every row
            and four locales promised "click for exact date/time", while the
            table kept a bare DATE. `observed_at` is the two of them combined;
            when it is absent (a row from before 2026-09-10, or a stamp FIRMS
            gave that would not parse) the date shows alone rather than a
            midnight that NASA never observed. */}
        {p.observed_at != null
          ? <Row label={t("fire.observedLabel")}
                 value={String(p.observed_at).slice(0, 16).replace("T", " ") + " UTC"} />
          : p.acq_date != null && <Row label={t("fire.dateLabel")} value={String(p.acq_date)} />}
        {p.confidence != null && <Row label={t("fire.confidenceLabel")} value={String(p.confidence)} />}
        {p.brightness != null && <Row label={t("fire.brightnessLabel")} value={`${Number(p.brightness).toFixed(1)} K`} />}
        {p.frp != null && <Row label={t("fire.frpLabel")}             value={`${Number(p.frp).toFixed(1)} MW`} />}
        {p.instrument != null && <Row label={t("fire.instrumentLabel")} value={String(p.instrument)} />}
        {/* NASA ships instrument and satellite as two separate fields. This
            column used to hold OUR fused label ("VIIRS_SNPP") — a name we
            invented, not one NASA gave. Both are now stored as published. */}
        {p.satellite != null && <Row label={t("fire.satelliteLabel")} value={String(p.satellite)} />}
        {p.daynight != null && (
          <Row label={t("fire.dayNightLabel")}
               value={p.daynight === "N" ? t("fire.nightValue") : p.daynight === "D" ? t("fire.dayValue") : String(p.daynight)} />
        )}
        {p.version != null && <Row label={t("fire.versionLabel")} value={String(p.version)} />}
        {p.scan != null && p.track != null && (
          <Row label={t("fire.pixelSizeLabel")}
               value={`${Number(p.scan).toFixed(2)} × ${Number(p.track).toFixed(2)} km`} />
        )}
      </Section>
      <SourceAttribution link={sourceLinkFor("firms", p)} />
      <ExternalLinks>
        {coords && <ExternalLink href={`https://firms.modaps.eosdis.nasa.gov/map/#d:24hrs;@${coords[1]},${coords[0]},12z`} label="NASA FIRMS map" />}
      </ExternalLinks>
    </>
  );
}

