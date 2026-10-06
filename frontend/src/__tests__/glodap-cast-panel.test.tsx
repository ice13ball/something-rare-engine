// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import {
  GlodapCastPanel, GlodapProfileChart, profileSamples, castMoment, doiUrl, creditsFor, bottleInWindow, tickDecimals,
  BOTTLE_FOR_FIELD,
} from "../components/panels/fields/GlodapCastPanel";
import { useMapStore } from "../store/mapStore";
import { GLODAP_CAST } from "./detailPanelFetchFixtures";

const payload = {
  depth_m: [5, 200, 205, 4000],
  variables: { tco2: { values: [2050, 2150, null, 2250], flags: [2, 0, 9, 2], qc: 1, units: "µmol/kg" } },
} as any;

describe("profile chart draws only acceptable values as data", () => {
  it("separates flag-2 values from interpolated and missing ones", () => {
    const s = profileSamples(payload, "tco2");
    expect(s.good).toEqual([[5, 2050], [4000, 2250]]);
    expect(s.other).toEqual([[200, 2150, 0]]);          // flag 0 listed, not plotted as data; flag 9 has no value
  });
  it("an unknown column yields nothing instead of throwing", () => {
    expect(profileSamples(payload, "nope")).toEqual({ good: [], other: [] });
  });
  it("Cant has no bottle: it is compared with DIC", () => {
    expect(BOTTLE_FOR_FIELD).toEqual({ dic: "tco2", talk: "talk", ph: "phtsinsitutp", cant: "tco2" });
  });
});

describe("bottleInWindow picks the bottle the map would use, for variables the server has no level for", () => {
  it("takes the flag-2 sample closest to the standard depth inside the window", () => {
    expect(bottleInWindow([[5, 35.1], [190, 35.0], [215, 34.9], [600, 34.7]], 200)).toEqual([35.0, 190]);
    expect(bottleInWindow([[176, 35.0], [199, 34.9], [224, 34.8]], 200)).toEqual([34.9, 199]);
  });
  it("nothing inside the window is null, not the nearest bottle outside it", () => {
    expect(bottleInWindow([[5, 35.1], [600, 34.7]], 200)).toBeNull();
    expect(bottleInWindow([], 0)).toBeNull();
  });
  it("a depth with no window is null", () => { expect(bottleInWindow([[5, 1]], 123)).toBeNull(); });
});

describe("chart ticks are labelled with enough decimals to tell them apart", () => {
  it("decimals follow the range, not the magnitude", () => {
    expect(tickDecimals(0.3)).toBe(2);     // salinity 34.6-34.9
    expect(tickDecimals(0.2)).toBe(2);     // pH 7.9-8.1
    expect(tickDecimals(1000)).toBe(0);    // DIC over a deep cast
    expect(tickDecimals(0)).toBe(4);       // a constant profile is capped, not 9 digits
  });
  it("a narrow salinity profile prints three different ticks", () => {
    const { container } = render(<GlodapProfileChart samples={[[5, 34.6], [500, 34.75], [4000, 34.9]]} fieldPoints={[]}
      picked={null} units="PSU" label="Salinity" />);
    const ticks = Array.from(container.querySelectorAll("text")).map((t) => t.textContent)
      .filter((x) => /^\d+\.\d+$/.test(x ?? ""));
    expect(ticks).toEqual(["34.60", "34.75", "34.90"]);
  });
  it("a wide DIC range stays on whole numbers", () => {
    const { container } = render(<GlodapProfileChart samples={[[5, 1950], [4000, 2350]]} fieldPoints={[]}
      picked={null} units="µmol/kg" label="DIC" />);
    const texts = Array.from(container.querySelectorAll("text")).map((t) => t.textContent ?? "");
    expect(texts).toEqual(expect.arrayContaining(["1950", "2150", "2350"]));
    expect(texts.filter((x) => /^\d+\.\d+$/.test(x))).toEqual([]);
  });
});

