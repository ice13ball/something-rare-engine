// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { create } from "zustand";
import type { LayerId } from "../types/layers";
import { VENT_STATUS_VALUES } from "../types/layers";
import type { FeatureCollection } from "geojson";
import type { DatasetStats } from "../utils/argoAlarms";
import type { AoiSelection } from "../utils/aoiGeometry";

// Arctic Catchments — variable selector type (display state, not a filter)
export type ArcticCatchmentVariable = "ocs_mean" | "oc_tot" | "runoff_mean" | "pf_frac" | "t_2m_mean";

// Arctic Sediment Carbon (CASCADE) — display state types (not filters)
export type CascadeVariable = "oc" | "tn" | "d13c" | "d14c";
export type CascadeDisplayMode = "field" | "stations";

export interface SelectedFeature {
  id: string | number;
  layer: string;
  properties: Record<string, unknown>;
  slot: number; // monotonically increasing; used for stable panel positioning
}

/** One object a link asked for and the map could not show. */
export interface SharePanelFailure {
  /** Public layer id, so the notice can name the layer in the reader's language. */
  layerId: string;
  /** The identifier that did not resolve — shown so the sender can be told what to re-send. */
  featureId: string;
  /**
   * `true` for sources that mint new identifiers on every republication, so the
   * notice can say the link aged rather than implying the object never existed.
   * ⛔ Documented for OBIS in `.claude/rules/layers/obis-occurrences.md`.
   */
  idRegenerates?: boolean;
}

export interface VentConflict {
  vent_name: string;
  vent_status: string;
  depth_m: number | null;
  risk_level: string;
  lon?: number;
  lat?: number;
}

export interface RiskArea {
  isaId: string;           // specific claim isa_id — key for lookup
  name: string;            // contractor_name
  resource_type: string;
  hotspots: any[];         // species properties inside this specific claim polygon
  argoFloats: any[];       // GeoJSON feature objects near this specific claim
  containerFeature: any;   // single claim polygon feature for spatial queries
  oncStations: any[];       // ONC stations within 200 km of claim centroid
  oceansitesMoorings: any[]; // OceanSITES moorings within 500 km of claim centroid
  noiseCells: any[];         // noise risk grid cells within 200 km of claim centroid
  chessSites: any[];          // ChEssBase standalone sites within 10 km of claim centroid
}

// Start empty — the WelcomeOverlay (shown every visit) lets users pick a mode
// which populates the active set. No data fetches until user makes a choice.
const DEFAULT_ACTIVE = new Set<LayerId>();

export interface MapStore {
  // Selection (up to 3 panels)
  selectedFeatures: SelectedFeature[];
  setSelectedFeature: (f: Omit<SelectedFeature, "slot"> | null, shift?: boolean) => void;
  removeSelectedFeature: (id: string | number, layer: string) => void;

  /**
   * Objects a deep link named but the map could not produce.
   *
   * ⛔ Exists because the alternative is silence. `?focus=` has always done
   * `if (found) { open it }` and then cleared the param either way, so a link
   * to a vanished vent turned its layer on, opened nothing, and said nothing —
   * and the reader concluded that was what the sender meant. Both the share
   * link and `?focus=` write here, so one notice covers both doors.
   */
  sharePanelFailures: SharePanelFailure[];
  addSharePanelFailure: (f: SharePanelFailure) => void;
  clearSharePanelFailures: () => void;

  // Risk data for claim panels
  riskAreas: RiskArea[];
  setRiskAreas: (areas: RiskArea[] | ((prev: RiskArea[]) => RiskArea[])) => void;

  // Map fly-to callback wired from Map3D
  flyTo: ((lon: number, lat: number) => void) | null;
  setFlyTo: (fn: (lon: number, lat: number) => void) => void;

  // Argo dataset statistics for anomaly highlighting in popups
  argoDatasetStats: DatasetStats | null;
  setArgoDatasetStats: (stats: DatasetStats) => void;

  // Vent data for coordinate lookups in claim panels
  ventsData: import("geojson").FeatureCollection | null;
  setVentsData: (data: import("geojson").FeatureCollection) => void;

  // Layer visibility
  activeLayers: Set<LayerId>;
  enabledLayerIds: Set<string> | null;   // null = config not loaded / fetch failed → allow all
  setEnabledLayerIds: (ids: Set<string> | null) => void;
  setActiveLayers: (layers: Set<LayerId>) => void;
  toggleLayer: (id: LayerId) => void;
  disableAllLayers: () => void;

  // Contractor filtering
  hiddenContractors: Set<string>;
  toggleContractor: (key: string) => void;

