// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// `openFromLink` is where the two naming systems meet. A link carries the
// PUBLIC layer id; `DetailPanel` dispatches on a PRIVATE routing key, and 24 of
// those keys differ from any layer id. Getting the bridge wrong produces a link
// that is well-formed, opens nothing, and blames the data.
import { describe, it, expect } from "vitest";
import type { FeatureCollection } from "geojson";

import {
  resolveOpenTarget,
  layerIdForRoutingKey,
  openObjectsFor,
  STAGE1_OPENABLE,
  OPENABLE_LAYER_IDS,
} from "../components/map3d/openFromLink";

const fc = (props: Array<Record<string, unknown>>): FeatureCollection => ({
  type: "FeatureCollection",
  features: props.map((p) => ({
    type: "Feature",
    geometry: { type: "Point", coordinates: [0, 0] },
    properties: p,
  })),
});

describe("finding the feature a link names", () => {
  it("matches on the layer's own id property and returns its panel key", () => {
    const data = fc([{ isa_id: "ISA-001" }, { isa_id: "ISA-002" }]);
    const t = resolveOpenTarget("contracts", "ISA-002", data)!;
    expect(t).not.toBeNull();
    expect(t.routingKey).toBe("mining-contracts-mvt");
    expect(t.id).toBe("ISA-002");
    expect(t.properties.isa_id).toBe("ISA-002");
  });

  it("picks the panel from the feature's own properties, not from the layer id", () => {
    // ⛔ The whole reason a link can carry the public id: the routing key is
    // chosen AFTER the lookup, so the value-dependent split is decidable.
    const active = fc([{ name: "Lucky Strike", status: "Active" }]);
    const dead = fc([{ name: "Lucky Strike", status: "Extinct" }]);
    expect(resolveOpenTarget("hydrothermal-vents", "Lucky Strike", active)!.routingKey)
      .toBe("hydrothermal-vents-active");
    expect(resolveOpenTarget("hydrothermal-vents", "Lucky Strike", dead)!.routingKey)
      .toBe("hydrothermal-vents-inactive");
  });

  it("finds a vent by its numeric id as well as by its name", () => {
    // ⛔ The write side emits whatever the click path stored, which for a vent
    // is `id`; `?focus=vent:<name>` and the SEO buttons carry `name`. Both
    // routes must land on the same feature — a single-property lookup shipped
    // a link the panel could not reopen, caught only by the new notice.
    const data = fc([{ id: 405, name: "Lucky Strike", status: "Active" }]);
    expect(resolveOpenTarget("hydrothermal-vents", "405", data)!.id).toBe(405);
    expect(resolveOpenTarget("hydrothermal-vents", "Lucky Strike", data)!.id).toBe("Lucky Strike");
  });

  it("matches exactly, not by substring", () => {
    // `searchById` uses a substring match because a human is typing. A link is
    // machine-generated, and a substring match would let one link open a
    // different vent than the sender was looking at.
    const data = fc([{ name: "Lucky Strike North" }]);
    expect(resolveOpenTarget("hydrothermal-vents", "Lucky Strike", data)).toBeNull();
    expect(resolveOpenTarget("hydrothermal-vents", "Lucky Strike North", data)).not.toBeNull();
  });

  it("returns null — never a wrong feature — when nothing matches", () => {
    const data = fc([{ isa_id: "ISA-001" }]);
    expect(resolveOpenTarget("contracts", "ISA-999", data)).toBeNull();
  });

  it("returns null while the layer's data has not arrived", () => {
    expect(resolveOpenTarget("contracts", "ISA-001", null)).toBeNull();
    expect(resolveOpenTarget("contracts", "ISA-001", fc([]))).toBeNull();
  });

  it("refuses a layer stage 1 cannot open", () => {
    const data = fc([{ id: "x" }]);
    expect(resolveOpenTarget("bathymetry", "x", data)).toBeNull();
  });
});

describe("the two directions agree", () => {
  it("every key routingKey() can return is listed in routingKeys", () => {
    // ⛔ Two hand-kept lists. Without this they drift, and the drift is silent:
    // the link opens, the write side just stops carrying that panel.
    const probes = [{}, { status: "Active" }, { status: "Extinct" }, { status: "Inactive" }];
    expect(OPENABLE_LAYER_IDS.length).toBeGreaterThan(0);
    for (const layerId of OPENABLE_LAYER_IDS) {
      const cfg = STAGE1_OPENABLE[layerId];
      expect(cfg.routingKeys.length).toBeGreaterThan(0);
      for (const p of probes) {
        expect(cfg.routingKeys).toContain(cfg.routingKey(p));
      }
    }
  });

  it("maps every routing key back to its public layer id", () => {
    for (const layerId of OPENABLE_LAYER_IDS) {
      for (const key of STAGE1_OPENABLE[layerId].routingKeys) {
        expect(layerIdForRoutingKey(key)).toBe(layerId);
      }
    }
  });

  it("refuses a routing key no link may carry", () => {
    expect(layerIdForRoutingKey("memento-hexes")).toBeNull();
  });
});

describe("what the write side puts in a link", () => {
  it("translates open panels into public layer ids", () => {
    const out = openObjectsFor([
      { id: "ISA-002", layer: "mining-contracts-mvt" },
      { id: "Lucky Strike", layer: "hydrothermal-vents-inactive" },
    ]);
    expect(out).toEqual([
      ["contracts", "ISA-002"],
      ["hydrothermal-vents", "Lucky Strike"],
    ]);
  });

  it("drops a panel the reader could not reopen, rather than emitting it", () => {
    // ⛔ Filtering only on READ would still put the entry in a link — and links
    // travel. It would sit in someone's inbox long before the layer became
    // openable, failing every time it was clicked.
    const out = openObjectsFor([
      { id: "ISA-002", layer: "mining-contracts-mvt" },
      { id: "abc", layer: "memento-hexes" },
    ]);
    expect(out).toEqual([["contracts", "ISA-002"]]);
  });
});
