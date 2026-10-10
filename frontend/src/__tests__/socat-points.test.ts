import { describe, it, expect } from "vitest";
import { socatColor, SOCAT_NEUTRAL_RGBA, type SocatProps } from "../utils/socatPoints";
import { GLODAP_NO_VALUE_RGBA } from "../utils/glodapPoints";

const ramp = [{ pos: 0, hex: "#0000ff" }, { pos: 1, hex: "#ff0000" }];
const vm = { vmin: -2, vmax: 35, ramp };
const base: SocatProps = { e: "x", k: 1, y: 2024, f: 3800, t: 0, s: -3 };

describe("socatColor", () => {
  it("colours a 0.0 SST and a -0.03 salinity (zero and negative are values, not missing)", () => {
    expect(socatColor({ ...base, t: 0 }, "sst", 5, vm)).not.toEqual(GLODAP_NO_VALUE_RGBA);
    expect(socatColor({ ...base, s: -3 }, "salinity", 5, vm)).not.toEqual(GLODAP_NO_VALUE_RGBA);
  });
  it("greys a pre-1970 year at every decade", () => {
    for (let d = 0; d < 6; d++) expect(socatColor({ ...base, y: 1965 }, "fco2", d, vm)).toEqual(GLODAP_NO_VALUE_RGBA);
  });
  it("colours 2024 at decade 5 and greys it at decade 4", () => {
    expect(socatColor(base, "fco2", 5, vm)).not.toEqual(GLODAP_NO_VALUE_RGBA);
    expect(socatColor(base, "fco2", 4, vm)).toEqual(GLODAP_NO_VALUE_RGBA);
  });
  it("density is one neutral colour in the selected decade, grey outside it or before 1970", () => {
    expect(socatColor({ ...base, f: undefined }, "density", 5, vm)).toEqual(SOCAT_NEUTRAL_RGBA);
    expect(socatColor({ ...base, f: undefined }, "density", 4, vm)).toEqual(GLODAP_NO_VALUE_RGBA);
    expect(socatColor({ ...base, y: 1965 }, "density", 0, vm)).toEqual(GLODAP_NO_VALUE_RGBA);
  });
});
