// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect, useState, useCallback, useRef, useMemo } from "react";
import { useLocation } from "react-router-dom";
import DeckGL from "@deck.gl/react";
import { MVTLayer, TileLayer } from "@deck.gl/geo-layers";
import { GeoJsonLayer, PolygonLayer, ScatterplotLayer, ColumnLayer, TextLayer, IconLayer, BitmapLayer } from "@deck.gl/layers";
import type { PickingInfo, MapViewState } from "@deck.gl/core";
import { FlyToInterpolator } from "@deck.gl/core";
import { Map as ReactMap } from "react-map-gl/maplibre";
import type { FeatureCollection } from "geojson";
import { booleanPointInPolygon, centroid, distance as turfDistance } from "@turf/turf";
import { useMapStore } from "../store/mapStore";
import { DetailPanel } from "./DetailPanel";
import { Map3DControls } from "./Map3DControls";
import { LegendPanel } from "./LegendPanel";
import { StatusStrip } from "./StatusStrip";
import { DiscoveryPanel } from "./DiscoveryPanel";
import { buildPlumeLayers } from "./PlumeLayer";
import { buildCurrentsArrowLayer, type CurrentsMeta, type CurrentArrow } from "./CurrentsLayer";
import { CurrentsParticleCanvas, type VelocityField } from "./CurrentsParticleCanvas";
import { buildPlumeHistoryLayers } from "./PlumeHistoryLayer";
import { buildArgoTrailLayers } from "./ArgoTrailLayer";
import type { PlumeOriginInfo } from "./PlumeHistoryLayer";
import { computeDatasetStats, floatHasAlarm, phImplausible } from "../utils/argoAlarms";
import type { DatasetStats } from "../utils/argoAlarms";
import { loadMapState, saveMapState, consumeReturnFly, saveReturnFlyFromViewState } from "../utils/mapState";
import { setLiveMapState } from "../utils/liveMapState";
import { useLiveShareUrl } from "./map3d/useLiveShareUrl";
import { openTargetFor, isOpenableLayer, OPENABLE_LOOKUP } from "./map3d/openFromLink";
import { pointTargetFor, isPointLayer } from "./map3d/pointFromLink";
import { FocusUnavailableNotice } from "./FocusUnavailableNotice";
import { decodeShareState } from "../utils/shareState";
import { applyShareableFilters } from "../types/filterRegistry";
import { applyShareableDisplay } from "../types/displayRegistry";
import { resolveInitialCamera, resolveInitialLayers, shouldStripShareParam, linkCarriesView } from "./map3d/shareBootstrap";
import { nextActiveForLink, NO_CLIENT_COPY } from "./map3d/linkLayerActivation";
import { applyMenuExpansion } from "../utils/startupProfiles";
import { isActiveVentStatus, isConfirmedVentStatus } from "../utils/ventStatus";
import { SearchBar } from "./SearchBar";
import { analytics } from "../utils/analytics";
import type { ClaimFeatureCollection } from "../types/claims";
import { LAYER_CONFIGS } from "../types/layers";
import type { LayerId, ClaimRiskValue } from "../types/layers";
import { TAILINGS_HAZARD_VALUES } from "../types/landLayers";
import type { AssertComplete, AssertDisjoint } from "../types/layerRegistry";
import { LayerUnavailableNotice } from "./LayerUnavailableNotice";
import { fetchWithProgress } from "../utils/fetchWithProgress";
import { oceansitesPasses as oceansitesPassesRule } from "../utils/oceansitesFilter";
import { matchesAisFilters, classifyShipType, colorForShipClass } from "../utils/aisFilters";
import { colorForContractor } from "../utils/contractorColors";
import {
  WRI_AQUEDUCT, WRI_AQUEDUCT_NO_DATA,
  TAILINGS_HAZARD, TAILINGS_HAZARD_OTHER, TAILINGS_UNRATED,
  FIRMS_CONFIDENCE, FIRMS_FALLBACK,
  CHESS_COLOR,
  withAlpha,
} from "../styles/colorStandards";
import { stationAqi, AQI_NO_DATA_COLOR } from "../styles/aqi";
import { ONC_EOV_CATEGORIES, ONC_ALL_KNOWN_CATEGORIES } from "../types/onc";
import type { OncEov } from "../types/onc";
import { useLayerConfig, DECK_TO_TOGGLE } from "../utils/layerConfig";
import { gebcoTileUrl } from "../utils/gebcoTiles";
import { wodDecadeColor } from "../utils/wodDecades";
import { seepTypeColorRgba } from "../utils/seepTypes";
import { thawCategoryColorRgba, thawCategoryLineRgba } from "../utils/thawTypes";
import { elementColor } from "../utils/geotracesElements";
import { mosaicColor } from "../utils/mosaicVars";
import { seabedColor } from "../utils/seabedClasses";
import { bboxFromDrag, closePolygon, toggleHexCell } from "../utils/aoiGeometry";
import { ExportToolbar } from "./ExportToolbar";
import { useTranslation } from "react-i18next";
import {
  siosTopicColor, rampColor, divergingRampColor, _arcticCatchmentColor,
  RESOURCE_COLOR, hotspotPointColor, noiseRiskColor,
  MINING_FOOTPRINTS_FILL, MINING_FOOTPRINTS_STROKE,
  hydrophoneSourceColor,
} from "./map3d/colors";
import {
  type Box, expandBox, walkCoords, bboxToView, getBBoxCenter,
  approxViewBbox, bboxContains, expandBoxBuffer,
} from "./map3d/geometry";
import { makeSetFilter, oncEovVisible, tailingsHazardVisible } from "./map3d/filters";
import { hexPassesDecadeFilter, hexFilteredCount } from "./map3d/hexDecadeFilter";
import { decodeCurrentArrows, _currentsFieldLRU, lruPut } from "./map3d/currents";
import {
  type DepthCacheVal, depthCache, depthCacheKey,
  loadDepthCacheFromLS, scheduleDepthCacheFlush, depthFailedUntil,
  markDepthLookupFailed, depthLineFromCache,
} from "./map3d/depthCache";
import { BASEMAP, MAP_VIEW, tooltipStyle } from "./map3d/viewState";
import { useLayerFetcher } from "./map3d/useLayerFetcher";
import { useLayerData } from "./map3d/useLayerData";

// Re-exported so existing consumers (including src/__tests__/map3d-helpers.test.ts,
// which imports these from "../components/Map3D") keep working unchanged after the
// extraction into src/components/map3d/*.

const API = import.meta.env.VITE_API_BASE_URL ?? "";

// ── Ocean Currents decode helpers (module-scope, no React deps) ────────────

/** Decode a PNG blob into a flat RGBA array + dims via an offscreen canvas. */
async function decodeBlobToRGBA(blob: Blob): Promise<{ data: Uint8ClampedArray; width: number; height: number }> {
  const bmp = await createImageBitmap(blob);
  // Capture dims BEFORE close() — ImageBitmap.close() resets width/height to 0,
  // so reading them after close yields a 0x0 texture (empty data, NaN bands).
  const width = bmp.width;
  const height = bmp.height;
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d")!;
  ctx.drawImage(bmp, 0, 0);
  const img = ctx.getImageData(0, 0, width, height);
  bmp.close?.();
  return { data: img.data, width, height };
}


const _saved = loadMapState();
const _urlFly = (() => {
  const params = new URLSearchParams(window.location.search);
  const fly = params.get("fly");
  if (!fly) return null;
  const [lon, lat, z] = fly.split(",").map(Number);
  if (isNaN(lon) || isNaN(lat)) return null;
  // An explicit ?fly destination must win over any stale "return to where I
  // was" position saved on the last map unmount. Discard it here so the runtime
  // ?fly handler can't later override this destination with the previously
  // viewed feature. (Fixes "View on map" landing on the last-viewed vent.)
  consumeReturnFly();
  // Clean the URL param so it doesn't persist on refresh
  params.delete("fly");
  const clean = params.toString();
  window.history.replaceState({}, "", window.location.pathname + (clean ? `?${clean}` : ""));
  return { longitude: lon, latitude: lat, zoom: isNaN(z) ? 9 : z };
})();
// `?s=` — a shareable view link, read once at module init.
//
// ⭐ Unlike `?fly=` above, this param is NOT stripped once it has been applied.
// `useLiveShareUrl` now keeps it in step with what the map is showing, so the
// address bar is itself the shareable link. The old reason for stripping — "a
// refreshed link shouldn't re-fight the user's later navigation" — dissolves
// exactly when the URL becomes live: a reload now restores where the user
// actually is, which is not a fight but the point.
//
// ⛔ A param that FAILED to decode is still stripped. Leaving a malformed `s`
// in the bar would hand the reader a broken link to pass on, and the live
// writer only overwrites it on the first change — which may never come.
//
// ⛔ `?fly=`/`?focus=` mean "jump to one feature" and must still win over a
// whole restored view — a report back-link is more specific intent than a
// bookmarked view, so it is read FIRST (above) and this block never overrides
// a camera `_urlFly` already claimed.
const _urlShare = (() => {
  const params = new URLSearchParams(window.location.search);
  const raw = params.get("s");
  if (!raw) return null;
  const decoded = decodeShareState(raw);
  if (shouldStripShareParam(raw, decoded)) {
    params.delete("s");
    const clean = params.toString();
    window.history.replaceState({}, "", window.location.pathname + (clean ? `?${clean}` : ""));
  }
  if (!decoded) return null;
  // Filters are governed entirely by the store, not by React state threaded
  // through this component — applied here, once, before first render, so a
  // shared filter is visible in the very first paint rather than flashing
  // unfiltered-then-filtered.
  if (decoded.filters) applyShareableFilters(decoded.filters);
  // Same timing, same reason, different registry: the depth/decade/variable a
  // layer is drawn at. ⚠️ Applied BEFORE first render because these feed the
  // tile URLs — arriving late means the recipient fetches their own default
  // first and sees the sender's data replace it, which reads as a glitch.
  if (decoded.display) applyShareableDisplay(decoded.display);
  return decoded;
})();

const INITIAL_VIEW = {
  ...resolveInitialCamera(_urlFly, _urlShare?.camera ?? null, _saved?.viewState ?? null),
  minZoom: 2,
  maxZoom: 18,
};


async function prefetchDepth(lat: number, lon: number, apiBase: string): Promise<void> {
  loadDepthCacheFromLS();
  const key = depthCacheKey(lat, lon);
  if (depthCache.has(key)) return;  // already loading or loaded
  const retryAt = depthFailedUntil.get(key);
  if (retryAt != null && Date.now() < retryAt) return;  // recent failure — back off
  depthCache.set(key, "loading");
  try {
    const r = await fetch(`${apiBase}/api/v1/bathymetry/lookup?lat=${lat}&lon=${lon}`);
    if (!r.ok) { markDepthLookupFailed(key); return; }
    const d = await r.json();
    if (typeof d.depth_m === "number") {
      depthFailedUntil.delete(key);
      depthCache.set(key, d.depth_m < 0 ? d.depth_m : "land");
      scheduleDepthCacheFlush();
    } else {
      markDepthLookupFailed(key);  // unknown — retry after backoff
    }
  } catch {
    markDepthLookupFailed(key);
  }
}



// Chemosynthetic sites all share one color now — see CHESS_COLOR for why.
const CHESS_FILL_COLOR = withAlpha(CHESS_COLOR, 200);


/**
 * Ephemeral popup shown when the user clicks empty water with the bathymetry
 * layer on. Reads from the module-level depthCache populated by onHover
 * prefetch + onClick prefetch. Polls every 250ms for ~3s while waiting for
 * the cache to fill, then shows "Depth unavailable" if the lookup never
 * resolved. Dismisses on the × button or any subsequent map click (which
 * clears the pin via setBathymetryClickPin).
 */
function BathymetryClickPopup({
  pin, onClose,
}: { pin: { lat: number; lon: number; x: number; y: number }; onClose: () => void }) {
  const [depth, setDepth] = useState<DepthCacheVal | "unavailable" | null>(null);
  useEffect(() => {
    const key = depthCacheKey(pin.lat, pin.lon);
    let cancelled = false;
    let attempts = 0;
    const MAX_ATTEMPTS = 12;  // 12 × 250 ms ≈ 3 s, then give up
    const tick = () => {
      if (cancelled) return;
      const v = depthCache.get(key) ?? null;
      if (v !== "loading" && v !== null) {
        setDepth(v);  // resolved — depth number or "land"
        return;
      }
      if (++attempts > MAX_ATTEMPTS) {
        setDepth("unavailable");  // lookup failed or timed out — stop polling
        return;
      }
      setDepth(v);
      setTimeout(tick, 250);
    };
    tick();
    return () => { cancelled = true; };
  }, [pin.lat, pin.lon]);
  const meters = typeof depth === "number" ? Math.abs(Math.round(depth)) : null;
  const fmtCoord = (v: number) => v.toFixed(4);
  // Clamp to viewport so popup doesn't fall off the edge.
  const top = Math.max(8, pin.y - 70);
  const left = Math.max(8, pin.x + 12);
  return (
    <div
      className="absolute z-panel"
      style={{
        top, left,
        background: "rgba(10, 14, 22, 0.94)",
        color: "#e6edf6",
        fontSize: 12,
        padding: "8px 10px",
        borderRadius: 6,
        border: "1px solid rgba(255,255,255,0.12)",
        boxShadow: "0 4px 16px rgba(0,0,0,0.5)",
        minWidth: 180,
      }}
    >
      <button
        onClick={onClose}
        className="absolute top-1 right-1.5 text-white/65 hover:text-white text-base leading-none w-5 h-5"
        aria-label="Close"
      >×</button>
      <div className="text-[11px] uppercase tracking-wider text-white/65 mb-1">Seafloor depth</div>
      <div className="font-mono text-base">
        {meters != null ? (
          <><span>{meters.toLocaleString()}</span> <span className="text-white/70 text-xs">m below sea level</span></>
        ) : depth === "land" ? (
          <span className="text-white/70 text-xs">Land — no seafloor</span>
        ) : depth === "unavailable" ? (
          <span className="text-white/70 text-xs">Depth unavailable</span>
        ) : (
          <span className="text-white/65 text-xs">Looking up…</span>
        )}
      </div>
      <div className="mt-1.5 text-[11px] text-white/65 font-mono">
        {fmtCoord(pin.lat)}, {fmtCoord(pin.lon)}
      </div>
    </div>
  );
}

/**
 * Layers with no fly-to target in `flyConfigs` below.
 *
 * Group A — genuine rasters/animated fields: the frontend never holds a
 * feature list for these, only a `TileLayer`/`BitmapLayer` tile stack or (for
 * ocean-currents) a decoded texture. There is nothing to cycle through.
 *   bathymetry, ocean-currents, forest-loss, surface-water, carbon-flux, soil-carbon
 *
 * Group B — dual-mode field/hex layers: the frontend DOES fetch a real
 * PolygonLayer feature set for these (e.g. `seabedHexData`, `acidHexData`,
 * `vmeHex`, `chiHexData`, `coralExposureFeatures`), but that data was never
 * wired into flyToLayer's `layerMap` — clicking zoom either lands on a fixed
 * regional viewport from `rasterViews` (marine-carbon, seabed-substrate,
 * vme-suitability, coral-acid-exposure) or does nothing at all (the rest).
 * That is an existing gap in flyToLayer, not something this list fixes.
 *   woa-climatology, oxygen-deox, ocean-carbon, ocean-co2-surface,
 *   marine-carbon, seabed-substrate, vme-suitability, ocean-acidification,
 *   coral-acid-exposure, cumulative-human-impact
 */
const NO_FLY_TO = [
  // Group A — true rasters/animated fields, no client-side feature list ever.
  "bathymetry",
  "ocean-currents",
  "forest-loss",
  "surface-water",
  "carbon-flux",
  "soil-carbon",
  // Group B — hex/field dual-mode layers; real feature data exists client-side
  // but isn't wired into flyToLayer's layerMap.
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
] as const satisfies readonly LayerId[];

