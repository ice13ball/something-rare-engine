// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const MAP3D = readFileSync(resolve(__dirname, "../components/Map3D.tsx"), "utf8");

/**
 * ⚠️ A SHAPE test, not an executing one, and the exception is deliberate:
 * `Map3D.tsx` cannot be imported under vitest (it drags in deck.gl and MapLibre),
 * which is the whole reason its logic keeps being extracted into testable
 * modules. `hex-click-guard.test.ts` reads the same file for the same reason.
 *
 * What it exists to catch: `applyShareableFilters` and `applyShareableDisplay`
 * are both covered by executing tests — and deleting either CALL left every one
 * of those tests green. Verified by sabotage 2026-09-14. A tested function that
 * nothing invokes is a link that silently ignores half of what it carries: the
 * recipient sees their own filters and their own depth under the sender's
 * camera, and the whole view looks deliberate.
 *
 * Both must run at module init, before the first render, because they feed the
 * tile URLs — applying them later means fetching the recipient's default first
 * and visibly replacing it.
 */
describe("a share link's store-side state is actually applied at bootstrap", () => {
  // The module-init IIFE that parses `?s=`, from its opening to its closing `})();`.
  const block = MAP3D.match(/const _urlShare = \(\(\) => \{[\s\S]*?\n\}\)\(\);/)?.[0] ?? "";

  it("finds the bootstrap block at all", () => {
    // ⛔ Without this the two assertions below would pass vacuously on an empty
    // string the day the block is renamed or reshaped.
    expect(block.length).toBeGreaterThan(200);
    expect(block).toContain("decodeShareState");
  });

  it("applies the link's filters", () => {
    expect(block).toMatch(/applyShareableFilters\(\s*decoded\.filters\s*\)/);
  });

  it("applies the link's display selectors", () => {
    expect(block).toMatch(/applyShareableDisplay\(\s*decoded\.display\s*\)/);
  });
});

/**
 * ⛔ Same file, same reason, different failure: a link's layers can be applied
 * perfectly and still look lost. Tested on production 2026-09-14 — a 20-layer
 * link put seven LAND layers into the active set, drawn on the globe, with the
 * whole "LAND DATA" section of the left menu collapsed. The reader scrolls the
 * panel, counts fewer rows than the sender had, and reports missing layers.
 *
 * ⚠️ Gated on `linkCarriesView` on purpose. Doing it unconditionally would
 * re-open, on every single reload, a section the visitor collapsed themselves.
 */
describe("a link's layers are made visible in the menu, not just active", () => {
  const block = MAP3D.match(/if \(resolved\) \{[\s\S]*?\n    \}/)?.[0] ?? "";

  it("finds the layer-restore block at all", () => {
    expect(block).toContain("setActiveLayers(resolved)");
  });

  it("expands the sections the link's layers live in", () => {
    expect(block).toMatch(/applyMenuExpansion\(\s*resolved\s*\)/);
  });

  it("does it ONLY for a link, never for the reader's own saved state", () => {
    expect(block).toMatch(/if \(linkCarriesView\(_urlShare\)\)\s*applyMenuExpansion/);
  });
});

/**
 * ⛔ The pure rule is covered by `link-layer-activation.test.ts`, and that
 * cover is worthless if the call site hands it the wrong base set. The whole
 * defect was the ARGUMENT, not the rule: merging onto the effect's closure
 * value instead of the live store. Both spellings compile, both pass every
 * executing test, and only one keeps the link's layers.
 */
describe("the link's panels merge onto the live layer set, not a stale snapshot", () => {
  const block = MAP3D.match(/const liveActive = [\s\S]*?\n    \}/)?.[0] ?? "";

  it("finds the activation block at all", () => {
    expect(block).toContain("nextActiveForLink");
  });

  it("reads the layer set from the store, not from the closure", () => {
    expect(block).toMatch(/const liveActive = useMapStore\.getState\(\)\.activeLayers/);
  });

  it("passes that live set as the base", () => {
    expect(block).toMatch(/nextActiveForLink\(\s*liveActive,/);
  });

  it("asks the live set about loaded data too", () => {
    expect(block).toMatch(/liveActive\.has\(layerId\)/);
  });
});

/**
 * ⛔ The value is a literal in a React ref assignment, so no executing test can
 * reach it. What it guards is worth a shape test anyway: three layers wrote a
 * permanent `null` there, which the link opener reads as "still loading", and
 * a link naming one of them hung silently forever.
 */
describe("no layer claims its data is still loading forever", () => {
  const block = MAP3D.match(/searchDataRef\.current = \{[\s\S]*?\n    \};/)?.[0] ?? "";

  it("finds the search-data block at all", () => {
    expect(block.length).toBeGreaterThan(400);
    expect(block).toContain("claims:");
  });

  it("has no entry pinned to a bare null", () => {
    const pinned = [...block.matchAll(/^\s*([a-zA-Z]+):\s*null,/gm)].map(m => m[1]);
    expect(pinned).toEqual([]);
  });

  it("the three MVT-only layers use the explicit sentinel", () => {
    for (const key of ["memento", "geotraces", "mosaic"]) {
      expect(block).toMatch(new RegExp(`${key}: NO_CLIENT_COPY`));
    }
  });
});
