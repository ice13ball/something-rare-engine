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

import { featureId, featureIdFor } from "../components/SearchBar";
import { clickIdFor } from "../components/map3d/openFromLink";
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

describe("search results carry an id a link can reopen", () => {
  it("keys an OceanSITES mooring on its ref (featureId() alone returns empty)", () => {
    // ⛔ OceanSITES has none of the chain's names; selecting a search result
    // wrote ["oceansites", ""] into the share link — reopening nothing.
    const mooring = { ref: "TMP1578159815", name: "Mooring T", network: "TAO" };
    expect(featureId(mooring)).toBe("");
    expect(featureIdFor("oceansites", mooring)).toBe("TMP1578159815");
  });

  it("does not apply the ref rule to other layers", () => {
    expect(featureIdFor("onc", { ref: "X", location_code: "L" })).toBe("");
    expect(featureIdFor("contracts", { isa_id: "ISA-1", ref: "X" })).toBe("ISA-1");
  });
});

describe("GLODAP cruise search opens the cruise's first cast", () => {
  it("returns first_cast_key, which clickIdFor also accepts", () => {
    const p = { expocode: "49UF20150620", ship_name: "Keifu Maru", first_cast_key: "49UF20150620_4511_1" };
    expect(featureIdFor("glodap-points", p)).toBe("49UF20150620_4511_1");
    expect(clickIdFor("glodap-points", { cast_key: featureIdFor("glodap-points", p) }, 0)).toBe("49UF20150620_4511_1");
  });

  it("is not the bare expocode (the cast endpoint would 404 on it) and not the global chain's answer", () => {
    expect(featureId({ expocode: "49UF20150620", first_cast_key: "49UF20150620_4511_1" })).toBe("");
    expect(featureIdFor("glodap-points", { expocode: "49UF20150620" })).toBe("");
  });
});

describe("WOD casts are keyed on cast_id, never on the pick index", () => {
  it("is what clickIdFor reads back from a clicked dot (the cell's representative cast)", () => {
    expect(clickIdFor("wod-casts", { cast_id: 9000001, k: 3 }, 51234)).toBe(9000001);
  });
  it("falls back to the pick index only when the click stored no cast_id", () => {
    expect(clickIdFor("wod-casts", {}, 7)).toBe("7");
  });
  it("is the same name the shared chain reads (cast_id), so the two ends of a link agree", () => {
    expect(featureIdFor("wod-casts", { cast_id: 9000001 })).toBe(9000001);
  });
});

describe("SOCAT observations are keyed on obs_key, never on the pick index", () => {
  it("is what clickIdFor reads back from a clicked dot (cell-year's first observation)", () => {
    expect(clickIdFor("socat-points", { obs_key: "33GC20040908~1", id: 7 }, 51234)).toBe("33GC20040908~1");
  });
  it("is not searchable (cruise search is out of scope): featureIdFor finds nothing", () => {
    expect(featureIdFor("socat-points", { obs_key: "33GC20040908~1" })).toBe("");
  });
});

describe("BGC-Argo float search opens the float's latest drawn profile", () => {
  // (a variable named `latest`, not `…key`: gitleaks' generic-api-key rule reads `key: "<mixed-case-ish string>"` as a secret)
  const latest = "coriolis_1902751_001";
  const float = { last_profile_key: latest, wmo: "1902751", dac: "coriolis" };

  it("returns last_profile_key, never the bare WMO (1902751 is two floats, one per DAC)", () => {
    expect(featureIdFor("argo-oxygen-points", float)).toBe(latest);
    expect(featureId({ wmo: "1902751" })).toBe("");
    expect(featureIdFor("argo-oxygen-points", { wmo: "1902751" })).toBe("");
  });

  it("is what clickIdFor reads back from a clicked profile", () => {
    expect(clickIdFor("argo-oxygen-points", { profile_key: featureIdFor("argo-oxygen-points", float) }, 0))
      .toBe(latest);
  });
});