  // Filters
  ventStatusFilters: Set<string>;
  toggleVentStatus: (s: string) => void;
  argoAlarmFilters: Set<string>;
  toggleArgoAlarm: (a: string) => void;
  claimRiskFilters: Set<string>;
  toggleClaimRisk: (r: string) => void;
  iucnFilters: Set<string>;
  toggleIucnFilter: (cat: string) => void;
  noiseRiskFilters: Set<string>;
  toggleNoiseRiskFilter: (level: string) => void;
  chessPhylumFilters: Set<string>;
  toggleChessPhylumFilter: (p: string) => void;
  oceansitesNetworkFilters: Set<string>;
  toggleOceansitesNetworkFilter: (net: string) => void;
  /** OceanOPS's own platform status — "OPERATIONAL" | "INACTIVE" | "CLOSED" |
   *  "REGISTERED". Empty set = show all, like every other filter here. Measured
   *  on production 2026-09-11: 64 OPERATIONAL of 1,037 stations (6.2%). */
  oceansitesStatusFilters: Set<string>;
  toggleOceansitesStatusFilter: (status: string) => void;
  // Submarine cable source filter — values: "emodnet", "onc". Empty set = show all.
  cableSourceFilters: Set<string>;
  toggleCableSourceFilter: (src: string) => void;
  // Arctic river source filter — values: "arcticgro", "pangaea_lena", "pangaea_caa". Empty set = show all.
  arcticRiverSourceFilters: Set<string>;
  toggleArcticRiverSourceFilter: (v: string) => void;
  // SEAFLEA methane-seep feature-type filter. Empty set = show all.
  methaneSeepsFeatureTypeFilters: Set<string>;
  toggleMethaneSeepsFeatureTypeFilter: (v: string) => void;
  // Permafrost thaw filters (empty set = show all).
  thawTypeFilters: Set<string>;          // "abrupt" | "non-abrupt"
  toggleThawTypeFilter: (v: string) => void;
  thawCategoryFilters: Set<string>;      // lowercased feature_category
  toggleThawCategoryFilter: (v: string) => void;
  permafrostSourceFilters: Set<string>;  // "alaska_webb" | "arts_panarctic"
  togglePermafrostSourceFilter: (v: string) => void;
  fireConfidenceFilters: Set<string>;
  toggleFireConfidenceFilter: (c: string) => void;
  oncEovFilters: Set<string>;
  toggleOncEovFilter: (eov: string) => void;
  firesNearMiningOnly: boolean;
  toggleFiresNearMiningOnly: () => void;
  tailingsRiskFilters: Set<string>;
  toggleTailingsRiskFilter: (r: string) => void;
  tailingsStatusFilters: Set<string>;
  toggleTailingsStatusFilter: (s: string) => void;

  // DeepData stations — per-contractor visibility (short codes: NORI, TOML, …).
  // Empty set = show all (existing convention).
  deepdataStationContractorFilters: Set<string>;
  toggleDeepdataStationContractor: (code: string) => void;

  // WOD Oxygen — decade filter. Empty set = show all.
  wodDecadeFilters: Set<string>;
  toggleWodDecadeFilter: (v: string) => void;

  // MEMENTO (GEOMAR CH₄/N₂O) — display state (NOT filters; not in resetAllFilters)
  mementoGas: "ch4" | "n2o";
  setMementoGas: (g: "ch4" | "n2o") => void;
  mementoDisplayMode: "dots" | "hexes";
  setMementoDisplayMode: (m: "dots" | "hexes") => void;
  // MEMENTO real filters (DO add to resetAllFilters). Empty set = show all.
  mementoGasFilters: Set<string>;       // "ch4" | "n2o" presence
  toggleMementoGasFilter: (v: string) => void;
  mementoDecadeFilters: Set<string>;
  toggleMementoDecadeFilter: (v: string) => void;

  // GEOTRACES trace metals — display state (NOT a filter; not in resetAllFilters)
  geotracesElement: "mn" | "fe" | "co" | "ni" | "cu";
  setGeotracesElement: (e: "mn" | "fe" | "co" | "ni" | "cu") => void;
  geotracesDisplayMode: "dots" | "hexes";
  setGeotracesDisplayMode: (m: "dots" | "hexes") => void;
  // GEOTRACES real filter (DO add to resetAllFilters). Empty set = show all.
  geotracesDecadeFilters: Set<string>;
  toggleGeotracesDecadeFilter: (d: string) => void;

  // MOSAIC — global marine sediment carbon (ETH Zürich) — display state (NOT a filter; not in resetAllFilters)
  mosaicVariable: "toc" | "tn" | "d13c" | "d14c";
  setMosaicVariable: (v: "toc" | "tn" | "d13c" | "d14c") => void;
  mosaicDisplayMode: "dots" | "hexes";
  setMosaicDisplayMode: (m: "dots" | "hexes") => void;
  // MOSAIC real filter (DO add to resetAllFilters). Empty set = show all.
  mosaicDecadeFilters: Set<string>;
  toggleMosaicDecadeFilter: (d: string) => void;

  // Arctic Catchments — variable selector (display state, NOT a filter; not in resetAllFilters)
  arcticCatchmentsVariable: ArcticCatchmentVariable;
  setArcticCatchmentsVariable: (v: ArcticCatchmentVariable) => void;

