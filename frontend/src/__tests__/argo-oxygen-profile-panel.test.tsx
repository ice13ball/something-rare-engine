// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import {
  ArgoOxygenProfilePanel, goodSeries, otherCounts, modeLabelKey, profileMoment,
} from "../components/panels/fields/ArgoOxygenProfilePanel";
import { useMapStore } from "../store/mapStore";
import { ARGO_OXYGEN_PROFILE as payload } from "./detailPanelFetchFixtures";
import i18n from "../i18n";
import pl from "../../public/locales/pl/panels.json";
import de from "../../public/locales/de/panels.json";
import fr from "../../public/locales/fr/panels.json";

const levels = payload.levels as any;
const respond = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

describe("argo profile panel helpers", () => {
  it("charts only adjusted QC 1/2 values of an A/D profile", () => {
    expect(goodSeries(levels, "D")).toEqual([[5.9, 259.6], [495.8, 200.1]]);
    expect(goodSeries(levels, "A")).toEqual([[5.9, 259.6], [495.8, 200.1]]);
    expect(goodSeries(levels, "R")).toEqual([]);                          // raw real-time is never charted
  });
  it("counts what it does not chart, by reason", () => {
    expect(otherCounts(levels, "D")).toEqual({ adjustedFlagged: 1, rawOnly: 1 });
    // a real-time profile: its adjusted values (if any) are not good either; nothing is charted, all counted
    expect(otherCounts(levels, "R")).toEqual({ adjustedFlagged: 3, rawOnly: 1 });
  });
  it("names the data mode", () => {
    expect(modeLabelKey("D")).toBe("argoProfile.mode.delayed");
    expect(modeLabelKey("A")).toBe("argoProfile.mode.adjusted");
    expect(modeLabelKey("R")).toBe("argoProfile.mode.realtime");
  });
  it("shows the time in UTC to the minute, and says nothing when there is none", () => {
    expect(profileMoment("2006-10-22T02:16:24+00:00")).toBe("2006-10-22 02:16 UTC");
    expect(profileMoment("2006-10-22T23:30:00-03:00")).toBe("2006-10-23 02:30 UTC");   // never the viewer's zone
    expect(profileMoment(null)).toBeNull();
    expect(profileMoment("not a date")).toBeNull();
  });
});

describe("ArgoOxygenProfilePanel", () => {
  beforeEach(() => useMapStore.setState({ oxygenDepth: 500, oxygenView: "change" } as any));
  afterEach(() => { vi.restoreAllMocks(); cleanup(); });
  const open = (p: unknown = payload, id = "aoml_1900722_001") => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(respond(p));
    return render(<ArgoOxygenProfilePanel id={id} />);
  };

  it("shows the value at the selected depth beside the ISAS recent field, and never a Δ", async () => {
    open();
    // getAllByText: the same number can also appear as a chart tick or in the title
    await waitFor(() => expect(screen.getAllByText(/200\.1/).length).toBeGreaterThan(0));
    expect(screen.getAllByText(/205\.0/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/Δ|change vs/i)).toBeNull();
    expect(screen.getAllByText(/1900722/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/delayed mode/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/International Argo Program/).length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: /data file|GDAC/i }).getAttribute("href")).toBe(payload.source_url);
  });

  it("the value row carries the depth AND the pressure of the level, in separate units", async () => {
    open();
    await waitFor(() => expect(screen.getByText("200.1 µmol/kg at 495.8 m (500.0 dbar)")).toBeTruthy());
  });

  it("follows the selected depth: at 2000 m there is no good value and the window is named; the field value stays", async () => {
    useMapStore.setState({ oxygenDepth: 2000 } as any);
    open();
    await waitFor(() => expect(screen.getByText(/No good adjusted value in 1900–2100 m/)).toBeTruthy());
    expect(screen.getAllByText(/180\.0 µmol\/kg/).length).toBeGreaterThan(0);          // the ISAS20 mean at 2000 m
  });

  it("charts the good values solid and the ISAS mean dashed, with the selected window as a band; counts the rest", async () => {
    open();
    await waitFor(() => expect(screen.getByTestId("argo-profile-chart")).toBeTruthy());
    expect(screen.getByTestId("argo-field-curve")).toBeTruthy();
    expect(screen.getByTestId("argo-depth-window")).toBeTruthy();
    // exactly the 2 good points are solid; the 0 and 500 m field rings are drawn, 2000 m is beyond this profile
    const chart = screen.getByTestId("argo-profile-chart");
    expect(chart.querySelectorAll("circle[fill='rgb(248 250 252)']").length).toBe(2);
    expect(chart.querySelectorAll("circle[fill='none']").length).toBe(2);
    // the counts are over the STORED levels (4 here) and say so, apart from the source-level "good of" line below
    expect(screen.getByText("1 adjusted value flagged questionable or bad among the stored levels (4) — not charted")).toBeTruthy();
    expect(screen.getByText("1 raw-only value among the stored levels (4) — not charted")).toBeTruthy();
    expect(screen.getByText(/70 good of 71 levels/)).toBeTruthy();
  });

  it("date is shown to the minute in UTC; a profile with no time says so instead of inventing one", async () => {
    open();
    await waitFor(() => expect(screen.getByText("2006-10-22 02:16 UTC")).toBeTruthy());
    cleanup();
    open({ ...payload, profile_time: null });
    await waitFor(() => expect(screen.getByText(/date unknown/)).toBeTruthy());
    expect(screen.queryByText(/00:00/)).toBeNull();
  });

  it("a real-time (R) profile draws nothing as good: no chart, the mode is named, and it is flagged not drawn", async () => {
    open({ ...payload, doxy_mode: "R", drawable: false, at_depth: { "500": null } });
    await waitFor(() => expect(screen.getByTestId("argo-no-good")).toBeTruthy());
    expect(screen.queryByTestId("argo-profile-chart")).toBeNull();
    expect(screen.getAllByText(/real time, raw only/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/This profile is not drawn on the map/)).toBeTruthy();
  });

  it("older payloads without `citations` fall back to the combined citation", async () => {
    const { citations: _omit, ...old } = payload as any;
    open({ ...old, citation: "COMBINED CREDIT International Argo Program" });
    await waitFor(() => expect(screen.getByText(/COMBINED CREDIT/)).toBeTruthy());
  });

  it("404 says the profile no longer exists; another failure offers a retry that asks again", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(respond({}, 404));
    render(<ArgoOxygenProfilePanel id="aoml_1900722_009" />);
    await waitFor(() => expect(screen.getByText(/no longer exists/i)).toBeTruthy());
    expect(screen.queryByRole("button", { name: /retry/i })).toBeNull();          // missing is not broken
    cleanup();
    const spy = vi.spyOn(globalThis, "fetch");
    spy.mockResolvedValueOnce(respond({}, 503));
    render(<ArgoOxygenProfilePanel id="aoml_1900722_010" />);
    await waitFor(() => expect(screen.getByRole("button", { name: /retry/i })).toBeTruthy());
    expect(screen.queryByText(/no longer exists/i)).toBeNull();                   // broken is not missing
    spy.mockResolvedValueOnce(respond(payload));
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    await waitFor(() => expect(screen.getAllByText(/1900722/).length).toBeGreaterThan(0));
    expect(String(spy.mock.calls[spy.mock.calls.length - 1][0])).toContain("/api/v1/argo-oxygen/profile/aoml_1900722_010");
  });
});

