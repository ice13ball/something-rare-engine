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

// ── Units ───────────────────────────────────────────────────────────────────
// ⛔ The comment below used to assert "p.o3, p.no2, p.so2, p.co → ppb" as if it
// were a fact. OpenAQ publishes whatever the operator reports, and the mix is
// not close. Measured on production 2026-09-10 over air_quality_params:
//
//     o3    µg/m³ 6,692   ppm 3,583   ppb     7   -> ppb on 0.07% of stations
//     no2   µg/m³ 8,093   ppm 4,114   ppb   586   -> ppb on 4.6%
//     co    µg/m³ 4,345   ppm 2,126   ppb   563   -> ppb on 8.0%
//     pm25 / pm10 / pm1 / pm4          µg/m³ throughout — those were always fine
//
// Ozone reported in ppm (0.05, an ordinary value) scored on the ppb scale
// becomes 0.00005 ppm and yields AQI 0, so ozone dropped out of the
// worst-pollutant rule for 3,583 stations. Ozone in µg/m³ (100) scored as ppb
// yields AQI ~137 where the truth is ~84. The dot colours were wrong in both
// directions.
//
// ⛔ The stored value is never touched — the portal mirrors its sources 1:1.
// The conversion below exists only to feed the EPA breakpoints, which are
// DEFINED in specific units. A unit we cannot map yields null for that
// pollutant, never a guess: a wrongly-coloured dot is worse than a grey one.
//
// µg/m³ → ppb at 25 °C and 1 atm: ppb = µg/m³ × 24.45 / molecular weight.
const _MOLECULAR_WEIGHT: Record<string, number> = {
  o3: 48.00, no2: 46.0055, so2: 64.066, co: 28.010,
};

/** Normalise a published concentration to the unit the EPA breakpoints use.
 *
 * Returns null when the unit is absent or unrecognised — the caller must then
 * skip that pollutant rather than score it.
 */
export function toAqiUnit(key: string, value: number, unit: string | null | undefined): number | null {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  const mw = _MOLECULAR_WEIGHT[key];
  const u = (unit ?? "").trim().toLowerCase();

  if (mw === undefined) {
    // Particulates: the breakpoints are in µg/m³ and so is every source we see.
    // ⛔ Still refuse an unexpected unit rather than assume.
    return u === "µg/m³" || u === "ug/m3" || u === "µg/m3" ? value : null;
  }
  if (u === "ppb") return value;
  if (u === "ppm") return value * 1000;
  if (u === "µg/m³" || u === "ug/m3" || u === "µg/m3") return value * 24.45 / mw;
  return null;   // unknown or missing unit — say nothing
}

/**
 * Compute station AQI from any pollutant concentrations present in `props`.
 * EPA convention: station AQI = MAX(per-pollutant AQI). A pollutant whose unit
 * is missing or unrecognised is SKIPPED, not guessed at. Returns null if no
 * pollutant was usable — the caller then paints AQI_NO_DATA_COLOR.
 *
 * `props.units` is the per-pollutant unit map the /air-quality endpoint carries
 * straight from OpenAQ.
 */
export interface AqiResult {
  aqi: number;
  category: AqiCategory;
  dominant: string;       // "pm25" | "o3" | …
  color: RGB;
}

export function stationAqi(props: Record<string, unknown> | null | undefined): AqiResult | null {
  if (!props) return null;

  const units = (props.units ?? null) as Record<string, string> | null;
  const at = (key: string, fn: (v: number) => number | null): number | null => {
    const raw = props[key];
    if (typeof raw !== "number") return null;
    const v = toAqiUnit(key, raw, units?.[key]);
    return v === null ? null : fn(v);
  };

  const candidates: Array<{ key: string; aqi: number | null }> = [
    { key: "pm25", aqi: at("pm25", aqiFromPm25) },
    { key: "pm10", aqi: at("pm10", aqiFromPm10) },
    { key: "o3",   aqi: at("o3",   aqiFromO3)   },
    { key: "no2",  aqi: at("no2",  aqiFromNo2)  },
    { key: "so2",  aqi: at("so2",  aqiFromSo2)  },
    { key: "co",   aqi: at("co",   aqiFromCo)   },
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
