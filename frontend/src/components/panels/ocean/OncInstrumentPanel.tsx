// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { sourceLinkFor } from "../../../utils/sourceUrl";

import { latLonFromProps } from "../shared/format";
import { Row, Section, Badge, PanelHeader, SourceAttribution } from "../shared/primitives";
import { SeafloorDepthRow } from "../shared/chips";

const ONC_CATEGORY_BLURBS: Record<string, string> = {
  "CTD": "Measures conductivity, temperature and depth — the backbone of ocean profiling.",
  "OXYSENSOR": "Measures dissolved oxygen concentration.",
  "HYDROPHONE": "Records underwater sound (marine mammals, ship noise, seismic events).",
  "ADCP": "Acoustic Doppler Current Profiler — measures 3D current velocity across the water column.",
  "CURRENTMETER": "Measures water current speed and direction at a point.",
  "FLUOROMETER": "Measures chlorophyll and dissolved organic matter via fluorescence.",
  "PHSENSOR": "Measures seawater pH (ocean acidification).",
  "CO2SENSOR": "Measures dissolved CO₂ (carbon cycle studies).",
  "TURBIDITYMETER": "Measures water clarity / suspended sediment.",
  "NITRATESENSOR": "Measures dissolved nitrate concentration.",
  "METEOROLOGICAL": "Surface weather — wind, air temperature, pressure, humidity.",
  "SEISMOMETER": "Records earthquakes and seafloor ground motion.",
  "BPR": "Bottom Pressure Recorder — tsunami detection and tide measurement.",
  "HYDROPHONE_ARRAY": "Multi-element hydrophone array for directional acoustic recording.",
  "CAMERA": "Underwater video / still imagery for biological and habitat observation.",
  "ICEPROFILER": "Upward-looking sonar measuring sea-ice draft and thickness.",
  "ACOUSTICRECEIVER": "Listens for coded acoustic tags from tracked marine animals.",
  "ACOUSTICDOPPLERCURRENTPROFILER": "Acoustic Doppler Current Profiler — measures 3D current velocity.",
  "RADIOMETER": "Measures incoming light (PAR, UV, surface radiation).",
  "MAGNETOMETER": "Measures magnetic field variations.",
  // Chemistry/biology categories added with the 2026-09-08 full-breadth ONC ingest.
  "CDOM": "Measures coloured dissolved organic matter via fluorescence.",
  "CRUDEOILFLUOROMETER": "Fluorometer tuned to detect crude oil in seawater.",
  "REFINEDFUELSFLUOROMETER": "Fluorometer tuned to detect refined fuel products in seawater.",
  "TRANSMISSOMETER": "Measures light transmission — water clarity / particulate load.",
  "TURBCHLFL": "Combined turbidity and chlorophyll fluorescence sensor.",
  "PARTANALYZER": "Analyses suspended particle size and abundance.",
  "SEDTRAP": "Sediment trap — collects settling particulate matter over time.",
  "WATERSAMPLER": "Collects discrete water samples for lab analysis.",
  "WETLABS_WQM": "WET Labs water-quality monitor — multi-parameter optical sensor.",
  "PLANKTONSAMPLER": "Collects plankton samples in situ.",
  "PLANKTONCAMSYSTEM": "In situ camera system imaging plankton.",
  "CHEMINI": "Autonomous in situ chemical analyser (nutrients/metals).",
  "GTD": "Gas tension device — measures total dissolved gas pressure.",
  "METHSENSOR": "Measures dissolved methane concentration.",
  "BIOSPECTROMETER": "Spectrometer used for biological/optical measurements.",
  "MBIOSENSOR": "Microbial/biological sensor package.",
  "BARS": "Benthic and Riser Sensor package.",
  "BBES": "Benthic boundary environmental sensor package.",
  "UCRDS": "Underwater chemical/radiological detection system.",
  "UURS": "Underwater uranium/radiological survey system.",
  "UWVOLTAMMETRICSYSTEM": "Underwater voltammetric system — trace metal chemistry.",
};

function formatDate(value: unknown): string | null {
  if (value == null) return null;
  try {
    const d = new Date(String(value));
    if (isNaN(d.getTime())) return null;
    return d.toISOString().slice(0, 10);
  } catch { return null; }
}