describe("date precision", () => {
  it("a date-only cast has no time of day, even when the row carries a midnight timestamp", () => {
    expect(castMoment({ obs_date: "1998-03-02", obs_time: null, time_precision: "day" })).toEqual({ date: "1998-03-02", time: null });
    expect(castMoment({ obs_date: "1998-03-02", obs_time: "1998-03-02T00:00:00+00:00", time_precision: "day" }).time).toBeNull();
  });
  it("a minute-precision cast shows UTC", () => {
    expect(castMoment({ obs_date: "2015-06-20", obs_time: "2015-06-20T12:34:00+00:00", time_precision: "minute" }))
      .toEqual({ date: "2015-06-20", time: "12:34 UTC" });
    // an offset is normalised to UTC, never shown in the viewer's zone
    expect(castMoment({ obs_date: "2015-06-20", obs_time: "2015-06-20T14:34:00+02:00", time_precision: "minute" }).time).toBe("12:34 UTC");
  });
});

describe("links and credits", () => {
  it("builds the cruise DOI link from a bare DOI or keeps a full URL", () => {
    expect(doiUrl("10.1234/abc")).toBe("https://doi.org/10.1234/abc");
    expect(doiUrl("https://doi.org/10.1234/abc")).toBe("https://doi.org/10.1234/abc");
    expect(doiUrl(null)).toBeNull();
    expect(doiUrl("  ")).toBeNull();
  });
  it("the NVS CC BY 4.0 credit travels only with a ship name", () => {
    expect(creditsFor(GLODAP_CAST as any)).toHaveLength(3);
    const none = creditsFor({ ...(GLODAP_CAST as any), ship_name: null });
    expect(none).toHaveLength(2);
    expect(none.join(" ")).not.toContain("NERC Vocabulary");
  });
});

function ok(body: unknown) {
  return Promise.resolve({ ok: true, status: 200, json: async () => body } as Response);
}
// i18next may fetch a locale file through the stubbed global fetch; only the cast endpoint is under test.
const castCalls = (f: { mock: { calls: unknown[][] } }) => f.mock.calls.filter((c) => String(c[0]).includes("/glodap/cast/"));
const status = (code: number) => Promise.resolve({ ok: false, status: code, json: async () => ({}) } as Response);

