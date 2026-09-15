// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { CONTRACTOR_CODES, CONTRACTOR_COLORS, FALLBACK_CONTRACTOR_COLOR, UNPARSED_CONTRACTOR_KEY } from "../../utils/contractorColors";
import { AIS_SHIP_CLASSES, colorForShipClass } from "../../utils/aisFilters";

// Decades present in cascade_stations on production (counted 2026-09-04):
// 1930:31 1940:33 1970:21 1980:328 1990:1524 2000:1489 2010:878, plus 192 with
// no year at all. The previous list stopped at 1970, so the 64 oldest cores —
// the ones that distort an interpolation most — could not be selected or
// excluded, and vanished silently whenever any filter was active.
export const CASCADE_DECADES = ["1930", "1940", "1970", "1980", "1990", "2000", "2010", "undated"];

export const RISK_FILTERS = [
  { key: "biodiversity", label: "Biodiversity overlap" },
  { key: "argo",         label: "Argo float nearby" },
  { key: "vents",        label: "Vent conflict" },
  { key: "unesco",       label: "UNESCO proximity" },
];

export const IUCN_FILTER_DEFS = [
  { key: "CR", cat: "CR", label: "Critically Endangered", color: "#dc2626" },
  { key: "EN", cat: "EN", label: "Endangered",            color: "#ea580c" },
  { key: "VU", cat: "VU", label: "Vulnerable",            color: "#d97706" },
  { key: "NT", cat: "NT", label: "Near Threatened",       color: "#65a30d" },
  { key: "LC", cat: "LC", label: "Least Concern",         color: "#16a34a" },
] as const;

export const NOISE_RISK_FILTER_DEFS = [
  { key: "critical",  level: "critical",  label: "Critical (≥0.8)",    color: "#dc2626", dot: true },
  { key: "high",      level: "high",      label: "High (0.6–0.8)",     color: "#ea580c", dot: true },
  { key: "moderate",  level: "moderate",  label: "Moderate (0.4–0.6)", color: "#ca8a04", dot: true },
  { key: "low",       level: "low",       label: "Low (0.2–0.4)",      color: "#65a30d", dot: true },
  { key: "data_gap",  level: "data_gap",  label: "Data gap",            color: "#94a3b8", dot: true },
  { key: "minimal",   level: "minimal",   label: "Minimal (<0.2)",      color: "#64748b", dot: true },
] as const;

export const DEEPDATA_CONTRACTOR_DEFS = [
  ...CONTRACTOR_CODES.map(code => {
    const [r, g, b] = CONTRACTOR_COLORS[code] ?? [148, 163, 184, 230];
    return { key: code, label: code, color: `rgb(${r}, ${g}, ${b})`, dot: true } as const;
  }),
  // Stations whose dataset title doesn't match the contractor-code regex.
  // Slate-grey on the map; this entry lets users isolate them.
  {
    key: UNPARSED_CONTRACTOR_KEY,
    label: "(unparsed)",
    color: `rgb(${FALLBACK_CONTRACTOR_COLOR[0]}, ${FALLBACK_CONTRACTOR_COLOR[1]}, ${FALLBACK_CONTRACTOR_COLOR[2]})`,
    dot: true,
  } as const,
];

export const CHESS_HABITAT_DEFS = [
  { key: "seep",       label: "Cold Seep",   color: "#00c896", dot: true },
  { key: "whale_fall", label: "Whale Fall",  color: "#dc3282", dot: true },
  { key: "omz",        label: "OMZ / Other", color: "#6464ff", dot: true },
] as const;

export const CHESS_PHYLUM_DEFS = [
  { key: "Annelida",      label: "Annelida",      color: "#00c896" },
  { key: "Mollusca",      label: "Mollusca",      color: "#00c896" },
  { key: "Crustacea",     label: "Crustacea",     color: "#00c896" },
  { key: "Echinodermata", label: "Echinodermata", color: "#00c896" },
  { key: "Porifera",      label: "Porifera",      color: "#00c896" },
] as const;

// OceanOPS's OWN platform status vocabulary — these four strings come from the
// source and are never rewritten (`status.name` in the OceanOPS platform record).
// ⛔ Do not collapse them into "active"/"inactive": CLOSED and INACTIVE are
// different statements about a mooring, and REGISTERED means "announced, never
// deployed". The gloss beside each is ours and is translated; the KEY is theirs.
//
// Measured on production 2026-09-11, 1,037 positioned stations:
//   OPERATIONAL   64   (49 of them carrying a live observation)
//   INACTIVE     288   (1)
//   CLOSED       679   (0)
//   REGISTERED     6   (0)
export const OCEANSITES_STATUS_DEFS = [
  { key: "OPERATIONAL", labelKey: "filters.oceansites.status.operational", color: "#00e5a0" },
  { key: "INACTIVE",    labelKey: "filters.oceansites.status.inactive",    color: "#ffc857" },
  { key: "CLOSED",      labelKey: "filters.oceansites.status.closed",      color: "#8c94a6" },
  { key: "REGISTERED",  labelKey: "filters.oceansites.status.registered",  color: "#6fa8ff" },
] as const;

