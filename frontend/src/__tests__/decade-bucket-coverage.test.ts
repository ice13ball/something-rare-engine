// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { it, expect } from "vitest";
import { WOD_DECADES } from "../utils/wodDecades";
import { GEOTRACES_DECADES } from "../utils/geotracesElements";
import { MOSAIC_DECADES } from "../utils/mosaicVars";

/**
 * A decade the data holds but the chips cannot express is worse than a missing
 * filter: the rows are neither selectable nor excludable, and they vanish
 * silently whenever any chip is on. MOSAIC shipped that way — 12,002 of 25,608
 * cores (46.9%) were unreachable — and it took a production count to notice.
 *
 * Counted on production 2026-09-06. Update these lists when a sync widens the
 * data, and update the chips in the same commit.
 */
const PRODUCTION_DECADES = {
  // memento_casts: 155,418 rows, 1971-06-09 → 2016-12-19, zero NULL decades.
  // MEMENTO's chips come from WOD_DECADES, not a list of its own.
  memento: { buckets: WOD_DECADES, present: [1970, 1980, 1990, 2000, 2010] },
  // geotraces_stations: 2,049 rows, 2005-01-10 → 2023-01-24, zero NULL decades.
  geotraces: { buckets: GEOTRACES_DECADES, present: [2000, 2010, 2020] },
  // mosaic_cores: 25,608 rows, 1900 → 2022. Unlike the other two this one DOES
  // hold undated rows (7,053 after the 2026-09-06 re-sync), hence its extra bucket.
  mosaic: { buckets: MOSAIC_DECADES, present: [1900, 1950, 1960, 1970, 1980, 1990, 2000, 2010, 2020] },
  // wod_oxygen_profiles: 978,476 rows, every decade 1900-2020, zero NULL.
  wod: { buckets: WOD_DECADES, present: [1900, 1910, 1920, 1930, 1940, 1950, 1960, 1970, 1980, 1990, 2000, 2010, 2020] },
};

for (const [layer, { buckets, present }] of Object.entries(PRODUCTION_DECADES)) {
  it(`${layer}: every decade in the data has a chip`, () => {
    const missing = present.filter(d => !buckets.map(Number).includes(d));
    expect(missing).toEqual([]);
  });
}

/**
 * Only the two sediment layers hold undated rows, and each expresses its chip
 * differently: CASCADE keeps "undated" inside its bucket list, MOSAIC renders it
 * as an extra chip in the control. The test asserts the guarantee the user gets —
 * a reachable chip — not the shape the code happens to use.
 */
it("the two layers with undated rows both offer an undated chip", () => {
  const cascade = readFileSync(resolve(__dirname, "../components/controls/filterDefs.ts"), "utf8");
  expect(cascade).toMatch(/CASCADE_DECADES[^;]*"undated"/);

  const mosaicRow = readFileSync(
    resolve(__dirname, "../components/controls/sections/oceanClimatology/MosaicSedimentRow.tsx"), "utf8");
  expect(mosaicRow).toContain('toggleMosaicDecadeFilter("undated")');
});

it("the two layers with no undated rows do not offer the chip", () => {
  // memento_casts and geotraces_stations both have zero NULL decades on production.
  for (const row of ["MementoRow", "GeotracesRow"]) {
    const src = readFileSync(
      resolve(__dirname, `../components/controls/sections/oceanClimatology/${row}.tsx`), "utf8");
    expect(src).not.toContain('"undated"');
  }
});
