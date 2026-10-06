// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
/**
 * Every deck.gl layer the map draws must resolve to a toggle that has an
 * `order_idx`, or be on the explicit "always on top" list below.
 *
 * ⛔ WHY. Map3D sorts `layersRaw` by `order_idx` of `toggleIdForDeckLayer(layer.id)`
 * and sends an unknown id to 9999 — the very top. The array position a layer is
 * written at is therefore irrelevant: the 2026-06-19 change "render WOA/oxygen
 * behind layers" moved the WOA and oxygen bitmaps to the FRONT of the array and
 * changed nothing, because the order_idx sort (added 2026-05-03) put them back
 * on top. Seen on production 2026-10-06: the WOA field washed out the MEMENTO dots.
 * Nothing errors — the layer just sits above everything it should sit under.
 *
 * ⚠️ Two halves, because each alone has a hole:
 *  1. realistic ids (the shape the code really emits, per-slice suffix included)
 *     are driven through the real `toggleIdForDeckLayer` — catches a prefix
 *     that stops matching;
 *  2. the layer constructors are READ from the source and every id found is
 *     checked — catches the next layer someone adds and forgets to register.
 *     Same idea as `feature-id-chains-agree`: the test discovers the list, it
 *     does not restate it.
 */

import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

import { LAYER_DEFAULTS, toggleIdForDeckLayer } from "../utils/layerConfig";
import { toLf } from "./sliceSource";

const ORDER = new Map(LAYER_DEFAULTS.map((l) => [l.id, l.order_idx]));

describe("field layers (sliced bitmaps and hex views) resolve to their toggle", () => {
  // The ids exactly as Map3D builds them: `<toggle>-bitmap-<variable>-<depth|decade>-<slice>`.
  const REAL_IDS: Array<[string, string]> = [
    ["woa-climatology-bitmap-oxygen-500-0", "woa-climatology"],
    ["woa-climatology-bitmap-temperature-0-53", "woa-climatology"],
    ["woa-hexes", "woa-climatology"],
    ["oxygen-deox-bitmap-trend-200-17", "oxygen-deox"],
    ["oxygen-hexes", "oxygen-deox"],
    ["ocean-carbon-bitmap-dic-100-5", "ocean-carbon"],
    ["ocean-carbon-hexes", "ocean-carbon"],
    ["ocean-co2-surface-bitmap-fco2-2010-9", "ocean-co2-surface"],
    ["ocean-co2-surface-hexes", "ocean-co2-surface"],
    ["ocean-acidification-bitmap-omega_a-0-3", "ocean-acidification"],
    ["ocean-acidification-hexes", "ocean-acidification"],
  ];

  it.each(REAL_IDS)("%s -> %s, and that toggle has an order_idx", (deckId, toggle) => {
    expect(toggleIdForDeckLayer(deckId)).toBe(toggle);
    expect(ORDER.has(toggle), `${toggle} missing from LAYER_DEFAULTS`).toBe(true);
  });

  it("a prefix does not swallow a sibling layer's tiles", () => {
    expect(toggleIdForDeckLayer("ocean-carbon-bitmap-dic-0-0")).toBe("ocean-carbon");
    expect(toggleIdForDeckLayer("ocean-co2-surface-bitmap-fco2-2010-0")).toBe("ocean-co2-surface");
    expect(toggleIdForDeckLayer("ocean-nutrients-model-bitmap-chl-2026-08-3")).toBe("ocean-nutrients-model");
  });
});

// Overlays that are drawn on top ON PURPOSE: AOI tools, per-feature focus
// overlays and text labels. They are not data layers with an order_idx, so the
// 9999 fallback is the intended behaviour. A prefix here is matched against the
// static part of the id. Anything NOT listed must resolve to a LAYER_DEFAULTS id.
const ALWAYS_ON_TOP: Array<[string, string]> = [
  ["aoi-", "area-of-interest selection tools, appended after the sort anyway"],
  ["plume-", "Argo/contract plume overlays, shown only for the focused feature"],
  ["argo-drift-", "drift trail of the focused Argo float"],
  ["argo-sensor-fault-ring", "ring marking a faulty float, must stay visible over the float dots"],
  ["vessel-track-", "track of the vessel in focus"],
  ["eez-labels", "text labels, readable only on top (unchanged behaviour)"],
  ["ocean-currents-arrows", "reduced-motion fallback of the animated currents canvas overlay (unchanged behaviour)"],
];

