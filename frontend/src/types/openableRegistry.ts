// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

/**
 * Which layers a share link may re-open a panel for, and how.
 *
 * ⛔ The point of this file is the guard at the bottom, not the table above it.
 * Stage 1 wired five layers by hand, exactly as `?focus=` and `searchById` did
 * before it — and hand-kept lists are how `DECK_LAYER_ID` ended up describing
 * 6 of the 24 routing keys that differ from a layer id, with nothing to say so.
 * Here every `LayerId` must be either wired or explicitly opted out with a
 * REASON, and `tsc` names the ones that are neither.
 *
 * ⛔ A reason is never invented. If it cannot be established from the code or
 * the data, it says "nieustalone" — a plausible-sounding guess is worse than an
 * admission, because it stops anyone re-checking.
 */
import type { AssertComplete, AssertDisjoint } from "./layerRegistry";
import { isActiveVentStatus } from "../utils/ventStatus";

/** How the client gets at a feature of this layer. */
export type OpenableSource =
  /** The whole FeatureCollection is in React state; find it by id. */
  | "client"
  /** Server-tiled: the client holds only the viewport, so ask `/by-id`. */
  | "by-id";

/**
 * Does this layer's identifier survive a re-ingestion?
 *
 * ⛔ `regenerated` is not a guess: OBIS mints a new `_id` whenever a
 * contributor republishes a dataset — documented in
 * `.claude/rules/layers/obis-occurrences.md`, and it cost 8M duplicated rows
 * in July 2026. A link keyed on such an id WILL rot, and the reader is told so.
 */
export type IdStability = "stable" | "regenerated" | "nieustalone";

export interface OpenableLayer {
  source: OpenableSource;
  /** Candidate id properties, in priority order — see openFromLink.ts. */
  idProps: readonly string[];
  /** Every key `routingKey` can return; needed to build a link from the store. */
  routingKeys: readonly string[];
  routingKey: (properties: Record<string, unknown>) => string;
  zoom: number;
  idStability: IdStability;
  /**
   * Key into the map of already-fetched collections (`searchDataRef` in
   * Map3D — the same one the search bar reads). Absent when the client never
   * holds the whole layer.
   */
  dataKey?: string;
  /**
   * `/by-id` endpoint prefix, for layers the client holds only a viewport of.
   * ⛔ Tried only AFTER `dataKey`. The endpoint supplements the tile, it does
   * not replace it — `PermafrostThawPanel` renders category, type and name
   * straight from the tile's properties, so preferring the network would open
   * a panel poorer than a click produces, and say nothing about it.
   */
  byIdPath?: string;
}

/**
 * ⛔ `as const satisfies`, NOT `Partial<Record<LayerId, …>>`. The Partial form
 * compiles and reads correctly and its `keyof` still contains EVERY LayerId —
 * so `Covered` was the whole universe and the completeness guard below could
 * never go red. Caught by sabotage: removing an entry produced no error at all.
 */
/**
 * The property chain the WRITE side already walks.
 *
 * ⭐ Not a per-layer list. `SearchBar`'s `featureId()` reaches an identifier by
 * exactly this order, and whatever it picks is what lands in
 * `SelectedFeature.id` and therefore in a link. Reading by any other order
 * would let the two ends disagree — which is precisely the bug that shipped in
 * stage 1 and was caught only by the miss notice.
 */
// Exported so `__tests__/feature-id-chains-agree.test.ts` can drive SearchBar's
// hand-copied twin with every name in here and catch the two drifting apart.
export const ID_CHAIN = [
  "mmsi", "vessel_id", "event_id", "isa_id", "id", "platform_id", "peak_id", "mrgid",
  "site_id", "device_id", "device_code", "city", "dam_name", "site_name", "station_id",
  "cast_id", "ext_id", "metadata_id", "unique_id",
  // MARHYS keys on the row's position in the published workbook. ⛔ Its
  // `sample_id` is NOT an identifier — 6788 rows carry 6108 distinct labels —
  // so it must never enter this chain. Last in the list: the chain is
  // first-match-wins, and a late, uniquely-named key cannot shadow anything.
  "source_row",
] as const;

