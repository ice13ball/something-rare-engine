// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
import { afterEach, describe, expect, it, vi } from "vitest";
import { clickIdFor, fetchOpenTarget, openObjectsFor } from "../components/map3d/openFromLink";
import { PLANKTON_SITE } from "./detailPanelFetchFixtures";

afterEach(() => vi.unstubAllGlobals());

describe("a plankton place in a share link", () => {
  it("is written as its site_key, never the pick index", () => {
    expect(clickIdFor("plankton-occurrences", { site_key: "10.200000,50.200000", n: 6 }, 17)).toBe("10.200000,50.200000");
    expect(openObjectsFor([{ id: "10.200000,50.200000", layer: "plankton-occurrences" }]))
      .toEqual([["plankton-occurrences", "10.200000,50.200000"]]);
  });

  it("is read back through /api/v1/plankton/site/ and lands on the place's own coordinates", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      urls.push(url);
      return { ok: true, status: 200, json: async () => PLANKTON_SITE } as unknown as Response;
    }));
    const target = await fetchOpenTarget("plankton-occurrences", "10.200000,50.200000", "");
    expect(urls).toEqual(["/api/v1/plankton/site/10.200000%2C50.200000"]);
    expect(target?.routingKey).toBe("plankton-occurrences");
    expect(target?.id).toBe("10.200000,50.200000");
    expect(target?.feature.geometry).toEqual({ type: "Point", coordinates: [10.2, 50.2] });
  });

  it("is keyed on site_key only: a re-imported place with another site_id gives the same link", () => {
    const before = { site_key: "10.200000,50.200000", site_id: 111, n: 6 };
    const after = { site_key: "10.200000,50.200000", site_id: 999, n: 6 };
    expect(clickIdFor("plankton-occurrences", before, 3)).toBe(clickIdFor("plankton-occurrences", after, 40));
  });

  it("ignores a malformed site_key without calling the network", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    for (const bad of ["", "abc", "10.2,50.2", "10.200000;50.200000", "../../etc", "10.200000,50.200000/x", "10.200000,50.200000\n"]) {
      expect(await fetchOpenTarget("plankton-occurrences", bad, "")).toBeNull();
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