describe("the 'not charted' counts agree in number, in every locale", () => {
  // k adjusted levels flagged QC 3 and k raw-only levels, plus one good level: stored levels = 2k + 1
  const withK = (k: number) => ({
    ...payload, n_levels: 2 * k + 1,
    levels: {
      pres_dbar: Array.from({ length: 2 * k + 1 }, (_, i) => 10 + i), depth_m: Array.from({ length: 2 * k + 1 }, (_, i) => 10 + i),
      doxy_adj: [250, ...Array(k).fill(240), ...Array(k).fill(null)], doxy_adj_qc: [1, ...Array(k).fill(3), ...Array(k).fill(null)],
      doxy_raw: Array(2 * k + 1).fill(230), doxy_raw_qc: Array(2 * k + 1).fill(3),
    },
  });
  beforeEach(() => {
    useMapStore.setState({ oxygenDepth: 0, oxygenView: "recent" } as any);
    for (const [lng, b] of Object.entries({ pl, de, fr })) i18n.addResourceBundle(lng, "panels", b, true, true);
  });
  afterEach(async () => { cleanup(); await i18n.changeLanguage("en"); vi.restoreAllMocks(); });
  const show = async (lng: string, k: number) => {
    // locale files are requested over HTTP when the language changes: answer them empty, the profile with the payload
    vi.spyOn(globalThis, "fetch").mockImplementation((url) =>
      Promise.resolve(String(url).includes("/locales/") ? respond({}) : respond(withK(k))));
    await i18n.changeLanguage(lng);
    render(<ArgoOxygenProfilePanel id="aoml_1900722_001" />);
    await waitFor(() => expect(screen.getByTestId("argo-profile-chart")).toBeTruthy());
    return document.body.textContent ?? "";
  };

  it.each([
    ["en", 1, "1 adjusted value flagged", "1 raw-only value among the stored levels (3)"],
    ["en", 2, "2 adjusted values flagged", "2 raw-only values among the stored levels (5)"],
    ["pl", 1, "1 wartość skorygowana oznaczona", "1 wartość tylko surowa wśród zapisanych poziomów (3)"],
    ["pl", 2, "2 wartości skorygowane oznaczone", "2 wartości tylko surowe wśród zapisanych poziomów (5)"],
    ["pl", 5, "5 wartości skorygowanych oznaczonych", "5 wartości tylko surowych wśród zapisanych poziomów (11)"],
    ["de", 1, "1 korrigierter Wert als fraglich", "1 reiner Rohwert unter den gespeicherten Stufen (3)"],
    ["de", 2, "2 korrigierte Werte als fraglich", "2 reine Rohwerte unter den gespeicherten Stufen (5)"],
    ["fr", 1, "1 valeur ajustée marquée douteuse", "1 valeur brute seulement parmi les niveaux stockés (3)"],
    ["fr", 2, "2 valeurs ajustées marquées douteuses", "2 valeurs brutes seulement parmi les niveaux stockés (5)"],
  ])("%s, k=%i", async (lng, k, flagged, raw) => {
    const text = await show(lng, k);
    expect(text).toContain(flagged);
    expect(text).toContain(raw);
    expect(text).not.toContain("argoProfile.");
  });
});
