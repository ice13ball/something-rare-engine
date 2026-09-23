// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

/**
 * Which per-layer DISPLAY selectors a share link carries — the depth, decade,
 * variable and field/hexes switches that decide what a layer actually shows.
 *
 * ⚠️ Measured on production 2026-09-14, and the reason this file exists: a link
 * that carried a WOA panel at 2000 m rendered the coloured field behind it from
 * `oxygen/500.png` — the RECIPIENT's default. The panel was the sender's, the
 * map underneath it was not, and nothing said so.
 *
 * ⛔ Two registries, two universes, on purpose. `filterRegistry.ts` governs
 * `Set<string>` filters (`FilterSetKey`); this one governs scalars
 * (`ScalarStateKey`). A field seen by neither is a field nobody decided about —
 * which is exactly what happened to `firesNearMiningOnly`, a filter that is a
 * plain boolean and so fell through the gap between them for months.
 */
import { useMapStore } from "../store/mapStore";
import type { MapStore, ScalarStateKey } from "../store/mapStore";
import type { AssertComplete, AssertDisjoint } from "./layerRegistry";

/**
 * How a value arriving from a stranger's URL is checked.
 *
 * ⛔ `slug` is not cosmetic. `woaVariable`, `carbonVariable`, `co2Variable` and
 * `marineCarbonVariable` are interpolated straight into a request PATH
 * (`/api/v1/woa/${woaVariable}/${woaDepth}.png`). Their legal values live in
 * the backend's `/meta` response, so the client cannot hold an allow-list — but
 * it can and must refuse anything that is not a plain lowercase token, or a
 * link decides what path we fetch.
 */
export type DisplayCheck = "slug" | "depth" | "index" | "boolean" | "isoDate";

export interface DisplayField {
  /** The layer this selector belongs to. Documentation, and it makes the list auditable. */
  layer: string;
  /**
   * What the store starts with. A link carries a field ONLY when the sender's
   * value differs — otherwise every link would haul all 32 fields around for
   * nothing. ⛔ Kept honest by a test that reads the real initial store state.
   */
  default: string | number | boolean | null;
  /** Exactly one of these. `values` for a closed union, `check` for everything else. */
  values?: readonly string[];
  check?: DisplayCheck;
}

// ⛔ No helper function here, deliberately. A `const F = (...) => ({...})`
// wrapper reads better and WIDENS every `values` tuple to `readonly string[]`
// — which silently disarmed the exhaustiveness guard at the bottom of this
// file: `infer V` came back as `string`, so `Exclude<union, string>` was always
// `never` and dropping a literal compiled cleanly. Caught by sabotaging it.
// Plain object literals under `as const` are what keep the tuples literal.

