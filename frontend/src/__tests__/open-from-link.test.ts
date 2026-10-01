// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// `openFromLink` is where the two naming systems meet. A link carries the
// PUBLIC layer id; `DetailPanel` dispatches on a PRIVATE routing key, and 24 of
// those keys differ from any layer id. Getting the bridge wrong produces a link
// that is well-formed, opens nothing, and blames the data.
import { describe, it, expect, vi, afterEach } from "vitest";
import type { FeatureCollection } from "geojson";

import {
  resolveOpenTarget,
  layerIdForRoutingKey,
  openObjectsFor,
  openTargetFor,
  clickIdFor,
  OPENABLE,
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
    // Raw InterRidge values since 2026-09-21 — see ventStatus.ts. "Extinct"
    // never existed in the source and "Active" is gone; a vent's own status
    // is now "active, confirmed" | "active, inferred" | "inactive".
    const active = fc([{ name: "Lucky Strike", status: "active, confirmed" }]);
    const dead = fc([{ name: "Lucky Strike", status: "inactive" }]);
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
      const cfg = OPENABLE[layerId as keyof typeof OPENABLE];
      expect(cfg.routingKeys.length).toBeGreaterThan(0);
      for (const p of probes) {
        expect(cfg.routingKeys).toContain(cfg.routingKey(p));
      }
    }
  });

  it("maps every routing key back to its public layer id", () => {
    for (const layerId of OPENABLE_LAYER_IDS) {
      for (const key of OPENABLE[layerId as keyof typeof OPENABLE].routingKeys) {
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

describe("the click handler's id chain matches what a link can reopen", () => {
  // ⛔ coastdom and greenland-primary-production carry none of
  // isa_id/id/platform_id, so before this branch existed the click handler
  // fell through to `String(info.index)` — a deck.gl pick index that a share
  // link cannot reliably match back to a feature.
  const coastdomProps = {
    site_id: "54.32,10.11", lat: 54.32, lon: 10.11, location: "Kiel Bight",
    n_samples: 12, n_undated: 2, depth_min_m: 0, depth_max_m: 4,
    date_min: "1998-04-01", date_max: "2001-09-30",
  };
  const greenlandProps = {
    version_id: "v1", row_no: 7, event: "FS21_06E", event_2: "FS21_06E-2",
    lat: 76.1, lon: -20.4, sample_date: "2021-06-15", gpp_c_mg_m2_day: 133.4,
  };

  it("keys coastdom on site_id, not the pick index", () => {
    expect(clickIdFor("coastdom", coastdomProps, 11365)).toBe("54.32,10.11");
  });

  it("keys greenland-primary-production on event, not the pick index", () => {
    expect(clickIdFor("greenland-primary-production", greenlandProps, 10)).toBe("FS21_06E");
  });

  it("falls back to the pick index when a coastdom feature carries no site_id", () => {
    expect(clickIdFor("coastdom", { location: "unknown" }, 3)).toBe("3");
  });

  it("round-trips: the id the click handler writes reopens the same coastdom feature", async () => {
    const data = fc([{ site_id: "1,1" }, coastdomProps, { site_id: "2,2" }]);
    const clickedId = String(clickIdFor("coastdom", coastdomProps, 1));
    const t = await openTargetFor("coastdom", clickedId, data, "");
    expect(t).not.toBeNull();
    expect(t!.properties.location).toBe("Kiel Bight");
  });

  it("round-trips: the id the click handler writes reopens the same greenland station", async () => {
    const data = fc([{ event: "FS21_01" }, greenlandProps, { event: "FS21_09" }]);
    const clickedId = String(clickIdFor("greenland-primary-production", greenlandProps, 0));
    const t = await openTargetFor("greenland-primary-production", clickedId, data, "");
    expect(t).not.toBeNull();
    expect(t!.properties.gpp_c_mg_m2_day).toBe(133.4);
  });

  // AOC2025 POC (preview, dev-only) carries none of isa_id/id/platform_id/site_id/
  // event either — same fallback-to-pick-index failure mode as coastdom/greenland
  // above, guarded the same way.
  const aocPocProps = {
    station: "AOC2025-2", n_samples: 3, depth_min_db: 5, depth_max_db: 40,
    date_min: "2025-05-19", date_max: "2025-05-19",
  };

  it("keys greenland-sea-poc-aoc2025 on station, not the pick index", () => {
    expect(clickIdFor("greenland-sea-poc-aoc2025", aocPocProps, 42)).toBe("AOC2025-2");
  });

  it("falls back to the pick index when an AOC2025 POC feature carries no station", () => {
    expect(clickIdFor("greenland-sea-poc-aoc2025", { n_samples: 1 }, 5)).toBe("5");
  });

  it("round-trips: the id the click handler writes reopens the same AOC2025 POC station", async () => {
    const data = fc([{ station: "AOC2025-1" }, aocPocProps, { station: "AOC2025-9" }]);
    const clickedId = String(clickIdFor("greenland-sea-poc-aoc2025", aocPocProps, 1));
    const t = await openTargetFor("greenland-sea-poc-aoc2025", clickedId, data, "");
    expect(t).not.toBeNull();
    expect(t!.properties.depth_max_db).toBe(40);
  });

  // Svalbard Fjords PP (preview, dev-only): the SAME station name is sampled
  // at more than one position, so this layer must key on position_id, never
  // on station — a station-keyed link would reopen the wrong position.
  const svalbardFjordsPpProps = {
    position_id: "K:K2:78.97:11.74", station: "K2", region_code: "K",
    fjord_part: "Inner", n_expositions: 2, first_date: "1994-07-05", last_date: "2019-08-11",
  };

  it("keys svalbard-fjords-primary-production on position_id, not station", () => {
    expect(clickIdFor("svalbard-fjords-primary-production", svalbardFjordsPpProps, 42)).toBe("K:K2:78.97:11.74");
  });

  it("falls back to the pick index when a Svalbard Fjords PP feature carries no position_id", () => {
    expect(clickIdFor("svalbard-fjords-primary-production", { station: "K2" }, 5)).toBe("5");
  });

  it("round-trips: the id the click handler writes reopens the same Svalbard Fjords PP position, even with a reused station name", async () => {
    const otherPositionSameStation = { position_id: "K:K2:78.88:12.48", station: "K2", region_code: "K" };
    const data = fc([otherPositionSameStation, svalbardFjordsPpProps]);
    const clickedId = String(clickIdFor("svalbard-fjords-primary-production", svalbardFjordsPpProps, 1));
    const t = await openTargetFor("svalbard-fjords-primary-production", clickedId, data, "");
    expect(t).not.toBeNull();
    expect(t!.properties.position_id).toBe("K:K2:78.97:11.74");
  });
});

describe("client-held data comes first, the network only as a fallback", () => {
  afterEach(() => { vi.restoreAllMocks(); });

  it("does not go to the network for a feature it already has", async () => {
    // ⛔ `/by-id` supplements a tile, it does not reproduce one — PermafrostThaw
    // renders category, type and site name straight from the tile's properties
    // and the endpoint returns none of them. Asking the network first opens a
    // panel poorer than a click does, and says nothing about the difference.
    const spy = vi.spyOn(globalThis, "fetch");
    const data = fc([{ unique_id: "PF-1", feature_category: "thermokarst" }]);
    const t = await openTargetFor("permafrost-thaw", "PF-1", data, "");
    expect(t).not.toBeNull();
    expect(t!.properties.feature_category).toBe("thermokarst");
    expect(spy).not.toHaveBeenCalled();
  });

  it("asks the network when the client does not hold the feature", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true, json: async () => ({ gid: 77, ocs_mean: 12 }),
    } as unknown as Response);
    const t = await openTargetFor("arctic-catchments", "77", null, "");
    expect(spy).toHaveBeenCalledTimes(1);
    expect(t!.routingKey).toBe("arctic-catchments");
    expect(t!.properties.ocs_mean).toBe(12);
  });

  it("returns null — for the caller to report — when the network refuses", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: false, status: 404 } as unknown as Response);
    expect(await openTargetFor("arctic-catchments", "nope", null, "")).toBeNull();
  });
});

