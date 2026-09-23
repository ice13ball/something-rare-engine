// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// The oxygen-deox legend cites two different works, and they have different
// years. Until 2026-09-23 every locale folded them into one line,
// "Kolodziejczyk et al. 2024, SEANOE 10.17882/52367", which put the 2024 year
// of the ESSD paper on the SEANOE dataset DOI.
//
// Checked against DataCite / Crossref on 2026-09-23:
//   dataset  10.17882/52367             publicationYear 2023,
//            Kolodziejczyk, Prigent-Mazella, Gaillard (SEANOE)
//   paper    10.5194/essd-16-5191-2024  2024, ESSD 16:5191-5206
//
// SEANOE asks for both to be cited. The test reads every locale directory, so
// a new language is covered the day it is added.
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

const LOCALES = path.resolve(__dirname, "../../public/locales");
const locales = fs
  .readdirSync(LOCALES)
  .filter((d) => fs.existsSync(path.join(LOCALES, d, "legend.json")));

describe("oxygen-deox source citation", () => {
  it("finds at least the four shipped locales", () => {
    expect(locales.length).toBeGreaterThanOrEqual(4);
  });

  it.each(locales)("%s: the SEANOE dataset carries its own year, 2023", (loc) => {
    const legend = JSON.parse(fs.readFileSync(path.join(LOCALES, loc, "legend.json"), "utf8"));
    const source: string = legend.layers["oxygen-deox"].source;
    expect(source).toMatch(/Gaillard 2023, SEANOE 10\.17882\/52367/);
    expect(source).not.toMatch(/2024, SEANOE/);
  });

  it.each(locales)("%s: the 2024 ESSD paper is cited separately", (loc) => {
    const legend = JSON.parse(fs.readFileSync(path.join(LOCALES, loc, "legend.json"), "utf8"));
    expect(legend.layers["oxygen-deox"].source).toMatch(/2024, ESSD 16:5191/);
  });
});
