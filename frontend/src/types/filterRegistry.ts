// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import type { MapStore, FilterSetKey } from "../store/mapStore";
import { useMapStore } from "../store/mapStore";
import { AssertComplete, AssertDisjoint } from "./layerRegistry";
import { VENT_STATUS_VALUES, CLAIM_RISK_VALUES } from "./layers";

/**
 * Every `Set<string>` store field a share link is allowed to carry.
 *
 * ⛔ `exportCheckedLayers` is the one deliberate exclusion: it is Export-panel
 * UI state (which rows are ticked for the next download), not a map filter. A
 * share link that reproduced it would let a *viewer's* click set silently
 * reappear on whoever opens the link next — the wrong side of a link boundary.
 */
export const SHAREABLE_FILTER_FIELDS = [
  "hiddenContractors",
  "ventStatusFilters",
  "argoAlarmFilters",
  "claimRiskFilters",
  "iucnFilters",
  "noiseRiskFilters",
  "chessPhylumFilters",
  "oceansitesNetworkFilters",
  "oceansitesStatusFilters",
  "cableSourceFilters",
  "arcticRiverSourceFilters",
  "methaneSeepsFeatureTypeFilters",
  "thawTypeFilters",
  "thawCategoryFilters",
  "permafrostSourceFilters",
  "fireConfidenceFilters",
  "oncEovFilters",
  "tailingsRiskFilters",
  "tailingsStatusFilters",
  "deepdataStationContractorFilters",
  "wodDecadeFilters",
  "mementoGasFilters",
  "mementoDecadeFilters",
  "geotracesDecadeFilters",
  "mosaicDecadeFilters",
  "hydrophoneSourceFilters",
  "hydrophoneStatusFilters",
  "hydrophoneDepthFilters",
  "aisShipTypeFilters",
  "aisFlagFilters",
  "offshoreActivityFilters",
  "offshoreActivityCountryFilters",
  "cascadeDecadeFilters",
] as const;

export type ShareableFilterField = (typeof SHAREABLE_FILTER_FIELDS)[number];

export const FILTER_OPT_OUT_FIELDS = [
  "exportCheckedLayers",
  // `Set<LayerId>` structurally satisfies the `Set<string>` mapped-type test
  // below (method bivariance), so `activeLayers` shows up in `FilterSetKey`
  // even though it is the layer selection itself — carried in the envelope's
  // `l`, with its own whole-list-rejects rule, never as an `f` entry.
  "activeLayers",
] as const;
type OptOutFilterField = (typeof FILTER_OPT_OUT_FIELDS)[number];

// Compile-time guard: a `Set<string>` field added to MapStore that is named in
// neither list above fails the build here, naming the offending field — the
// same mechanism `abyssal-add-a-layer` already relies on for layer registries,
// generalised to a non-LayerId universe (see layerRegistry.ts).
const _filterRegistryComplete: AssertComplete<ShareableFilterField, OptOutFilterField, FilterSetKey> = true;
const _filterRegistryDisjoint: AssertDisjoint<ShareableFilterField, OptOutFilterField, FilterSetKey> = true;
void _filterRegistryComplete;
void _filterRegistryDisjoint;


/**
 * Filter fields whose values are a CLOSED vocabulary this codebase owns and
 * has changed at least once. Everything else on the shareable list draws its
 * values from the data (contractor names, flag states, phyla) — there is no
 * list to check those against, and a value missing from today's data is a
 * legitimate "matches nothing right now", not a stale link.
 *
 * ⛔ Why this exists: on 2026-09-21 the vent vocabulary changed from the
 * invented "Active"/"Inactive"/"Extinct" to InterRidge's own strings. A link
 * shared before that date still carries the old words, and `has()` against the
 * new ones matches nothing — the layer reads as toggled on and empty, which is
 * indistinguishable from an outage. A retired value must drop out of the link,
 * never blank a layer.
 */
const CLOSED_VOCABULARIES: Partial<Record<ShareableFilterField, readonly string[]>> = {
  ventStatusFilters: VENT_STATUS_VALUES,
  claimRiskFilters: CLAIM_RISK_VALUES,
};

const SHAREABLE_SET: ReadonlySet<string> = new Set(SHAREABLE_FILTER_FIELDS);

export function isShareableFilterField(key: string): key is ShareableFilterField {
  return SHAREABLE_SET.has(key);
}

/**
 * Build the `f` payload from live store state: only NON-EMPTY sets, so a link
 * with one active filter doesn't drag 33 empty-array keys along for the ride.
 */
export function collectShareableFilters(state: MapStore): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const key of SHAREABLE_FILTER_FIELDS) {
    const value = state[key] as Set<string>;
    if (value.size > 0) out[key] = [...value];
  }
  return out;
}

/**
 * Validate a decoded `f` payload and apply it to the live store.
 *
 * An unknown key here is dropped rather than rejecting the whole payload —
 * unlike the layer list, a stray filter field can't turn "no filter" into
 * "wrong filter"; the worst case is one ignored key. A malformed VALUE
 * (anything but an array of strings) drops that one field the same way.
 *
 * Values are checked too, for the fields in `CLOSED_VOCABULARIES`: a value the
 * vocabulary no longer contains is dropped, and a field left with no surviving
 * value is skipped entirely so the store default stands.
 */
export function applyShareableFilters(payload: Record<string, unknown>): void {
  const patch: Partial<MapStore> = {};
  for (const [key, value] of Object.entries(payload)) {
    if (!isShareableFilterField(key)) continue;
    if (!Array.isArray(value) || !value.every((v) => typeof v === "string")) continue;
    let values = value as string[];
    const vocabulary = CLOSED_VOCABULARIES[key];
    if (vocabulary) {
      values = values.filter((v) => vocabulary.includes(v));
      // Every value the link carried is retired. Leaving the field out of the
      // patch keeps the store's own default, which is the visible state — the
      // link loses its filter, and the reader still sees the layer.
      if (values.length === 0) continue;
    }
    (patch as Record<string, unknown>)[key] = new Set(values);
  }
  if (Object.keys(patch).length > 0) useMapStore.setState(patch);
}