export const DISPLAY_FIELDS = {
  woaVariable: { layer: "woa-climatology", default: "oxygen", check: "slug" },
  woaDepth: { layer: "woa-climatology", default: 500, check: "depth" },
  woaDisplayMode: { layer: "woa-climatology", default: "field", values: ["field", "hexes"] },
  oxygenView: { layer: "oxygen-deox", default: "change", values: ["recent", "change"] },
  oxygenDepth: { layer: "oxygen-deox", default: 500, check: "depth" },
  oxygenDisplayMode: { layer: "oxygen-deox", default: "field", values: ["field", "hexes"] },
  carbonVariable: { layer: "ocean-carbon", default: "dic", check: "slug" },
  carbonDepth: { layer: "ocean-carbon", default: 0, check: "depth" },
  carbonDisplayMode: { layer: "ocean-carbon", default: "field", values: ["field", "hexes"] },
  acidificationVariable: { layer: "ocean-acidification", default: "aragonite", values: ["aragonite", "calcite", "horizon", "horizon-shift"] },
  acidificationDepth: { layer: "ocean-acidification", default: 0, check: "depth" },
  acidificationDisplayMode: { layer: "ocean-acidification", default: "field", values: ["field", "hexes"] },
  marineCarbonVariable: { layer: "marine-carbon", default: "co2_fco2", check: "slug" },
  marineCarbonDepth: { layer: "marine-carbon", default: 0, check: "depth" },
  co2Variable: { layer: "ocean-co2-surface", default: "fco2", check: "slug" },
  co2Decade: { layer: "ocean-co2-surface", default: 5, check: "index" },
  co2DisplayMode: { layer: "ocean-co2-surface", default: "field", values: ["field", "hexes"] },
  chiDisplayMode: { layer: "cumulative-human-impact", default: "field", values: ["field", "hexes"] },
  vmeView: { layer: "vme-suitability", default: "suitability", values: ["suitability", "uncertainty"] },
  seabedDisplayMode: { layer: "seabed-substrate", default: "field", values: ["field", "hexes"] },
  mementoGas: { layer: "memento", default: "n2o", values: ["ch4", "n2o"] },
  mementoDisplayMode: { layer: "memento", default: "dots", values: ["dots", "hexes"] },
  geotracesElement: { layer: "geotraces", default: "fe", values: ["mn", "fe", "co", "ni", "cu"] },
  geotracesDisplayMode: { layer: "geotraces", default: "dots", values: ["dots", "hexes"] },
  mosaicVariable: { layer: "mosaic-sediment", default: "toc", values: ["toc", "tn", "d13c", "d14c"] },
  mosaicDisplayMode: { layer: "mosaic-sediment", default: "dots", values: ["dots", "hexes"] },
  arcticCatchmentsVariable: { layer: "arctic-catchments", default: "ocs_mean", values: ["ocs_mean", "oc_tot", "runoff_mean", "pf_frac", "t_2m_mean"] },
  cascadeVariable: { layer: "arctic-sediment-carbon", default: "oc", values: ["oc", "tn", "d13c", "d14c"] },
  cascadeDisplayMode: { layer: "arctic-sediment-carbon", default: "field", values: ["field", "stations"] },
  marhysView: { layer: "marhys", default: "points", values: ["points", "density"] },
  currentsDepth: { layer: "ocean-currents", default: "surface", values: ["surface", "1000m"] },
  // null means "latest available". A sender parked on a specific day is saying
  // something a recipient cannot reconstruct, so it travels.
  currentsDate: { layer: "ocean-currents", default: null, check: "isoDate" },
  // ⚠️ Semantically a FILTER, carried here for a mechanical reason: `f` holds
  // arrays of strings and this is a boolean, so the filter registry's universe
  // (`Set<string>` fields) cannot see it. It changes which fires the recipient
  // is shown, which is the only test that decides whether a link must carry it.
  firesNearMiningOnly: { layer: "fires", default: false, check: "boolean" },
} as const satisfies Record<string, DisplayField>;

/** Widened alias for lookup by a plain string — same reason as OPENABLE_LOOKUP. */
export const DISPLAY_LOOKUP: Record<string, DisplayField> = DISPLAY_FIELDS;

/**
 * Scalars a link deliberately does NOT carry, each with its reason.
 * ⛔ None of these was guessed — every one is UI state that says nothing about
 * what the map shows.
 */
export const DISPLAY_OPT_OUT_FIELDS = [
  // An animation controller, not a selector. `currentsDate` already carries the
  // moment the sender was looking at; arriving with the animation RUNNING would
  // walk the recipient off that moment within a second of opening the link.
  "currentsPlaying",
  // Panel and overlay chrome — open/closed, not what is on the map.
  "discoveryOpen",
  "exportPanelOpen",
  "tutorialReady",
  // Which legend entry is scrolled to in the docs panel.
  "legendFocusLayer",
  // The next download's file format. A link that set it would change what the
  // recipient's own export produces, which is their business, not the sender's.
  "exportFormat",
  // AOI draw-tool interaction state — mid-gesture, not a view.
  "selectionMode",
  // Mobile panel-auto-close counter, pure plumbing.
  "mapTapCount",
] as const;

type Covered = keyof typeof DISPLAY_FIELDS;
type OptedOut = (typeof DISPLAY_OPT_OUT_FIELDS)[number];

export const _displayIsComplete: AssertComplete<Covered, OptedOut, ScalarStateKey> = true;
export const _displayIsDisjoint: AssertDisjoint<Covered, OptedOut, ScalarStateKey> = true;

/**
 * ⛔ Every closed union must be listed in full.
 *
 * A `values` list missing one literal does not fail anywhere obvious: the field
 * still works, and only the ONE value nobody listed is silently dropped from
 * links — the rarest option becomes the unshareable one, and it looks like the
 * link just didn't carry anything. This resolves to the missing literal, by
 * name, at compile time.
 */
