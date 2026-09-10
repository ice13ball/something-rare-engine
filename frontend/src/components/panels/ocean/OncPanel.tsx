// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { sourceLinkFor } from "../../../utils/sourceUrl";

import { Sparkline } from "../../charts/Sparkline";
import { AdcpHeatmap } from "../../charts/AdcpHeatmap";
import { ProfilePlot } from "../../charts/ProfilePlot";
import type { ProfileVariable } from "../../charts/ProfilePlot";

import { API } from "../shared/tokens";
import { latLonFromProps } from "../shared/format";
import { Row, Section, Badge, PanelHeader, BodyText, SourceAttribution } from "../shared/primitives";
import { SeafloorDepthRow } from "../shared/chips";

interface OncSensor {
  value: number; unit: string | null; label: string; time: string | null;
  // ONC's QAQC flag for this sample. `undefined` on readings cached before we
  // started keeping it; `null` when ONC sent no flag at all. Neither is 0 —
  // 0 is ONC saying "we ran no QC", which is a different statement.
  qc?: number | null;
}

// ⛔ ONC calls flags 3 and 4 "poor quality data". Only those two are doubt.
// 7 (averaged) and 8 (interpolated) are processing notes, NOT errors, and
// marking them would cry wolf on most of a healthy station.
// Scale: https://wiki.oceannetworks.ca/display/DP/Quality+Assurance+Quality+Control
// ⛔ "We fetched nothing" and "there is nothing to fetch" must not share one
// message. 1,338 ONC locations show no readings, and for 960 of them that is
// not our failure — the instruments there do not publish a scalar measurement
// at all. Measured on production 2026-09-10 across every location: of the 960
// carrying ONLY the categories below, **zero** have ever produced a reading.
//
// ⚠️ The list is short on purpose. Each entry was checked for counterexamples
// and the ones that failed were dropped:
//   - JB / Junction Box — REMOVED. Three of them (PBY, SGDLS, YPVPF.J1) do
//     publish a pressure reading, so "infrastructure, no sensor" would be a
//     false claim about them.
//   - ACCELEROMETER — never added. ZEBA.W1 returns "JMA Intensity Amplitude";
//     ONC has scalar data there, our own property allowlist simply does not
//     recognise it. That is a gap on our side, not an absence on theirs, and
//     the two must not be dressed in the same sentence.
type NoScalarKey =
  | "onc.noScalarDrifter"
  | "onc.noScalarAis"
  | "onc.noScalarHydrophone"
  | "onc.noScalarInfrastructure"
  | "onc.noScalarGeneric";

const ONC_NON_SCALAR: Record<string, NoScalarKey> = {
  DRIFTER:         "onc.noScalarDrifter",
  AISRECEIVER:     "onc.noScalarAis",
  HYDROPHONE:      "onc.noScalarHydrophone",
  ADAPTER:         "onc.noScalarInfrastructure",
  CAMLIGHTS:       "onc.noScalarInfrastructure",
  "CAMERA LIGHTS": "onc.noScalarInfrastructure",
};

/** The reason ONC publishes no scalar reading here, or null if we cannot say. */
function noScalarReasonKey(categories: unknown): NoScalarKey | null {
  if (!Array.isArray(categories) || categories.length === 0) return null;
  const keys = new Set<NoScalarKey>();
  for (const raw of categories) {
    const key = ONC_NON_SCALAR[String(raw).toUpperCase()];
    if (!key) return null;          // one unexplained category ⇒ we cannot claim anything
    keys.add(key);
  }
  // Several kinds of non-scalar instrument on one location: say the general
  // thing rather than picking one of them and implying it is the only one.
  return keys.size === 1 ? [...keys][0] : "onc.noScalarGeneric";
}

const ONC_DOUBTFUL_FLAGS = new Set([3, 4]);
const isDoubtful = (qc: number | null | undefined) =>
  typeof qc === "number" && ONC_DOUBTFUL_FLAGS.has(qc);

// Keys are ONC propertyCodes, and this list only sets ORDER — anything absent
// still renders, appended after these (see sensorKeys below). Kept in "what a
// reader looks for first" order: core hydrography, then chemistry, then optics.
// ⚠️ `seawatertemperature` and `temperature` are two distinct ONC properties;
// both appear here on purpose rather than being merged, because ONC labels and
// measures them separately.
const SENSOR_ORDER = [
  "temperature", "seawatertemperature", "salinity", "pressure", "oxygen",
  "density", "sigmat", "sigmatheta", "conductivity", "soundspeed",
  "ph", "redox", "nitrateconcentration",
  "co2concentration", "co2concentrationlinearized", "co2partialpressure",
  "methaneconcentration", "methanemolarconcentration", "methanepartialpressure",
  "chlorophyll", "cdom", "cdomfluorescence", "fluorescence",
  "turbidityntu", "turbidityftu", "turbidity",
  "par", "parphotonbased", "absorbance", "beamattenuationcoefficient",
  "crudeoilfluoroscence", "refinedfuelfluorescene",
];

