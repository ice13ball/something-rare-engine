// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// The left-menu hover popup is assembled from TWO registries that nothing held
// together until this file existed:
//
//   LAYER_TOOLTIPS_META[id]                  → source, sourceUrl, pairsWith
//   t(`tooltip.descriptions.${id}`)          → the prose the reader actually reads
//
// `AssertComplete` in controls/tooltips.ts already pins the FIRST to the layer
// union, so a layer can never lose its metadata silently. Nothing pinned the
// SECOND, and rows.tsx reads it with `{ defaultValue: "" }` — so a missing
// description is not an error, not a fallback to English, and not a visible
// gap in a diff. It is a popup that opens with an empty body.
//
// ⛔ That is exactly how `hydrophone-stations` shipped: metadata present, prose
// absent in all four locales, from the day the layer landed until 2026-09-13.
// A guard that only checks the metadata side would have stayed green through
// the whole of it.
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { LAYER_TOOLTIPS_META } from "../components/controls/tooltips";

const LOCALES_DIR = path.resolve(__dirname, "../../public/locales");
const SEEDS = path.resolve(__dirname, "../../../backend/startup_seeds.py");

const locales = fs
  .readdirSync(LOCALES_DIR, { withFileTypes: true })
  .filter((e) => e.isDirectory())
  .map((e) => e.name)
  .sort();

const descriptionsFor = (loc: string): Record<string, string> =>
  JSON.parse(fs.readFileSync(path.join(LOCALES_DIR, loc, "panels.json"), "utf8"))
    ?.tooltip?.descriptions ?? {};

/**
 * Layers pulled for licence reasons keep their translated prose: the copy is
 * unreachable (no layer, no metadata entry) but re-translating it if a licence
 * is ever granted costs more than leaving it. The list is read from the
 * backend so this allowance can never outlive the withdrawal it cites.
 */
const withdrawn = (() => {
  const src = fs.readFileSync(SEEDS, "utf8");
  const block = src.slice(src.indexOf("WITHDRAWN_LAYER_IDS"));
  // ⛔ End the tuple on a `)` alone on its line, not on the first `)` in the
  // slice — the licence notes above the ids contain "(protectedareas@…org)",
  // and stopping there parsed an EMPTY withdrawal list that made every id look
  // stranded. The non-empty assertion below is what caught it.
  const end = block.search(/^\)/m);
  return new Set(
    [...block.slice(0, end).matchAll(/^\s+"([a-z0-9-]+)",/gm)].map((m) => m[1]),
  );
})();

const metaIds = Object.keys(LAYER_TOOLTIPS_META).sort();

describe("the two halves of a layer tooltip", () => {
  // ⛔ Both sides must be non-empty before any set difference below means
  // anything. An empty `metaIds` makes every "nothing is missing" assertion
  // pass while proving nothing at all.
  it("has a non-empty registry on each side", () => {
    expect(locales.length).toBeGreaterThanOrEqual(2);
    expect(metaIds.length).toBeGreaterThan(40);
    expect(withdrawn.size).toBeGreaterThan(0);
    for (const loc of locales) {
      expect(Object.keys(descriptionsFor(loc)).length).toBeGreaterThan(40);
    }
  });

  it.each(locales)("%s: every layer with tooltip metadata has prose to show", (loc) => {
    const d = descriptionsFor(loc);
    const missing = metaIds.filter((id) => !(id in d));
    expect(missing).toEqual([]);
  });

  it.each(locales)("%s: no description is present but blank", (loc) => {
    const d = descriptionsFor(loc);
    // `defaultValue: ""` in rows.tsx means an empty string renders exactly like
    // an absent key, so absence is not the only way to ship an empty popup.
    const blank = metaIds.filter((id) => id in d && d[id].trim() === "");
    expect(blank).toEqual([]);
  });

  it.each(locales)("%s: no description is stranded without a layer", (loc) => {
    const d = descriptionsFor(loc);
    const stranded = Object.keys(d)
      .filter((id) => !(id in LAYER_TOOLTIPS_META) && !withdrawn.has(id))
      .sort();
    expect(stranded).toEqual([]);
  });

  it.each(locales.filter((l) => l !== "en"))(
    "%s: no description is an untranslated copy of the English one",
    (loc) => {
      const en = descriptionsFor("en");
      const other = descriptionsFor(loc);
      const stubs = metaIds.filter((id) => id in en && id in other && en[id] === other[id]);
      expect(stubs).toEqual([]);
    },
  );
});
