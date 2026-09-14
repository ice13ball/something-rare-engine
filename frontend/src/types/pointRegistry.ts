// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

/**
 * Which layers a link may address by COORDINATE, and what each one needs.
 *
 * ⛔ Deliberately a second registry, not more rows in `openableRegistry.ts`.
 * The two address different things and fail differently: `o` names a record
 * that either exists or is gone, `p` names a spot on a continuous field that
 * always exists and may simply have no measurement. One shape, one validator
 * and one failure message for both would have to lie about one of them.
 *
 * ⭐ The universe here is NOT every LayerId — it is exactly the list of layers
 * `openableRegistry` already refused to address by id. That is the honest
 * question this file answers: "of the layers a link cannot name, which can it
 * still point at?" A layer added tomorrow lands in `OPENABLE` or in
 * `NOT_OPENABLE`; if it lands in the latter, the guard at the bottom of this
 * file forces it into `POINT_LAYERS` or into `NOT_POINT` with a reason.
 */
import type { AssertComplete, AssertDisjoint } from "./layerRegistry";
import { NOT_OPENABLE } from "./openableRegistry";

export interface PointLayer {
  /**
   * The string `DetailPanel` dispatches on. Identical to the layer id for all
   * nine today — written out anyway, because "identical today" is a fact about
   * today, and the whole reason stage 2 needed a registry was that 24 routing
   * keys quietly stopped matching their layer id.
   */
  routingKey: string;
  /**
   * The prefix `Map3D`'s click handler puts in front of the synthetic
   * selection id. ⚠️ NOT always the layer id: `vme-suitability` builds
   * `vme:<lat>,<lon>`. Reproducing the id exactly is what keeps a link-opened
   * panel and a clicked panel from stacking as two panels for one spot.
   */
  idPrefix: string;
  /**
   * The one extra number the panel needs besides the coordinate, named by the
   * `properties` key it arrives under — or null when the coordinate is the
   * whole address.
   *
   * ⛔ Not optional-in-practice: `WoaPointPanel` puts `depth` straight into
   * its query string, so an entry that omits it fetches `depth=undefined` and
   * the panel renders "No data found." — a wrong answer wearing an ordinary
   * empty-result message. An entry missing a required extra is refused, and
   * the refusal is reported.
   */
  extra: "depth" | "decade" | null;
}

/**
 * ⛔ `as const satisfies`, never `Partial<Record<LayerId, …>>`. The latter
 * keeps every LayerId in `keyof`, so the completeness guard below can never go
 * red — that exact mistake shipped in stage 2's first draft and was found only
 * by sabotaging it.
 */
export const POINT_LAYERS = {
  // Depth comes from that layer's own slider in the store and is copied into
  // the selection at click time (`Map3D.tsx`, the `*-hexes` branches).
  "woa-climatology":         { routingKey: "woa-climatology",         idPrefix: "woa-climatology",         extra: "depth"  },
  "oxygen-deox":             { routingKey: "oxygen-deox",             idPrefix: "oxygen-deox",             extra: "depth"  },
  "ocean-carbon":            { routingKey: "ocean-carbon",            idPrefix: "ocean-carbon",            extra: "depth"  },
  "ocean-acidification":     { routingKey: "ocean-acidification",     idPrefix: "ocean-acidification",     extra: "depth"  },
  "marine-carbon":           { routingKey: "marine-carbon",           idPrefix: "marine-carbon",           extra: "depth"  },
  // Surface only — the selector here picks a decade, not a depth.
  "ocean-co2-surface":       { routingKey: "ocean-co2-surface",       idPrefix: "ocean-co2-surface",       extra: "decade" },
  // Coordinate is the whole address; these panels take no selector.
  "cumulative-human-impact": { routingKey: "cumulative-human-impact", idPrefix: "cumulative-human-impact", extra: null     },
  "vme-suitability":         { routingKey: "vme-suitability",         idPrefix: "vme",                     extra: null     },
  // ⚠️ The click handler also stuffs cell_id/suitability/state into the
  // selection. `CoralExposurePanel` reads none of them — every value it shows
  // comes from `/coral-exposure/point` and `/coral-exposure/summary` — so a
  // link that carries only the coordinate opens the identical panel.
  "coral-acid-exposure":     { routingKey: "coral-acid-exposure",     idPrefix: "coral-acid-exposure",     extra: null     },
} as const satisfies Record<string, PointLayer>;

/**
 * Widened alias for lookup by a `string` that is not known to be a key.
 * Indexing `POINT_LAYERS` directly with a plain string fails to compile, and
 * the per-entry literal types are what make the guard below able to fail —
 * same arrangement as `OPENABLE_LOOKUP`.
 */
export const POINT_LOOKUP: Record<string, PointLayer> = POINT_LAYERS;

/**
 * Layers a link may not address at all — neither by id nor by coordinate.
 *
 * ⛔ Every reason below was checked in the code, not assumed. Where the answer
 * is genuinely unknown it says so rather than inventing a tidy one.
 */
export const NOT_POINT = [
  // Clicking these opens nothing: `DetailPanel`'s dispatcher has no branch for
  // them and falls through to "No details available." There is no panel for a
  // link to reopen.
  "bathymetry",
  "ocean-currents",
  "forest-loss",
  "carbon-flux",
  "soil-carbon",
  // A panel exists, but everything it renders comes from the clicked tile's
  // own properties — there is no coordinate query behind it. Carrying those
  // properties in the URL is out of scope (one object would exceed the 4000
  // char cap).
  "seabed-substrate",
  "noise-risk",
  "water-risk",
  "mining-footprints",
  "apeis",
  // `SurfaceWaterPanel()` takes no arguments at all — it is fixed explanatory
  // text. A coordinate would address nothing in it.
  "surface-water",
  // ⚠️ The one genuinely open case. `MonitoringDensityPanel` DOES query by
  // coordinate, but it also renders `point_count` and `source_count` straight
  // from the tile's properties, and whether `/monitoring-density/cell`'s
  // `total` is the same number as the tile's `point_count` is **nieustalone**.
  // Carrying only a coordinate would render those two rows as 0 and say
  // nothing about it.
  "monitoring-density",
] as const;

/**
 * ⛔ `keyof typeof POINT_LAYERS` with no `& Universe` intersection. Writing
 * `keyof … & PointUniverse` would make a key that is not a real layer id
 * vanish from `Covered` instead of erroring — the guard would then pass while
 * silently holding a typo. Without the intersection the constraint
 * `Covered extends Universe` fails and names the offending key.
 */
type PointUniverse = (typeof NOT_OPENABLE)[number];
type Covered = keyof typeof POINT_LAYERS;
type OptedOut = (typeof NOT_POINT)[number];

export const _pointIsComplete: AssertComplete<Covered, OptedOut, PointUniverse> = true;
export const _pointIsDisjoint: AssertDisjoint<Covered, OptedOut, PointUniverse> = true;