export const OPENABLE = {
  "air-quality": {
    source: "client", idProps: ID_CHAIN,
    routingKeys: ["air-quality"], routingKey: () => "air-quality",
    zoom: 7, idStability: "nieustalone",
    dataKey: "airQuality",
  },
  "ais-live": {
    source: "client", idProps: ID_CHAIN,
    routingKeys: ["ais-live"], routingKey: () => "ais-live",
    zoom: 7, idStability: "nieustalone",
    dataKey: "aisLive",
  },
  "arctic-catchments": {
    source: "by-id", idProps: ["gid", "id"],
    routingKeys: ["arctic-catchments"], routingKey: () => "arctic-catchments",
    zoom: 7, idStability: "nieustalone",
    byIdPath: "/api/v2/spatial/arctic-catchments/by-id/",
  },
  "arctic-rivers": {
    source: "client", idProps: ID_CHAIN,
    routingKeys: ["arctic-rivers"], routingKey: () => "arctic-rivers",
    zoom: 7, idStability: "nieustalone",
    dataKey: "arcticRivers",
  },
  "arctic-sediment-carbon": {
    source: "client", idProps: ID_CHAIN,
    routingKeys: ["arctic-sediment-carbon-stations"], routingKey: () => "arctic-sediment-carbon-stations",
    zoom: 7, idStability: "nieustalone",
    dataKey: "arcticSedimentCarbon",
  },
  "argo": {
    source: "client", idProps: ID_CHAIN,
    routingKeys: ["argo-floats-3d"], routingKey: () => "argo-floats-3d",
    zoom: 7, idStability: "stable",  // WMO float number, an international identifier
    dataKey: "argo",
  },
  "biodiversity-hotspots": {
    source: "client", idProps: ID_CHAIN,
    routingKeys: ["biodiversity-hotspots"], routingKey: () => "biodiversity-hotspots",
    zoom: 7, idStability: "regenerated",  // OBIS mints a new _id on every republication — rules/layers/obis-occurrences.md
    dataKey: "hotspots",
  },
  "chess": {
    source: "client", idProps: ID_CHAIN,
    routingKeys: ["chess"], routingKey: () => "chess",
    zoom: 7, idStability: "nieustalone",
    dataKey: "chess",
  },
  "contracts": {
    source: "client", idProps: ID_CHAIN,
    routingKeys: ["mining-contracts-mvt"], routingKey: () => "mining-contracts-mvt",
    zoom: 6, idStability: "stable",  // ISA's own concession identifier, assigned by the registry
    dataKey: "claims",
  },
  "dams": {
    source: "client", idProps: ID_CHAIN,
    routingKeys: ["dams"], routingKey: () => "dams",
    zoom: 7, idStability: "nieustalone",
    dataKey: "dams",
  },
  "deepdata-stations": {
    source: "by-id", idProps: ["station_id", "id"],
    routingKeys: ["deepdata-stations"], routingKey: () => "deepdata-stations",
    zoom: 7, idStability: "nieustalone",
    dataKey: "deepdataStations",
    byIdPath: "/api/v2/map/deepdata-stations/by-id/",
  },
  "eez": {
    source: "client", idProps: ID_CHAIN,
    routingKeys: ["eez"], routingKey: () => "eez",
    zoom: 7, idStability: "nieustalone",
    dataKey: "eez",
  },
  "fires": {
    source: "client", idProps: ID_CHAIN,
    routingKeys: ["fires"], routingKey: () => "fires",
    zoom: 7, idStability: "nieustalone",
    dataKey: "fires",
  },
  "geotraces": {
    source: "by-id", idProps: ["station_id", "id"],
    routingKeys: ["geotraces"], routingKey: () => "geotraces",
    zoom: 7, idStability: "nieustalone",
    dataKey: "geotraces",
    byIdPath: "/api/v2/spatial/geotraces/by-id/",
  },
  marhys: {
    source: "client", idProps: ID_CHAIN,
    routingKeys: ["marhys"], routingKey: () => "marhys",
    // Vent-field scale: samples from one field sit within a few hundred metres
    // of each other, so a shallower zoom lands on an indistinguishable cluster.
    zoom: 11,
    // ⭐ Genuinely stable, and for a reason worth stating: MARHYS 4.0 is frozen
    // behind a DOI, so a row's position in the workbook cannot change. A
    // version 5.0 would be a different DOI and a different ingest.
    idStability: "stable",
    dataKey: "marhys",
  },
  "hydrophone-stations": {
    source: "client", idProps: ID_CHAIN,
    routingKeys: ["hydrophone-stations"], routingKey: () => "hydrophone-stations",
    zoom: 7, idStability: "nieustalone",
    dataKey: "hydrophones",
  },
  "hydrothermal-vents": {
    // ⛔ The only layer that needs a property the shared chain does not carry.
    // `featureId()` never returns `name`, so a link built in the app carries
    // the numeric `id` — but `?focus=vent:<name>` and the "View on map" button
    // on every vent's SEO page carry a NAME. Both must find the same vent.
    source: "client", idProps: ["id", "name"],
    routingKeys: ["hydrothermal-vents-active", "hydrothermal-vents-inactive"], routingKey: (p) => (isActiveVentStatus(p.status) ? "hydrothermal-vents-active" : "hydrothermal-vents-inactive"),
    zoom: 8, idStability: "nieustalone",
    dataKey: "vents",
  },
  "landslides": {
    source: "client", idProps: ID_CHAIN,
    routingKeys: ["landslides"], routingKey: () => "landslides",
    zoom: 7, idStability: "nieustalone",
    dataKey: "landslides",
  },
  "memento": {
    source: "by-id", idProps: ["cast_id", "id"],
    routingKeys: ["memento"], routingKey: () => "memento",
    zoom: 7, idStability: "nieustalone",
    dataKey: "memento",
    byIdPath: "/api/v2/spatial/memento/by-id/",
  },
  "methane-seeps": {
    source: "client", idProps: ID_CHAIN,
    routingKeys: ["methane-seeps"], routingKey: () => "methane-seeps",
    zoom: 7, idStability: "nieustalone",
    dataKey: "methaneSeeps",
  },
  "mosaic-sediment": {
    source: "by-id", idProps: ["core_id", "id"],
    routingKeys: ["mosaic-sediment"], routingKey: () => "mosaic-sediment",
    zoom: 7, idStability: "nieustalone",
    byIdPath: "/api/v2/spatial/mosaic/by-id/",
  },
  "oceansites": {
    source: "client", idProps: ID_CHAIN,
    routingKeys: ["oceansites"], routingKey: () => "oceansites",
    zoom: 7, idStability: "nieustalone",
    dataKey: "oceansites",
  },
  "offshore-activities": {
    source: "by-id", idProps: ["id", "feature_id"],
    routingKeys: ["offshore-activities-mvt"], routingKey: () => "offshore-activities-mvt",
    zoom: 7, idStability: "nieustalone",
    byIdPath: "/api/v2/spatial/offshore-activities/by-id/",
  },
  "onc": {
    source: "client", idProps: ID_CHAIN,
    routingKeys: ["onc"], routingKey: () => "onc",
    zoom: 7, idStability: "nieustalone",
    dataKey: "onc",
  },
  "onc-instruments": {
    source: "client", idProps: ID_CHAIN,
    routingKeys: ["onc-instruments"], routingKey: () => "onc-instruments",
    zoom: 7, idStability: "nieustalone",
    dataKey: "oncInstruments",
  },
  "permafrost-thaw": {
    source: "by-id", idProps: ["unique_id", "id"],
    routingKeys: ["permafrost-thaw"], routingKey: () => "permafrost-thaw",
    zoom: 7, idStability: "stable",  // deterministic sha1 of lon|lat|FeatureName — opaque but reproducible
    dataKey: "permafrostThaw",
    byIdPath: "/api/v2/map/permafrost-thaw/by-id/",
  },
  "ports": {
    source: "client", idProps: ID_CHAIN,
    routingKeys: ["ports"], routingKey: () => "ports",
    zoom: 7, idStability: "nieustalone",
    dataKey: "ports",
  },
  "protected-marine-sites": {
    source: "client", idProps: ID_CHAIN,
    routingKeys: ["protected-marine-sites"], routingKey: () => "protected-marine-sites",
    zoom: 7, idStability: "nieustalone",
    dataKey: "protectedSites",
  },
  "relinquished-areas": {
    source: "client", idProps: ID_CHAIN,
    routingKeys: ["relinquished-areas"], routingKey: () => "relinquished-areas",
    zoom: 7, idStability: "nieustalone",
    dataKey: "relinquished",
  },
  "reserved-areas": {
    source: "client", idProps: ID_CHAIN,
    routingKeys: ["reserved-areas"], routingKey: () => "reserved-areas",
    zoom: 7, idStability: "nieustalone",
    dataKey: "reserved",
  },
  "seamounts": {
    source: "client", idProps: ID_CHAIN,
    routingKeys: ["seamounts"], routingKey: () => "seamounts",
    zoom: 7, idStability: "nieustalone",
    dataKey: "seamounts",
  },
  "sios-svalbard": {
    source: "client", idProps: ID_CHAIN,
    routingKeys: ["sios-svalbard"], routingKey: () => "sios-svalbard",
    zoom: 7, idStability: "nieustalone",
    dataKey: "sios",
  },
  "submarine-cables": {
    source: "client", idProps: ID_CHAIN,
    routingKeys: ["submarine-cables"], routingKey: () => "submarine-cables",
    zoom: 7, idStability: "stable",  // composite (source_layer, source_id) key, adopted after the old (name,status) key rotted
    dataKey: "cables",
  },
  "tailings": {
    source: "client", idProps: ID_CHAIN,
    routingKeys: ["tailings"], routingKey: () => "tailings",
    zoom: 7, idStability: "nieustalone",
    dataKey: "tailings",
  },
  "tectonic-plates": {
    source: "client", idProps: ID_CHAIN,
    routingKeys: ["tectonic-plates-boundaries"], routingKey: () => "tectonic-plates-boundaries",
    zoom: 7, idStability: "nieustalone",
    dataKey: "tectonic",
  },
  "vessel-events": {
    source: "client", idProps: ID_CHAIN,
    routingKeys: ["vessel-events"], routingKey: () => "vessel-events",
    zoom: 7, idStability: "nieustalone",
    dataKey: "vessels",
  },
  "wod-oxygen": {
    source: "by-id", idProps: ["id", "feature_id"],
    routingKeys: ["wod-oxygen"], routingKey: () => "wod-oxygen",
    zoom: 7, idStability: "nieustalone",
    byIdPath: "/api/v2/spatial/wod-oxygen/by-id/",
  },
} as const satisfies Record<string, OpenableLayer>;

