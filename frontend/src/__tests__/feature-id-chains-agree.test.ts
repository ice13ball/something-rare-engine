// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
/**
 * `SearchBar.featureId()` and `openableRegistry.ID_CHAIN` must recognise the
 * same id properties.
 *
 * ⛔ WHY. They are two hand-maintained copies of one list, and on 2026-09-23
 * they had already drifted: `source_row` was added to ID_CHAIN for the MARHYS
 * layer and missed in `featureId()`. Selecting a MARHYS sample from search then
 * produced a share link carrying `["marhys", ""]`. The camera still flew to the
 * right place, so nothing looked broken — the link simply reopened nothing.
 *
 * ⚠️ This DRIVES the real function with each name rather than comparing the two
 * source texts. A text comparison would go green on a rename that breaks
 * nothing and stay green if `featureId` stopped being called at all.
 */

import { describe, expect, it } from "vitest";

import { featureId } from "../components/SearchBar";
import { ID_CHAIN } from "../types/openableRegistry";

describe("the two id chains agree", () => {
  it.each(ID_CHAIN)("featureId() recognises %s", (prop) => {
    expect(featureId({ [prop]: "SENTINEL-42" })).toBe("SENTINEL-42");
  });

  it("returns an empty string when a feature carries no known id", () => {
    // The empty string is the signal the share link uses for "no id" — it must
    // stay reachable, so a caller can tell "unidentified" from "id is 0".
    expect(featureId({ colour: "orange", depth_mbsl: 850 })).toBe("");
  });

  it("does not mistake a MARHYS sample_id for an identifier", () => {
    // 6,788 MARHYS rows carry only 6,108 distinct sample_ids. Routing on it
    // would send two different samples to the same link.
    expect(featureId({ sample_id: "Menez Gwen-Fontaine-1994" })).toBe("");
  });

  it("keys a MARHYS sample on its source row", () => {
    expect(featureId({ sample_id: "Menez Gwen-Fontaine-1994", source_row: 312 })).toBe(312);
  });
});
