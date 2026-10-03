// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// The Historical record section reads from TWO archives: the OceanSITES GDAC and, for
// the Davis Strait moorings, the NSF Arctic Data Center (doi:10.18739/A2416T169).
// ⛔ What is protected: the archive link and the source named must follow files[].source.
// The panel used to take the THREDDS directory from files[0].file.split("/")[1]; for an
// Arctic Data Center file ("ADC/A2416T169/<name>.nc") that is "A2416T169" — a GDAC
// directory that does not exist — and the section would have said "OceanSITES GDAC"
// over data that never came from it.
//
// Fixture: oceansites-history-adc.json — `adc_only` is the endpoint's response for the
// DS_C4 2013 row built from a REAL trimmed Davis netCDF; `mixed` adds a real GDAC file
// and series (no real station has both yet), see the fixture's _provenance.
// Each assertion targets a phrase unique to its own element and counts exactly.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { OceansitesPanel } from "../components/panels/ocean/OceansitesPanel";
import fixtures from "./fixtures/oceansites-history-adc.json";

const ADC_ONLY = fixtures.adc_only;
const MIXED = fixtures.mixed;
const DOI_URL = "https://doi.org/10.18739/A2416T169";
const GDAC_PAP = "https://tds0.ifremer.fr/thredds/catalog/CORIOLIS-OCEANSITES-GDAC-OBS/DATA/PAP/catalog.html";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const ok = (body: unknown) => Promise.resolve({ ok: true, status: 200, json: async () => body } as Response);
const stubFetch = (body: unknown) => vi.stubGlobal("fetch", vi.fn(() => ok(body)));

const station = (extra: Record<string, unknown> = {}) => ({
  ref: "TMP-1036802018",
  name: "DS_C4",
  status: "CLOSED",
  network: "OceanSITES",
  model: "Subsurface Mooring Custom",
  latest_obs: null,
  history_start: "2013-09-16T23:06:00+00:00",
  history_end: "2015-09-11T13:06:00+00:00",
  history_files: 1,
  ...extra,
});
const renderWith = (extra: Record<string, unknown> = {}) =>
  render(<OceansitesPanel properties={station(extra) as never} />);

const count = (phrase: RegExp) => screen.queryAllByText(phrase).length;
const hrefs = () => screen.queryAllByRole("link").map(a => a.getAttribute("href"));
const ready = () => screen.findAllByTestId("oceansites-series");

