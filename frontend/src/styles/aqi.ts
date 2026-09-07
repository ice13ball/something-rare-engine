// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

/**
 * US EPA AQI converter.
 *
 * Reference: 40 CFR Part 58 Appendix G; NowCast methodology
 *   https://www.airnow.gov/aqi/aqi-basics/
 *   https://www.airnow.gov/sites/default/files/2020-05/aqi-technical-assistance-document-sept2018.pdf
 *
 * AQI is a piecewise-linear interpolation between regulatory breakpoints.
 * The breakpoints below correspond to the standard averaging windows
 * (PM2.5 24h, O3 8h, NO2 1h, SO2 1h, CO 8h, PM10 24h). OpenAQ "latest"
 * readings are instantaneous and do not match those windows exactly —
 * the resulting score is *indicative* and should be labeled as such.
 *
 * Final station AQI is the MAX across pollutants (EPA "worst pollutant" rule).
 */

import { EPA_AQI, EPA_AQI_NO_DATA, type AqiCategory, type RGB } from "./colorStandards";

/** AQI category bounds (low/high inclusive). */
const AQI_CATEGORIES: Array<{ aqiLo: number; aqiHi: number; cat: AqiCategory }> = [
  { aqiLo:   0, aqiHi:  50, cat: "Good"           },
  { aqiLo:  51, aqiHi: 100, cat: "Moderate"       },
  { aqiLo: 101, aqiHi: 150, cat: "USG"            },
  { aqiLo: 151, aqiHi: 200, cat: "Unhealthy"      },
  { aqiLo: 201, aqiHi: 300, cat: "Very Unhealthy" },
  { aqiLo: 301, aqiHi: 500, cat: "Hazardous"      },
];

/**
 * Pollutant breakpoint table — concentration ranges aligned to AQI ranges.
 * Each entry: { cLo, cHi, aqiLo, aqiHi }. Concentration units per pollutant
 * are documented in the comment above each table.
 */

// PM2.5 — µg/m³, 24h average. Truncate inputs to 0.1 µg/m³.
const BP_PM25 = [
  { cLo:   0.0, cHi:  12.0, aqiLo:   0, aqiHi:  50 },
  { cLo:  12.1, cHi:  35.4, aqiLo:  51, aqiHi: 100 },
  { cLo:  35.5, cHi:  55.4, aqiLo: 101, aqiHi: 150 },
  { cLo:  55.5, cHi: 150.4, aqiLo: 151, aqiHi: 200 },
  { cLo: 150.5, cHi: 250.4, aqiLo: 201, aqiHi: 300 },
  { cLo: 250.5, cHi: 500.4, aqiLo: 301, aqiHi: 500 },
];

// PM10 — µg/m³, 24h average. Truncate to 1 µg/m³.
const BP_PM10 = [
  { cLo:   0, cHi:  54, aqiLo:   0, aqiHi:  50 },
  { cLo:  55, cHi: 154, aqiLo:  51, aqiHi: 100 },
  { cLo: 155, cHi: 254, aqiLo: 101, aqiHi: 150 },
  { cLo: 255, cHi: 354, aqiLo: 151, aqiHi: 200 },
  { cLo: 355, cHi: 424, aqiLo: 201, aqiHi: 300 },
  { cLo: 425, cHi: 604, aqiLo: 301, aqiHi: 500 },
];

// O3 — ppm, 8h average. Truncate to 0.001 ppm. (1ppb = 0.001 ppm)
const BP_O3_8H = [
  { cLo: 0.000, cHi: 0.054, aqiLo:   0, aqiHi:  50 },
  { cLo: 0.055, cHi: 0.070, aqiLo:  51, aqiHi: 100 },
  { cLo: 0.071, cHi: 0.085, aqiLo: 101, aqiHi: 150 },
  { cLo: 0.086, cHi: 0.105, aqiLo: 151, aqiHi: 200 },
  { cLo: 0.106, cHi: 0.200, aqiLo: 201, aqiHi: 300 },
];

// NO2 — ppb, 1h average. Truncate to 1 ppb.
const BP_NO2 = [
  { cLo:    0, cHi:   53, aqiLo:   0, aqiHi:  50 },
  { cLo:   54, cHi:  100, aqiLo:  51, aqiHi: 100 },
  { cLo:  101, cHi:  360, aqiLo: 101, aqiHi: 150 },
  { cLo:  361, cHi:  649, aqiLo: 151, aqiHi: 200 },
  { cLo:  650, cHi: 1249, aqiLo: 201, aqiHi: 300 },
  { cLo: 1250, cHi: 2049, aqiLo: 301, aqiHi: 500 },
];

// SO2 — ppb, 1h average. Truncate to 1 ppb.
// 1h SO2 only valid up to 200 ppb; above that EPA switches to 24h scale (305+).
const BP_SO2 = [
  { cLo:   0, cHi:  35, aqiLo:   0, aqiHi:  50 },
  { cLo:  36, cHi:  75, aqiLo:  51, aqiHi: 100 },
  { cLo:  76, cHi: 185, aqiLo: 101, aqiHi: 150 },
  { cLo: 186, cHi: 304, aqiLo: 151, aqiHi: 200 },
  { cLo: 305, cHi: 604, aqiLo: 201, aqiHi: 300 },
  { cLo: 605, cHi: 1004, aqiLo: 301, aqiHi: 500 },
];

