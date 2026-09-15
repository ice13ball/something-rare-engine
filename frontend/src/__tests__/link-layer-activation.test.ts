// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// A link may carry BOTH a layer list and a panel. Switching the panel's layer
// on used to merge onto the `activeLayers` captured in the effect's closure —
// a value one render behind the mount effect that had just applied the link's
// own list. Every layer the link named but the panel did not need was dropped.
//
// Reproduced on production 2026-09-15 with
//   l: ["ocean-carbon", "ocean-co2-surface"], p: [["ocean-carbon", …]]
// which opened with exactly ["ocean-carbon"] active. Silently: no notice, no
// console error — and the live address writer then re-encoded the loss, so the
// recipient could not pass the sender's link on either.
import { describe, it, expect } from "vitest";

import { nextActiveForLink, NO_CLIENT_COPY } from "../components/map3d/linkLayerActivation";
import { resolveOpenTarget } from "../components/map3d/openFromLink";

const openable = (id: string) => id !== "not-openable";
const point = (id: string) => id !== "not-a-point";

describe("nextActiveForLink", () => {
  it("keeps a layer the link carried but no panel needs", () => {
    // ⛔ THE regression. `ocean-co2-surface` is named by the link and wanted by
    // nothing else; it must survive switching the point's layer on.
    const out = nextActiveForLink(
      new Set(["ocean-carbon", "ocean-co2-surface"]),
      [],
      [["ocean-carbon", -30, 20, 1000]],
      openable, point,
    );
    // Nothing to add — the point's layer is already on — so no write at all.
    expect(out).toBeNull();
  });

  it("adds the panel's layer WITHOUT dropping the others", () => {
    const out = nextActiveForLink(
      new Set(["ocean-carbon", "ocean-co2-surface"]),
      [],
      [["vme-suitability", -30, 20]],
      openable, point,
    );
    expect(out).not.toBeNull();
    expect([...out!].sort()).toEqual(
      ["ocean-carbon", "ocean-co2-surface", "vme-suitability"],
    );
  });

  it("merges record panels and point panels in one pass", () => {
    const out = nextActiveForLink(
      new Set(["contracts"]),
      [["argo", "7900884"]],
      [["woa-climatology", -30, 20, 500]],
      openable, point,
    );
    expect([...out!].sort()).toEqual(["argo", "contracts", "woa-climatology"]);
  });

  it("ignores an entry naming a layer of the wrong kind", () => {
    // A record id for a layer that is not openable, and a coordinate for a
    // layer that is not a point layer: neither may switch anything on.
    const out = nextActiveForLink(
      new Set(["contracts"]),
      [["not-openable", "x"]],
      [["not-a-point", 1, 2]],
      openable, point,
    );
    expect(out).toBeNull();
  });

  it("returns null when every wanted layer is already on", () => {
    // ⛔ Not an equal set: the caller writes to the store only on a non-null,
    // and an unconditional write re-runs the effect that produced it.
    const out = nextActiveForLink(
      new Set(["argo"]), [["argo", "1"]], [], openable, point,
    );
    expect(out).toBeNull();
  });

  it("never mutates the set it was given", () => {
    const base = new Set(["contracts"]);
    nextActiveForLink(base, [["argo", "1"]], [], openable, point);
    expect([...base]).toEqual(["contracts"]);
  });
});

// ⛔ Three MVT-only layers stored a literal `null` as their client-side copy,
// and `null` is the map's word for "the fetch has not landed". A link naming
// one waited for data that would never arrive: no panel, no `/by-id` request,
// and no failure notice either, because the wait returns before the code that
// reports one. Observed on the dev deployment 2026-09-15 for `memento`:
// nine tile requests, zero by-id requests, zero notices.
describe("a layer with no client-side copy", () => {
  it("says so with an empty collection, never with null", () => {
    expect(NO_CLIENT_COPY).not.toBeNull();
    expect(NO_CLIENT_COPY.type).toBe("FeatureCollection");
    expect(NO_CLIENT_COPY.features).toEqual([]);
  });

  it("is frozen, so one layer cannot fill another layer's copy", () => {
    expect(Object.isFrozen(NO_CLIENT_COPY)).toBe(true);
  });

  it("sends the resolver past the client lookup instead of matching nothing", () => {
    // Same answer as `null` from the resolver's point of view — the whole
    // difference lives in the caller, which must not WAIT on this one.
    expect(resolveOpenTarget("memento", "7894b1c77c39d6fa", NO_CLIENT_COPY)).toBeNull();
  });

  it("still looks like a searchable collection to the search bar", () => {
    // SearchBar bails on `!fc?.features`; an empty array is truthy, so the
    // group is scanned and simply finds nothing — as it did with null.
    expect(Boolean(NO_CLIENT_COPY.features)).toBe(true);
  });
});
