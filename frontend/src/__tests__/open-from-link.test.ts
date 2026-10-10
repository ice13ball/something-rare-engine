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

describe("OceanSITES moorings are keyed on ref, never on the pick index", () => {
  // ⛔ OceanSITES features carry none of isa_id/id/platform_id, so the click
  // handler wrote the deck.gl pick index ("oceansites · 469") into the link and
  // the restore — which searches the id chain — answered "points at something
  // missing". `ref` is the only unique key (1038 of 1038 features on prod).
  const mooring = { ref: "TMP1578159815", name: "Mooring T", network: "TAO", status: "operational" };
  const other = { ref: "1500009", name: "Mooring O", network: "OOI", status: "operational" };
  const third = { ref: "4400001", name: "Mooring Z", network: "DART", status: "operational" };

  it("writes the ref into the link, not the pick index", () => {
    expect(clickIdFor("oceansites", mooring, 469)).toBe("TMP1578159815");
    expect(clickIdFor("oceansites", other, 0)).toBe("1500009");
  });

  it("falls back to the pick index when a mooring carries no ref", () => {
    expect(clickIdFor("oceansites", { name: "no ref" }, 7)).toBe("7");
  });

  it("round-trips through openObjectsFor: the link carries the ref", () => {
    const id = clickIdFor("oceansites", mooring, 469);
    expect(openObjectsFor([{ id, layer: "oceansites" }])).toEqual([["oceansites", "TMP1578159815"]]);
  });

  it("opens that exact mooring, even when the feature array is reordered", async () => {
    const clickedId = String(clickIdFor("oceansites", mooring, 0));
    for (const order of [[mooring, other, third], [third, other, mooring], [other, mooring, third]]) {
      const t = await openTargetFor("oceansites", clickedId, fc(order), "");
      expect(t).not.toBeNull();
      expect(t!.routingKey).toBe("oceansites");
      expect(t!.properties.name).toBe("Mooring T");
      expect(t!.id).toBe("TMP1578159815");
    }
  });

  it("does not let a bare pick index open some unrelated mooring", () => {
    // An old link carrying the index must say "missing", not open mooring #1.
    const data = fc([mooring, other, third]);
    expect(resolveOpenTarget("oceansites", "1", data)).toBeNull();
    expect(resolveOpenTarget("oceansites", "469", data)).toBeNull();
    expect(resolveOpenTarget("oceansites", "0", data)).toBeNull();
  });

  it("does not match on a ref-like value carried in another property", () => {
    // `ref` is OceanSITES' own key, not part of the global chain: another
    // layer's `ref` must never be reachable through it, and here an unrelated
    // property that merely equals the link id must not match either.
    const data = fc([{ ref: "A", name: "1500009" }]);
    expect(resolveOpenTarget("oceansites", "1500009", data)).toBeNull();
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


describe("GLODAP casts are keyed on cast_key, never on the pick index", () => {
  afterEach(() => { vi.restoreAllMocks(); });
  const cast = { key: "49UF20150620_4511_1", cast_key: "49UF20150620_4511_1" };

  it("writes the cast key into the link, not the pick index", () => {
    expect(clickIdFor("glodap-points", cast, 51234)).toBe("49UF20150620_4511_1");
  });
  it("accepts the points document's own name for it (`key`)", () => {
    expect(clickIdFor("glodap-points", { key: "49UF20150620_4511_1" }, 7)).toBe("49UF20150620_4511_1");
  });
  it("is not captured by the generic chain: an `id` on the properties never wins", () => {
    expect(clickIdFor("glodap-points", { ...cast, id: 7 }, 3)).toBe("49UF20150620_4511_1");
  });
  it("a reloaded BGC-Argo link reopens the same profile: `/by-id` by profile_key, panel routed to argo-oxygen-points, camera on its position", async () => {
    const body = { profile_key: "coriolis_3902120_002D", lat: -23.93, lon: 10.5 };
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true, json: async () => body } as unknown as Response);
    const id = clickIdFor("argo-oxygen-points", { profile_key: "coriolis_3902120_002D", key: "coriolis_3902120_002D" }, 99);
    const [layerId, featureId] = openObjectsFor([{ id, layer: "argo-oxygen-points" }])[0];
    expect([layerId, featureId]).toEqual(["argo-oxygen-points", "coriolis_3902120_002D"]);
    const t = await openTargetFor(layerId, featureId, null, "");
    expect((spy.mock.calls[0] as unknown as [string])[0]).toBe("/api/v1/argo-oxygen/profile/coriolis_3902120_002D");
    expect(t!.routingKey).toBe("argo-oxygen-points");
    expect(t!.id).toBe("coriolis_3902120_002D");
    expect(t!.properties.profile_key).toBe("coriolis_3902120_002D");   // the panel reads this
    expect(t!.zoom).toBe(6);
    expect(t!.feature.geometry).toEqual({ type: "Point", coordinates: [10.5, -23.93] });
  });
  it("an unknown profile (404) is null, for the caller to report", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: false, status: 404 } as unknown as Response);
    expect(await openTargetFor("argo-oxygen-points", "aoml_1900722_999", null, "")).toBeNull();
  });
  it("argo-oxygen-points links carry the profile key, never the pick index", () => {
    expect(clickIdFor("argo-oxygen-points", { profile_key: "coriolis_3902120_002D" }, 17)).toBe("coriolis_3902120_002D");
    expect(clickIdFor("argo-oxygen-points", { key: "aoml_1900722_001" }, 3)).toBe("aoml_1900722_001");
    expect(clickIdFor("argo-oxygen-points", { profile_key: "aoml_1900722_001", id: 7 }, 3)).toBe("aoml_1900722_001");
  });
  it("round-trips through the cast key, not the pick index or the row id", () => {
    const id = clickIdFor("glodap-points", { ...cast, id: 7 }, 3);
    expect(openObjectsFor([{ id, layer: "glodap-points" }])).toEqual([["glodap-points", "49UF20150620_4511_1"]]);
  });

  it("a reloaded link reopens the same cast: `/by-id` by cast_key, panel routed to glodap-points, camera on its position", async () => {
    // After a reload the layer's data is NOT loaded and every surrogate id has changed — the only thing that
    // survives is the cast key in the link, so the lookup has to go to the API with exactly that.
    const body = { cast_key: "49UF20150620_4511_1", lat: 1.23, lon: 4.56, expocode: "49UF20150620" };
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true, json: async () => body } as unknown as Response);
    const [layerId, featureId] = openObjectsFor([{ id: clickIdFor("glodap-points", cast, 99), layer: "glodap-points" }])[0];
    const t = await openTargetFor(layerId, featureId, null, "");
    expect(spy).toHaveBeenCalledTimes(1);
    expect((spy.mock.calls[0] as unknown as [string])[0]).toBe("/api/v1/glodap/cast/49UF20150620_4511_1");
    expect(t!.routingKey).toBe("glodap-points");
    expect(t!.id).toBe("49UF20150620_4511_1");               // the same id a click writes -> the panel dedupes
    expect(t!.properties.cast_key).toBe("49UF20150620_4511_1");
    expect(t!.zoom).toBe(6);
    // the link can fly there: the bare answer's lat/lon became a Point
    expect(t!.feature.geometry).toEqual({ type: "Point", coordinates: [4.56, 1.23] });
  });

  it("a reloaded SOCAT link reopens the observation: `/by-id` by obs_key (encodeURIComponent leaves the `~`), panel routed to socat-points, camera on its position", async () => {
    const body = { obs_key: "33GC20040908~1", lat: 42.9, lon: -70.5, expocode: "33GC20040908" };
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true, json: async () => body } as unknown as Response);
    const id = clickIdFor("socat-points", { obs_key: "33GC20040908~1", lod: false, year: 2004, k: 5, cell: "10/300/400/77" }, 99);
    expect(id).toBe("33GC20040908~1");
    const [layerId, featureId] = openObjectsFor([{ id, layer: "socat-points" }])[0];
    expect([layerId, featureId]).toEqual(["socat-points", "33GC20040908~1"]);
    const t = await openTargetFor(layerId, featureId, null, "");
    expect((spy.mock.calls[0] as unknown as [string])[0]).toBe("/api/v1/socat/obs/33GC20040908~1");
    expect(t!.routingKey).toBe("socat-points");
    expect(t!.id).toBe("33GC20040908~1");
    expect(t!.properties.obs_key).toBe("33GC20040908~1");
    expect(t!.zoom).toBe(9);
    expect(t!.feature.geometry).toEqual({ type: "Point", coordinates: [-70.5, 42.9] });
  });

  it("a reloaded WOD cast link reopens the cast: `/by-id` by cast_id, panel routed to wod-casts, camera on its position", async () => {
    const body = { cast_id: 9000001, lat: 42.9, lon: -70.5, instrument: "ctd" };
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true, json: async () => body } as unknown as Response);
    const id = clickIdFor("wod-casts", { cast_id: 9000001, k: 5, a: 1990, b: 2004, cell: "10/300/400/77" }, 99);
    expect(id).toBe(9000001);
    const [layerId, featureId] = openObjectsFor([{ id, layer: "wod-casts" }])[0];
    expect([layerId, featureId]).toEqual(["wod-casts", "9000001"]);
    const t = await openTargetFor(layerId, featureId, null, "");
    expect((spy.mock.calls[0] as unknown as [string])[0]).toBe("/api/v1/wod/cast/9000001");
    expect(t!.routingKey).toBe("wod-casts");
    expect(t!.id).toBe("9000001");
    expect(t!.properties.cast_id).toBe(9000001);
    expect(t!.zoom).toBe(8);
    expect(t!.feature.geometry).toEqual({ type: "Point", coordinates: [-70.5, 42.9] });
  });

  it("a cast that no longer exists (404) is null — for the caller to report", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: false, status: 404 } as unknown as Response);
    expect(await openTargetFor("wod-casts", "1", null, "")).toBeNull();
  });

  it("an observation that no longer exists (404) is null — for the caller to report", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: false, status: 404 } as unknown as Response);
    expect(await openTargetFor("socat-points", "GONE~0", null, "")).toBeNull();
  });

  it("a cast key with reserved characters is encoded in the path", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true, json: async () => ({ cast_key: "A/B_1_1", lat: 1, lon: 2 }) } as unknown as Response);
    await openTargetFor("glodap-points", "A/B_1_1", null, "");
    expect((spy.mock.calls[0] as unknown as [string])[0]).toBe("/api/v1/glodap/cast/A%2FB_1_1");
  });

  it("a cast that no longer exists (404) is null — for the caller to report", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: false, status: 404 } as unknown as Response);
    expect(await openTargetFor("glodap-points", "GONE_1_1", null, "")).toBeNull();
  });

  it("only layers that opt in get a Point from a bare lat/lon answer", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true, json: async () => ({ gid: 77, lat: 5, lon: 6 }) } as unknown as Response);
    const t = await openTargetFor("arctic-catchments", "77", null, "");
    expect(t!.feature.geometry).toBeNull();
  });
});