export function Map3D() {
  const { t } = useTranslation("common");
  const {
    activeLayers, setActiveLayers, setEnabledLayerIds,
    setVentConflicts, ventConflicts,
    plumeTraces, addPlumeTrace,
    plumeHistoryQueue, addPlumeHistory,
    ventStatusFilters, argoAlarmFilters,
    claimRiskFilters, hiddenContractors, iucnFilters, noiseRiskFilters,
  } = useMapStore();

  const { search: locationSearch } = useLocation();
  const oceansitesNetworkFilters = useMapStore(s => s.oceansitesNetworkFilters);
  const oceansitesStatusFilters  = useMapStore(s => s.oceansitesStatusFilters);
  const cableSourceFilters = useMapStore(s => s.cableSourceFilters);
  const sharePanelFailures = useMapStore(s => s.sharePanelFailures);
  const clearSharePanelFailures = useMapStore(s => s.clearSharePanelFailures);
  const arcticRiverSourceFilters = useMapStore(s => s.arcticRiverSourceFilters);
  const chessPhylumFilters  = useMapStore(s => s.chessPhylumFilters);
  const fireConfidenceFilters   = useMapStore(s => s.fireConfidenceFilters);
  const firesNearMiningOnly     = useMapStore(s => s.firesNearMiningOnly);
  const oncEovFilters           = useMapStore(s => s.oncEovFilters);
  const tailingsRiskFilters = useMapStore(s => s.tailingsRiskFilters);
  const tailingsStatusFilters = useMapStore(s => s.tailingsStatusFilters);
  const aisShipTypeFilters  = useMapStore(s => s.aisShipTypeFilters);
  const aisFlagFilters      = useMapStore(s => s.aisFlagFilters);
  const deepdataStationContractorFilters = useMapStore(s => s.deepdataStationContractorFilters);
  const hydrophoneSourceFilters = useMapStore(s => s.hydrophoneSourceFilters);
  const hydrophoneStatusFilters = useMapStore(s => s.hydrophoneStatusFilters);
  const hydrophoneDepthFilters  = useMapStore(s => s.hydrophoneDepthFilters);
  const offshoreActivityFilters = useMapStore(s => s.offshoreActivityFilters);
  const offshoreActivityCountryFilters = useMapStore(s => s.offshoreActivityCountryFilters);
  const vesselFocus         = useMapStore(s => s.vesselFocus);
  const setVesselFocus      = useMapStore(s => s.setVesselFocus);

  // Clear persisted vessel focus when the Live Vessels layer is turned off.
  useEffect(() => {
    if (vesselFocus && !activeLayers.has("ais-live")) setVesselFocus(null);
  }, [activeLayers, vesselFocus, setVesselFocus]);

  const wodDecadeFilters   = useMapStore(s => s.wodDecadeFilters);
  const mementoGas          = useMapStore(s => s.mementoGas);
  const mementoDisplayMode  = useMapStore(s => s.mementoDisplayMode);
  const mementoGasFilters   = useMapStore(s => s.mementoGasFilters);
  const mementoDecadeFilters = useMapStore(s => s.mementoDecadeFilters);
  const methaneSeepsFeatureTypeFilters = useMapStore(s => s.methaneSeepsFeatureTypeFilters);
  const thawTypeFilters = useMapStore(s => s.thawTypeFilters);
  const thawCategoryFilters = useMapStore(s => s.thawCategoryFilters);
  const permafrostSourceFilters = useMapStore(s => s.permafrostSourceFilters);
  const geotracesElement      = useMapStore(s => s.geotracesElement);
  const geotracesDisplayMode  = useMapStore(s => s.geotracesDisplayMode);
  const geotracesDecadeFilters = useMapStore(s => s.geotracesDecadeFilters);
  const mosaicVariable       = useMapStore(s => s.mosaicVariable);
  const mosaicDisplayMode    = useMapStore(s => s.mosaicDisplayMode);
  const mosaicDecadeFilters  = useMapStore(s => s.mosaicDecadeFilters);
  const arcticCatchmentsVariable = useMapStore(s => s.arcticCatchmentsVariable);
  const seabedDisplayMode  = useMapStore(s => s.seabedDisplayMode);
  const cascadeVariable      = useMapStore(s => s.cascadeVariable);
  const cascadeDisplayMode   = useMapStore(s => s.cascadeDisplayMode);
  const cascadeDecadeFilters = useMapStore(s => s.cascadeDecadeFilters);
  const currentsDepth      = useMapStore((s) => s.currentsDepth);
  const currentsDate       = useMapStore((s) => s.currentsDate);
  const setCurrentsDate    = useMapStore((s) => s.setCurrentsDate);
  const currentsPlaying    = useMapStore((s) => s.currentsPlaying);
  const setCurrentsPlaying = useMapStore((s) => s.setCurrentsPlaying);
  const woaVariable        = useMapStore((s) => s.woaVariable);
  const woaDepth           = useMapStore((s) => s.woaDepth);
  const woaDisplayMode     = useMapStore((s) => s.woaDisplayMode);
  const carbonVariable     = useMapStore((s) => s.carbonVariable);
  const carbonDepth        = useMapStore((s) => s.carbonDepth);
  const carbonDisplayMode  = useMapStore((s) => s.carbonDisplayMode);
  const acidificationVariable     = useMapStore((s) => s.acidificationVariable);
  const acidificationDepth        = useMapStore((s) => s.acidificationDepth);
  const acidificationDisplayMode  = useMapStore((s) => s.acidificationDisplayMode);
  const chiDisplayMode     = useMapStore((s) => s.chiDisplayMode);
  const co2Variable        = useMapStore((s) => s.co2Variable);
  const co2Decade          = useMapStore((s) => s.co2Decade);
  const co2DisplayMode     = useMapStore((s) => s.co2DisplayMode);
  const selectionMode      = useMapStore((s) => s.selectionMode);
  const aoiSelection       = useMapStore((s) => s.aoiSelection);
  const setAoiSelection    = useMapStore((s) => s.setAoiSelection);
  const setSelectionMode   = useMapStore((s) => s.setSelectionMode);
  const exportPanelOpen    = useMapStore((s) => s.exportPanelOpen);
  const clearAoiSelection  = useMapStore((s) => s.clearAoiSelection);
  const oxygenView         = useMapStore((s) => s.oxygenView);
  const oxygenDepth        = useMapStore((s) => s.oxygenDepth);
  const oxygenDisplayMode  = useMapStore((s) => s.oxygenDisplayMode);
  const {
    riskAreas,
    selectedFeatures,
    setSelectedFeature,
    setTracePlume,
    setFetchPlumeHistory,
    setRiskAreas,
    setFlyTo,
    setFlyToLayer,
    setSearchById,
    setVentsData: storeSetVentsData,
    bumpMapTap,
  } = useMapStore();

  const [claimsData,         setClaimsData]         = useState<ClaimFeatureCollection | null>(null);
  const [reservedData,       setReservedData]        = useState<FeatureCollection | null>(null);
  const [apeisData,          setApeisData]           = useState<FeatureCollection | null>(null);
  const [relinquishedData,   setRelinquishedData]    = useState<FeatureCollection | null>(null);
  const [argoData,           setArgoData]            = useState<FeatureCollection | null>(null);
  const [argoTrailsData,     setArgoTrailsData]      = useState<FeatureCollection | null>(null);
  const [ventsData,          setVentsData]           = useState<FeatureCollection | null>(null);
  const [hotspotsData,       setHotspotsData]        = useState<FeatureCollection | null>(null);

  const [noiseRiskData,    setNoiseRiskData]    = useState<FeatureCollection | null>(null);
  const [tectonicData,     setTectonicData]     = useState<{ boundaries: FeatureCollection; plates: FeatureCollection } | null>(null);

  // Land layers
  // miningFootprints: served as MVT tiles, no client-side state needed
  // (kbas, wdpa: withdrawn 2026-09-03 — no MVT layer or state at all)

  const [viewState,          setViewState]           = useState<Record<string, unknown>>(INITIAL_VIEW);
  const [isInteracting,      setIsInteracting]       = useState(false);
  const [restored,           setRestored]            = useState(false);
  const interactionTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Active "render bbox" for mining-footprints viewport culling. Held wider
  // than the visible viewport so small pans don't trigger refilter; widens
  // again only when the camera moves outside it. See effect below.
  const [miningRenderBbox, setMiningRenderBbox] = useState<Box | null>(null);
  const [loading,            setLoading]             = useState(true);
  const [currentsMeta,    setCurrentsMeta]    = useState<Record<string, CurrentsMeta> | null>(null);
  const [woaMeta,         setWoaMeta]         = useState<{ variables: Array<{ key: string; label: string; units: string; vmin: number; vmax: number; cmap: string; baseline: string; depths: number[]; ramp?: Array<{ pos: number; hex: string }> }>; depths: number[] } | null>(null);
  const [woaTiles,        setWoaTiles]        = useState<{ bounds: [number, number, number, number]; image: HTMLCanvasElement }[] | null>(null);
  const [carbonMeta,      setCarbonMeta]      = useState<{ variables: Array<{ key: string; label: string; units: string; vmin: number; vmax: number; cmap: string; baseline: string; depths: number[]; ramp?: Array<{ pos: number; hex: string }> }>; depths: number[] } | null>(null);
  const [carbonTiles,     setCarbonTiles]     = useState<{ bounds: [number, number, number, number]; image: HTMLCanvasElement }[] | null>(null);
  const [carbonHexData,   setCarbonHexData]   = useState<FeatureCollection | null>(null);
  const [acidMeta,        setAcidMeta]        = useState<{ variables: Array<{ key: string; label: string; units: string; vmin: number; vmax: number; center: number | null; kind: string; cmap: string; depths: number[]; ramp?: Array<{ pos: number; hex: string }> }>; depths: number[] } | null>(null);
  const [acidTiles,       setAcidTiles]       = useState<{ bounds: [number, number, number, number]; image: HTMLCanvasElement }[] | null>(null);
  const [acidHexData,     setAcidHexData]     = useState<FeatureCollection | null>(null);
  const [chiMeta,         setChiMeta]         = useState<{ variables: Array<{ key: string; label: string; units: string; vmin: number; vmax: number; cmap: string; ramp?: Array<{ pos: number; hex: string }> }> } | null>(null);
  const [chiHexData,      setChiHexData]      = useState<FeatureCollection | null>(null);
  const [co2Meta,         setCo2Meta]         = useState<{ variables: Array<{ key: string; label: string; units: string; vmin: number; vmax: number; cmap: string; ramp?: Array<{ pos: number; hex: string }> }>; decades: Array<{ index: number; label: string }> } | null>(null);
  const [co2Tiles,        setCo2Tiles]        = useState<{ bounds: [number, number, number, number]; image: HTMLCanvasElement }[] | null>(null);
  const [co2HexData,      setCo2HexData]      = useState<FeatureCollection | null>(null);
  const [oxygenMeta,  setOxygenMeta]  = useState<{ views: Array<{ key: string; label: string; units: string; vmin: number; vmax: number; cmap: string; ramp: Array<{ pos: number; hex: string }>; depths: number[]; diverging: boolean }>; depths: number[]; attribution: string } | null>(null);
  const [oxygenTiles, setOxygenTiles] = useState<{ bounds: [number, number, number, number]; image: HTMLCanvasElement }[] | null>(null);
  const [woaHexData,    setWoaHexData]    = useState<FeatureCollection | null>(null);
  const [oxygenHexData,  setOxygenHexData]  = useState<FeatureCollection | null>(null);
  const [mementoHexData, setMementoHexData] = useState<FeatureCollection | null>(null);
  const [geotracesHexData, setGeotracesHexData] = useState<FeatureCollection | null>(null);
  const [mosaicHexData, setMosaicHexData] = useState<FeatureCollection | null>(null);

  // Filter the decade at the data level, not through a transparent fill. deck.gl
  // picks and highlights on geometry, ignoring alpha — a hex hidden by alpha alone
  // still flashes white under the cursor and still answers a click. Dropping it
  // from `data` is the only way it is genuinely gone.
  const visibleMementoHexes = useMemo(
    () => (mementoHexData?.features ?? []).filter(f => hexPassesDecadeFilter((f as any).properties, mementoDecadeFilters)),
    [mementoHexData, mementoDecadeFilters]
  );
  const visibleGeotracesHexes = useMemo(
    () => (geotracesHexData?.features ?? []).filter(f => hexPassesDecadeFilter((f as any).properties, geotracesDecadeFilters)),
    [geotracesHexData, geotracesDecadeFilters]
  );
  const visibleMosaicHexes = useMemo(
    () => (mosaicHexData?.features ?? []).filter(f => hexPassesDecadeFilter((f as any).properties, mosaicDecadeFilters)),
    [mosaicHexData, mosaicDecadeFilters]
  );
  const [seabedHexData, setSeabedHexData] = useState<any>(null);
  // Decoded velocity field for the animated 2D-canvas particle overlay.
  const [currentsField,   setCurrentsField]   = useState<VelocityField | null>(null);
  const [currentsArrows,  setCurrentsArrows]  = useState<CurrentArrow[] | null>(null);
  const [reduceMotion,    setReduceMotion]    = useState<boolean>(
    () => typeof window !== "undefined" &&
          window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true
  );

  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    if (!mq) return;
    const onChange = () => setReduceMotion(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  // Bumping this re-keys MVTLayer data URLs (?v=N) so deck.gl forgets its
  // internal failed-tile cache and refetches every visible tile. Only bumped
  // by explicit Retry button — never auto-bumped on recovery (that causes
  // a cascade where every layer refetches whenever any tile succeeds).
  const [tileCacheVersion,   setTileCacheVersion]    = useState(26); // v26: wod-oxygen re-synced (ragged-array fix), memento ch4_surf/n2o_surf recomputed water-only
  // Tile errors are noisy (backend restarts briefly drop tiles). Only surface
  // the layer as failed after MANY consecutive errors, and clear on first
  // success. A 3-5 s deploy window can easily produce 5-10 errors per layer
  // (deck.gl prefetches dozens of tiles), so the threshold needs headroom.
  const tileErrorCountRef = useRef<Map<string, number>>(new Map());
  const TILE_FAIL_THRESHOLD = 20;
  const onTileLayerError = useCallback((name: string) => {
    const next = (tileErrorCountRef.current.get(name) ?? 0) + 1;
    tileErrorCountRef.current.set(name, next);
    if (next >= TILE_FAIL_THRESHOLD) {
      setFailedLayers(prev => (prev.includes(name) ? prev : [...prev, name]));
    }
  }, []);
  const onTileLayerLoad = useCallback((name: string) => {
    tileErrorCountRef.current.set(name, 0);
    setFailedLayers(prev => (prev.includes(name) ? prev.filter(n => n !== name) : prev));
  }, []);
  const retryFailedLayers = useCallback(() => {
    tileErrorCountRef.current.clear();
    setFailedLayers([]);
    setTileCacheVersion(v => v + 1);
    // ⛔ Without this the button only HID the message. Bumping the tile cache
    // re-requests tiles; the 31 GeoJSON layers behind fetchGuarded were never
    // re-fetched, because their effects depend on activeLayers and fetchGuarded
    // and neither changed. The layer stayed empty and stopped saying so.
    retryGuardedLayers();
    // Deps stay empty: this callback is declared above useLayerFetcher(), so
    // naming those bindings here would evaluate them in the temporal dead zone.
    // Both are stable — a setState setter and a useCallback([], …).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const [isTracing,          setIsTracing]           = useState(false);
  const [legendOpen,         setLegendOpen]          = useState(false);
  const legendFocusLayer = useMapStore(s => s.legendFocusLayer);
  useEffect(() => { if (legendFocusLayer) setLegendOpen(true); }, [legendFocusLayer]);
  // Ephemeral popup for empty-water clicks while bathymetry is on.
  // {x,y} are SCREEN pixels at click time — popup stays put if user pans
  // (intentional simplification; re-click to move).
  const [bathymetryClickPin, setBathymetryClickPin] = useState<{
    lat: number; lon: number; x: number; y: number;
  } | null>(null);
  // Hide the depth pin when the bathymetry layer is toggled off.
  useEffect(() => {
    if (!activeLayers.has("bathymetry")) setBathymetryClickPin(null);
  }, [activeLayers]);

  const setLayerProgress = useMapStore(s => s.setLayerProgress);
  const markLayerDone = useMapStore(s => s.markLayerDone);

  const [layerOrder, , enabledLayerIds] = useLayerConfig();
  useEffect(() => { setEnabledLayerIds(enabledLayerIds); }, [enabledLayerIds, setEnabledLayerIds]);

  const { fetchLayer, fetchGuarded, failedLayers, setFailedLayers, retryGuardedLayers } = useLayerFetcher();
  const {
    eezData, protectedSitesData, seamountsData, oceansitesData, oncData, chessData,
    cablesData, oncCablesData, ooiCablesData, noaaCablesData, nzCablesData, auCablesData,
    oncInstrumentsData, deepdataStationsData, hydrophoneData, portsData,
    miningFootprintsData, tailingsData, firesData, airQualityData, landslidesData,
    damsData, vesselEventsData, aisLiveData, arcticRiversData, siosData,
    methaneSeepsData, permafrostThawData, cascadeStationsData, monitoringDensityData,
  } = useLayerData(activeLayers, fetchGuarded);

  // Ref that always points to current layer data — read by SearchBar on each keystroke
  const searchDataRef = useRef<Record<string, FeatureCollection | null>>({});
  const [searchDataVersion, setSearchDataVersion] = useState(0);
  useEffect(() => {
    searchDataRef.current = {
      claims: claimsData, reserved: reservedData, relinquished: relinquishedData,
      seamounts: seamountsData, argo: argoData, vents: ventsData,
      eez: eezData, protectedSites: protectedSitesData, hotspots: hotspotsData,
      oceansites: oceansitesData, onc: oncData, chess: chessData,
      cables: cablesData, oncCables: oncCablesData, ooiCables: ooiCablesData, noaaCables: noaaCablesData, nzCables: nzCablesData, auCables: auCablesData, oncInstruments: oncInstrumentsData, ports: portsData,
      deepdataStations: deepdataStationsData,
      hydrophones: hydrophoneData,
      tectonic: tectonicData?.boundaries ?? null,
      tailings: tailingsData, fires: firesData, airQuality: airQualityData,
      landslides: landslidesData, dams: damsData, arcticRivers: arcticRiversData,
      vessels: vesselEventsData,
      aisLive: aisLiveData,
      miningFootprints: miningFootprintsData,
      memento: NO_CLIENT_COPY, // MVT-only — see NO_CLIENT_COPY: a bare null reads as "still loading"
      geotraces: NO_CLIENT_COPY, // MVT-only — see NO_CLIENT_COPY: a bare null reads as "still loading"
      mosaic: NO_CLIENT_COPY, // MVT-only — see NO_CLIENT_COPY: a bare null reads as "still loading"
      methaneSeeps: methaneSeepsData,
      sios: siosData,
      arcticSedimentCarbon: cascadeStationsData,
      permafrostThaw: permafrostThawData,
    };
    setSearchDataVersion(v => v + 1);
  }, [claimsData, reservedData, relinquishedData, seamountsData, argoData, ventsData, eezData, protectedSitesData, hotspotsData, oceansitesData, oncData, chessData, cablesData, oncCablesData, ooiCablesData, noaaCablesData, nzCablesData, auCablesData, oncInstrumentsData, portsData, deepdataStationsData, hydrophoneData, tectonicData, tailingsData, firesData, airQualityData, landslidesData, damsData, vesselEventsData, aisLiveData, arcticRiversData, miningFootprintsData, methaneSeepsData, siosData, cascadeStationsData, permafrostThawData]);

  const mapRef = useRef<any>(null);

  const argoTrailsFetchedRef     = useRef(false);
  const hotspotsFetchStartedRef  = useRef(false);
  const ventConflictsFetchedRef = useRef(false);
  const tectonicFetchedRef      = useRef(false);
  const noiseRiskFetchedRef     = useRef(false);
  const currentsFetchedRef      = useRef(false);
  const woaFetchedRef           = useRef(false);
  const oxygenFetchedRef        = useRef(false);
  const carbonFetchedRef        = useRef(false);
  const acidFetchedRef          = useRef(false);
  const chiFetchedRef           = useRef(false);
  const co2FetchedRef           = useRef(false);

  // Land layer fetch guards (kbas, wdpa withdrawn 2026-09-03 — nothing to fetch;
  // mining-footprints is GeoJSON now — small enough to ship simplified)
  const firesNearMiningFetchedRef   = useRef(false);
  const [firesNearMiningSet, setFiresNearMiningSet] = useState<Set<number> | null>(null);

  const riskAreasRef     = useRef(riskAreas);
  const viewStateRef     = useRef<Record<string, unknown>>(INITIAL_VIEW);
  const fetchedTracesRef = useRef<Set<string>>(new Set());
  const fetchedPlumesRef = useRef<Set<string>>(new Set());
  const fetchedHotspotTilesRef = useRef<Set<string>>(new Set());
  const seenHotspotCoordsRef  = useRef<Set<string>>(new Set());
  const layerFlyIndexRef = useRef<Record<string, number>>({});
  type OffshoreBbox = { id: number; west: number; south: number; east: number; north: number };
  const offshoreBboxCacheRef = useRef<Map<string, OffshoreBbox[]>>(new Map());
  const saveTimerRef     = useRef<ReturnType<typeof setTimeout> | null>(null);
  const latestStateRef   = useRef<{ viewState: Record<string, unknown>; activeLayers: Set<LayerId> } | null>(null);
  const dragStart        = useRef<[number, number] | null>(null);

  // ── AOI polygon + hex state ─────────────────────────────────────────────
  const [polyVerts, setPolyVerts] = useState<number[][]>([]);

  // When the export panel closes, clear the drawn AOI + any in-progress polygon so the
  // marked square disappears from the map (the selection lives in the store otherwise).
  useEffect(() => {
    if (!exportPanelOpen) {
      clearAoiSelection();
      setPolyVerts([]);
    }
  }, [exportPanelOpen, clearAoiSelection]);
  const [hexGridData, setHexGridData] = useState<FeatureCollection | null>(null);
  // Tracks last click time for double-click detection in polygon mode.
  const lastPolyClickRef = useRef<number>(0);
  // Stable ref so the keyboard handler (empty-deps effect) can read current verts.
  const polyVertsRef = useRef<number[][]>([]);
  polyVertsRef.current = polyVerts;

  // Fetch monitoring-density hex grid when hex selection mode is active.
  useEffect(() => {
    if (selectionMode !== "hexes") { setHexGridData(null); return; }
    fetchWithProgress(`${API}/api/v2/map/monitoring-density`, () => {})
      .then((fc) => setHexGridData(fc as FeatureCollection))
      .catch(() => {});
  }, [selectionMode]);

  // Keyboard shortcuts for polygon draw mode (Enter = close, Escape = cancel).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const mode = useMapStore.getState().selectionMode;
      if (mode === "polygon") {
        if (e.key === "Enter" && polyVertsRef.current.length >= 3) {
          useMapStore.getState().setAoiSelection({
            mode: "polygon",
            polygon: closePolygon(polyVertsRef.current),
          });
          setPolyVerts([]);
          useMapStore.getState().setSelectionMode(null);
          lastPolyClickRef.current = 0;
        } else if (e.key === "Escape") {
          setPolyVerts([]);
          lastPolyClickRef.current = 0;
          useMapStore.getState().setSelectionMode(null);
        }
      } else if (mode && e.key === "Escape") {
        useMapStore.getState().setSelectionMode(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // ── Initial data fetch ──────────────────────────────────────────────────
  useEffect(() => {
    // Read localStorage fresh (not the module-level _saved which is stale
    // after unmount/remount cycles, e.g. returning from a report page).
    const freshSaved = loadMapState();
    const resolved = resolveInitialLayers(
      // The envelope, not `?.layers` — see resolveInitialLayers: flattening it
      // here makes "camera-only link" indistinguishable from "no link".
      _urlShare,
      freshSaved,
      LAYER_CONFIGS.map(cfg => cfg.id),
    );
    if (resolved) {
      setActiveLayers(resolved);
      // ⛔ Only for a link, and only here. A link's layers can land in a menu
      // section this reader has collapsed: tested on production, seven land
      // layers arrived ACTIVE and drawn, with the whole "LAND DATA" section
      // shut — which reads as "the link lost half my layers". The saved-state
      // path deliberately does NOT do this; re-opening a section the visitor
      // closed on purpose, on every reload, is a different bug.
      if (linkCarriesView(_urlShare)) applyMenuExpansion(resolved);
    }
    // From here the view is the one the page opens with; anything after this
    // is the reader's own doing and may go in the address bar.
    setRestored(true);

    fetchLayer("/api/v1/map/claims", fc => { setClaimsData(fc as ClaimFeatureCollection); setLoading(false); }, "Mining Concessions")
      .then(failed => {
        if (failed) { setLoading(false); setFailedLayers(prev => [...prev, failed]); }
      });

    Promise.all([
      fetchLayer("/api/v1/map/reserved-areas",     setReservedData,     "Reserved Areas"),
      fetchLayer("/api/v1/map/apeis",              setApeisData,        "Protected Areas (APEIs)"),
      fetchLayer("/api/v1/map/relinquished-areas", setRelinquishedData, "Relinquished Areas"),
      fetchLayer("/api/v1/map/argo",               setArgoData,         "Argo Floats"),
      fetchLayer("/api/v1/map/vents",              d => { setVentsData(d); storeSetVentsData(d); }, "Hydrothermal Vents"),
    ]).then(results => {
      const failed = results.filter((r): r is string => typeof r === "string");
      if (failed.length) setFailedLayers(prev => [...prev, ...failed]);
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Lazy argo trails / tectonic plates / vent-mining conflicts ────────────
  // (the plain fetchGuarded-on-activation layers now live in useLayerData)
  useEffect(() => {
    if (activeLayers.has("argo") && !argoTrailsFetchedRef.current) {
      argoTrailsFetchedRef.current = true;
      fetchWithProgress(
        `${API}/api/v1/map/argo/trails`,
        (received, total) => setLayerProgress("Argo Trails", received, total),
      )
        .then(d => { if (d) setArgoTrailsData(d); markLayerDone("Argo Trails"); })
        .catch(() => { markLayerDone("Argo Trails"); });
    }
    if (activeLayers.has("tectonic-plates") && !tectonicFetchedRef.current) {
      tectonicFetchedRef.current = true;
      setLayerProgress("Tectonic Plates", 0, 1);
      Promise.all([
        fetch("https://raw.githubusercontent.com/fraxen/tectonicplates/master/GeoJSON/PB2002_boundaries.json").then(r => r.json()),
        fetch("https://raw.githubusercontent.com/fraxen/tectonicplates/master/GeoJSON/PB2002_plates.json").then(r => r.json()),
      ]).then(([boundaries, plates]) => {
        setTectonicData({ boundaries, plates });
        markLayerDone("Tectonic Plates");
      }).catch(() => { markLayerDone("Tectonic Plates"); setFailedLayers(prev => [...prev, "Tectonic Plates"]); });
    }

    if (activeLayers.has("contracts") && activeLayers.has("hydrothermal-vents") && !ventConflictsFetchedRef.current) {
      ventConflictsFetchedRef.current = true;
      fetchWithProgress(
        `${API}/api/v1/conflicts/vent-mining`,
        (received, total) => setLayerProgress("Vent Conflicts", received, total),
      )
        .then((rows: Array<{ isa_id: string; vent_name: string; vent_status: string; depth_m: number | null; risk_level: string }> | null) => {
          if (rows) {
            const byId: Record<string, typeof rows> = {};
            for (const row of rows) {
              if (!byId[row.isa_id]) byId[row.isa_id] = [];
              byId[row.isa_id].push(row);
            }
            setVentConflicts(byId);
          }
          markLayerDone("Vent Conflicts");
        })
        .catch(() => { markLayerDone("Vent Conflicts"); });
    }
  }, [activeLayers]);

  // ── Fires-near-mining overlap — lazy fetch when filter toggled on ──────────
  // Fetches IDs from the precomputed overlap_mining_fires view (25 km radius,
  // index-driven). Result is a Set for O(1) lookup inside filteredFiresFeatures.
  useEffect(() => {
    if (!firesNearMiningOnly || firesNearMiningFetchedRef.current) return;
    firesNearMiningFetchedRef.current = true;
    fetch(`${API}/api/v2/overlaps/mining-fires`)
      .then(r => { if (!r.ok) throw new Error(r.statusText); return r.json(); })
      .then((rows: { fire_id: number }[]) => setFiresNearMiningSet(new Set(rows.map(r => r.fire_id))))
      .catch(() => {
        firesNearMiningFetchedRef.current = false;
        setFailedLayers(prev => prev.includes("Mining-fire overlap") ? prev : [...prev, "Mining-fire overlap"]);
      });
  }, [firesNearMiningOnly]);

  // ── Global hotspot fetch — viewport-first, incremental, with byte-level progress ──
  useEffect(() => {
    if (!activeLayers.has("biodiversity-hotspots") || loading || hotspotsFetchStartedRef.current) return;
    hotspotsFetchStartedRef.current = true;

    const tiles: [number, number, number, number][] = [];
    const lonSteps = [-180, -90, 0, 90, 180];
    const latSteps = [-90, -30, 30, 90];
    for (let li = 0; li < latSteps.length - 1; li++) {
      for (let lo = 0; lo < lonSteps.length - 1; lo++) {
        tiles.push([lonSteps[lo], latSteps[li], lonSteps[lo + 1], latSteps[li + 1]]);
      }
    }

    // Split into viewport tile(s) and the rest
    const vLon = viewState.longitude as number;
    const vLat = viewState.latitude as number;
    const priorityTiles: typeof tiles = [];
    const remainingTiles: typeof tiles = [];
    for (const t of tiles) {
      if (vLon >= t[0] && vLon < t[2] && vLat >= t[1] && vLat < t[3]) {
        priorityTiles.push(t);
      } else {
        remainingTiles.push(t);
      }
    }
    // Fallback: if viewport is outside all tiles (edge/pole), just use the first tile
    if (priorityTiles.length === 0) {
      priorityTiles.push(tiles[0]);
      remainingTiles.splice(0, remainingTiles.length, ...tiles.slice(1));
    }

    // Seed immediately so layer condition (`&& hotspotsData`) becomes true
    setHotspotsData({ type: "FeatureCollection", features: [] });

    // Aggregated progress tracking across all tiles
    const tileProgress: { received: number; total: number }[] = tiles.map(() => ({ received: 0, total: 0 }));
    const reportAggregated = () => {
      let sumReceived = 0, sumTotal = 0;
      for (const tp of tileProgress) { sumReceived += tp.received; sumTotal += tp.total; }
      setLayerProgress("OBIS Species (Deep)", sumReceived, sumTotal);
    };

    let completed = 0;
    let totalMerged = 0;
    const total = tiles.length;

    const fetchTile = (tile: [number, number, number, number], tileIdx: number) => {
      const [minLon, minLat, maxLon, maxLat] = tile;
      return fetchWithProgress(
        `${API}/api/v1/map/biodiversity/hotspots?min_lon=${minLon}&max_lon=${maxLon}&min_lat=${minLat}&max_lat=${maxLat}&zoom=8`,
        (received, t) => { tileProgress[tileIdx] = { received, total: t }; reportAggregated(); },
      )
        .catch(() => ({ type: "FeatureCollection" as const, features: [] }))
        .then((fc: any) => {
          completed++;
          if (fc?.features?.length) {
            totalMerged += fc.features.length;
            setHotspotsData(prev => {
              const seenCoords = seenHotspotCoordsRef.current;
              const newFeatures = fc.features.filter((f: any) => {
                const c = f.geometry?.coordinates;
                if (!c) return false;
                const key = `${c[0]},${c[1]}`;
                if (seenCoords.has(key)) return false;
                seenCoords.add(key);
                return true;
              });
              if (!prev) return { type: "FeatureCollection" as const, features: newFeatures };
              return newFeatures.length ? { ...prev, features: [...prev.features, ...newFeatures] } : prev;
            });
          }
          if (completed === total) {
            if (totalMerged === 0) {
              setHotspotsData(null);
              setFailedLayers(prev => [...prev, "OBIS Species (Deep)"]);
            }
            markLayerDone("OBIS Species (Deep)");
          }
        });
    };

    // Map original tile indices for progress tracking
    const allTilesOrdered = [...priorityTiles, ...remainingTiles];
    const tileIndices = allTilesOrdered.map(t => tiles.indexOf(t));

    // Phase 1: Fetch viewport tile(s) first, await them
    const priorityPromises = priorityTiles.map((t, i) => fetchTile(t, tileIndices[i]));
    Promise.all(priorityPromises).then(() => {
      // Phase 2: Fire remaining tiles in parallel
      const offset = priorityTiles.length;
      for (let i = 0; i < remainingTiles.length; i++) {
        fetchTile(remainingTiles[i], tileIndices[offset + i]);
      }
    });
  }, [activeLayers, loading, setLayerProgress, markLayerDone]);


  useEffect(() => {
    if (!activeLayers.has("noise-risk") || noiseRiskFetchedRef.current) return;
    noiseRiskFetchedRef.current = true;
    fetchWithProgress(
      `${API}/api/v1/map/noise/risk-grid`,
      (received, total) => setLayerProgress("Noise Risk Grid", received, total),
    )
      .then(d => { if (d) setNoiseRiskData(d); markLayerDone("Noise Risk Grid"); })
      .catch(() => { markLayerDone("Noise Risk Grid"); setFailedLayers(prev => [...prev, "Noise Risk Grid"]); });
  }, [activeLayers, setLayerProgress, markLayerDone]);


  // ── Ocean Currents: fetch meta when layer activates ────────────────────────
  const currentsActive = activeLayers.has("ocean-currents");

  useEffect(() => {
    if (!currentsActive || currentsFetchedRef.current) return;
    currentsFetchedRef.current = true;
    fetch(`${API}/api/v1/currents/meta`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((m: Record<string, CurrentsMeta>) => {
        if (!m || Object.keys(m).length === 0) throw new Error("empty currents meta");
        setCurrentsMeta(m);
      })
      .catch(() => {
        currentsFetchedRef.current = false; // allow retry on next toggle
        setFailedLayers((prev) => (prev.includes("Ocean Currents") ? prev : [...prev, "Ocean Currents"]));
      });
  }, [currentsActive]);

  // ── WOA Climatology: fetch meta when layer activates ──────────────────────
  const woaActive = activeLayers.has("woa-climatology");

  useEffect(() => {
    if (!woaActive || woaFetchedRef.current) return;
    woaFetchedRef.current = true;
    fetch(`${API}/api/v1/woa/meta`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((m) => {
        if (!m?.variables?.length) throw new Error("empty woa meta");
        setWoaMeta(m);
      })
      .catch(() => {
        woaFetchedRef.current = false; // allow retry on next toggle
        setFailedLayers((prev) => (prev.includes("WOA Climatology") ? prev : [...prev, "WOA Climatology"]));
      });
  }, [woaActive]);

  // Slice the WOA field PNG into a grid of small BitmapLayer tiles. One global
  // BitmapLayer quad renders only a partial band under map pitch; small per-tile
  // quads cover the full map (same approach as the bathymetry tiles). Tiles are
  // clamped to the web-mercator latitude limit (±85.05°) — a tile reaching ±90°
  // is a degenerate quad in mercator and fails to render (the polar gaps). Edges
  // use shared integer pixel boundaries so adjacent tiles never leave seams.
  useEffect(() => {
    if (!woaActive) { setWoaTiles(null); return; }
    let cancelled = false;
    setWoaTiles(null); // drop the previous variable/depth tiles so none linger with a stale texture
    (async () => {
      try {
        const resp = await fetch(`${API}/api/v1/woa/${woaVariable}/${woaDepth}.png`);
        if (!resp.ok) throw new Error(String(resp.status));
        const bmp = await createImageBitmap(await resp.blob());
        const W = bmp.width, H = bmp.height; // 360×180 (1°/px), row 0 = north
        const MAXLAT = 85.0511;
        const yTop = Math.round(((90 - MAXLAT) / 180) * H);
        const yBot = Math.round(((90 + MAXLAT) / 180) * H);
        const COLS = 9, ROWS = 6;
        const xs = Array.from({ length: COLS + 1 }, (_, i) => Math.round((i * W) / COLS));
        const ys = Array.from({ length: ROWS + 1 }, (_, i) => Math.round(yTop + (i * (yBot - yTop)) / ROWS));
        const lonOf = (px: number) => -180 + (px / W) * 360;
        const latOf = (py: number) => 90 - (py / H) * 180;
        const tiles: { bounds: [number, number, number, number]; image: HTMLCanvasElement }[] = [];
        for (let cy = 0; cy < ROWS; cy++) {
          for (let cx = 0; cx < COLS; cx++) {
            const sx = xs[cx], sw = xs[cx + 1] - xs[cx];
            const sy = ys[cy], sh = ys[cy + 1] - ys[cy];
            if (sw <= 0 || sh <= 0) continue;
            const cv = document.createElement("canvas");
            cv.width = sw; cv.height = sh;
            cv.getContext("2d")!.drawImage(bmp, sx, sy, sw, sh, 0, 0, sw, sh);
            // bounds = [west, south, east, north]
            tiles.push({ bounds: [lonOf(sx), latOf(ys[cy + 1]), lonOf(xs[cx + 1]), latOf(sy)], image: cv });
          }
        }
        bmp.close();
        if (!cancelled) setWoaTiles(tiles);
      } catch {
        if (!cancelled) setWoaTiles(null);
      }
    })();
    return () => { cancelled = true; };
  }, [woaActive, woaVariable, woaDepth]);

  // ── Ocean Carbon (GLODAP): fetch meta when layer activates ─────────────────
  const carbonActive = activeLayers.has("ocean-carbon");

  useEffect(() => {
    if (!carbonActive || carbonFetchedRef.current) return;
    carbonFetchedRef.current = true;
    fetch(`${API}/api/v1/carbon/meta`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((m) => {
        if (!m?.variables?.length) throw new Error("empty carbon meta");
        setCarbonMeta(m);
      })
      .catch(() => {
        carbonFetchedRef.current = false; // allow retry on next toggle
        setFailedLayers((prev) => (prev.includes("Ocean Carbon") ? prev : [...prev, "Ocean Carbon"]));
      });
  }, [carbonActive]);

  // Slice the carbon field PNG into BitmapLayer tiles — identical approach to woaTiles.
  useEffect(() => {
    if (!carbonActive) { setCarbonTiles(null); return; }
    let cancelled = false;
    setCarbonTiles(null); // drop previous variable/depth tiles so none linger with a stale texture
    (async () => {
      try {
        const resp = await fetch(`${API}/api/v1/carbon/${carbonVariable}/${carbonDepth}.png`);
        if (!resp.ok) throw new Error(String(resp.status));
        const bmp = await createImageBitmap(await resp.blob());
        const W = bmp.width, H = bmp.height; // 360×180 (1°/px), row 0 = north
        const MAXLAT = 85.0511;
        const yTop = Math.round(((90 - MAXLAT) / 180) * H);
        const yBot = Math.round(((90 + MAXLAT) / 180) * H);
        const COLS = 9, ROWS = 6;
        const xs = Array.from({ length: COLS + 1 }, (_, i) => Math.round((i * W) / COLS));
        const ys = Array.from({ length: ROWS + 1 }, (_, i) => Math.round(yTop + (i * (yBot - yTop)) / ROWS));
        const lonOf = (px: number) => -180 + (px / W) * 360;
        const latOf = (py: number) => 90 - (py / H) * 180;
        const tiles: { bounds: [number, number, number, number]; image: HTMLCanvasElement }[] = [];
        for (let cy = 0; cy < ROWS; cy++) {
          for (let cx = 0; cx < COLS; cx++) {
            const sx = xs[cx], sw = xs[cx + 1] - xs[cx];
            const sy = ys[cy], sh = ys[cy + 1] - ys[cy];
            if (sw <= 0 || sh <= 0) continue;
            const cv = document.createElement("canvas");
            cv.width = sw; cv.height = sh;
            cv.getContext("2d")!.drawImage(bmp, sx, sy, sw, sh, 0, 0, sw, sh);
            // bounds = [west, south, east, north]
            tiles.push({ bounds: [lonOf(sx), latOf(ys[cy + 1]), lonOf(xs[cx + 1]), latOf(sy)], image: cv });
          }
        }
        bmp.close();
        if (!cancelled) setCarbonTiles(tiles);
      } catch {
        if (!cancelled) setCarbonTiles(null);
      }
    })();
    return () => { cancelled = true; };
  }, [carbonActive, carbonVariable, carbonDepth]);

  // ── Carbon hex grid ───────────────────────────────────────────────────────
  useEffect(() => {
    if (!carbonActive || carbonDisplayMode !== "hexes") { setCarbonHexData(null); return; }
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetch(`${API}/api/v1/carbon/hexes?variable=${carbonVariable}&depth=${carbonDepth}`);
        if (!resp.ok) throw new Error(String(resp.status));
        const fc: FeatureCollection = await resp.json();
        if (!cancelled) setCarbonHexData(fc);
      } catch {
        if (!cancelled) {
          setCarbonHexData(null);
          setFailedLayers((prev) => prev.includes("Ocean Carbon") ? prev : [...prev, "Ocean Carbon"]);
        }
      }
    })();
    return () => { cancelled = true; };
  }, [carbonActive, carbonDisplayMode, carbonVariable, carbonDepth]);

  // ── Ocean Acidification (GLODAP Ω): fetch meta when layer activates ───────
  const acidActive = activeLayers.has("ocean-acidification");

  useEffect(() => {
    if (!acidActive || acidFetchedRef.current) return;
    acidFetchedRef.current = true;
    fetch(`${API}/api/v1/acidification/meta`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((m) => {
        if (!m?.variables?.length) throw new Error("empty acidification meta");
        setAcidMeta(m);
      })
      .catch(() => {
        acidFetchedRef.current = false; // allow retry on next toggle
        setFailedLayers((prev) => (prev.includes("Ocean Acidification") ? prev : [...prev, "Ocean Acidification"]));
      });
  }, [acidActive]);

  // Slice the acidification field PNG into BitmapLayer tiles — identical approach to carbonTiles.
  useEffect(() => {
    if (!acidActive) { setAcidTiles(null); return; }
    let cancelled = false;
    setAcidTiles(null); // drop previous variable/depth tiles so none linger with a stale texture
    (async () => {
      try {
        const url = acidificationVariable === "horizon"
          ? `${API}/api/v1/acidification/horizon.png`
          : acidificationVariable === "horizon-shift"
            ? `${API}/api/v1/acidification/horizon-shift.png`
            : `${API}/api/v1/acidification/${acidificationVariable}/${acidificationDepth}.png`;
        const resp = await fetch(url);
        if (!resp.ok) throw new Error(String(resp.status));
        const bmp = await createImageBitmap(await resp.blob());
        const W = bmp.width, H = bmp.height; // 360×180 (1°/px), row 0 = north
        const MAXLAT = 85.0511;
        const yTop = Math.round(((90 - MAXLAT) / 180) * H);
        const yBot = Math.round(((90 + MAXLAT) / 180) * H);
        const COLS = 9, ROWS = 6;
        const xs = Array.from({ length: COLS + 1 }, (_, i) => Math.round((i * W) / COLS));
        const ys = Array.from({ length: ROWS + 1 }, (_, i) => Math.round(yTop + (i * (yBot - yTop)) / ROWS));
        const lonOf = (px: number) => -180 + (px / W) * 360;
        const latOf = (py: number) => 90 - (py / H) * 180;
        const tiles: { bounds: [number, number, number, number]; image: HTMLCanvasElement }[] = [];
        for (let cy = 0; cy < ROWS; cy++) {
          for (let cx = 0; cx < COLS; cx++) {
            const sx = xs[cx], sw = xs[cx + 1] - xs[cx];
            const sy = ys[cy], sh = ys[cy + 1] - ys[cy];
            if (sw <= 0 || sh <= 0) continue;
            const cv = document.createElement("canvas");
            cv.width = sw; cv.height = sh;
            cv.getContext("2d")!.drawImage(bmp, sx, sy, sw, sh, 0, 0, sw, sh);
            // bounds = [west, south, east, north]
            tiles.push({ bounds: [lonOf(sx), latOf(ys[cy + 1]), lonOf(xs[cx + 1]), latOf(sy)], image: cv });
          }
        }
        bmp.close();
        if (!cancelled) setAcidTiles(tiles);
      } catch {
        if (!cancelled) setAcidTiles(null);
      }
    })();
    return () => { cancelled = true; };
  }, [acidActive, acidificationVariable, acidificationDepth]);

  // ── Acidification hex grid ───────────────────────────────────────────────
  useEffect(() => {
    if (!acidActive || acidificationDisplayMode !== "hexes") { setAcidHexData(null); return; }
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetch(
          `${API}/api/v1/acidification/hexes?variable=${acidificationVariable}&depth=${acidificationDepth}&v=1`);
        if (!resp.ok) throw new Error(String(resp.status));
        const fc: FeatureCollection = await resp.json();
        if (!cancelled) setAcidHexData(fc);
      } catch {
        if (!cancelled) {
          setAcidHexData(null);
          setFailedLayers((prev) => prev.includes("Ocean Acidification") ? prev : [...prev, "Ocean Acidification"]);
        }
      }
    })();
    return () => { cancelled = true; };
  }, [acidActive, acidificationDisplayMode, acidificationVariable, acidificationDepth]);

  // ── Cumulative Human Impact (NCEAS/Halpern 2025): fetch meta when active ──
  const chiActive = activeLayers.has("cumulative-human-impact");

  useEffect(() => {
    if (!chiActive || chiFetchedRef.current) return;
    chiFetchedRef.current = true;
    fetch(`${API}/api/v1/chi/meta`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((m) => {
        if (!m?.variables?.length) throw new Error("empty chi meta");
        setChiMeta(m);
      })
      .catch(() => {
        chiFetchedRef.current = false; // allow retry on next toggle
        setFailedLayers((prev) => (prev.includes("Cumulative Human Impact") ? prev : [...prev, "Cumulative Human Impact"]));
      });
  }, [chiActive]);

  // ── CHI hex grid ─────────────────────────────────────────────────────────
  useEffect(() => {
    if (!chiActive || chiDisplayMode !== "hexes") { setChiHexData(null); return; }
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetch(`${API}/api/v1/chi/hexes`);
        if (!resp.ok) throw new Error(String(resp.status));
        const fc: FeatureCollection = await resp.json();
        if (!cancelled) setChiHexData(fc);
      } catch {
        if (!cancelled) {
          setChiHexData(null);
          setFailedLayers((prev) => prev.includes("Cumulative Human Impact") ? prev : [...prev, "Cumulative Human Impact"]);
        }
      }
    })();
    return () => { cancelled = true; };
  }, [chiActive, chiDisplayMode]);

  // ── Marine Carbon (unified hex grid) ─────────────────────────────────────
  const [marineCarbonHex, setMarineCarbonHex] = useState<any | null>(null);
  const marineCarbonActive = activeLayers.has("marine-carbon");
  const marineCarbonVariable = useMapStore((s) => s.marineCarbonVariable);
  const marineCarbonDepth = useMapStore((s) => s.marineCarbonDepth);

  useEffect(() => {
    if (!marineCarbonActive) { setMarineCarbonHex(null); return; }
    let cancelled = false;
    (async () => {
      try {
        // v=2: bust the 24h HTTP cache after the any-source-coverage fix (was v1:
        // selected-variable-only, which left stale sparse responses cached). Bump on
        // any change to the unified-hexes response shape/coverage.
        const resp = await fetch(
          `${API}/api/v1/carbon/unified-hexes?variable=${marineCarbonVariable}&depth=${marineCarbonDepth}&v=2`);
        if (!resp.ok) throw new Error(String(resp.status));
        const fc = await resp.json();
        if (!cancelled) setMarineCarbonHex(fc);
      } catch {
        if (!cancelled) {
          setMarineCarbonHex(null);
          setFailedLayers((prev) => prev.includes("Marine Carbon") ? prev : [...prev, "Marine Carbon"]);
        }
      }
    })();
    return () => { cancelled = true; };
  }, [marineCarbonActive, marineCarbonVariable, marineCarbonDepth]);

  // ── VME Suitability (modeled hex grid) ───────────────────────────────────
  const [vmeHex, setVmeHex] = useState<any | null>(null);
  // Colour-ramp domain max for the current view. Suitability is a true 0–1 index;
  // uncertainty (ensemble spread) only reaches ~0.45, so on a fixed 0–1 ramp it renders
  // washed-out and the view toggle looks like it does nothing. Scale it to its own data
  // range so switching visibly changes the map and the uncertainty field stays legible.
  const [vmeMax, setVmeMax] = useState(1);
  const vmeActive = activeLayers.has("vme-suitability");
  const vmeView = useMapStore((s) => s.vmeView);

  useEffect(() => {
    if (!vmeActive) { setVmeHex(null); return; }
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetch(`${API}/api/v1/vme/hexes?view=${vmeView}&v=1`);
        if (!resp.ok) throw new Error(String(resp.status));
        const fc = await resp.json();
        if (!cancelled) {
          // Suitability keeps its true 0–1 domain; uncertainty scales to its own max
          // (floored at 0.05 so a low-spread field can't over-amplify) so the ramp is legible.
          const vals: number[] = (fc.features ?? [])
            .map((f: any) => f?.properties?.value)
            .filter((v: any) => typeof v === "number");
          setVmeMax(vmeView === "uncertainty" ? Math.max(0.05, ...(vals.length ? vals : [1])) : 1);
          setVmeHex(fc);
        }
      } catch {
        if (!cancelled) {
          setVmeHex(null);
          setFailedLayers((prev) => prev.includes("VME Suitability") ? prev : [...prev, "VME Suitability"]);
        }
      }
    })();
    return () => { cancelled = true; };
  }, [vmeActive, vmeView]);

  // ── Coral Acidification Exposure (VME suitability × aragonite horizons) ─────
  // Meta (state → colour, fetched once per activation) and hexes (re-fetched each
  // activation) are two independent effects, mirroring the co2Meta/co2Tiles split
  // below — one failing must not block the other from rendering.
  const [coralExposureMeta, setCoralExposureMeta] = useState<any | null>(null);
  const [coralExposureFeatures, setCoralExposureFeatures] = useState<any[] | null>(null);
  const coralExposureActive = activeLayers.has("coral-acid-exposure");
  const coralExposureMetaFetchedRef = useRef(false);

  useEffect(() => {
    if (!coralExposureActive || coralExposureMetaFetchedRef.current) return;
    coralExposureMetaFetchedRef.current = true;
    fetch(`${API}/api/v1/coral-exposure/meta`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((m) => {
        if (!m?.states?.length) throw new Error("empty coral-exposure meta");
        setCoralExposureMeta(m);
      })
      .catch(() => {
        coralExposureMetaFetchedRef.current = false; // allow retry on next toggle
        setFailedLayers((prev) => prev.includes("Coral Acidification Exposure") ? prev : [...prev, "Coral Acidification Exposure"]);
      });
  }, [coralExposureActive]);

  useEffect(() => {
    if (!coralExposureActive) { setCoralExposureFeatures(null); return; }
    let cancelled = false;
    (async () => {
      try {
        const fc: FeatureCollection = await fetchWithProgress(`${API}/api/v1/coral-exposure/hexes`, () => {});
        if (!cancelled) setCoralExposureFeatures((fc.features ?? []) as any[]);
      } catch {
        if (!cancelled) {
          setCoralExposureFeatures(null);
          setFailedLayers((prev) => prev.includes("Coral Acidification Exposure") ? prev : [...prev, "Coral Acidification Exposure"]);
        }
      }
    })();
    return () => { cancelled = true; };
  }, [coralExposureActive]);

  // ── Surface Ocean CO₂ (SOCAT): fetch meta when layer activates ──────────────
  const co2Active = activeLayers.has("ocean-co2-surface");

  useEffect(() => {
    if (!co2Active || co2FetchedRef.current) return;
    co2FetchedRef.current = true;
    fetch(`${API}/api/v1/co2/meta`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((m) => {
        if (!m?.variables?.length) throw new Error("empty co2 meta");
        setCo2Meta(m);
      })
      .catch(() => {
        co2FetchedRef.current = false; // allow retry on next toggle
        setFailedLayers((prev) => (prev.includes("Surface CO₂") ? prev : [...prev, "Surface CO₂"]));
      });
  }, [co2Active]);

  // Slice the CO₂ field PNG into BitmapLayer tiles — identical approach to carbonTiles.
  useEffect(() => {
    if (!co2Active) { setCo2Tiles(null); return; }
    let cancelled = false;
    setCo2Tiles(null); // drop previous variable/decade tiles so none linger with a stale texture
    (async () => {
      try {
        const resp = await fetch(`${API}/api/v1/co2/${co2Variable}/${co2Decade}.png`);
        if (!resp.ok) throw new Error(String(resp.status));
        const bmp = await createImageBitmap(await resp.blob());
        const W = bmp.width, H = bmp.height; // 360×180 (1°/px), row 0 = north
        const MAXLAT = 85.0511;
        const yTop = Math.round(((90 - MAXLAT) / 180) * H);
        const yBot = Math.round(((90 + MAXLAT) / 180) * H);
        const COLS = 9, ROWS = 6;
        const xs = Array.from({ length: COLS + 1 }, (_, i) => Math.round((i * W) / COLS));
        const ys = Array.from({ length: ROWS + 1 }, (_, i) => Math.round(yTop + (i * (yBot - yTop)) / ROWS));
        const lonOf = (px: number) => -180 + (px / W) * 360;
        const latOf = (py: number) => 90 - (py / H) * 180;
        const tiles: { bounds: [number, number, number, number]; image: HTMLCanvasElement }[] = [];
        for (let cy = 0; cy < ROWS; cy++) {
          for (let cx = 0; cx < COLS; cx++) {
            const sx = xs[cx], sw = xs[cx + 1] - xs[cx];
            const sy = ys[cy], sh = ys[cy + 1] - ys[cy];
            if (sw <= 0 || sh <= 0) continue;
            const cv = document.createElement("canvas");
            cv.width = sw; cv.height = sh;
            cv.getContext("2d")!.drawImage(bmp, sx, sy, sw, sh, 0, 0, sw, sh);
            // bounds = [west, south, east, north]
            tiles.push({ bounds: [lonOf(sx), latOf(ys[cy + 1]), lonOf(xs[cx + 1]), latOf(sy)], image: cv });
          }
        }
        bmp.close();
        if (!cancelled) setCo2Tiles(tiles);
      } catch {
        if (!cancelled) {
          setCo2Tiles(null);
          setFailedLayers((prev) => prev.includes("Surface CO₂") ? prev : [...prev, "Surface CO₂"]);
        }
      }
    })();
    return () => { cancelled = true; };
  }, [co2Active, co2Variable, co2Decade]);

  // ── CO₂ hex grid ─────────────────────────────────────────────────────────
  useEffect(() => {
    if (!co2Active || co2DisplayMode !== "hexes") { setCo2HexData(null); return; }
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetch(`${API}/api/v1/co2/hexes?variable=${co2Variable}&decade=${co2Decade}`);
        if (!resp.ok) throw new Error(String(resp.status));
        const fc: FeatureCollection = await resp.json();
        if (!cancelled) setCo2HexData(fc);
      } catch {
        if (!cancelled) {
          setCo2HexData(null);
          setFailedLayers((prev) => prev.includes("Surface CO₂") ? prev : [...prev, "Surface CO₂"]);
        }
      }
    })();
    return () => { cancelled = true; };
  }, [co2Active, co2DisplayMode, co2Variable, co2Decade]);

  // ── Ocean Oxygen (ISASO2): fetch meta when layer activates ──────────────────
  const oxygenActive = activeLayers.has("oxygen-deox");

  useEffect(() => {
    if (!oxygenActive || oxygenFetchedRef.current) return;
    oxygenFetchedRef.current = true;
    fetch(`${API}/api/v1/oxygen/meta`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((m) => {
        if (!m?.views?.length) throw new Error("empty oxygen meta");
        setOxygenMeta(m);
      })
      .catch(() => {
        oxygenFetchedRef.current = false;
        setFailedLayers((prev) => (prev.includes("Ocean Oxygen (ISASO2)") ? prev : [...prev, "Ocean Oxygen (ISASO2)"]));
      });
  }, [oxygenActive]);

  // Slice the oxygen field PNG into BitmapLayer tiles — identical approach to woaTiles.
  useEffect(() => {
    if (!oxygenActive) { setOxygenTiles(null); return; }
    let cancelled = false;
    setOxygenTiles(null); // drop previous view/depth tiles (avoid stale textures)
    (async () => {
      try {
        const resp = await fetch(`${API}/api/v1/oxygen/${oxygenView}/${oxygenDepth}.png`);
        if (!resp.ok) throw new Error(String(resp.status));
        const bmp = await createImageBitmap(await resp.blob());
        const W = bmp.width, H = bmp.height; // row 0 = north
        const MAXLAT = 85.0511;
        const yTop = Math.round(((90 - MAXLAT) / 180) * H);
        const yBot = Math.round(((90 + MAXLAT) / 180) * H);
        const COLS = 9, ROWS = 6;
        const xs = Array.from({ length: COLS + 1 }, (_, i) => Math.round((i * W) / COLS));
        const ys = Array.from({ length: ROWS + 1 }, (_, i) => Math.round(yTop + (i * (yBot - yTop)) / ROWS));
        const lonOf = (px: number) => -180 + (px / W) * 360;
        const latOf = (py: number) => 90 - (py / H) * 180;
        const tiles: { bounds: [number, number, number, number]; image: HTMLCanvasElement }[] = [];
        for (let cy = 0; cy < ROWS; cy++) {
          for (let cx = 0; cx < COLS; cx++) {
            const sx = xs[cx], sw = xs[cx + 1] - xs[cx];
            const sy = ys[cy], sh = ys[cy + 1] - ys[cy];
            if (sw <= 0 || sh <= 0) continue;
            const cv = document.createElement("canvas");
            cv.width = sw; cv.height = sh;
            cv.getContext("2d")!.drawImage(bmp, sx, sy, sw, sh, 0, 0, sw, sh);
            tiles.push({ bounds: [lonOf(sx), latOf(ys[cy + 1]), lonOf(xs[cx + 1]), latOf(sy)], image: cv });
          }
        }
        bmp.close();
        if (!cancelled) setOxygenTiles(tiles);
      } catch {
        if (!cancelled) setOxygenTiles(null);
      }
    })();
    return () => { cancelled = true; };
  }, [oxygenActive, oxygenView, oxygenDepth]);

  // ── WOA hex grid ─────────────────────────────────────────────────────────
  useEffect(() => {
    if (!woaActive || woaDisplayMode !== "hexes") { setWoaHexData(null); return; }
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetch(`${API}/api/v1/woa/hexes?variable=${woaVariable}&depth=${woaDepth}`);
        if (!resp.ok) throw new Error(String(resp.status));
        const fc: FeatureCollection = await resp.json();
        if (!cancelled) setWoaHexData(fc);
      } catch {
        if (!cancelled) {
          setWoaHexData(null);
          setFailedLayers((prev) => prev.includes("WOA Climatology") ? prev : [...prev, "WOA Climatology"]);
        }
      }
    })();
    return () => { cancelled = true; };
  }, [woaActive, woaDisplayMode, woaVariable, woaDepth]);

  // ── Oxygen hex grid ───────────────────────────────────────────────────────
  useEffect(() => {
    if (!oxygenActive || oxygenDisplayMode !== "hexes") { setOxygenHexData(null); return; }
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetch(`${API}/api/v1/oxygen/hexes?view=${oxygenView}&depth=${oxygenDepth}`);
        if (!resp.ok) throw new Error(String(resp.status));
        const fc: FeatureCollection = await resp.json();
        if (!cancelled) setOxygenHexData(fc);
      } catch {
        if (!cancelled) {
          setOxygenHexData(null);
          setFailedLayers((prev) => prev.includes("Ocean Oxygen (ISASO2)") ? prev : [...prev, "Ocean Oxygen (ISASO2)"]);
        }
      }
    })();
    return () => { cancelled = true; };
  }, [oxygenActive, oxygenDisplayMode, oxygenView, oxygenDepth]);

  // ── MEMENTO hex grid ──────────────────────────────────────────────────────
  useEffect(() => {
    const mementoActive = activeLayers.has("memento");
    if (!mementoActive || mementoDisplayMode !== "hexes") { setMementoHexData(null); return; }
    let cancelled = false;
    (async () => {
      try {
        const fc: FeatureCollection = await fetchWithProgress(`${API}/api/v1/map/memento/hexes`, () => {});
        if (!cancelled) setMementoHexData(fc);
      } catch {
        if (!cancelled) {
          setMementoHexData(null);
          setFailedLayers((prev) => prev.includes("MEMENTO (CH₄/N₂O)") ? prev : [...prev, "MEMENTO (CH₄/N₂O)"]);
        }
      }
    })();
    return () => { cancelled = true; };
  }, [activeLayers, mementoDisplayMode]);

  // ── GEOTRACES hex density fetch ─────────────────────────────────────────────
  useEffect(() => {
    const geotracesActive = activeLayers.has("geotraces");
    if (!geotracesActive || geotracesDisplayMode !== "hexes") { setGeotracesHexData(null); return; }
    let cancelled = false;
    (async () => {
      try {
        const fc: FeatureCollection = await fetchWithProgress(`${API}/api/v1/map/geotraces/hexes`, () => {});
        if (!cancelled) setGeotracesHexData(fc);
      } catch {
        if (!cancelled) {
          setGeotracesHexData(null);
          setFailedLayers((prev) => prev.includes("GEOTRACES Trace Metals") ? prev : [...prev, "GEOTRACES Trace Metals"]);
        }
      }
    })();
    return () => { cancelled = true; };
  }, [activeLayers, geotracesDisplayMode]);

  // ── MOSAIC hex density fetch ─────────────────────────────────────────────
  useEffect(() => {
    const mosaicActive = activeLayers.has("mosaic-sediment");
    if (!mosaicActive || mosaicDisplayMode !== "hexes") { setMosaicHexData(null); return; }
    let cancelled = false;
    (async () => {
      try {
        const fc: FeatureCollection = await fetchWithProgress(`${API}/api/v1/map/mosaic/hexes`, () => {});
        if (!cancelled) setMosaicHexData(fc);
      } catch {
        if (!cancelled) {
          setMosaicHexData(null);
          setFailedLayers((prev) => prev.includes("Marine Sediment Carbon") ? prev : [...prev, "Marine Sediment Carbon"]);
        }
      }
    })();
    return () => { cancelled = true; };
  }, [activeLayers, mosaicDisplayMode]);

  // ── Seabed Substrate hex grid ─────────────────────────────────────────────
  useEffect(() => {
    if (!activeLayers.has("seabed-substrate") || seabedDisplayMode !== "hexes") return;
    if (seabedHexData) return;
    fetch(`${API}/api/v1/seabed/hexes`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (d) setSeabedHexData(d); })
      .catch(() => setFailedLayers((p) => p.includes("Seabed Substrate") ? p : [...p, "Seabed Substrate"]));
  }, [activeLayers, seabedDisplayMode, seabedHexData]);

  // ── Ocean Currents: load + decode the depth-selected texture ───────────────
  useEffect(() => {
    if (!currentsActive || !currentsMeta) return;
    const meta = currentsMeta[currentsDepth];
    if (!meta) return;
    const dates = meta.available_dates ?? [];
    // Effective date drives BOTH the request and the cache key, so the initial
    // (currentsDate == null) load and a later explicit max_date load share a slot.
    const effDate = (currentsDate && dates.includes(currentsDate))
      ? currentsDate
      : (meta.max_date ?? null);
    const key = `${currentsDepth}:${effDate ?? meta.date}`;
    const cached = _currentsFieldLRU.get(key);
    if (cached) {
      setCurrentsField(cached.field);
      setCurrentsArrows(cached.arrows);
      return;
    }
    let cancelled = false;
    const url = `${API}/api/v1/currents/${currentsDepth}.png` + (effDate ? `?date=${effDate}` : "");
    fetch(url)
      .then((r) => (r.ok ? r.blob() : Promise.reject(new Error(String(r.status)))))
      .then(async (blob) => {
        const rgba = await decodeBlobToRGBA(blob);
        if (cancelled) return;
        const field: VelocityField = {
          data: rgba.data, width: rgba.width, height: rgba.height,
          bounds: meta.bounds, unscale: meta.imageUnscale,
        };
        const arrows = decodeCurrentArrows(rgba, meta);
        lruPut(key, { field, arrows });
        setCurrentsField(field);
        setCurrentsArrows(arrows);
      })
      .catch(() => {
        if (!cancelled)
          setFailedLayers((prev) => prev.includes("Ocean Currents") ? prev : [...prev, "Ocean Currents"]);
      });
    return () => { cancelled = true; };
  }, [currentsActive, currentsMeta, currentsDepth, currentsDate]);

  // Default currentsDate to latest once meta arrives.
  useEffect(() => {
    if (!currentsMeta) return;
    const meta = currentsMeta[currentsDepth];
    if (meta?.max_date && currentsDate == null) setCurrentsDate(meta.max_date);
    // currentsDate intentionally omitted: only acts when null; setter is stable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentsMeta, currentsDepth]);

  // ── Ocean Currents: play loop — advance through available_dates, prefetch next ──
  useEffect(() => {
    if (!currentsPlaying || !currentsMeta) return;
    const meta = currentsMeta[currentsDepth];
    const dates = meta?.available_dates ?? [];
    if (dates.length < 2) { setCurrentsPlaying(false); return; }
    const id = setInterval(() => {
      const cur = useMapStore.getState().currentsDate ?? dates[dates.length - 1];
      const i = dates.indexOf(cur);
      if (i < 0 || i >= dates.length - 1) { setCurrentsPlaying(false); return; }
      const next = dates[i + 1];
      setCurrentsDate(next);
      const ahead = dates[i + 2];
      if (ahead && !_currentsFieldLRU.has(`${currentsDepth}:${ahead}`)) {
        fetch(`${API}/api/v1/currents/${currentsDepth}.png?date=${ahead}`)
          .then((r) => (r.ok ? r.blob() : null))
          .then(async (b) => {
            if (!b) return;
            const rgba = await decodeBlobToRGBA(b);
            lruPut(`${currentsDepth}:${ahead}`, {
              field: { data: rgba.data, width: rgba.width, height: rgba.height,
                       bounds: meta!.bounds, unscale: meta!.imageUnscale },
              arrows: decodeCurrentArrows(rgba, meta!) });
          }).catch(() => {});
      }
    }, 600);
    return () => clearInterval(id);
  }, [currentsPlaying, currentsMeta, currentsDepth]);

  // ── Viewport hotspot fetch — enriches sparse areas as user pans/zooms ──
  // Fires at any zoom once global fetch is done. Snap grid + pad scale with zoom
  // so distant views fetch larger areas and close views fetch fine-grained tiles.
  const hotspotsLoaded = hotspotsData !== null;

  // Integer-snapped zoom — limits layer re-uploads to once per zoom level, not 60×/s during animations
  const snappedZoom = useMemo(
    () => Math.round(viewState.zoom as number),
    [viewState.zoom]
  );

  const filteredHotspotsFeatures = useMemo(() => {
    if (!hotspotsData) return [];
    const features = iucnFilters.size === 0
      ? hotspotsData.features
      : hotspotsData.features.filter((f: any) => iucnFilters.has(f.properties?.iucn_category as string));
    // Decimation at distant zoom — keeps rendering fast, glow overlap hides grid
    const step = snappedZoom < 3 ? 8 : snappedZoom < 5 ? 4 : snappedZoom < 7 ? 2 : 1;
    if (step === 1) return features;
    return features.filter((_: any, i: number) => i % step === 0);
  }, [hotspotsData, iucnFilters, snappedZoom]);


  const filteredNoiseFeatures = useMemo(() => {
    if (!noiseRiskData) return [];
    if (noiseRiskFilters.size === 0) return noiseRiskData.features;
    return noiseRiskData.features.filter((f: any) =>
      noiseRiskFilters.has(f.properties?.risk_level)
    );
  }, [noiseRiskData, noiseRiskFilters]);

  // ⛔ ONE predicate, used by BOTH the rendered layer and flyConfigs below.
  // When those two drifted apart on this very layer, flyToLayer cycled through
  // features the map was not drawing and zoomed to an empty patch of ocean.
  // Writing the rule twice is how that happened; this is why it is a variable.
  const oceansitesPasses = useCallback(
    (f: any) => oceansitesPassesRule(f?.properties, oceansitesNetworkFilters, oceansitesStatusFilters),
    [oceansitesNetworkFilters, oceansitesStatusFilters],
  );

  const filteredOceansitesFeatures = useMemo(() => {
    if (!oceansitesData) return [];
    if (oceansitesNetworkFilters.size === 0 && oceansitesStatusFilters.size === 0)
      return oceansitesData.features;
    return oceansitesData.features.filter(oceansitesPasses);
  }, [oceansitesData, oceansitesNetworkFilters, oceansitesStatusFilters, oceansitesPasses]);

  const filteredChessFeatures = useMemo(() => {
    if (!chessData) return [];
    if (chessPhylumFilters.size === 0) return chessData.features;
    return chessData.features.filter((f: any) => {
      const phyla: string[] = f.properties?.phyla ?? [];
      return phyla.some((p: string) => chessPhylumFilters.has(p));
    });
  }, [chessData, chessPhylumFilters]);

  const filteredDeepdataStations = useMemo(() => {
    if (!deepdataStationsData) return [];
    if (deepdataStationContractorFilters.size === 0) return deepdataStationsData.features;
    return deepdataStationsData.features.filter(
      // Empty string is the sentinel for stations whose contractor_code is null
      // (couldn't parse from the DwC title). Coerce nullish → "" so the Set
      // membership check works for both real codes and the (unparsed) chip.
      (f: any) => deepdataStationContractorFilters.has(f.properties?.contractor_code ?? ""),
    );
  }, [deepdataStationsData, deepdataStationContractorFilters]);

  const filteredHydrophoneFeatures = useMemo(() => {
    const feats = hydrophoneData?.features ?? [];
    return feats.filter((f: any) => {
      const p = (f.properties ?? {}) as Record<string, unknown>;
      if (hydrophoneSourceFilters.size > 0 && !hydrophoneSourceFilters.has(String(p.source))) return false;
      if (hydrophoneStatusFilters.size > 0) {
        const status = p.deploy_end ? "retired" : "active";
        if (!hydrophoneStatusFilters.has(status)) return false;
      }
      if (hydrophoneDepthFilters.size > 0) {
        const depth = typeof p.depth_m === "number" ? p.depth_m : null;
        const band = depth == null ? null : depth < 200 ? "shallow" : depth <= 2000 ? "slope" : "abyssal";
        if (!band || !hydrophoneDepthFilters.has(band)) return false;
      }
      return true;
    });
  }, [hydrophoneData, hydrophoneSourceFilters, hydrophoneStatusFilters, hydrophoneDepthFilters]);

  // hydrophoneSourceColor is imported from ./map3d/colors (HYDROPHONE_SOURCE_COLOR
  // registry) — was an inline switch here, re-created on every render.

  const filteredFiresFeatures = useMemo(() => {
    if (!firesData) return [];
    let features = firesData.features;
    if (fireConfidenceFilters.size > 0)
      features = features.filter((f: any) => fireConfidenceFilters.has(f.properties?.confidence));
    if (firesNearMiningOnly && firesNearMiningSet)
      features = features.filter((f: any) => firesNearMiningSet.has(f.properties?.id as number));
    return features;
  }, [firesData, fireConfidenceFilters, firesNearMiningOnly, firesNearMiningSet]);

  const filteredTailingsFeatures = useMemo(() => {
    if (!tailingsData) return [];
    let features = tailingsData.features;
    if (tailingsRiskFilters.size > 0) {
      features = features.filter((f: any) =>
        tailingsHazardVisible(f.properties?.hazard_raw, tailingsRiskFilters, TAILINGS_HAZARD_VALUES)
      );
    }
    if (tailingsStatusFilters.size > 0) {
      features = features.filter((f: any) => {
        const s = (f.properties?.status ?? "").toLowerCase();
        if (tailingsStatusFilters.has("Active") && s.includes("active")) return true;
        if (tailingsStatusFilters.has("Inactive") && (s.includes("inactive") || s.includes("care"))) return true;
        if (tailingsStatusFilters.has("Closed") && (s.includes("closed") || s.includes("reclaim") || s.includes("rehab") || s.includes("decommission") || s.includes("closure"))) return true;
        return false;
      });
    }
    return features;
  }, [tailingsData, tailingsRiskFilters, tailingsStatusFilters]);

  const filteredAisLive = useMemo(() => {
    if (!aisLiveData?.features) return [];
    return aisLiveData.features.filter((f) =>
      matchesAisFilters(f.properties as Record<string, unknown>, {
        aisShipTypeFilters,
        aisFlagFilters,
      }),
    );
  }, [aisLiveData, aisShipTypeFilters, aisFlagFilters]);

  const filteredArcticRiverFeatures = useMemo(() => {
    const feats = arcticRiversData?.features ?? [];
    if (arcticRiverSourceFilters.size === 0) return feats;
    return feats.filter((f: any) => arcticRiverSourceFilters.has(f.properties?.source));
  }, [arcticRiversData, arcticRiverSourceFilters]);

  const filteredSiosFeatures = useMemo(() => siosData?.features ?? [], [siosData]);

  const filteredMethaneSeepsFeatures = useMemo(() => {
    const feats = methaneSeepsData?.features ?? [];
    if (methaneSeepsFeatureTypeFilters.size === 0) return feats;
    return feats.filter((f: any) =>
      (f.properties?.feature_types ?? []).some((t: string) => methaneSeepsFeatureTypeFilters.has(t)));
  }, [methaneSeepsData, methaneSeepsFeatureTypeFilters]);

  const filteredPermafrostThawFeatures = useMemo(() => {
    const feats = permafrostThawData?.features ?? [];
    const noType = thawTypeFilters.size === 0;
    const noCat = thawCategoryFilters.size === 0;
    const noSrc = permafrostSourceFilters.size === 0;
    if (noType && noCat && noSrc) return feats;
    return feats.filter((f: any) => {
      const p = f.properties ?? {};
      const typeOk = noType || thawTypeFilters.has(String(p.thaw_type ?? ""));
      const catOk = noCat || thawCategoryFilters.has(String(p.feature_category ?? "").trim().toLowerCase());
      const srcOk = noSrc || permafrostSourceFilters.has(String(p.source ?? ""));
      return typeOk && catOk && srcOk;
    });
  }, [permafrostThawData, thawTypeFilters, thawCategoryFilters, permafrostSourceFilters]);

  const filteredCascadeFeatures = useMemo(() => {
    const feats = cascadeStationsData?.features ?? [];
    if (cascadeDecadeFilters.size === 0) return feats;
    return feats.filter((f: any) => {
      const d = f.properties?.decade;
      if (d == null) return cascadeDecadeFilters.has("undated");
      return cascadeDecadeFilters.has(String(d));
    });
  }, [cascadeStationsData, cascadeDecadeFilters]);

  const _oncEovAllowed = useMemo(() => {
    if (oncEovFilters.size === 0) return null;
    return new Set(
      Array.from(oncEovFilters).flatMap(e => ONC_EOV_CATEGORIES[e as OncEov] ?? [])
    );
  }, [oncEovFilters]);

  const filteredOncFeatures = useMemo(() => {
    if (!oncData) return [];
    return oncData.features.filter((f: any) =>
      oncEovVisible(f.properties?.device_categories, _oncEovAllowed, ONC_ALL_KNOWN_CATEGORIES)
    );
  }, [oncData, _oncEovAllowed]);

  const filteredOncInstrumentsFeatures = useMemo(() => {
    if (!oncInstrumentsData) return [];
    return oncInstrumentsData.features.filter((f: any) =>
      oncEovVisible(
        f.properties?.device_category != null ? [f.properties.device_category] : [],
        _oncEovAllowed,
        ONC_ALL_KNOWN_CATEGORIES,
      )
    );
  }, [oncInstrumentsData, _oncEovAllowed]);

  const seamountsFeatures = useMemo(() => {
    if (!seamountsData) return [];
    return seamountsData.features;
  }, [seamountsData]);

  // ── Viewport hotspot fetch — load individual dots for current view at zoom 5.5+ ──
  // Snap to 5° grid before using as deps so the effect only fires on tile boundary crossings,
  // not on every sub-pixel pan.
  const hotspotAboveThreshold = (viewState.zoom as number) >= 5.0 ? 1 : 0;
  const hotspotSnapLon = Math.floor((viewState.longitude as number) / 5) * 5;
  const hotspotSnapLat = Math.floor((viewState.latitude as number) / 5) * 5;
  useEffect(() => {
    if (!activeLayers.has("biodiversity-hotspots") || !hotspotsLoaded || !hotspotAboveThreshold) return;
    const tileKey = `${hotspotSnapLon},${hotspotSnapLat}`;
    if (fetchedHotspotTilesRef.current.has(tileKey)) return;
    fetchedHotspotTilesRef.current.add(tileKey);
    // Wider fetch box at low zoom so a single request covers the whole visible
    // globe at z=5; tighter box at z=6+ where viewport is smaller.
    const pad = (viewState.zoom as number) < 6 ? 10 : 5;
    fetch(`${API}/api/v1/map/biodiversity/hotspots?min_lon=${hotspotSnapLon - pad}&max_lon=${hotspotSnapLon + pad + 5}&min_lat=${hotspotSnapLat - pad}&max_lat=${hotspotSnapLat + pad + 5}&zoom=8`)
      .then(r => r.ok ? r.json() : null)
      .then((fc: FeatureCollection | null) => {
        if (!fc?.features?.length) return;
        setHotspotsData(prev => {
          if (!prev) return prev;
          const seenCoords = seenHotspotCoordsRef.current;
          const newFeatures = fc.features.filter(f => {
            const c = (f.geometry as any)?.coordinates;
            if (!c) return false;
            const key = `${c[0]},${c[1]}`;
            if (seenCoords.has(key)) return false;
            seenCoords.add(key);
            return true;
          });
          if (!newFeatures.length) return prev;
          return { ...prev, features: [...prev.features, ...newFeatures] };
        });
      })
      .catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeLayers, hotspotsLoaded, hotspotAboveThreshold, hotspotSnapLon, hotspotSnapLat]);

  // ── Debounced state persistence ─────────────────────────────────────────
  // Also keep latestStateRef current so the unmount flush always has fresh values.
  useEffect(() => {
    latestStateRef.current = { viewState, activeLayers };
    // Published for the share button, which needs the camera as it is now —
    // the save below is debounced, so reading localStorage would hand a
    // recipient wherever the map was a moment ago.
    setLiveMapState(viewState, activeLayers);
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(() => {
      saveMapState(viewState, activeLayers, LAYER_CONFIGS.map(l => l.id));
    }, 1000);
    return () => { if (saveTimerRef.current) clearTimeout(saveTimerRef.current); };
  }, [viewState, activeLayers]);

  // The address bar carries the same view, updated when the user settles —
  // so "copy the URL" works as a share. See useLiveShareUrl for why the
  // trigger is interaction-end and not a timer.
  useLiveShareUrl(viewState, activeLayers, isInteracting, restored);

  // ── Objects and spots named by a share link ─────────────────────────────
  // Runs once per link. Mirrors the `?focus=` effect below: turn the layer on,
  // wait for its data to land, then fly and open. The difference is that this
  // one SAYS SO when it misses.
  //
  // Two kinds arrive here. A RECORD (`o`) is looked up by id and can genuinely
  // be gone. A SPOT (`p`) is a coordinate on a continuous field: it is always
  // there, needs no lookup, and moves no camera — see openPoint below.
  const linkObjectsDoneRef = useRef(false);
  const linkObjectsAbortRef = useRef<AbortController | null>(null);
  // Panels open on a 1.3 s delay so they land after the fly-to settles. ⛔ The
  // handles have to be kept: a reader who clicks through to a report inside
  // that window unmounts this component, and the timer would still reach the
  // module-level store — so coming back to the map would show a panel they
  // never opened in that session, with nothing to explain it.
  const linkPanelTimersRef = useRef<Array<ReturnType<typeof setTimeout>>>([]);
  const openPanelLater = (f: { id: string | number; layer: string; properties: Record<string, unknown> }) => {
    linkPanelTimersRef.current.push(setTimeout(() => setSelectedFeature(f, true), 1300));
  };
  // ⛔ Aborting from the effect's own cleanup was wrong: the deps below change
  // while a `/by-id` request is in flight, React runs the previous cleanup,
  // and the fetch died — recording a "this object is gone" failure for an
  // object that was on its way. Only unmount may cancel.
  useEffect(() => () => {
    linkObjectsAbortRef.current?.abort();
    linkPanelTimersRef.current.forEach(clearTimeout);
  }, []);
  useEffect(() => {
    if (linkObjectsDoneRef.current) return;
    const wanted = _urlShare?.openObjects ?? [];
    // Spots on a continuous field, carried as coordinates rather than ids.
    // ⛔ Handled in THIS effect, not a second one: both kinds compete for the
    // same three panel slots and both may need their layer switched on, and
    // two effects racing to do that would turn a layer on twice and open the
    // fourth panel of three.
    const wantedPoints = _urlShare?.points ?? [];
    if (wanted.length === 0 && wantedPoints.length === 0) { linkObjectsDoneRef.current = true; return; }

    // ⭐ One lookup for every openable layer, through the map the search bar
    // already maintains. The five hand-written entries this replaces were the
    // same shape as `searchById`'s four branches and `?focus=`'s two — the
    // habit this stage exists to end.
    const dataFor = (layerId: string): FeatureCollection | null | undefined => {
      const key = OPENABLE_LOOKUP[layerId]?.dataKey;
      return key ? searchDataRef.current[key] : undefined;
    };

    // ⛔ A layer whose data has not arrived is NOT a miss. Reporting it as one
    // would put a "this object is gone" notice on screen a second before the
    // object appears. Wait; the effect re-runs when the fetch lands.
    // Same staleness trap as the activation below: asking the closure's
    // `activeLayers` whether a layer is on can answer "no" for a layer the
    // restore just switched on, which turns "its data is still loading" into
    // "the object is gone" — the one notice that must never be wrong.
    const liveActive = useMapStore.getState().activeLayers as ReadonlySet<string>;
    const missingData = wanted.some(([layerId]) =>
      isOpenableLayer(layerId) && liveActive.has(layerId) && dataFor(layerId) === null);
    // ⛔ The LIVE set, not the `activeLayers` this effect closed over. That
    // closure value is one render behind the layer restore above, so merging
    // onto it silently dropped every layer the link carried but the panel did
    // not need. Reproduced on production 2026-09-15 — see linkLayerActivation.
    const next = nextActiveForLink(
      liveActive, wanted, wantedPoints, isOpenableLayer, isPointLayer,
    );
    if (next) {
      setActiveLayers(next as Set<LayerId>);
      return;
    }
    if (missingData) return;

    linkObjectsDoneRef.current = true;
    const store = useMapStore.getState();
    const ctrl = new AbortController();
    linkObjectsAbortRef.current = ctrl;
    let flewTo = false;
    const open = async ([layerId, featureId]: readonly [string, string]) => {
      // ⛔ Client-held data first, the network only as a fallback — see
      // fetchOpenTarget for what `/by-id` does not return.
      const target = await openTargetFor(layerId, featureId, dataFor(layerId), API, ctrl.signal);
      if (!target) {
        store.addSharePanelFailure({ layerId, featureId });
        return;
      }
      // ⛔ `?fly=`/`?focus=` mean "jump to this ONE feature" and outrank a whole
      // restored view — so a link's own camera only moves when neither is present.
      // `/by-id` may answer without geometry; then there is nothing to fly to
      // and the link's own camera stands.
      if (!flewTo && !_urlFly && target.feature.geometry) {
        const c = getBBoxCenter([target.feature as any]);
        setViewState({ ...viewStateRef.current, longitude: c.longitude, latitude: c.latitude,
          zoom: target.zoom, pitch: 45, bearing: 0,
          transitionDuration: 1200, transitionInterpolator: new FlyToInterpolator({ speed: 1.5 }) });
        flewTo = true;
      }
      // `shift: true` stacks — the sender may have had up to three side by side.
      openPanelLater({ id: target.id, layer: target.routingKey, properties: target.properties });
    };
    // ⭐ A coordinate needs no lookup at all — the spot always exists and the
    // panel asks the API itself. The only way this fails is a layer that is no
    // longer addressable by coordinate, or a link missing the selector value
    // the panel needs; both are reported rather than swallowed.
    //
    // ⛔ And nothing here touches the camera. The link already carries the
    // sender's framing, and a field layer has no landing zoom to fly to —
    // picking one would replace what the sender chose with a guess.
    const openPoint = ([layerId, lon, lat, extra]: readonly [string, number, number, number?]) => {
      const target = pointTargetFor(layerId, lon, lat, extra);
      if (!target) {
        store.addSharePanelFailure({ layerId, featureId: `${lat}, ${lon}` });
        return;
      }
      openPanelLater({ id: target.id, layer: target.routingKey, properties: target.properties });
    };

    // Sequential, not parallel: the fly-to belongs to the FIRST object the
    // sender listed, and a race would hand it to whichever `/by-id` answered
    // soonest.
    void (async () => {
      for (const entry of wanted) await open(entry);
      wantedPoints.forEach(openPoint);
    })();
    // ⚠️ `searchDataVersion` is the signal, not the 30-odd data variables: the
    // ref it tracks is exactly the map read above, and listing every dataset
    // here would rot the moment a layer is added.
  }, [searchDataVersion, activeLayers, setSelectedFeature]);

  // ── Flush map state on unmount (e.g. navigating to a report) ────────────
  // Also write RETURN_FLY here — latestStateRef is always current, unlike
  // the debounced localStorage write, so the saved coords are always right.
  useEffect(() => {
    return () => {
      if (latestStateRef.current) {
        const { viewState: vs, activeLayers: al } = latestStateRef.current;
        saveMapState(vs, al, LAYER_CONFIGS.map(l => l.id));
        saveReturnFlyFromViewState(
          vs.longitude as number,
          vs.latitude  as number,
          vs.zoom      as number,
        );
      }
    };
  }, []);

  // ── Plume tracing ────────────────────────────────────────────────────────
  // Accepts a platform_id and traces plumes for ALL historical positions of
  // that float (from argoTrailsData), showing drift plume origins over time.
  const tracePlume = useCallback(async (platformId: string) => {
    if (fetchedTracesRef.current.has(`platform:${platformId}`)) return;
    fetchedTracesRef.current.add(`platform:${platformId}`);
    setIsTracing(true);
    let succeeded = 0;
    let failed = 0;
    try {
      // Collect all profile_ids for this platform from trail data
      const profileIds: string[] = [];
      if (argoTrailsData?.features) {
        for (const f of argoTrailsData.features) {
          const props = f.properties ?? {};
          if (String(props.platform_id) === platformId && props.profile_id) {
            profileIds.push(String(props.profile_id));
          }
        }
      }
      // Fallback: if no trail data yet, trace just the single profile
      if (profileIds.length === 0) profileIds.push(platformId);

      for (const pid of profileIds) {
        if (fetchedTracesRef.current.has(pid)) continue;
        fetchedTracesRef.current.add(pid);
        try {
          const controller = new AbortController();
          const timeout = setTimeout(() => controller.abort(), 45_000);
          const r = await fetch(
            `${API}/api/v1/analysis/correlate-plume?argo_id=${encodeURIComponent(pid)}&hours=168&depth=1000`,
            { signal: controller.signal },
          );
          clearTimeout(timeout);
          if (r.ok) {
            const data = await r.json();
            addPlumeTrace(pid, data, platformId);
            succeeded++;
          } else { failed++; }
        } catch { failed++; }
      }
    } finally {
      setIsTracing(false);
      // Surface structured feedback when traces fail
      if (failed > 0 && succeeded === 0) {
        setFailedLayers(prev => [...prev, "Plume model — CMEMS endpoint timed out or is unavailable. Try again later."]);
      } else if (failed > 0) {
        setFailedLayers(prev => [...prev, `Plume model — ${succeeded} of ${succeeded + failed} traces completed, ${failed} timed out`]);
      }
    }
  }, [addPlumeTrace, argoTrailsData]);

  useEffect(() => { setTracePlume(tracePlume); }, [tracePlume, setTracePlume]);

  // ── Plume history ────────────────────────────────────────────────────────
  const fetchPlumeHistory = useCallback(async (contractorName: string) => {
    if (fetchedPlumesRef.current.has(contractorName)) return;
    fetchedPlumesRef.current.add(contractorName);
    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 30_000);
      const r = await fetch(
        `${API}/api/v1/plumes/history?contractor_name=${encodeURIComponent(contractorName)}&limit=50`,
        { signal: controller.signal },
      );
      clearTimeout(timeout);
      if (r.ok) {
        const data = await r.json();
        addPlumeHistory(contractorName, data);
      }
    } catch {
      // Allow retry on next click
      fetchedPlumesRef.current.delete(contractorName);
    }
  }, [addPlumeHistory]);

  useEffect(() => { setFetchPlumeHistory(fetchPlumeHistory); }, [fetchPlumeHistory, setFetchPlumeHistory]);

  // ── Fly-to callback ──────────────────────────────────────────────────────
  const flyTo = useCallback((lon: number, lat: number) => {
    setViewState({
      ...viewStateRef.current,
      longitude: lon, latitude: lat, zoom: 9,
      transitionDuration: 1200,
      transitionInterpolator: new FlyToInterpolator(),
    });
  }, []);
  useEffect(() => { setFlyTo(flyTo); }, [flyTo, setFlyTo]);

  // When a vessel track is focused, fit the viewport to its bounding box so all
  // points are visible. Dependency key includes the mmsi + point count so a
  // track update (more points arrived) does not retrigger during re-renders.
  useEffect(() => {
    if (!vesselFocus) return;
    const pts = vesselFocus.track.features.filter(f => f.geometry?.type === "Point");
    if (pts.length === 0) return;
    const box: Box = { minLon: 180, maxLon: -180, minLat: 90, maxLat: -90 };
    for (const f of pts) {
      const c = (f.geometry as GeoJSON.Point).coordinates;
      expandBox(box, c);
    }
    const cx = (box.minLon + box.maxLon) / 2;
    const cy = (box.minLat + box.maxLat) / 2;
    const span = Math.max(box.maxLon - box.minLon, (box.maxLat - box.minLat) * 2, 0.05);
    const zoom = Math.min(11, Math.max(3, Math.log2(360 / span)));
    setViewState({
      ...viewStateRef.current,
      longitude: cx, latitude: cy, zoom,
      transitionDuration: 1200,
      transitionInterpolator: new FlyToInterpolator(),
    });
  }, [vesselFocus?.mmsi, vesselFocus?.track.features.length]);  // eslint-disable-line react-hooks/exhaustive-deps

  // Fly-to with custom zoom (used by DiscoveryPanel)
  const discoveryFlyTo = useCallback((lon: number, lat: number, zoom: number) => {
    setViewState({
      ...viewStateRef.current,
      longitude: lon, latitude: lat, zoom,
      transitionDuration: 1800,
      transitionInterpolator: new FlyToInterpolator(),
    });
  }, []);

  // Handle return-fly from report pages and ?fly= URL param — re-runs on every location change
  useEffect(() => {
    // Priority 1: an explicit ?fly= destination (e.g. "View on map" from a
    // feature page). This is direct user intent and must win over the saved
    // "return to where I was" position — otherwise a stale return-fly from the
    // previously-viewed feature hijacks the deep-link and lands on the wrong one.
    const params = new URLSearchParams(locationSearch);
    const fly = params.get("fly");
    if (fly) {
      const [lon, lat, z] = fly.split(",").map(Number);
      if (!isNaN(lon) && !isNaN(lat)) {
        consumeReturnFly(); // discard any stale return-fly so it can't fire next
        params.delete("fly");
        const clean = params.toString();
        window.history.replaceState({}, "", window.location.pathname + (clean ? `?${clean}` : ""));
        setViewState(prev => ({
          ...prev,
          longitude: lon, latitude: lat, zoom: isNaN(z) ? 9 : z,
          transitionDuration: 1200,
          transitionInterpolator: new FlyToInterpolator(),
        }));
        return;
      }
    }
    // Priority 2: return-fly saved by a report "back to map" button (no ?fly).
    const saved = consumeReturnFly();
    if (saved) {
      setViewState(prev => ({
        ...prev,
        longitude: saved.lon, latitude: saved.lat, zoom: saved.zoom,
        transitionDuration: 1200,
        transitionInterpolator: new FlyToInterpolator(),
      }));
    }
  }, [locationSearch]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Claim filter predicate ───────────────────────────────────────────────
  const riskAreaMap = useMemo(
    () => new Map(riskAreas.map(r => [r.isaId, r])),
    [riskAreas]
  );

  const claimPassesFilter = useCallback((props: any): boolean => {
    if (!props) return true;
    if (hiddenContractors.size > 0) {
      const key = `${props.contractor_name}::${props.resource_type}`;
      if (hiddenContractors.has(key)) return false;
    }
    if (claimRiskFilters.size > 0) {
      const checks: Record<ClaimRiskValue, boolean> = {
        biodiversity: props.is_high_risk === true,
        argo:         (riskAreaMap.get(String(props.isa_id ?? ""))?.argoFloats.length ?? 0) > 0,
        vents:        props.isa_id != null && String(props.isa_id) in ventConflicts,
        unesco:       props.nearest_unesco_dist_km != null && props.nearest_unesco_dist_km < 200,
      };
      for (const risk of claimRiskFilters) {
        const check = (checks as Record<string, boolean | undefined>)[risk];
        // ⛔ A value with no test behind it is a retired filter, not a failed
        // one. `!undefined` is true, so the plain `if (!checks[risk])` this
        // replaced made every concession fail and blanked the whole layer —
        // the same way a pre-2026-09-21 link blanked the vents. An unknown
        // value is ignored: showing more than the link asked for is survivable,
        // showing nothing is indistinguishable from an outage.
        if (check === undefined) continue;
        if (!check) return false;
      }
    }
    return true;
  }, [hiddenContractors, claimRiskFilters, riskAreaMap, ventConflicts]);

  // ── Memoized data selectors (must be before flyToLayer) ─────────────────
  const { setArgoDatasetStats } = useMapStore();
  const datasetStats: DatasetStats = useMemo(
    () => computeDatasetStats((argoData?.features ?? []) as any[]),
    [argoData]
  );
  useEffect(() => { setArgoDatasetStats(datasetStats); }, [datasetStats, setArgoDatasetStats]);

  const filteredArgoData = useMemo(() => {
    if (!argoData) return null;
    if (argoAlarmFilters.size === 0) return argoData;
    return {
      ...argoData,
      features: argoData.features.filter(f =>
        [...argoAlarmFilters].some(alarm => floatHasAlarm(f.properties as any, alarm, datasetStats))
      ),
    };
  }, [argoData, argoAlarmFilters, datasetStats]);

  // Pre-computed alarm sets — avoids floatHasAlarm() being called per-feature per-frame in GPU accessors
  const argoAlarmFeatures = useMemo(() => {
    if (!filteredArgoData) return [];
    return filteredArgoData.features.filter((f: any) =>
      ["low_oxygen", "low_ph"].some(a => floatHasAlarm(f.properties as any, a, datasetStats))
    );
  }, [filteredArgoData, datasetStats]);

  const argoAlarmIdSet = useMemo(
    () => new Set<string>(argoAlarmFeatures.map((f: any) => String(f.properties?.platform_id ?? ""))),
    [argoAlarmFeatures]
  );

  // Floats whose pH is physically impossible (failed BGC pH sensor). Marked with an
  // amber ring so they're visible without clicking; additive to the alarm color.
  const argoSensorFaultFeatures = useMemo(() => {
    if (!filteredArgoData) return [];
    return filteredArgoData.features.filter((f: any) => phImplausible(f.properties?.ph));
  }, [filteredArgoData]);

  // ── Fly-to-layer config ──────────────────────────────────────────────────
  // Each layer declares how flyToLayer should resolve its deck.gl ID, feature
  // ID property, and optional filter. New layers only need one entry here.
  type FlyConfig = {
    deckLayerId: string | ((f: any) => string);
    idProp?: string;
    filter?: (f: any) => boolean;
    fallback?: (f: any) => boolean;
  };
  const flyConfigs = useMemo(() => ({
    "contracts":             { deckLayerId: "mining-contracts-mvt", idProp: "isa_id",
                               filter: (f: any) => claimPassesFilter(f.properties) },
    "reserved-areas":        { deckLayerId: "reserved-areas" },
    "apeis":                 { deckLayerId: "apeis" },
    "biodiversity-hotspots": { deckLayerId: "biodiversity-hotspots", idProp: "id",
                               filter: makeSetFilter(iucnFilters, "iucn_category"),
                               fallback: (f: any) => f.properties?.phylum },
    "seamounts":             { deckLayerId: "seamounts" },
    "relinquished-areas":    { deckLayerId: "relinquished-areas" },
    "argo":                  { deckLayerId: "argo-floats-3d", idProp: "platform_id",
                               filter: argoAlarmFilters.size > 0
                                 ? (f: any) => [...argoAlarmFilters].some(a => floatHasAlarm(f.properties as any, a, datasetStats))
                                 : undefined },
    "hydrothermal-vents":    { deckLayerId: (f: any) => isActiveVentStatus(f.properties?.status)
                                 ? "hydrothermal-vents-active" : "hydrothermal-vents-inactive",
                               filter: (f: any) => ventStatusFilters.has(f.properties?.status) },
    "eez":                   { deckLayerId: "eez" },
    "protected-marine-sites":{ deckLayerId: "protected-marine-sites" },
    "noise-risk":            { deckLayerId: "noise-risk", idProp: "cell_key",
                               filter: makeSetFilter(noiseRiskFilters, "risk_level") },
    // Rule: every layer with a filter Set MUST have a matching filter predicate here,
    // mirroring its filteredXxxFeatures useMemo. Without it, flyToLayer cycles through
    // raw (invisible) features and zooms to blank ocean.
    "oceansites": {
      deckLayerId: "oceansites",
      // Not makeSetFilter(...) any more: with two filter Sets a single-key
      // helper can only mirror one of them, and the half it drops is the half
      // flyToLayer lands in.
      filter: oceansitesPasses,
    },
    "chess": {
      deckLayerId: "chess",
      idProp: "locality",
      filter: chessPhylumFilters.size > 0
        ? (f: any) => filteredChessFeatures.some((ff: any) => ff.properties?.locality === f.properties?.locality)
        : undefined,
    },
    "submarine-cables":  { deckLayerId: "submarine-cables" },
    "onc": {
      deckLayerId: "onc",
      filter: _oncEovAllowed
        ? (f: any) => oncEovVisible(f.properties?.device_categories, _oncEovAllowed, ONC_ALL_KNOWN_CATEGORIES)
        : undefined,
    },
    "onc-instruments": {
      deckLayerId: "onc-instruments",
      filter: _oncEovAllowed
        ? (f: any) => oncEovVisible(
            f.properties?.device_category != null ? [f.properties.device_category] : [],
            _oncEovAllowed,
            ONC_ALL_KNOWN_CATEGORIES,
          )
        : undefined,
    },
    "deepdata-stations": {
      deckLayerId: "deepdata-stations",
      filter: deepdataStationContractorFilters.size > 0
        ? (f: any) => deepdataStationContractorFilters.has(f.properties?.contractor_code ?? "")
        : undefined,
    },
    "hydrophone-stations": {
      deckLayerId: "hydrophone-stations",
      idProp: "station_id",
      filter: (hydrophoneSourceFilters.size > 0 || hydrophoneStatusFilters.size > 0 || hydrophoneDepthFilters.size > 0)
        ? (f: any) => {
            const p = (f.properties ?? {}) as Record<string, unknown>;
            if (hydrophoneSourceFilters.size > 0 && !hydrophoneSourceFilters.has(String(p.source))) return false;
            if (hydrophoneStatusFilters.size > 0) {
              const status = p.deploy_end ? "retired" : "active";
              if (!hydrophoneStatusFilters.has(status)) return false;
            }
            if (hydrophoneDepthFilters.size > 0) {
              const depth = typeof p.depth_m === "number" ? p.depth_m : null;
              const band = depth == null ? null : depth < 200 ? "shallow" : depth <= 2000 ? "slope" : "abyssal";
              if (!band || !hydrophoneDepthFilters.has(band)) return false;
            }
            return true;
          }
        : undefined,
    },
    "ports":               { deckLayerId: "ports" },
    "monitoring-density":  { deckLayerId: "monitoring-density" },
    "tectonic-plates":  { deckLayerId: "tectonic-plates-boundaries" },
    // Land layers
    "mining-footprints": { deckLayerId: "mining-footprints" },
    "water-risk":        { deckLayerId: "water-risk-mvt" },
    "tailings": {
      deckLayerId: "tailings",
      filter: tailingsRiskFilters.size > 0
        ? (f: { properties?: Record<string, unknown> | null }) =>
            tailingsHazardVisible(f.properties?.hazard_raw as string | null | undefined, tailingsRiskFilters, TAILINGS_HAZARD_VALUES)
        : undefined,
    },
    "fires": {
      deckLayerId: "fires",
      filter: (f: { properties?: Record<string, unknown> | null }) => {
        if (fireConfidenceFilters.size > 0 && !fireConfidenceFilters.has(f.properties?.confidence as string)) return false;
        if (firesNearMiningOnly && firesNearMiningSet && !firesNearMiningSet.has(f.properties?.id as number)) return false;
        return true;
      },
    },
    "air-quality":       { deckLayerId: "air-quality" },
    "landslides":        { deckLayerId: "landslides" },
    "dams":              { deckLayerId: "dams" },
    "vessel-events": {
      deckLayerId: "vessel-events",
    },
    "ais-live": {
      deckLayerId: "ais-live",
      filter: (f: any) =>
        matchesAisFilters(f.properties as Record<string, unknown>, {
          aisShipTypeFilters,
          aisFlagFilters,
        }),
    },
    "arctic-rivers": {
      deckLayerId: "arctic-rivers",
      filter: arcticRiverSourceFilters.size > 0
        ? (f: any) => arcticRiverSourceFilters.has(f.properties?.source)
        : undefined,
    },
    "methane-seeps": {
      deckLayerId: "methane-seeps",
      filter: methaneSeepsFeatureTypeFilters.size > 0
        ? (f: any) => (f.properties?.feature_types ?? []).some((t: string) => methaneSeepsFeatureTypeFilters.has(t))
        : undefined,
    },
    "permafrost-thaw": {
      deckLayerId: "permafrost-thaw",
      filter: (thawTypeFilters.size > 0 || thawCategoryFilters.size > 0 || permafrostSourceFilters.size > 0)
        ? (f: any) => {
            const p = f.properties ?? {};
            const typeOk = thawTypeFilters.size === 0 || thawTypeFilters.has(String(p.thaw_type ?? ""));
            const catOk = thawCategoryFilters.size === 0 || thawCategoryFilters.has(String(p.feature_category ?? "").trim().toLowerCase());
            const srcOk = permafrostSourceFilters.size === 0 || permafrostSourceFilters.has(String(p.source ?? ""));
            return typeOk && catOk && srcOk;
          }
        : undefined,
    },
    "sios-svalbard": {
      deckLayerId: "sios-svalbard",
    },
    "offshore-activities": {
      deckLayerId: "offshore-activities-mvt",
      filter: (f: any) => {
        const typeOk = offshoreActivityFilters.size === 0 || offshoreActivityFilters.has(f.properties?.activity_type as string);
        const countryOk = offshoreActivityCountryFilters.size === 0 || offshoreActivityCountryFilters.has(f.properties?.sovereign as string);
        return typeOk && countryOk;
      },
    },
    "wod-oxygen": {
      deckLayerId: "wod-oxygen",
      filter: wodDecadeFilters.size > 0
        ? (f: any) => wodDecadeFilters.has(String(f.properties?.decade))
        : undefined,
    },
    "memento": {
      deckLayerId: "memento",
      filter: (mementoGasFilters.size > 0 || mementoDecadeFilters.size > 0)
        ? (f: any) => {
            const gasOk = mementoGasFilters.size === 0 || (
              (mementoGasFilters.has("ch4") && f.properties?.has_ch4) ||
              (mementoGasFilters.has("n2o") && f.properties?.has_n2o)
            );
            const decOk = mementoDecadeFilters.size === 0 || mementoDecadeFilters.has(String(f.properties?.decade));
            return gasOk && decOk;
          }
        : undefined,
    },
    "geotraces": {
      deckLayerId: "geotraces",
      filter: (f: any) => {
        const p = f.properties || {};
        if (!p[`has_${geotracesElement}`]) return false;
        if (geotracesDecadeFilters.size > 0 && !geotracesDecadeFilters.has(String(p.decade))) return false;
        return true;
      },
    },
    "mosaic-sediment": {
      deckLayerId: "mosaic-sediment",
      filter: (f: any) => {
        const p = f.properties || {};
        if (!p[`has_${mosaicVariable}`]) return false;
        if (mosaicDecadeFilters.size > 0) {
          const key = p.decade == null ? "undated" : String(p.decade);
          if (!mosaicDecadeFilters.has(key)) return false;
        }
        return true;
      },
    },
    "arctic-catchments": { deckLayerId: "arctic-catchments-mvt" },
    "arctic-sediment-carbon": {
      deckLayerId: "arctic-sediment-carbon-stations",
      filter: (f: any) => {
        if (cascadeDecadeFilters.size === 0) return true;
        const d = f.properties?.decade;
        if (d == null) return cascadeDecadeFilters.has("undated");
        return cascadeDecadeFilters.has(String(d));
      },
    },
  }) as const satisfies Record<string, FlyConfig>, [claimPassesFilter, iucnFilters, argoAlarmFilters, ventStatusFilters, noiseRiskFilters, oceansitesNetworkFilters, oceansitesStatusFilters, oceansitesPasses, datasetStats, chessPhylumFilters, filteredChessFeatures, fireConfidenceFilters, firesNearMiningOnly, firesNearMiningSet, tailingsRiskFilters, aisShipTypeFilters, aisFlagFilters, _oncEovAllowed, offshoreActivityFilters, offshoreActivityCountryFilters, deepdataStationContractorFilters, hydrophoneSourceFilters, hydrophoneStatusFilters, hydrophoneDepthFilters, wodDecadeFilters, arcticRiverSourceFilters, mementoGasFilters, mementoDecadeFilters, methaneSeepsFeatureTypeFilters, geotracesElement, geotracesDecadeFilters, mosaicVariable, mosaicDecadeFilters, cascadeDecadeFilters, thawTypeFilters, thawCategoryFilters, permafrostSourceFilters]);

  // Completeness guard. Cheap at runtime (one boolean); the work is at compile
  // time. `void` rather than `export` because this sits inside a component.
  type FlyCovered = Extract<keyof typeof flyConfigs, LayerId>;
  const _flyToIsComplete: AssertComplete<FlyCovered, (typeof NO_FLY_TO)[number]> = true;
  void _flyToIsComplete;
  // Completeness alone would pass even if a layer sat in BOTH flyConfigs and
  // NO_FLY_TO — e.g. someone silencing a completeness error by adding a
  // working layer to the opt-out list. Disjointness catches that lie.
  const _flyToIsDisjoint: AssertDisjoint<FlyCovered, (typeof NO_FLY_TO)[number]> = true;
  void _flyToIsDisjoint;

  // ── Fly-to-layer callback ────────────────────────────────────────────────
  const flyToLayer = useCallback((id: LayerId) => {
    const layerMap: Partial<Record<LayerId, FeatureCollection | null>> = {
      "contracts":            claimsData,
      "reserved-areas":       reservedData,
      "apeis":                apeisData,
      "biodiversity-hotspots": hotspotsData,
      "seamounts":            seamountsData,
      "relinquished-areas":   relinquishedData,
      "argo":                 argoData,
      "hydrothermal-vents":   ventsData,
      "eez":                  eezData,
      "protected-marine-sites": protectedSitesData,
      "noise-risk":     noiseRiskData,
      "oceansites":     oceansitesData,
      "onc":            oncData,
      "chess":          chessData,
      "submarine-cables": cablesData,
      "onc-instruments":    oncInstrumentsData,
      "deepdata-stations":  deepdataStationsData,
      "hydrophone-stations": hydrophoneData,
      "monitoring-density": monitoringDensityData,
      "ports":              portsData,
      "tectonic-plates": tectonicData?.boundaries ?? null,
      // Land layers
      "mining-footprints": miningFootprintsData,
      "water-risk":        null, // MVT layer — no client-side data
      "tailings":          tailingsData,
      "fires":             firesData,
      "air-quality":       airQualityData,
      "landslides":        landslidesData,
      "dams":              damsData,
      "vessel-events": vesselEventsData,
      "ais-live":      aisLiveData,
      "arctic-rivers":     arcticRiversData,
      "sios-svalbard":     siosData,
      "methane-seeps":     methaneSeepsData,
      "permafrost-thaw":   permafrostThawData,
      "offshore-activities": null, // MVT layer — no client-side data
      "arctic-catchments": null,   // MVT layer — no client-side data
      "arctic-sediment-carbon": cascadeStationsData,
    };
    let candidates = layerMap[id]?.features ?? [];
    // Submarine cables: combine both sources, respecting the source filter.
    // Without this, flyToLayer zooms only to EMODnet features even when the user
    // has filtered to ONC-only (or vice versa).
    if (id === "submarine-cables") {
      const emodnet = cableSourceFilters.size === 0 || cableSourceFilters.has("emodnet")
        ? (cablesData?.features ?? []) : [];
      const onc = cableSourceFilters.size === 0 || cableSourceFilters.has("onc")
        ? (oncCablesData?.features ?? []) : [];
      const ooi = cableSourceFilters.size === 0 || cableSourceFilters.has("ooi")
        ? (ooiCablesData?.features ?? []) : [];
      const noaa = cableSourceFilters.size === 0 || cableSourceFilters.has("noaa")
        ? (noaaCablesData?.features ?? []) : [];
      const nz = cableSourceFilters.size === 0 || cableSourceFilters.has("nz")
        ? (nzCablesData?.features ?? []) : [];
      const au = cableSourceFilters.size === 0 || cableSourceFilters.has("au")
        ? (auCablesData?.features ?? []) : [];
      candidates = [...emodnet, ...onc, ...ooi, ...noaa, ...nz, ...au];
    }
    if (!candidates.length) {
      // Offshore activities: cycle through individual feature bboxes (like ISA claims)
      // so each press lands on a specific block, not an aggregate centroid.
      if (id === "offshore-activities" && (offshoreActivityFilters.size > 0 || offshoreActivityCountryFilters.size > 0)) {
        const cacheKey = offshoreFilterKey;
        const flyOne = (list: OffshoreBbox[]) => {
          if (!list.length) return;
          let idx = layerFlyIndexRef.current[id] || 0;
          idx = idx % list.length;
          const b = list[idx];
          const raw = bboxToView({ minLon: b.west, maxLon: b.east, minLat: b.south, maxLat: b.north });
          const zoom = Math.max(raw.zoom, 5);
          setViewState({ ...viewStateRef.current, longitude: raw.longitude, latitude: raw.latitude, zoom, pitch: 45, bearing: 0, transitionDuration: 1200, transitionInterpolator: new FlyToInterpolator({ speed: 1.5 }) });
          layerFlyIndexRef.current[id] = (idx + 1) % list.length;
          // Open popup after fly animation lands — matches ISA cycle UX
          const lon = (b.west + b.east) / 2;
          const lat = (b.south + b.north) / 2;
          setTimeout(() => {
            fetch(`${API}/api/v2/spatial/offshore-activities/by-id/${b.id}`)
              .then(r => r.ok ? r.json() : null)
              .then((feat: any) => {
                if (!feat) return;
                setSelectedFeature({
                  id: String(feat.id ?? b.id),
                  layer: "offshore-activities",
                  properties: { ...feat, _lon: lon, _lat: lat },
                });
              })
              .catch(() => {});
          }, 1300);
        };
        const cached = offshoreBboxCacheRef.current.get(cacheKey);
        if (cached) {
          flyOne(cached);
        } else {
          const params = new URLSearchParams();
          if (offshoreActivityFilters.size) params.set("types", [...offshoreActivityFilters].sort().join(","));
          if (offshoreActivityCountryFilters.size) params.set("countries", [...offshoreActivityCountryFilters].sort().join(","));
          fetch(`${API}/api/v2/spatial/offshore-activities/feature-bboxes?${params.toString()}`)
            .then(r => r.ok ? r.json() : null)
            .then((list: OffshoreBbox[] | null) => {
              if (!list?.length) return;
              offshoreBboxCacheRef.current.set(cacheKey, list);
              flyOne(list);
            })
            .catch(() => {});
        }
        analytics.trackEvent("fly_to_layer", { layer_id: id });
        return;
      }

      // Raster tile layers have no features — fly to a preset viewport instead
      const rasterViews: Partial<Record<LayerId, { longitude: number; latitude: number; zoom: number }>> = {
        "mining-footprints": { longitude: -65, latitude: -15, zoom: 5 },
        "surface-water":  { longitude: 30, latitude: 0, zoom: 5 },
        "forest-loss":    { longitude: -60, latitude: -5, zoom: 5 },
        "carbon-flux":    { longitude: -60, latitude: -5, zoom: 5 },
        "soil-carbon":    { longitude: 20, latitude: 10, zoom: 4 },
        "water-risk":            { longitude: 30, latitude: 25, zoom: 4 },
        // Vessel layers have no features when the DB is empty (new deploy,
        // no S1 coverage over ISA polygons yet) — fly to CCZ where the
        // biggest concentration of ISA concessions sits.
        "vessel-events":  { longitude: -140, latitude: 12, zoom: 3 },
        "ais-live":       { longitude: -140, latitude: 12, zoom: 3 },
        "offshore-activities": { longitude: 3, latitude: 56, zoom: 5.5 },
        "marine-carbon":  { longitude: -150, latitude: 10, zoom: 2.5 },
        "arctic-catchments": { longitude: 20, latitude: 70, zoom: 3.5 },
        "seabed-substrate":  { longitude: -130, latitude: 12, zoom: 3 },
        "arctic-sediment-carbon": { longitude: 10, latitude: 80, zoom: 2.5 },
        "vme-suitability": { longitude: -20, latitude: 30, zoom: 2 },
        "coral-acid-exposure": { longitude: -20, latitude: 30, zoom: 2 },
      };
      const rv = rasterViews[id];
      if (!rv) return;
      setViewState({
        ...viewStateRef.current,
        ...rv,
        pitch: 45, bearing: 0,
        transitionDuration: 1200,
        transitionInterpolator: new FlyToInterpolator({ speed: 1.5 }),
      });
      analytics.trackEvent("fly_to_layer", { layer_id: id });
      return;
    }

    // Apply layer-specific filter, then fallback preference
    // Cast needed here only: `id` is the full LayerId union, but flyConfigs'
    // sealed literal type only has keys for the 41 covered layers (that's what
    // makes the completeness assertion below bite). Excluded ids correctly
    // resolve to undefined at runtime, same as before this narrowing.
    const cfg = (flyConfigs as Partial<Record<LayerId, FlyConfig>>)[id];
    if (cfg?.filter) {
      const filtered = candidates.filter(cfg.filter);
      if (!filtered.length) return; // active filter matches nothing — don't zoom to invisible spot
      candidates = filtered;
    } else if (cfg?.fallback) {
      const preferred = candidates.filter(cfg.fallback);
      if (preferred.length) candidates = preferred;
    }

    let idx = layerFlyIndexRef.current[id] || 0;
    idx = idx % candidates.length;
    const feature = candidates[idx];
    if (!feature?.geometry) return;

    const { longitude, latitude, zoom } = getBBoxCenter([feature]);
    setViewState({
      ...viewStateRef.current,
      longitude, latitude, zoom,
      pitch: 45, bearing: 0,
      transitionDuration: 1200,
      transitionInterpolator: new FlyToInterpolator({ speed: 1.5 }),
    });
    layerFlyIndexRef.current[id] = (idx + 1) % candidates.length;
    analytics.trackEvent("fly_to_layer", { layer_id: id });

    // Open popup after fly animation — works for every layer
    if (cfg) {
      const props = feature.properties as any;
      const featureId = props?.[cfg.idProp ?? "id"] ?? props?.isa_id ?? props?.platform_id ?? String(idx);
      const deckId = typeof cfg.deckLayerId === "function" ? cfg.deckLayerId(feature) : cfg.deckLayerId;
      setTimeout(() => setSelectedFeature({ id: featureId, layer: deckId, properties: props }), 1300);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [claimsData, reservedData, apeisData, hotspotsData, seamountsData, relinquishedData, argoData, ventsData, eezData, protectedSitesData, noiseRiskData, oceansitesData, oncData, chessData, cablesData, oncCablesData, ooiCablesData, noaaCablesData, nzCablesData, auCablesData, oncInstrumentsData, portsData, hydrophoneData, tectonicData, tailingsData, firesData, airQualityData, landslidesData, damsData, arcticRiversData, siosData, miningFootprintsData, methaneSeepsData, cascadeStationsData, permafrostThawData, cableSourceFilters, offshoreActivityFilters, offshoreActivityCountryFilters, flyConfigs]);
  useEffect(() => { setFlyToLayer(flyToLayer); }, [flyToLayer, setFlyToLayer]);

  // ── Search-by-ID callback ────────────────────────────────────────────────
  const searchById = useCallback((query: string): boolean => {
    const q = query.trim().toLowerCase();
    if (!q) return false;

    // 1. Mining contracts — match isa_id
    const claim = claimsData?.features.find(
      (f: any) => (f.properties?.isa_id ?? "").toLowerCase() === q,
    );
    if (claim) {
      const props = claim.properties as any;
      const { longitude, latitude, zoom } = getBBoxCenter([claim]);
      setViewState({ ...viewStateRef.current, longitude, latitude, zoom: Math.max(zoom, 6), pitch: 45, bearing: 0, transitionDuration: 1200, transitionInterpolator: new FlyToInterpolator({ speed: 1.5 }) });
      setTimeout(() => setSelectedFeature({ id: props.isa_id, layer: "mining-contracts-mvt", properties: props }), 1300);
      return true;
    }

    // 2. Hydrothermal vents — match name (case-insensitive)
    const vent = ventsData?.features.find(
      (f: any) => (f.properties?.name ?? "").toLowerCase().includes(q),
    );
    if (vent) {
      const props = vent.properties as any;
      const { longitude, latitude } = getBBoxCenter([vent]);
      setViewState({ ...viewStateRef.current, longitude, latitude, zoom: 8, pitch: 45, bearing: 0, transitionDuration: 1200, transitionInterpolator: new FlyToInterpolator({ speed: 1.5 }) });
      const deckId = isActiveVentStatus(props.status) ? "hydrothermal-vents-active" : "hydrothermal-vents-inactive";
      setTimeout(() => setSelectedFeature({ id: props.id ?? props.name, layer: deckId, properties: props }), 1300);
      return true;
    }

    // 3. Argo floats — match platform_id
    const argo = argoData?.features.find(
      (f: any) => String(f.properties?.platform_id ?? "").toLowerCase() === q,
    );
    if (argo) {
      const props = argo.properties as any;
      const { longitude, latitude } = getBBoxCenter([argo]);
      setViewState({ ...viewStateRef.current, longitude, latitude, zoom: 7, pitch: 45, bearing: 0, transitionDuration: 1200, transitionInterpolator: new FlyToInterpolator({ speed: 1.5 }) });
      setTimeout(() => setSelectedFeature({ id: props.platform_id, layer: "argo-floats-3d", properties: props }), 1300);
      return true;
    }

    // 4. Chess sites — match locality
    const chess = chessData?.features.find(
      (f: any) => (f.properties?.locality ?? "").toLowerCase().includes(q),
    );
    if (chess) {
      const props = chess.properties as any;
      const { longitude, latitude } = getBBoxCenter([chess]);
      setViewState({ ...viewStateRef.current, longitude, latitude, zoom: 8, pitch: 45, bearing: 0, transitionDuration: 1200, transitionInterpolator: new FlyToInterpolator({ speed: 1.5 }) });
      setTimeout(() => setSelectedFeature({ id: props.locality, layer: "chess", properties: props }), 1300);
      return true;
    }

    return false;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [claimsData, ventsData, argoData, chessData]);
  useEffect(() => { setSearchById(searchById); }, [searchById, setSearchById]);

  // ── ?focus=<id> deep-link: fly to a feature + open its popup ─────────────
  // Used by report back-links. Two forms:
  //   ?focus=<value>            → plain; resolved via searchById (argo/claim/…)
  //   ?focus=seamount:<peak_id> → fly to that seamount + open its panel
  //   ?focus=vent:<name>        → fly to that vent + open its panel
  // For the typed forms we first ensure the layer is active (so its data
  // fetches), then wait for the data, then fly + open. Fires once.
  const focusDoneRef = useRef(false);
  useEffect(() => {
    if (focusDoneRef.current) return;
    const params = new URLSearchParams(locationSearch);
    const focus = params.get("focus");
    if (!focus) return;

    const stripParam = () => {
      focusDoneRef.current = true;
      params.delete("focus");
      const clean = params.toString();
      window.history.replaceState({}, "", window.location.pathname + (clean ? `?${clean}` : ""));
    };
    const flyTo = (feature: any, zoom: number) => {
      const c = getBBoxCenter([feature]);
      setViewState({ ...viewStateRef.current, longitude: c.longitude, latitude: c.latitude, zoom, pitch: 45, bearing: 0, transitionDuration: 1200, transitionInterpolator: new FlyToInterpolator({ speed: 1.5 }) });
    };

    const sep = focus.indexOf(":");
    const type = sep > 0 ? focus.slice(0, sep) : null;
    const value = sep > 0 ? focus.slice(sep + 1) : focus;

    if (type === "seamount") {
      if (!activeLayers.has("seamounts")) { setActiveLayers(new Set(activeLayers).add("seamounts")); return; }
      if (!seamountsData) return; // wait for fetch, effect re-runs when it lands
      const sm = seamountsData.features.find((f: any) => String(f.properties?.peak_id) === value);
      if (sm) {
        flyTo(sm, 7);
        const props = (sm as any).properties;
        setTimeout(() => setSelectedFeature({ id: props.peak_id, layer: "seamounts", properties: props }), 1300);
      } else {
        // ⛔ Was: nothing. The layer came on, the param vanished, no panel
        // opened and nothing was said — so the reader concluded that was the
        // sender's point. Report it instead.
        useMapStore.getState().addSharePanelFailure({ layerId: "seamounts", featureId: value });
      }
      stripParam();
      return;
    }
    if (type === "vent") {
      if (!activeLayers.has("hydrothermal-vents")) { setActiveLayers(new Set(activeLayers).add("hydrothermal-vents")); return; }
      if (!ventsData) return;
      const v = ventsData.features.find((f: any) => (f.properties?.name ?? "").toLowerCase() === value.toLowerCase());
      if (v) {
        flyTo(v, 8);
        const props = (v as any).properties;
        const deckId = isActiveVentStatus(props.status) ? "hydrothermal-vents-active" : "hydrothermal-vents-inactive";
        setTimeout(() => setSelectedFeature({ id: props.id ?? props.name, layer: deckId, properties: props }), 1300);
      } else {
        // Same silence, same fix — see the seamount branch above.
        useMapStore.getState().addSharePanelFailure({ layerId: "hydrothermal-vents", featureId: value });
      }
      stripParam();
      return;
    }

    // Plain focus (argo/claim/chess) — resolved via searchById once argo loads.
    if (!argoData) return;
    if (searchById(focus)) { stripParam(); return; }
    // ⛔ Not found — but "not found YET" and "not there" look identical here,
    // so give up only once every dataset `searchById` consults has landed.
    // Reporting earlier would put a "this object is gone" notice on screen a
    // second before the object appears.
    if (claimsData && ventsData && argoData && chessData) {
      useMapStore.getState().addSharePanelFailure({ layerId: "", featureId: focus });
      stripParam();
    }
  }, [argoData, seamountsData, ventsData, claimsData, chessData, activeLayers, setActiveLayers, locationSearch, searchById]);

  // ── Sync ventsData to store for claim panel lookups ──────────────────────
  useEffect(() => { if (ventsData) storeSetVentsData(ventsData); }, [ventsData, storeSetVentsData]);


  const onViewStateChange = useCallback(({ viewState: vs }: { viewState: Record<string, unknown> }) => {
    viewStateRef.current = vs;
    setViewState(vs);
    setIsInteracting(true);
    if (interactionTimerRef.current) clearTimeout(interactionTimerRef.current);
    interactionTimerRef.current = setTimeout(() => setIsInteracting(false), 150);
  }, []);

  // ── Risk areas: base computation from claims + argo ──────────────────────
  useEffect(() => {
    if (!claimsData) return;
    const timer = setTimeout(() => {
      // Key by isa_id — one entry per specific claim polygon
      const isaMap = new Map<string, import("../store/mapStore").RiskArea>();
      for (const f of claimsData.features) {
        if (!f.properties.is_high_risk) continue;
        const isaId = String(f.properties.isa_id ?? "");
        if (!isaId) continue;
        isaMap.set(isaId, {
          isaId,
          name: f.properties.contractor_name,
          resource_type: f.properties.resource_type,
          hotspots: [],
          argoFloats: [],
          containerFeature: f,
          oncStations: [],
          oceansitesMoorings: [],
          noiseCells: [],
          chessSites: [],
        });
      }
      if (argoData) {
        for (const float of (argoData.features as any[]).filter(f => f.properties?.near_mining)) {
          const floatCoords = float.geometry?.coordinates as [number, number] | undefined;
          const zones: { name: string; dist_km?: number }[] = float.properties?.mining_zones?.length
            ? float.properties.mining_zones
            : float.properties?.mining_zone ? [{ name: float.properties.mining_zone }] : [];
          for (const zone of zones) {
            // Find claims matching this zone name and assign float to the closest one
            for (const [, risk] of isaMap) {
              if (risk.name !== zone.name) continue;
              if (!floatCoords) { risk.argoFloats.push(float); continue; }
              const c = centroid(risk.containerFeature as any).geometry.coordinates as [number, number];
              if (turfDistance(floatCoords, c, { units: "kilometers" }) <= 350) {
                risk.argoFloats.push(float);
              }
            }
          }
        }
      }
      setRiskAreas([...isaMap.values()]);
    }, 500);
    return () => clearTimeout(timer);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [claimsData, argoData]);

  // ── Risk areas: enrich with hotspot species ──────────────────────────────
  useEffect(() => {
    if (!hotspotsData) return;
    setRiskAreas(prev => prev.map(risk => {
      const seen = new Set<string>();
      const hotspots: any[] = [];
      for (const hp of hotspotsData.features) {
        const name = hp.properties?.scientific_name;
        if (!name || seen.has(name)) continue;
        if (booleanPointInPolygon(hp as any, risk.containerFeature as any)) {
          hotspots.push(hp.properties);
          seen.add(name);
        }
      }
      return { ...risk, hotspots };
    }));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hotspotsData]);

  // ── Risk areas: enrich with ONC stations within 200 km ───────────────────
  useEffect(() => {
    if (!oncData) return;
    setRiskAreas(prev => prev.map(risk => {
      const c = centroid(risk.containerFeature as any).geometry.coordinates as [number, number];
      const oncStations = oncData.features.filter((f: any) => {
        const coords = f.geometry?.coordinates as [number, number] | undefined;
        return coords && turfDistance(coords, c, { units: "kilometers" }) <= 200;
      });
      return { ...risk, oncStations };
    }));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [oncData]);

  // ── Risk areas: enrich with OceanSITES moorings within 500 km ───────────
  useEffect(() => {
    if (!oceansitesData) return;
    setRiskAreas(prev => prev.map(risk => {
      const c = centroid(risk.containerFeature as any).geometry.coordinates as [number, number];
      const oceansitesMoorings = oceansitesData.features.filter((f: any) => {
        const coords = f.geometry?.coordinates as [number, number] | undefined;
        return coords && turfDistance(coords, c, { units: "kilometers" }) <= 500;
      });
      return { ...risk, oceansitesMoorings };
    }));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [oceansitesData]);

  // ── Risk areas: enrich with noise risk cells within 200 km ──────────────────
  useEffect(() => {
    if (!noiseRiskData) return;
    setRiskAreas(prev => prev.map(risk => {
      const c = centroid(risk.containerFeature as any).geometry.coordinates as [number, number];
      const noiseCells = noiseRiskData.features.filter((f: any) => {
        const coords = f.geometry?.coordinates as [number, number] | undefined;
        return coords && turfDistance(coords, c, { units: "kilometers" }) <= 200;
      }).sort((a: any, b: any) => (b.properties?.risk_index ?? 0) - (a.properties?.risk_index ?? 0));
      return { ...risk, noiseCells };
    }));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [noiseRiskData]);

  // ── Risk areas: enrich with ChEssBase sites within 10 km ─────────────────
  useEffect(() => {
    if (!chessData) return;
    setRiskAreas(prev => prev.map(risk => {
      const c = centroid(risk.containerFeature as any).geometry.coordinates as [number, number];
      // No longer sorted by habitat weight — habitat_type is gone (it was our
      // own regex over locality, not a source field). Natural filter order.
      const chessSites = chessData.features.filter((f: any) => {
        const coords = f.geometry?.coordinates as [number, number] | undefined;
        return coords && turfDistance(coords, c, { units: "kilometers" }) <= 10;
      });
      return { ...risk, chessSites };
    }));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chessData]);

  // Keep riskAreasRef in sync so the fallback fetch closure reads fresh data
  useEffect(() => { riskAreasRef.current = riskAreas; }, [riskAreas]);

  // ── Targeted hotspot fallback — fires when a claim panel is opened ────────
  // The global tiled fetch caps at 3000/tile. If a dense tile (e.g. CCZ) exceeds
  // the cap, some hotspot records are dropped, leaving is_high_risk claims with an
  // empty species list. This targeted fetch fills the gap for the clicked claim.
  useEffect(() => {
    for (const sf of selectedFeatures) {
      if (sf.layer !== "mining-contracts-mvt") continue;
      if (!sf.properties.is_high_risk) continue;
      const isaId = String(sf.properties.isa_id ?? "");
      const risk = riskAreasRef.current.find(r => r.isaId === isaId);
      if (!risk || risk.hotspots.length > 0) continue; // already enriched

      const geom = risk.containerFeature.geometry as { coordinates?: unknown } | null;
      if (!geom?.coordinates) continue;
      const box: Box = { minLon: Infinity, maxLon: -Infinity, minLat: Infinity, maxLat: -Infinity };
      walkCoords(geom.coordinates, box);
      if (!isFinite(box.minLon)) continue;

      const pad = 0.2;
      fetch(
        `${API}/api/v1/map/biodiversity/hotspots?min_lon=${box.minLon - pad}&max_lon=${box.maxLon + pad}&min_lat=${box.minLat - pad}&max_lat=${box.maxLat + pad}&zoom=8`
      )
        .then(r => r.json())
        .then((fc: FeatureCollection) => {
          setRiskAreas(prev => prev.map(r => {
            if (r.isaId !== isaId) return r;
            if (r.hotspots.length > 0) return r; // enriched by global fetch in the meantime
            const seen = new Set<string>();
            const hotspots: any[] = [];
            for (const hp of fc.features ?? []) {
              const name = hp.properties?.scientific_name;
              if (!name || seen.has(name)) continue;
              if (booleanPointInPolygon(hp as any, r.containerFeature as any)) {
                hotspots.push(hp.properties);
                seen.add(name);
              }
            }
            return { ...r, hotspots };
          }));
          // Also merge into hotspotsData so green dots appear on the map layer
          setHotspotsData(prev => {
            if (!prev) return prev; // only add if layer was already loaded
            const seenCoords = seenHotspotCoordsRef.current;
            const newFeatures = (fc.features ?? []).filter(f => {
              const c = (f.geometry as any)?.coordinates;
              if (!c) return false;
              const key = `${c[0]},${c[1]}`;
              if (seenCoords.has(key)) return false;
              seenCoords.add(key);
              return true;
            });
            if (!newFeatures.length) return prev;
            return { ...prev, features: [...prev.features, ...newFeatures] };
          });
        })
        .catch(() => {});
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedFeatures]);

  const filteredVentsData = useMemo(() => {
    if (!ventsData) return null;
    return {
      ...ventsData,
      features: ventsData.features.filter(f => ventStatusFilters.has(f.properties?.status as string)),
    };
  }, [ventsData, ventStatusFilters]);

  const activeVents = useMemo(
    () => ({ type: "FeatureCollection" as const, features: (filteredVentsData?.features ?? []).filter(f => isActiveVentStatus(f.properties?.status)) }),
    [filteredVentsData]
  );

  const inactiveVents = useMemo(
    () => ({ type: "FeatureCollection" as const, features: (filteredVentsData?.features ?? []).filter(f => !isActiveVentStatus(f.properties?.status)) }),
    [filteredVentsData]
  );

  // ── Zoom-adaptive radii for ColumnLayers ─────────────────────────────────
  // ColumnLayer ignores radiusMinPixels/radiusMaxPixels — must compute radius
  // in meters to maintain a target screen size at any zoom level.
  // Snap zoom to integers so radius stays constant during fly animations —
  // continuous zoom changes would rebuild column geometry every frame (60fps),
  // causing visible flickering.
  const metersPerPixel = useMemo(() => {
    return 156543.03 * Math.cos(20 * Math.PI / 180) / Math.pow(2, snappedZoom);
  }, [snappedZoom]);
  const seamountRadius = useMemo(() => Math.max(300, Math.min(8000, 7 * metersPerPixel)), [metersPerPixel]);
  const ventRadius     = useMemo(() => Math.max(100, Math.min(3000, 5 * metersPerPixel)), [metersPerPixel]);
  const argoRadius     = useMemo(() => Math.max(300, Math.min(6000, 6 * metersPerPixel)), [metersPerPixel]);

  const eezLabelPoints = useMemo(() => {
    if (!eezData) return [];
    return eezData.features
      .filter(f => f.geometry)
      .map(f => {
        const c = centroid(f as any);
        return {
          position: c.geometry.coordinates as [number, number],
          name: f.properties?.geoname ?? f.properties?.name ?? "",
          properties: f.properties ?? {} as Record<string, unknown>,
        };
      })
      .filter(p => p.name);
  }, [eezData]);

  // ── Click handler ────────────────────────────────────────────────────────
  const handlePlumeOriginClick = useCallback(
    (info: PlumeOriginInfo) => {
      setSelectedFeature({
        id: info.profile_id,
        layer: "plume-origin",
        properties: info as unknown as Record<string, unknown>,
      });
    },
    [setSelectedFeature]
  );

  // Derive set of platform_ids that have been plume-traced (for clickable trail dots)
  const tracedPlatforms = useMemo(() => {
    const set = new Set<string>();
    for (const t of plumeTraces) {
      // Each trace's argoId is a profile_id; look up its platform_id from trail data
      if (argoTrailsData?.features) {
        for (const f of argoTrailsData.features) {
          const p = f.properties ?? {};
          if (String(p.profile_id) === t.argoId) {
            set.add(String(p.platform_id));
            break;
          }
        }
      }
    }
    return set;
  }, [plumeTraces, argoTrailsData]);

  const handleTrailDotClick = useCallback((info: PickingInfo) => {
    let props = info.object?.properties ?? {};
    // Inject click coordinates so SeafloorDepthRow (and any future geo-context
    // widget) can resolve a lat/lon — trail-dot data shape doesn't always
    // expose latitude/longitude at the property level.
    if (info.coordinate) {
      props = { ...props, _lon: info.coordinate[0], _lat: info.coordinate[1] };
    }
    setSelectedFeature({
      id: String(props.profile_id ?? info.index),
      layer: "argo-trail-dot",
      properties: props,
    });
  }, [setSelectedFeature]);

  const handleClick = useCallback((info: PickingInfo, event?: any) => {
    // Drawing mode active — suppress all feature-inspect clicks.
    if (useMapStore.getState().selectionMode) return;
    // Hex grid clicks (WOA / oxygen hexes) — route to existing value panels
    const lid0 = info.layer?.id ?? "";
    if (lid0 === "memento-hexes") {
      const p = info.object?.properties;
      if (!p) return;
      // A filtered-out hex is drawn fully transparent, but deck.gl picking ignores
      // alpha — without this guard, clicking where it sits opens a panel for the
      // very points the user just excluded.
      // ⛔ Read the filter from the store, not the closure: handleClick is a
      // useCallback whose dependency array carries no *DecadeFilters, so a closed-over
      // Set stays frozen at the first render's empty value and the guard always passes.
      // Same reason selectionMode is read via getState() at the top of this handler.
      if (!hexPassesDecadeFilter(p, useMapStore.getState().mementoDecadeFilters)) return;
      setSelectedFeature({
        id: `memento-hex:${p.lat},${p.lon}`,
        layer: "memento-hexes",
        properties: { count: p.count, _lat: p.lat, _lon: p.lon,
                      year_min: p.year_min, year_max: p.year_max,
                      n_undated: p.n_undated, by_decade: p.by_decade },
      });
      return;
    }
    if (lid0 === "geotraces-hexes") {
      const p = info.object?.properties;
      if (!p) return;
      // A filtered-out hex is drawn fully transparent, but deck.gl picking ignores
      // alpha — without this guard, clicking where it sits opens a panel for the
      // very points the user just excluded.
      if (!hexPassesDecadeFilter(p, useMapStore.getState().geotracesDecadeFilters)) return;
      setSelectedFeature({
        id: `geotraces-hex:${p.lat},${p.lon}`,
        layer: "geotraces-hexes",
        properties: { count: p.count, _lat: p.lat, _lon: p.lon,
                      year_min: p.year_min, year_max: p.year_max,
                      n_undated: p.n_undated, by_decade: p.by_decade },
      });
      return;
    }
    if (lid0 === "mosaic-hexes") {
      const p = info.object?.properties;
      if (!p) return;
      // A filtered-out hex is drawn fully transparent, but deck.gl picking ignores
      // alpha — without this guard, clicking where it sits opens a panel for the
      // very cores the user just excluded.
      if (!hexPassesDecadeFilter(p, useMapStore.getState().mosaicDecadeFilters)) return;
      setSelectedFeature({
        id: `mosaic-hex:${p.lat},${p.lon}`,
        layer: "mosaic-hexes",
        properties: { count: p.count, _lat: p.lat, _lon: p.lon,
                      year_min: p.year_min, year_max: p.year_max,
                      n_undated: p.n_undated, by_decade: p.by_decade },
      });
      return;
    }
    if (lid0 === "woa-hexes" || lid0 === "oxygen-hexes") {
      const p = info.object?.properties;
      if (!p) return;
      const fieldLayer = lid0 === "woa-hexes" ? "woa-climatology" : "oxygen-deox";
      const depth = fieldLayer === "woa-climatology" ? woaDepth : oxygenDepth;
      setSelectedFeature({
        id: `${fieldLayer}:${p.lat},${p.lon},${depth}`,
        layer: fieldLayer,
        properties: { _lat: p.lat, _lon: p.lon, depth },
      });
      return;
    }
    if (lid0 === "ocean-carbon-hexes") {
      const p = info.object?.properties;
      if (!p) return;
      setSelectedFeature({
        id: `ocean-carbon:${p.lat},${p.lon},${carbonDepth}`,
        layer: "ocean-carbon",
        properties: { _lat: p.lat, _lon: p.lon, depth: carbonDepth },
      });
      return;
    }
    if (lid0 === "ocean-acidification-hexes") {
      const p = info.object?.properties;
      if (!p) return;
      setSelectedFeature({
        id: `ocean-acidification:${p.lat},${p.lon},${acidificationDepth}`,
        layer: "ocean-acidification",
        properties: { _lat: p.lat, _lon: p.lon, depth: acidificationDepth },
      });
      return;
    }
    if (lid0 === "cumulative-human-impact-hexes") {
      const p = info.object?.properties;
      if (!p) return;
      setSelectedFeature({
        id: `cumulative-human-impact:${p.lat},${p.lon}`,
        layer: "cumulative-human-impact",
        properties: { _lat: p.lat, _lon: p.lon },
      });
      return;
    }
    if (lid0 === "marine-carbon-hexes") {
      const p = info.object?.properties;
      if (!p) return;
      setSelectedFeature({
        id: `marine-carbon:${p.lat},${p.lon},${marineCarbonDepth}`,
        layer: "marine-carbon",
        properties: { _lat: p.lat, _lon: p.lon, depth: marineCarbonDepth },
      });
      return;
    }
    if (lid0 === "vme-suitability-hexes") {
      const p = info.object?.properties;
      if (!p) return;
      setSelectedFeature({
        id: `vme:${p.lat},${p.lon}`,
        layer: "vme-suitability",
        properties: { _lat: p.lat, _lon: p.lon },
      });
      return;
    }
    if (lid0 === "coral-acid-exposure-hexes") {
      const p = info.object?.properties;
      if (!p) return;
      // Unlike marine-carbon/vme hexes, this response has no lat/lon in properties
      // (only cell_id/suitability/state) — read the click coordinate instead, same
      // fallback pattern as seabed-substrate-hexes.
      const lat = info.coordinate?.[1];
      const lon = info.coordinate?.[0];
      if (lat == null || lon == null) return;
      setSelectedFeature({
        id: `coral-acid-exposure:${lat},${lon}`,
        layer: "coral-acid-exposure",
        properties: { _lat: lat, _lon: lon, cell_id: p.cell_id, suitability: p.suitability, state: p.state },
      });
      return;
    }
    if (lid0 === "ocean-co2-surface-hexes") {
      const p = info.object?.properties;
      if (!p) return;
      setSelectedFeature({
        id: `ocean-co2-surface:${p.lat},${p.lon},${co2Decade}`,
        layer: "ocean-co2-surface",
        properties: { _lat: p.lat, _lon: p.lon, decade: co2Decade },
      });
      return;
    }
    if (lid0 === "seabed-substrate-hexes") {
      const p = info.object?.properties;
      if (!p) return;
      setSelectedFeature({
        id: `seabed-substrate:${p.lat ?? info.coordinate?.[1]},${p.lon ?? info.coordinate?.[0]}`,
        layer: "seabed-substrate",
        properties: p,
      });
      return;
    }
    if (!info.object) { setSelectedFeature(null); return; }
    let props = info.object.properties ?? info.object;
    // Skip filtered-out claims so clicks fall through to the map
    if (info.layer?.id === "mining-contracts-mvt" && !claimPassesFilter(props)) return;
    // Mirror the offshore filter logic (activity_type + sovereign) used in
    // getFillColor — without this, a layer's pickable: true would still
    // surface clicks on features rendered transparent by the filter.
    if (info.layer?.id === "offshore-activities-mvt" || info.layer?.id === "offshore-zones-mvt") {
      const type = String(props.activity_type ?? "");
      const sov  = String(props.sovereign ?? "");
      if (offshoreActivityFilters.size        && !offshoreActivityFilters.has(type)) return;
      if (offshoreActivityCountryFilters.size && !offshoreActivityCountryFilters.has(sov)) return;
    }
    // Remap deck layer ids that differ from their toggle/panel id
    const layerId = info.layer?.id === "arctic-catchments-mvt"
      ? "arctic-catchments"
      : (info.layer?.id ?? "unknown");
    const id = layerId === "chess"
      ? (props.locality ?? String(info.index))
      : layerId === "deepdata-stations"
        ? (props.station_id ?? String(info.index))
        : layerId === "hydrophone-stations"
          ? (props.station_id ?? String(info.index))
          : layerId === "arctic-rivers"
            ? (props.station_id ?? String(info.index))
            : layerId === "sios-svalbard"
              ? (props.metadata_id ?? props.station_key ?? String(info.index))
              : layerId === "memento"
                ? (props.cast_id ?? String(info.index))
                : layerId === "geotraces"
                  ? (props.station_id ?? String(info.index))
                  : layerId === "arctic-catchments"
                    ? (props.gid ?? String(info.index))
                    : (props.isa_id ?? props.id ?? props.platform_id ?? String(info.index));
    const shift = !!(event?.srcEvent as MouseEvent)?.shiftKey;

    // Inject click coordinates so panels can build Google Earth links for any layer
    if (info.coordinate) {
      props = { ...props, _lon: info.coordinate[0], _lat: info.coordinate[1] };
    }

    setSelectedFeature({ id, layer: layerId, properties: props }, shift);

    // Enrich offshore panel with area_km2 + full columns not stored in tile for perf.
    // Both the concession layer ("offshore-activities-mvt") and the zone layer
    // ("offshore-zones-mvt") share the same /by-id endpoint and panel renderer.
    if ((layerId === "offshore-activities-mvt" || layerId === "offshore-zones-mvt") && props.id != null) {
      fetch(`${API}/api/v2/spatial/offshore-activities/by-id/${props.id}`)
        .then(r => r.ok ? r.json() : null)
        .then((enriched: any) => {
          if (!enriched) return;
          if (!useMapStore.getState().selectedFeatures.some(f => f.id === id)) return;
          setSelectedFeature({ id, layer: layerId, properties: { ...props, ...enriched } }, shift);
        })
        .catch(() => {});
    }

    // Enrich DeepData station panel with citation + horizons + dates.
    if (layerId === "deepdata-stations" && props.station_id) {
      fetch(`${API}/api/v2/map/deepdata-stations/by-id/${encodeURIComponent(String(props.station_id))}`)
        .then(r => r.ok ? r.json() : null)
        .then((enriched: any) => {
          if (!enriched) return;
          if (!useMapStore.getState().selectedFeatures.some(f => f.id === id)) return;
          setSelectedFeature({ id, layer: layerId, properties: { ...props, ...enriched } }, shift);
        })
        .catch(() => {});
    }

    analytics.trackEvent("select_feature", {
      event_category: "interaction",
      event_label: info.layer?.id ?? "unknown",
      feature_id: String(id),
    });

    if (info.layer?.id === "mining-contracts-mvt") {
      // Plume history is opt-in via the "Track historical plumes" button in the
      // mining-contract panel — clicking the polygon no longer auto-fetches
      // plumes (was confusing: plumes appeared without user requesting them
      // and never cleared until reload).
      const contractorName = String(props.contractor_name ?? "");
      analytics.selectConcession(String(id), contractorName);
    }
  }, [setSelectedFeature, claimPassesFilter, offshoreActivityFilters, offshoreActivityCountryFilters, woaDepth, oxygenDepth, carbonDepth, co2Decade]);

  // ── Mining footprints: viewport culling + memoisation ────────────────────
  // 44k polygons is too many to send to the GPU even when only one is visible
  // (deck.gl projects every vertex every frame regardless of viewport). We
  // precompute each feature's bbox once, then pass deck.gl only the features
  // whose bbox intersects a buffered viewport — typically <100 polygons at
  // city zooms. Refilter only fires when the camera moves outside the buffer.

  // 1. One-shot bbox precompute (Float32Array, 4 floats per feature).
  const miningFootprintsBboxes = useMemo(() => {
    if (!miningFootprintsData) return null;
    const features = miningFootprintsData.features;
    const out = new Float32Array(features.length * 4);
    for (let i = 0; i < features.length; i++) {
      const box: Box = { minLon: Infinity, maxLon: -Infinity, minLat: Infinity, maxLat: -Infinity };
      const geom = features[i].geometry as { coordinates?: unknown } | null;
      if (geom?.coordinates) walkCoords(geom.coordinates, box);
      out[i * 4]     = box.minLon;
      out[i * 4 + 1] = box.minLat;
      out[i * 4 + 2] = box.maxLon;
      out[i * 4 + 3] = box.maxLat;
    }
    return out;
  }, [miningFootprintsData]);

  // 2. Update render bbox only when the visible viewport leaves it.
  useEffect(() => {
    if (!activeLayers.has("mining-footprints") || !miningFootprintsData) return;
    const view = approxViewBbox(viewState);
    if (miningRenderBbox && bboxContains(miningRenderBbox, view)) return;
    setMiningRenderBbox(expandBoxBuffer(view, 2));
  }, [viewState, activeLayers, miningFootprintsData, miningRenderBbox]);

  // 3. Filter features whose bbox intersects the render bbox. ~1-2 ms scan at 44k.
  const filteredMiningFootprints = useMemo(() => {
    if (!miningFootprintsData) return null;
    if (!miningFootprintsBboxes || !miningRenderBbox) return miningFootprintsData;
    const { minLon, minLat, maxLon, maxLat } = miningRenderBbox;
    const features = miningFootprintsData.features;
    const out: typeof features = [];
    for (let i = 0; i < features.length; i++) {
      const fMinLon = miningFootprintsBboxes[i * 4];
      const fMinLat = miningFootprintsBboxes[i * 4 + 1];
      const fMaxLon = miningFootprintsBboxes[i * 4 + 2];
      const fMaxLat = miningFootprintsBboxes[i * 4 + 3];
      if (fMaxLon < minLon || fMinLon > maxLon) continue;
      if (fMaxLat < minLat || fMinLat > maxLat) continue;
      out.push(features[i]);
    }
    return { type: "FeatureCollection", features: out } as FeatureCollection;
  }, [miningFootprintsData, miningFootprintsBboxes, miningRenderBbox]);

  // 4. Memoise the layer so deck.gl reuses the instance across pan frames.
  const showMiningStrokes = (viewState.zoom as number) >= 4;
  const miningFootprintsLayer = useMemo(() => {
    if (!activeLayers.has("mining-footprints") || !filteredMiningFootprints) return null;
    return new GeoJsonLayer({
      id: "mining-footprints",
      data: filteredMiningFootprints,
      stroked: showMiningStrokes,
      filled: true,
      getFillColor: MINING_FOOTPRINTS_FILL,
      getLineColor: MINING_FOOTPRINTS_STROKE,
      getLineWidth: 1,
      pickable: !isInteracting,
      onClick: handleClick,
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeLayers, filteredMiningFootprints, showMiningStrokes, isInteracting, handleClick]);

  // ── Layer stack ──────────────────────────────────────────────────────────
  const offshoreFilterKey = useMemo(() => (
    `t=${[...offshoreActivityFilters].sort().join(",") || "ALL"}` +
    `|c=${[...offshoreActivityCountryFilters].sort().join(",").replace(/ /g, "_") || "ALL"}`
  ), [offshoreActivityFilters, offshoreActivityCountryFilters]);

  const MC_RAMP: { pos: number; hex: string }[] = [
    { pos: 0.0, hex: "#0d235c" }, { pos: 0.4, hex: "#286eaa" },
    { pos: 0.7, hex: "#dca06e" }, { pos: 1.0, hex: "#aa1e50" },
  ];

  // VME suitability — viridis ramp, mirrors backend vme_sdm.RAMP_HEX. Values are
  // clamped 0..1 (suitability score or normalised uncertainty).
  const VME_RAMP: { pos: number; hex: string }[] = [
    { pos: 0.00, hex: "#440154" }, { pos: 0.25, hex: "#3b528b" },
    { pos: 0.50, hex: "#21918c" }, { pos: 0.75, hex: "#5ec962" },
    { pos: 1.00, hex: "#fde725" },
  ];

  const layersRaw = [
    // WOA Climatology / Oxygen — ambient field tiles rendered FIRST (bottom)
    // so all point/vector layers draw on top. Only shown in "field" display mode;
    // "hexes" mode uses the PolygonLayer hex grid instead.
    woaActive && woaDisplayMode === "field" && woaTiles ? woaTiles.map((tile, i) => new BitmapLayer({
      id: `woa-climatology-bitmap-${woaVariable}-${woaDepth}-${i}`,
      image: tile.image,
      bounds: tile.bounds,
      opacity: 0.72,
    })) : null,

    oxygenActive && oxygenDisplayMode === "field" && oxygenTiles ? oxygenTiles.map((tile, i) => new BitmapLayer({
      id: `oxygen-deox-bitmap-${oxygenView}-${oxygenDepth}-${i}`,
      bounds: tile.bounds,
      image: tile.image,
      opacity: 0.72,
    })) : [],

    carbonActive && carbonDisplayMode === "field" && carbonTiles ? carbonTiles.map((tile, i) => new BitmapLayer({
      id: `ocean-carbon-bitmap-${carbonVariable}-${carbonDepth}-${i}`,
      image: tile.image,
      bounds: tile.bounds,
      opacity: 0.72,
    })) : null,

    acidActive && acidificationDisplayMode === "field" && acidTiles ? acidTiles.map((tile, i) => new BitmapLayer({
      id: `ocean-acidification-bitmap-${acidificationVariable}-${acidificationDepth}-${i}`,
      image: tile.image,
      bounds: tile.bounds,
      opacity: 0.72,
    })) : null,

    co2Active && co2DisplayMode === "field" && co2Tiles ? co2Tiles.map((tile, i) => new BitmapLayer({
      id: `ocean-co2-surface-bitmap-${co2Variable}-${co2Decade}-${i}`,
      image: tile.image,
      bounds: tile.bounds,
      opacity: 0.72,
    })) : null,

    // Cumulative Human Impact — server-rendered raster PNG tiles (field mode). Single
    // TileLayer id → exact DECK_TO_TOGGLE match → order_idx 72, so the field renders
    // UNDER claims/dots (the seabed/arctic raster pattern, NOT the manually-sliced
    // BitmapLayer field pattern which forces the field on top). pickable:false — the
    // BitmapLayer whole-quad-pick gotcha; field clicks resolve via the <DeckGL onClick>
    // empty-click branch + /v1/chi/point.
    chiActive && chiDisplayMode === "field" && new TileLayer({
      id: "cumulative-human-impact-raster",
      data: `${API}/api/v1/chi/raster/{z}/{x}/{y}.png?v=${tileCacheVersion}`,
      minZoom: 0, maxZoom: 8, tileSize: 256, refinementStrategy: "no-overlap",
      opacity: 0.72,
      pickable: false,
      updateTriggers: { data: [tileCacheVersion] },
      onTileError: () => onTileLayerError("Cumulative Human Impact"),
      renderSubLayers: (props: any) => new BitmapLayer(props, {
        data: undefined, image: props.data,
        bounds: [props.tile.boundingBox[0][0], props.tile.boundingBox[0][1],
                 props.tile.boundingBox[1][0], props.tile.boundingBox[1][1]],
      }),
    }),

    // ⛔ Do NOT hardcode a vintage in prose here. wms.gebco.net serves
    // GEBCO_LATEST, so the grid changes under us: a comment predicting
    // "GEBCO_2025 from June 2026" was wrong by the time it shipped —
    // GEBCO published 2026 in April. The single source of truth is
    // GEBCO_ATTRIBUTION in utils/gebcoTiles.ts, checked against
    // GetCapabilities. Live check 2026-09-10: GEBCO_2026, and only that.
    // Shaded-relief seafloor — rendered FIRST so every other layer
    // (vents, Argo floats, polygons, density grid) sits on top of it. Default
    // off; users toggle on for depth context. Tile pyramid up to z=8 (~150 m
    // pixel at equator) — enough detail without hammering GEBCO's free service.
    activeLayers.has("bathymetry") && new TileLayer({
      id: "bathymetry",
      // GEBCO WMS needs bbox per tile (not {x}/{y}/{z}), so we override getTileData
      // to build the URL and fetch the image manually. `data` is required by the
      // type but unused when getTileData is set; we pass an empty string.
      data: "",
      getTileData: async ({ index }) => {
        const url = gebcoTileUrl(index.z, index.x, index.y);
        const blob = await fetch(url).then(r => r.ok ? r.blob() : Promise.reject(r.status));
        return await createImageBitmap(blob);
      },
      minZoom: 0,
      maxZoom: 8,
      tileSize: 256,
      // 0.55 (down from 0.85): the shaded relief was visually dominating
      // every layer drawn on top of it, making thin cyan polygon outlines
      // (mining contracts, reserved areas) effectively invisible against
      // the busy backdrop. 0.55 keeps the depth context readable but lets
      // strokes pop.
      opacity: 0.55,
      renderSubLayers: (props: any) => {
        const [[west, south], [east, north]] = props.tile.boundingBox;
        return new BitmapLayer(props, {
          data: undefined,
          image: props.data,
          bounds: [west, south, east, north],
          // Fully decouple bathymetry from the GPU depth buffer:
          // - depthMask:false  → don't write depth (vector layers behind us
          //                       in z still pass their depth test if any)
          // - depthTest:false  → we don't read depth (always draw)
          // Combined: bathymetry is a pure 2D background overlay, isolated
          // from any 3D extrusions (e.g. Argo column heights).
          parameters: { depthMask: false, depthTest: false },
        });
      },
      onTileError: () => onTileLayerError("GEBCO Bathymetry"),
      onTileLoad: () => onTileLayerLoad("GEBCO Bathymetry"),
    }),

    // Marine Carbon unified hex — kept at the BACK of the render/pick order (just
    // above the bathymetry basemap) so claims, seamounts, biodiversity dots, etc.
    // render and stay clickable on top of it. Translucent, so it still shows through.
    marineCarbonActive && marineCarbonHex && new PolygonLayer({
      id: "marine-carbon-hexes",
      data: marineCarbonHex.features,
      getPolygon: (f: any) => f.geometry.coordinates[0],
      filled: true, stroked: true,
      getLineColor: [255, 255, 255, 40], getLineWidth: 1, lineWidthMinPixels: 0.4,
      // value==null → selected variable has no data here (e.g. sparse SOCAT fCO₂),
      // but the cell still has other sources; render a clearly-visible muted slate
      // (alpha 140 vs the 170 of coloured data cells) so the ocean reads as full and
      // "click for other sources" rather than disappearing. NOTE: must NOT pass null
      // to rampColor — it yields NaN channels and the cell renders invisible.
      getFillColor: (f: any) =>
        f.properties.value == null
          ? [100, 116, 139, 140]
          : rampColor(f.properties.value, marineCarbonHex.vmin, marineCarbonHex.vmax, MC_RAMP),
      updateTriggers: { getFillColor: [marineCarbonVariable, marineCarbonDepth, marineCarbonHex] },
      // Pure 2D background field: don't write/test depth (same as the bathymetry
      // basemap). Without this, the large flat hexes write the depth buffer and, on a
      // pitched globe, occlude BOTH the rendering and the picking of dots/claims behind
      // them — so clicks were swallowed even with the layer at the back of the array.
      parameters: { depthMask: false, depthTest: false },
      pickable: true,
      onClick: handleClick,
    }),

    // VME Suitability (modeled) unified hex — same back-of-stack pattern as
    // marine-carbon: translucent field, claims/dots stay clickable on top.
    vmeActive && vmeHex && new PolygonLayer({
      id: "vme-suitability-hexes",
      data: vmeHex.features,
      getPolygon: (f: any) => f.geometry.coordinates[0],
      filled: true, stroked: true,
      getLineColor: [255, 255, 255, 40], getLineWidth: 1, lineWidthMinPixels: 0.4,
      getFillColor: (f: any) =>
        f.properties.value == null
          ? [100, 116, 139, 140]
          : rampColor(Math.max(0, Math.min(vmeMax, f.properties.value)), 0, vmeMax, VME_RAMP),
      updateTriggers: { getFillColor: [vmeView, vmeHex, vmeMax] },
      parameters: { depthMask: false, depthTest: false },
      pickable: true,
      onClick: handleClick,
    }),

    // Coral Acidification Exposure — VME suitability × aragonite horizon crossing.
    // Same back-of-stack pattern as marine-carbon/vme-suitability: translucent field,
    // claims/dots stay clickable on top. Coloured from /meta so map + panel never drift
    // from the backend's STATE_COLORS.
    coralExposureActive && coralExposureFeatures && new PolygonLayer({
      id: "coral-acid-exposure-hexes",
      data: coralExposureFeatures,
      getPolygon: (f: any) => f.geometry.coordinates[0],
      filled: true, stroked: false,
      getFillColor: (f: any) =>
        (coralExposureMeta?.states.find((s: any) => s.key === f.properties.state)?.color)
          ?? [148, 163, 184, 90],
      updateTriggers: { getFillColor: [coralExposureMeta] },
      parameters: { depthMask: false, depthTest: false },
      pickable: true,
      onClick: handleClick,
    }),

    // Tectonic plate fill — subtle, underneath everything
    activeLayers.has("tectonic-plates") && tectonicData?.plates && new GeoJsonLayer({
      id: "tectonic-plates-fill",
      data: tectonicData.plates,
      filled: true, stroked: false,
      getFillColor: [201, 149, 110, 18],
      pickable: true, autoHighlight: true, highlightColor: [201, 149, 110, 40],
      onClick: handleClick,
    }),

    // Tectonic plate boundaries
    activeLayers.has("tectonic-plates") && tectonicData?.boundaries && new GeoJsonLayer({
      id: "tectonic-plates-boundaries",
      data: tectonicData.boundaries,
      filled: false, stroked: true,
      getLineColor: [201, 149, 110, 160],
      getLineWidth: 1, lineWidthMinPixels: 1,
      pickable: true, autoHighlight: true, highlightColor: [201, 149, 110, 100],
      onClick: handleClick,
    }),

    // Offshore zone classifications — non-concession aggregate polygons
    // (Colombia ANH "sin asignar"/"ambiental", PASA "available_block").
    // Backend serves these from a separate /tiles/offshore-zones SQL path.
    // Rendered FIRST (bottom of the offshore stack) at slate alpha that fades
    // with zoom — visible at z<7 to indicate "open zone" context, fades out
    // by z≥9 so users can read terrain + concessions clearly when zoomed in.
    // Pickable so clicks land on zone polygons in pure-zone areas, but the
    // concession layer rendered on top wins picks wherever they overlap.
    //
    // POSITION NOTE: this whole offshore stack (zones + concessions) is
    // intentionally placed at the bottom of the layers array — right after
    // tectonic plates and before every other polygon/point layer — so that
    // OBIS dots, Argo floats, hydrothermal vents and other point markers
    // always render ON TOP of offshore polygons. Without this, large
    // offshore concessions (e.g. Australian NOPTA blocks) visually obscure
    // the species/sensor dots that are scientifically more important on a
    // mining-impact map.
    activeLayers.has("offshore-activities") && new MVTLayer({
      id: "offshore-zones-mvt",
      data: `${API}/api/v2/spatial/tiles/offshore-zones/{z}/{x}/{y}?v=${tileCacheVersion}`,
      minZoom: 2, maxZoom: 14, tileSize: 512,
      getFillColor: (f: any) => {
        const type = f.properties?.activity_type as string;
        const sov  = String(f.properties?.sovereign ?? "");
        if (offshoreActivityFilters.size        && !offshoreActivityFilters.has(type)) return [0, 0, 0, 0];
        if (offshoreActivityCountryFilters.size && !offshoreActivityCountryFilters.has(sov)) return [0, 0, 0, 0];
        const a = snappedZoom < 6 ? 60 : snappedZoom < 8 ? 40 : snappedZoom < 10 ? 25 : 15;
        return [148, 163, 184, a];
      },
      getLineColor: (f: any) => {
        const type = f.properties?.activity_type as string;
        const sov  = String(f.properties?.sovereign ?? "");
        if (offshoreActivityFilters.size        && !offshoreActivityFilters.has(type)) return [0, 0, 0, 0];
        if (offshoreActivityCountryFilters.size && !offshoreActivityCountryFilters.has(sov)) return [0, 0, 0, 0];
        const a = snappedZoom < 8 ? 140 : snappedZoom < 10 ? 90 : 60;
        return [148, 163, 184, a];
      },
      getLineWidth: 1, lineWidthMinPixels: 1,
      pickable: true, autoHighlight: true, highlightColor: [255, 255, 255, 60],
      onClick: handleClick,
      updateTriggers: {
        getFillColor: [offshoreActivityFilters, offshoreActivityCountryFilters, snappedZoom],
        getLineColor: [offshoreActivityFilters, offshoreActivityCountryFilters, snappedZoom],
      },
      onTileError: () => onTileLayerError("Offshore Activities"),
      onTileLoad: () => onTileLayerLoad("Offshore Activities"),
    }),

    // Offshore Activities — concessions only (zones excluded server-side).
    // Rendered AFTER the zones layer so concessions visually + click-wise win
    // wherever they overlap a zone polygon underneath.
    activeLayers.has("offshore-activities") && new MVTLayer({
      id: "offshore-activities-mvt",
      data: `${API}/api/v2/spatial/tiles/offshore-activities/{z}/{x}/{y}?v=${tileCacheVersion}`,
      // maxZoom: 14 lets deck.gl fetch native-zoom tiles up to z=14, eliminating
      // the "blank layer at viewport > maxZoom" race seen on small lease blocks
      // (BOEM Cook Inlet etc). Performance verified fine at z=13-14 (~4 ms/tile)
      // thanks to geom_3857 + slim SQL. Fragmentation at high zoom is handled by
      // the PolygonThumbnail SVG in the panel, not by trying to "un-fragment"
      // the map.
      minZoom: 2, maxZoom: 14, tileSize: 512,
      getFillColor: (f: any) => {
        const type = f.properties?.activity_type as string;
        const sov  = String(f.properties?.sovereign ?? "");
        if (offshoreActivityFilters.size        && !offshoreActivityFilters.has(type)) return [0, 0, 0, 0];
        if (offshoreActivityCountryFilters.size && !offshoreActivityCountryFilters.has(sov)) return [0, 0, 0, 0];
        const a = snappedZoom < 10 ? 60 : 100;
        if (type === "offshore_wind") return [56,  189, 248, a];
        if (type === "seabed_mining") return [217,  70, 239, a];
        if (type === "ccs_storage")   return [ 16, 185, 129, a];
        return [220, 38, 38, a]; // oil_gas / fallback
      },
      getLineColor: (f: any) => {
        const type = f.properties?.activity_type as string;
        const sov  = String(f.properties?.sovereign ?? "");
        if (offshoreActivityFilters.size        && !offshoreActivityFilters.has(type)) return [0, 0, 0, 0];
        if (offshoreActivityCountryFilters.size && !offshoreActivityCountryFilters.has(sov)) return [0, 0, 0, 0];
        if (type === "offshore_wind") return [56,  189, 248, 220];
        if (type === "seabed_mining") return [217,  70, 239, 220];
        if (type === "ccs_storage")   return [ 16, 185, 129, 220];
        return [220, 38, 38, 220];
      },
      getLineWidth: 1, lineWidthMinPixels: 1,
      pickable: true, autoHighlight: true, highlightColor: [255, 255, 255, 50],
      onClick: handleClick,
      updateTriggers: {
        getFillColor: [offshoreActivityFilters, offshoreActivityCountryFilters, snappedZoom],
        getLineColor: [offshoreActivityFilters, offshoreActivityCountryFilters],
      },
      onTileError: () => onTileLayerError("Offshore Activities"),
      onTileLoad: () => onTileLayerLoad("Offshore Activities"),
    }),

    activeLayers.has("relinquished-areas") && relinquishedData && new GeoJsonLayer({
      id: "relinquished-areas",
      data: relinquishedData,
      filled: true, stroked: true,
      getFillColor: [255, 68, 102, 45],
      getLineColor: [255, 68, 102, 180],
      getLineWidth: 1, lineWidthMinPixels: 1,
      pickable: true, autoHighlight: true, highlightColor: [255, 68, 102, 80],
      onClick: handleClick,
    }),

    activeLayers.has("reserved-areas") && reservedData && new GeoJsonLayer({
      id: "reserved-areas",
      data: reservedData,
      filled: true, stroked: true,
      getFillColor: [0, 255, 159, 40],
      getLineColor: [0, 255, 159, 200],
      getLineWidth: 1, lineWidthMinPixels: 1,
      pickable: true, autoHighlight: true, highlightColor: [0, 255, 159, 80],
      onClick: handleClick,
    }),

    activeLayers.has("apeis") && apeisData && new GeoJsonLayer({
      id: "apeis",
      data: apeisData,
      filled: true, stroked: true,
      getFillColor: [191, 95, 255, 50],
      getLineColor: [191, 95, 255, 200],
      getLineWidth: 1, lineWidthMinPixels: 1,
      pickable: true, autoHighlight: true, highlightColor: [191, 95, 255, 80],
      onClick: handleClick,
    }),

    activeLayers.has("eez") && eezData && new GeoJsonLayer({
      id: "eez",
      data: eezData,
      filled: false, stroked: true,
      getLineColor: [255, 215, 0, 160],
      getLineWidth: 1, lineWidthMinPixels: 1,
      pickable: true, autoHighlight: true, highlightColor: [255, 215, 0, 60],
      onClick: handleClick,
    }),

    activeLayers.has("eez") && eezData && new TextLayer({
      id: "eez-labels",
      data: eezLabelPoints,
      getPosition: (d: any) => d.position,
      getText: (d: any) => d.name,
      getSize: 12,
      getColor: [255, 215, 0, 220],
      getAngle: 0,
      fontFamily: "sans-serif",
      fontWeight: "600",
      background: true,
      getBackgroundColor: [0, 0, 0, 160],
      backgroundPadding: [4, 2],
      visible: (viewState.zoom as number) >= 2.5,
      pickable: true,
      onClick: (info: PickingInfo, event?: any) => {
        if (!info.object) return;
        const props = info.object.properties as Record<string, unknown>;
        const id = props?.mrgid ?? info.object.name ?? String(info.index);
        const shift = !!(event?.srcEvent as MouseEvent)?.shiftKey;
        setSelectedFeature({ id: String(id), layer: "eez", properties: props }, shift);
      },
    }),

    activeLayers.has("protected-marine-sites") && protectedSitesData && new GeoJsonLayer({
      id: "protected-marine-sites",
      data: protectedSitesData,
      filled: true, stroked: true,
      getFillColor: [0, 230, 118, 40],
      getLineColor: [0, 230, 118, 200],
      getLineWidth: 1, lineWidthMinPixels: 1,
      pickable: true, autoHighlight: true, highlightColor: [0, 230, 118, 80],
      onClick: handleClick,
    }),

    activeLayers.has("contracts") && new MVTLayer({
      id: "mining-contracts-mvt",
      data: `${API}/api/v2/spatial/tiles/mining_contracts/{z}/{x}/{y}?v=${tileCacheVersion}`,
      minZoom: 1, maxZoom: 14,
      getFillColor: (f: any) => claimPassesFilter(f.properties)
        ? (RESOURCE_COLOR[f.properties?.resource_type as string] ?? [100, 160, 255, 180])
        : [0, 0, 0, 0],
      getLineColor: (f: any) => claimPassesFilter(f.properties) ? [0, 242, 255, 180] : [0, 0, 0, 0],
      lineWidthMinPixels: 2,
      updateTriggers: {
        getFillColor: [claimRiskFilters, hiddenContractors, riskAreas, ventConflicts],
        getLineColor:  [claimRiskFilters, hiddenContractors, riskAreas, ventConflicts],
      },
      pickable: true, autoHighlight: true, highlightColor: [255, 255, 255, 60],
      onClick: handleClick,
      onTileError: () => onTileLayerError("Mining Claims"),
      onTileLoad: () => onTileLayerLoad("Mining Claims"),
    }),

    // Seamounts & Knolls — octagonal column scaled to actual height (visible from zoom 5.5+)
    activeLayers.has("seamounts") && seamountsData && (viewState.zoom as number) >= 5.5 && new ColumnLayer({
      id: "seamounts",
      data: seamountsFeatures,
      getPosition: (f: any) => f.geometry.coordinates,
      getElevation: (f: any) => Math.max((f.properties?.height_m as number) ?? 300, 300),
      getFillColor: (f: any) =>
        f.properties?.in_concession ? [245, 210, 0, 220] : [145, 205, 255, 200],
      radius: seamountRadius,
      diskResolution: 8,
      extruded: true,
      flatShading: true,
      pickable: true,
      onClick: handleClick,
    }),

    // ── Biodiversity Hotspots — ScatterplotLayer at all zoom levels ──────────
    // Glow layer: large transparent circles that overlap into density blobs
    activeLayers.has("biodiversity-hotspots") && hotspotsData
      && new ScatterplotLayer({
        id: "biodiversity-hotspots-glow",
        data: filteredHotspotsFeatures,
        getPosition: (f: any) => f.geometry.coordinates,
        getRadius: 80000,
        getFillColor: (f: any) => { const c = hotspotPointColor(f.properties); return [c[0], c[1], c[2], 35]; },
        radiusMinPixels: 8, radiusMaxPixels: 40,
        pickable: false,
        parameters: { depthTest: false },
        updateTriggers: { getFillColor: [iucnFilters] },
      }),

    // Core dot — pickable at all zoom levels
    activeLayers.has("biodiversity-hotspots") && hotspotsData
      && new ScatterplotLayer({
        id: "biodiversity-hotspots",
        data: filteredHotspotsFeatures,
        getPosition: (f: any) => f.geometry.coordinates,
        getRadius: 30000,
        getFillColor: (f: any) => hotspotPointColor(f.properties),
        getLineColor: (f: any) => hotspotPointColor(f.properties),
        stroked: true, lineWidthMinPixels: 1,
        radiusMinPixels: 3, radiusMaxPixels: 18,
        pickable: true, autoHighlight: true, highlightColor: [160, 255, 180, 80],
        onClick: handleClick,
        parameters: { depthTest: false },
        updateTriggers: { getFillColor: [iucnFilters], getLineColor: [iucnFilters] },
      }),

    // Monitoring density grid — PolygonLayer bypasses GeoJsonLayer tessellation on GlobeView
    activeLayers.has("monitoring-density") && monitoringDensityData && new PolygonLayer({
      id: "monitoring-density",
      data: monitoringDensityData.features,
      getPolygon: (f: any) => f.geometry.coordinates[0],
      filled: true,
      stroked: true,
      getLineColor: [255, 255, 255, 110],
      getLineWidth: 1,
      lineWidthMinPixels: 0.6,
      getFillColor: (f: any) => {
        // Scale matches the LegendPanel colorRampHex + colorRamp labels exactly.
        // Reversed per scientist feedback (June 2026): MORE data = DARKER + more
        // prominent, so well-observed cells now read strongest and monitoring gaps
        // fade to pale. 0–4 cream (gap) → 5–19 yellow → 20–59 orange → 60–199 red
        // → 200+ dark red. Alpha rises with density so high-coverage cells dominate;
        // sparse/gap cells stay translucent.
        const cnt: number = f.properties?.point_count ?? 0;
        if (cnt < 5)   return [240, 240, 210, 70];  // 0–4   monitoring gap (lightest)
        if (cnt < 20)  return [225, 200, 110, 80];  // 5–19  sparse
        if (cnt < 60)  return [230, 140, 50, 100];  // 20–59 moderate
        if (cnt < 200) return [200, 45, 35, 130];   // 60–199 good coverage
        return [140, 20, 20, 155];                  // 200+  well-observed (darkest)
      },
      pickable: true,
      autoHighlight: true,
      highlightColor: [255, 255, 255, 60],
      onClick: handleClick,
    }),

    // WOA / Oxygen hex grids — value-ramped PolygonLayers, shown in "hexes" display mode.
    // Placed near monitoring-density so point layers stay on top.
    woaActive && woaDisplayMode === "hexes" && woaHexData && new PolygonLayer({
      id: "woa-hexes",
      data: woaHexData.features,
      getPolygon: (f: any) => f.geometry.coordinates[0],
      filled: true, stroked: true,
      getLineColor: [255, 255, 255, 40], getLineWidth: 1, lineWidthMinPixels: 0.4,
      getFillColor: (f: any) => {
        const vm = woaMeta?.variables.find((v) => v.key === woaVariable);
        return vm ? rampColor(f.properties.value, vm.vmin, vm.vmax, vm.ramp ?? []) : [150, 150, 150, 170];
      },
      updateTriggers: { getFillColor: [woaVariable, woaDepth, woaMeta] },
      pickable: true,
      onClick: handleClick,
    }),

    oxygenActive && oxygenDisplayMode === "hexes" && oxygenHexData && new PolygonLayer({
      id: "oxygen-hexes",
      data: oxygenHexData.features,
      getPolygon: (f: any) => f.geometry.coordinates[0],
      filled: true, stroked: true,
      getLineColor: [255, 255, 255, 40], getLineWidth: 1, lineWidthMinPixels: 0.4,
      getFillColor: (f: any) => {
        const vw = oxygenMeta?.views.find((v) => v.key === oxygenView);
        return vw ? rampColor(f.properties.value, vw.vmin, vw.vmax, vw.ramp ?? []) : [150, 150, 150, 170];
      },
      updateTriggers: { getFillColor: [oxygenView, oxygenDepth, oxygenMeta] },
      pickable: true,
      onClick: handleClick,
    }),

    activeLayers.has("seabed-substrate") && seabedDisplayMode === "hexes" && seabedHexData && new PolygonLayer({
      id: "seabed-substrate-hexes",
      data: seabedHexData.features,
      getPolygon: (f: any) => f.geometry.coordinates[0],
      getFillColor: (f: any) => seabedColor(f.properties?.class_code),
      getLineColor: [255, 255, 255, 20],
      lineWidthMinPixels: 0.5,
      pickable: true,
      onClick: handleClick,
      updateTriggers: { getFillColor: [seabedHexData] },
    }),

    carbonActive && carbonDisplayMode === "hexes" && carbonHexData && new PolygonLayer({
      id: "ocean-carbon-hexes",
      data: carbonHexData.features,
      getPolygon: (f: any) => f.geometry.coordinates[0],
      filled: true, stroked: true,
      getLineColor: [255, 255, 255, 40], getLineWidth: 1, lineWidthMinPixels: 0.4,
      getFillColor: (f: any) => {
        const vm = carbonMeta?.variables.find((v) => v.key === carbonVariable);
        return vm ? rampColor(f.properties.value, vm.vmin, vm.vmax, vm.ramp ?? []) : [150, 150, 150, 170];
      },
      updateTriggers: { getFillColor: [carbonVariable, carbonDepth, carbonMeta] },
      pickable: true,
      onClick: handleClick,
    }),

    acidActive && acidificationDisplayMode === "hexes" && acidHexData && new PolygonLayer({
      id: "ocean-acidification-hexes",
      data: acidHexData.features,
      getPolygon: (f: any) => f.geometry.coordinates[0],
      filled: true, stroked: true,
      getLineColor: [255, 255, 255, 40], getLineWidth: 1, lineWidthMinPixels: 0.4,
      getFillColor: (f: any) => {
        const vm = acidMeta?.variables.find((v) => v.key === acidificationVariable);
        if (!vm) return [150, 150, 150, 170];
        // Aragonite/calcite use a diverging ramp anchored on Ω=1 (center) — match
        // the server-baked field bitmap. Horizon (sequential) uses linear rampColor.
        return vm.kind === "diverging" && vm.center != null
          ? divergingRampColor(f.properties.value, vm.vmin, vm.center, vm.vmax, vm.ramp ?? [])
          : rampColor(f.properties.value, vm.vmin, vm.vmax, vm.ramp ?? []);
      },
      updateTriggers: { getFillColor: [acidificationVariable, acidificationDepth, acidMeta] },
      pickable: true,
      onClick: handleClick,
    }),

    // Cumulative Human Impact — pickable hex readout (sequential ramp, single "impact" var).
    chiActive && chiDisplayMode === "hexes" && chiHexData && new PolygonLayer({
      id: "cumulative-human-impact-hexes",
      data: chiHexData.features,
      getPolygon: (f: any) => f.geometry.coordinates[0],
      filled: true, stroked: true,
      getLineColor: [255, 255, 255, 40], getLineWidth: 1, lineWidthMinPixels: 0.4,
      getFillColor: (f: any) => {
        const vm = chiMeta?.variables.find((v) => v.key === "impact");
        return vm ? rampColor(f.properties.value, vm.vmin, vm.vmax, vm.ramp ?? []) : [150, 150, 150, 170];
      },
      updateTriggers: { getFillColor: [chiMeta] },
      pickable: true,
      onClick: handleClick,
    }),

    co2Active && co2DisplayMode === "hexes" && co2HexData && new PolygonLayer({
      id: "ocean-co2-surface-hexes",
      data: co2HexData.features,
      getPolygon: (f: any) => f.geometry.coordinates[0],
      filled: true, stroked: true,
      getLineColor: [255, 255, 255, 40], getLineWidth: 1, lineWidthMinPixels: 0.4,
      getFillColor: (f: any) => {
        const vm = co2Meta?.variables.find((v) => v.key === co2Variable);
        return vm ? rampColor(f.properties.value, vm.vmin, vm.vmax, vm.ramp ?? []) : [150, 150, 150, 170];
      },
      updateTriggers: { getFillColor: [co2Variable, co2Decade, co2Meta] },
      pickable: true,
      onClick: handleClick,
    }),

    activeLayers.has("noise-risk") && noiseRiskData && new ScatterplotLayer({
      id: "noise-risk",
      data: filteredNoiseFeatures,
      getPosition: (f: any) => f.geometry.coordinates,
      getRadius: (f: any) => Math.max(30000, (f.properties?.risk_index ?? 0.1) * 120000),
      getFillColor: (f: any) => noiseRiskColor(f.properties?.risk_level ?? "minimal"),
      radiusMinPixels: 4,
      radiusMaxPixels: 28,
      pickable: true,
      autoHighlight: true,
      highlightColor: [255, 255, 255, 60],
      onClick: handleClick,
      parameters: { depthTest: false },
      updateTriggers: { getFillColor: [Array.from(noiseRiskFilters)], data: [Array.from(noiseRiskFilters)] },
    }),

    // Drift trails rendered below the main columns so columns stay on top
    ...(activeLayers.has("argo") ? buildArgoTrailLayers(argoTrailsData, datasetStats, tracedPlatforms, handleTrailDotClick) : []),

    activeLayers.has("argo") && argoSensorFaultFeatures.length > 0 && new ScatterplotLayer({
      id: "argo-sensor-fault-ring",
      data: argoSensorFaultFeatures,
      getPosition: (f: any) => f.geometry.coordinates,
      stroked: true,
      filled: false,
      getLineColor: [245, 158, 11, 230],   // amber-500 — "data suspect"
      lineWidthMinPixels: 2,
      getRadius: 45000,
      radiusMinPixels: 10, radiusMaxPixels: 30,
      pickable: false,
      parameters: { depthTest: false },
    }),

    activeLayers.has("argo") && filteredArgoData && new ScatterplotLayer({
      id: "argo-glow",
      data: argoAlarmFeatures,
      getPosition: (f: any) => f.geometry.coordinates,
      getRadius: 60000,
      getFillColor: [255, 40, 40, 30],
      radiusMinPixels: 12, radiusMaxPixels: 50,
      pickable: false,
      parameters: { depthTest: false },
    }),

    activeLayers.has("argo") && filteredArgoData && new ColumnLayer({
      id: "argo-floats-3d",
      data: filteredArgoData.features,
      getPosition: (f: any) => f.geometry.coordinates,
      getElevation: (f: any) => (f.properties?.max_depth_m as number) ?? 500,
      getFillColor: (f: any) =>
        argoAlarmIdSet.has(String(f.properties?.platform_id ?? ""))
          ? [255, 50, 50, 230]
          : [0, 200, 255, 180],
      updateTriggers: { getFillColor: [argoAlarmIdSet] },
      radius: argoRadius,
      diskResolution: 12,
      extruded: true,
      flatShading: true,
      pickable: true,
      onClick: handleClick,
    }),

    // Active vents — narrow bright chimney upward + warm glow halo.
    // ⭐ Confirmed (directly observed) vs inferred (deduced from a plume or
    // chemical anomaly) must stay visually distinct — 54% of what the map
    // used to lump into one word "Active" was inferred. Same red hue for
    // both (no new palette entry); only opacity carries the distinction:
    // confirmed gets the full glow halo, inferred gets none — an inferred
    // vent's "glow" was never observed, so it doesn't get to look observed.
    activeLayers.has("hydrothermal-vents") && activeVents.features.length > 0 && new ScatterplotLayer({
      id: "hydrothermal-vents-active-glow",
      data: activeVents.features,
      getPosition: (f: any) => f.geometry.coordinates,
      getRadius: 28000,
      getFillColor: (f: any) => isConfirmedVentStatus(f.properties?.status) ? [255, 35, 35, 22] : [255, 35, 35, 0],
      radiusMinPixels: 3, radiusMaxPixels: 10,
      pickable: false,
      parameters: { depthTest: false },
    }),

    activeLayers.has("hydrothermal-vents") && activeVents.features.length > 0 && new ColumnLayer({
      id: "hydrothermal-vents-active",
      data: activeVents.features,
      getPosition: (f: any) => f.geometry.coordinates,
      getElevation: 1800,
      // Confirmed: full opacity. Inferred: same colour, dimmed — the
      // opacity difference this project's style vocabulary uses elsewhere.
      getFillColor: (f: any) => isConfirmedVentStatus(f.properties?.status) ? [255, 35, 35, 235] : [255, 35, 35, 120],
      radius: ventRadius,
      diskResolution: 6,
      extruded: true,
      flatShading: true,
      pickable: true, autoHighlight: true, highlightColor: [255, 150, 150, 100],
      onClick: handleClick,
    }),

    // Inactive vents — shorter cooler chimney, no glow
    activeLayers.has("hydrothermal-vents") && inactiveVents.features.length > 0 && new ColumnLayer({
      id: "hydrothermal-vents-inactive",
      data: inactiveVents.features,
      getPosition: (f: any) => f.geometry.coordinates,
      getElevation: 800,
      getFillColor: [90, 120, 170, 175],
      radius: ventRadius,
      diskResolution: 6,
      extruded: true,
      flatShading: true,
      pickable: true, autoHighlight: true, highlightColor: [180, 210, 255, 60],
      onClick: handleClick,
    }),

    // OceanSITES — cyan rings (outlined, no fill) → look like mooring buoys
    activeLayers.has("oceansites") && oceansitesData && new ScatterplotLayer({
      id: "oceansites",
      data: filteredOceansitesFeatures,
      getPosition: (f: any) => f.geometry.coordinates,
      getFillColor: [0, 220, 255, 0],      // transparent fill → ring shape
      getLineColor: [0, 220, 255, 230],
      filled: false,
      stroked: true,
      lineWidthMinPixels: 2,
      getRadius: 10000,
      radiusMinPixels: 5,
      radiusMaxPixels: 22,
      pickable: true,
      autoHighlight: true,
      highlightColor: [0, 255, 255, 60],
      onClick: handleClick,
      parameters: { depthTest: false },
    }),

    // ONC — teal filled dots with thick outer ring (glow halo layer + core dot)
    activeLayers.has("onc") && oncData && new ScatterplotLayer({
      id: "onc-glow",
      data: filteredOncFeatures,
      getPosition: (f: any) => f.geometry.coordinates,
      getFillColor: [77, 184, 164, 30],
      getRadius: 18000,
      radiusMinPixels: 6, radiusMaxPixels: 30,
      pickable: false,
      parameters: { depthTest: false },
    }),
    activeLayers.has("onc") && oncData && new ScatterplotLayer({
      id: "onc",
      data: filteredOncFeatures,
      getPosition: (f: any) => f.geometry.coordinates,
      getFillColor: [77, 184, 164, 200],
      getLineColor: [77, 184, 164, 255],
      stroked: true,
      lineWidthMinPixels: 2,
      getRadius: 8000,
      radiusMinPixels: 4,
      radiusMaxPixels: 16,
      pickable: true,
      autoHighlight: true,
      highlightColor: [220, 150, 255, 80],
      onClick: handleClick,
      parameters: { depthTest: false },
    }),

    // Chess — core dots (zoom-adaptive sizing)
    activeLayers.has("chess") && chessData && new ScatterplotLayer({
      id: "chess",
      data: filteredChessFeatures,
      getPosition: (f: any) => f.geometry.coordinates,
      getRadius: snappedZoom < 4 ? 30000 : snappedZoom < 6 ? 18000 : 10000,
      radiusMinPixels: snappedZoom < 4 ? 5 : 3,
      radiusMaxPixels: snappedZoom < 6 ? 14 : 18,
      getFillColor: CHESS_FILL_COLOR,
      pickable: true,
      autoHighlight: true,
      highlightColor: [255, 255, 255, 60],
      onClick: handleClick,
      updateTriggers: {
        getRadius: [snappedZoom],
      },
    }),

    // Contractor sampling stations (DeepData ANALYTICS tier — platform-derived)
    activeLayers.has("deepdata-stations") && deepdataStationsData && new ScatterplotLayer({
      id: "deepdata-stations",
      data: filteredDeepdataStations,
      getPosition: (f: any) => f.geometry.coordinates,
      getRadius: snappedZoom < 4 ? 22000 : snappedZoom < 6 ? 14000 : 8000,
      radiusMinPixels: snappedZoom < 4 ? 4 : 3,
      radiusMaxPixels: snappedZoom < 6 ? 12 : 16,
      getFillColor: (f: any) => colorForContractor(f.properties?.contractor_code),
      stroked: true,
      lineWidthMinPixels: 0.5,
      getLineColor: [10, 14, 20, 220],
      pickable: true,
      autoHighlight: true,
      highlightColor: [255, 255, 255, 80],
      onClick: handleClick,
      updateTriggers: {
        getFillColor: [Array.from(deepdataStationContractorFilters)],
        getRadius: [snappedZoom],
      },
    }),

    // Hydrophone Stations — per-source colored dots (ooi/imos/mars)
    activeLayers.has("hydrophone-stations") && hydrophoneData && new ScatterplotLayer({
      id: "hydrophone-stations",
      data: filteredHydrophoneFeatures,
      pickable: true,
      stroked: true,
      filled: true,
      radiusUnits: "pixels",
      getPosition: (f: any) => f.geometry.coordinates,
      getRadius: 6,
      lineWidthMinPixels: 1.5,
      getFillColor: (f: any) => hydrophoneSourceColor(f.properties?.source),
      getLineColor: [255, 255, 255, 220],
      autoHighlight: true,
      highlightColor: [255, 255, 255, 80],
      onClick: handleClick,
      updateTriggers: {
        getFillColor: [
          Array.from(hydrophoneSourceFilters),
          Array.from(hydrophoneStatusFilters),
          Array.from(hydrophoneDepthFilters),
        ],
      },
    }),

    // Submarine cables — EMODnet (global telecom network)
    activeLayers.has("submarine-cables") && cablesData &&
    (cableSourceFilters.size === 0 || cableSourceFilters.has("emodnet")) && new GeoJsonLayer({
      id: "submarine-cables",
      data: cablesData,
      filled: false, stroked: true,
      getLineColor: [251, 191, 36, 200],
      getLineWidth: 3, lineWidthMinPixels: 2,
      pickable: true, autoHighlight: true, highlightColor: [251, 191, 36, 80],
      onClick: handleClick,
    }),

    // Submarine cables — ONC (NE Pacific fibre-optic observatory network)
    activeLayers.has("submarine-cables") && oncCablesData &&
    (cableSourceFilters.size === 0 || cableSourceFilters.has("onc")) && new GeoJsonLayer({
      id: "onc-cables",
      data: oncCablesData,
      filled: false, stroked: true,
      getLineColor: [34, 211, 238, 220],
      getLineWidth: 3, lineWidthMinPixels: 2,
      pickable: true, autoHighlight: true, highlightColor: [34, 211, 238, 80],
      onClick: handleClick,
    }),

    // Submarine cables — OOI RCA (Oregon, approximate straight-line routes)
    activeLayers.has("submarine-cables") && ooiCablesData &&
    (cableSourceFilters.size === 0 || cableSourceFilters.has("ooi")) && new GeoJsonLayer({
      id: "ooi-cables",
      data: ooiCablesData,
      filled: false, stroked: true,
      getLineColor: [232, 121, 249, 220],
      getLineWidth: 3, lineWidthMinPixels: 2,
      pickable: true, autoHighlight: true, highlightColor: [232, 121, 249, 80],
      onClick: handleClick,
    }),

    // Submarine cables — NOAA Marine Cadastre (US corridors, polygon buffers)
    activeLayers.has("submarine-cables") && noaaCablesData &&
    (cableSourceFilters.size === 0 || cableSourceFilters.has("noaa")) && new GeoJsonLayer({
      id: "noaa-cables",
      data: noaaCablesData,
      filled: false, stroked: true,
      getLineColor: [251, 191, 36, 200],
      // Thinner than polyline cables (3/2): polygon outlines render two parallel edges;
      // 2/1 balances the visual weight against single-line cables on the same layer.
      getLineWidth: 2, lineWidthMinPixels: 1,
      // autoHighlight disabled: with 2,816 MultiPolygons + per-mousemove picking
      // it caused noticeable pan-lag. Click still works for the panel.
      pickable: true, autoHighlight: false,
      onClick: handleClick,
    }),

    // Submarine cables — NZ LINZ (Hydrographic chart-derived polylines)
    activeLayers.has("submarine-cables") && nzCablesData &&
    (cableSourceFilters.size === 0 || cableSourceFilters.has("nz")) && new GeoJsonLayer({
      id: "nz-cables",
      data: nzCablesData,
      filled: false, stroked: true,
      getLineColor: [251, 191, 36, 200],
      // Polyline widths match OOI (3/2), not NOAA's polygon-outline 2/1.
      getLineWidth: 3, lineWidthMinPixels: 2,
      // autoHighlight off (NOAA lesson — picking on dense polyline layers causes pan-lag)
      pickable: true, autoHighlight: false,
      onClick: handleClick,
    }),

    // Submarine cables — AU AODN (ACMA cable protection zones, 16 features)
    activeLayers.has("submarine-cables") && auCablesData &&
    (cableSourceFilters.size === 0 || cableSourceFilters.has("au")) && new GeoJsonLayer({
      id: "au-cables",
      data: auCablesData,
      filled: false, stroked: true,
      getLineColor: [251, 191, 36, 200],
      getLineWidth: 3, lineWidthMinPixels: 2,
      pickable: true, autoHighlight: false,
      onClick: handleClick,
    }),

    // ONC Instruments — per-device points
    activeLayers.has("onc-instruments") && oncInstrumentsData && new ScatterplotLayer({
      id: "onc-instruments",
      data: filteredOncInstrumentsFeatures,
      getPosition: (f: any) => f.geometry.coordinates,
      getFillColor: [167, 139, 250, 220],
      getLineColor: [255, 255, 255, 160],
      getRadius: 4500,
      radiusMinPixels: 3, radiusMaxPixels: 8,
      stroked: true, lineWidthMinPixels: 1,
      pickable: true, autoHighlight: true, highlightColor: [167, 139, 250, 120],
      onClick: handleClick,
    }),

    // Port locations — anchor icon
    activeLayers.has("ports") && portsData && new IconLayer({
      id: "ports",
      data: portsData.features,
      getPosition: (f: any) => f.geometry.coordinates,
      iconAtlas: "/icons/port-anchor.png",
      iconMapping: { anchor: { x: 0, y: 0, width: 64, height: 64, mask: false } },
      getIcon: () => "anchor",
      getSize: 8000,
      sizeMinPixels: 14, sizeMaxPixels: 36,
      pickable: true, autoHighlight: true, highlightColor: [96, 165, 250, 100],
      onClick: handleClick,
    }),

    // ── Land layers ─────────────────────────────────────────────────────────

    // Surface water occurrence (JRC) — raster tiles
    activeLayers.has("surface-water") && new TileLayer({
      id: "surface-water",
      data: "https://storage.googleapis.com/global-surface-water/tiles2021/occurrence/{z}/{x}/{y}.png",
      minZoom: 0,
      maxZoom: 13,
      tileSize: 256,
      opacity: 0.6,
      renderSubLayers: (props: any) => {
        const [[west, south], [east, north]] = props.tile.boundingBox;
        return new BitmapLayer(props, {
          data: undefined,
          image: props.data,
          bounds: [west, south, east, north],
        });
      },
      onTileError: () => onTileLayerError("Global Surface Water"),
      onTileLoad: () => onTileLayerLoad("Global Surface Water"),
    }),

    // Tree cover loss (UMD/GFW) — raster tiles
    activeLayers.has("forest-loss") && new TileLayer({
      id: "forest-loss",
      // ⛔ Pin the version deliberately, and check it against GFW's own
      // dataset API when touching this. v1.11 was served while v1.13 was
      // current — two annual releases behind, so the most recent years of
      // loss were simply absent. Measured 2026-09-10 on tile 5/16/14:
      // v1.11 returned 775 bytes, v1.13 returned 1,608.
      data: "https://tiles.globalforestwatch.org/umd_tree_cover_loss/v1.13/tcd_30/{z}/{x}/{y}.png",
      minZoom: 0,
      maxZoom: 12,
      tileSize: 256,
      opacity: 0.7,
      renderSubLayers: (props: any) => {
        const [[west, south], [east, north]] = props.tile.boundingBox;
        return new BitmapLayer(props, {
          data: undefined,
          image: props.data,
          bounds: [west, south, east, north],
        });
      },
      onTileError: () => onTileLayerError("Tree Cover Loss"),
      onTileLoad: () => onTileLayerLoad("Tree Cover Loss"),
    }),

    // Forest carbon net flux (GFW) — raster tiles
    activeLayers.has("carbon-flux") && new TileLayer({
      id: "carbon-flux",
      data: "https://tiles.globalforestwatch.org/gfw_forest_carbon_net_flux/v20250430/default/{z}/{x}/{y}.png",
      minZoom: 0,
      maxZoom: 12,
      tileSize: 256,
      opacity: 0.7,
      renderSubLayers: (props: any) => {
        const [[west, south], [east, north]] = props.tile.boundingBox;
        return new BitmapLayer(props, {
          data: undefined,
          image: props.data,
          bounds: [west, south, east, north],
        });
      },
      onTileError: () => onTileLayerError("Forest Carbon Flux"),
      onTileLoad: () => onTileLayerLoad("Forest Carbon Flux"),
    }),

    // Soil organic carbon (ISRIC SoilGrids WMS) — raster tiles
    activeLayers.has("soil-carbon") && new TileLayer({
      id: "soil-carbon",
      minZoom: 0,
      maxZoom: 12,
      tileSize: 256,
      opacity: 0.85,
      getTileData: (tile: any) => {
        const { west, south, east, north } = tile.bbox;
        const toMerc = (lon: number, lat: number) => {
          const x = lon * 20037508.34 / 180;
          const y = Math.log(Math.tan((90 + lat) * Math.PI / 360)) / (Math.PI / 180);
          return [x, y * 20037508.34 / 180];
        };
        const [x1, y1] = toMerc(west, south);
        const [x2, y2] = toMerc(east, north);
        const url = `https://maps.isric.org/mapserv?map=/map/soc.map&SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap&LAYERS=soc_0-5cm_mean&STYLES=default&SRS=EPSG:3857&BBOX=${x1},${y1},${x2},${y2}&WIDTH=256&HEIGHT=256&FORMAT=image/png&TRANSPARENT=true`;
        return fetch(url).then(r => {
          if (!r.ok) return null;
          const ct = r.headers.get("content-type") || "";
          if (!ct.includes("image")) return null;
          return r.blob().then(b => createImageBitmap(b));
        }).catch(() => null);
      },
      renderSubLayers: (props: any) => {
        const [[west, south], [east, north]] = props.tile.boundingBox;
        return new BitmapLayer(props, {
          data: undefined,
          image: props.data,
          bounds: [west, south, east, north],
        });
      },
      onTileError: () => onTileLayerError("Soil Organic Carbon"),
      onTileLoad: () => onTileLayerLoad("Soil Organic Carbon"),
    }),

    // Water Risk — colored MVT polygons (WRI Aqueduct 4.0) — rendered behind other polygons
    activeLayers.has("water-risk") && new MVTLayer({
      id: "water-risk-mvt",
      data: `${API}/api/v2/spatial/tiles/water_risk/{z}/{x}/{y}?v=${tileCacheVersion}`,
      minZoom: 2, maxZoom: 14, tileSize: 512,
      getFillColor: (f: any) => {
        const cat = f.properties?.w_awr_min_tot_cat;
        // WRI Aqueduct 4.0 official 5-class palette (see colorStandards.WRI_AQUEDUCT).
        if (cat === 0) return withAlpha(WRI_AQUEDUCT[0],  80);
        if (cat === 1) return withAlpha(WRI_AQUEDUCT[1],  80);
        if (cat === 2) return withAlpha(WRI_AQUEDUCT[2], 100);
        if (cat === 3) return withAlpha(WRI_AQUEDUCT[3], 120);
        if (cat === 4) return withAlpha(WRI_AQUEDUCT[4], 140);
        return withAlpha(WRI_AQUEDUCT_NO_DATA,  40);
      },
      getLineColor: (f: any) => {
        const cat = f.properties?.w_awr_min_tot_cat;
        if (cat === 0) return withAlpha(WRI_AQUEDUCT[0], 180);
        if (cat === 1) return withAlpha(WRI_AQUEDUCT[1], 180);
        if (cat === 2) return withAlpha(WRI_AQUEDUCT[2], 200);
        if (cat === 3) return withAlpha(WRI_AQUEDUCT[3], 220);
        if (cat === 4) return withAlpha(WRI_AQUEDUCT[4], 220);
        return withAlpha(WRI_AQUEDUCT_NO_DATA, 80);
      },
      getLineWidth: 1, lineWidthMinPixels: 1,
      pickable: true, autoHighlight: true, highlightColor: [14, 165, 233, 80],
      onClick: handleClick,
      onTileError: () => onTileLayerError("Water Risk (Aqueduct)"),
      onTileLoad: () => onTileLayerLoad("Water Risk (Aqueduct)"),
    }),

    // Mining footprints — memoised layer (see miningFootprintsLayer above).
    miningFootprintsLayer,

    // Key Biodiversity Areas — REMOVED 2026-09-03. BirdLife's KBA terms forbid
    // redistribution through an interactive web map without prior written
    // permission from the KBA Secretariat, plus a separate no-commercial-use
    // clause; the tile endpoint is gone from the backend.

    // WDPA Protected Areas — REMOVED 2026-09-03. Protected Planet forbids
    // redistribution through an interactive web map without prior written
    // permission from UNEP-WCMC; the tile endpoint is gone from the backend.

    // Arctic Catchments — server-rendered raster PNG tiles (TileLayer+BitmapLayer).
    // id kept as "arctic-catchments-mvt" (deliberate misnomer) so DECK_TO_TOGGLE,
    // handleClick routing, flyConfigs, and rasterViews keep working unchanged.
    activeLayers.has("arctic-catchments") && new TileLayer({
      id: "arctic-catchments-mvt",   // id kept (misnomer) — see DECK_TO_TOGGLE/handleClick/flyConfigs
      data: `${API}/api/v1/map/arctic-catchments/raster/{z}/{x}/{y}.png?variable=${arcticCatchmentsVariable}&v=${tileCacheVersion}`,
      minZoom: 0, maxZoom: 12, tileSize: 256,
      refinementStrategy: "no-overlap",
      // NON-pickable: a BitmapLayer picks its whole tile quad incl. transparent pixels, which
      // would shadow the ocean hex/dot layers beneath. Clicks are resolved at the DeckGL-level
      // onClick (empty-click → /by-point), exactly like the old vector layer over transparent areas.
      pickable: false,
      updateTriggers: { data: [arcticCatchmentsVariable, tileCacheVersion] },
      onTileError: () => onTileLayerError("Arctic Catchments"),
      onTileLoad: () => onTileLayerLoad("Arctic Catchments"),
      renderSubLayers: (props: any) => {
        const { boundingBox } = props.tile;
        return new BitmapLayer(props, {
          data: undefined,
          image: props.data,
          bounds: [boundingBox[0][0], boundingBox[0][1], boundingBox[1][0], boundingBox[1][1]],
        });
      },
    }),

    // Seabed Substrate — server-rendered raster PNG tiles (TileLayer+BitmapLayer).
    // pickable:false — same BitmapLayer whole-quad-pick gotcha as arctic-catchments.
    // Clicks resolved via the DeckGL empty-click branch + /v1/seabed/point.
    activeLayers.has("seabed-substrate") && seabedDisplayMode === "field" && new TileLayer({
      id: "seabed-substrate-raster",
      data: `${API}/api/v1/seabed/raster/{z}/{x}/{y}.png?v=${tileCacheVersion}`,
      minZoom: 0, maxZoom: 8, tileSize: 256, refinementStrategy: "no-overlap",
      pickable: false,
      updateTriggers: { data: [tileCacheVersion] },
      onTileError: () => onTileLayerError("Seabed Substrate"),
      renderSubLayers: (props: any) => new BitmapLayer(props, {
        data: undefined, image: props.data,
        bounds: [props.tile.boundingBox[0][0], props.tile.boundingBox[0][1],
                 props.tile.boundingBox[1][0], props.tile.boundingBox[1][1]],
      }),
    }),

    // Arctic Sediment Carbon (CASCADE) — server-rendered raster PNG tiles (field mode).
    // pickable:false — same BitmapLayer whole-quad-pick gotcha as seabed-substrate/arctic-catchments.
    // Clicks resolved via the DeckGL empty-click branch + /v1/cascade/point.
    activeLayers.has("arctic-sediment-carbon") && cascadeDisplayMode === "field" && new TileLayer({
      id: "arctic-sediment-carbon-raster",
      data: `${API}/api/v1/cascade/raster/{z}/{x}/{y}.png?variable=${cascadeVariable}&v=${tileCacheVersion}`,
      minZoom: 0, maxZoom: 8, tileSize: 256, refinementStrategy: "no-overlap",
      pickable: false,
      updateTriggers: { data: [cascadeVariable, tileCacheVersion] },
      onTileError: () => onTileLayerError("Arctic Sediment Carbon"),
      renderSubLayers: (props: any) => new BitmapLayer(props, {
        data: undefined, image: props.data,
        bounds: [props.tile.boundingBox[0][0], props.tile.boundingBox[0][1],
                 props.tile.boundingBox[1][0], props.tile.boundingBox[1][1]],
      }),
    }),

    // WOD Oxygen Profiles — point MVT dots coloured by decade (older=cool blue → recent=warm amber).
    activeLayers.has("wod-oxygen") && new MVTLayer({
      id: "wod-oxygen",
      data: `${API}/api/v2/spatial/tiles/wod-oxygen/{z}/{x}/{y}?v=${tileCacheVersion}`,
      tileSize: 512, maxZoom: 8,
      pointType: "circle",
      // Dot size matches the arctic-rivers layer (6px radius, min 5) — pixel
      // units so it stays constant at every zoom. Size-only change; no outline.
      getPointRadius: 6, pointRadiusUnits: "pixels", pointRadiusMinPixels: 5,
      getFillColor: (f: any) => {
        const dec = f.properties?.decade as number;
        if (wodDecadeFilters.size && !wodDecadeFilters.has(String(dec))) return [0, 0, 0, 0];
        return [...wodDecadeColor(dec), 200] as [number, number, number, number];
      },
      updateTriggers: { getFillColor: [wodDecadeFilters] },
      pickable: true, autoHighlight: true, highlightColor: [255, 255, 255, 80],
      onClick: handleClick,
      onTileError: () => onTileLayerError("WOD Oxygen Profiles"),
      onTileLoad: () => onTileLayerLoad("WOD Oxygen Profiles"),
    }),

    // MEMENTO (GEOMAR) — CH₄/N₂O research cruise casts, colour-coded by selected gas value.
    // Dots visible when mementoDisplayMode === "dots"; hexes rendered in Task 5.
    activeLayers.has("memento") && mementoDisplayMode === "dots" && new MVTLayer({
      id: "memento",
      data: `${API}/api/v2/spatial/tiles/memento/{z}/{x}/{y}?v=${tileCacheVersion}`,
      tileSize: 512, maxZoom: 8,
      pointType: "circle",
      getPointRadius: 6, pointRadiusUnits: "pixels", pointRadiusMinPixels: 5,
      getFillColor: (f: any) => {
        const dec = f.properties?.decade as number;
        const hasCh4 = !!f.properties?.has_ch4;
        const hasN2o = !!f.properties?.has_n2o;
        // Gas-presence filter: hide casts that don't carry the selected gas (or filtered gas)
        if (mementoGasFilters.size > 0) {
          const wantCh4 = mementoGasFilters.has("ch4");
          const wantN2o = mementoGasFilters.has("n2o");
          if (wantCh4 && !hasCh4 && !wantN2o) return [0, 0, 0, 0];
          if (wantN2o && !hasN2o && !wantCh4) return [0, 0, 0, 0];
        }
        // Decade filter
        if (mementoDecadeFilters.size && !mementoDecadeFilters.has(String(dec))) return [0, 0, 0, 0];
        // Colour by selected gas value: low (teal) → high (magenta)
        const v = mementoGas === "ch4" ? (f.properties?.ch4_surf as number | null) : (f.properties?.n2o_surf as number | null);
        const hasGas = mementoGas === "ch4" ? hasCh4 : hasN2o;
        // Muted grey: no *dissolved* value for this gas — either the cast never measured
        // it, or every value it carries is an atmospheric mole fraction (see the panel's
        // "air" badge). Never colour those as zero.
        if (!hasGas || v == null) return [120, 130, 140, 60];
        // Simple teal→magenta ramp — normalise per gas: CH₄ ~0–50 nM, N₂O ~5–30 nM
        const max = mementoGas === "ch4" ? 50 : 30;
        const t = Math.min(1, Math.max(0, v / max));
        const r = Math.round(45 + t * (232 - 45));   // teal[0]=45 → magenta[0]=232
        const g = Math.round(212 - t * (212 - 60));  // teal[1]=212 → magenta[1]=60
        const b = Math.round(191 - t * (191 - 249)); // teal[2]=191 → magenta[2]=249
        return [r, g, b, 200] as [number, number, number, number];
      },
      updateTriggers: { getFillColor: [mementoGas, mementoGasFilters, mementoDecadeFilters] },
      pickable: true, autoHighlight: true, highlightColor: [255, 255, 255, 80],
      onClick: handleClick,
      onTileError: () => onTileLayerError("MEMENTO (CH₄/N₂O)"),
      onTileLoad: () => onTileLayerLoad("MEMENTO (CH₄/N₂O)"),
    }),

    // MEMENTO hexes — cast-density grid shown in "hexes" display mode.
    activeLayers.has("memento") && mementoDisplayMode === "hexes" && mementoHexData && new PolygonLayer({
      id: "memento-hexes",
      data: visibleMementoHexes,
      getPolygon: (f: any) => f.geometry.coordinates[0],
      filled: true, stroked: true,
      getLineColor: [255, 255, 255, 40],
      getLineWidth: 1, lineWidthMinPixels: 0.4,
      getFillColor: (f: any) => {
        const count = hexFilteredCount(f.properties, mementoDecadeFilters);
        const t = Math.min(1, count / 100);
        const r = Math.round(45 + t * (232 - 45));
        const g = Math.round(212 - t * (212 - 60));
        const b = Math.round(191 - t * (191 - 249));
        return [r, g, b, 200] as [number, number, number, number];
      },
      updateTriggers: { getFillColor: [mementoDecadeFilters] },
      pickable: true,
      onClick: handleClick,
      autoHighlight: true,
      highlightColor: [255, 255, 255, 80],
    }),

    // GEOTRACES trace-metal stations — coloured by selected element value.
    // Dots visible when geotracesDisplayMode === "dots"; hexes rendered below.
    activeLayers.has("geotraces") && geotracesDisplayMode === "dots" && new MVTLayer({
      id: "geotraces",
      data: `${API}/api/v2/spatial/tiles/geotraces/{z}/{x}/{y}?v=${tileCacheVersion}`,
      tileSize: 512, maxZoom: 8,
      pointType: "circle",
      getPointRadius: 5, pointRadiusUnits: "pixels", pointRadiusMinPixels: 4,
      getFillColor: (f: any) => {
        const p = f.properties || {};
        const hasEl = p[`has_${geotracesElement}`];
        if (!hasEl) return [0, 0, 0, 0];
        if (geotracesDecadeFilters.size > 0 && !geotracesDecadeFilters.has(String(p.decade))) return [0, 0, 0, 0];
        return elementColor(geotracesElement as any, p[`${geotracesElement}_max`]);
      },
      updateTriggers: { getFillColor: [geotracesElement, geotracesDecadeFilters] },
      pickable: true, autoHighlight: true, highlightColor: [255, 255, 255, 80],
      onClick: handleClick,
      onTileError: () => onTileLayerError("GEOTRACES Trace Metals"),
      onTileLoad: () => onTileLayerLoad("GEOTRACES Trace Metals"),
    }),

    // GEOTRACES hexes — station-density grid shown in "hexes" display mode.
    activeLayers.has("geotraces") && geotracesDisplayMode === "hexes" && geotracesHexData && new PolygonLayer({
      id: "geotraces-hexes",
      data: visibleGeotracesHexes,
      getPolygon: (f: any) => f.geometry.coordinates[0],
      filled: true, stroked: true,
      getLineColor: [255, 255, 255, 40],
      getLineWidth: 1, lineWidthMinPixels: 0.4,
      getFillColor: (f: any) => {
        const count = hexFilteredCount(f.properties, geotracesDecadeFilters);
        const t = Math.min(1, count / 20);
        return [Math.round(70 + 130 * t), Math.round(90 + 60 * t), 200, 150] as [number, number, number, number];
      },
      updateTriggers: { getFillColor: [geotracesDecadeFilters] },
      pickable: true,
      onClick: handleClick,
      autoHighlight: true,
      highlightColor: [255, 255, 255, 80],
    }),

    // MOSAIC marine-sediment-carbon cores — coloured by selected variable value.
    // Dots visible when mosaicDisplayMode === "dots"; hexes rendered below.
    activeLayers.has("mosaic-sediment") && mosaicDisplayMode === "dots" && new MVTLayer({
      id: "mosaic-sediment",
      data: `${API}/api/v2/spatial/tiles/mosaic/{z}/{x}/{y}?v=${tileCacheVersion}`,
      tileSize: 512, maxZoom: 8,
      pointType: "circle",
      getPointRadius: 5, pointRadiusUnits: "pixels", pointRadiusMinPixels: 4,
      getFillColor: (f: any) => {
        const p = f.properties || {};
        const hasVar = p[`has_${mosaicVariable}`];
        if (!hasVar) return [0, 0, 0, 0];
        if (mosaicDecadeFilters.size > 0) {
          const key = p.decade == null ? "undated" : String(p.decade);
          if (!mosaicDecadeFilters.has(key)) return [0, 0, 0, 0];
        }
        return mosaicColor(mosaicVariable, p[`${mosaicVariable}_surf`]);
      },
      updateTriggers: { getFillColor: [mosaicVariable, mosaicDecadeFilters] },
      pickable: true, autoHighlight: true, highlightColor: [255, 255, 255, 80],
      onClick: handleClick,
      onTileError: () => onTileLayerError("Marine Sediment Carbon"),
      onTileLoad: () => onTileLayerLoad("Marine Sediment Carbon"),
    }),

    // MOSAIC hexes — core-density grid shown in "hexes" display mode.
    activeLayers.has("mosaic-sediment") && mosaicDisplayMode === "hexes" && mosaicHexData && new PolygonLayer({
      id: "mosaic-hexes",
      data: visibleMosaicHexes,
      getPolygon: (f: any) => f.geometry.coordinates[0],
      filled: true, stroked: true,
      getLineColor: [255, 255, 255, 40],
      getLineWidth: 1, lineWidthMinPixels: 0.4,
      getFillColor: (f: any) => {
        const count = hexFilteredCount(f.properties, mosaicDecadeFilters);
        const t = Math.min(1, count / 20);
        return [Math.round(70 + 130 * t), Math.round(90 + 60 * t), 200, 150] as [number, number, number, number];
      },
      updateTriggers: { getFillColor: [mosaicDecadeFilters] },
      pickable: true,
      onClick: handleClick,
      autoHighlight: true,
      highlightColor: [255, 255, 255, 80],
    }),

    // Tailings dams — red dots (show from z4+)
    activeLayers.has("tailings") && tailingsData && snappedZoom >= 4 && new ScatterplotLayer({
      id: "tailings",
      data: filteredTailingsFeatures,
      getPosition: (f: any) => f.geometry.coordinates,
      getRadius: 5000,
      getFillColor: (f: any) => {
        // hazard_raw is the operator's own rating string, verbatim. Colors are
        // DISTINCT HUES (TAILINGS_HAZARD, colorStandards.ts) — no risk ramp,
        // and no alpha ramp by severity either: every rated dam gets the same
        // opacity so darker/brighter never reads as "more dangerous".
        const risk = f.properties?.hazard_raw as string | undefined;
        if (risk && TAILINGS_HAZARD[risk]) return withAlpha(TAILINGS_HAZARD[risk], 200);
        if (risk) return withAlpha(TAILINGS_HAZARD_OTHER, 200); // rated, but outside the 6 known values
        return withAlpha(TAILINGS_UNRATED, 160); // hazard_raw is null — no rating disclosed
      },
      getLineColor: (f: any) => {
        const risk = f.properties?.hazard_raw;
        if (risk) return [255, 255, 255, 200];
        return withAlpha(TAILINGS_UNRATED, 200);
      },
      getLineWidth: 1,
      lineWidthMinPixels: 1,
      stroked: true,
      radiusMinPixels: 4, radiusMaxPixels: 12,
      pickable: true, autoHighlight: true, highlightColor: [220, 38, 38, 100],
      onClick: handleClick,
      updateTriggers: { getFillColor: [tailingsData], getLineColor: [tailingsData] },
    }),

    // Active fires — yellow→orange→red by NASA FIRMS confidence (low/nominal/high).
    activeLayers.has("fires") && firesData && snappedZoom >= 3 && new ScatterplotLayer({
      id: "fires",
      data: snappedZoom < 5
        ? filteredFiresFeatures.filter((_: any, i: number) => i % 4 === 0)
        : snappedZoom < 7
          ? filteredFiresFeatures.filter((_: any, i: number) => i % 2 === 0)
          : filteredFiresFeatures,
      getPosition: (f: any) => f.geometry.coordinates,
      getRadius: 3000,
      getFillColor: (f: any) => {
        const conf = (f.properties?.confidence as string | undefined)?.toLowerCase() ?? "";
        const c = FIRMS_CONFIDENCE[conf] ?? FIRMS_FALLBACK;
        return withAlpha(c, 210);
      },
      radiusMinPixels: 3, radiusMaxPixels: 10,
      pickable: true, autoHighlight: true, highlightColor: withAlpha(FIRMS_FALLBACK, 100),
      updateTriggers: { getFillColor: [filteredFiresFeatures] },
      onClick: handleClick,
    }),

    // Air quality stations — EPA AQI palette by latest reading (worst-pollutant rule).
    // Stations with no parseable concentrations get the EPA "no data" grey.
    activeLayers.has("air-quality") && airQualityData && snappedZoom >= 3 && new ScatterplotLayer({
      id: "air-quality",
      data: snappedZoom < 5
        ? airQualityData.features.filter((_: any, i: number) => i % 3 === 0)
        : airQualityData.features,
      getPosition: (f: any) => f.geometry.coordinates,
      getRadius: 4000,
      getFillColor: (f: any) => {
        const r = stationAqi(f.properties);
        return withAlpha(r ? r.color : AQI_NO_DATA_COLOR, 220);
      },
      radiusMinPixels: 3, radiusMaxPixels: 10,
      pickable: true, autoHighlight: true, highlightColor: [255, 255, 255, 120],
      updateTriggers: { getFillColor: [airQualityData] },
      onClick: handleClick,
    }),

    // Landslides — brown dots (show from z4+, decimated at low zoom)
    activeLayers.has("landslides") && landslidesData && snappedZoom >= 4 && new ScatterplotLayer({
      id: "landslides",
      data: snappedZoom < 6
        ? landslidesData.features.filter((_: any, i: number) => i % 3 === 0)
        : landslidesData.features,
      getPosition: (f: any) => f.geometry.coordinates,
      getRadius: 3000,
      getFillColor: [146, 64, 14, 200],
      radiusMinPixels: 3, radiusMaxPixels: 10,
      pickable: true, autoHighlight: true, highlightColor: [146, 64, 14, 100],
      onClick: handleClick,
    }),

    // Global dams — indigo dots (show from z4+)
    activeLayers.has("dams") && damsData && snappedZoom >= 4 && new ScatterplotLayer({
      id: "dams",
      data: damsData.features,
      getPosition: (f: any) => f.geometry.coordinates,
      getRadius: 4000,
      getFillColor: [94, 138, 180, 200],
      radiusMinPixels: 3, radiusMaxPixels: 10,
      pickable: true, autoHighlight: true, highlightColor: [94, 138, 180, 100],
      onClick: handleClick,
    }),

    // Arctic river stations — colored by sub-source (ArcticGRO / PANGAEA)
    activeLayers.has("arctic-rivers") && arcticRiversData && new GeoJsonLayer({
      id: "arctic-rivers",
      data: filteredArcticRiverFeatures,
      visible: activeLayers.has("arctic-rivers"),
      pickable: true,
      pointType: "circle",
      getPointRadius: 6,
      pointRadiusUnits: "pixels",
      pointRadiusMinPixels: 5,
      getFillColor: (f: any) => {
        const s: string = f.properties?.source ?? "";
        const rgb: [number, number, number] =
          s === "arcticgro" ? [56, 189, 248]
          : s === "pangaea_lena" ? [167, 139, 250]
          : [251, 191, 36];
        return [...rgb, 230] as [number, number, number, number];
      },
      getLineColor: [255, 255, 255, 200],
      getLineWidth: 1,
      lineWidthUnits: "pixels",
      updateTriggers: { getFillColor: [arcticRiverSourceFilters] },
      onClick: handleClick,
    }),

    // SIOS Svalbard datasets — colored by ISO topic
    activeLayers.has("sios-svalbard") && siosData && new GeoJsonLayer({
      id: "sios-svalbard",
      data: filteredSiosFeatures as any,
      visible: activeLayers.has("sios-svalbard"),
      pickable: true,
      pointType: "circle",
      getFillColor: (f: any) => siosTopicColor(f.properties?.iso_topic),
      getPointRadius: 6,
      pointRadiusUnits: "pixels",
      pointRadiusMinPixels: 5,
      stroked: true,
      getLineColor: [255, 255, 255, 200],
      lineWidthMinPixels: 1,
      onClick: handleClick,
    }),

    // Methane seeps — colored by primary_type via single-sourced SEAFLEA palette
    activeLayers.has("methane-seeps") && methaneSeepsData && new GeoJsonLayer({
      id: "methane-seeps",
      data: filteredMethaneSeepsFeatures as any,
      visible: activeLayers.has("methane-seeps"),
      pickable: true,
      pointType: "circle",
      getPointRadius: 5,
      pointRadiusUnits: "pixels",
      pointRadiusMinPixels: 4,
      getFillColor: (f: any) => seepTypeColorRgba(f.properties?.primary_type),
      getLineColor: [255, 255, 255, 180],
      getLineWidth: 1,
      lineWidthUnits: "pixels",
      updateTriggers: { getFillColor: [methaneSeepsFeatureTypeFilters] },
      onClick: handleClick,
    }),

    activeLayers.has("permafrost-thaw") && permafrostThawData && new GeoJsonLayer({
      id: "permafrost-thaw",
      data: filteredPermafrostThawFeatures as any,
      visible: activeLayers.has("permafrost-thaw"),
      pickable: true,
      pointType: "circle",
      getPointRadius: 5,
      pointRadiusUnits: "pixels",
      pointRadiusMinPixels: 4,
      getFillColor: (f: any) => thawCategoryColorRgba(f.properties?.feature_category),
      // Darker shade of the category colour as the outline — a white border
      // vanished against the near-white Arctic terrain, making dots hard to find.
      getLineColor: (f: any) => thawCategoryLineRgba(f.properties?.feature_category),
      getLineWidth: 1.5,
      lineWidthUnits: "pixels",
      lineWidthMinPixels: 1.5,
      updateTriggers: {
        getFillColor: [thawTypeFilters, thawCategoryFilters, permafrostSourceFilters],
        getLineColor: [thawTypeFilters, thawCategoryFilters, permafrostSourceFilters],
      },
      onClick: handleClick,
    }),

    // Arctic Sediment Carbon (CASCADE) — station dots (stations mode). Fixed teal
    // for v1 simplicity (per-variable ramp deferred; see Task 8/9 controls+panel).
    activeLayers.has("arctic-sediment-carbon") && cascadeDisplayMode === "stations" && cascadeStationsData && new GeoJsonLayer({
      id: "arctic-sediment-carbon-stations",
      data: filteredCascadeFeatures as any,
      visible: activeLayers.has("arctic-sediment-carbon"),
      pickable: true,
      pointType: "circle",
      getPointRadius: 5,
      pointRadiusUnits: "pixels",
      pointRadiusMinPixels: 4,
      getFillColor: [212, 163, 115, 200],
      getLineColor: [255, 255, 255, 180],
      getLineWidth: 1,
      lineWidthUnits: "pixels",
      updateTriggers: { data: [filteredCascadeFeatures] },
      onClick: handleClick,
    }),

    // ── Live AIS vessels (own ingest via AISStream.io) ────────────────────
    // Zoom-gated at z >= 2.5 — far enough out to see global traffic
    // patterns (shipping lanes, port clusters) but not so far that the
    // 20k-icon batch tanks frame rate on low-end laptops.
    activeLayers.has("ais-live") && !vesselFocus && (viewState.zoom as number) >= 2.5 && new IconLayer({
      id: "ais-live",
      data: filteredAisLive,
      getPosition: (d: any) => d.geometry.coordinates,
      // Ship icon (vessel-fishing.png = generic blue trawler silhouette).
      // Class-specific colors would require multi-tinted PNGs; for now the
      // class is surfaced in the detail panel on click.
      getIcon: () => ({
        url: "/icons/vessel-fishing.png",
        width: 192, height: 104, anchorY: 52, anchorX: 96,
      }),
      // Length scales icon footprint; cap so supertankers don't dominate.
      getSize: (d: any) => {
        const len = d.properties.length_m as number | null;
        return len && len > 50 ? Math.min(len * 40, 12000) : 3000;
      },
      sizeUnits: "meters",
      sizeMinPixels: 10,
      sizeMaxPixels: 32,
      // Orientation intentionally fixed — icons always point "up" regardless
      // of heading/cog. Rotated silhouettes were hard to read at low zoom.
      getAngle: 0,
      // Color modulates the icon. Keeping the class color as a tint on the
      // white-outline artwork preserves ship-type signal at glance.
      getColor: (d: any) => colorForShipClass(classifyShipType(d.properties.ship_type)),
      billboard: true,
      parameters: { depthTest: false },
      pickable: true,
      autoHighlight: true,
      onClick: (info: any) => {
        if (info.object) {
          setSelectedFeature({
            id: info.object.properties.mmsi,
            layer: "ais-live",
            properties: info.object.properties,
          });
        }
      },
      updateTriggers: {
        getColor: [aisShipTypeFilters],
      },
    }),

    // ── Vessel Events (SAR × AIS correlation) ─────────────────────────────
    activeLayers.has("vessel-events") && !vesselFocus && new IconLayer({
      id: "vessel-events",
      data: vesselEventsData?.features ?? [],
      getPosition: (d: any) => [d.properties.lon, d.properties.lat],
      getIcon: (d: any) => {
        const isDark = d.properties.classification === "dark";
        return {
          url: isDark ? "/icons/vessel-mining.png" : "/icons/vessel-fishing.png",
          width: 192, height: 104, anchorY: 52, anchorX: 96,
        };
      },
      getSize: (d: any) => d.properties.classification === "dark" ? 8000 : 6000,
      getColor: (d: any) => {
        const c = d.properties.classification;
        return c === "matched" ? [34, 197, 94, 255]        // green
             : c === "dark"    ? [239, 68, 68, 255]         // red
                               : [245, 158, 11, 255];       // amber = ambiguous
      },
      updateTriggers: { getColor: [] },
      sizeUnits: "meters",
      sizeMinPixels: 6,
      sizeMaxPixels: 44,
      billboard: true,
      parameters: { depthTest: false },
      pickable: true,
      onClick: (info: any) => {
        if (info.object) {
          setSelectedFeature({
            id: info.object.properties.event_id,
            layer: "vessel-events",
            properties: info.object.properties,
          });
        }
      },
    }),

    // ── Vessel focus: track path + clickable points (replaces live layer) ──
    vesselFocus && new GeoJsonLayer({
      id: `vessel-track-path-${vesselFocus.mmsi}`,
      data: vesselFocus.track,
      stroked: true, filled: false, pointType: "circle",
      pointRadiusMinPixels: 0, pointRadiusMaxPixels: 0,  // hide default point
      getLineColor: [34, 211, 238, 210],
      lineWidthMinPixels: 2,
      parameters: { depthTest: false },
      pickable: false,
    }),
    vesselFocus && new ScatterplotLayer({
      id: `vessel-track-points-${vesselFocus.mmsi}`,
      data: vesselFocus.track.features.filter(f => f.geometry?.type === "Point"),
      getPosition: (d: any) => d.geometry.coordinates,
      getRadius: 4,
      radiusUnits: "pixels",
      getFillColor: (d: any) => {
        const sog = d.properties?.sog_knots as number | null;
        // Speed shading: slow (loitering) = amber, fast = cyan
        if (sog == null) return [180, 180, 180, 220];
        if (sog < 1) return [251, 191, 36, 230];     // amber — stopped/loitering
        if (sog < 5) return [34, 211, 238, 220];     // cyan — slow cruise
        return [96, 165, 250, 210];                   // blue — underway
      },
      getLineColor: [255, 255, 255, 220],
      lineWidthMinPixels: 1,
      stroked: true,
      pickable: true,
      autoHighlight: true,
      parameters: { depthTest: false },
      onClick: (info: any) => {
        if (info.object) {
          setSelectedFeature({
            id: `${vesselFocus.mmsi}-${info.object.properties?.ts ?? info.index}`,
            layer: "vessel-track-point",
            properties: { ...info.object.properties, mmsi: vesselFocus.mmsi, vessel_name: vesselFocus.name },
          }, true); // shift=true: stack alongside vessel panel so focus stays live
        }
      },
    }),

    ...plumeTraces.flatMap(t => buildPlumeLayers(t.data, t.argoId, viewState.zoom as number)),

    // Animated currents render on a 2D-canvas overlay (see JSX below). Only the
    // static arrow fallback is a deck.gl layer, used when reduced-motion is on.
    ...(currentsActive && reduceMotion ? buildCurrentsArrowLayer(currentsArrows) : []),

    ...plumeHistoryQueue.flatMap(h =>
      buildPlumeHistoryLayers(h.data, h.contractorName, handlePlumeOriginClick)
    ),
  ].filter(Boolean);

  const layers = (() => {
    // Sort layersRaw by layer order from config.
    const sorted = (() => {
      if (!layerOrder.length) return layersRaw;
      const orderMap = new Map(layerOrder.map(c => [c.id, c.order_idx]));
      type RawItem = (typeof layersRaw)[number];
      return [...layersRaw].sort((a: RawItem, b: RawItem) => {
        const aid = (a as unknown as { id?: string })?.id ?? "";
        const bid = (b as unknown as { id?: string })?.id ?? "";
        const ga = DECK_TO_TOGGLE[aid] ?? aid;
        const gb = DECK_TO_TOGGLE[bid] ?? bid;
        return (orderMap.get(ga) ?? 9999) - (orderMap.get(gb) ?? 9999);
      });
    })();

    // ── AOI overlay layers (always on top) ─────────────────────────────────

    // Hex pick layer — pickable cell grid, only while hex selection is active.
    const selectedCellIds = aoiSelection?.mode === "hexes" ? aoiSelection.cellIds : [];
    const hexPickLayer = (selectionMode === "hexes" && hexGridData)
      ? new GeoJsonLayer({
          id: "aoi-hex-pick",
          data: hexGridData,
          pickable: true,
          stroked: true,
          filled: true,
          getFillColor: (f: any) =>
            selectedCellIds.includes(f.properties?.cell_id)
              ? ([125, 211, 252, 100] as [number, number, number, number])
              : ([125, 211, 252, 20] as [number, number, number, number]),
          getLineColor: [125, 211, 252, 100] as [number, number, number, number],
          getLineWidth: 1,
          lineWidthMinPixels: 1,
          updateTriggers: { getFillColor: [selectedCellIds] },
          onClick: (info: PickingInfo) => {
            const cellId = (info.object as any)?.properties?.cell_id as string | undefined;
            if (!cellId) return true;
            const current = aoiSelection?.mode === "hexes" ? aoiSelection.cellIds : [];
            setAoiSelection({ mode: "hexes", cellIds: toggleHexCell(current, cellId) });
            return true;
          },
        })
      : null;

    // Polygon vertex dots — shown while drawing.
    const polyVertLayer = (selectionMode === "polygon" && polyVerts.length >= 1)
      ? new ScatterplotLayer({
          id: "aoi-poly-verts",
          data: polyVerts,
          getPosition: (d: number[]) => d as [number, number, number],
          getRadius: 5,
          radiusUnits: "pixels" as const,
          getFillColor: [125, 211, 252, 220] as [number, number, number, number],
          pickable: false,
        })
      : null;

    // Polygon in-progress ring — preview of the ring as it forms.
    const polyRingLayer = (selectionMode === "polygon" && polyVerts.length >= 2)
      ? new PolygonLayer({
          id: "aoi-poly-preview-ring",
          data: [polyVerts],
          getPolygon: (d: number[][]) => d,
          pickable: false,
          stroked: true,
          filled: true,
          getFillColor: [125, 211, 252, 15] as [number, number, number, number],
          getLineColor: [125, 211, 252, 160] as [number, number, number, number],
          getLineWidth: 2,
          lineWidthMinPixels: 1,
        })
      : null;

    // Closed AOI preview (box or finalized polygon, committed to store).
    let ring: number[][] | null = null;
    if (aoiSelection?.mode === "box") {
      const [minLng, minLat, maxLng, maxLat] = aoiSelection.bbox;
      ring = [[minLng, minLat], [maxLng, minLat], [maxLng, maxLat], [minLng, maxLat], [minLng, minLat]];
    } else if (aoiSelection?.mode === "polygon") {
      // polygon is already number[][] — no cast needed.
      ring = aoiSelection.polygon;
    }
    const previewLayer = ring
      ? new PolygonLayer({
          id: "aoi-preview",
          data: [ring],
          getPolygon: (d: number[][]) => d,
          pickable: false,
          stroked: true,
          filled: true,
          getFillColor: [125, 211, 252, 40] as [number, number, number, number],
          getLineColor: [125, 211, 252, 200] as [number, number, number, number],
          getLineWidth: 2,
          lineWidthMinPixels: 1,
        })
      : null;

    return [
      ...sorted,
      hexPickLayer,
      polyVertLayer,
      polyRingLayer,
      previewLayer,
    ].filter(Boolean);
  })();

  // ── Render ───────────────────────────────────────────────────────────────
  return (
    <>
      {loading && (
        <div className="absolute inset-0 z-overlay flex items-center justify-center bg-surface-overlay pointer-events-none">
          <div className="flex flex-col items-center gap-3">
            <div className="w-6 h-6 border-2 border-white/20 border-t-white/80 rounded-full animate-spin" />
            <p className="text-white/65 text-xs">{t("map.loadingOceanData")}</p>
          </div>
        </div>
      )}

      {isTracing && (
        <div className="absolute bottom-8 left-1/2 -translate-x-1/2 z-panel bg-surface-overlay border border-white/20 text-white/85 text-xs px-4 py-2 rounded-lg pointer-events-none">
          {t("map.tracingPlume")}
        </div>
      )}

      {failedLayers.length > 0 && (
        <LayerUnavailableNotice
          layers={failedLayers}
          onDismiss={() => setFailedLayers([])}
          onRetry={retryFailedLayers}
        />
      )}

      {/* ⛔ Independent of failedLayers: a link naming a vanished object is a
          different failure with a different remedy, and it must be able to
          appear when every layer loaded perfectly. Bottom-LEFT so the two
          never stack on the same strip of screen. */}
      <FocusUnavailableNotice
        failures={sharePanelFailures}
        onDismiss={clearSharePanelFailures}
      />

      <div
        id="map-canvas"
        role="application"
        aria-label={t("map.ariaLabel")}
        style={{ position: "absolute", inset: 0 }}
        onContextMenu={e => e.preventDefault()}
      >
        <DeckGL
          views={MAP_VIEW}
          viewState={viewState as unknown as MapViewState}
          onViewStateChange={onViewStateChange}
          controller={{ dragRotate: true, touchRotate: true, touchZoom: true, keyboard: true, dragPan: selectionMode !== "box", doubleClickZoom: selectionMode !== "polygon" }}
          layers={layers}
          pickingRadius={8}
          onHover={info => {
            // Prefetch GEBCO seafloor depth at the cursor when bathymetry is on.
            // Filled cache means getTooltip's next call can include the depth
            // inline. No-op when bathymetry layer is off.
            if (!activeLayers.has("bathymetry")) return;
            if (!info?.coordinate) return;
            const [lon, lat] = info.coordinate;
            void prefetchDepth(lat, lon, API);
          }}
          onDragStart={(info) => {
            if (useMapStore.getState().selectionMode !== "box") return;
            if (info.coordinate) dragStart.current = info.coordinate as [number, number];
          }}
          onDrag={(info) => {
            if (useMapStore.getState().selectionMode !== "box") return;
            if (dragStart.current && info.coordinate) {
              setAoiSelection({ mode: "box", bbox: bboxFromDrag(dragStart.current, info.coordinate as [number, number]) });
            }
          }}
          onDragEnd={(info) => {
            if (useMapStore.getState().selectionMode !== "box") { dragStart.current = null; return; }
            if (dragStart.current && info.coordinate) {
              setAoiSelection({ mode: "box", bbox: bboxFromDrag(dragStart.current, info.coordinate as [number, number]) });
              setSelectionMode(null);
            }
            dragStart.current = null;
          }}
          onClick={info => {
            bumpMapTap();
            // Polygon draw: each click adds a vertex; rapid double-click closes ring.
            if (useMapStore.getState().selectionMode === "polygon" && info.coordinate) {
              const now = Date.now();
              if (now - lastPolyClickRef.current < 350 && polyVertsRef.current.length >= 3) {
                // Second click within 350 ms = double-click → close the polygon.
                setAoiSelection({
                  mode: "polygon",
                  polygon: closePolygon(polyVertsRef.current),
                });
                setPolyVerts([]);
                setSelectionMode(null);
                lastPolyClickRef.current = 0;
              } else {
                setPolyVerts(v => [...v, info.coordinate as [number, number]]);
                lastPolyClickRef.current = now;
              }
              return;
            }
            // Drawing mode active — suppress empty-click inspect paths too.
            if (useMapStore.getState().selectionMode) return;
            // Always clear any prior depth pin — keeps it ephemeral.
            setBathymetryClickPin(null);
            if (info.layer || info.object) return; // some pickable layer handled it
            // Empty-map click always dismisses any open detail panel.
            setSelectedFeature(null);
            // Raster arctic-catchments is non-pickable; resolve its clicks HERE (only on empty
            // clicks, so we never shadow hex/dot/claim picks). Over bare arctic land info.coordinate
            // is still set; a /by-point miss (open ocean) just leaves the panel closed.
            if (activeLayers.has("arctic-catchments") && info.coordinate) {
              const [lng, lat] = info.coordinate;
              fetch(`${API}/api/v1/map/arctic-catchments/by-point?lat=${lat}&lon=${lng}`)
                .then(r => r.ok ? r.json() : null)
                .then(row => { if (row) setSelectedFeature({ id: String(row.gid ?? `${lat},${lng}`), layer: "arctic-catchments", properties: row }); })
                .catch(() => {});
            }
            if (activeLayers.has("seabed-substrate") && seabedDisplayMode === "field" && info.coordinate) {
              const [lng, lat] = info.coordinate;
              fetch(`${API}/api/v1/seabed/point?lat=${lat}&lon=${lng}`)
                .then((r) => (r.ok ? r.json() : null))
                .then((row) => { if (row && row.class_code != null)
                  setSelectedFeature({ id: `seabed:${lat.toFixed(3)},${lng.toFixed(3)}`,
                                       layer: "seabed-substrate", properties: row }); })
                .catch(() => {});
            }
            if (activeLayers.has("arctic-sediment-carbon") && cascadeDisplayMode === "field" && info.coordinate) {
              const [lng, lat] = info.coordinate;
              fetch(`${API}/api/v1/cascade/point?lat=${lat}&lon=${lng}&variable=${cascadeVariable}`)
                .then(r => r.ok ? r.json() : null)
                .then(row => { if (row && row.value != null)
                  setSelectedFeature({ id: `cascade:${lat.toFixed(3)},${lng.toFixed(3)}`,
                    layer: "arctic-sediment-carbon", properties: row }); })
                .catch(() => {});
            }
            // Cumulative Human Impact field is a non-pickable BitmapLayer; resolve field
            // clicks here (empty branch) via /v1/chi/point, then open the CHI panel.
            if (activeLayers.has("cumulative-human-impact") && chiDisplayMode === "field" && info.coordinate) {
              const [lng, lat] = info.coordinate;
              setSelectedFeature({
                id: `cumulative-human-impact:${lat.toFixed(3)},${lng.toFixed(3)}`,
                layer: "cumulative-human-impact",
                properties: { _lat: lat, _lon: lng },
              });
            }
            // With bathymetry on, also show the ephemeral depth popup.
            if (activeLayers.has("bathymetry") && info.coordinate && typeof info.x === "number") {
              const [lon, lat] = info.coordinate;
              void prefetchDepth(lat, lon, API);
              setBathymetryClickPin({ lat, lon, x: info.x, y: info.y });
            }
          }}
          getTooltip={(info: any) => {
            const layerId = info?.layer?.id as string | undefined;
            const p = info?.object?.properties;
            const bathyOn = activeLayers.has("bathymetry");
            // When bathymetry is on AND user hovers a feature, append the
            // seafloor depth (from the prefetch cache) to whatever the
            // feature-specific tooltip would otherwise show.
            const depthLine = bathyOn && info?.coordinate
              ? depthLineFromCache(info.coordinate[1], info.coordinate[0])
              : null;
            if (!layerId || !p) {
              return null;
            }

            if (layerId === "deepdata-stations") {
              const code = p.contractor_code ?? "Unparsed";
              const proto = p.sampling_protocol;
              const loc = p.location_id;
              const dMin = p.depth_m_min, dMax = p.depth_m_max;
              const depth = (dMin != null && dMax != null && dMin !== dMax)
                ? `${Math.round(dMin)}–${Math.round(dMax)} m`
                : (dMin != null ? `${Math.round(dMin)} m` : null);
              const occ = p.occurrence_count;
              const sp  = p.species_count;
              const lines = [
                `<b>${code}</b>${proto ? ` · ${proto}` : ""}`,
                loc ? `<span style="color:#94a3b8">${loc}</span>` : null,
                depth,
                [
                  occ != null ? `${occ.toLocaleString()} occurrences` : null,
                  sp  != null ? `${sp} species` : null,
                ].filter(Boolean).join(" · ") || null,
                depthLine,
              ].filter(Boolean);
              return { html: lines.join("<br/>"), style: tooltipStyle };
            }

            if (layerId === "arctic-rivers") {
              const nm = p.river_name ?? p.site_label ?? p.station_id;
              const srcLabel = p.source === "arcticgro"
                ? "ArcticGRO"
                : p.source === "pangaea_caa" ? "PANGAEA (Canadian Arctic)" : null;
              const lines = [
                nm ? `<b>${String(nm)}</b>` : null,
                srcLabel ? `<span style="color:#94a3b8">${srcLabel}</span>` : null,
                depthLine,
              ].filter(Boolean);
              return lines.length ? { html: lines.join("<br/>"), style: tooltipStyle } : null;
            }

            if (layerId === "ais-live") {
              const name     = p.name ?? (p.mmsi ? `MMSI ${p.mmsi}` : "Unknown vessel");
              const cls      = classifyShipType(p.ship_type);
              const speed    = p.sog_knots != null ? `${Number(p.sog_knots).toFixed(1)} kn` : null;
              const lenStr   = p.length_m ? `${p.length_m} m` : null;
              const flag     = p.flag ?? null;
              const dest     = p.destination ?? null;
              const lines = [
                `<b>${name}</b>`,
                [cls, flag, lenStr].filter(Boolean).join(" · "),
                speed ? `Speed: ${speed}` : null,
                dest ? `→ ${dest}` : null,
              ].filter(Boolean);
              return { html: lines.join("<br/>"), style: tooltipStyle };
            }

            if (layerId === "vessel-events") {
              const cls   = String(p.classification ?? "ambiguous");
              const label = cls === "dark" ? "Dark vessel (SAR, no AIS)"
                          : p.vessel_name ?? (p.matched_mmsi ? `MMSI ${p.matched_mmsi}` : "Vessel event");
              const inside = p.inside_polygon_name ?? p.inside_polygon_type;
              const lines = [
                `<b>${label}</b>`,
                `Class: ${cls}`,
                inside ? `Inside: ${inside}` : null,
              ].filter(Boolean);
              return { html: lines.join("<br/>"), style: tooltipStyle };
            }

            // Generic fallback: show the hovered feature's name (plus the GEBCO
            // seafloor depth when bathymetry is on). Previously a tooltip only
            // appeared with bathymetry enabled, so hovering a vent/station/etc.
            // showed nothing — you couldn't see a feature's name without clicking.
            // river_name/site_label added so any future name-bearing layer beats
            // a raw slug id.
            const name = (p.name ?? p.platform_id ?? p.river_name ?? p.site_label ?? p.station_id ?? p.isa_id ?? p.peak_id ?? p.site_id);
            if (name || depthLine) {
              return {
                html: [name ? `<b>${String(name)}</b>` : null, depthLine]
                  .filter(Boolean).join("<br/>"),
                style: tooltipStyle,
              };
            }

            return null;
          }}
          useDevicePixels={Math.min(window.devicePixelRatio ?? 1, 1.5)}
          style={{ touchAction: "none" }}
        >
          <ReactMap ref={mapRef} mapStyle={BASEMAP} renderWorldCopies={true} antialias={false} />
        </DeckGL>

        {/* Animated ocean-current particles (2D canvas overlay, CPU-advected). */}
        <CurrentsParticleCanvas
          field={currentsField}
          viewState={viewState as unknown as { longitude: number; latitude: number; zoom: number; pitch?: number; bearing?: number }}
          active={currentsActive && !reduceMotion}
          playing={currentsPlaying}
        />

        {bathymetryClickPin && (
          <BathymetryClickPopup
            pin={bathymetryClickPin}
            onClose={() => setBathymetryClickPin(null)}
          />
        )}
      </div>

      <SearchBar dataRef={searchDataRef} dataVersion={searchDataVersion} />

      <Map3DControls
        claimsData={claimsData}
        currentsMeta={currentsMeta}
        currentsDate={currentsDate}
        setCurrentsDate={setCurrentsDate}
        currentsPlaying={currentsPlaying}
        setCurrentsPlaying={setCurrentsPlaying}
        woaMeta={woaMeta}
        oxygenMeta={oxygenMeta}
        carbonMeta={carbonMeta}
        co2Meta={co2Meta}
      />

      <DetailPanel />

      <ExportToolbar />

      {/* Legend button — top-right (desktop), top-LEFT (mobile, right of the
          ⋯ site-menu button which owns left-4). Mobile top row holds ⋯ +
          Reference (left) and Discover (right); the bottom row is reserved for
          the two primary actions (Layers + Search). */}
      <button
        data-tutorial="legend-btn"
        onClick={() => setLegendOpen(v => !v)}
        className="fixed sm:absolute top-4 left-16 sm:left-auto sm:right-4 z-panel bg-[rgba(10,14,20,0.92)] border border-white/[0.12] text-white/80 hover:text-white text-xs font-mono uppercase tracking-wider px-3 py-2 min-h-[44px] rounded transition-colors"
        title={t("tooltips.dataReference")}
      >
        {t("map.referenceButton")}
      </button>
      {legendOpen && <LegendPanel onClose={() => setLegendOpen(false)} />}

      {/* Raster layer color legends — appear when layer is active */}
      {(() => {
        const rasterLegends: { id: LayerId; label: string; source: string; stops: [string, string][] }[] = [
          { id: "surface-water", label: "Surface Water Occurrence", source: "JRC 1984–2021",
            stops: [["#ffffcc", "Rare"], ["#41b6c4", "Seasonal"], ["#0c2c84", "Permanent"]] },
          { id: "forest-loss", label: "Tree Cover Loss", source: "UMD / GFW",
            stops: [["#ffeda0", "Minor loss"], ["#f03b20", "Moderate"], ["#bd0026", "Severe"]] },
          { id: "carbon-flux", label: "Forest Carbon Flux", source: "GFW",
            stops: [["#d73027", "Net source"], ["#ffffbf", "Neutral"], ["#1a9850", "Net sink"]] },
          { id: "soil-carbon", label: "Soil Organic Carbon", source: "ISRIC SoilGrids",
            stops: [["#ffffd4", "Low (g/kg)"], ["#fe9929", "Medium"], ["#8c2d04", "High"]] },
        ];
        const active = rasterLegends.filter(l => activeLayers.has(l.id));
        if (!active.length) return null;
        return (
          <div className="absolute bottom-40 right-4 z-panel flex flex-col gap-2 pointer-events-auto">
            {active.map(l => (
              <div key={l.id} className="bg-surface-overlay border border-white/10 rounded-lg px-3 py-2.5 min-w-[160px] backdrop-blur-sm">
                <div className="text-white/95 text-xs font-medium mb-1">{l.label}</div>
                <div
                  className="h-2.5 rounded-sm mb-1.5"
                  style={{ background: `linear-gradient(to right, ${l.stops.map(s => s[0]).join(", ")})` }}
                />
                <div className="flex justify-between text-[9px] text-white/70">
                  {l.stops.map((s, i) => <span key={i}>{s[1]}</span>)}
                </div>
                <div className="text-[8px] text-white/60 mt-1">{l.source}</div>
              </div>
            ))}
          </div>
        );
      })()}

      {/* Zoom controls — always visible, works on mobile */}
      <div className="absolute bottom-24 right-4 z-panel flex flex-col gap-1.5">
        <button
          onClick={() => setViewState({
            ...viewStateRef.current,
            zoom: Math.min((viewStateRef.current.zoom as number) + 1, 18),
            transitionDuration: 300,
            transitionInterpolator: new FlyToInterpolator(),
          })}
          className="w-11 h-11 bg-surface-overlay border border-white/15 text-white/80 hover:text-white hover:bg-surface-primary rounded-lg text-lg leading-none flex items-center justify-center transition-colors select-none"
          aria-label={t("tooltips.zoomIn")}
        >+</button>
        <button
          onClick={() => setViewState({
            ...viewStateRef.current,
            zoom: Math.max((viewStateRef.current.zoom as number) - 1, 2),
            transitionDuration: 300,
            transitionInterpolator: new FlyToInterpolator(),
          })}
          className="w-11 h-11 bg-surface-overlay border border-white/15 text-white/80 hover:text-white hover:bg-surface-primary rounded-lg text-lg leading-none flex items-center justify-center transition-colors select-none"
          aria-label={t("tooltips.zoomOut")}
        >−</button>
      </div>

      {/* Discovery presets — bottom right, above zoom indicator */}
      <DiscoveryPanel onFlyTo={discoveryFlyTo} />

      {/* Mission-control status strip (UTC clock, sync age, layer count, zoom) */}
      <StatusStrip zoom={viewState.zoom as number} degraded={failedLayers.length > 0} />
    </>
  );
}
