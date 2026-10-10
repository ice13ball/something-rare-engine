// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// `openableRegistry.ts` names, per layer, the key `DetailPanel` dispatches on.
// Those keys are hand-entered strings in a private namespace with 72 members,
// and nothing in the type system ties them to the dispatcher — a typo compiles,
// ships, and produces a link that opens nothing.
//
// ⛔ This is the test that makes hand-entry safe. The completeness of the
// registry itself is guarded at COMPILE time by AssertComplete/AssertDisjoint;
// what a type cannot check is whether the string corresponds to a real branch.
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

import { OPENABLE, OPENABLE_LOOKUP, NOT_OPENABLE } from "../types/openableRegistry";
import { LAYER_DEFAULTS } from "../utils/layerConfig";

const DETAIL_PANEL = path.resolve(__dirname, "../components/DetailPanel.tsx");

const dispatcherBranches = (): Set<string> => {
  const src = fs.readFileSync(DETAIL_PANEL, "utf8");
  return new Set([...src.matchAll(/layer === "([a-z0-9:-]+)"/g)].map((m) => m[1]));
};

describe("every key the registry promises is a branch the dispatcher has", () => {
  it("reads a non-empty dispatcher", () => {
    // ⛔ Positive control first. An empty branch set would make every
    // "is a member" assertion below vacuous in the wrong direction — and a
    // regex that stopped matching is exactly how that happens.
    expect(dispatcherBranches().size).toBeGreaterThan(50);
    expect(Object.keys(OPENABLE).length).toBeGreaterThan(30);
  });

  it("each routing key exists in DetailPanel", () => {
    const branches = dispatcherBranches();
    const orphans: string[] = [];
    for (const [layerId, cfg] of Object.entries(OPENABLE)) {
      for (const key of cfg.routingKeys) {
        if (!branches.has(key)) orphans.push(`${layerId} → ${key}`);
      }
    }
    expect(orphans).toEqual([]);
  });

  it("every key routingKey() can return is declared in routingKeys", () => {
    // Two hand-kept lists per layer; without this they drift silently — the
    // link opens, the write side just stops carrying that panel.
    const probes = [{}, { status: "Active" }, { status: "Extinct" }, { status: "Inactive" }];
    for (const [layerId, cfg] of Object.entries(OPENABLE)) {
      expect(cfg.routingKeys.length, layerId).toBeGreaterThan(0);
      for (const p of probes) expect(cfg.routingKeys, layerId).toContain(cfg.routingKey(p));
    }
  });

  it("a layer is either openable or opted out, never both and never neither", () => {
    // The compile-time guards say this too; asserting it here names the layer
    // in a test report rather than only in a type error.
    const covered = new Set(Object.keys(OPENABLE));
    const opted = new Set<string>(NOT_OPENABLE);
    expect(covered.size).toBeGreaterThan(0);
    expect(opted.size).toBeGreaterThan(0);
    expect([...covered].filter((l) => opted.has(l))).toEqual([]);
    expect(covered.size + opted.size).toBe(69);
  });

  it("an identifier known to rot is marked, not quietly treated as stable", () => {
    // ⛔ OBIS mints a new id on every republication. A reader whose link stops
    // working deserves to be told the link aged, not that the record never was.
    expect(OPENABLE["biodiversity-hotspots"].idStability).toBe("regenerated");
  });
});

describe("alsoActivate names real layers and is wired where the cast link needs it", () => {
  it("every alsoActivate id is a layer the map has, and never the layer itself", () => {
    const real = new Set(LAYER_DEFAULTS.map((l) => l.id as string));
    expect(real.size).toBeGreaterThan(50);                       // positive control
    const withAlso = Object.entries(OPENABLE_LOOKUP).filter(([, c]) => c.alsoActivate?.length);
    expect(withAlso.length).toBeGreaterThan(0);
    for (const [layerId, cfg] of withAlso) {
      for (const dep of cfg.alsoActivate!) {
        expect(real.has(dep), `${layerId} -> ${dep}`).toBe(true);
        expect(dep).not.toBe(layerId);
      }
    }
  });
  it("the GLODAP cast link also switches on the Ocean Carbon field", () => {
    expect(OPENABLE["glodap-points"].alsoActivate).toEqual(["ocean-carbon"]);
  });
  it("the BGC-Argo profile link is keyed on the profile key and also switches on the Ocean Oxygen field", () => {
    const e = OPENABLE["argo-oxygen-points"];
    expect(e.source).toBe("by-id");
    expect(e.idStability).toBe("stable");
    expect(e.byIdPath).toBe("/api/v1/argo-oxygen/profile/");
    expect(e.idProps).toEqual(["profile_key", "key"]);
    expect(e.alsoActivate).toEqual(["oxygen-deox"]);
  });
  it("the SOCAT observation link is keyed on obs_key, opens at the point zoom and also switches on the Surface CO2 field", () => {
    const e = OPENABLE["socat-points"];
    expect(e.source).toBe("by-id");
    expect(e.idStability).toBe("stable");
    expect(e.byIdPath).toBe("/api/v1/socat/obs/");
    expect(e.idProps).toEqual(["obs_key"]);
    expect(e.zoom).toBe(9);
    expect(e.geometryFromLatLon).toBe(true);
    expect(e.alsoActivate).toEqual(["ocean-co2-surface"]);
  });
  it("the WOD cast link is keyed on cast_id, opens at zoom 8 and also switches on the WOA climatology", () => {
    const e = OPENABLE["wod-casts"];
    expect(e.source).toBe("by-id");
    expect(e.idStability).toBe("stable");
    expect(e.byIdPath).toBe("/api/v1/wod/cast/");
    expect(e.idProps).toEqual(["cast_id"]);
    expect(e.zoom).toBe(8);
    expect(e.geometryFromLatLon).toBe(true);
    expect(OPENABLE_LOOKUP["wod-casts"].dataKey).toBeUndefined();
    expect(e.alsoActivate).toEqual(["woa-climatology"]);
  });
});
