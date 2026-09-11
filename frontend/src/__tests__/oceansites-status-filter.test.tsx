// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// OceanSITES gained a status filter because 64 of 1,037 positioned stations are
// OPERATIONAL (measured on production 2026-09-11) — the other 973 are moorings
// that were recovered, retired, or announced and never deployed. Without it the
// map answers "where are the moorings" with a century of history at once.
//
// ⛔ The keys are OceanOPS's OWN status words. We gloss them, we never rewrite
// them, and we never collapse them into "active"/"inactive" — CLOSED and
// INACTIVE are different statements about a mooring.
//
// ⛔ THE TRAP THIS LAYER HAS ALREADY FALLEN INTO. A filtered layer needs its
// predicate in TWO places: the features deck.gl draws, and flyConfigs, which
// decides where the zoom button lands. When those drifted apart on OceanSITES,
// flyToLayer cycled through features the map was not drawing and zoomed to an
// empty patch of ocean. The fix is one shared predicate, and the test below
// asserts the sharing rather than the wording.
import { describe, it, expect, beforeEach } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { useMapStore } from "../store/mapStore";
import { OCEANSITES_STATUS_DEFS, OCEANSITES_NETWORK_DEFS } from "../components/controls/filterDefs";
import { oceansitesPasses } from "../utils/oceansitesFilter";

const SRC = path.resolve(__dirname, "..");
const LOCALES = path.resolve(__dirname, "../../public/locales");

