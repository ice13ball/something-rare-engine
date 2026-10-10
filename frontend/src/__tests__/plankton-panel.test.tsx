// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { PlanktonPanel } from "../components/panels/ocean/PlanktonPanel";
import { useMapStore } from "../store/mapStore";
import { PLANKTON_SITE } from "./detailPanelFetchFixtures";

const K = "10.200000,50.200000";
let calls: string[] = [];

const PLANKTON_API = "/api/v1/plankton/";

function serve(status: number, body: unknown = PLANKTON_SITE) {
  calls = [];
  const passThrough = globalThis.fetch;
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    // ⛔ Only the plankton calls are recorded and answered: i18next lazily loads /locales/... through the same
    // global fetch at unpredictable moments, and recording those made this file flaky (2 of 4 full runs).
    if (!String(url).includes(PLANKTON_API)) return passThrough(url, init);
    calls.push(String(url));
    return { ok: status >= 200 && status < 300, status, json: async () => body } as unknown as Response;
  }));
}

beforeEach(() => useMapStore.getState().resetAllFilters());
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("PlanktonPanel", () => {
  it("asks the BFF for the place with the active map filters", async () => {
    serve(200);
    useMapStore.setState({ planktonGroupFilters: new Set(["copepoda"]), planktonDecadeFilters: new Set(["2010"]) });
    render(<PlanktonPanel siteKey={K} />);
    await screen.findByTestId("plankton-panel");
    expect(calls).toEqual(["/api/v1/plankton/site/10.200000%2C50.200000?g=copepoda&d=2010"]);
  });

  it("does not record fetches that are not plankton calls (i18next background loads)", async () => {
    serve(200);
    render(<PlanktonPanel siteKey={K} />);
    await screen.findByTestId("plankton-panel");
    await fetch("/locales/en/legend.json").catch(() => undefined);
    expect(calls).toHaveLength(1);
    expect(calls.every(c => c.includes(PLANKTON_API))).toBe(true);
  });

  it("refetches when a filter changes while the panel is open", async () => {
    serve(200);
    render(<PlanktonPanel siteKey={K} />);
    await screen.findByTestId("plankton-panel");
    act(() => useMapStore.getState().togglePlanktonGroupFilter("diatoms"));
    await waitFor(() => expect(calls.length).toBe(2));
    expect(calls[1]).toContain("g=copepoda,euphausiacea,coccolithophores,dinoflagellates");
  });

  it("shows the place's own coordinates, its species, the NC note and the OBIS links", async () => {
    serve(200);
    render(<PlanktonPanel siteKey={K} />);
    await screen.findByTestId("plankton-panel");
    expect(screen.getByText("50.2000, 10.2000")).toBeTruthy();
    expect(screen.getByText(/Calanus finmarchicus/)).toBeTruthy();
    expect(screen.getByText(/non-commercial use only/)).toBeTruthy();
    expect(screen.getByText(/CC-BY-NC, 2/)).toBeTruthy();
    const link = screen.getByRole("link", { name: "Synthetic CC-BY-NC dataset" });
    expect(link.getAttribute("href")).toBe("https://obis.org/dataset/00000000-0000-0000-0000-0000000000ab");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
  });

  it("renders dataset titles and citations as text, and never links a non-OBIS url", async () => {
    serve(200, { ...PLANKTON_SITE, datasets: [{
      ...PLANKTON_SITE.datasets[0], title: "<img src=x onerror=alert(1)>", citation: "<b>bold</b>",
      obis_url: "javascript:alert(1)",
    }] });
    const { container } = render(<PlanktonPanel siteKey={K} />);
    await screen.findByTestId("plankton-panel");
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
    expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeTruthy();
    expect(screen.queryByRole("link", { name: /onerror/ })).toBeNull();
  });

  it("says so when nothing at the place matches the filters", async () => {
    serve(200, { ...PLANKTON_SITE, total: 0, groups: [], top_species: [], licences: [], datasets: [], datasets_total: 0 });
    render(<PlanktonPanel siteKey={K} />);
    expect(await screen.findByText("No observation at this place matches the active filters.")).toBeTruthy();
  });

  it("a 404 is 'not in this import'; anything else is 'unavailable' with a working retry", async () => {
    serve(404);
    render(<PlanktonPanel siteKey={K} />);
    expect(await screen.findByText(/not in the current plankton import/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
    cleanup();
    serve(503);
    render(<PlanktonPanel siteKey={K} />);
    fireEvent.click(await screen.findByRole("button", { name: "Try again" }));
    await waitFor(() => expect(calls.length).toBe(2));
  });
});