  // Hydrophone stations — three filter dimensions (source, status, depth band).
  // Empty set = show all (existing convention).
  hydrophoneSourceFilters: Set<string>;
  hydrophoneStatusFilters: Set<string>;
  hydrophoneDepthFilters:  Set<string>;
  toggleHydrophoneSourceFilter: (value: string) => void;
  toggleHydrophoneStatusFilter: (value: string) => void;
  toggleHydrophoneDepthFilter:  (value: string) => void;

  // Vent conflicts indexed by isa_id
  ventConflicts: Record<string, VentConflict[]>;
  setVentConflicts: (c: Record<string, VentConflict[]>) => void;

  // Plume traces (real-time). One traced float fans out to many profile traces,
  // so platformId groups them back to the float the user actually opened.
  plumeTraces: { argoId: string; platformId?: string; data: FeatureCollection }[];
  addPlumeTrace: (argoId: string, data: FeatureCollection, platformId?: string) => void;
  removePlumeTracesByPlatform: (platformId: string) => void;
  clearPlumeTraces: () => void;

  // Plume history
  plumeHistoryQueue: { contractorName: string; data: FeatureCollection }[];
  addPlumeHistory: (name: string, data: FeatureCollection) => void;
  clearPlumeHistory: () => void;

  // Vessel focus — when set, Map3D hides Live Vessels and draws only this ship's
  // 30-day track (path + clickable points). null = normal view.
  vesselFocus: { mmsi: number; name: string; track: FeatureCollection } | null;
  setVesselFocus: (v: { mmsi: number; name: string; track: FeatureCollection } | null) => void;

  // Transient callbacks wired from Map3D
  tracePlume: ((platformId: string) => Promise<void>) | null;
  setTracePlume: (fn: (platformId: string) => Promise<void>) => void;
  fetchPlumeHistory: ((contractorName: string) => Promise<void>) | null;
  setFetchPlumeHistory: (fn: (contractorName: string) => Promise<void>) => void;
  flyToLayer: ((id: LayerId) => void) | null;
  setFlyToLayer: (fn: (id: LayerId) => void) => void;
  searchById: ((query: string) => boolean) | null;
  setSearchById: (fn: (query: string) => boolean) => void;

  // Incremented on every bare map tap — lets panels auto-close on mobile
  mapTapCount: number;
  bumpMapTap: () => void;

  // Report generation jobs
  reportJobs: { platformId: string; status: "generating" | "ready" | "failed"; error?: string; type: "float" | "claim" | "chess" }[];
  startReportJob: (platformId: string, type?: "float" | "claim" | "chess") => void;
  updateReportJob: (platformId: string, status: "generating" | "ready" | "failed", error?: string) => void;
  dismissReportJob: (platformId: string) => void;

  // Live AIS layer filters (Phase 0 vessel rebuild)
  aisShipTypeFilters: Set<string>;   // AIS ITU type-code buckets: cargo, tanker, fishing, passenger, other
  toggleAisShipTypeFilter: (c: string) => void;
  aisFlagFilters: Set<string>;       // ISO country codes (e.g. "CN", "NO")
  toggleAisFlagFilter: (f: string) => void;

  // Offshore-activity type filter — values: "oil_gas", "offshore_wind", "seabed_mining". Empty = show all.
  offshoreActivityFilters: Set<string>;
  toggleOffshoreActivityFilter: (t: string) => void;

  // Offshore-activity country filter — values are sovereign names ("Canada", "United States"). Empty = show all.
  offshoreActivityCountryFilters: Set<string>;
  toggleOffshoreActivityCountryFilter: (c: string) => void;

  // WOA Climatology — display mode (NOT a filter; not reset by resetAllFilters)
  woaVariable: string;
  setWoaVariable: (v: string) => void;
  woaDepth: number;
  setWoaDepth: (d: number) => void;
  woaDisplayMode: "field" | "hexes";
  setWoaDisplayMode: (m: "field" | "hexes") => void;

  // Ocean Carbon (GLODAP) — display mode (NOT a filter; not reset by resetAllFilters)
  carbonVariable: string;
  setCarbonVariable: (v: string) => void;
  carbonDepth: number;
  setCarbonDepth: (d: number) => void;
  carbonDisplayMode: "field" | "hexes";
  setCarbonDisplayMode: (m: "field" | "hexes") => void;

  // Ocean Acidification (GLODAP Ω) — display mode (NOT a filter; not reset by resetAllFilters)
  acidificationVariable: "aragonite" | "calcite" | "horizon" | "horizon-shift";
  setAcidificationVariable: (v: "aragonite" | "calcite" | "horizon" | "horizon-shift") => void;
  acidificationDepth: number;
  setAcidificationDepth: (d: number) => void;
  acidificationDisplayMode: "field" | "hexes";
  setAcidificationDisplayMode: (m: "field" | "hexes") => void;

