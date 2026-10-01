// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";

import { CoastdomPanel } from "../components/panels/ocean/CoastdomPanel";
import { GreenlandPrimaryProductionPanel } from "../components/panels/ocean/GreenlandPrimaryProductionPanel";

// Served fields of CoastDOM slice row 1 (source data row 0, Minjiang estuary M02),
// as /v1/map/coastdom/samples returns them.
const ROW_1 = {
  version_id: 1, row_no: 1, location: "Minjiang estuary", sample_id: "M02", sample_date: "2017-04-15",
  lat: 26.145, lon: 119.109, elevation_m: null, depth_m: 0.0, temp_c: 19.4, sal: 0.1, tss_mg_l: 4.3,
  chl_a_ug_l: null, qf_chl_a: null, no3_no2_umol_l: null, qf_no3_no2: null, nh4_umol_l: null, qf_nh4: null,
  hpo4_umol_l: null, qf_hpo4: null, doc_umol_l: 118.0, doc_method: "High temperature combustion", qf_doc: 2,
  don_umol_l: null, tdn_umol_l: null, tdn_method: null, qf_tdn: null, dop_umol_l: null, tdp_umol_l: null,
  tdp_method: null, qf_tdp: null, poc_umol_l: 9.0, poc_method: "High temperature combustion", qf_poc: 2,
  pn_umol_l: 0.5, pn_method: "High temperature combustion", qf_tpn: 2, pp_umol_l: null, pp_method: null,
  qf_pp: null, dic_umol_kg: null, qf_dic: null, at_umol_kg: null, qf_at: null, pi: "Liyang Yang",
  institution: "Fuzhou University, Fuzhou, China", ref_1: "doi:10.1007/s11356-019-05700-2",
  ref_2: "doi:10.1016/j.jmarsys.2019.103264", ref_3: null, comment: null,
};
// ⛔ Synthetic: no real undated row has coordinates, so this is ROW_1 with its date
// removed — the only way to show the undated path in a located panel.
const UNDATED = { ...ROW_1, row_no: 99, sample_id: "M02-undated", sample_date: null };

const META = { versions: [
  { version_id: 1, layer_id: "coastdom", is_current: true, doi: "10.1594/PANGAEA.964012",
    date_published: "2023-12-12", sha256: "76f550dd55f8c6760b465095efc6f2de7db0b1b50b077613580ba3de04fe129e",
    rows_in_source: 70823, rows_unmappable: 532, data_points: 1286555,
    citation: "Lønborg, Christian; et al. (2023): CoastDOM v.1 [dataset]. PANGAEA, https://doi.org/10.1594/PANGAEA.964012",
    related_citation: null, license: "https://creativecommons.org/licenses/by/4.0/", ingested_at: "2026-09-25T00:00:00Z",
    units: { doc_umol_l: "DOC [µmol/l]", qf_doc: "QF DOC", depth_m: "Depth water [m]" } },
  { version_id: 2, layer_id: "greenland-primary-production", is_current: true, doi: "10.1594/PANGAEA.965985",
    date_published: "2025-04-07", sha256: "0ae42f5e8967b0caa3fbf1b745c9217a17e3590f84f0d715c3a88c9376cebad9",
    rows_in_source: 12, rows_unmappable: 0, data_points: 12, citation: "Cherkasheva et al. (2025) [dataset]. PANGAEA",
    related_citation: null, license: "https://creativecommons.org/licenses/by/4.0/", ingested_at: "2026-09-25T00:00:00Z",
    units: { gpp_c_mg_m2_day: "GPP C [mg/m**2/day]" } },
] };

function ok(body: unknown) {
  return Promise.resolve({ ok: true, json: async () => body } as Response);
}

beforeEach(() => vi.setSystemTime(new Date("2026-09-25T12:00:00Z")));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); });

describe("CoastdomPanel", () => {
  it("lists every sample, says 'no date in source' for an undated one, and prints the source's units", async () => {
    vi.stubGlobal("fetch", vi.fn((url: string) =>
      url.includes("/api/v1/map/coastdom/samples")
        ? ok({ lat: 26.145, lon: 119.109, n_samples: 2, samples: [ROW_1, UNDATED] })
        : ok(META)));
    const { container } = render(<CoastdomPanel properties={{ site_id: "26.145,119.109", lat: 26.145, lon: 119.109, location: "Minjiang estuary", n_samples: 2 }} />);
    expect(await screen.findByText(/no date in source/)).toBeTruthy();
    await waitFor(() => expect(container.textContent).toContain("DOC [µmol/l]"));
    const text = container.textContent ?? "";
    expect(text).toContain("2017-04-15");
    expect(text).toContain("QF DOC 2");
    expect(text).not.toContain("2026-09-25");            // never the sync/today date
    expect(text).toContain("10.1594/PANGAEA.964012");
  });

  it("asks for the clicked position through the BFF proxy", async () => {
    const fetchMock = vi.fn((url: string) => url.includes("samples")
      ? ok({ lat: 26.145, lon: 119.109, n_samples: 1, samples: [ROW_1] }) : ok(META));
    vi.stubGlobal("fetch", fetchMock);
    render(<CoastdomPanel properties={{ lat: 26.145, lon: 119.109, location: "Minjiang estuary", n_samples: 1 }} />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const urls = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(urls.some((u) => u.includes("/api/v1/map/coastdom/samples?lat=26.145&lon=119.109"))).toBe(true);
    for (const u of urls) expect(u).toContain("/api/v1/");   // BFF proxy, never a bare /v1/
  });

  it("renders the singular English header for exactly one sample", async () => {
    vi.stubGlobal("fetch", vi.fn((url: string) =>
      url.includes("/api/v1/map/coastdom/samples")
        ? ok({ lat: 26.145, lon: 119.109, n_samples: 1, samples: [ROW_1] })
        : ok(META)));
    render(<CoastdomPanel properties={{ lat: 26.145, lon: 119.109, location: "Minjiang estuary", n_samples: 1 }} />);
    expect(await screen.findByText("1 sample at this position")).toBeTruthy();
  });

  it("shows a failure line when the samples cannot be loaded", async () => {
    vi.stubGlobal("fetch", vi.fn((url: string) => url.includes("samples")
      ? Promise.reject(new Error("network down")) : ok(META)));
    render(<CoastdomPanel properties={{ lat: 26.145, lon: 119.109, location: "Minjiang estuary", n_samples: 1 }} />);
    expect(await screen.findByText(/could not be loaded/)).toBeTruthy();
  });
});

describe("GreenlandPrimaryProductionPanel", () => {
  it("labels GPP with the source unit as an areal rate, never as a concentration", async () => {
    vi.stubGlobal("fetch", vi.fn(() => ok(META)));
    const { container } = render(<GreenlandPrimaryProductionPanel properties={{
      version_id: 2, row_no: 1, event: "FS21_06E", event_2: null, lat: 78.833, lon: 6.0,
      sample_date: "2021-08-02", gpp_c_mg_m2_day: 2234.38 }} />);
    await waitFor(() => expect(container.textContent).toContain("10.1594/PANGAEA.965985"));
    const text = container.textContent ?? "";
    expect(text).toContain("GPP C [mg/m**2/day]");
    expect(text).toContain("2234.38");
    expect(text).toMatch(/areal rate/i);
    expect(text).not.toMatch(/concentration/i);
    expect(text).toContain("2021-08-02");
  });
});
