// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { Linkify } from "../../../utils/linkify";

import { Row, Section, Badge, PanelHeader } from "../shared/primitives";
import { MiniLineChart } from "./shared";

const SOURCE_LABEL: Record<string, string> = {
  arcticgro:    "ArcticGRO",
  pangaea_lena: "PANGAEA (Lena)",
  pangaea_caa:  "PANGAEA (Canadian Arctic)",
};

const SOURCE_COLOR: Record<string, string> = {
  arcticgro:    "text-sky-300 border-sky-500/40",
  pangaea_lena: "text-violet-300 border-violet-500/40",
  pangaea_caa:  "text-amber-300 border-amber-500/40",
};


// Canonical biogeochem parameter keys → display label + unit. Keys come from
// ARCTICGRO_PARAM_MAP / PANGAEA_PARAM_MAP in backend/ingestion/arctic_rivers.py.
const ARCTIC_PARAM_META: Record<string, { label: string; unit: string }> = {
  // Units are the ArcticGRO source units (mass concentration, not molar). These are
  // FALLBACKS — the panel prefers per-station `units` captured verbatim at ingest.
  doc:        { label: "DOC",          unit: "mg/L" },
  tdn:        { label: "TDN",          unit: "mg/L" },
  no3:        { label: "NO₃⁻",         unit: "µg/L as N" },
  nh4:        { label: "NH₄⁺",         unit: "µg/L as N" },
  tdp:        { label: "TDP",          unit: "µg/L as P" },
  srp:        { label: "SRP",          unit: "µg/L as P" },
  po4:        { label: "PO₄³⁻",        unit: "µg/L as P" },
  sio2:       { label: "SiO₂",         unit: "mg/L" },
  dsi:        { label: "Si(OH)₄",      unit: "mg/L" },
  alkalinity: { label: "Alkalinity",   unit: "mg CaCO₃/L" },
  // Physical / water-isotope properties (PANGAEA CAA)
  d18o:       { label: "δ¹⁸O",         unit: "‰" },
  dd:         { label: "δD",           unit: "‰" },
  temp:       { label: "Temperature",  unit: "°C" },
  ec:         { label: "Conductivity", unit: "µS/cm" },
};
const ARCTIC_PARAM_ORDER = ["doc", "tdn", "no3", "nh4", "tdp", "srp", "po4", "sio2", "dsi", "alkalinity", "d18o", "dd", "temp", "ec"];
// Params shown under "Water Properties" instead of "Biogeochemistry".
const ARCTIC_PHYS_PARAMS = new Set(["d18o", "dd", "temp", "ec"]);
const orderArcticParams = (obj: Record<string, unknown>): string[] => [
  ...ARCTIC_PARAM_ORDER.filter((k) => k in obj),
  ...Object.keys(obj).filter((k) => !ARCTIC_PARAM_ORDER.includes(k)),
];