  // Cumulative Human Impact — display state only (NOT a filter; not reset by resetAllFilters)
  chiDisplayMode: "field" | "hexes";
  setChiDisplayMode: (m: "field" | "hexes") => void;

  // Marine Carbon (unified hex grid) — display state (NOT a filter; not reset by resetAllFilters)
  marineCarbonVariable: string;
  setMarineCarbonVariable: (v: string) => void;
  marineCarbonDepth: number;
  setMarineCarbonDepth: (d: number) => void;

  // VME suitability (modeled hex) — display state (NOT a filter)
  vmeView: "suitability" | "uncertainty";
  setVmeView: (v: "suitability" | "uncertainty") => void;

  // Surface Ocean CO₂ (SOCAT) — display state (NOT a filter; not reset by resetAllFilters)
  co2Variable: string;
  setCo2Variable: (v: string) => void;
  co2Decade: number;
  setCo2Decade: (d: number) => void;
  co2DisplayMode: "field" | "hexes";
  setCo2DisplayMode: (m: "field" | "hexes") => void;

  // Oxygen Deoxgenation — display mode (NOT a filter; not reset by resetAllFilters)
  oxygenView: "recent" | "change";
  setOxygenView: (v: "recent" | "change") => void;
  oxygenDepth: number;
  setOxygenDepth: (d: number) => void;
  oxygenDisplayMode: "field" | "hexes";
  setOxygenDisplayMode: (m: "field" | "hexes") => void;

  // Seabed Substrate — display mode (NOT a filter; not reset by resetAllFilters)
  seabedDisplayMode: "field" | "hexes";
  setSeabedDisplayMode: (m: "field" | "hexes") => void;

  // Arctic Sediment Carbon (CASCADE) — display state (NOT filters; not reset by resetAllFilters)
  cascadeVariable: CascadeVariable;
  setCascadeVariable: (v: CascadeVariable) => void;
  cascadeDisplayMode: CascadeDisplayMode;
  setCascadeDisplayMode: (m: CascadeDisplayMode) => void;
  // CASCADE decade filter (real filter, IS reset by resetAllFilters)
  cascadeDecadeFilters: Set<string>;
  toggleCascadeDecadeFilter: (d: string) => void;

  // Ocean currents — display mode (NOT a filter; not reset by resetAllFilters)
  currentsDepth: "surface" | "1000m";
  setCurrentsDepth: (d: "surface" | "1000m") => void;
  currentsDate: string | null;            // null = latest
  setCurrentsDate: (d: string | null) => void;
  currentsPlaying: boolean;
  setCurrentsPlaying: (b: boolean) => void;

  // Resets all filters to defaults in one action
  resetAllFilters: () => void;

  // Layer loading progress
  layerProgress: Map<string, { received: number; total: number; done: boolean }>;
  setLayerProgress: (name: string, received: number, total: number) => void;
  markLayerDone: (name: string) => void;
  clearLayerProgress: (name: string) => void;

  // Discovery panel open state (shared so WelcomeOverlay can trigger it)
  discoveryOpen: boolean;
  setDiscoveryOpen: (v: boolean) => void;

  // Tutorial
  tutorialReady: boolean;
  setTutorialReady: (v: boolean) => void;

  // AOI selection + export panel — display/interaction state (NOT filters; not in resetAllFilters)
  aoiSelection: AoiSelection | null;
  selectionMode: "box" | "polygon" | "hexes" | null;
  exportPanelOpen: boolean;
  exportCheckedLayers: Set<string>;
  setSelectionMode: (m: "box" | "polygon" | "hexes" | null) => void;
  setAoiSelection: (a: AoiSelection | null) => void;
  clearAoiSelection: () => void;
  toggleExportLayer: (id: string) => void;
  setExportCheckedLayers: (ids: string[]) => void;
  setExportPanelOpen: (open: boolean) => void;
  // Export format — display state (NOT a filter; not in resetAllFilters)
  exportFormat: "geojson" | "csv";
  setExportFormat: (f: "geojson" | "csv") => void;

  // LegendPanel deep-link — display state (NOT a filter; not in resetAllFilters)
  legendFocusLayer: string | null;
  openLegendForLayer: (id: string) => void;
  clearLegendFocus: () => void;
}

// Monotonically increases so each panel gets a unique, stable slot for positioning.
// Resets to 0 when all panels are closed to avoid very large numbers over time.
let _nextSlot = 0;

// Exported so filterRegistry.ts can derive its "every Set<string> field must be
// classified" universe from the store shape itself, rather than a hand-typed
// list that silently stops growing the day someone adds a 36th filter field.
/**
 * Every scalar field of the store — the universe a share link's display-state
 * registry must account for.
 *
 * ⛔ `NonNullable` is load-bearing: `currentsDate` is `string | null`, and a
 * plain `extends string` test drops it silently. A field this universe cannot
 * see is a field the completeness guard can never ask about.
 *
 * Sibling of `FilterSetKey` below, which does the same job for `Set<string>`
 * filters. Two universes because the two kinds validate and travel differently,
 * not because one was forgotten.
 */
