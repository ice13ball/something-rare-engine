// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// stationAqi() documented its own contract as "p.o3, p.no2, p.so2, p.co → ppb"
// and every caller believed it. OpenAQ publishes whatever the operator reports.
// Measured over air_quality_params on production 2026-09-10:
//
//     o3    µg/m³ 6,692   ppm 3,583   ppb     7   -> ppb on 0.07% of stations
//     no2   µg/m³ 8,093   ppm 4,114   ppb   586   -> ppb on 4.6%
//     co    µg/m³ 4,345   ppm 2,126   ppb   563   -> ppb on 8.0%
//     pm25 / pm10                       µg/m³ throughout — always correct
//
// Ozone at 0.05 ppm — an ordinary value — scored on the ppb scale becomes
// 0.00005 ppm and yields AQI 0, so ozone left the worst-pollutant rule for
// 3,583 stations. Ozone at 100 µg/m³ scored as ppb yields ~137 where the truth
// is ~84. The map's dot colours were wrong in both directions.
//
// ⛔ Stored values are never converted — the portal mirrors its sources 1:1.
// The conversion exists only to feed the EPA breakpoints, which are DEFINED in
// particular units. An unrecognised unit yields null, never a guess.
import { describe, it, expect } from "vitest";
import { stationAqi, toAqiUnit, AQI_NO_DATA_COLOR } from "../styles/aqi";

describe("toAqiUnit", () => {
  it("passes ppb through untouched", () => {
    expect(toAqiUnit("no2", 42, "ppb")).toBe(42);
  });

  it("scales ppm to ppb", () => {
    expect(toAqiUnit("o3", 0.05, "ppm")).toBeCloseTo(50, 6);
  });

  it("converts µg/m³ with the pollutant's own molecular weight", () => {
    // O3, MW 48.00: 100 µg/m³ × 24.45 / 48.00 = 50.94 ppb
    expect(toAqiUnit("o3", 100, "µg/m³")).toBeCloseTo(50.94, 1);
    // NO2, MW 46.0055: 40 µg/m³ × 24.45 / 46.0055 = 21.26 ppb
    expect(toAqiUnit("no2", 40, "µg/m³")).toBeCloseTo(21.26, 1);
    // ⛔ The two must differ — a single shared constant would pass a test that
    // only ever checked one gas.
    expect(toAqiUnit("o3", 100, "µg/m³")).not.toBeCloseTo(
      toAqiUnit("no2", 100, "µg/m³")!, 1);
  });

  it("refuses a unit it does not recognise, rather than guessing", () => {
    for (const bad of ["mg/m3", "", null, undefined, "particles/cm³", "%"]) {
      expect(toAqiUnit("no2", 42, bad)).toBeNull();
    }
  });

  it("refuses an unexpected unit even for particulates", () => {
    expect(toAqiUnit("pm25", 12, "µg/m³")).toBe(12);
    expect(toAqiUnit("pm25", 12, "ppb")).toBeNull();
  });
});

describe("stationAqi — units decide the colour", () => {
  const OZONE = 100;   // µg/m³, an ordinary summer value

  it("scores ozone in µg/m³ far below what the old ppb assumption produced", () => {
    const correct = stationAqi({ o3: OZONE, units: { o3: "µg/m³" } });
    const asPpb   = stationAqi({ o3: OZONE, units: { o3: "ppb" } });
    expect(correct).not.toBeNull();
    expect(asPpb).not.toBeNull();
    // 100 µg/m³ ≈ 51 ppb ≈ 0.051 ppm -> ~84; scored as 100 ppb -> ~137.
    expect(correct!.aqi).toBeLessThan(asPpb!.aqi - 30);
  });

  it("does not let ozone in ppm collapse to nothing", () => {
    // 0.05 ppm = 50 ppb -> AQI 46. Read as ppb it becomes 0.00005 ppm -> AQI 0,
    // and ozone silently drops out of the worst-pollutant rule.
    const correct = stationAqi({ o3: 0.05, units: { o3: "ppm" } });
    expect(correct).not.toBeNull();
    expect(correct!.aqi).toBe(46);

    const asPpb = stationAqi({ o3: 0.05, units: { o3: "ppb" } });
    expect(asPpb === null || asPpb.aqi === 0).toBe(true);
  });

  it("skips a pollutant whose unit the source did not publish", () => {
    // ⛔ Not "assume ppb". A wrongly-coloured dot is worse than a grey one.
    expect(stationAqi({ o3: 0.05 })).toBeNull();
    expect(stationAqi({ o3: 0.05, units: {} })).toBeNull();
  });

  it("still scores the pollutants whose units ARE known, ignoring the rest", () => {
    const r = stationAqi({ pm25: 55.5, o3: 0.05, units: { pm25: "µg/m³" } });
    expect(r).not.toBeNull();
    expect(r!.dominant).toBe("pm25");
  });

  it("keeps particulates working, which were never broken", () => {
    const r = stationAqi({ pm25: 12.0, units: { pm25: "µg/m³" } });
    expect(r).not.toBeNull();
    expect(r!.aqi).toBeGreaterThan(0);
    expect(AQI_NO_DATA_COLOR).toBeTruthy();
  });
});
