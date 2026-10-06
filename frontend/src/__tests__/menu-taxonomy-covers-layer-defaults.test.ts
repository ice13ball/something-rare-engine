// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
/**
 * `LAYER_TO_SUBGROUP` is a hand-kept twin of `LAYER_DEFAULTS` (and of backend/profiles.py
 * KNOWN_LAYER_IDS): a layer missing from it never expands its left-menu group when a share link or a
 * profile switches it on. Nothing but this test connects the two lists.
 *
 * It compares the two MAPS as they are at run time. `UNGROUPED` is the honest record of layers that
 * are not in the map today — an entry there is a known gap, not a verdict; when one is fixed this test
 * fails until the entry is deleted, so the list can only shrink.
 */
import { describe, expect, it } from "vitest";

import { LAYER_DEFAULTS } from "../utils/layerConfig";
import { LAYER_TO_SUBGROUP } from "../utils/menuTaxonomy";

// Found 2026-10-06 while adding glodap-points; not decided here. The same three are also absent from
// backend/profiles.py KNOWN_LAYER_IDS (see test_known_layer_ids_cover_layer_defaults.py).
const UNGROUPED = new Set<string>([
  "marhys", "greenland-sea-poc-aoc2025", "svalbard-fjords-primary-production",
]);

describe("LAYER_TO_SUBGROUP covers LAYER_DEFAULTS", () => {
  it("every layer the map can render has a menu sub-group, bar the recorded gaps", () => {
    const missing = LAYER_DEFAULTS.map((d) => d.id).filter((id) => !(id in LAYER_TO_SUBGROUP));
    expect(new Set(missing)).toEqual(UNGROUPED);
  });

  it("names no layer the registry does not have", () => {
    const ids = new Set(LAYER_DEFAULTS.map((d) => d.id));
    expect(Object.keys(LAYER_TO_SUBGROUP).filter((id) => !ids.has(id))).toEqual([]);
  });

  it("groups glodap-points with the Ocean Carbon field it is switched from", () => {
    expect(LAYER_TO_SUBGROUP["glodap-points"]).toBe(LAYER_TO_SUBGROUP["ocean-carbon"]);
  });
});