beforeEach(() => { useMapStore.setState({ carbonVariable: "dic", carbonDepth: 200 }); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("GlodapCastPanel", () => {
  it("fetches the cast through the BFF by cast_key", async () => {
    const f = vi.fn(() => ok(GLODAP_CAST));
    vi.stubGlobal("fetch", f);
    render(<GlodapCastPanel id="49UF20150620_4511_1" />);
    await screen.findByTestId("glodap-cast-panel");
    expect(castCalls(f).map((c) => c[0])).toEqual([expect.stringMatching(/\/api\/v1\/glodap\/cast\/49UF20150620_4511_1$/)]);
  });

  it("plots flag-2 bottles only, and shows the bottle and the field value at the selected depth", async () => {
    vi.stubGlobal("fetch", vi.fn(() => ok(GLODAP_CAST)));
    const { container } = render(<GlodapCastPanel id="49UF20150620_4511_1" />);
    await screen.findByTestId("glodap-cast-panel");
    // tco2: 5 samples, one flag-0 (205 m), one flag-9 without a value -> 3 plotted points (white circles, r=2)
    const svg = screen.getByTestId("glodap-profile-chart");
    expect(svg.querySelectorAll('circle[r="2"]').length).toBe(3);
    // the dashed field curve and the highlighted bottle used at 200 m
    expect(screen.getByTestId("glodap-field-curve")).toBeTruthy();
    expect(screen.getByTestId("glodap-picked")).toBeTruthy();
    expect(container.textContent).toContain("2150 µmol/kg @ 200 m");           // bottle value + its true depth
    expect(container.textContent).toContain("2140.2 µmol/kg");         // field at 200 m
    expect(container.textContent).toContain("3 acceptable (flag 2)");
    expect(container.textContent).toContain("1 with another flag");
  });

  it("a shallow cast is not squashed by the field curve: the comparison is clipped to the cast's own depths", async () => {
    const shallow = { ...GLODAP_CAST, depth_m: [5, 50, 100],
      variables: { tco2: { values: [2050, 2060, 2070], flags: [2, 2, 2], qc: 1, units: "µmol/kg" } } };
    vi.stubGlobal("fetch", vi.fn(() => ok(shallow)));
    render(<GlodapCastPanel id="x" />);
    const svg = await screen.findByTestId("glodap-profile-chart");
    // field points exist at 0, 200, 500 … 4000 m; only 0 m lies inside a 100 m cast -> one marker, no curve
    expect(screen.queryByTestId("glodap-field-curve")).toBeNull();
    expect(Array.from(svg.querySelectorAll("text")).map((t) => t.textContent)).toContain("100");
    expect(Array.from(svg.querySelectorAll("text")).map((t) => t.textContent)).not.toContain("4000");
  });

  it("states the product versions of points and field", async () => {
    vi.stubGlobal("fetch", vi.fn(() => ok(GLODAP_CAST)));
    const { container } = render(<GlodapCastPanel id="x" />);
    await screen.findByTestId("glodap-cast-panel");
    expect(container.textContent).toContain("GLODAPv3 (2026)");
    expect(container.textContent).toContain("GLODAPv2.2016b mapped climatology (TCO2 and pH normalised to 2002)");
  });

  it("minute-precision cast shows the UTC time; the cruise, ship and DOI link are present", async () => {
    vi.stubGlobal("fetch", vi.fn(() => ok(GLODAP_CAST)));
    const { container } = render(<GlodapCastPanel id="x" />);
    await screen.findByTestId("glodap-cast-panel");
    expect(container.textContent).toContain("2015-06-20 12:34 UTC");
    expect(container.textContent).toContain("49UF20150620");
    expect(container.textContent).toContain("TEST Ship");
    const doi = Array.from(container.querySelectorAll("a")).find((a) => a.href.includes("10.1234/test-cruise"));
    expect(doi?.getAttribute("href")).toBe("https://doi.org/10.1234/test-cruise");
    expect(Array.from(container.querySelectorAll("a")).some((a) => a.href === "https://doi.org/10.25921/m6tp-mj50")).toBe(true);
  });

  it("a date-only cast never shows a fake midnight, and without a ship name carries no NVS credit", async () => {
    const dateOnly = { ...GLODAP_CAST, ship_name: null, obs_time: null, time_precision: "day", obs_date: "1998-03-02" };
    vi.stubGlobal("fetch", vi.fn(() => ok(dateOnly)));
    const { container } = render(<GlodapCastPanel id="x" />);
    await screen.findByTestId("glodap-cast-panel");
    expect(container.textContent).toContain("1998-03-02 (date only, no time recorded)");
    expect(container.textContent).not.toMatch(/00:00/);
    expect(container.textContent).not.toContain("NERC Vocabulary Server");
    expect(container.textContent).not.toContain("TEST Ship");
  });

  it("a cast the source gives no number for reads 'not given', never 'null' or the internal nc", async () => {
    const noCast = { ...GLODAP_CAST, cast_key: "49UF20150620_4511_nc", cast_no: null };
    vi.stubGlobal("fetch", vi.fn(() => ok(noCast)));
    const { container } = render(<GlodapCastPanel id="49UF20150620_4511_nc" />);
    await screen.findByTestId("glodap-cast-panel");
    expect(container.textContent).toContain("4511 / not given");
    expect(container.textContent).not.toMatch(/null|\/ nc|undefined/);
  });

  it("a ship name brings the NVS CC BY 4.0 attribution with it", async () => {
    vi.stubGlobal("fetch", vi.fn(() => ok(GLODAP_CAST)));
    const { container } = render(<GlodapCastPanel id="x" />);
    await screen.findByTestId("glodap-cast-panel");
    expect(container.textContent).toContain("NERC Vocabulary Server");
    expect(container.textContent).toContain("CC BY 4.0");
    expect(container.textContent).toContain("essd-2026-496");
  });

  it("Cant: the chart falls back to DIC with a caption, and the field row still reads Cant", async () => {
    useMapStore.setState({ carbonVariable: "cant", carbonDepth: 0 });
    vi.stubGlobal("fetch", vi.fn(() => ok(GLODAP_CAST)));
    const { container } = render(<GlodapCastPanel id="x" />);
    await screen.findByTestId("glodap-cast-panel");
    expect(container.textContent).toContain("Bottles carry no anthropogenic CO₂");
    expect(container.textContent).toContain("55.4 µmol/kg");           // the Cant field value the map shows
    expect(screen.getByTestId("glodap-profile-chart")).toBeTruthy();   // DIC profile
  });

  it("DIC selected: no Cant caption", async () => {
    vi.stubGlobal("fetch", vi.fn(() => ok(GLODAP_CAST)));
    const { container } = render(<GlodapCastPanel id="x" />);
    await screen.findByTestId("glodap-cast-panel");
    expect(container.textContent).not.toContain("Bottles carry no anthropogenic CO₂");
  });

  it("no acceptable bottle in the depth window is said so, not drawn as a blank", async () => {
    useMapStore.setState({ carbonVariable: "dic", carbonDepth: 1000 });
    vi.stubGlobal("fetch", vi.fn(() => ok(GLODAP_CAST)));
    const { container } = render(<GlodapCastPanel id="x" />);
    await screen.findByTestId("glodap-cast-panel");
    expect(container.textContent).toContain("no acceptable bottle within 950–1050 m");
    expect(screen.queryByTestId("glodap-picked")).toBeNull();
  });

  it("a variable without a field counterpart still reports the bottle in the window (salinity)", async () => {
    // Regression: `levels` exists only for DIC/TA/pH, so salinity used to read "no acceptable bottle" always.
    const withSalinity = { ...GLODAP_CAST, variables: { ...GLODAP_CAST.variables,
      salinity: { values: [35.1, 34.9, 34.95, 34.7, 34.9], flags: [2, 2, 0, 2, 2], qc: 1, units: "PSU" } } };
    vi.stubGlobal("fetch", vi.fn(() => ok(withSalinity)));
    const { container } = render(<GlodapCastPanel id="x" />);
    await screen.findByTestId("glodap-cast-panel");
    fireEvent.change(container.querySelector("select")!, { target: { value: "salinity" } });
    expect(container.textContent).toContain("34.9 PSU @ 200 m");
    expect(container.textContent).not.toContain("no acceptable bottle within");
    expect(screen.getByTestId("glodap-picked")).toBeTruthy();
    // and a depth whose window holds only a flag-0 sample is honestly "none"
    cleanup();
    useMapStore.setState({ carbonDepth: 500 });
    vi.stubGlobal("fetch", vi.fn(() => ok({ ...withSalinity, depth_m: [5, 200, 500, 1000, 4000],
      variables: { ...withSalinity.variables, salinity: { ...withSalinity.variables.salinity, flags: [2, 2, 0, 2, 2] } } })));
    const second = render(<GlodapCastPanel id="x" />);
    await screen.findByTestId("glodap-cast-panel");
    fireEvent.change(second.container.querySelector("select")!, { target: { value: "salinity" } });
    expect(second.container.textContent).toContain("no acceptable bottle within 450–550 m");
  });

  it("a variable with no acceptable sample says so instead of an empty chart", async () => {
    const bad = { ...GLODAP_CAST, variables: { ...GLODAP_CAST.variables, tco2: { values: [2050, 2150, null, null, null], flags: [0, 0, 9, 9, 9], qc: 1, units: "µmol/kg" } } };
    vi.stubGlobal("fetch", vi.fn(() => ok(bad)));
    render(<GlodapCastPanel id="x" />);
    await screen.findByTestId("glodap-no-acceptable");
    expect(screen.queryByTestId("glodap-profile-chart")).toBeNull();
  });

  it("404 is a distinct 'no longer exists' state", async () => {
    vi.stubGlobal("fetch", vi.fn(() => status(404)));
    render(<GlodapCastPanel id="GONE_1_1" />);
    expect(await screen.findByText(/no longer exists/)).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("503 is 'unavailable' with a retry that refetches", async () => {
    const f = vi.fn().mockImplementationOnce(() => status(503)).mockImplementation(() => ok(GLODAP_CAST));
    vi.stubGlobal("fetch", f);
    render(<GlodapCastPanel id="49UF20150620_4511_1" />);
    const retry = await screen.findByRole("button", { name: "Try again" });
    expect(screen.queryByText(/no longer exists/)).toBeNull();
    fireEvent.click(retry);
    await screen.findByTestId("glodap-cast-panel");
    expect(castCalls(f)).toHaveLength(2);
  });

  it("a network failure is also 'unavailable', never a blank panel", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("offline"))));
    const { container } = render(<GlodapCastPanel id="x" />);
    await waitFor(() => expect(container.textContent).toContain("could not be loaded"));
  });
});
