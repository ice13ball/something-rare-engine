// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
import { describe, expect, it } from "vitest";
import {
  PLANKTON_DECADES, PLANKTON_DEPTH_BANDS, PLANKTON_GROUPS, planktonCellZoomTarget, planktonFillColor,
  planktonFilterActive, planktonFilterQuery, planktonLineColor, planktonRadius, planktonTileUrl,
  planktonVersionFromMeta, planktonVersionUrl,
} from "../utils/plankton";

const none = { groups: new Set<string>(), decades: new Set<string>(), bands: new Set<string>(), showEdna: true };

describe("plankton vocabulary", () => {
  it("is the backend's, in the backend's order (bit i of `groups` = PLANKTON_GROUPS[i])", () => {
    expect(PLANKTON_GROUPS).toEqual(["copepoda", "euphausiacea", "diatoms", "coccolithophores", "dinoflagellates"]);
    expect(PLANKTON_DECADES).toEqual(["-1", "1940", "1950", "1960", "1970", "1980", "1990", "2000", "2010", "2020"]);
    expect(PLANKTON_DEPTH_BANDS).toEqual(["0", "1", "2", "3"]);
  });
});

describe("planktonFilterQuery", () => {
  it("is empty for the default view and for a fully ticked set", () => {
    expect(planktonFilterQuery(none)).toBe("");
    expect(planktonFilterQuery({ ...none, groups: new Set(PLANKTON_GROUPS) })).toBe("");
    expect(planktonFilterActive(none)).toBe(false);
  });
  it("is canonical: vocabulary order whatever the click order", () => {
    const f = { groups: new Set(["diatoms", "copepoda"]), decades: new Set(["2010", "-1"]), bands: new Set(["3"]), showEdna: false };
    expect(planktonFilterQuery(f)).toBe("g=copepoda,diatoms&d=-1,2010&b=3&e=0");
    expect(planktonFilterActive(f)).toBe(true);
  });
  it("never sends a value outside the vocabulary (the server would answer 400)", () => {
    expect(planktonFilterQuery({ ...none, decades: new Set(["1930"]) })).toBe("");
  });
});

describe("planktonTileUrl", () => {
  it("goes through the BFF /api prefix and carries the data version", () => {
    expect(planktonTileUrl("", "20261007120000-a1b2c3", none, 0))
      .toBe("/api/v1/plankton/tiles/{z}/{x}/{y}.pbf?v=20261007120000-a1b2c3&r=0");
    expect(planktonTileUrl("https://x", "20261007120000-a1b2c3", { ...none, showEdna: false }, 2))
      .toBe("https://x/api/v1/plankton/tiles/{z}/{x}/{y}.pbf?v=20261007120000-a1b2c3&e=0&r=2");
  });
});

describe("planktonVersionFromMeta", () => {
  it("accepts only a well-formed version", () => {
    expect(planktonVersionFromMeta({ tile_version: "20261007120000-a1b2c3" })).toBe("20261007120000-a1b2c3");
    expect(planktonVersionFromMeta({ tile_version: null })).toBeNull();
    expect(planktonVersionFromMeta({ tile_version: "../x" })).toBeNull();
    expect(planktonVersionFromMeta(null)).toBeNull();
  });
});

describe("drawing", () => {
  it("grows the dot with log(n) and caps it", () => {
    expect(planktonRadius(1)).toBe(3);
    expect(planktonRadius(10)).toBe(5);
    expect(planktonRadius(1e9)).toBe(14);
    expect(planktonRadius(undefined)).toBe(3);
  });
  it("fills with the dominant group's colour", () => {
    expect(planktonFillColor({ top_group: "copepoda", edna_only: false })).toEqual([249, 115, 22, 200]);
    expect(planktonFillColor({ top_group: "nonsense" })).toEqual([148, 163, 184, 200]);
  });
  it("draws an eDNA-only place as an outline in its group colour, with no fill", () => {
    expect(planktonFillColor({ top_group: "diatoms", edna_only: true })).toEqual([0, 0, 0, 0]);
    expect(planktonLineColor({ top_group: "diatoms", edna_only: true })).toEqual([250, 204, 21, 255]);
    expect(planktonLineColor({ top_group: "diatoms", edna_only: false })).toEqual([255, 255, 255, 90]);
  });
  it("a click on a grid cell zooms to the next band", () => {
    expect(planktonCellZoomTarget(2)).toBe(4.5);
    expect(planktonCellZoomTarget(5)).toBe(7.5);
  });
});

describe("plankton first-paint version lookup", () => {
  it("asks the cheap tile-version endpoint through the BFF, never /meta", () => {
    expect(planktonVersionUrl("https://x.test")).toBe("https://x.test/api/v1/plankton/tile-version");
    expect(planktonVersionUrl("")).not.toContain("/meta");
  });
  it("reads the version from the tile-version body", () => {
    expect(planktonVersionFromMeta({ tile_version: "20261007120000-a1b2c3", tile_built_at: "x" })).toBe("20261007120000-a1b2c3");
    expect(planktonVersionFromMeta({ tile_version: "２０261007120000-a1b2c3" })).toBeNull();
  });
});
