// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// 2026-09-18 production incident: Googlebot crawling seamount pages got 504s on
// GET /api/api/v1/seo/seamount/<id> — a doubled "/api" prefix. Root cause:
// frontend/Dockerfile used to bake `ENV VITE_API_BASE_URL=/api` at build time,
// while every call site (SeoPage.tsx included) ALSO hardcodes a literal "/api"
// in the fetch URL (`${API}/api/v1/...`). Both layers of the BFF proxy happen
// to strip a leading /api twice (Express's own mount-prefix strip, then
// http-proxy-middleware's pathRewrite matching again on what Express left
// behind), so the request still quietly reached the right backend route — which
// is exactly why the defect went unnoticed until it showed up as a literal URL
// crawled by Googlebot and, under a slow backend, an extra proxy hop that timed
// out as its own 504.
//
// The fix is in frontend/Dockerfile (VITE_API_BASE_URL is no longer set, so it
// resolves to "" — the same as the local dev default). This test guards the
// OTHER half: that with that corrected (unset) env, the actual rendered
// seamount/vent/concession pages issue a request to plain /api/v1/... and never
// to /api/api/v1/....
//
// ⚠️ This test cannot see a Dockerfile regression by itself — see
// dockerfile-api-base-url.test.ts, which reads the Dockerfile directly. Losing
// either one re-opens half the defect.

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, cleanup, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { HelmetProvider } from "react-helmet-async";

import { SeoPage } from "../components/SeoPage";
import { VentReport } from "../components/VentReport";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function mockFetchOk(body: Record<string, unknown>) {
  return vi.fn().mockResolvedValue({
    ok: true,
    json: async () => body,
  });
}

describe("no doubled /api/api/ prefix in rendered pages", () => {
  it.each([
    ["seamount", "42"],
    ["vent", "vent-1"],
    ["concession", "isa-1"],
  ] as const)("SeoPage type=%s fetches /api/v1/seo/%s/<id>, never /api/api/", async (type, id) => {
    const fetchMock = mockFetchOk({ meta: { title: "t", description: "d", canonical_url: "/x", json_ld: {} } });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <HelmetProvider>
        <MemoryRouter initialEntries={[`/${type}/${id}`]}>
          <Routes>
            <Route path={`/${type}/:id`} element={<SeoPage type={type} />} />
          </Routes>
        </MemoryRouter>
      </HelmetProvider>,
    );

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const calledUrl = fetchMock.mock.calls[0][0] as string;
    expect(calledUrl).toBe(`/api/v1/seo/${type}/${id}`);
    expect(calledUrl).not.toContain("/api/api/");
  });

  it("VentReport fetches /api/v1/seo/vent-report/<id>, never /api/api/", async () => {
    const fetchMock = mockFetchOk({
      name: "Snake Pit", status: "Active", depth_m: 2500, min_depth_m: null,
      max_temp_c: null, temp_category: null, ocean: null, region: null,
      jurisdiction: null, tectonic_setting: null, discovery_year: null,
      biology_notes: null, latitude: 1, longitude: 2, source_url: null,
      chess_count: 0, chess_species: [], nearby_claims: [],
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter initialEntries={["/vent-report/vent-1"]}>
        <Routes>
          <Route path="/vent-report/:ventId" element={<VentReport />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const calledUrl = fetchMock.mock.calls[0][0] as string;
    expect(calledUrl).toBe("/api/v1/seo/vent-report/vent-1");
    expect(calledUrl).not.toContain("/api/api/");
  });
});
