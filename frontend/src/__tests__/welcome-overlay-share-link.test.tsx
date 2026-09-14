// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// Reproduced on production 2026-09-14: a link carrying 20 layers opened with
// all 20 active AND the mode picker on top of them. The picker offers no way to
// say "keep what the link gave me" — every profile button calls
// `setActiveLayers(new Set(...))`, which REPLACES. Picking one dropped the
// sender's 20 to the profile's 10, and because the address bar is live, the
// replacement was re-encoded into `?s=` on the spot: the recipient no longer
// even held the link they were sent.
//
// ⛔ These must fail if the overlay stops consulting the link. A unit test of
// `linkCarriesView` alone cannot see a deleted call site.
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { WelcomeOverlay } from "../components/WelcomeOverlay";
import { linkCarriesView } from "../components/map3d/shareBootstrap";
import { encodeShareState } from "../utils/shareState";
import { useMapStore } from "../store/mapStore";

const CAMERA = { longitude: 12.5, latitude: -3.25, zoom: 6, pitch: 45, bearing: 0 };

function param(over: Partial<Parameters<typeof encodeShareState>[0]>): string {
  return encodeShareState({
    camera: CAMERA, layers: [], filters: {}, openObjects: [], points: [], display: {},
    ...over,
  } as Parameters<typeof encodeShareState>[0]);
}

function setUrl(search: string) {
  window.history.replaceState({}, "", search ? `/?${search}` : "/");
}

function draw() {
  return render(<MemoryRouter><WelcomeOverlay /></MemoryRouter>);
}

beforeEach(() => {
  vi.restoreAllMocks();
  // `useStartupProfiles` fetches on mount; keep it off the network.
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve([]) })));
  useMapStore.setState({ activeLayers: new Set(), tutorialReady: false });
  setUrl("");
});
afterEach(() => { cleanup(); setUrl(""); });

describe("linkCarriesView — what counts as 'the link already answered this'", () => {
  it("is true for a link naming layers", () => {
    expect(linkCarriesView({ layers: ["contracts"] as never })).toBe(true);
  });

  it("is true for a link naming a record panel, with no layers", () => {
    expect(linkCarriesView({ layers: null, openObjects: [["contracts", "ISA-1"]] })).toBe(true);
  });

  it("is true for a link naming a point panel, with no layers", () => {
    expect(linkCarriesView({ layers: null, points: [["woa-climatology", 1, 2, 500]] })).toBe(true);
  });

  it("is FALSE for a camera-only link — the globe would be blank", () => {
    // ⛔ Not an oversight. With nothing drawn, the picker is the only way the
    // recipient gets any data; suppressing it there trades one bug for a
    // blank map.
    expect(linkCarriesView({ layers: null, openObjects: null, points: null })).toBe(false);
  });

  it("is false for no link at all, and for empty lists", () => {
    expect(linkCarriesView(null)).toBe(false);
    expect(linkCarriesView({ layers: [], openObjects: [], points: [] })).toBe(false);
  });
});

describe("the overlay itself", () => {
  it("positive control: with no link and no layers, the picker IS shown", () => {
    // ⛔ Without this, every assertion below would pass on a component that
    // renders nothing under any circumstances.
    draw();
    expect(screen.getAllByRole("button").length).toBeGreaterThan(0);
    expect(document.body.textContent!.length).toBeGreaterThan(40);
  });

  it("does not ask the recipient to pick a mode when the link names layers", () => {
    setUrl(`s=${param({ layers: ["contracts", "argo"] as never })}`);
    const { container } = draw();
    expect(container.firstChild).toBeNull();
  });

  it("does not ask when the link names a panel but no layers", () => {
    setUrl(`s=${param({ openObjects: [["contracts", "ISA-1"]] as never })}`);
    const { container } = draw();
    expect(container.firstChild).toBeNull();
  });

  it("STILL asks for a camera-only link", () => {
    setUrl(`s=${param({})}`);
    draw();
    expect(screen.getAllByRole("button").length).toBeGreaterThan(0);
  });

  it("still asks when the `s` param is corrupt — broken must not look like absent", () => {
    setUrl("s=not-a-real-envelope");
    draw();
    expect(screen.getAllByRole("button").length).toBeGreaterThan(0);
  });

  it("starts the first-visit coach it would otherwise have started on exit", () => {
    // The overlay's own `finish()` sets this; skipping the overlay must not
    // leave a link's recipient as the one visitor who never gets the tutorial.
    expect(useMapStore.getState().tutorialReady).toBe(false);   // control
    setUrl(`s=${param({ layers: ["contracts"] as never })}`);
    draw();
    expect(useMapStore.getState().tutorialReady).toBe(true);
  });
});
