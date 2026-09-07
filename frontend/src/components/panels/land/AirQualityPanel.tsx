// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { fmtDate } from "../shared/format";
import { Row, Section, Badge, PanelHeader, ExternalLink, ExternalLinks, SourceAttribution } from "../shared/primitives";
import { sourceLinkFor } from "../../../utils/sourceUrl";

export function AirQualityPanel({ properties: p }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation("panels");
  const locId = p.location_id != null ? String(p.location_id) : null;
  const isMonitor = p.is_monitor === true;
  const isMonitorKnown = p.is_monitor != null;
  const isMobile = p.is_mobile === true;

  return (
    <>
      <Badge label={t("airQuality.panelTitle")} color="text-slate-300 border-slate-500/40" />
      <PanelHeader>{String(p.name ?? p.city ?? "—")}</PanelHeader>

      <Section title={t("airQuality.locationSectionTitle")}>
        {p.locality != null && String(p.locality) !== "" && <Row label={t("airQuality.localityLabel")}  value={String(p.locality)} />}
        {p.city != null && <Row label={t("airQuality.cityLabel")}                                       value={String(p.city)} />}
        {p.country != null && <Row label={t("airQuality.countryLabel")}                                 value={String(p.country)} />}
        {p.timezone != null && String(p.timezone) !== "" && <Row label={t("airQuality.timezoneLabel")} value={String(p.timezone)} />}
      </Section>

      <Section title={t("airQuality.stationSectionTitle")}>
        {isMonitorKnown && (
          <Row label={t("airQuality.typeLabel")} value={
            <span className={`text-xs px-1.5 py-0.5 rounded-full border ${isMonitor ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/30" : "bg-amber-500/10 text-amber-400 border-amber-500/30"}`}>
              {isMonitor ? "Reference Monitor" : "Low-cost Sensor"}
            </span>
          } />
        )}
        {isMobile && <Row label={t("airQuality.mobilityLabel")} value={<span className="text-xs px-1.5 py-0.5 rounded-full border bg-sky-500/10 text-sky-400 border-sky-500/30">Mobile</span>} />}
        {p.provider != null && String(p.provider) !== "" && <Row label={t("airQuality.providerLabel")} value={String(p.provider)} />}
        {p.owner != null && String(p.owner) !== "" && <Row label={t("airQuality.ownerLabel")}          value={String(p.owner)} />}
        {p.datetime_first != null && <Row label={t("airQuality.activeSinceLabel")} value={new Date(String(p.datetime_first)).getFullYear().toString()} />}
      </Section>

      <Section title={t("airQuality.particulatesSectionTitle")}>
        {p.pm1 != null && <Row label="PM1" value={`${Number(p.pm1).toFixed(1)} µg/m³`} />}
        {p.pm25 != null && <Row label="PM2.5" value={`${Number(p.pm25).toFixed(1)} µg/m³`} />}
        {p.pm4 != null && <Row label="PM4" value={`${Number(p.pm4).toFixed(1)} µg/m³`} />}
        {p.pm10 != null && <Row label="PM10" value={`${Number(p.pm10).toFixed(1)} µg/m³`} />}
        {p.bc != null && <Row label={t("airQuality.blackCarbonLabel")} value={`${Number(p.bc).toFixed(1)} µg/m³`} />}
      </Section>

      <Section title={t("airQuality.gasesSectionTitle")}>
        {p.no != null && <Row label="NO" value={`${Number(p.no).toFixed(1)} ppb`} />}
        {p.no2 != null && <Row label="NO₂" value={`${Number(p.no2).toFixed(1)} ppb`} />}
        {p.nox != null && <Row label="NOx" value={`${Number(p.nox).toFixed(1)} ppb`} />}
        {p.so2 != null && <Row label="SO₂" value={`${Number(p.so2).toFixed(1)} ppb`} />}
        {p.o3 != null && <Row label="O₃" value={`${Number(p.o3).toFixed(1)} ppb`} />}
        {p.co != null && <Row label="CO" value={`${Number(p.co).toFixed(1)} ppb`} />}
        {p.co2 != null && <Row label="CO₂" value={`${Number(p.co2).toFixed(1)} ppm`} />}
        {p.ch4 != null && <Row label="CH₄" value={`${Number(p.ch4).toFixed(1)} ppb`} />}
        {p.ufp != null && <Row label="UFP" value={`${Number(p.ufp).toFixed(0)} particles/cm³`} />}
      </Section>

      <Section title={t("airQuality.meterologicalSectionTitle")}>
        {p.humidity != null && <Row label={t("airQuality.humidityLabel")}    value={`${Number(p.humidity).toFixed(1)} %`} />}
        {p.temperature != null && <Row label={t("airQuality.temperatureLabel")} value={`${Number(p.temperature).toFixed(1)} °C`} />}
      </Section>

      <Section title={t("airQuality.dataQualitySectionTitle")}>
        {p.coverage_pct != null && (
          <Row label={t("airQuality.coverageLabel")} value={
            <span className={`text-xs font-mono ${Number(p.coverage_pct) >= 80 ? "text-emerald-400" : Number(p.coverage_pct) >= 40 ? "text-amber-400" : "text-red-400"}`}>
              {Number(p.coverage_pct).toFixed(0)}%
            </span>
          } />
        )}
        {p.last_updated != null && <Row label={t("airQuality.readingTimeLabel")} value={fmtDate(String(p.last_updated))} />}
      </Section>

      <SourceAttribution link={sourceLinkFor("openaq", p)} />
      <ExternalLinks>
        {locId && <ExternalLink href={`https://explore.openaq.org/locations/${locId}`} label="OpenAQ station" />}
      </ExternalLinks>
    </>
  );
}