/**
 * Widened view for lookup code.
 *
 * ⛔ `OPENABLE` itself must keep its literal types — `as const satisfies` is
 * what lets `keyof` name the covered layers, and that is the whole basis of the
 * completeness guard at the bottom. But those literal types also mean an entry
 * without `dataKey` genuinely has no such property, so a union access will not
 * compile. This alias is the shape lookup code wants. Same pattern as
 * `LEGEND_ENTRIES` in LegendPanel.tsx.
 */
export const OPENABLE_LOOKUP: Record<string, OpenableLayer> = OPENABLE;

/**
 * Layers a link may NOT carry an object for, each with the reason.
 *
 * ⛔ Every reason below is lifted from a list that already carried it —
 * `NO_SEARCH` in `SearchBar.tsx`, or the absence of a `/by-id` endpoint. None
 * was invented for this file.
 */
export const NOT_OPENABLE = [
  // A "feature" here is a probe point, pixel or cell — not a discrete named
  // thing. There is no name-shaped field anywhere in its properties, so there
  // is no identifier a link could carry. These are stage 3's territory: the
  // link will carry a COORDINATE instead.
  "bathymetry",
  "ocean-currents",
  "woa-climatology",
  "oxygen-deox",
  "ocean-carbon",
  "ocean-co2-surface",
  "marine-carbon",
  "seabed-substrate",
  "vme-suitability",
  "ocean-acidification",
  "coral-acid-exposure",
  "cumulative-human-impact",
  "forest-loss",
  "surface-water",
  "carbon-flux",
  "soil-carbon",
  "noise-risk",
  "monitoring-density",
  // Server-tiled — the client holds only the current viewport — AND, unlike the
  // other four tiled layers, it has no `/by-id` endpoint to ask instead.
  // Openable the day one exists; nothing else is in the way.
  "water-risk",
  // The client DOES hold the whole set, but nothing in the data functions as a
  // name or a number: apeis ships AreaKM2/Remarks/Status/arcgis_id only,
  // mining-footprints ships area_km2/country/ftype/source only.
  // (Checked against production 2026-09-11, recorded in SearchBar's NO_SEARCH.)
  "mining-footprints",
  "apeis",
] as const;

// ⛔ No `& LayerId` intersection. That form makes a key which is NOT a real
// layer id vanish from `Covered` instead of erroring, so a typo'd entry would
// leave the guard green while covering nothing — the same "guard that cannot
// go red" defect this file's `as const satisfies` exists to prevent. Without
// it the `Covered extends Universe` constraint fails and names the bad key.
type Covered = keyof typeof OPENABLE;
type OptedOut = (typeof NOT_OPENABLE)[number];

export const _openableIsComplete: AssertComplete<Covered, OptedOut> = true;
export const _openableIsDisjoint: AssertDisjoint<Covered, OptedOut> = true;
