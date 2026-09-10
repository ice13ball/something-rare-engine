// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { fmtDate } from "../shared/format";
import { Row, Section, Badge, PanelHeader, ExternalLink, ExternalLinks, SourceAttribution } from "../shared/primitives";
import { sourceLinkFor } from "../../../utils/sourceUrl";

// ⛔ Every gas row below printed a hardcoded "ppb". OpenAQ publishes whatever
// the operator reports, and ppb is the rare case: measured on production
// 2026-09-10, NO2 was ppb on 586 of 12,793 stations, O3 on 7 of 10,282.
// The label was a unit OpenAQ never gave us, on ~95% of those rows.
// `units` now travels with the feature; the published unit is shown verbatim,
// and a pollutant whose unit the source omitted says so instead of borrowing
// one. ⛔ The value itself is never converted here — this portal mirrors its
// sources 1:1; the AQI colour does its own conversion for the EPA scale.
function reading(
  value: unknown,
  units: Record<string, string> | null,
  key: string,
  fallback?: string,
): string | null {
  if (typeof value !== "number") return null;
  const unit = units?.[key] ?? fallback ?? null;
  const digits = key === "ufp" ? 0 : 1;
  return unit ? `${value.toFixed(digits)} ${unit}` : `${value.toFixed(digits)}`;
}

export function AirQualityPanel({ properties: p }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation("panels");
  const units = (p.units ?? null) as Record<string, string> | null;
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
        {reading(p.pm1, units, "pm1", "µg/m³") !== null && <Row label="PM1" value={reading(p.pm1, units, "pm1", "µg/m³")!} />}
        {reading(p.pm25, units, "pm25", "µg/m³") !== null && <Row label="PM2.5" value={reading(p.pm25, units, "pm25", "µg/m³")!} />}
        {reading(p.pm4, units, "pm4", "µg/m³") !== null && <Row label="PM4" value={reading(p.pm4, units, "pm4", "µg/m³")!} />}
        {reading(p.pm10, units, "pm10", "µg/m³") !== null && <Row label="PM10" value={reading(p.pm10, units, "pm10", "µg/m³")!} />}
        {reading(p.bc, units, "bc", "µg/m³") !== null && <Row label={t("airQuality.blackCarbonLabel")} value={reading(p.bc, units, "bc", "µg/m³")!} />}
      </Section>

      <Section title={t("airQuality.gasesSectionTitle")}>
        {reading(p.no, units, "no") !== null && <Row label="NO" value={reading(p.no, units, "no")!} />}
        {reading(p.no2, units, "no2") !== null && <Row label="NO₂" value={reading(p.no2, units, "no2")!} />}
        {reading(p.nox, units, "nox") !== null && <Row label="NOx" value={reading(p.nox, units, "nox")!} />}
        {reading(p.so2, units, "so2") !== null && <Row label="SO₂" value={reading(p.so2, units, "so2")!} />}
        {reading(p.o3, units, "o3") !== null && <Row label="O₃" value={reading(p.o3, units, "o3")!} />}
        {reading(p.co, units, "co") !== null && <Row label="CO" value={reading(p.co, units, "co")!} />}
        {reading(p.co2, units, "co2") !== null && <Row label="CO₂" value={reading(p.co2, units, "co2")!} />}
        {reading(p.ch4, units, "ch4") !== null && <Row label="CH₄" value={reading(p.ch4, units, "ch4")!} />}
        {reading(p.ufp, units, "ufp", "particles/cm³") !== null && <Row label="UFP" value={reading(p.ufp, units, "ufp", "particles/cm³")!} />}
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