export function ArcticRiverPanel({ properties: p }: { properties: Record<string, unknown> }) {
  const src       = String(p.source ?? "");
  const badgeLabel = SOURCE_LABEL[src] ?? src;
  const badgeColor = SOURCE_COLOR[src] ?? "text-sky-300 border-sky-500/40";

  // discharge_monthly: array of [YYYY-MM, value] | null
  const dischargeSeries = Array.isArray(p.discharge_monthly)
    ? (p.discharge_monthly as [string, number][]).filter(([, v]) => v != null)
    : null;

  // biogeochem_monthly: object of { param: [[YYYY-MM, val]] } | null
  const biogeoObj = p.biogeochem_monthly != null && typeof p.biogeochem_monthly === "object"
    ? (p.biogeochem_monthly as Record<string, [string, number][]>)
    : null;

  // summary_stats: object of { param: meanValue } — the actual measured values.
  // CAA stations are single-visit grab samples (one point per param), so the
  // monthly charts below can't draw; these rows surface the values regardless.
  const summaryObj = p.summary_stats != null && typeof p.summary_stats === "object"
    ? (p.summary_stats as Record<string, number>)
    : null;

  // units: object { param: sourceUnitString } captured verbatim from the dataset
  // (ArcticGRO posts mass concentration, e.g. tdn→"mg/L", no3→"ug/L as N"). Prefer
  // these over the hardcoded fallback so we never misrepresent the provider's units.
  const unitsObj = p.units != null && typeof p.units === "object"
    ? (p.units as Record<string, string>)
    : null;
  const prettyUnit = (u: string): string =>
    u.replace(/\bug\//g, "µg/").replace(/CaCO3/g, "CaCO₃").replace(/\bdeg C\b/g, "°C");
  const unitFor = (param: string): string => {
    const src = unitsObj?.[param];
    if (src) return prettyUnit(src);
    return ARCTIC_PARAM_META[param]?.unit ?? "";
  };

  // annual_fluxes: object { water_km3, doc_gg, tn_gg, tp_gg, ... } | null
  const fluxes = p.annual_fluxes != null && typeof p.annual_fluxes === "object"
    ? (p.annual_fluxes as Record<string, number>)
    : null;

  const riverName = String(p.river_name ?? "");
  const siteLabel = String(p.site_label ?? "");

  return (
    <>
      <Badge label={badgeLabel} color={badgeColor} />
      <PanelHeader>{riverName ? `${riverName} River` : siteLabel || "Arctic River Station"}</PanelHeader>

      <Section title="Station">
        {riverName  && <Row label="River"      value={riverName} />}
        {siteLabel  && <Row label="Station"    value={siteLabel} />}
        {p.source   != null && <Row label="Source"     value={badgeLabel} />}
        {(p.record_start != null || p.record_end != null) && (
          <Row
            label="Record"
            value={`${p.record_start ?? "?"} – ${p.record_end ?? "?"}`}
          />
        )}
        {p.lat != null && p.lon != null && (
          <Row label="Lat / Lon" value={`${Number(p.lat).toFixed(4)}°, ${Number(p.lon).toFixed(4)}°`} />
        )}
      </Section>

      {/* Discharge sparkline */}
      {dischargeSeries && dischargeSeries.length >= 2 && (
        <Section title="Monthly Discharge">
          <MiniLineChart data={dischargeSeries} label="Discharge" unit="m³/s" color="#38bdf8" />
        </Section>
      )}

      {/* Biogeochemistry + Water Properties — measured values, plus monthly
          trend charts when a real time series exists. Single-visit stations
          (PANGAEA CAA) only show value rows; ArcticGRO time series add charts.
          discharge_m3s lives in summary_stats but is shown in its own
          "Monthly Discharge" section above — kept out of these tables. */}
      {summaryObj && (() => {
        const params = orderArcticParams(summaryObj)
          .filter((k) => !k.toLowerCase().includes("discharge"))
          .filter((k) => {
            const v = summaryObj[k];
            return v != null && Number.isFinite(Number(v));
          });
        const valueRow = (param: string) => {
          const v = summaryObj[param];
          const meta = ARCTIC_PARAM_META[param] ?? { label: param.toUpperCase(), unit: "" };
          const unit = unitFor(param);
          return (
            <Row
              key={param}
              label={meta.label}
              value={`${Number(v).toLocaleString(undefined, { maximumFractionDigits: 3 })}${unit ? ` ${unit}` : ""}`}
            />
          );
        };
        const bioParams  = params.filter((k) => !ARCTIC_PHYS_PARAMS.has(k));
        const physParams = params.filter((k) => ARCTIC_PHYS_PARAMS.has(k));
        return (
          <>
            {bioParams.length > 0 && (
              <Section title="Biogeochemistry">
                {bioParams.map(valueRow)}
                {biogeoObj && bioParams.map((param) => {
                  const series = (biogeoObj[param] ?? []).filter(([, v]) => v != null);
                  if (series.length < 2) return null;
                  const meta = ARCTIC_PARAM_META[param] ?? { label: param.toUpperCase(), unit: "" };
                  return (
                    <MiniLineChart
                      key={`chart-${param}`}
                      data={series}
                      label={meta.label}
                      unit={unitFor(param)}
                      color={param.toLowerCase().startsWith("doc") ? "#a78bfa" : "#fbbf24"}
                    />
                  );
                })}
              </Section>
            )}
            {physParams.length > 0 && (
              <Section title="Water Properties">
                {physParams.map(valueRow)}
                {(physParams.includes("d18o") || physParams.includes("dd")) && (
                  <p className="text-[11px] text-white/60 leading-relaxed mt-1.5">
                    δ¹⁸O and δD are stable water-isotope ratios (per mil, ‰, relative to
                    ocean water). Strongly negative values point to snow and glacial
                    meltwater — a fingerprint of where the river's freshwater comes from.
                  </p>
                )}
              </Section>
            )}
          </>
        );
      })()}

      {/* Annual flux table */}
      {fluxes && Object.keys(fluxes).length > 0 && (
        <Section title="Annual Fluxes">
          {fluxes.water_km3   != null && <Row label="Water"         value={`${Number(fluxes.water_km3).toLocaleString()} km³/yr`} />}
          {Object.entries(fluxes)
            .filter(([k]) => k.endsWith("_gg"))
            .map(([k, v]) => (
              <Row key={k} label={k.replace("_gg", "").toUpperCase()} value={`${Number(v).toLocaleString()} Gg/yr`} />
            ))}
        </Section>
      )}

      {/* Citation — mandatory attribution */}
      {p.citation != null && (
        <Section title="Citation">
          <p className="text-[11px] text-white/75 leading-relaxed break-words"><Linkify text={String(p.citation)} /></p>
        </Section>
      )}

      {/* Source links */}
      <p className="text-[11px] text-white/65 mt-2">
        {src === "arcticgro" ? (
          <>
            Source:{" "}
            <a href="https://arcticgreatrivers.org" target="_blank" rel="noopener noreferrer" className="text-sky-400 hover:underline">
              Arctic Great Rivers Observatory ↗
            </a>
          </>
        ) : (
          <>
            Source:{" "}
            <a href="https://pangaea.de" target="_blank" rel="noopener noreferrer" className="text-sky-400 hover:underline">
              PANGAEA ↗
            </a>
          </>
        )}
      </p>
    </>
  );
}
