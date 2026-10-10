import { describe, it, expect } from "vitest";
import { wodColor, wodTileVar, wodTileUrl, type WodProps } from "../utils/wodCasts";
import { GLODAP_NO_VALUE_RGBA } from "../utils/glodapPoints";

const ramp = [{ pos: 0, hex: "#0000ff" }, { pos: 1, hex: "#ff0000" }];
const vm = { vmin: -2, vmax: 35, ramp };
const base: WodProps = { q: 1, k: 3, id: 7, a: 1990, b: 2000, d0: 0 };
const meta = { variables: ["temperature", "salinity", "oxygen"] };

describe("wod-casts utilities", () => {
  it("colours a 0.00 degC mean (zero is a value, not missing)", () => {
    expect(wodColor(base, 0, true, 100, vm)).not.toEqual(GLODAP_NO_VALUE_RGBA);
  });
  it("is grey where the depth slot is absent", () => {
    expect(wodColor(base, 1, true, 100, vm)).toEqual(GLODAP_NO_VALUE_RGBA);
  });
  it("AOU has no per-cast value: temperature positions, grey", () => {
    expect(wodTileVar("aou", meta)).toEqual({ tileVar: "temperature", measured: false });
    expect(wodColor(base, 0, false, 100, vm)).toEqual(GLODAP_NO_VALUE_RGBA);
  });
  it("tile URL carries y0/y1 only for a narrowed range", () => {
    expect(wodTileUrl("v1", "oxygen", null)).not.toContain("y0");
    const u = wodTileUrl("v1", "oxygen", [1990, 2000]);
    expect(u).toContain("y0=1990");
    expect(u).toContain("y1=2000");
  });
});
