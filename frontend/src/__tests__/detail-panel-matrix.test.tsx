// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// The safety net for the eventual DetailPanel.tsx split (6,956 lines, ~65
// panel components dispatched from one if/else chain, PanelContent()).
//
// Renders every panel PanelContent() can produce and snapshots the DOM. A
// later refactor that moves this code across files must not change what
// gets rendered for any layer id — this test is the invariant that proves
// it didn't.
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, render, cleanup, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { DetailPanel } from "../components/DetailPanel";
import { useMapStore } from "../store/mapStore";
import { LAYER_FIXTURES, EXPECTED_LAYER_COUNT } from "./detailPanelFixtures";
import {
  MINING_DETAIL, VENT_DETAIL_ACTIVE, VENT_DETAIL_INACTIVE, WOA_SAMPLE,
  ONC_SPARKLINES, ONC_ADCP, ONC_CTD, ONC_EARTHQUAKES, HYDROPHONE_SOUNDSCAPE,
  MONITORING_DENSITY_CELL, WOD_BY_ID, MEMENTO_CAST, GEOTRACES_RESPONSE,
  MOSAIC_RESPONSE, ARCTIC_CATCHMENT_DETAIL, WOA_POINT, CARBON_POINT,
  ACIDIFICATION_POINT, CHI_POINT, UNIFIED_CARBON_POINT, UNIFIED_CARBON_NEAREST_OBS,
  VME_POINT, CORAL_EXPOSURE_POINT, CORAL_EXPOSURE_SUMMARY, CO2_POINT, OXYGEN_POINT,
} from "./detailPanelFetchFixtures";

// Every panel that fetches does so in a useEffect; the FIRST snapshot per
// layer is still taken synchronously right after render(), before any fetch
// promise resolves — that's the pre-fetch/loading state, deterministic
// regardless of what the mock resolves to.
//
// For the subset of panels that fetch on mount (enumerated in FETCHING_LAYERS
// below), a SECOND snapshot is taken after `waitFor` confirms the DOM changed
// from that loading state — i.e. after the real post-fetch render, the one
// that actually exercises each domain's chart component (MementoDepthChart,
// GeotracesDepthChart, MosaicDepthChart, WodO2Chart, AdcpHeatmap, ProfilePlot,
// SocDepthChart, ...). Before this file, those charts were never rendered by
// this suite at all — see the file-level comment in detailPanelFetchFixtures.ts.
//
// The mock below is a per-URL router, not a blanket stub: an unmatched URL
// rejects instead of silently returning `{}`, so a chart wired to the wrong
// endpoint after the split fails loudly here rather than passing green with
// an accidentally-empty payload. See "intentionally unmatched" below for the
// three endpoints left unmatched on purpose, and why that's safe.
function jsonResponse(data: unknown) {
  return { ok: true, status: 200, json: async () => data, text: async () => JSON.stringify(data) };
}