const read = (p: string) => fs.readFileSync(p, "utf8");
/** Strip comments so a guard never passes (or fails) on prose about itself. */
const code = (s: string) =>
  s.replace(/\/\*[\s\S]*?\*\//g, " ").replace(/(?<!:)\/\/[^\n]*/g, " ");

beforeEach(() => { useMapStore.getState().resetAllFilters(); });

describe("OceanSITES status filter — state", () => {
  it("starts empty, so the map shows every station the source gave", () => {
    expect(useMapStore.getState().oceansitesStatusFilters.size).toBe(0);
  });

  it("toggles on and off without mutating the previous Set", () => {
    const before = useMapStore.getState().oceansitesStatusFilters;
    useMapStore.getState().toggleOceansitesStatusFilter("OPERATIONAL");
    const after = useMapStore.getState().oceansitesStatusFilters;
    expect(after.has("OPERATIONAL")).toBe(true);
    expect(before.has("OPERATIONAL")).toBe(false);   // immutable update
    expect(after).not.toBe(before);
    useMapStore.getState().toggleOceansitesStatusFilter("OPERATIONAL");
    expect(useMapStore.getState().oceansitesStatusFilters.size).toBe(0);
  });

  it("is cleared by resetAllFilters — the single most-forgotten wiring", () => {
    useMapStore.getState().toggleOceansitesStatusFilter("CLOSED");
    useMapStore.getState().toggleOceansitesNetworkFilter("OceanSITES/RAMA");
    expect(useMapStore.getState().oceansitesStatusFilters.size).toBe(1);
    useMapStore.getState().resetAllFilters();
    expect(useMapStore.getState().oceansitesStatusFilters.size).toBe(0);
    expect(useMapStore.getState().oceansitesNetworkFilters.size).toBe(0);
  });
});

describe("OceanSITES status filter — the source's own vocabulary", () => {
  it("offers exactly the four statuses OceanOPS publishes", () => {
    // Measured on production 2026-09-11 over 1,037 positioned stations:
    //   OPERATIONAL 64 · INACTIVE 288 · CLOSED 679 · REGISTERED 6
    expect(OCEANSITES_STATUS_DEFS.map(d => d.key).sort())
      .toEqual(["CLOSED", "INACTIVE", "OPERATIONAL", "REGISTERED"]);
  });

  it("keeps four distinct source words rather than collapsing them to a two-state toggle", () => {
    // ⛔ INACTIVE is one of OceanOPS's real words — an earlier version of this
    // test listed it as a forbidden invention and went red on the truth. The
    // invention to guard against is ACTIVE (a word the source never uses) and
    // any two-state collapse of the four.
    const keys = OCEANSITES_STATUS_DEFS.map(d => d.key);
    expect(new Set(keys).size).toBe(4);
    for (const k of keys) {
      expect(k).toBe(k.toUpperCase());          // stored verbatim, not title-cased
      expect(["ACTIVE", "ON", "OFF", "LIVE"]).not.toContain(k);
    }
  });
});

describe("OceanSITES status filter — the zoom must agree with the map", () => {
  const map3d = code(read(path.join(SRC, "components/Map3D.tsx")));

  it("uses ONE predicate for the drawn features and for flyConfigs", () => {
    // the shared predicate exists
    expect(map3d).toMatch(/const\s+oceansitesPasses\s*=\s*useCallback/);
    // the rendered set uses it
    const memo = map3d.slice(
      map3d.indexOf("const filteredOceansitesFeatures"),
      map3d.indexOf("const filteredChessFeatures"),
    );
    expect(memo).toContain("oceansitesPasses");
    // and so does the fly config, by reference — not by a restated rule
    const fly = map3d.slice(map3d.indexOf('"oceansites": {'));
    const entry = fly.slice(0, fly.indexOf("},") + 2);
    expect(entry).toMatch(/filter:\s*oceansitesPasses/);
  });

  // ⛔ These CALL the rule. The previous version grepped Map3D for both filter
  // names and passed while the status check was deleted — the dependency array
  // still mentioned it. A predicate you can run is a predicate you can trust.
  const NONE = new Set<string>();
  const OPERATIONAL = new Set(["OPERATIONAL"]);
  const RAMA = new Set(["OceanSITES/RAMA"]);
  const rama_op   = { network: "OceanSITES/RAMA", status: "OPERATIONAL" };
  const rama_clsd = { network: "OceanSITES/RAMA", status: "CLOSED" };
  const pirata_op = { network: "OceanSITES/PIRATA", status: "OPERATIONAL" };

  it("shows everything when both Sets are empty", () => {
    for (const f of [rama_op, rama_clsd, pirata_op])
      expect(oceansitesPasses(f, NONE, NONE)).toBe(true);
  });

  it("hides a CLOSED station once OPERATIONAL is selected", () => {
    expect(oceansitesPasses(rama_op,   NONE, OPERATIONAL)).toBe(true);
    expect(oceansitesPasses(rama_clsd, NONE, OPERATIONAL)).toBe(false);
  });

  it("combines the two Sets with AND, never OR", () => {
    expect(oceansitesPasses(rama_op,   RAMA, OPERATIONAL)).toBe(true);
    expect(oceansitesPasses(rama_clsd, RAMA, OPERATIONAL)).toBe(false); // right net, wrong status
    expect(oceansitesPasses(pirata_op, RAMA, OPERATIONAL)).toBe(false); // right status, wrong net
  });

  it("treats a station with no status as filtered out, not as a wildcard", () => {
    expect(oceansitesPasses({ network: "OceanSITES" }, NONE, OPERATIONAL)).toBe(false);
    expect(oceansitesPasses(null, NONE, OPERATIONAL)).toBe(false);
    expect(oceansitesPasses(null, NONE, NONE)).toBe(true);
  });

  it("Map3D delegates to this rule rather than restating it", () => {
    expect(map3d).toContain("oceansitesPassesRule(f?.properties, oceansitesNetworkFilters, oceansitesStatusFilters)");
  });

  it("keeps flyToLayer's zero-match bail-out, so an empty filter never zooms to nothing", () => {
    expect(map3d).toMatch(/if\s*\(!filtered\.length\)\s*return;/);
  });
});

describe("OceanSITES status filter — every locale", () => {
  const locales = fs.readdirSync(LOCALES).filter(d =>
    fs.statSync(path.join(LOCALES, d)).isDirectory());

  it("discovers more than one locale, or this suite proves nothing", () => {
    expect(locales.length).toBeGreaterThan(1);
  });

  it.each(locales)("%s has every filter label, translated", (loc) => {
    const f = JSON.parse(read(path.join(LOCALES, loc, "panels.json")))?.filters?.oceansites;
    expect(f, `${loc} has no filters.oceansites block`).toBeTruthy();
    expect(f.statusHeader, `${loc} statusHeader`).toBeTruthy();
    expect(f.networkHeader, `${loc} networkHeader`).toBeTruthy();
    for (const d of OCEANSITES_STATUS_DEFS) {
      const key = d.labelKey.split(".").pop()!;
      expect(f.status?.[key], `${loc} missing status.${key}`).toBeTruthy();
      // the gloss is ours and must be translated; the SOURCE WORD stays English
      expect(f.status[key]).toContain(d.key);
    }
    if (loc !== "en") {
      const en = JSON.parse(read(path.join(LOCALES, "en", "panels.json"))).filters.oceansites;
      expect(f.statusHeader, `${loc} statusHeader is an English stub`).not.toBe(en.statusHeader);
    }
  });
});

describe("OceanSITES status filter — reset and badge wiring", () => {
  const controls = code(read(path.join(SRC, "components/Map3DControls.tsx")));
  const section  = code(read(path.join(SRC, "components/controls/sections/SensorsSection.tsx")));

  it("counts towards the active-filter badge", () => {
    expect(controls).toContain("oceansitesStatusFilters.size > 0");
  });

  it("is captured in the undo snapshot, so Clear all can be undone", () => {
    expect(controls).toMatch(/oceansitesStatusFilters:\s*new Set\(oceansitesStatusFilters\)/);
  });

  it("the per-layer reset link clears the status Set too, not only the network one", () => {
    const reset = section.slice(section.indexOf("FilterResetLink"), section.indexOf("OCEANSITES_NETWORK_DEFS.map"));
    expect(reset).toContain("oceansitesStatusFilters.forEach(toggleOceansitesStatusFilter)");
    expect(reset).toContain("oceansitesStatusFilters.size > 0");
  });

  it("the network filter still exists — this is an addition, not a replacement", () => {
    expect(OCEANSITES_NETWORK_DEFS.length).toBeGreaterThan(1);
    expect(section).toContain("toggleOceansitesNetworkFilter");
  });
});