export type ScalarStateKey = {
  [K in keyof MapStore]: NonNullable<MapStore[K]> extends string | number | boolean ? K : never;
}[keyof MapStore];

export type FilterSetKey = { [K in keyof MapStore]: MapStore[K] extends Set<string> ? K : never }[keyof MapStore];

function _makeToggle(
  set: (fn: (s: MapStore) => Partial<MapStore>) => void,
  key: FilterSetKey,
) {
  return (value: string) =>
    set((s) => {
      const next = new Set(s[key] as Set<string>);
      next.has(value) ? next.delete(value) : next.add(value);
      return { [key]: next } as Partial<MapStore>;
    });
}

/** Intersect a desired active-set with the enabled set. null enabled = allow all. */
function _gateActive(enabled: Set<string> | null, layers: Set<LayerId>): Set<LayerId> {
  if (!enabled) return layers;
  return new Set([...layers].filter((id) => enabled.has(id)));
}

export const useMapStore = create<MapStore>((set) => ({
  selectedFeatures: [],
  setSelectedFeature: (f, shift = false) =>
    set((s) => {
      if (f === null) {
        _nextSlot = 0;
        return { selectedFeatures: [] };
      }
      // Skip if exact same feature already open
      if (s.selectedFeatures.some(x => x.id === f.id && x.layer === f.layer))
        return {};
      const withSlot = { ...f, slot: _nextSlot++ };
      if (shift) {
        // Shift+click: stack alongside existing panels (max 3)
        return { selectedFeatures: [...s.selectedFeatures, withSlot].slice(0, 3) };
      }
      // Normal click: replace all open panels with the new one
      _nextSlot = 1; // reset after clearing
      return { selectedFeatures: [{ ...f, slot: 0 }] };
    }),
  sharePanelFailures: [],
  addSharePanelFailure: (f) =>
    set((s) =>
      // Same object reported twice (the effect re-runs as each dataset lands)
      // must not stack into two lines of the same complaint.
      s.sharePanelFailures.some(x => x.layerId === f.layerId && x.featureId === f.featureId)
        ? {}
        : { sharePanelFailures: [...s.sharePanelFailures, f] },
    ),
  clearSharePanelFailures: () => set({ sharePanelFailures: [] }),
  removeSelectedFeature: (id, layer) =>
    set((s) => ({
      selectedFeatures: s.selectedFeatures.filter(x => !(x.id === id && x.layer === layer)),
    })),

  activeLayers: new Set(DEFAULT_ACTIVE),
  enabledLayerIds: null,
  setEnabledLayerIds: (ids) =>
    set((s) => ({
      enabledLayerIds: ids,
      // Prune anything already active that just became non-enabled (handles the
      // race where WelcomeOverlay seeded before the config finished loading).
      activeLayers: _gateActive(ids, s.activeLayers),
    })),
  setActiveLayers: (layers) =>
    set((s) => ({ activeLayers: _gateActive(s.enabledLayerIds, layers) })),
  toggleLayer: (id) =>
    set((s) => {
      // Never activate a non-enabled layer; always allow deactivation.
      if (!s.activeLayers.has(id) && s.enabledLayerIds && !s.enabledLayerIds.has(id)) {
        return { activeLayers: s.activeLayers };
      }
      const next = new Set(s.activeLayers);
      next.has(id) ? next.delete(id) : next.add(id);
      return { activeLayers: next };
    }),
  disableAllLayers: () => set({ activeLayers: new Set() }),

  hiddenContractors: new Set(),
  toggleContractor: (key) =>
    set((s) => {
      const next = new Set(s.hiddenContractors);
      next.has(key) ? next.delete(key) : next.add(key);
      return { hiddenContractors: next };
    }),

  ventStatusFilters: new Set(VENT_STATUS_VALUES),
  toggleVentStatus: _makeToggle(set, "ventStatusFilters"),

  argoAlarmFilters: new Set<string>(),
  toggleArgoAlarm: _makeToggle(set, "argoAlarmFilters"),

  claimRiskFilters: new Set<string>(),
  toggleClaimRisk: _makeToggle(set, "claimRiskFilters"),

  iucnFilters: new Set<string>(),
  toggleIucnFilter: _makeToggle(set, "iucnFilters"),

  noiseRiskFilters: new Set<string>(),
  toggleNoiseRiskFilter: _makeToggle(set, "noiseRiskFilters"),

  chessPhylumFilters: new Set<string>(),
  toggleChessPhylumFilter: _makeToggle(set, "chessPhylumFilters"),

  oceansitesNetworkFilters: new Set<string>(),
  toggleOceansitesNetworkFilter: _makeToggle(set, "oceansitesNetworkFilters"),
  oceansitesStatusFilters: new Set<string>(),
  toggleOceansitesStatusFilter: _makeToggle(set, "oceansitesStatusFilters"),
  cableSourceFilters: new Set<string>(),
  toggleCableSourceFilter: _makeToggle(set, "cableSourceFilters"),
  arcticRiverSourceFilters: new Set<string>(),
  toggleArcticRiverSourceFilter: _makeToggle(set, "arcticRiverSourceFilters"),
  methaneSeepsFeatureTypeFilters: new Set<string>(),
  toggleMethaneSeepsFeatureTypeFilter: _makeToggle(set, "methaneSeepsFeatureTypeFilters"),
  thawTypeFilters: new Set<string>(),
  toggleThawTypeFilter: _makeToggle(set, "thawTypeFilters"),
  thawCategoryFilters: new Set<string>(),
  toggleThawCategoryFilter: _makeToggle(set, "thawCategoryFilters"),
  permafrostSourceFilters: new Set<string>(),
  togglePermafrostSourceFilter: _makeToggle(set, "permafrostSourceFilters"),
  fireConfidenceFilters: new Set<string>(),
  toggleFireConfidenceFilter: _makeToggle(set, "fireConfidenceFilters"),
  oncEovFilters: new Set<string>(),
  toggleOncEovFilter: _makeToggle(set, "oncEovFilters"),
  firesNearMiningOnly: false,
  toggleFiresNearMiningOnly: () => set(s => ({ firesNearMiningOnly: !s.firesNearMiningOnly })),
  tailingsRiskFilters: new Set<string>(),
  toggleTailingsRiskFilter: _makeToggle(set, "tailingsRiskFilters"),
  tailingsStatusFilters: new Set<string>(),
  toggleTailingsStatusFilter: _makeToggle(set, "tailingsStatusFilters"),

  aisShipTypeFilters: new Set<string>(),
  toggleAisShipTypeFilter: _makeToggle(set, "aisShipTypeFilters"),
  aisFlagFilters: new Set<string>(),
  toggleAisFlagFilter: _makeToggle(set, "aisFlagFilters"),

  deepdataStationContractorFilters: new Set<string>(),
  toggleDeepdataStationContractor: _makeToggle(set, "deepdataStationContractorFilters"),

  wodDecadeFilters: new Set<string>(),
  toggleWodDecadeFilter: _makeToggle(set, "wodDecadeFilters"),

  mementoGas: "n2o",
  setMementoGas: (g) => set({ mementoGas: g }),
  mementoDisplayMode: "dots",
  setMementoDisplayMode: (m) => set({ mementoDisplayMode: m }),
  mementoGasFilters: new Set<string>(),
  toggleMementoGasFilter: _makeToggle(set, "mementoGasFilters"),
  mementoDecadeFilters: new Set<string>(),
  toggleMementoDecadeFilter: _makeToggle(set, "mementoDecadeFilters"),

  geotracesElement: "fe",
  setGeotracesElement: (e) => set({ geotracesElement: e }),
  geotracesDisplayMode: "dots",
  setGeotracesDisplayMode: (m) => set({ geotracesDisplayMode: m }),
  geotracesDecadeFilters: new Set<string>(),
  toggleGeotracesDecadeFilter: _makeToggle(set, "geotracesDecadeFilters"),

  mosaicVariable: "toc",
  setMosaicVariable: (v) => set({ mosaicVariable: v }),
  mosaicDisplayMode: "dots",
  setMosaicDisplayMode: (m) => set({ mosaicDisplayMode: m }),
  mosaicDecadeFilters: new Set<string>(),
  toggleMosaicDecadeFilter: _makeToggle(set, "mosaicDecadeFilters"),

  arcticCatchmentsVariable: "ocs_mean",
  setArcticCatchmentsVariable: (v) => set({ arcticCatchmentsVariable: v }),

  hydrophoneSourceFilters: new Set<string>(),
  hydrophoneStatusFilters: new Set<string>(),
  hydrophoneDepthFilters:  new Set<string>(),
  toggleHydrophoneSourceFilter: _makeToggle(set, "hydrophoneSourceFilters"),
  toggleHydrophoneStatusFilter: _makeToggle(set, "hydrophoneStatusFilters"),
  toggleHydrophoneDepthFilter:  _makeToggle(set, "hydrophoneDepthFilters"),

  offshoreActivityFilters: new Set<string>(),
  toggleOffshoreActivityFilter: _makeToggle(set, "offshoreActivityFilters"),
  offshoreActivityCountryFilters: new Set<string>(),
  toggleOffshoreActivityCountryFilter: _makeToggle(set, "offshoreActivityCountryFilters"),

  woaVariable: "oxygen",
  setWoaVariable: (v) => set({ woaVariable: v }),
  woaDepth: 500,
  setWoaDepth: (d) => set({ woaDepth: d }),
  woaDisplayMode: "field",
  setWoaDisplayMode: (m) => set({ woaDisplayMode: m }),

  carbonVariable: "dic",
  setCarbonVariable: (v) => set({ carbonVariable: v }),
  carbonDepth: 0,
  setCarbonDepth: (d) => set({ carbonDepth: d }),
  carbonDisplayMode: "field",
  setCarbonDisplayMode: (m) => set({ carbonDisplayMode: m }),

  acidificationVariable: "aragonite",
  setAcidificationVariable: (v) => set({ acidificationVariable: v }),
  acidificationDepth: 0,
  setAcidificationDepth: (d) => set({ acidificationDepth: d }),
  acidificationDisplayMode: "field",
  setAcidificationDisplayMode: (m) => set({ acidificationDisplayMode: m }),

  // chiDisplayMode is NOT in resetAllFilters — display state only
  chiDisplayMode: "field",
  setChiDisplayMode: (m) => set({ chiDisplayMode: m }),

  marineCarbonVariable: "co2_fco2",
  setMarineCarbonVariable: (v) => set({ marineCarbonVariable: v }),
  marineCarbonDepth: 0,
  setMarineCarbonDepth: (d) => set({ marineCarbonDepth: d }),

  vmeView: "suitability",
  setVmeView: (v) => set({ vmeView: v }),

  co2Variable: "fco2",
  setCo2Variable: (v) => set({ co2Variable: v }),
  co2Decade: 5,
  setCo2Decade: (d) => set({ co2Decade: d }),
  co2DisplayMode: "field",
  setCo2DisplayMode: (m) => set({ co2DisplayMode: m }),

  oxygenView: "change",
  setOxygenView: (v) => set({ oxygenView: v }),
  oxygenDepth: 500,
  setOxygenDepth: (d) => set({ oxygenDepth: d }),
  oxygenDisplayMode: "field",
  setOxygenDisplayMode: (m) => set({ oxygenDisplayMode: m }),

  // seabedDisplayMode is NOT in resetAllFilters — display state only
  seabedDisplayMode: "field",
  setSeabedDisplayMode: (m) => set({ seabedDisplayMode: m }),

  // cascadeVariable / cascadeDisplayMode are NOT in resetAllFilters — display state only
  cascadeVariable: "oc",
  setCascadeVariable: (v) => set({ cascadeVariable: v }),
  cascadeDisplayMode: "field",
  setCascadeDisplayMode: (m) => set({ cascadeDisplayMode: m }),
  cascadeDecadeFilters: new Set<string>(),
  toggleCascadeDecadeFilter: _makeToggle(set, "cascadeDecadeFilters"),

  currentsDepth: "surface",
  setCurrentsDepth: (d) => set({ currentsDepth: d }),
  currentsDate: null,
  setCurrentsDate: (d) => set({ currentsDate: d }),
  currentsPlaying: false,
  setCurrentsPlaying: (b) => set({ currentsPlaying: b }),

  ventConflicts: {},
  setVentConflicts: (c) => set({ ventConflicts: c }),

  plumeTraces: [],
  addPlumeTrace: (argoId, data, platformId) =>
    set((s) => ({
      plumeTraces: [...s.plumeTraces.slice(-49), { argoId, platformId, data }],
    })),
  removePlumeTracesByPlatform: (platformId) =>
    set((s) => ({
      plumeTraces: s.plumeTraces.filter(
        (t) => (t.platformId ?? t.argoId) !== platformId,
      ),
    })),
  clearPlumeTraces: () => set({ plumeTraces: [] }),

  plumeHistoryQueue: [],
  addPlumeHistory: (name, data) =>
    set((s) => ({
      plumeHistoryQueue: [...s.plumeHistoryQueue.slice(-9), { contractorName: name, data }],
    })),
  clearPlumeHistory: () => set({ plumeHistoryQueue: [] }),

  vesselFocus: (() => {
    try {
      const raw = localStorage.getItem("vesselFocus");
      return raw ? JSON.parse(raw) : null;
    } catch { return null; }
  })(),
  setVesselFocus: (v) => {
    try {
      if (v) localStorage.setItem("vesselFocus", JSON.stringify(v));
      else localStorage.removeItem("vesselFocus");
    } catch { /* quota/SSR — non-fatal */ }
    set({ vesselFocus: v });
  },

  tracePlume: null,
  setTracePlume: (fn) => set({ tracePlume: fn }),
  fetchPlumeHistory: null,
  setFetchPlumeHistory: (fn) => set({ fetchPlumeHistory: fn }),
  flyToLayer: null,
  setFlyToLayer: (fn) => set({ flyToLayer: fn }),
  searchById: null,
  setSearchById: (fn) => set({ searchById: fn }),

  riskAreas: [],
  setRiskAreas: (areas) =>
    set((s) => ({ riskAreas: typeof areas === "function" ? areas(s.riskAreas) : areas })),

  flyTo: null,
  setFlyTo: (fn) => set({ flyTo: fn }),

  argoDatasetStats: null,
  setArgoDatasetStats: (stats) => set({ argoDatasetStats: stats }),

  ventsData: null,
  setVentsData: (data) => set({ ventsData: data }),

  mapTapCount: 0,
  bumpMapTap: () => set((s) => ({ mapTapCount: s.mapTapCount + 1 })),

  reportJobs: [],
  startReportJob: (platformId, type = "float") =>
    set((s) => ({
      reportJobs: s.reportJobs.some(j => j.platformId === platformId)
        ? s.reportJobs.map(j => j.platformId === platformId ? { ...j, status: "generating" as const, error: undefined } : j)
        : [...s.reportJobs, { platformId, status: "generating" as const, type }],
    })),
  updateReportJob: (platformId, status, error) =>
    set((s) => ({
      reportJobs: s.reportJobs.map(j =>
        j.platformId === platformId ? { ...j, status, error } : j
      ),
    })),
  dismissReportJob: (platformId) =>
    set((s) => ({
      reportJobs: s.reportJobs.filter(j => j.platformId !== platformId),
    })),

  resetAllFilters: () => set({
    claimRiskFilters:  new Set<string>(),
    ventStatusFilters: new Set(VENT_STATUS_VALUES),
    argoAlarmFilters:  new Set<string>(),
    hiddenContractors: new Set<string>(),
    iucnFilters:       new Set<string>(),
    noiseRiskFilters:  new Set<string>(),
    oceansitesNetworkFilters: new Set<string>(),
    oceansitesStatusFilters: new Set<string>(),
    cableSourceFilters: new Set<string>(),
    arcticRiverSourceFilters: new Set<string>(),
    methaneSeepsFeatureTypeFilters: new Set<string>(),
    thawTypeFilters: new Set<string>(),
    thawCategoryFilters: new Set<string>(),
    permafrostSourceFilters: new Set<string>(),
    chessPhylumFilters:    new Set<string>(),
    fireConfidenceFilters: new Set<string>(),
    oncEovFilters: new Set<string>(),
    firesNearMiningOnly: false,
    tailingsRiskFilters: new Set<string>(),
    tailingsStatusFilters: new Set<string>(),
    deepdataStationContractorFilters: new Set<string>(),
    wodDecadeFilters: new Set<string>(),
    aisShipTypeFilters:  new Set<string>(),
    aisFlagFilters:      new Set<string>(),
    offshoreActivityFilters: new Set<string>(),
    offshoreActivityCountryFilters: new Set<string>(),
    hydrophoneSourceFilters: new Set<string>(),
    hydrophoneStatusFilters: new Set<string>(),
    hydrophoneDepthFilters:  new Set<string>(),
    mementoGasFilters: new Set<string>(),
    mementoDecadeFilters: new Set<string>(),
    geotracesDecadeFilters: new Set<string>(),
    cascadeDecadeFilters: new Set<string>(),
    mosaicDecadeFilters: new Set<string>(),
  }),

  layerProgress: new Map(),
  setLayerProgress: (name, received, total) =>
    set(s => {
      const next = new Map(s.layerProgress);
      next.set(name, { received, total, done: false });
      return { layerProgress: next };
    }),
  markLayerDone: (name) =>
    set(s => {
      const next = new Map(s.layerProgress);
      const entry = next.get(name);
      if (entry) next.set(name, { ...entry, done: true });
      return { layerProgress: next };
    }),
  clearLayerProgress: (name) =>
    set(s => {
      const next = new Map(s.layerProgress);
      next.delete(name);
      return { layerProgress: next };
    }),

  discoveryOpen: false,
  setDiscoveryOpen: (v) => set({ discoveryOpen: v }),

  tutorialReady: false,
  setTutorialReady: (v) => set({ tutorialReady: v }),

  // AOI selection + export panel (display/interaction state — NOT in resetAllFilters)
  aoiSelection: null,
  selectionMode: null,
  exportPanelOpen: false,
  exportCheckedLayers: new Set<string>(),
  setSelectionMode: (m) => set({ selectionMode: m }),
  setAoiSelection: (a) => set({ aoiSelection: a }),
  clearAoiSelection: () => set({ aoiSelection: null, selectionMode: null }),
  toggleExportLayer: (id) =>
    set((s) => {
      const next = new Set(s.exportCheckedLayers);
      next.has(id) ? next.delete(id) : next.add(id);
      return { exportCheckedLayers: next };
    }),
  setExportCheckedLayers: (ids) => set({ exportCheckedLayers: new Set(ids) }),
  setExportPanelOpen: (open) => set({ exportPanelOpen: open }),
  exportFormat: "geojson",
  setExportFormat: (f) => set({ exportFormat: f }),

  // LegendPanel deep-link (display state — NOT in resetAllFilters)
  legendFocusLayer: null,
  openLegendForLayer: (id) => set({ legendFocusLayer: id }),
  clearLegendFocus: () => set({ legendFocusLayer: null }),
}));