// CO — ppm, 8h average. Truncate to 0.1 ppm. (input arrives in ppb → /1000)
const BP_CO_8H = [
  { cLo:  0.0, cHi:  4.4, aqiLo:   0, aqiHi:  50 },
  { cLo:  4.5, cHi:  9.4, aqiLo:  51, aqiHi: 100 },
  { cLo:  9.5, cHi: 12.4, aqiLo: 101, aqiHi: 150 },
  { cLo: 12.5, cHi: 15.4, aqiLo: 151, aqiHi: 200 },
  { cLo: 15.5, cHi: 30.4, aqiLo: 201, aqiHi: 300 },
  { cLo: 30.5, cHi: 50.4, aqiLo: 301, aqiHi: 500 },
];

function piecewiseAqi(conc: number, breakpoints: typeof BP_PM25): number | null {
  if (!Number.isFinite(conc) || conc < 0) return null;
  for (const bp of breakpoints) {
    if (conc >= bp.cLo && conc <= bp.cHi) {
      const aqi = ((bp.aqiHi - bp.aqiLo) / (bp.cHi - bp.cLo)) * (conc - bp.cLo) + bp.aqiLo;
      return Math.round(aqi);
    }
  }
  // Above the highest breakpoint → cap at top AQI value of the table.
  const last = breakpoints[breakpoints.length - 1];
  if (conc > last.cHi) return last.aqiHi;
  return null;
}

/** Per-pollutant AQI from a single concentration reading. */
export function aqiFromPm25(ugm3: number): number | null {
  // Truncate to 0.1 µg/m³ per EPA spec.
  const c = Math.trunc(ugm3 * 10) / 10;
  return piecewiseAqi(c, BP_PM25);
}

export function aqiFromPm10(ugm3: number): number | null {
  return piecewiseAqi(Math.trunc(ugm3), BP_PM10);
}

/** O3 input in ppb; converted to ppm internally. */
export function aqiFromO3(ppb: number): number | null {
  const ppm = Math.trunc(ppb) / 1000;
  return piecewiseAqi(ppm, BP_O3_8H);
}

export function aqiFromNo2(ppb: number): number | null {
  return piecewiseAqi(Math.trunc(ppb), BP_NO2);
}

export function aqiFromSo2(ppb: number): number | null {
  return piecewiseAqi(Math.trunc(ppb), BP_SO2);
}

/** CO input in ppb; converted to ppm internally. */
export function aqiFromCo(ppb: number): number | null {
  const ppm = Math.trunc(ppb) / 100 / 10; // ppb → ppm with 0.1 truncation
  return piecewiseAqi(ppm, BP_CO_8H);
}

/** AQI value → category. */
export function aqiCategory(aqi: number): AqiCategory {
  for (const c of AQI_CATEGORIES) {
    if (aqi >= c.aqiLo && aqi <= c.aqiHi) return c.cat;
  }
  return aqi > 500 ? "Hazardous" : "Good";
}

/**
 * Compute station AQI from any pollutant concentrations present in `props`.
 * EPA convention: station AQI = MAX(per-pollutant AQI). Unknown / missing
 * pollutants are silently skipped. Returns null if no pollutant was usable.
 *
 * Property keys come from the OpenAQ enrichment in main.py:
 *   p.pm25, p.pm10  → µg/m³
 *   p.o3, p.no2, p.so2, p.co → ppb
 */
export interface AqiResult {
  aqi: number;
  category: AqiCategory;
  dominant: string;       // "pm25" | "o3" | …
  color: RGB;
}

export function stationAqi(props: Record<string, unknown> | null | undefined): AqiResult | null {
  if (!props) return null;

  const candidates: Array<{ key: string; aqi: number | null }> = [
    { key: "pm25", aqi: typeof props.pm25 === "number" ? aqiFromPm25(props.pm25) : null },
    { key: "pm10", aqi: typeof props.pm10 === "number" ? aqiFromPm10(props.pm10) : null },
    { key: "o3",   aqi: typeof props.o3   === "number" ? aqiFromO3  (props.o3)   : null },
    { key: "no2",  aqi: typeof props.no2  === "number" ? aqiFromNo2 (props.no2)  : null },
    { key: "so2",  aqi: typeof props.so2  === "number" ? aqiFromSo2 (props.so2)  : null },
    { key: "co",   aqi: typeof props.co   === "number" ? aqiFromCo  (props.co)   : null },
  ];

  let best: { key: string; aqi: number } | null = null;
  for (const c of candidates) {
    if (c.aqi != null && (best === null || c.aqi > best.aqi)) {
      best = { key: c.key, aqi: c.aqi };
    }
  }
  if (!best) return null;
  const cat = aqiCategory(best.aqi);
  return { aqi: best.aqi, category: cat, dominant: best.key, color: EPA_AQI[cat] };
}

/** Color for stations with no parseable pollutant data. */
export const AQI_NO_DATA_COLOR: RGB = EPA_AQI_NO_DATA;