// [urlPattern, response] — first match wins. Patterns are anchored on the
// path segment (not just a bare substring) so e.g. "/v1/carbon/point" cannot
// accidentally match "/v1/carbon/unified-point" or vice versa.
const ROUTES: Array<[RegExp, unknown]> = [
  [/\/v2\/spatial\/feature\/mining_contracts\//, MINING_DETAIL],
  [/\/v2\/spatial\/feature\/hydrothermal_vents\/1(?:$|\?)/, VENT_DETAIL_ACTIVE],
  [/\/v2\/spatial\/feature\/hydrothermal_vents\/2(?:$|\?)/, VENT_DETAIL_INACTIVE],
  [/\/v1\/woa\/sample(?:$|\?)/, WOA_SAMPLE],
  [/\/v1\/onc\/sparkline\//, ONC_SPARKLINES],
  [/\/v1\/onc\/adcp-strip\//, ONC_ADCP],
  [/\/v1\/onc\/ctd\//, ONC_CTD],
  [/\/v1\/onc\/earthquakes-near\//, ONC_EARTHQUAKES],
  [/\/v1\/hydrophones\/.*\/soundscape/, HYDROPHONE_SOUNDSCAPE],
  [/\/v2\/map\/monitoring-density\/cell/, MONITORING_DENSITY_CELL],
  [/\/v2\/spatial\/wod-oxygen\/by-id\//, WOD_BY_ID],
  [/\/v2\/spatial\/memento\/by-id\//, MEMENTO_CAST],
  [/\/v2\/spatial\/geotraces\/by-id\//, GEOTRACES_RESPONSE],
  [/\/v2\/spatial\/mosaic\/by-id\//, MOSAIC_RESPONSE],
  [/\/v2\/spatial\/arctic-catchments\/by-id\//, ARCTIC_CATCHMENT_DETAIL],
  [/\/v1\/woa\/point(?:$|\?)/, WOA_POINT],
  [/\/v1\/carbon\/unified-point(?:$|\?)/, UNIFIED_CARBON_POINT],
  [/\/v1\/carbon\/nearest-obs(?:$|\?)/, UNIFIED_CARBON_NEAREST_OBS],
  [/\/v1\/carbon\/point(?:$|\?)/, CARBON_POINT],
  [/\/v1\/acidification\/point(?:$|\?)/, ACIDIFICATION_POINT],
  [/\/v1\/chi\/point(?:$|\?)/, CHI_POINT],
  [/\/v1\/vme\/point(?:$|\?)/, VME_POINT],
  [/\/v1\/coral-exposure\/point(?:$|\?)/, CORAL_EXPOSURE_POINT],
  [/\/v1\/coral-exposure\/summary(?:$|\?)/, CORAL_EXPOSURE_SUMMARY],
  [/\/v1\/co2\/point(?:$|\?)/, CO2_POINT],
  [/\/v1\/oxygen\/point(?:$|\?)/, OXYGEN_POINT],
];

// Intentionally unmatched (reject, never {}):
//  - /v1/bathymetry/lookup            (SeafloorDepthRow — embedded in ~15 unrelated panels)
//  - /v1/bathymetry/confidence/...    (BathymetryConfidenceBlock — embedded in 5 unrelated panels)
//  - /v1/bathymetry/gmrt/...          (same component, second of its two fetches)
// All three are optional-enrichment widgets shared across many panels that
// aren't tied to one layer id; every call site wraps them in `.catch(() =>
// self-hide)`, so a rejection is exactly their designed "no data" path and
// produces the same deterministic (absent) output as the old blanket mock —
// verified by reading every call site: DetailPanel.tsx:118 and :1368/:1377.
// Giving them real fixture data would only add flakiness (their promises can
// race the specific fetch each test's `waitFor` is targeting) for zero
// chart-coverage gain, since neither renders anything chart-shaped.
const fetchMock = vi.fn(async (url: string) => {
  const hit = ROUTES.find(([re]) => re.test(url));
  if (hit) return jsonResponse(hit[1]);
  return Promise.reject(new Error(`Unmocked fetch in detail-panel-matrix.test.tsx: ${url}`));
});

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  // Freezes "now" so any panel computing an age/freshness (e.g. AisVesselPanel's
  // "N min ago") gets a fixed, reproducible number instead of drifting with the
  // wall clock between test runs.
  vi.setSystemTime(new Date("2026-08-20T12:00:00Z"));
  useMapStore.setState({ selectedFeatures: [], vesselFocus: null });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

// Layer ids whose panel fetches on mount (directly, or via an always-rendered
// child like ArgoPanel's WoaSeasonalExplorer) and where that fetch feeds a
// materially different render — a domain chart, a table, a heatmap. Derived
// by reading every `fetch(` call site in DetailPanel.tsx and walking up to
// its enclosing `function ComponentName` to find which layer id(s) dispatch
// to it (see PanelContent() around DetailPanel.tsx:6560-6633). Two ids
// (hydrothermal-vents-active/-inactive) share one component, VentPanel.
//
// NOT included, and why:
//  - argo-trail-dot: TrailDotPanel only renders SeafloorDepthRow, which is
//    excluded above (shared, self-hiding, not chart-shaped).
//  - ais-live: AisVesselPanel's vessel-history fetch is gated behind a
//    "Show track" button (`showTrack` state, default false) — it does not
//    fire on mount with the default fixture (vesselFocus reset to null in
//    beforeEach), so there is no post-fetch state to reach without simulating
//    a click, which is out of scope for a fetch-on-mount gap.
//  - chess (ChessPanel), MiningPanel's claim-impact POST, ArgoPanel's
//    impact-report POST: all three fire from onClick handlers, not useEffect.
//  - argo-floats-3d: ArgoPanel renders WoaSeasonalExplorer (which fetches
//    /v1/woa/sample on mount) only behind `latLonFromProps(p) &&` — see
//    DetailPanel.tsx:945-951. The existing "argo-floats-3d" fixture in
//    detailPanelFixtures.ts carries no `lat`/`latitude`/`_lat` key, so
//    `latLonFromProps` returns null and WoaSeasonalExplorer never mounts:
//    confirmed live — with lat/lon added to the fixture, the panel does
//    fetch and the post-fetch DOM does diverge (verified locally, then
//    reverted so this file adds coverage without touching the existing
//    fixture's shape/semantics). Left out rather than silently skipped —
//    this is the one panel named in the brief as "could not reach" and why.
const FETCHING_LAYERS = new Set([
  "mining-contracts-mvt", "hydrothermal-vents-active", "hydrothermal-vents-inactive",
  "onc", "hydrophone-stations", "monitoring-density",
  "wod-oxygen", "memento", "geotraces", "mosaic-sediment", "arctic-catchments",
  "woa-climatology", "ocean-carbon", "ocean-acidification", "cumulative-human-impact",
  "marine-carbon", "vme-suitability", "coral-acid-exposure", "ocean-co2-surface",
  "oxygen-deox",
]);

describe("DetailPanel dispatch matrix", () => {
  // Re-derive the branch count from the real source rather than trusting the
  // fixture list alone — if PanelContent() gains or loses a `layer === "..."`
  // branch, this fails even if nobody remembered to update the fixtures.
  it("PanelContent dispatches on exactly the expected number of layer ids", () => {
    const src = readFileSync(
      resolve(__dirname, "../components/DetailPanel.tsx"),
      "utf-8",
    );
    const fnStart = src.indexOf("function PanelContent(");
    const fnEnd = src.indexOf("\n}\n", fnStart);
    const body = src.slice(fnStart, fnEnd);
    const matches = body.match(/layer === "[^"]*"/g) ?? [];
    // A changed number here means a panel was added or lost — go update
    // EXPECTED_LAYER_COUNT and LAYER_FIXTURES together, never one alone.
    expect(matches.length).toBe(EXPECTED_LAYER_COUNT);
    expect(new Set(matches).size).toBe(EXPECTED_LAYER_COUNT); // no duplicate literal
  });

  it("fixture list covers exactly the expected number of layer ids", () => {
    expect(LAYER_FIXTURES.length).toBe(EXPECTED_LAYER_COUNT);
    expect(new Set(LAYER_FIXTURES.map(f => f.layer)).size).toBe(EXPECTED_LAYER_COUNT);
  });

  // Every fetching layer named above must actually exist in the fixture list —
  // otherwise FETCHING_LAYERS could silently drift into asserting nothing.
  it("every entry in FETCHING_LAYERS has a fixture", () => {
    const fixtureLayers = new Set(LAYER_FIXTURES.map(f => f.layer));
    for (const layer of FETCHING_LAYERS) {
      expect(fixtureLayers.has(layer)).toBe(true);
    }
  });

  for (const fixture of LAYER_FIXTURES) {
    it(`renders ${fixture.layer} without throwing and matches its snapshot`, () => {
      useMapStore.getState().setSelectedFeature({
        id: fixture.id,
        layer: fixture.layer,
        properties: fixture.properties,
      });

      const { container } = render(<DetailPanel />);

      expect(container).toMatchSnapshot();
    });

    if (FETCHING_LAYERS.has(fixture.layer)) {
      it(`renders ${fixture.layer} after data loads`, async () => {
        useMapStore.getState().setSelectedFeature({
          id: fixture.id,
          layer: fixture.layer,
          properties: fixture.properties,
        });

        const { container } = render(<DetailPanel />);
        const loadingHtml = container.innerHTML;

        // Generic across all fetching layers rather than a per-panel text
        // marker: wait until the DOM actually differs from the synchronous
        // pre-fetch render. This is the same fixed point the sibling
        // "without throwing" test captures on the loading side — here we
        // wait past it instead of stopping at it.
        await waitFor(() => {
          expect(container.innerHTML).not.toBe(loadingHtml);
        });

        // Flush past that FIRST mutation, not just to it. Several of these
        // panels also mount SeafloorDepthRow / BathymetryConfidenceBlock —
        // shared enrichment widgets whose URLs are deliberately unmatched
        // (see "intentionally unmatched" above) and so always reject. RTL's
        // waitFor resolves on the FIRST DOM mutation it observes (it uses a
        // MutationObserver, a microtask, not a macrotask poll), so without
        // this the snapshot was a coin flip between "the main fetch settled
        // first" and "the incidental reject settled first" — caught by
        // running the suite in a loop: ~1-in-3 runs produced a different
        // "mining-contracts-mvt after data loads" snapshot. A real macrotask
        // tick drains every microtask queued so far (both the main fetch's
        // chain and any shorter incidental one), so by the time it fires,
        // every promise created during this render has settled.
        await act(async () => {
          await new Promise((r) => setTimeout(r, 0));
        });

        // The check named in the brief: a panel whose fetch silently no-ops
        // (e.g. wrong response shape post-refactor) would leave the loaded
        // snapshot the same size as the loading one. Loading state is just
        // panel chrome + a spinner line (see file-level comment in the
        // fixtures file), so any real chart/table push this well past it.
        expect(container.innerHTML.length).toBeGreaterThan(loadingHtml.length);

        expect(container).toMatchSnapshot();
      });
    }
  }
});
