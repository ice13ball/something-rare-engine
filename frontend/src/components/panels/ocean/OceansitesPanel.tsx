// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { tEnum } from "../../../utils/translateEnum";
import { sourceLinkFor } from "../../../utils/sourceUrl";

import { Row, Section, Badge, PanelHeader, BodyText, WarningBanner, SourceAttribution } from "../shared/primitives";

// ⛔ `sensor_models` repeats models ON PURPOSE. A mooring carries the same
// instrument at several depths, so "SEABIRD_SBE37" seven times is seven real
// instruments, not a source bug — deduplicating it would quietly discard the
// size of the array. The raw string reaches 1,837 characters (mean 265), which
// no side panel can show, so group and count instead: same multiset, readable.
function groupSensorModels(raw: string): string {
  const counts = new Map<string, number>();
  for (const model of raw.split(",").map(m => m.trim()).filter(Boolean)) {
    counts.set(model, (counts.get(model) ?? 0) + 1);
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([model, n]) => (n > 1 ? `${model} ×${n}` : model))
    .join(", ");
}

export function OceansitesPanel({ properties: p }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation(["panels", "enums"]);
  const obs = p.latest_obs as Record<string, unknown> | null | undefined;
  const fetchedAt = p.obs_fetched_at ? String(p.obs_fetched_at) : null;
  const obsSource = p.obs_source ? String(p.obs_source) : null;

  const obsAgeDays = obs?.obs_time
    ? Math.floor((Date.now() - new Date(String(obs.obs_time)).getTime()) / 86_400_000)
    : null;
  // PMEL/GDAC daily data lags QC by days-to-weeks; bump stale threshold for those.
  const staleThreshold = obsSource === "PMEL" || obsSource === "GDAC" ? 45 : 14;
  const isStale = obsAgeDays !== null && obsAgeDays > staleThreshold;

  const sourceLabel = obsSource === "NDBC"
    ? "NDBC (live, ~1-3h fresh)"
    : obsSource === "PMEL"
    ? "NOAA PMEL ERDDAP (TAO/PIRATA/RAMA, daily QC'd)"
    : obsSource === "GDAC"
    ? "OceanSITES GDAC THREDDS (IFREMER NetCDF)"
    : obsSource;

  return (
    <>
      <Badge label={t("oceansites.panelBadge")} color="text-cyan-300 border-cyan-500/40" />
      <PanelHeader>{String(p.name ?? p.ref ?? "—")}</PanelHeader>
      <Section title={t("oceansites.stationSectionTitle")}>
        <Row label={t("oceansites.referenceLabel")} value={String(p.ref ?? "—")} />
        {/* ⚠️ Conditional on purpose: only 340 of 1,072 stations carry a WIGOS
            identifier and 482 a deploy ship. An em dash on the other 700 would
            read as "we failed to fetch it" rather than "the source has none". */}
        {p.wigos_id != null && <Row label={t("oceansites.wigosLabel")} value={String(p.wigos_id)} />}
        <Row label={t("oceansites.statusLabel")}    value={tEnum(t, "status", String(p.status ?? ""))} />
        <Row label={t("oceansites.networkLabel")}   value={String(p.network ?? "—")} />
        {p.country != null && <Row label={t("oceansites.countryLabel")} value={String(p.country)} />}
        {p.deploy_date != null && <Row label={t("oceansites.deployedLabel")} value={String(p.deploy_date).slice(0, 10)} />}
        {p.deploy_ship != null && <Row label={t("oceansites.deployShipLabel")} value={String(p.deploy_ship)} />}
        {typeof p.deployment_count === "number" && p.deployment_count > 0 && (
          <Row label={t("oceansites.deploymentCountLabel")} value={String(p.deployment_count)} />
        )}
        {p.sensor_models != null && String(p.sensor_models).trim() !== "" && (
          <Row label={t("oceansites.sensorModelsLabel")} value={groupSensorModels(String(p.sensor_models))} />
        )}
      </Section>
      <Section title={t("oceansites.latestObservationsSectionTitle")}>
        {obs ? (
          <>
            {obs.obs_time && <Row label={t("oceansites.obsTimeLabel")} value={String(obs.obs_time)} />}
            {sourceLabel && <Row label={t("oceansites.sourceLabel")} value={sourceLabel} />}
            {isStale && (
              <WarningBanner color="orange">
                {t("oceansites.staleWarning", { days: obsAgeDays })} {obsSource === "PMEL" || obsSource === "GDAC"
                  ? "QC'd daily archives lag real-time by days-to-weeks — values older than ~6 weeks usually mean the buoy is offline for maintenance or recovery."
                  : "NDBC has stopped receiving transmissions from this buoy — it may be offline for maintenance or recovery."}
              </WarningBanner>
            )}
            {obs.wtmp != null && <Row label={t("oceansites.seaTempLabel")}  value={`${Number(obs.wtmp).toFixed(1)} °C`} />}
            {obs.atmp != null && <Row label={t("oceansites.airTempLabel")}  value={`${Number(obs.atmp).toFixed(1)} °C`} />}
            {obs.wspd != null && obs.wdir != null && (
              <Row label={t("oceansites.windLabel")} value={`${Number(obs.wspd).toFixed(1)} m/s from ${obs.wdir}°`} />
            )}
            {obs.wvht != null && <Row label={t("oceansites.waveHeightLabel")} value={`${Number(obs.wvht).toFixed(1)} m`} />}
            {obs.pres != null && <Row label={t("oceansites.pressureLabel")}   value={`${Number(obs.pres).toFixed(1)} hPa`} />}
            {obs.sss != null && <Row label={t("oceansites.salinityLabel")} value={`${Number(obs.sss).toFixed(2)} PSU`} />}
            {fetchedAt && (
              <p className="text-xs text-white/60 mt-1">
                Cached {fetchedAt.slice(0, 10)}
              </p>
            )}
          </>
        ) : (
          <p className="text-xs text-white/65 italic">{t("oceansites.noObservationsText")}</p>
        )}
      </Section>
      <BodyText>{t("oceansites.body")}</BodyText>
      <SourceAttribution link={sourceLinkFor("oceansites-platform", p)} />
    </>
  );
}

