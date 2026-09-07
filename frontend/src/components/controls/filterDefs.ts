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

export const OCEANSITES_NETWORK_DEFS = [
  { key: "OceanSITES/PIRATA",     label: "PIRATA (Atlantic)",       color: "#00cfff" },
  { key: "OceanSITES/RAMA",       label: "RAMA (Indian Ocean)",     color: "#00cfff" },
  { key: "OceanSITES/OOI",        label: "OOI (US Observatories)",  color: "#00cfff" },
  { key: "OceanSITES",            label: "Other OceanSITES",        color: "#00cfff" },
] as const;

// AIS ship-class filter chips. Labels are plain English (not i18n-keyed) —
// same as the ship class taxonomy names shown nowhere else in the UI copy.
export const AIS_SHIP_CLASS_DEFS = AIS_SHIP_CLASSES.map(c => {
  const [r, g, b] = colorForShipClass(c);
  return { key: c, label: c.charAt(0).toUpperCase() + c.slice(1), color: `rgb(${r}, ${g}, ${b})`, dot: true };
});
