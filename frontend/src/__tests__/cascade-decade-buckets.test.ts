// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { it, expect } from "vitest";
import { CASCADE_DECADES } from "../components/controls/filterDefs";

// Decades present in production (cascade_stations, 2026-09-04): 1930..2010 plus 192 NULL.
const PRODUCTION_DECADES = ["1930", "1940", "1970", "1980", "1990", "2000", "2010"];

it("offers a bucket for every decade the data actually contains", () => {
  for (const d of PRODUCTION_DECADES) {
    expect(CASCADE_DECADES).toContain(d);
  }
});

it("offers a bucket for stations the source never dated", () => {
  expect(CASCADE_DECADES).toContain("undated");
});
