// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
/**
 * Global search finds a GLODAPv3 cruise by EXPOCODE or ship name, and selecting it opens a STABLE target:
 * the cruise's first cast (`cast_key`), never a pick index. Renders the real SearchBar with the
 * `/v1/glodap/cruises` document shape (backend/domains/glodap_points.py) in its data ref.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { FeatureCollection } from "geojson";

import { SearchBar } from "../components/SearchBar";
import { useMapStore } from "../store/mapStore";

const cruise = (expocode: string, ship: string | null, first: string, last: string, cast: string, lon: number, lat: number) => ({
  type: "Feature" as const,
  geometry: { type: "Point" as const, coordinates: [lon, lat] },
  properties: { expocode, ship_name: ship, platform_code: null, doi: null, first_date: first, last_date: last, n_casts: 10, first_cast_key: cast },
});
const CRUISES: FeatureCollection = {
  type: "FeatureCollection",
  features: [
    cruise("49UF20150620", "Keifu Maru", "2015-06-20", "2015-07-30", "49UF20150620_4511_1", 145.5, 35.1),
    cruise("33RO20130803", null, "2013-08-03", "2013-08-03", "33RO20130803_1_1", -20.25, 10.5),
  ],
};

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve([]) })) as unknown as typeof fetch);
  useMapStore.setState({ activeLayers: new Set(["glodap-points", "ocean-carbon"]) as never, enabledLayerIds: null });
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); useMapStore.setState({ flyTo: null, selectedFeatures: [] } as never); });

const type = (q: string) => {
  render(<SearchBar dataRef={{ current: { glodapCruises: CRUISES } }} dataVersion={1} />);
  fireEvent.change(screen.getByRole("textbox"), { target: { value: q } });
  act(() => { vi.advanceTimersByTime(250); });
};

describe("GLODAPv3 cruise search", () => {
  it("finds a cruise by ship name and shows expocode and years", () => {
    type("keifu");
    expect(screen.getByText("GLODAPv3 cruises")).toBeInTheDocument();
    expect(screen.getByText("Keifu Maru")).toBeInTheDocument();
    expect(screen.getByText("49UF20150620 · 2015")).toBeInTheDocument();
  });

  it("finds a cruise by expocode, falling back to the expocode when no ship name is known", () => {
    type("33ro2013");
    expect(screen.getByText("33RO20130803")).toBeInTheDocument();
    expect(screen.queryByText("Keifu Maru")).toBeNull();
  });

  it("selecting a result opens the first cast by its stable key, switching the Ocean Carbon field on with it", () => {
    useMapStore.setState({ activeLayers: new Set(["glodap-points"]) as never });
    const flyTo = vi.fn();
    useMapStore.setState({ flyTo } as never);
    type("keifu");
    fireEvent.click(screen.getByText("Keifu Maru"));
    expect(flyTo).toHaveBeenCalledWith(145.5, 35.1);
    expect(useMapStore.getState().activeLayers.has("ocean-carbon" as never)).toBe(true);
    act(() => { vi.advanceTimersByTime(900); });
    const sel = useMapStore.getState().selectedFeatures[0];
    expect(sel?.id).toBe("49UF20150620_4511_1");
    expect(sel?.layer).toBe("glodap-points");
  });
});