export function OncInstrumentPanel({ properties: p }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation("panels");
  const category = p.device_category != null ? String(p.device_category) : null;
  // Match on upper-cased category words so display variants still hit the blurb map.
  const blurb = category
    ? ONC_CATEGORY_BLURBS[category.toUpperCase().replace(/[^A-Z0-9]/g, "")] ?? null
    : null;
  const start = formatDate(p.deployment_start);
  const end = formatDate(p.deployment_end);
  const status = p.status != null ? String(p.status) : null;
  const description = p.description != null ? String(p.description) : null;
  const products = Array.isArray(p.data_products) ? (p.data_products as Array<{code: string; name: string; help_url?: string}>) : [];
  const readings = Array.isArray(p.latest_readings) ? (p.latest_readings as Array<{code: string; label: string; value: number; unit?: string; time?: string}>) : [];
  const readingsAt = formatDate(p.readings_at);
  const deviceLink = p.device_link != null ? String(p.device_link) : null;
  const fmtValue = (v: number) => Math.abs(v) >= 100 ? v.toFixed(1) : Math.abs(v) >= 1 ? v.toFixed(2) : v.toFixed(3);

  return (
    <>
      <Badge
        label={`${t("oncInstrument.panelBadge")}${status ? ` • ${status}` : ""}`}
        color={status === "retired"
          ? "text-zinc-400 border-zinc-500/40"
          : "text-violet-300 border-violet-500/40"}
      />
      <PanelHeader>{String(p.device_name ?? p.device_code ?? "Instrument")}</PanelHeader>
      {/* Compact context strip — depth + station so the user knows what they're looking at */}
      {(p.depth_m != null || p.location_name != null) && (
        <div className="mb-2 text-xs text-zinc-400 flex flex-wrap gap-x-3 gap-y-0.5">
          {p.depth_m != null && (
            <span><span className="text-zinc-500">Depth:</span> <span className="text-zinc-200">{Math.round(Number(p.depth_m))} m</span></span>
          )}
          {p.location_name != null && (
            <span><span className="text-zinc-500">Station:</span> <span className="text-zinc-200">{String(p.location_name)}</span></span>
          )}
        </div>
      )}
      {/* Latest Readings — TOP priority. Real ocean values are what users come for. */}
      {readings.length > 0 ? (
        <Section title={`${t("onc.latestReadingsSectionTitle")}${readingsAt ? ` · ${readingsAt}` : ""}`}>
          <ul className="text-xs space-y-0.5">
            {readings.map((r) => (
              <li key={r.code} className="flex justify-between gap-2">
                <span className="text-zinc-400 truncate">{r.label}</span>
                <span className="text-zinc-100 font-mono whitespace-nowrap">
                  {fmtValue(r.value)}<span className="text-zinc-500"> {r.unit ?? ""}</span>
                </span>
              </li>
            ))}
          </ul>
        </Section>
      ) : (
        <p className="mb-3 text-xs text-zinc-500 italic">
          {t("oncInstrument.noReadingsText")}
        </p>
      )}
      {blurb && (
        <p className="mb-3 text-xs text-zinc-400 leading-relaxed">{blurb}</p>
      )}
      {(start || end) && (
        <Section title={t("oncInstrument.deploySectionTitle")}>
          {start && <Row label={t("oncInstrument.deployedLabel")} value={start} />}
          <Row label={t("oncInstrument.endedLabel")} value={end ?? "ongoing"} />
        </Section>
      )}
      <Section title={t("oncInstrument.deviceSectionTitle")}>
        {category != null && <Row label={t("oncInstrument.categoryLabel")} value={category} />}
        {p.device_code != null && <Row label={t("oncInstrument.codeLabel")} value={String(p.device_code)} />}
        {p.device_id != null && <Row label={t("oncInstrument.deviceIdLabel")} value={String(p.device_id)} />}
      </Section>
      {(p.site_name != null || p.location_code != null) && (
        <Section title={t("oncInstrument.locationSectionTitle")}>
          {p.site_name != null && <Row label={t("oncInstrument.siteLabel")} value={String(p.site_name)} />}
          {p.location_code != null && <Row label={t("oncInstrument.locationCodeLabel")} value={String(p.location_code)} />}
          {(() => { const c = latLonFromProps(p); return c && <SeafloorDepthRow lat={c[0]} lon={c[1]} />; })()}
        </Section>
      )}
      {p.image_url != null && (
        <div className="mb-3">
          <img
            src={String(p.image_url)}
            alt={String(p.device_name ?? "")}
            className="w-full rounded-lg object-cover max-h-28"
            onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
          />
        </div>
      )}
      {products.length > 0 && (
        <Section title={t("oncInstrument.dataProductsSectionTitle")}>
          <ul className="text-xs text-zinc-300 space-y-0.5 list-disc list-inside">
            {products.slice(0, 10).map((dp) => (
              <li key={dp.code}>
                {dp.help_url ? (
                  <a href={dp.help_url} target="_blank" rel="noopener noreferrer"
                     className="text-violet-300 hover:text-violet-200 underline underline-offset-2">
                    {dp.name}
                  </a>
                ) : dp.name}
                <span className="text-zinc-500"> · {dp.code}</span>
              </li>
            ))}
            {products.length > 10 && (
              <li className="text-zinc-500">+{products.length - 10} more</li>
            )}
          </ul>
        </Section>
      )}
      {deviceLink && (
        <div className="mt-3 flex flex-wrap gap-2 text-xs">
          <a href={deviceLink} target="_blank" rel="noopener noreferrer"
             className="px-2.5 py-1 rounded border border-violet-500/40 text-violet-200 hover:bg-violet-500/10">
            Device on ONC ↗
          </a>
        </div>
      )}
      {description && (
        <p className="mt-3 text-[11px] text-zinc-500 leading-relaxed italic">
          Cite: {description}
        </p>
      )}
      <SourceAttribution link={sourceLinkFor("onc-instrument", p)} />
    </>
  );
}

