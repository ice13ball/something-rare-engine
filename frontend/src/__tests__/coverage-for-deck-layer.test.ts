// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { it, expect } from "vitest";
import { coverageForDeckLayer } from "../utils/useTemporalCoverage";
import { DECK_TO_TOGGLE } from "../utils/layerConfig";
import type { Coverage } from "../components/panels/shared/TemporalFrame";

const frame = (kind: Coverage["kind"] = "compilation"): Coverage => ({
  start_year: 1972, end_year: 2013, kind,
  wording: "w", source_url: null, verified_on: "2026-09-08",
});

// Frames are stored under canonical layer ids; a popup asks with the deck id.
const COVERAGE: Record<string, Coverage> = {
  "argo": frame("observations"),
  "cumulative-human-impact": frame("modelled"),
  "hydrothermal-vents": frame(),
  "ocean-acidification": frame(),
  "permafrost-thaw": frame(),
};

it("translates a deck layer id to the canonical id the frames are keyed by", () => {
  // ⛔ The failure this exists for: looking up "argo-floats-3d" directly finds
  // nothing, renders nothing, and reports nothing. Silence looks like "this layer
  // has no frame", which is a different and wrong claim.
  expect(coverageForDeckLayer(COVERAGE, "argo-floats-3d")).toBe(COVERAGE["argo"]);
  expect(coverageForDeckLayer(COVERAGE, "argo-glow")).toBe(COVERAGE["argo"]);
});

it("resolves the raster and hex variants of one layer to the same frame", () => {
  const a = coverageForDeckLayer(COVERAGE, "cumulative-human-impact-raster");
  const b = coverageForDeckLayer(COVERAGE, "cumulative-human-impact-hexes");
  expect(a).toBe(COVERAGE["cumulative-human-impact"]);
  expect(b).toBe(a);
});

it("resolves several deck ids that collapse onto one layer", () => {
  for (const deckId of ["hydrothermal-vents-active", "hydrothermal-vents-inactive",
                        "hydrothermal-vents-active-glow"]) {
    expect(coverageForDeckLayer(COVERAGE, deckId)).toBe(COVERAGE["hydrothermal-vents"]);
  }
});

it("falls back to the id itself for a layer drawn under its own name", () => {
  expect(coverageForDeckLayer(COVERAGE, "permafrost-thaw")).toBe(COVERAGE["permafrost-thaw"]);
});

it("returns undefined for a layer with no frame, rather than a wrong one", () => {
  expect(coverageForDeckLayer(COVERAGE, "seamounts")).toBeUndefined();
  expect(coverageForDeckLayer(COVERAGE, "not-a-layer-at-all")).toBeUndefined();
});

it("every DECK_TO_TOGGLE target is a plain layer id, not another deck id", () => {
  // If a value were itself a deck id, the lookup would need two hops and would
  // quietly resolve to nothing.
  for (const [deckId, target] of Object.entries(DECK_TO_TOGGLE)) {
    expect(DECK_TO_TOGGLE[target], `${deckId} → ${target} → ?`).toBeUndefined();
  }
});
