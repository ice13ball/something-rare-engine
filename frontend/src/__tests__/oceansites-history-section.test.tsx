// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// The "Historical record" section (which names its source) of the OceanSITES station
// panel. 971 of 1,038 moorings are not operational and show no live reading;
// where the GDAC archive holds their measurements, this section is how a reader
// sees them.
//
// The fixture is REAL: two responses of GET /v1/oceansites/{ref}/history captured
// from tds0.ifremer.fr data on 2026-10-01 — PAP-2 (TMP236332161) untouched, and
// TAO 0N140W (5100311) with each series cut to its first 10 points + the last
// one (the payload is 155 KB; the series metadata is untouched).
//
// Each assertion below targets a phrase that appears only in its own element,
// and counts matches exactly: "at least one" would stay green if the section
// rendered the same line for every series, or for none of them but one.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { OceansitesPanel } from "../components/panels/ocean/OceansitesPanel";
import fixtures from "./fixtures/oceansites-history.json";

const PAP = fixtures.pap2_default;
const TAO = fixtures.tao_0n140w_default_points_trimmed;

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const ok = (body: unknown) => Promise.resolve({ ok: true, status: 200, json: async () => body } as Response);
const stubFetch = (impl: (url: string) => Promise<Response>) => {
  const fn = vi.fn(impl);
  vi.stubGlobal("fetch", fn);
  return fn;
};

const station = (extra: Record<string, unknown> = {}) => ({
  ref: "TMP236332161",
  name: "PAP-2",
  status: "CLOSED",
  network: "OceanSITES",
  model: "Subsurface Mooring Custom",
  latest_obs: null,
  history_start: "2002-10-06T20:00:00+00:00",
  history_end: "2005-07-08T09:45:00+00:00",
  history_files: 3,
  ...extra,
});
const renderWith = (extra: Record<string, unknown> = {}) =>
  render(<OceansitesPanel properties={station(extra) as never} />);

// i18n lazy-loads `/locales/<lng>/legend.json` through the same global fetch; whether that lands
// inside a test depends on machine load, so only the history requests are counted.
const historyCalls = (fn: { mock: { calls: unknown[][] } }) =>
  fn.mock.calls.filter(c => String(c[0]).includes("/oceansites/")).length;

const count = (phrase: RegExp) => screen.queryAllByText(phrase).length;

describe("OceanSITES historical record: when the section exists", () => {
  it.each([
    ["zero files", { history_files: 0 }],
    ["no summary at all", { history_files: undefined, history_start: undefined, history_end: undefined }],
    ["a null count", { history_files: null }],
  ])("is absent, and fetches nothing, with %s", (_name, extra) => {
    const fetchMock = stubFetch(() => ok(PAP));
    renderWith(extra);
    expect(count(/Historical record/)).toBe(0);
    expect(historyCalls(fetchMock)).toBe(0);
  });

  it("is present when the station has catalogue files, and asks the BFF path exactly once", async () => {
    const fetchMock = stubFetch(() => ok(PAP));
    renderWith();
    expect(count(/^Historical record$/)).toBe(1);
    await screen.findAllByTestId("oceansites-series");
    expect(count(/^OceanSITES GDAC \(IFREMER\)$/)).toBe(1);   // a GDAC-only record names GDAC, and only GDAC
    expect(count(/Arctic Data Center/)).toBe(0);
    // Count the history requests only: i18n lazy-loads `/locales/<lng>/legend.json` through the
    // same global fetch, and whether that lands inside this test depends on machine load.
    const urls = fetchMock.mock.calls.map(c => String(c[0])).filter(u => !u.startsWith("/locales/"));
    expect(urls.length).toBe(1);
    // ⛔ `${API}/api/v1/...`: the bare `/v1/...` path silently fails in the SPA.
    expect(urls[0]).toMatch(/\/api\/v1\/oceansites\/TMP236332161\/history$/);
  });

  it("shows the span as dates only, and the catalogue file count", async () => {
    stubFetch(() => ok(PAP));
    renderWith();
    expect(count(/^2002-10-06 – 2005-07-08$/)).toBe(1);
    await screen.findAllByTestId("oceansites-series");
    expect(count(/^Files in the archive$/)).toBe(1);
    expect(screen.getByText("Files in the archive").nextSibling?.textContent).toBe("3");
    expect(screen.getByText("Files read for the plots").nextSibling?.textContent).toBe("3");
  });
});