interface SparklineData { unit: string; samples: [number, number][] }
interface AdcpData {
  device_code: string;
  bin_count: number;
  window_start: string;
  window_end: string;
  variable: string | null;
  units: string | null;
  depths: number[];
  strip: (number | null)[][];
}
interface CtdCast { device_code: string; cast_time: string; profile: Record<string, (number | null)[]> }

interface EarthquakeRow {
  usgs_id: string;
  occurred_at: string;
  magnitude: number | null;
  depth_km: number | null;
  place: string;
  distance_km: number;
}

function magColor(m: number | null) {
  if (m == null) return "text-white/65";
  if (m >= 5) return "text-red-400";
  if (m >= 4) return "text-amber-400";
  return "text-white/70";
}

export function OncPanel({ properties: p }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation("panels");
  const locationCode = String(p.location_code ?? "");
  const sensors = (p.latest_sensors ?? {}) as Record<string, OncSensor>;
  const fetchedAt = p.sensors_fetched_at ? String(p.sensors_fetched_at) : null;

  const sensorKeys = SENSOR_ORDER.filter(k => k in sensors)
    .concat(Object.keys(sensors).filter(k => !SENSOR_ORDER.includes(k)));

  // Lazy-fetch enrichment data when panel opens
  const [sparklines, setSparklines] = useState<Record<string, SparklineData> | null>(null);
  const [adcp, setAdcp] = useState<AdcpData | null>(null);
  const [adcpLoaded, setAdcpLoaded] = useState(false);
  const [ctdCasts, setCtdCasts] = useState<CtdCast[] | null>(null);
  const [earthquakes, setEarthquakes] = useState<EarthquakeRow[] | null>(null);

  useEffect(() => {
    if (!locationCode) return;

    Promise.all([
      fetch(`${API}/api/v1/onc/sparkline/${encodeURIComponent(locationCode)}`)
        .then(r => r.ok ? r.json() : {}).then(setSparklines).catch(() => setSparklines({})),
      fetch(`${API}/api/v1/onc/adcp-strip/${encodeURIComponent(locationCode)}`)
        .then(r => r.ok ? r.json() : null).then(d => { setAdcp(d ?? null); setAdcpLoaded(true); }).catch(() => setAdcpLoaded(true)),
      fetch(`${API}/api/v1/onc/ctd/${encodeURIComponent(locationCode)}`)
        .then(r => r.ok ? r.json() : []).then(setCtdCasts).catch(() => setCtdCasts([])),
      fetch(`${API}/api/v1/onc/earthquakes-near/${encodeURIComponent(locationCode)}?radius_km=200&days=30`)
        .then(r => r.ok ? r.json() : []).then(setEarthquakes).catch(() => setEarthquakes([])),
    ]);
  }, [locationCode]);

  // Build sparkline samples per sensor key
  const sparklineBySensor = useMemo(() => {
    if (!sparklines) return {} as Record<string, SparklineData>;
    return sparklines;
  }, [sparklines]);

  // Build CTD ProfilePlot variables from most recent cast
  const ctdVariables: ProfileVariable[] = useMemo(() => {
    const cast = ctdCasts?.[0];
    if (!cast?.profile) return [];
    const VARIABLE_CONFIGS: Record<string, { label: string; unit: string; color: string }> = {
      temperature: { label: "Temp",     unit: "°C",   color: "#f97316" },
      salinity:    { label: "Salinity", unit: "PSU",  color: "#38bdf8" },
      oxygen:      { label: "O₂",       unit: "mL/L", color: "#4ade80" },
    };
    return Object.entries(VARIABLE_CONFIGS)
      .filter(([key]) => Array.isArray(cast.profile[key]) && cast.profile[key].length > 0)
      .map(([key, cfg]) => ({
        key,
        label:  cfg.label,
        unit:   cfg.unit,
        color:  cfg.color,
        values: (cast.profile[key] as (number | null)[]).map(v => v ?? 0),
      }));
  }, [ctdCasts]);

  const ctdDepths = useMemo(() => {
    const cast = ctdCasts?.[0];
    return (cast?.profile?.depth ?? []) as number[];
  }, [ctdCasts]);

  return (
    <>
      <Badge label={t("onc.panelBadge")} color="text-teal-300 border-teal-500/40" />
      <PanelHeader>{String(p.name ?? locationCode ?? "—")}</PanelHeader>
      <Section title={t("onc.stationSectionTitle")}>
        <Row label={t("onc.locationCodeLabel")} value={locationCode} />
        {p.depth_m != null && <Row label={t("onc.depthLabel")} value={`${Math.round(Number(p.depth_m)).toLocaleString()} m`} />}
        {(() => { const c = latLonFromProps(p); return c && <SeafloorDepthRow lat={c[0]} lon={c[1]} />; })()}
      </Section>

      <Section title={t("onc.latestReadingsSectionTitle")}>
        {sensorKeys.length === 0 ? (
          <p className="text-xs text-white/65 italic">
            {t(noScalarReasonKey(p.device_categories) ?? "onc.noReadingsText")}{" "}
            <a href={`https://data.oceannetworks.ca/DataSearch?locationCode=${locationCode}`}
               target="_blank" rel="noopener noreferrer"
               className="text-teal-400 underline">ONC portal ↗</a>
          </p>
        ) : (
          <>
            {sensorKeys.map(key => {
              const s = sensors[key];
              const decimals = key === "pressure" ? 1 : 2;
              const sl = sparklineBySensor[key];
              const slSamples = Array.isArray(sl?.samples)
                ? sl.samples.map(([t, v]: [number, number]) => ({ t, v }))
                : [];
              return (
                <div key={key} className="flex items-center justify-between py-0.5">
                  <span className="text-[12px] text-white/70">{s.label}</span>
                  <div className="flex items-center gap-2">
                    {slSamples.length > 1 && (
                      <Sparkline samples={slSamples} color="#2dd4bf" width={80} height={24} />
                    )}
                    {/* ⛔ The value stays visible. ONC's own doubt is shown
                        beside it, not used to hide it — hiding would put
                        "no reading" and "doubtful reading" back on one path. */}
                    {isDoubtful(s.qc) && (
                      <span
                        className="text-[10px] px-1 rounded bg-amber-500/20 text-amber-300 border border-amber-400/30"
                        title={t("onc.qcDoubtfulTooltip", { flag: s.qc })}
                      >
                        {t("onc.qcDoubtfulBadge")}
                      </span>
                    )}
                    <span
                      className={
                        isDoubtful(s.qc)
                          ? "text-[12px] text-amber-300/90 font-mono"
                          : "text-[12px] text-white/90 font-mono"
                      }
                    >
                      {s.value.toFixed(decimals)} {s.unit}
                    </span>
                  </div>
                </div>
              );
            })}
            {/* ⛔ One "as of" for the whole panel was a claim we could not
                support once readings started arriving from several instrument
                categories, each its own API call with its own sample time.
                Show the span when the readings really do differ, and a single
                date only when they genuinely share one. */}
            {(() => {
              const times = sensorKeys
                .map(k => sensors[k]?.time)
                .filter((t): t is string => Boolean(t))
                .sort();
              if (!times.length) return fetchedAt ? (
                <p className="text-xs text-white/60 mt-1">
                  Fetched {fetchedAt.slice(0, 16).replace("T", " ")} UTC · ONC gave no measurement time
                </p>
              ) : null;
              const first = times[0].slice(0, 16).replace("T", " ");
              const last = times[times.length - 1].slice(0, 16).replace("T", " ");
              return (
                <p className="text-xs text-white/60 mt-1">
                  {first === last
                    ? `Measured ${first} UTC`
                    : `Measured ${first} — ${last} UTC (readings differ in age)`}
                </p>
              );
            })()}
            {sparklines === null && (
              <p className="text-[10px] text-white/50 mt-1 italic">Loading trends…</p>
            )}
          </>
        )}
      </Section>

      {/* ADCP backscatter */}
      {adcpLoaded && adcp !== null && (
        <Section title={t("onc.adcpSectionTitle")}>
          <p className="text-[10px] text-white/60 mb-1">
            {adcp.bin_count} depth bins · mean backscatter{adcp.units ? ` (${adcp.units})` : ""}
          </p>
          <AdcpHeatmap
            strip={adcp.strip}
            depths={adcp.depths}
            units={adcp.units ?? undefined}
            windowStart={adcp.window_start}
            windowEnd={adcp.window_end}
          />
        </Section>
      )}

      {/* CTD profile */}
      {ctdCasts !== null && ctdCasts.length > 0 && ctdVariables.length > 0 && (
        <Section title={t("onc.ctdSectionTitle")}>
          <ProfilePlot
            depths={ctdDepths}
            variables={ctdVariables}
            castTime={ctdCasts[0].cast_time}
          />
        </Section>
      )}

      {/* Earthquakes */}
      {earthquakes !== null && earthquakes.length > 0 && (
        <Section title={t("onc.earthquakesSectionTitle")}>
          <div className="space-y-1">
            {earthquakes.slice(0, 8).map(eq => (
              <div key={eq.usgs_id} className="flex items-center justify-between text-[11px]">
                <span className={`font-mono font-bold ${magColor(eq.magnitude)}`}>
                  M{eq.magnitude?.toFixed(1) ?? "?"}
                </span>
                <span className="text-white/70 flex-1 mx-2 truncate">{eq.place}</span>
                <span className="text-white/60 shrink-0">{eq.distance_km} km</span>
              </div>
            ))}
          </div>
          <p className="text-[10px] text-white/50 mt-1">
            {earthquakes.length} event{earthquakes.length !== 1 ? "s" : ""} total
          </p>
        </Section>
      )}

      <BodyText>{t("onc.body")}</BodyText>
      <SourceAttribution link={sourceLinkFor("onc-location", p)} />
    </>
  );
}