export const OCEANSITES_NETWORK_DEFS = [
  { key: "OceanSITES/PIRATA",     label: "PIRATA (Atlantic)",       color: "#00cfff" },
  { key: "OceanSITES/RAMA",       label: "RAMA (Indian Ocean)",     color: "#00cfff" },
  { key: "OceanSITES/OOI",        label: "OOI (US Observatories)",  color: "#00cfff" },
  { key: "OceanSITES",            label: "Other OceanSITES",        color: "#00cfff" },
] as const;

// Hydrophone-station "source" filter chips (SensorsSection). `key` MUST match
// `acoustic_stations.source` exactly — case matters (see md_wea_cpod below).
// This is one of THREE independent registries over the same key set — the
// other two are HYDROPHONE_SOURCE_COLOR (components/map3d/colors.ts) and
// HYDROPHONE_SOURCE_LABEL (panels/ocean/HydrophoneStationPanel.tsx). Guarded
// by __tests__/hydrophone-source-registries.test.ts — keep all three in sync.
export const HYDROPHONE_SOURCE_DEFS = [
  { key: "ooi",    label: "OOI",         color: "#e879f9" },
  { key: "imos",   label: "IMOS",        color: "#22c55e" },
  { key: "mars",   label: "MARS",        color: "#22d3ee" },
  { key: "palaoa", label: "AWI PALAOA",  color: "#f8fafc" },
  { key: "obsea",  label: "OBSEA",       color: "#facc15" },
  { key: "km3net", label: "KM3NeT",      color: "#818cf8" },
  { key: "nrs",        label: "NOAA NRS",        color: "#38bdf8" },
  { key: "sanctsound", label: "NOAA SanctSound", color: "#fb923c" },
  { key: "nefsc",      label: "NOAA NEFSC",      color: "#f472b6" },
  // Phase 4 — 12 NOAA Passive Acoustic Archive programs
  { key: "pifsc",  label: "PIFSC", color: "#0ea5e9" },
  { key: "sefsc",  label: "SEFSC", color: "#fbbf24" },
  { key: "onms",   label: "ONMS",  color: "#f97316" },
  { key: "adeon",  label: "ADEON", color: "#8b5cf6" },
  { key: "boem",   label: "BOEM",  color: "#4b5563" },
  { key: "aeon",   label: "AEON",  color: "#a78bfa" },
  { key: "navy",   label: "Navy",  color: "#1f2937" },
  { key: "nps",    label: "NPS",   color: "#10b981" },
  { key: "jasco",  label: "JASCO", color: "#d946ef" },
  { key: "fram",   label: "FRAM",  color: "#e1d314" },
  { key: "coastal_studies_institute", label: "CSI", color: "#0e7490" },
  { key: "ioos",   label: "IOOS",  color: "#4f46e5" },
  // Phase 3 — PANGAEA/Dryad
  { key: "sambah", label: "SAMBAH", color: "#34d399" },
  // Phase 4 — CTBTO IMS
  { key: "ims", label: "CTBTO IMS", color: "#67e8f9" },
  // Phase 5 — 8 NOAA Passive Acoustic Archive programs added 2026-09-15.
  // Colours match HYDROPHONE_SOURCE_COLOR exactly (see that file for the
  // distance-from-existing-palette reasoning).
  { key: "afsc",    label: "AFSC",    color: "#065f46" },
  { key: "cornell", label: "Cornell", color: "#b91c1c" },
  { key: "mbarc_socal",  label: "MBARC SoCal",  color: "#3b82f6" },
  { key: "mbarc_arctic", label: "MBARC Arctic", color: "#bfdbfe" },
  { key: "mbarc_flip",   label: "MBARC FLIP",   color: "#1e40af" },
  { key: "swfsc",   label: "SWFSC",   color: "#78350f" },
  { key: "rutgers_njrmi", label: "Rutgers NJRMI", color: "#65a30d" },
  // ⚠️ Lowercase key — matches acoustic_stations.source exactly, NOT the
  // bucket's uppercase MD_WEA_CPOD/ prefix. See HYDROPHONE_SOURCE_LABEL.
  { key: "md_wea_cpod", label: "MD WEA C-POD", color: "#db2777" },
] as const;

// AIS ship-class filter chips. Labels are plain English (not i18n-keyed) —
// same as the ship class taxonomy names shown nowhere else in the UI copy.
export const AIS_SHIP_CLASS_DEFS = AIS_SHIP_CLASSES.map(c => {
  const [r, g, b] = colorForShipClass(c);
  return { key: c, label: c.charAt(0).toUpperCase() + c.slice(1), color: `rgb(${r}, ${g}, ${b})`, dot: true };
});