// Layer constructors outside the main map: they feed a different, unsorted deck.
const NOT_THE_MAIN_MAP = new Set(["ImpactReportMap.tsx"]);

function sourceFiles(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) return e.name === "__tests__" ? [] : sourceFiles(p);
    return /\.tsx?$/.test(e.name) && !NOT_THE_MAIN_MAP.has(e.name) ? [p] : [];
  });
}

// `new XLayer({ id: "..." | `...${v}...` ` — comments between `{` and `id` allowed.
const WITH_ID =
  /new\s+\w+Layer(?:<[^>(]*>)?\(\s*\{\s*(?:\/\/[^\n]*\n\s*)*id:\s*(`[^`]*`|"[^"]*"|'[^']*')/g;
const ANY_CTOR = /new\s+\w+Layer(?:<[^>(]*>)?\(/g;
// `new BitmapLayer(props, {...})` is the renderSubLayers form: the id comes from the parent.
const SUBLAYER = /new\s+\w+Layer(?:<[^>(]*>)?\(\s*props\s*,/g;

interface Emitted { id: string; file: string }

function emittedIds(): { ids: Emitted[]; unreadable: string[] } {
  const root = path.resolve(__dirname, "..");
  const ids: Emitted[] = [];
  const unreadable: string[] = [];
  for (const file of sourceFiles(root)) {
    const src = toLf(fs.readFileSync(file, "utf8"));
    const withId = [...src.matchAll(WITH_ID)];
    for (const m of withId) {
      // The static part is all we can know; a variable part is stood in for by a
      // realistic suffix so prefix rules are exercised the way a real id would.
      const raw = m[1].slice(1, -1);
      const cut = raw.indexOf("${");
      ids.push({ id: cut === -1 ? raw : `${raw.slice(0, cut)}SAMPLE-0`, file: path.basename(file) });
    }
    const all = [...src.matchAll(ANY_CTOR)].length;
    const sub = [...src.matchAll(SUBLAYER)].length;
    if (all !== withId.length + sub) {
      unreadable.push(`${path.basename(file)}: ${all} constructors, ${withId.length} with a literal id, ${sub} sub-layers`);
    }
  }
  return { ids, unreadable };
}

describe("every layer the map draws is ordered by its toggle's order_idx", () => {
  const { ids, unreadable } = emittedIds();

  it("finds the layers it is meant to guard (a scanner that finds nothing proves nothing)", () => {
    const found = new Set(ids.map((i) => i.id));
    expect([...found].some((i) => i.startsWith("woa-climatology-bitmap-"))).toBe(true);
    expect(found.has("woa-hexes")).toBe(true);
    expect(found.has("memento-hexes")).toBe(true);
    expect(ids.length).toBeGreaterThan(60);
  });

  it("every constructor has an id this test can read (or is a renderSubLayers child)", () => {
    // A layer given `id: someVariable` would slip past the check below unseen.
    expect(unreadable).toEqual([]);
  });

  it("no layer falls through to 9999 unless it is on the always-on-top list", () => {
    const stray = ids
      .filter(({ id }) => !ORDER.has(toggleIdForDeckLayer(id)))
      .filter(({ id }) => !ALWAYS_ON_TOP.some(([prefix]) => id.startsWith(prefix)))
      .map(({ id, file }) => `${id} (${file})`);
    // A name here means: that layer sorts at 9999, i.e. on top of every point layer,
    // whatever its order_idx says. Map it in DECK_TO_TOGGLE (exact id) or
    // DECK_ID_PREFIX_TO_TOGGLE (id with a variable part) in utils/layerConfig.ts.
    expect([...new Set(stray)]).toEqual([]);
  });

  it("the always-on-top list holds no stale entry", () => {
    for (const [prefix] of ALWAYS_ON_TOP) {
      expect(ids.some(({ id }) => id.startsWith(prefix)), `${prefix} is emitted by nothing`).toBe(true);
    }
  });

  it("an always-on-top id really is unmapped (otherwise it belongs in the registry, not on the list)", () => {
    for (const { id } of ids) {
      if (!ALWAYS_ON_TOP.some(([prefix]) => id.startsWith(prefix))) continue;
      expect(ORDER.has(toggleIdForDeckLayer(id)), `${id} now resolves to a toggle`).toBe(false);
    }
  });
});

// ── Mapping is half of it: the NUMBER must put a field under the dots ────────
//
// Once the ids resolve, order_idx is what decides. The four ambient fields were
// numbered 2075-2082, i.e. above memento/geotraces/wod-oxygen, a mistake nobody
// could see while the unmapped ids forced them to 9999 anyway.

/** Layer ids of one subgroup of the admin panel's mirror of the left menu. */
function menuGroup(name: string): string[] {
  const file = path.resolve(__dirname, "../../../admin-panel/src/layerCategories.ts");
  const src = toLf(fs.readFileSync(file, "utf8"));
  const m = src.match(new RegExp(`group:\\s*"${name}",\\s*ids:\\s*\\[([^\\]]*)\\]`));
  if (!m) throw new Error(`menu group not found in layerCategories.ts: ${name}`);
  return [...m[1].matchAll(/"([a-z0-9-]+)"/g)].map((x) => x[1]);
}

describe("ambient fields sit under the point layers", () => {
  const { ids } = emittedIds();
  // A field is a layer that draws a sliced bitmap or a baked raster: those ids carry
  // `-bitmap-` / `-raster`. Derived from what the code emits, not restated here.
  const fields = new Set(
    ids.filter(({ id }) => /-(bitmap|raster)(-|$)/.test(id)).map(({ id }) => toggleIdForDeckLayer(id)),
  );
  // The menu subgroups that mix fields with point layers (argo lives in Sensors).
  const inMenu = [...menuGroup("Ocean Climatology"), ...menuGroup("Sensors & Monitoring")];
  const points = inMenu.filter((id) => !fields.has(id));

  it("finds the four fields and a real list of point layers", () => {
    for (const f of ["woa-climatology", "oxygen-deox", "ocean-carbon", "ocean-co2-surface"]) {
      expect(fields.has(f), `${f} emits no bitmap/raster id`).toBe(true);
    }
    for (const p of ["memento", "geotraces", "wod-oxygen", "argo", "arctic-rivers", "methane-seeps"]) {
      expect(points, `${p} not among the point layers`).toContain(p);
    }
  });

  it("every point layer is registered, so the comparison below cannot be skipped", () => {
    expect(points.filter((id) => !ORDER.has(id))).toEqual([]);
  });

  it.each(["woa-climatology", "oxygen-deox", "ocean-carbon", "ocean-co2-surface"])(
    "%s is below every point layer of Ocean Climatology and Sensors",
    (field) => {
      const idx = ORDER.get(field)!;
      const above = points.filter((p) => ORDER.get(p)! <= idx).map((p) => `${p}=${ORDER.get(p)}`);
      expect(above, `${field}=${idx} is not under: ${above.join(", ")}`).toEqual([]);
    },
  );

  it("any sliced-bitmap field, present or future, is under every point layer", () => {
    const bitmapFields = new Set(
      ids.filter(({ id }) => /-bitmap-/.test(id)).map(({ id }) => toggleIdForDeckLayer(id)),
    );
    const bad = [...bitmapFields].filter((f) => points.some((p) => ORDER.get(p)! <= ORDER.get(f)!));
    expect(bad).toEqual([]);
  });
});
