// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// These are the precedence rules Map3D.tsx's module-init bootstrap follows,
// pulled into a pure module so they're testable without importing Map3D.tsx
// itself (which drags in deck.gl/MapLibre — see map3d-helpers.test.ts).
import { describe, it, expect } from "vitest";

import { resolveInitialCamera, resolveInitialLayers, shouldStripShareParam } from "../components/map3d/shareBootstrap";
import type { LayerId } from "../types/layers";

const FLY = { longitude: 1, latitude: 2, zoom: 9 };
const SHARE_CAM = { longitude: 10, latitude: 20, zoom: 6, pitch: 30, bearing: 15 };
const SAVED_CAM = { longitude: 99, latitude: 99, zoom: 3, pitch: 45, bearing: 0 };

describe("camera precedence — ?fly= wins over a share link, which wins over a saved view", () => {
  it("?fly= beats a share-link camera", () => {
    const r = resolveInitialCamera(FLY, SHARE_CAM, SAVED_CAM);
    expect(r).toEqual({ ...FLY, pitch: 45, bearing: 0 });
  });

  it("a share-link camera beats the visitor's saved view", () => {
    const r = resolveInitialCamera(null, SHARE_CAM, SAVED_CAM);
    expect(r).toEqual(SHARE_CAM);
  });

  it("falls back to the saved view when there is no link at all", () => {
    const r = resolveInitialCamera(null, null, SAVED_CAM);
    expect(r).toEqual(SAVED_CAM);
  });

  it("falls back to the hardcoded default with nothing saved and no link", () => {
    const r = resolveInitialCamera(null, null, null);
    expect(r).toEqual({ longitude: -30, latitude: 20, zoom: 3, pitch: 45, bearing: 0 });
  });
});

const ALL_IDS = ["contracts", "argo", "seamounts", "brand-new-layer"] as unknown as LayerId[];

describe("layer precedence — a link's layer list is authoritative, never merged", () => {
  it("a share link's layers are used exactly as given, ignoring saved preferences", () => {
    const shareLayers = ["contracts"] as unknown as LayerId[];
    const saved = { activeLayers: ["argo", "seamounts"] as unknown as LayerId[], knownLayers: [] as LayerId[] };
    const r = resolveInitialLayers({ layers: shareLayers }, saved, ALL_IDS);
    expect(r).toEqual(new Set(shareLayers));
  });

  it("requirement 3 — a camera-only link does NOT pull in the reader's saved layers", () => {
    // ⛔ The case this originally got wrong, and the reason the helper takes the
    // whole envelope: a link that carries a camera and no layer list is still a
    // link. Falling through to the reader's save would show the recipient their
    // OWN layers under the sender's camera, and neither of them would know.
    // `null` here means "start from the defaults", the same as a first visit.
    const saved = {
      activeLayers: ["argo"] as unknown as LayerId[],
      knownLayers: ["argo", "contracts", "seamounts", "brand-new-layer"] as LayerId[],
    };
    const r = resolveInitialLayers({}, saved, ALL_IDS);
    expect(r).toBeNull();
  });

  it("requirement 3 — an empty layer list in a link is still the link speaking", () => {
    // A sender who turned every layer off shared exactly that. It must not be
    // read as "said nothing" and refilled from the reader's save.
    //
    // ⚠️ Not reachable through the codec today: `encodeShareState` omits an
    // empty `l`, and `validateLayers` maps `[]` back to null, so a real link
    // cannot carry this. Kept because it pins the RESOLVER's contract — if the
    // codec ever learns to say "no layers, deliberately", the resolver must
    // already honour it rather than quietly substituting the reader's set.
    const saved = { activeLayers: ["argo"] as unknown as LayerId[], knownLayers: [] as LayerId[] };
    const r = resolveInitialLayers({ layers: [] as unknown as LayerId[] }, saved, ALL_IDS);
    expect(r).not.toEqual(new Set(["argo"]));
  });

  it("new-layer-defaults-ON is preserved when no link is present", () => {
    const saved = { activeLayers: ["argo"] as unknown as LayerId[], knownLayers: ["argo", "contracts"] as LayerId[] };
    // "brand-new-layer" and "seamounts" are absent from knownLayers.
    // seamounts stays opt-in; brand-new-layer auto-enables.
    const r = resolveInitialLayers(null, saved, ALL_IDS);
    expect(r).toEqual(new Set(["argo", "brand-new-layer"]));
  });

  it("returns null (do nothing) when there is neither a link nor saved state", () => {
    expect(resolveInitialLayers(null, null, ALL_IDS)).toBeNull();
  });
});

describe("a share param in the address bar — kept, or cleared", () => {
  it("keeps a param that decoded, so the live writer can own the bar", () => {
    // This is what makes "copy the URL" a way to share: the param stays and
    // useLiveShareUrl keeps it current. Stripping it, as this used to, sent
    // the reader back to a bare URL the moment the link was applied.
    expect(shouldStripShareParam("some-valid-looking-blob", { camera: null })).toBe(false);
  });

  it("clears a param that did NOT decode", () => {
    // ⛔ Otherwise the reader keeps a broken link in the bar and can pass it
    // on, and the live writer only overwrites it when they change something —
    // which may never happen. Broken must not look like absent.
    expect(shouldStripShareParam("!!!not-base64!!!", null)).toBe(true);
  });

  it("does nothing when there is no param at all", () => {
    expect(shouldStripShareParam(null, null)).toBe(false);
  });
});
