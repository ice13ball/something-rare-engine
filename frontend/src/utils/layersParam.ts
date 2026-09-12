// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { SEA_LAYER_IDS, type LayerId } from "../types/layers";
import { LAND_LAYER_IDS } from "../types/landLayers";

/**
 * Every layer id that may appear in a `?layers=` URL, sea and land.
 *
 * ⛔ Built from the id lists, NOT from `LAYER_CONFIGS`. `LAYER_CONFIGS` is a
 * shorter list that exists for a different job, and validating against it meant
 * six real, served layers (`wod-oxygen`, `geotraces`, `oxygen-deox`,
 * `ocean-acidification`, `sios-svalbard`, `arctic-catchments`) could not be
 * named in a link at all.
 */
// Exported so any other reader that needs "is this still a real layer id" —
// mapState.ts's own-storage pruning, shareState.ts's link validation — checks
// against the SAME set instead of growing a second, driftable copy.
export const VALID_LAYER_IDS: ReadonlySet<string> = new Set<string>([
  ...SEA_LAYER_IDS,
  ...LAND_LAYER_IDS,
]);

/**
 * Parse a `?layers=` value into the layer set it names.
 *
 * Returns `null` when the parameter should be ignored entirely — the caller
 * then starts up exactly as if no link had been followed.
 *
 * ⛔ ONE unknown token rejects the WHOLE list. The previous behaviour filtered
 * unknown ids out and applied whatever survived, which quietly turned three
 * different things into the same outcome: a typo, a link written against a
 * newer release, and a link naming a layer this build validated against the
 * wrong registry. In every case the reader got a smaller layer set presented as
 * if the author had chosen it. A link is input from outside; it is either
 * understood or it is not acted on.
 *
 * Note the asymmetry with our OWN saved state: an unknown id read back from
 * localStorage is dropped silently, because there it means "a layer we retired
 * since this visitor's last visit" — stale, not hostile.
 */
export function parseLayersParam(raw: string | null): LayerId[] | null {
  if (!raw) return null;

  // Cheap bound before any work: a `?layers=` naming every layer twice is still
  // far under this, so anything longer is not a link we wrote.
  if (raw.length > 2000) return null;

  const tokens = raw.split(",").map(t => t.trim()).filter(Boolean);
  if (tokens.length === 0) return null;

  for (const t of tokens) {
    if (!VALID_LAYER_IDS.has(t)) return null;
  }
  // Duplicates are not an error — the caller builds a Set anyway.
  return tokens as LayerId[];
}

/** Exported for the guard test; not part of the parsing contract. */
export const _VALID_LAYER_ID_COUNT = VALID_LAYER_IDS.size;