// ⛔ Collects the MISSING literals, then demands the collection be empty.
// The first attempt mapped each field to `true | <missing>` and unioned those —
// which always contains `true`, so `= true` always compiled and the guard could
// not fail. Only found by sabotaging it. Same shape as `AssertComplete`: resolve
// to `true` when there is nothing left over, otherwise to the leftovers.
type MissingEnumValues = {
  [K in Covered]: (typeof DISPLAY_FIELDS)[K] extends { values: readonly (infer V)[] }
    ? Exclude<MapStore[K], V>
    : never;
}[Covered];

export const _displayEnumsAreComplete: [MissingEnumValues] extends [never]
  ? true
  : MissingEnumValues = true;

/** Shape rules for values that have no closed list. See `DisplayCheck`. */
const CHECKS: Record<DisplayCheck, (v: unknown) => boolean> = {
  // ⛔ Security-relevant, not cosmetic: these land in a request PATH.
  slug: (v) => typeof v === "string" && /^[a-z0-9_]{1,24}$/.test(v),
  // A depth in metres. Not an allow-list — the legal depths come from the
  // backend's /meta and differ per variable, so the client cannot hold them.
  // This is a sanity bound (the deepest ocean is ~10,935 m); a value that is
  // in range but not offered simply 404s the tile, which the existing
  // "layer unavailable" notice already reports.
  depth: (v) => typeof v === "number" && Number.isInteger(v) && v >= 0 && v <= 11000,
  // A position in a short list the backend publishes (e.g. which decade).
  index: (v) => typeof v === "number" && Number.isInteger(v) && v >= 0 && v <= 99,
  boolean: (v) => typeof v === "boolean",
  isoDate: (v) => typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v),
};

export function isValidDisplayValue(field: string, value: unknown): boolean {
  const cfg = DISPLAY_LOOKUP[field];
  if (!cfg) return false;
  if (cfg.values) return typeof value === "string" && cfg.values.includes(value);
  return cfg.check ? CHECKS[cfg.check](value) : false;
}

/**
 * The selectors the sender changed — and only those.
 *
 * ⛔ Emitting all 32 unconditionally would put ~600 characters of defaults into
 * every link, and would also make a link freeze the recipient's map at the
 * sender's defaults FOREVER: a value later changed in the code would be
 * overridden by every old link still in circulation. Carrying only differences
 * means a link says what the sender chose, not what the app happened to start with.
 */
export function collectShareableDisplay(state: MapStore): Record<string, string | number | boolean> {
  const out: Record<string, string | number | boolean> = {};
  for (const [field, cfg] of Object.entries(DISPLAY_FIELDS) as Array<[Covered, DisplayField]>) {
    const value = state[field] as unknown;
    if (value === cfg.default) continue;
    if (value === null || value === undefined) continue;
    if (!isValidDisplayValue(field, value)) continue;  // never emit what we would refuse
    out[field] = value as string | number | boolean;
  }
  return out;
}

/**
 * Put a link's selectors into the store. Mirrors `applyShareableFilters`, and
 * is called from the same place for the same reason: before first render, so a
 * shared depth is what the very first tile request asks for rather than a
 * second request after a visible flash of the recipient's own default.
 *
 * ⛔ Writes through `setState`, not through the fields' setters. Every one of
 * the 31 setters is a plain `set({ field: value })` (checked, 2026-09-14) and
 * the 32nd — `firesNearMiningOnly` — has no setter at all, only a toggle. A
 * name-mangling `set${Capitalize<field>}` lookup would therefore have to carry
 * an exception for it, and would break silently the day a setter is renamed.
 *
 * Values are re-validated here even though `decodeShareState` already did: this
 * function is exported and nothing stops a future caller from handing it
 * something that never went through the envelope.
 */
export function applyShareableDisplay(payload: Record<string, unknown>): void {
  const patch: Partial<MapStore> = {};
  for (const [key, value] of Object.entries(payload)) {
    if (!isValidDisplayValue(key, value)) continue;
    (patch as Record<string, unknown>)[key] = value;
  }
  if (Object.keys(patch).length > 0) useMapStore.setState(patch);
}