describe("Historical record from the Arctic Data Center only", () => {
  it("links the dataset's DOI, and offers no GDAC directory", async () => {
    stubFetch(ADC_ONLY);
    renderWith();
    await ready();
    const link = screen.getByRole("link", { name: /Open the dataset at the NSF Arctic Data Center \(DOI\)/ });
    expect(link.getAttribute("href")).toBe(DOI_URL);
    expect(screen.queryAllByRole("link", { name: /GDAC/ }).length).toBe(0);
    expect(hrefs().filter(h => h?.includes("thredds")).length).toBe(0);
  });

  it("names the Arctic Data Center as the source and never claims the GDAC", async () => {
    stubFetch(ADC_ONLY);
    renderWith();
    await ready();
    expect(count(/^NSF Arctic Data Center \(Davis Strait moorings\)$/)).toBe(1);
    expect(count(/^Source$/)).toBe(1);
    expect(count(/^Historical record$/)).toBe(1);
    // Nothing the history section prints says GDAC: neither its title, its source row, its link.
    expect(count(/^OceanSITES GDAC \(IFREMER\)$/)).toBe(0);
    expect(count(/Historical record \(OceanSITES GDAC\)/)).toBe(0);
  });

  it("prints the dataset's citation, once, and not the OceanSITES one", async () => {
    stubFetch(ADC_ONLY);
    renderWith();
    await ready();
    expect(ADC_ONLY.citations.length).toBe(1);
    expect(count(new RegExp(ADC_ONLY.citation.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")))).toBe(1);
    expect(count(/international OceanSITES project/)).toBe(0);
  });

  it("draws the velocity series with the units the file declared", async () => {
    stubFetch(ADC_ONLY);
    renderWith();
    await ready();
    expect(screen.queryAllByTestId("oceansites-series").length).toBe(2);   // eastward and northward at 500 m
    expect(count(/^units: m s-1$/)).toBe(2);
    expect(count(/^500 m$/)).toBe(2);
    expect(count(/^Empty in the file \(no value recorded\): 27$/)).toBe(2);   // the real fill values, counted
  });

  it("collapses the one DOI shared by many files into one link", async () => {
    const second = { ...ADC_ONLY.files[0], file: "ADC/A2416T169/Davis_RCM_velocity_C4_2013_250m_L2.nc" };
    stubFetch({ ...ADC_ONLY, files: [ADC_ONLY.files[0], second], n_files_read: 2 });
    renderWith({ history_files: 2 });
    await ready();
    expect(hrefs().filter(h => h === DOI_URL).length).toBe(1);
  });
});

describe("Historical record from both archives", () => {
  it("names both sources, GDAC first, in one row", async () => {
    stubFetch(MIXED);
    renderWith({ history_files: 2 });
    await ready();
    expect(count(/^OceanSITES GDAC \(IFREMER\) · NSF Arctic Data Center \(Davis Strait moorings\)$/)).toBe(1);
  });

  it("links each archive to its own place: THREDDS for the GDAC file's site, the DOI for the ADC file", async () => {
    stubFetch(MIXED);
    renderWith({ history_files: 2 });
    await ready();
    expect(screen.getByRole("link", { name: /Browse the files in the GDAC \(THREDDS\)/ }).getAttribute("href")).toBe(GDAC_PAP);
    expect(screen.getByRole("link", { name: /Open the dataset at the NSF Arctic Data Center/ }).getAttribute("href")).toBe(DOI_URL);
  });

  it("does not read the GDAC directory off an Arctic Data Center file that happens to come first", async () => {
    stubFetch({ ...MIXED, files: [...MIXED.files].reverse() });
    renderWith({ history_files: 2 });
    await ready();
    const thredds = hrefs().filter(h => h?.includes("thredds"));
    expect(thredds).toEqual([GDAC_PAP]);
    expect(hrefs().some(h => h?.includes("A2416T169") && h.includes("thredds"))).toBe(false);
  });

  it("prints both citations, each once, OceanSITES first", async () => {
    stubFetch(MIXED);
    renderWith({ history_files: 2 });
    await ready();
    expect(MIXED.citations.length).toBe(2);
    for (const c of MIXED.citations) expect(screen.queryAllByText(c).length).toBe(1);
    const shown = screen.getAllByText(/international OceanSITES project|NSF Arctic Data Center\. https/).map(e => e.textContent);
    expect(shown).toEqual(MIXED.citations);
  });
});

describe("Historical record from a source this panel does not know", () => {
  it("neither names nor links it", async () => {
    stubFetch({ ...ADC_ONLY, files: [{ ...ADC_ONLY.files[0], source: "something_new", url: "https://example.org/x" }] });
    renderWith();
    await ready();
    expect(count(/^Source$/)).toBe(0);
    expect(hrefs()).not.toContain("https://example.org/x");
    expect(screen.queryAllByRole("link", { name: /GDAC|Arctic Data Center/ }).length).toBe(0);
  });

  it("does not turn a non-https url into a link", async () => {
    stubFetch({ ...ADC_ONLY, files: [{ ...ADC_ONLY.files[0], url: "javascript:alert(1)" }] });
    renderWith();
    await ready();
    expect(hrefs().some(h => h?.startsWith("javascript:"))).toBe(false);
  });
});

describe("The 'no files' sentence names both archives that were searched", () => {
  it("in English, once, with how each archive was searched", () => {
    renderWith({ history_files: 0, status: "INACTIVE" });
    expect(count(/^Neither the OceanSITES GDAC archive nor the Davis Strait mooring dataset of the NSF Arctic Data Center holds files matched to this mooring \(GDAC: by position and name; Arctic Data Center: by mooring name and deployment date\)\.$/)).toBe(1);
    expect(count(/^The OceanSITES GDAC archive holds no files/)).toBe(0);
  });

  const read = (lng: string, file: string) =>
    JSON.parse(readFileSync(resolve(__dirname, `../../public/locales/${lng}/${file}.json`), "utf-8"));

  it.each(["en", "pl", "fr", "de"])("%s names the GDAC and the Arctic Data Center", lng => {
    const none = read(lng, "panels").oceansites.historyNone as string;
    expect(none).toMatch(/GDAC/);
    expect(none).toMatch(/Arctic Data Center/);
  });

  it("is a real translation: four different sentences", () => {
    const all = ["en", "pl", "fr", "de"].map(l => read(l, "panels").oceansites.historyNone);
    expect(new Set(all).size).toBe(4);
  });

  it.each(["en", "pl", "fr", "de"])("%s has every source key the section uses, and none of them claims the GDAC for the ADC", lng => {
    const o = read(lng, "panels").oceansites;
    expect(o.historySourceGdac).toMatch(/GDAC/);
    expect(o.historySourceGdac).not.toMatch(/Arctic/);
    expect(o.historySourceAdc).toMatch(/Arctic Data Center/);
    expect(o.historySourceAdc).not.toMatch(/GDAC/);
    expect(o.historyBrowseAdc).toMatch(/Arctic Data Center/);
    expect(o.historySourceLabel.length).toBeGreaterThan(0);
    expect(o.historySectionTitle).not.toMatch(/GDAC/);   // the title is shown before the source is known
  });

  it.each(["en", "pl", "fr", "de"])("%s legend names the Arctic Data Center in the layer and the verify text", lng => {
    const d = read(lng, "legend");
    expect(d.layers.oceansitesMoorings.source).toMatch(/Arctic Data Center/);
    expect(d.layers.oceansitesMoorings.reading).toMatch(/Arctic Data Center/);
    expect(d.verify.oceansites).toMatch(/10\.18739\/A2416T169/);
  });
});
