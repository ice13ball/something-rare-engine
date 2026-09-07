#!/usr/bin/env node
// ─────────────────────────────────────────────────────────────────────────────
// Layer parity checker  (Tier 1)
//
// Adding a new data layer touches ~17 spots across 8 files. Three of those registries are keyed by the
// same kebab-case LayerId, so we can mechanically prove a layer was wired into
// all of them. This catches the two misses that actually break UX:
//
//   1. A layer in LAYER_CONFIGS / LAND_LAYER_CONFIGS with no flyConfigs entry
//      → the "locate" button (flyToLayer) zooms nowhere. MANDATORY for all.
//   2. A layer with no SearchBar entry → users can't find it by name.
//      EXPECTED for most, but legitimately N/A for grids / MVT-tile / raster
//      coverage layers that have no per-feature names to search. Those are
//      listed in SEARCH_EXEMPT below, each with a reason.
//
// The legend registry (LAYER_STRUCT in LegendPanel.tsx) is deliberately keyed
// by a *different* camelCase content-key namespace (it indexes legend.json),
// so it can't be set-diffed against LayerId — that's Tier 2 and out of scope.
//
// Dependency-free, mirrors scripts/check-i18n-keys.sh. Run:
//   node scripts/check-layer-parity.mjs        (or: npm run check:layers)
// Exit code 1 on any FAIL so CI can gate on it.
// ─────────────────────────────────────────────────────────────────────────────
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const read = (p) => readFileSync(resolve(root, p), "utf8");

// Layers that intentionally have no SearchBar entry. Each is a grid, MVT-tile,
// or raster-coverage layer with no searchable per-feature names. If you add a
// new non-searchable layer, add it here WITH a reason — don't delete the check.
const SEARCH_EXEMPT = new Map([
  ["apeis", "named APEI polygons, but searched via the contracts/area flow, not SearchBar"],
  ["noise-risk", "2°×2° risk grid — no per-feature names"],
  ["monitoring-density", "aggregation grid — no per-feature names"],
  ["offshore-activities", "MVT tile layer — features not held client-side to index"],
  ["mining-footprints", "raster/polygon coverage — no per-feature names"],
  ["forest-loss", "raster coverage — no per-feature names"],
  ["surface-water", "raster coverage — no per-feature names"],
  ["carbon-flux", "raster coverage — no per-feature names"],
  ["soil-carbon", "raster coverage — no per-feature names"],
  ["water-risk", "sub-basin risk polygons — no searchable names"],
  ["kbas", "polygon coverage layer — not indexed for name search"],
]);

const KEBAB = "[a-z][a-z0-9-]*";

/** All `id: "..."` literals in a layer-config source file. */
function idsFromConfig(file) {
  const re = new RegExp(`\\bid:\\s*"(${KEBAB})"`, "g");
  return new Set([...read(file).matchAll(re)].map((m) => m[1]));
}

/** Quoted-kebab keys inside a `{ ... }` block, matched as `"key": {`. */
function blockKeys(block) {
  const re = new RegExp(`"(${KEBAB})":\\s*\\{`, "g");
  return [...block.matchAll(re)].map((m) => m[1]);
}

/**
 * All fly targets in Map3D.tsx. A layer's "locate" button is satisfied by
 * EITHER source:
 *   (a) the flyConfigs useMemo  — feature-based layers (fly to a feature)
 *   (b) the rasterViews map     — raster/MVT-tile layers with no features
 *                                 (fly to a preset viewport instead)
 * Miss both and flyToLayer zooms nowhere.
 */
function flyTargetKeys() {
  const src = read("src/components/Map3D.tsx");
  const keys = new Set();

  // (a) flyConfigs useMemo — closes at the first `}), [` (deps array).
  const fStart = src.indexOf("const flyConfigs: Record<string, FlyConfig>");
  if (fStart === -1) throw new Error("Could not locate flyConfigs declaration in Map3D.tsx");
  const fCloseRel = src.slice(fStart).search(/\n\s*\}\),\s*\[/);
  if (fCloseRel === -1) throw new Error("Could not find flyConfigs useMemo close");
  for (const k of blockKeys(src.slice(fStart, fStart + fCloseRel))) keys.add(k);

  // (b) rasterViews preset-viewport map — closes at the first `};`.
  const rStart = src.indexOf("const rasterViews:");
  if (rStart === -1) throw new Error("Could not locate rasterViews declaration in Map3D.tsx");
  const rCloseRel = src.slice(rStart).indexOf("};");
  if (rCloseRel === -1) throw new Error("Could not find rasterViews close");
  for (const k of blockKeys(src.slice(rStart, rStart + rCloseRel))) keys.add(k);

  return keys;
}

/** All `layerId: "..."` literals in SEARCH_CONFIGS. */
function searchLayerIds() {
  const re = new RegExp(`\\blayerId:\\s*"(${KEBAB})"`, "g");
  return new Set([...read("src/components/SearchBar.tsx").matchAll(re)].map((m) => m[1]));
}

const sea = idsFromConfig("src/types/layers.ts");
const land = idsFromConfig("src/types/landLayers.ts");
const universe = new Set([...sea, ...land]);
const fly = flyTargetKeys();
const search = searchLayerIds();

const diff = (a, b) => [...a].filter((x) => !b.has(x)).sort();
let failed = false;
const fail = (msg) => { failed = true; console.error(`✗ ${msg}`); };
const ok = (msg) => console.log(`✓ ${msg}`);

console.log(`Layer parity check — ${universe.size} layers (${sea.size} sea + ${land.size} land)\n`);

// 1. Every layer must be flyable.
const missingFly = diff(universe, fly);
if (missingFly.length) fail(`flyConfigs: missing entries for: ${missingFly.join(", ")}\n   → "locate" button will zoom nowhere. Add a flyConfigs entry in Map3D.tsx.`);
else ok(`flyConfigs: all ${universe.size} layers have a fly target`);

// Orphan fly configs (key with no matching layer) — likely a typo or stale entry.
const orphanFly = diff(fly, universe);
if (orphanFly.length) fail(`flyConfigs: keys with no matching layer id: ${orphanFly.join(", ")}\n   → typo, or a layer removed from LAYER_CONFIGS but left in flyConfigs.`);

// 2. Every layer should be searchable unless explicitly exempt.
const missingSearch = diff(universe, search).filter((id) => !SEARCH_EXEMPT.has(id));
if (missingSearch.length) fail(`SearchBar: missing SEARCH_CONFIGS entries for: ${missingSearch.join(", ")}\n   → users can't find these by name. Add to SEARCH_CONFIGS, or to SEARCH_EXEMPT here with a reason.`);
else ok(`SearchBar: all searchable layers covered (${SEARCH_EXEMPT.size} exempt by design)`);

// Stale exemptions: layer is exempt here but actually IS in SearchBar.
const staleExempt = [...SEARCH_EXEMPT.keys()].filter((id) => search.has(id)).sort();
if (staleExempt.length) console.warn(`! SEARCH_EXEMPT lists layers that are now searchable (remove them): ${staleExempt.join(", ")}`);

// Search entries pointing at a non-existent layer.
const orphanSearch = diff(search, universe);
if (orphanSearch.length) fail(`SearchBar: layerId with no matching layer: ${orphanSearch.join(", ")}\n   → typo in SEARCH_CONFIGS layerId.`);

console.log();
if (failed) { console.error("Layer parity FAILED."); process.exit(1); }
console.log("Layer parity OK.");