describe("OceanSITES historical record: what is drawn", () => {
  it("draws one sparkline per series, with an accessible label naming variable, depth and span", async () => {
    stubFetch(() => ok(PAP));
    renderWith();
    const rows = await screen.findAllByTestId("oceansites-series");
    expect(rows.length).toBe(PAP.series.length); // 6
    expect(screen.getAllByTestId("oceansites-sparkline").length).toBe(6);
    expect(screen.getAllByRole("img", { name: /^Salinity, 1003 m, 2004-06-22 to 2005-07-04$/ }).length).toBe(1);
  });

  it("groups by variable, and says '3 of N depths shown' per variable when more exist", async () => {
    stubFetch(() => ok(PAP));
    renderWith();
    await screen.findAllByTestId("oceansites-series");
    expect(screen.getAllByTestId("oceansites-variable").length).toBe(2); // salinity, temperature
    expect(count(/3 of 20 depths shown/)).toBe(1);  // salinity: 20 depths served
    expect(count(/3 of 22 depths shown/)).toBe(1);  // temperature: 22
  });

  it("says nothing about depths when every depth is already shown", async () => {
    const all = JSON.parse(JSON.stringify(PAP)) as typeof PAP;
    for (const s of all.series) s.depths_available = all.series.filter(o => o.standard_name === s.standard_name).map(o => o.depth_m);
    stubFetch(() => ok(all));
    renderWith();
    await screen.findAllByTestId("oceansites-series");
    expect(count(/depths shown/)).toBe(0);
  });

  it("states units exactly as the archive sent them, including a bare '1'", async () => {
    stubFetch(() => ok(TAO));
    renderWith({ ref: "5100311" });
    await screen.findAllByTestId("oceansites-series");
    fireEvent.click(screen.getByRole("button", { name: /Show all 7 variables/ }));
    expect(count(/^units: cm\/s/)).toBe(2);               // eastward + northward
    expect(count(/^units: m\/s/)).toBe(2);
    expect(count(/^units: degree_Celsius/)).toBe(2);      // SST + sea water temperature
    expect(count(/^units: 1/)).toBe(1);                   // practical salinity
  });

  it("keeps cm/s and m/s velocity apart even though standard_name and depth can coincide", async () => {
    stubFetch(() => ok(TAO));
    renderWith({ ref: "5100311" });
    await screen.findAllByTestId("oceansites-series");
    // Collapsed view: eastward cm/s (5, 25, 120 m) and eastward m/s (45, 150, 290 m)
    // are two blocks, never one block of six depths.
    const blocks = screen.getAllByTestId("oceansites-variable");
    expect(blocks.length).toBe(4);
    expect(blocks[0].textContent).toMatch(/units: cm\/s/);
    expect(blocks[1].textContent).toMatch(/units: m\/s/);
    expect(blocks[0].querySelectorAll("[data-testid=oceansites-series]").length).toBe(3);
    expect(blocks[1].querySelectorAll("[data-testid=oceansites-series]").length).toBe(3);
  });

  it("shows a series whose file declares no depth without any depth, never as 'null m'", async () => {
    // The API sends depth_m: null for a file with no DEPTH variable. The 150 m salinity series
    // becomes that file's series; its row must carry no depth line and a label without one.
    const body = JSON.parse(JSON.stringify(PAP)) as { series: { depth_m: number | null }[] };
    body.series[1].depth_m = null;
    stubFetch(() => ok(body));
    renderWith();
    const rows = await screen.findAllByTestId("oceansites-series");
    expect(rows.length).toBe(6);
    expect(document.body.textContent).not.toMatch(/null/);
    expect(count(/^\d+ m$/)).toBe(5);                                      // five depths, the sixth shows none
    expect(count(/^150 m$/)).toBe(0);
    expect(screen.getAllByRole("img", { name: /^Salinity, 2002-10-08 to 2002-12-08$/ }).length).toBe(1);
    expect(screen.queryAllByRole("img", { name: /null|NaN|undefined/ }).length).toBe(0);
    // the no-depth series is listed after the real depths of its variable, not first (null is not 0 m)
    const salinity = screen.getAllByTestId("oceansites-variable")[0];
    const order = [...salinity.querySelectorAll("[data-testid=oceansites-series]")]
      .map(r => r.querySelector("p")?.textContent);
    expect(order).toEqual(["10 m", "1003 m", "2002-10-08 – 2002-12-08"]);
  });

  it("collapses to four variables and shows the rest on request", async () => {
    stubFetch(() => ok(TAO));
    renderWith({ ref: "5100311" });
    await screen.findAllByTestId("oceansites-series");
    expect(screen.getAllByTestId("oceansites-variable").length).toBe(4);
    fireEvent.click(screen.getByRole("button", { name: "Show all 7 variables" }));
    expect(screen.getAllByTestId("oceansites-variable").length).toBe(7);
    expect(screen.getAllByTestId("oceansites-sparkline").length).toBe(TAO.series.length); // 19
    fireEvent.click(screen.getByRole("button", { name: "Show fewer variables" }));
    expect(screen.getAllByTestId("oceansites-variable").length).toBe(4);
  });

  it("offers no 'show all' toggle when four variables or fewer exist", async () => {
    stubFetch(() => ok(PAP));
    renderWith();
    await screen.findAllByTestId("oceansites-series");
    expect(screen.queryAllByRole("button").length).toBe(0);
  });
});

describe("OceanSITES historical record: three different counts stay three", () => {
  it("shows the source's quality-flag withholding only on the series that has it", async () => {
    stubFetch(() => ok(PAP));
    renderWith();
    await screen.findAllByTestId("oceansites-series");
    expect(count(/^Withheld by the source's quality flag: 1$/)).toBe(1);      // salinity at 1003 m
    expect(count(/Withheld by the source's quality flag/)).toBe(1);
  });

  it("reports empty file values separately, once per series that has some", async () => {
    stubFetch(() => ok(PAP));
    renderWith();
    await screen.findAllByTestId("oceansites-series");
    expect(count(/^Empty in the file \(no value recorded\): 119$/)).toBe(1);
    expect(count(/^Empty in the file \(no value recorded\): 116$/)).toBe(2);
    expect(count(/Empty in the file/)).toBe(3);
  });

  it("reports dropped same-instant duplicates, and only when there are some", async () => {
    stubFetch(() => ok(PAP));
    const { unmount } = renderWith();
    await screen.findAllByTestId("oceansites-series");
    expect(count(/Same-instant duplicates dropped/)).toBe(0);
    unmount();

    stubFetch(() => ok(TAO));
    renderWith({ ref: "5100311" });
    await screen.findAllByTestId("oceansites-series");
    // TAO eastward and northward cm/s at 25 m and 120 m: four series, each dropped one instant.
    expect(count(/^Same-instant duplicates dropped \(overlapping files\): 1$/)).toBe(4);
  });
});

describe("OceanSITES historical record: the physical-range count", () => {
  const RANGE = /^Points outside the physical range for this quantity, not plotted: 7$/;
  const withRange = (n: number | undefined) => {
    const body = structuredClone(PAP) as typeof PAP;
    (body.series[0] as Record<string, unknown>).range_withheld = n;
    return body;
  };

  it("appears only on the series that has some, and only when the count is above zero", async () => {
    stubFetch(() => ok(PAP));                       // the captured response: no range_withheld at all
    const first = renderWith();
    await screen.findAllByTestId("oceansites-series");
    expect(count(/outside the physical range/)).toBe(0);
    first.unmount();

    stubFetch(() => ok(withRange(0)));
    const zero = renderWith();
    await screen.findAllByTestId("oceansites-series");
    expect(count(/outside the physical range/)).toBe(0);
    zero.unmount();

    stubFetch(() => ok(withRange(7)));
    renderWith();
    await screen.findAllByTestId("oceansites-series");
    expect(count(RANGE)).toBe(1);
    expect(count(/outside the physical range/)).toBe(1);
  });

  it("is a sentence of its own, not folded into the quality-flag or the empty-value count", async () => {
    stubFetch(() => ok(withRange(7)));
    renderWith();
    await screen.findAllByTestId("oceansites-series");
    // the same three counts the captured response already shows, unchanged by the new one
    expect(count(/^Withheld by the source's quality flag: 1$/)).toBe(1);
    expect(count(/Withheld by the source's quality flag/)).toBe(1);
    expect(count(/Empty in the file/)).toBe(3);
    expect(count(RANGE)).toBe(1);
  });

  it("draws min and max from the points it was sent, which are already net of withheld extremes", async () => {
    const body = withRange(7);
    body.series[0].points = [["2002-10-14T04:00:00Z", 35.1], ["2002-10-15T04:00:00Z", 35.9], ["2002-10-16T04:00:00Z", 35.5]] as never;
    stubFetch(() => ok(body));
    renderWith();
    await screen.findAllByTestId("oceansites-series");
    expect(count(/^min 35\.1 · max 35\.9$/)).toBe(1);
  });
});

describe("OceanSITES historical record: the range sentence exists in every language", () => {
  const read = (lng: string) =>
    JSON.parse(readFileSync(resolve(__dirname, `../../public/locales/${lng}/panels.json`), "utf-8"));

  it.each(["en", "pl", "fr", "de"])("%s has historyRangeWithheld with its count, and not the QC sentence", lng => {
    const o = read(lng).oceansites;
    expect(o.historyRangeWithheld).toContain("{{count}}");
    expect(o.historyRangeWithheld).not.toBe(o.historyQcWithheld);
  });

  it("is a real translation: no two languages share the sentence", () => {
    const all = ["en", "pl", "fr", "de"].map(l => read(l).oceansites.historyRangeWithheld);
    expect(new Set(all).size).toBe(4);
  });
});

describe("OceanSITES historical record: honesty about what the points are", () => {
  it("says the points are every N-th real measurement, not averages, exactly once", async () => {
    stubFetch(() => ok(PAP));
    renderWith();
    await screen.findAllByTestId("oceansites-series");
    expect(count(/real measurements, thinned to every N-th sample — not averages/)).toBe(1);
  });

  it("states how many points are plotted of how many measurements were stored", async () => {
    stubFetch(() => ok(PAP));
    renderWith();
    await screen.findAllByTestId("oceansites-series");
    expect(count(/^181 of 27139 measurements plotted$/)).toBe(1);
  });

  it("prints every citation the archive sent, each once", async () => {
    stubFetch(() => ok(PAP));
    renderWith();
    await screen.findAllByTestId("oceansites-series");
    expect(PAP.citations.length).toBe(2);
    for (const c of PAP.citations) expect(screen.queryAllByText(c).length).toBe(1);
  });

  it("links to the GDAC THREDDS directory of the first file's site", async () => {
    stubFetch(() => ok(PAP));
    renderWith();
    await screen.findAllByTestId("oceansites-series");
    const link = screen.getByRole("link", { name: /Browse the files in the GDAC \(THREDDS\)/ });
    expect(link.getAttribute("href"))
      .toBe("https://tds0.ifremer.fr/thredds/catalog/CORIOLIS-OCEANSITES-GDAC-OBS/DATA/PAP/catalog.html");
  });
});

describe("OceanSITES historical record: states", () => {
  it("says it is loading while the request is open, and nothing else yet", () => {
    stubFetch(() => new Promise<Response>(() => {}));
    renderWith();
    expect(count(/^Loading the historical record…$/)).toBe(1);
    expect(count(/Could not load/)).toBe(0);
    expect(count(/readable measurements/)).toBe(0);
  });

  it.each([
    ["a network failure", () => Promise.reject(new TypeError("Failed to fetch"))],
    ["an HTTP 503", () => Promise.resolve({ ok: false, status: 503, json: async () => ({}) } as Response)],
    ["a body that is not a history", () => ok({ detail: "nope" })],
  ])("says it could not load after %s — which is not 'no history'", async (_n, impl) => {
    stubFetch(impl as () => Promise<Response>);
    renderWith();
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(count(/^Could not load the historical record\./)).toBe(1);
    expect(count(/readable measurements/)).toBe(0);
    expect(count(/Loading the historical record/)).toBe(0);
  });

  it("says the archive has files but no readable measurements when the series list is empty", async () => {
    stubFetch(() => ok({ ...PAP, series: [], files: [] }));
    renderWith();
    await waitFor(() => expect(count(/we hold no readable measurements/)).toBe(1));
    expect(screen.queryAllByRole("alert").length).toBe(0);
    expect(count(/Could not load/)).toBe(0);
    expect(screen.queryAllByTestId("oceansites-sparkline").length).toBe(0);
  });

  it("does not fetch again when the panel re-renders for the same station", async () => {
    const fetchMock = stubFetch(() => ok(PAP));
    const { rerender } = renderWith();
    await screen.findAllByTestId("oceansites-series");
    rerender(<OceansitesPanel properties={station({ obs_fetched_at: "2026-10-01" }) as never} />);
    expect(historyCalls(fetchMock)).toBe(1);
  });
});

describe("OceanSITES: a subsurface mooring that is operational", () => {
  // Real OceanOPS model names, read from production 2026-10-01.
  const SUBSURFACE = /instruments of this mooring sit below the surface/;
  const GENERIC = /none of our sources/;

  it.each(["Subsurface Mooring Custom", "Benthic Mooring Custom"])(
    "explains why a %s has no live reading: no satellite link, data only after recovery",
    (model) => {
      renderWith({ status: "OPERATIONAL", model, history_files: 0 });
      expect(count(SUBSURFACE)).toBe(1);
      expect(count(/only after the mooring is recovered/)).toBe(1);
      expect(count(GENERIC)).toBe(0);
    },
  );

  it("keeps the generic message for an operational surface mooring", () => {
    renderWith({ status: "OPERATIONAL", model: "TAO_REFRESH", history_files: 0 });
    expect(count(GENERIC)).toBe(1);
    expect(count(SUBSURFACE)).toBe(0);
  });

  // Changed 2026-10-02: a closed subsurface mooring used to get the generic
  // "no longer transmits", which implies it once transmitted. It gets its own
  // past-tense line — and still never the OPERATIONAL subsurface one.
  it("tells a closed subsurface mooring it never transmitted, not the operational line", () => {
    renderWith({ status: "CLOSED", model: "Subsurface Mooring Custom", history_files: 0 });
    expect(count(/never sent live readings/)).toBe(1);
    expect(count(/no longer transmits/)).toBe(0);
    expect(count(SUBSURFACE)).toBe(0);
  });

  it("does not use it when the station has a reading", () => {
    renderWith({
      status: "OPERATIONAL", model: "Subsurface Mooring Custom", history_files: 0,
      obs_source: "GDAC", obs_fetched_at: new Date().toISOString(),
      latest_obs: { wtmp: 12.3, obs_time: new Date().toISOString() },
    });
    expect(count(SUBSURFACE)).toBe(0);
  });
});
