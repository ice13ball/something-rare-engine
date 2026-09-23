// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useState, useEffect, useRef } from "react";
import { useTranslation, Trans } from "react-i18next";
import { analytics } from "../utils/analytics";
import { WOD_DECADE_HEX } from "../utils/wodDecades";
import { useMapStore } from "../store/mapStore";
import type { LayerId } from "../types/layers";
import type { AssertComplete, LayerIdOf } from "../types/layerRegistry";
import { TemporalFrame } from "./panels/shared/TemporalFrame";
import { useTemporalCoverage } from "../utils/useTemporalCoverage";

const API = import.meta.env.VITE_API_BASE_URL ?? "";

// ── Tab IDs ───────────────────────────────────────────────────────────────────
const TAB_IDS = ["layers", "inventory", "howto", "alarms", "dates", "verify"] as const;
type TabId = typeof TAB_IDS[number];

// ── Inventory types ───────────────────────────────────────────────────────────
interface InventoryItem {
  key: string;
  label: string;
  table: string;
  count: number;
  source_org: string;
  source_url: string;
  last_synced_at: string | null;
}

interface InventoryGroup {
  id: string;
  label: string;
  items: InventoryItem[];
}

interface InventoryResponse {
  generated_at: string;
  total_objects: number;
  total_layers: number;
  groups: InventoryGroup[];
}

/** Format an integer for display: 26_738_644 → "26.7M". */
function formatCount(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(n >= 10_000_000 ? 1 : 2).replace(/\.?0+$/, "") + "M";
  if (n >= 1_000)     return (n / 1_000).toFixed(n >= 10_000 ? 0 : 1).replace(/\.0$/, "") + "K";
  return n.toLocaleString();
}

/** Format an ISO timestamp as "YYYY-MM-DD" or "—". */
function formatSyncDate(iso: string | null): string {
  if (!iso) return "—";
  return iso.slice(0, 10);
}

// ── Structural layer data (visual / key fields only) ─────────────────────────
// Content fields (label, source, description, reading, limitations, colorStandard,
// selectionCriteria, updateFreq, colorRamp[].label) live in legend.json.

interface LayerStruct {
  id: string;
  /** Toggle id for enablement gating — filters this entry out of the legend
   *  when the layer is globally disabled (enabledLayerIds). Optional: entries
   *  with no real toggle (e.g. "area-export") always render. */
  layerId?: LayerId;
  color: string;
  symbol: "polygon" | "dot" | "triangle" | "column" | "line" | "ring" | "square" | "anchor" | "ship";
  syncKey?: string;
  /** Hex values for the color ramp — matched positionally with colorRamp[i].label in JSON. */
  colorRampHex?: string[];
}

const LAYER_STRUCT = [
  { id: "miningConcessions",   layerId: "contracts",           color: "#00f2ff", symbol: "polygon", syncKey: "mining_contracts" },
  { id: "relinquishedAreas",   layerId: "relinquished-areas",   color: "#ff4466", symbol: "polygon", syncKey: "relinquished_areas" },
  { id: "reservedAreas",       layerId: "reserved-areas",       color: "#00ff9f", symbol: "polygon", syncKey: "reserved_areas" },
  { id: "apeis",               layerId: "apeis",                color: "#bf5fff", symbol: "polygon", syncKey: "apeis" },
  { id: "obisSpecies",         layerId: "biodiversity-hotspots",color: "#3ce664", symbol: "dot",     syncKey: "biodiversity_hotspots" },
  { id: "seamounts",           layerId: "seamounts",            color: "#7eb8f7", symbol: "column",  syncKey: "seamounts" },
  { id: "argoFloats",          layerId: "argo",                 color: "#00e5ff", symbol: "column",  syncKey: "argo_profiles" },
  { id: "hydrothermalVents",   layerId: "hydrothermal-vents",   color: "#ff2323", symbol: "triangle",syncKey: "hydrothermal_vents" },
  { id: "eezBoundaries",       layerId: "eez",                  color: "#ffd700", symbol: "line",    syncKey: "eez" },
  { id: "unescoMarineHeritage",layerId: "protected-marine-sites",color: "#00e676", symbol: "polygon", syncKey: "protected_marine_sites" },
  { id: "noiseRiskGrid",       layerId: "noise-risk",           color: "#ff6b00", symbol: "dot",     syncKey: "noise_risk" },
  { id: "oceansitesMoorings",  layerId: "oceansites",           color: "#00dcff", symbol: "ring",    syncKey: "oceansites-obs" },
  { id: "oceanCurrents",       layerId: "ocean-currents",       color: "#5eead4", symbol: "line",    syncKey: "currents-surface" },
  { id: "oncObservatories",    layerId: "onc",                  color: "#4db8a4", symbol: "dot",     syncKey: "onc-sensors" },
  // NOTE: key "chemosynthenticSites" has a typo but is consistent in legend.json
  { id: "chemosynthenticSites",layerId: "chess",                color: "#00c896", symbol: "dot",     syncKey: "chess" },
  { id: "contractorStations",  layerId: "deepdata-stations",    color: "#f472b6", symbol: "dot",     syncKey: "deepdata-stations" },
  { id: "submarineCables",     layerId: "submarine-cables",     color: "#fbbf24", symbol: "line",    syncKey: "submarine_cables" },
  { id: "oncInstruments",      layerId: "onc-instruments",      color: "#a78bfa", symbol: "dot",     syncKey: "onc_instruments" },
  { id: "portLocations",       layerId: "ports",                color: "#60a5fa", symbol: "anchor",  syncKey: "port_locations" },
  { id: "tectonicPlates",      layerId: "tectonic-plates",      color: "#c9956e", symbol: "polygon" },
  { id: "bathymetry",          layerId: "bathymetry",           color: "#3b82a6", symbol: "polygon" },
  {
    id: "monitoringDensity",
    layerId: "monitoring-density",
    color: "#ff7a00",
    symbol: "polygon",
    colorRampHex: ["#f0f0d2", "#e1c86e", "#e68c32", "#c82d23", "#8c1414"],
  },
  { id: "miningFootprints",    layerId: "mining-footprints",    color: "#dc267f", symbol: "polygon", syncKey: "mining_footprints" },
  { id: "tailingsDams",        layerId: "tailings",             color: "#9d0208", symbol: "dot",     syncKey: "tailings_dams" },
  { id: "activeFires",         layerId: "fires",                color: "#c1121f", symbol: "dot",     syncKey: "active_fires" },
  { id: "airQualityStations",  layerId: "air-quality",          color: "#ffff00", symbol: "dot",     syncKey: "air_quality" },
  { id: "landslideCatalog",    layerId: "landslides",           color: "#92400e", symbol: "dot",     syncKey: "landslides" },
  { id: "globalDams",          layerId: "dams",                 color: "#5e8ab4", symbol: "dot",     syncKey: "dams" },
  { id: "globalSurfaceWater",  layerId: "surface-water",        color: "#06b6d4", symbol: "polygon" },
  { id: "treeCoverLoss",       layerId: "forest-loss",          color: "#f59e0b", symbol: "polygon" },
  { id: "forestCarbonFlux",    layerId: "carbon-flux",          color: "#065f46", symbol: "polygon" },
  { id: "soilOrganicCarbon",   layerId: "soil-carbon",          color: "#78350f", symbol: "polygon" },
  { id: "waterRisk",           layerId: "water-risk",           color: "#0ea5e9", symbol: "polygon", syncKey: "water_risk" },
  { id: "offshoreActivities",  layerId: "offshore-activities",  color: "#dc2626", symbol: "polygon", syncKey: "offshore_activities" },
  { id: "hydrophone-stations",  layerId: "hydrophone-stations", color: "#22d3ee", symbol: "dot",     syncKey: "acoustic-stations" },
  { id: "marhys",               layerId: "marhys",              color: "#fb923c", symbol: "dot",     syncKey: "marhys" },
  { id: "woa-climatology",      layerId: "woa-climatology",     color: "#50aac8", symbol: "polygon" },
  { id: "wod-oxygen",           layerId: "wod-oxygen",           color: "#0891b2", symbol: "dot",     syncKey: "wod-oxygen",
    colorRampHex: WOD_DECADE_HEX,
  },
  {
    id: "oxygen-deox",
    layerId: "oxygen-deox",
    color: "#3b82f6",
    symbol: "polygon",
    colorRampHex: ["#67000d", "#ef3b2c", "#fc9272", "#f7f7f7", "#9ecae1", "#2171b5", "#084594"],
  },
  {
    id: "arctic-rivers",
    layerId: "arctic-rivers",
    symbol: "dot",
    syncKey: "arctic-rivers",
    color: "#38bdf8",
    colorRampHex: ["#38bdf8", "#a78bfa", "#fbbf24"],
  },
  { id: "memento", layerId: "memento", color: "#2dd4bf", symbol: "dot", syncKey: "memento" },
  { id: "geotraces", layerId: "geotraces", color: "#f97316", symbol: "dot", syncKey: "geotraces" },
  { id: "mosaic-sediment", layerId: "mosaic-sediment", color: "#c084fc", symbol: "dot", syncKey: "mosaic" },
  { id: "methane-seeps", layerId: "methane-seeps", symbol: "dot", syncKey: "seaflea", color: "#ef4444",
    colorRampHex: ["#ef4444", "#22d3ee", "#fbbf24", "#60a5fa", "#34d399", "#a78bfa"] },
  { id: "permafrost-thaw", layerId: "permafrost-thaw", symbol: "dot", syncKey: "permafrost-thaw", color: "#38bdf8",
    colorRampHex: ["#38bdf8", "#f97316", "#ef4444", "#a78bfa", "#fbbf24", "#34d399", "#e879f9", "#22d3ee", "#94a3b8"] },
  { id: "ocean-carbon", layerId: "ocean-carbon", color: "#38b2ac", symbol: "square", syncKey: "glodap-carbon" },
  { id: "ocean-co2-surface", layerId: "ocean-co2-surface", color: "#06b6d4", symbol: "square", syncKey: "socat-co2" },
  { id: "sios-svalbard", layerId: "sios-svalbard", color: "#7dd3fc", symbol: "dot", syncKey: "sios" },
  { id: "arctic-catchments", layerId: "arctic-catchments", color: "#7dd3fc", symbol: "polygon", syncKey: "arcade" },
  { id: "marine-carbon", layerId: "marine-carbon", color: "#6ee7b7", symbol: "polygon", syncKey: "glodap-carbon" },
  // Viridis — MUST stay in sync with VME_RAMP in Map3D.tsx and the swatch block
  // in Map3DControls.tsx. One scale, three render sites.
  {
    id: "vme-suitability",
    layerId: "vme-suitability",
    color: "#21918c",
    symbol: "polygon",
    syncKey: "vme-sdm",
    colorRampHex: ["#440154", "#3b528b", "#21918c", "#5ec962", "#fde725"],
  },
  // No corresponding toggle id — "area-export" is the export tool, not a map layer.
  { id: "area-export",   color: "#94a3b8", symbol: "square" },
  { id: "seabed-substrate", layerId: "seabed-substrate", color: "#9a6b3a", symbol: "polygon", syncKey: "seabed" },
  { id: "arctic-sediment-carbon", layerId: "arctic-sediment-carbon", color: "#d4a373", symbol: "dot", syncKey: "cascade" },
  // Diverging RdBu — MUST stay in sync with _RAMPS["div_acid"] in backend
  // services/acidification.py and the tooltip swatch block in Map3DControls.tsx.
  { id: "ocean-acidification", layerId: "ocean-acidification", color: "#2166ac", symbol: "polygon", syncKey: "acidification",
    colorRampHex: ["#b2182b", "#f7f7f7", "#2166ac"] },
  // MUST stay in sync with STATE_COLORS in backend/services/coral_acid_exposure.py
  // and the swatch block in Map3DControls.tsx — one scale, three render sites.
  { id: "coral-acid-exposure", layerId: "coral-acid-exposure", color: "#be1e5a", symbol: "polygon",
    syncKey: "coral-acid-exposure",
    colorRampHex: ["#be1e5a", "#8c5a96", "#3c8caf", "#94a3b8"] },
  // Sequential seq_chi ramp — MUST stay in sync with _RAMPS["seq_chi"] in backend/services/chi_impact.py.
  { id: "cumulative-human-impact", layerId: "cumulative-human-impact", color: "#f0be5a", symbol: "polygon",
    syncKey: "chi",
    colorRampHex: ["#214e64", "#4ea0a0", "#f0be5a", "#961c1c"] },
  { id: "ais-live",      layerId: "ais-live",      color: "#22d3ee", symbol: "dot", syncKey: "ais_aois" },
  { id: "vessel-events", layerId: "vessel-events", color: "#f59e0b", symbol: "dot", syncKey: "vessel_events" },
] as const satisfies readonly LayerStruct[];

// One entry ("area-export") omits the `layerId` key entirely, so a plain
// indexed access — (typeof LAYER_STRUCT)[number]["layerId"] — doesn't compile;
// LayerIdOf distributes over the union instead. See its docstring.
type LegendCovered = LayerIdOf<(typeof LAYER_STRUCT)[number]>;

// LAYER_STRUCT covers all 57 layers today. Nothing is opted out: a layer with
// no legend entry is undocumented in the Reference tab, which is never correct.
export const _legendIsComplete: AssertComplete<LegendCovered, never> = true;

// `as const satisfies` keeps LAYER_STRUCT's per-entry literal type (needed above
// for LegendCovered) rather than widening every entry to LayerStruct — so a
// union access like `s.layerId` fails on the one entry ("area-export") that
// omits the key entirely. Render code below wants the widened interface shape
// instead; this alias is that view.
const LEGEND_ENTRIES: readonly LayerStruct[] = LAYER_STRUCT;

// ── Symbol renderer ───────────────────────────────────────────────────────────
function LayerSymbol({ doc }: { doc: LayerStruct }) {
  const col = doc.color;
  if (doc.symbol === "triangle") {
    return (
      <svg aria-hidden="true" width="18" height="20" viewBox="0 0 18 20" className="flex-shrink-0">
        {/* glow base */}
        <ellipse cx="9" cy="19" rx="8" ry="2" fill={col} opacity="0.25" />
        {/* main triangle */}
        <polygon points="9,2 17,18 1,18" fill={col} opacity="0.88" />
        {/* inner highlight */}
        <polygon points="9,6 15,16 3,16" fill="#ff9944" opacity="0.38" />
        {/* plume dot */}
        <circle cx="9" cy="1" r="1.5" fill="#ffdd44" opacity="0.85" />
      </svg>
    );
  }
  if (doc.symbol === "column") {
    return (
      <svg aria-hidden="true" width="18" height="20" viewBox="0 0 18 20" className="flex-shrink-0">
        {/* shadow */}
        <ellipse cx="9" cy="19" rx="5" ry="1.5" fill={col} opacity="0.2" />
        {/* column body */}
        <rect x="5" y="5" width="8" height="14" rx="1.5" fill={col} opacity="0.75" />
        {/* top face highlight */}
        <rect x="5" y="5" width="8" height="3" rx="1.5" fill={col} opacity="0.95" />
      </svg>
    );
  }
  if (doc.symbol === "line") {
    return (
      <svg aria-hidden="true" width="18" height="14" viewBox="0 0 18 14" className="flex-shrink-0">
        <rect x="0" y="5" width="18" height="4" rx="1" fill={col} opacity="0.25" />
        <line x1="0" y1="7" x2="18" y2="7" stroke={col} strokeWidth="2" strokeDasharray="4 2" />
      </svg>
    );
  }
  if (doc.symbol === "polygon") {
    return (
      <div
        className="flex-shrink-0 w-4 h-4 rounded-sm border-2"
        style={{ background: col + "30", borderColor: col }}
      />
    );
  }
  if (doc.symbol === "ring") {
    return (
      <div
        className="flex-shrink-0 w-4 h-4 rounded-full border-2"
        style={{ background: "transparent", borderColor: col, boxShadow: `0 0 4px ${col}80` }}
      />
    );
  }
  if (doc.symbol === "anchor") {
    return <span className="flex-shrink-0 text-sm leading-none" style={{ color: col }}>⚓</span>;
  }
  if (doc.symbol === "ship") {
    return (
      <svg aria-hidden="true" width="20" height="14" viewBox="0 0 20 14" className="flex-shrink-0">
        {/* hull */}
        <path d="M1 8 L3 11 H17 L19 8 Z" fill={col} opacity="0.9" />
        {/* deckhouse */}
        <rect x="7" y="4" width="6" height="4" fill={col} opacity="0.95" />
        {/* mast */}
        <line x1="10" y1="1" x2="10" y2="4" stroke={col} strokeWidth="1.2" />
      </svg>
    );
  }
  if (doc.symbol === "square") {
    return (
      <div
        className="flex-shrink-0 w-3 h-3 border-2 rotate-45"
        style={{ background: col + "50", borderColor: col }}
      />
    );
  }
  return (
    <div
      className="flex-shrink-0 w-3 h-3 rounded-full border-2 flex-shrink-0"
      style={{ background: col + "60", borderColor: col }}
    />
  );
}

// ── Main component ────────────────────────────────────────────────────────────
export function LegendPanel({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation("legend");
  const [active, setActive] = useState<TabId>("layers");
  const ref = useRef<HTMLDivElement>(null);
  const [syncDates, setSyncDates] = useState<Record<string, string>>({});
  // WHEN the data is from — a different question from syncDates above, which is
  // when we last fetched it. Both are shown, never merged. Shared with every popup
  // through one cached fetch.
  const coverage = useTemporalCoverage();
  const [inventory, setInventory] = useState<InventoryResponse | null>(null);
  const [inventoryError, setInventoryError] = useState(false);
  const legendFocusLayer = useMapStore(s => s.legendFocusLayer);
  const clearLegendFocus = useMapStore(s => s.clearLegendFocus);
  const enabledLayerIds = useMapStore((s) => s.enabledLayerIds);

  /**
   * Is this layer still served? The Reference tab has always gated on
   * `enabledLayerIds` because it maps over LAYER_STRUCT, so retiring a layer
   * server-side emptied it there for free. The Dates and Verify tabs are
   * hand-written lists with no registry behind them, so they kept documenting
   * `ais-live` and `vessel-events` as live feeds after both had already gone
   * from the map and from Reference — seen in production on 2026-09-14.
   *
   * ⚠️ `enabledLayerIds` is null when the config has not loaded or its fetch
   * failed. Null must mean "show everything": a network blip is not a reason
   * to tell a reader that the platform's sources do not exist.
   */
  const layerShown = (id: string) => !enabledLayerIds || enabledLayerIds.has(id);

  // Deep-link from a tooltip/panel button: jump to the Layers tab and scroll
  // to the focused layer's row, then clear the request.
  useEffect(() => {
    if (!legendFocusLayer) return;
    setActive("layers");
    const timer = setTimeout(() => {
      document.getElementById(`legend-layer-${legendFocusLayer}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
      clearLegendFocus();
    }, 60);
    return () => clearTimeout(timer);
  }, [legendFocusLayer, clearLegendFocus]);

  useEffect(() => {
    fetch(`${API}/api/v1/sync/status`)
      .then(r => r.ok ? r.json() : {})
      .then(setSyncDates)
      .catch(() => {});
  }, []);

  // Fetch the data inventory only when the user opens the tab — avoids
  // hitting the backend cache miss on every Legend open.
  useEffect(() => {
    if (active !== "inventory" || inventory || inventoryError) return;
    fetch(`${API}/api/v1/stats/dataset-counts`)
      .then(r => r.ok ? r.json() : Promise.reject(new Error(`${r.status}`)))
      .then((data: InventoryResponse) => setInventory(data))
      .catch(() => setInventoryError(true));
  }, [active, inventory, inventoryError]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) { if (e.key === "Escape") onClose(); }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const isMobile = typeof window !== "undefined" && window.matchMedia("(max-width: 767px)").matches;

  return (
    <div className="fixed inset-0 z-overlay flex items-start justify-end pointer-events-none">
      {/* Backdrop */}
      <div
        className="absolute inset-0 pointer-events-auto bg-black/30 sm:bg-transparent"
        onClick={onClose}
      />
      {/* Panel */}
      <div
        ref={ref}
        className={`relative pointer-events-auto bg-[rgba(10,14,20,0.97)] border border-white/[0.08] flex flex-col overflow-hidden ${
          isMobile
            ? "fixed bottom-0 left-0 right-0 max-h-[75vh] rounded-t-lg border-b-0 animate-slide-up"
            : "mt-16 mr-4 mb-4 w-[810px] max-w-[calc(100vw-2rem)] rounded"
        }`}
        style={isMobile ? undefined : { maxHeight: "calc(100vh - 5rem)" }}
      >
        {/* Drag handle (mobile) */}
        {isMobile && (
          <div className="flex justify-center pt-2 pb-1 shrink-0">
            <div className="w-8 h-1 rounded-full bg-white/20" />
          </div>
        )}
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-2 border-b border-white/[0.06] flex-shrink-0">
          <div>
            <p className="text-white/90 text-[13px] font-mono uppercase tracking-[0.12em]">{t("dataReference.title")}</p>
            <p className="text-white/70 text-[13px] font-mono mt-0.5 hidden sm:block">{t("dataReference.subtitle")}</p>
          </div>
          <button
            onClick={onClose}
            className="text-white/60 hover:text-white text-sm leading-none flex-shrink-0 -m-2 p-2 transition-colors"
            aria-label={t("dataReference.closeAriaLabel")}
          >×</button>
        </div>

        {/* Tabs — flex-wrap so longer locales (de) span multiple rows cleanly */}
        <div className="flex flex-wrap border-b border-white/[0.06] flex-shrink-0">
          {TAB_IDS.map(id => (
            <button
              key={id}
              onClick={() => { setActive(id); analytics.openLegendTab(id); }}
              className={`px-3 py-1.5 sm:py-1.5 min-h-[44px] sm:min-h-0 text-xs sm:text-[11px] font-mono uppercase tracking-[0.12em] whitespace-nowrap transition-colors border-b-2 ${
                active === id
                  ? "text-white/90 border-white/45 -mb-[2px]"
                  : "text-white/60 hover:text-white/75 border-transparent"
              }`}
            >
              {t(`tabs.${id}`)}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="overflow-y-auto flex-1 custom-scrollbar">
          {active === "layers" && (
            <div className="divide-y divide-white/[0.04]">
              {LEGEND_ENTRIES
                .filter((s) => !s.layerId || !enabledLayerIds || enabledLayerIds.has(s.layerId))
                .map(s => {
                // i18next strict-key types enforce literal keys — for computed keys we
                // cast the result to string so the JSX renderer gets the right type.
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                const lt = (suffix: string): string => (t as any)(`layers.${s.id}.${suffix}`);
                // Raw (non-string) value reader — for arrays like dataSources, read with
                // returnObjects (same idiom as DiscoveryPanel's nextSteps).
                const ltRaw = (suffix: string): unknown => (t as any)(`layers.${s.id}.${suffix}`, { returnObjects: true });
                return (
                <div key={s.id} id={`legend-layer-${s.id}`} className="px-4 py-2.5">
                  <div className="flex items-center gap-2 mb-2">
                    <LayerSymbol doc={s} />
                    <span className="text-white/95 text-[15px] font-mono uppercase tracking-wide">{lt("label")}</span>
                  </div>
                  <p className="text-white/85 text-[15px] leading-[1.6] mb-2">{lt("description")}</p>
                  <p className="text-white/80 text-[15px] leading-[1.6] mb-2">
                    <span className="text-white/75 font-mono text-[13px] uppercase tracking-wider">{t("dataReference.readingPrefix")} → </span>{lt("reading")}
                  </p>
                  {/* What it is → how to read it → WHEN it is from. Absent for a layer
                      whose frame has not been established at the source yet; absent is
                      honest, a guessed range would not be. */}
                  <TemporalFrame coverage={coverage[s.layerId ?? s.id]} />
                  {lt("selectionCriteria") !== `layers.${s.id}.selectionCriteria` && lt("selectionCriteria") ? (
                    <p className="text-white/80 text-[15px] leading-[1.6] mb-2">
                      <span className="text-white/75 font-mono text-[13px] uppercase tracking-wider">What's included → </span>{lt("selectionCriteria")}
                    </p>
                  ) : null}
                  {lt("limitations") !== `layers.${s.id}.limitations` && lt("limitations") ? (
                    <p className="text-white/80 text-[15px] leading-[1.6] mb-2">
                      <span className="text-white/75 font-mono text-[13px] uppercase tracking-wider">Limitations → </span>{lt("limitations")}
                    </p>
                  ) : null}
                  {s.colorRampHex && (
                    <div className="flex flex-col gap-0.5 my-2">
                      {s.colorRampHex.map((hex, i) => (
                        <div key={hex} className="flex items-center gap-1.5">
                          <span className="inline-block w-3 h-3 rounded-sm shrink-0" style={{ backgroundColor: hex }} />
                          <span className="text-white/80 text-[14px]">{lt(`colorRamp.${i}.label`)}</span>
                        </div>
                      ))}
                    </div>
                  )}
                  <p className="text-white/75 text-[13px] font-mono leading-relaxed whitespace-pre-line">{lt("source")}</p>
                  {lt("method") !== `layers.${s.id}.method` && lt("method") ? (
                    <div className="mt-3">
                      <p className="text-white/60 text-[11px] uppercase tracking-wide mb-1">{t("layers.methodHeading", { defaultValue: "Methodology" })}</p>
                      <p className="text-white/75 text-[13px] leading-relaxed whitespace-pre-line">{lt("method")}</p>
                    </div>
                  ) : null}
                  {Array.isArray(ltRaw("dataSources")) && (ltRaw("dataSources") as { name: string; url: string }[]).length > 0 && (
                    <div className="mt-3">
                      <p className="text-white/60 text-[11px] uppercase tracking-wide mb-1">{t("layers.dataSourcesHeading", { defaultValue: "Data sources" })}</p>
                      <ul className="space-y-0.5">
                        {(ltRaw("dataSources") as { name: string; url: string }[]).map((ds) => (
                          <li key={ds.url}>
                            <a href={ds.url} target="_blank" rel="noopener noreferrer" className="text-cyan-300/80 hover:text-cyan-200 text-[12px] underline decoration-dotted">
                              {ds.name} <span aria-hidden="true">↗</span>
                            </a>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {lt("colorStandard") !== `layers.${s.id}.colorStandard` && lt("colorStandard") ? (
                    <p className="text-white/75 text-[13px] mt-1 leading-relaxed">
                      <span className="text-white/75 font-mono uppercase tracking-wider">{t("dataReference.colorStandardPrefix")} → </span>
                      {lt("colorStandard")}
                    </p>
                  ) : null}
                  {s.syncKey && syncDates[s.syncKey] && (
                    <p className="text-white/70 text-[13px] mt-1 font-mono">
                      {t("dataReference.syncedPrefix")} {syncDates[s.syncKey]}
                    </p>
                  )}
                </div>
                );
              })}
            </div>
          )}

          {active === "inventory" && (
            <div className="px-4 py-3">
              {inventoryError && (
                <p className="text-rose-300/80 text-[14px] leading-relaxed">
                  Inventory unavailable. The backend may be restarting — try again in a minute.
                </p>
              )}
              {!inventoryError && !inventory && (
                <p className="text-white/75 text-[15px]">Loading…</p>
              )}
              {inventory && (
                <>
                  <div className="mb-3 pb-2.5 border-b border-white/[0.06]">
                    <p className="text-white/90 text-[17px] font-mono">
                      {formatCount(inventory.total_objects)} objects
                      <span className="text-white/75"> across {inventory.total_layers} layers</span>
                    </p>
                    <p className="text-white/75 text-[14px] mt-1 leading-relaxed">
                      Live counts of every record we store and render on the map.
                      Sourced from {inventory.total_layers} scientific and regulatory datasets.
                      Counts refresh every 10 minutes.
                    </p>
                  </div>
                  <div className="space-y-4">
                    {inventory.groups.map(group => (
                      <section key={group.id}>
                        <h3 className="text-white/85 text-[13px] font-mono uppercase tracking-[0.14em] mb-1.5">
                          {group.label}
                        </h3>
                        <table className="w-full text-[14px] border-collapse">
                          <thead>
                            <tr className="text-white/75 text-[13px] uppercase tracking-wider">
                              <th className="text-left font-mono font-normal py-1 pr-2">Layer</th>
                              <th className="text-right font-mono font-normal py-1 px-2 w-20">Records</th>
                              <th className="text-left font-mono font-normal py-1 px-2">Source</th>
                              <th className="text-right font-mono font-normal py-1 pl-2 w-20">Synced</th>
                            </tr>
                          </thead>
                          <tbody>
                            {group.items.map(item => (
                              <tr key={item.key} className="border-t border-white/[0.04]">
                                <td className="text-white/85 py-1.5 pr-2 align-top">{item.label}</td>
                                <td className="text-white/90 font-mono text-right py-1.5 px-2 tabular-nums align-top">
                                  {formatCount(item.count)}
                                </td>
                                <td className="text-white/75 py-1.5 px-2 align-top">
                                  <a
                                    href={item.source_url}
                                    target="_blank"
                                    rel="noopener"
                                    className="text-cyan-400/80 hover:text-cyan-300 transition-colors"
                                  >
                                    {item.source_org}
                                  </a>
                                </td>
                                <td className="text-white/70 font-mono text-right text-[13px] py-1.5 pl-2 tabular-nums align-top">
                                  {formatSyncDate(item.last_synced_at)}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </section>
                    ))}
                  </div>
                  <p className="text-white/70 text-[13px] mt-4 pt-3 border-t border-white/[0.04] leading-relaxed">
                    Generated {formatSyncDate(inventory.generated_at)}. Counts are exact (live <code className="text-white/75">count(*)</code> against PostgreSQL); sync dates are when the source last refreshed our copy. "—" means the layer is live or doesn't track per-source sync timestamps.
                  </p>
                </>
              )}
            </div>
          )}

          {active === "howto" && (
            <div className="px-4 py-3 space-y-4 text-[15px] text-white/80 leading-[1.6]">
              <section>
                <h3 className="text-white/85 text-[13px] font-mono uppercase tracking-[0.15em] mb-1.5">{t("howto.navigationTitle")}</h3>
                <ul className="space-y-1.5">
                  <li><span className="text-white/90">Drag</span> — {t("howto.nav_drag")}</li>
                  <li><span className="text-white/90">Scroll / pinch</span> — {t("howto.nav_scroll")}</li>
                  <li><span className="text-white/90">Right-drag or Ctrl+drag</span> — {t("howto.nav_rightdrag")}</li>
                  <li><span className="text-white/90">Click a claim polygon</span> — {t("howto.nav_clickClaim")}</li>
                  <li><span className="text-white/90">Click any other dot or spike</span> — {t("howto.nav_clickDot")}</li>
                  <li><span className="text-white/90">Shift+click any object</span> — {t("howto.nav_shiftclick")}</li>
                  <li><span className="text-white/90">Click empty ocean</span> — {t("howto.nav_clickOcean")}</li>
                </ul>
              </section>
              <section>
                <h3 className="text-white/85 text-[13px] font-mono uppercase tracking-[0.15em] mb-1.5">{t("howto.sidebarTitle")}</h3>
                <ul className="space-y-1.5">
                  <li><span className="text-white/90">Layer toggles</span> — {t("howto.sidebar_toggles")}</li>
                  <li><span className="text-white/90">Locate button (⊙)</span> — {t("howto.sidebar_locate")}</li>
                  <li><span className="text-white/90">Claim Risk Filter</span> — {t("howto.sidebar_claimRisk")}</li>
                  <li><span className="text-white/90">Vent Status</span> — {t("howto.sidebar_ventStatus")}</li>
                  <li><span className="text-white/90">IUCN Filter</span> — {t("howto.sidebar_iucnFilter")}</li>
                  <li><span className="text-white/90">Alarm Filter</span> — {t("howto.sidebar_alarmFilter")}</li>
                  <li><span className="text-white/90">Contractors</span> — {t("howto.sidebar_contractors")}</li>
                  <li><span className="text-white/90">Reset filters</span> — {t("howto.sidebar_reset")}</li>
                  <li><span className="text-white/90">Mobile</span> — {t("howto.sidebar_mobile")}</li>
                </ul>
              </section>
              <section>
                <h3 className="text-white/85 text-[13px] font-mono uppercase tracking-[0.15em] mb-1.5">{t("howto.iucnTitle")}</h3>
                <ul className="space-y-1.5">
                  <li><span className="inline-block w-2 h-2 rounded-full bg-red-500 mr-1.5 align-middle" /><span className="text-white/90">Red</span> — {t("howto.iucn_red")}</li>
                  <li><span className="inline-block w-2 h-2 rounded-full bg-orange-500 mr-1.5 align-middle" /><span className="text-white/90">Orange</span> — {t("howto.iucn_orange")}</li>
                  <li><span className="inline-block w-2 h-2 rounded-full bg-green-500 mr-1.5 align-middle" /><span className="text-white/90">Green</span> — {t("howto.iucn_green")}</li>
                  <li><span className="inline-block w-2 h-2 rounded-full bg-yellow-400 mr-1.5 align-middle" /><span className="text-white/90">Yellow-orange</span> — {t("howto.iucn_yellow")}</li>
                  <li className="text-white/75 text-[15px] pt-1">{t("howto.iucn_note")}</li>
                </ul>
              </section>
              <section>
                <h3 className="text-white/85 text-[13px] font-mono uppercase tracking-[0.15em] mb-1.5">{t("howto.riskTitle")}</h3>
                <ul className="space-y-1.5">
                  <li><span className="text-red-400 font-medium">High Risk</span> — {t("howto.risk_high")}</li>
                  <li><span className="text-orange-400 font-medium">Active Conflict</span> — {t("howto.risk_conflict")}</li>
                  <li><span className="text-yellow-400 font-medium">Dormant Overlap</span> — {t("howto.risk_dormant")}</li>
                  <li><span className="text-white/70 font-medium">Historical Overlap</span> — {t("howto.risk_historical")}</li>
                </ul>
              </section>
              <section>
                <h3 className="text-white/85 text-[13px] font-mono uppercase tracking-[0.15em] mb-1.5">{t("howto.noiseTitle")}</h3>
                <p className="mb-1.5">{t("howto.noise_intro")}</p>
                <ul className="space-y-1.5 mb-1.5">
                  <li><span className="text-red-400 font-medium">Critical (≥0.8)</span> — {t("howto.noise_critical")}</li>
                  <li><span className="text-orange-400 font-medium">High (0.6–0.8)</span> — {t("howto.noise_high")}</li>
                  <li><span className="text-yellow-400 font-medium">Moderate (0.4–0.6)</span> — {t("howto.noise_moderate")}</li>
                  <li><span className="text-green-400 font-medium">Low / Minimal</span> — {t("howto.noise_low")}</li>
                  <li><span className="text-slate-400 font-medium">Data gap</span> — {t("howto.noise_datagap")}</li>
                </ul>
                <p className="mb-1.5">{t("howto.noise_filter")}</p>
                <p className="text-white/75">{t("howto.noise_mining")}</p>
              </section>
              <section>
                <h3 className="text-white text-base font-semibold mb-2 mt-4">{t("howto.chessTitle")}</h3>
                <p className="mb-1.5">{t("howto.chess_intro")}</p>
                <p className="mb-1">{t("howto.chess_filter")}</p>
                <p>{t("howto.chess_vents")}</p>
              </section>
              <section>
                <h3 className="text-white/85 text-[13px] font-mono uppercase tracking-[0.15em] mb-1.5">{t("howto.argoTitle")}</h3>
                <p className="mb-1.5">{t("howto.argo_intro")}</p>
                <ul className="space-y-1">
                  <li><span className="text-orange-400 font-medium">Low oxygen</span> — {t("howto.argo_oxygen")}</li>
                  <li><span className="text-slate-400 font-medium">Low pH</span> — {t("howto.argo_ph")}</li>
                  <li><span className="text-red-400 font-medium">Temp anomaly</span> — {t("howto.argo_temp")}</li>
                  <li><span className="text-cyan-400 font-medium">Salinity anomaly</span> — {t("howto.argo_salinity")}</li>
                </ul>
                <p className="mt-1.5 text-white/75">{t("howto.argo_logic")}</p>
              </section>
              <section>
                <h3 className="text-white/85 text-[13px] font-mono uppercase tracking-[0.15em] mb-1.5">{t("howto.driftTitle")}</h3>
                <p className="mb-2">{t("howto.drift_trail")}</p>
                <p className="mb-2">{t("howto.drift_track")}</p>
                <p>{t("howto.drift_clickable")}</p>
              </section>
              <section>
                <h3 className="text-white/85 text-[13px] font-mono uppercase tracking-[0.15em] mb-1.5 mt-3">{t("howto.landTitle")}</h3>
                <p className="mb-2">{t("howto.land_intro")}</p>
                <ul className="space-y-1.5">
                  <li><span className="text-white/90">Mining Footprints</span> — {t("howto.land_footprints")}</li>
                  <li><span className="text-white/90">Tailings Dams</span> — {t("howto.land_tailings")}</li>
                  <li><span className="text-white/90">Fires + Air Quality</span> — {t("howto.land_fires")}</li>
                  <li><span className="text-white/90">Dams + Surface Water</span> — {t("howto.land_dams")}</li>
                </ul>
                <p className="mt-2 text-white/75">{t("howto.land_note")}</p>
              </section>
            </div>
          )}

          {active === "alarms" && (
            <div className="px-4 py-3 space-y-4 text-[15px] text-white/80 leading-[1.6]">
              <p className="text-white/75 text-[14px] font-mono">
                {t("alarms.intro")}
              </p>

              {/* Low Oxygen */}
              <section>
                <div className="flex items-center gap-2 mb-1.5">
                  <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: "#f97316" }} />
                  <h3 className="text-white/85 text-[13px] font-mono uppercase tracking-[0.15em]">{t("alarms.lowOxygen.title")}</h3>
                </div>
                <p className="mb-1.5">{t("alarms.lowOxygen.description")}</p>
                <table className="w-full text-[14px] font-mono border-collapse">
                  <thead>
                    <tr className="text-white/75 border-b border-white/[0.06]">
                      <th className="text-left pb-1 font-normal">{t("alarms.lowOxygen.tableHeaders.depth")}</th>
                      <th className="text-left pb-1 font-normal">{t("alarms.lowOxygen.tableHeaders.threshold")}</th>
                      <th className="text-left pb-1 font-normal">{t("alarms.lowOxygen.tableHeaders.note")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(["shallow", "mid", "deep"] as const).map((rowKey, i) => (
                      <tr key={rowKey} className={i < 2 ? "border-b border-white/[0.04]" : ""}>
                        <td className="py-0.5 text-white/75">{(t as any)(`alarms.lowOxygen.rows.${rowKey}.depth`)}</td>
                        <td className="py-0.5 text-orange-400">{(t as any)(`alarms.lowOxygen.rows.${rowKey}.threshold`)}</td>
                        <td className="py-0.5 text-white/75">{(t as any)(`alarms.lowOxygen.rows.${rowKey}.note`)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>

              {/* Low pH */}
              <section>
                <div className="flex items-center gap-2 mb-1.5">
                  <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: "#7c9bb5" }} />
                  <h3 className="text-white/85 text-[13px] font-mono uppercase tracking-[0.15em]">{t("alarms.lowPh.title")}</h3>
                </div>
                <p className="mb-1.5">{t("alarms.lowPh.description")}</p>
                <table className="w-full text-[14px] font-mono border-collapse">
                  <thead>
                    <tr className="text-white/75 border-b border-white/[0.06]">
                      <th className="text-left pb-1 font-normal">{t("alarms.lowPh.tableHeaders.depth")}</th>
                      <th className="text-left pb-1 font-normal">{t("alarms.lowPh.tableHeaders.threshold")}</th>
                      <th className="text-left pb-1 font-normal">{t("alarms.lowPh.tableHeaders.normal")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(["shallow", "mid", "deep"] as const).map((rowKey, i) => (
                      <tr key={rowKey} className={i < 2 ? "border-b border-white/[0.04]" : ""}>
                        <td className="py-0.5 text-white/75">{(t as any)(`alarms.lowPh.rows.${rowKey}.depth`)}</td>
                        <td className="py-0.5 text-slate-400">{(t as any)(`alarms.lowPh.rows.${rowKey}.threshold`)}</td>
                        <td className="py-0.5 text-white/75">{(t as any)(`alarms.lowPh.rows.${rowKey}.normal`)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>

              <section className="border-t border-white/[0.06] pt-2.5">
                <h3 className="text-white/85 text-[13px] font-mono uppercase tracking-[0.15em] mb-1.5">{t("alarms.usage.title")}</h3>
                <ol className="space-y-1 list-decimal list-inside">
                  <li><Trans i18nKey="alarms.usage.step1" t={t} components={{ 1: <span className="text-white/90" /> }} /></li>
                  <li><Trans i18nKey="alarms.usage.step2" t={t} components={{ 1: <span className="text-white/90" /> }} /></li>
                  <li>{t("alarms.usage.step3")}</li>
                  <li><Trans i18nKey="alarms.usage.step4" t={t} components={{ 1: <span className="text-white/90" /> }} /></li>
                  <li>{t("alarms.usage.step5")}</li>
                  <li><Trans i18nKey="alarms.usage.step6" t={t} components={{ 1: <span className="text-white/90" /> }} /></li>
                  <li>{t("alarms.usage.step7")}</li>
                </ol>
              </section>
            </div>
          )}

          {active === "dates" && (
            <div className="px-4 py-3 space-y-4 text-[15px] text-white/80 leading-[1.6]">
              <section>
                <h3 className="text-white/85 text-[13px] font-mono uppercase tracking-[0.15em] mb-1.5">{t("dates.whatMeansTitle")}</h3>
                <ul className="space-y-2">
                  <li>
                    <span className="text-white/90 font-medium">{t("dates.mining_expiry_title")}</span>
                    <p>{t("dates.mining_expiry")}</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("dates.obis_obs_title")}</span>
                    <p>{t("dates.obis_obs")}</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("dates.argo_profile_title")}</span>
                    <p>{t("dates.argo_profile")}</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("dates.vents_title")}</span>
                    <p>{t("dates.vents")}</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("dates.eez_title")}</span>
                    <p>{t("dates.eez")}</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("dates.unesco_title")}</span>
                    <p>{t("dates.unesco")}</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("dates.oceansites_title")}</span>
                    <p>{t("dates.oceansites")}</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("dates.onc_title")}</span>
                    <p>{t("dates.onc")}</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("dates.cables_title")}</span>
                    <p>{t("dates.cables")}</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("dates.oncInstruments_title")}</span>
                    <p>{t("dates.oncInstruments")}</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("dates.ports_title")}</span>
                    <p>{t("dates.ports")}</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("dates.tectonic_title")}</span>
                    <p>{t("dates.tectonic")}</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("dates.chess_title")}</span>
                    <p>{t("dates.chess")}</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("dates.worms_title")}</span>
                    <p>{t("dates.worms")}</p>
                  </li>
                </ul>
              </section>
              <section>
                <h3 className="text-white/85 text-[13px] font-mono uppercase tracking-[0.15em] mb-1.5">{t("dates.landDatesTitle")}</h3>
                <ul className="space-y-2">
                  <li>
                    <span className="text-white/90 font-medium">{t("dates.landMining_title")}</span>
                    <p>{t("dates.landMining")}</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("dates.fires_title")}</span>
                    <p>{t("dates.fires")}</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("dates.airQuality_title")}</span>
                    <p>{t("dates.airQuality")}</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("dates.landslides_title")}</span>
                    <p>{t("dates.landslides")}</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("dates.staticDams_title")}</span>
                    <p>{t("dates.staticDams")}</p>
                  </li>
                </ul>
              </section>
              <section>
                <h3 className="text-white/85 text-[13px] font-mono uppercase tracking-[0.15em] mb-1.5">{t("dates.freshnessTitle")}</h3>
                <ul className="space-y-1.5">
                  <li><span className="text-white/90">Argo Floats</span> — {t("dates.fresh_argo")}{syncDates["argo_profiles"] && <span className="text-white/75 font-mono ml-1">({syncDates["argo_profiles"]})</span>}</li>
                  <li><span className="text-white/90">OBIS Species (Deep)</span> — {t("dates.fresh_obis")}{syncDates["biodiversity_hotspots"] && <span className="text-white/75 font-mono ml-1">({syncDates["biodiversity_hotspots"]})</span>}</li>
                  <li><span className="text-white/90">Chemosynthetic Sites</span> — {t("dates.fresh_chess")}{syncDates["chess"] && <span className="text-white/75 font-mono ml-1">({syncDates["chess"]})</span>}</li>
                  <li><span className="text-white/90">OceanSITES</span> — {t("dates.fresh_oceansites")}{syncDates["oceansites-obs"] && <span className="text-white/75 font-mono ml-1">({syncDates["oceansites-obs"]})</span>}</li>
                  <li><span className="text-white/90">Ocean Currents</span> — {t("dates.fresh_currents")}{syncDates["currents-surface"] && <span className="text-white/75 font-mono ml-1">({syncDates["currents-surface"]})</span>}</li>
                  <li><span className="text-white/90">Ocean Climatology (WOA)</span> — Static (WOA23 release)</li>
                  <li><span className="text-white/90">Ocean Carbon (GLODAP)</span> — Static (GLODAPv2.2016b release; observations 1972–2013){syncDates["glodap-carbon"] && <span className="text-white/75 font-mono ml-1">({syncDates["glodap-carbon"]})</span>}</li>
                  <li><span className="text-white/90">Surface Ocean CO₂ (SOCAT)</span> — Static (SOCATv2026 release){syncDates["socat-co2"] && <span className="text-white/75 font-mono ml-1">({syncDates["socat-co2"]})</span>}</li>
                  <li><span className="text-white/90">Ocean Oxygen &amp; Deoxygenation</span> — Static (ISAS 2014–2018 release){syncDates["oxygen-deox"] && <span className="text-white/75 font-mono ml-1">({syncDates["oxygen-deox"]})</span>}</li>
                  <li><span className="text-white/90">Historical Oxygen Profiles (WOD)</span> — Static (WOD23 release; global){syncDates["wod-oxygen"] && <span className="text-white/75 font-mono ml-1">({syncDates["wod-oxygen"]})</span>}</li>
                  <li><span className="text-white/90">Arctic River Inputs</span> — Static (ArcticGRO + PANGAEA datasets){syncDates["arctic-rivers"] && <span className="text-white/75 font-mono ml-1">({syncDates["arctic-rivers"]})</span>}</li>
                  <li><span className="text-white/90">Arctic Catchments (ARCADE)</span> — Static (ARCADE v1 release){syncDates["arcade"] && <span className="text-white/75 font-mono ml-1">({syncDates["arcade"]})</span>}</li>
                  <li><span className="text-white/90">MEMENTO (Marine CH₄/N₂O)</span> — Static (frozen archive, last update ~2020){syncDates["memento"] && <span className="text-white/75 font-mono ml-1">({syncDates["memento"]})</span>}</li>
                  <li><span className="text-white/90">Vent Fluid Chemistry (MARHYS)</span> — Static (MARHYS 4.0, published 2024-10-14; frozen behind its DOI and not updated). Samples collected 1977–2023{syncDates["marhys"] && <span className="text-white/75 font-mono ml-1">({syncDates["marhys"]})</span>}</li>
                  <li><span className="text-white/90">GEOTRACES Trace Metals</span> — Static (GEOTRACES IDP2025 release){syncDates["geotraces"] && <span className="text-white/75 font-mono ml-1">({syncDates["geotraces"]})</span>}</li>
                  <li><span className="text-white/90">Marine Sediment Carbon</span> — Static (MOSAIC v1 release; cores 1900–2022), synced from ETH Zürich{syncDates["mosaic"] && <span className="text-white/75 font-mono ml-1">({syncDates["mosaic"]})</span>}</li>
                  <li><span className="text-white/90">Methane Seeps (SEAFLEA)</span> — Static (SEAFLEA observed database, Feb 2019){syncDates["seaflea"] && <span className="text-white/75 font-mono ml-1">({syncDates["seaflea"]})</span>}</li>
                  <li><span className="text-white/90">SIOS Svalbard Observing</span> — Weekly (SIOS METSIS catalogue){syncDates["sios"] && <span className="text-white/75 font-mono ml-1">({syncDates["sios"]})</span>}</li>
                  <li><span className="text-white/90">Marine Carbon (unified)</span> — Static climatologies (GLODAP v2.2016b, observations 1972–2013 · SOCAT v2026 · ISAS20, 2014–2018 mean · WOA23){syncDates["glodap-carbon"] && <span className="text-white/75 font-mono ml-1">({syncDates["glodap-carbon"]})</span>}</li>
                  <li><span className="text-white/90">VME Suitability (modeled)</span> — Periodic model bake, out-of-process MaxEnt worker (NOAA DSCRTP occurrences){syncDates["vme-sdm"] && <span className="text-white/75 font-mono ml-1">({syncDates["vme-sdm"]})</span>}</li>
                  <li><span className="text-white/90">Ocean Acidification (modeled)</span> — Static (GLODAPv2.2016b release; observations 1972–2013); in-process bake of GLODAP ΩA/ΩC + platform-derived horizon{syncDates["acidification"] && <span className="text-white/75 font-mono ml-1">({syncDates["acidification"]})</span>}</li>
                  <li><span className="text-white/90">Coral Acidification Exposure (modeled)</span> — baked from GLODAP + VME + GEBCO holdings; crosses the VME MaxEnt suitability model with the reconstructed aragonite saturation horizons{syncDates["coral-acid-exposure"] && <span className="text-white/75 font-mono ml-1">({syncDates["coral-acid-exposure"]})</span>}</li>
                  <li><span className="text-white/90">Cumulative Human Impact (modelled)</span> — Static (NCEAS / Halpern et al. 2025 release); present-state cumulative-impact index, baked once from the published global raster{syncDates["chi"] && <span className="text-white/75 font-mono ml-1">({syncDates["chi"]})</span>}</li>
                  <li><span className="text-white/90">Seabed Substrate</span> — Static (Dutkiewicz 2015 release){syncDates["seabed"] && <span className="text-white/75 font-mono ml-1">({syncDates["seabed"]})</span>}</li>
                  <li><span className="text-white/90">Arctic Sediment Carbon</span> — Static (CASCADE v2 release; cores 1934–2018){syncDates["cascade"] && <span className="text-white/75 font-mono ml-1">({syncDates["cascade"]})</span>}</li>
                  <li><span className="text-white/90">Permafrost Thaw</span> — static (Webb et al. 2026 + ARTS v6.0.0 releases), synced from Zenodo{syncDates["permafrost-thaw"] && <span className="text-white/75 font-mono ml-1">({syncDates["permafrost-thaw"]})</span>}</li>
                  <li><span className="text-white/90">Bathymetry confidence</span> — Static (GEBCO_2024 / GMRT){syncDates["bathymetry-stats"] && <span className="text-white/75 font-mono ml-1">({syncDates["bathymetry-stats"]})</span>}</li>
                  {layerShown("ais-live") && (
                  <li><span className="text-white/90">Live Vessels (AIS)</span> — live, last 60 min (AISStream.io WebSocket feed){syncDates["ais_aois"] && <span className="text-white/75 font-mono ml-1">({syncDates["ais_aois"]})</span>}</li>
                  )}
                  {layerShown("vessel-events") && (
                  <li><span className="text-white/90">Dark Vessels (SAR×AIS)</span> — SAR×AIS correlation, synced every 6 h (Sentinel-1 revisit cadence){syncDates["vessel_events"] && <span className="text-white/75 font-mono ml-1">({syncDates["vessel_events"]})</span>}</li>
                  )}
                  <li><span className="text-white/90">ONC Observatories</span> — {t("dates.fresh_onc")}{syncDates["onc-sensors"] && <span className="text-white/75 font-mono ml-1">({syncDates["onc-sensors"]})</span>}</li>
                  <li><span className="text-white/90">ONC Instruments</span> — {t("dates.fresh_oncInstruments")}{syncDates["onc_instruments"] && <span className="text-white/75 font-mono ml-1">({syncDates["onc_instruments"]})</span>}</li>
                  <li><span className="text-white/90">Submarine Cables</span> — {t("dates.fresh_cables")}{syncDates["submarine_cables"] && <span className="text-white/75 font-mono ml-1">({syncDates["submarine_cables"]})</span>}</li>
                  <li><span className="text-white/90">Port Locations</span> — {t("dates.fresh_ports")}{syncDates["port_locations"] && <span className="text-white/75 font-mono ml-1">({syncDates["port_locations"]})</span>}</li>
                  <li>
                    <span className="text-white/90">Offshore Activities</span> — {t("dates.fresh_offshore")}{syncDates["offshore_activities"] && <span className="text-white/75 font-mono ml-1">({syncDates["offshore_activities"]})</span>}
                    <ul className="mt-1 ml-3 space-y-0.5 text-white/75 text-[13px] font-mono">
                      <li>{t("dates.fresh_offshore_emodnet")}</li>
                      <li>{t("dates.fresh_offshore_boem")}</li>
                      <li>{t("dates.fresh_offshore_noaa")}</li>
                      <li>{t("dates.fresh_offshore_crown")}</li>
                      <li>{t("dates.fresh_offshore_scotland")}</li>
                      <li>{t("dates.fresh_offshore_nsta")}</li>
                      <li>{t("dates.fresh_offshore_sodir")}</li>
                      <li>{t("dates.fresh_offshore_geus")}</li>
                      <li>{t("dates.fresh_offshore_cnsopb")}</li>
                      <li>{t("dates.fresh_offshore_cnlopb")}</li>
                      <li>{t("dates.fresh_offshore_mexico")}</li>
                      <li>{t("dates.fresh_offshore_brazil")}</li>
                      <li>{t("dates.fresh_offshore_australia")}</li>
                      <li>{t("dates.fresh_offshore_nz")}</li>
                      <li>{t("dates.fresh_offshore_indonesia")}</li>
                      <li>{t("dates.fresh_offshore_southafrica")}</li>
                      <li>{t("dates.fresh_offshore_png")}</li>
                      <li>{t("dates.fresh_offshore_namibia")}</li>
                      <li>{t("dates.fresh_offshore_cookislands")}</li>
                    </ul>
                  </li>
                  <li>
                    <span className="text-white/90">Hydrophone Stations</span> — synced weekly from 23 networks (OOI, IMOS, MBARI MARS, AWI PALAOA, OBSEA, KM3NeT, SAMBAH, CTBTO IMS + 15 NOAA-archive programs)
                    {syncDates["acoustic-stations"] && (
                      <span className="text-white/75 font-mono ml-1">({syncDates["acoustic-stations"]})</span>
                    )}
                    <ul className="mt-1 ml-3 space-y-0.5 text-white/75 text-[13px] font-mono">
                      <li>OOI — <span className="text-cyan-400">raw.githubusercontent.com/oceanobservatories/asset-management</span></li>
                      <li>IMOS ANMN — <span className="text-cyan-400">geoserver-123.aodn.org.au</span> (typename: <code>imos:anmn_acoustics_map</code>)</li>
                      <li>MBARI MARS — <span className="text-cyan-400">docs.mbari.org/pacific-sound</span></li>
                      <li>AWI PALAOA — <span className="text-cyan-400">doi.pangaea.de/10.1594/PANGAEA.773610</span></li>
                      <li>AWI HAUSGARTEN (Fram Strait, 7 moorings, CC BY 4.0) — <span className="text-cyan-400">doi.pangaea.de/10.1594/PANGAEA.964051</span></li>
                      <li>OBSEA — <span className="text-cyan-400">obsea.es</span></li>
                      <li>KM3NeT (ARCA + ORCA) — <span className="text-cyan-400">km3net.org</span></li>
                      <li>SAMBAH — Baltic Sea C-POD grid (~298 stations, CC0 1.0) — <span className="text-cyan-400">doi.org/10.5061/dryad.n5tb2rbx7</span></li>
                      <li>CTBTO IMS — 11 global hydroacoustic stations (treaty-disclosed positions, structurally static) — <span className="text-cyan-400">ctbto.org/our-work/station-profiles/</span></li>
                      <li>NOAA Passive Acoustic Archive (15 programs: NRS, SanctSound, NEFSC, PIFSC, SEFSC, ONMS, ADEON, BOEM, AEON, Navy, NPS, JASCO, FRAM, CSI, IOOS) — <span className="text-cyan-400">storage.googleapis.com/noaa-passive-bioacoustic/</span></li>
                    </ul>
                  </li>
                  <li><span className="text-white/90">Tectonic Plates</span> — {t("dates.fresh_tectonic")}</li>
                  <li><span className="text-white/90">Tree Cover Loss / Forest Carbon / Soil Organic Carbon</span> — {t("dates.fresh_pendingTiles")}</li>
                  <li><span className="text-white/90">Mining claims</span> — {t("dates.fresh_mining")}{syncDates["mining_contracts"] && <span className="text-white/75 font-mono ml-1">({syncDates["mining_contracts"]})</span>}</li>
                  <li><span className="text-white/90">Relinquished Areas</span> — {t("dates.fresh_relinquished")}{syncDates["relinquished_areas"] && <span className="text-white/75 font-mono ml-1">({syncDates["relinquished_areas"]})</span>}</li>
                  <li><span className="text-white/90">Reserved Areas</span> — {t("dates.fresh_reserved")}{syncDates["reserved_areas"] && <span className="text-white/75 font-mono ml-1">({syncDates["reserved_areas"]})</span>}</li>
                  <li><span className="text-white/90">Protected Areas (APEIs)</span> — {t("dates.fresh_apeis")}{syncDates["apeis"] && <span className="text-white/75 font-mono ml-1">({syncDates["apeis"]})</span>}</li>
                  <li><span className="text-white/90">Baseline Monitoring Density</span> — {t("dates.fresh_density")}{syncDates["mbari-vars"] && <span className="text-white/75 font-mono ml-1">({t("dates.fresh_density_mbari")} {syncDates["mbari-vars"]})</span>}{syncDates["noaa-corals"] && <span className="text-white/75 font-mono ml-1">({t("dates.fresh_density_noaaCorals")} {syncDates["noaa-corals"]})</span>}</li>
                  <li><span className="text-white/90">Contractor Sampling Stations</span> — {t("dates.fresh_contractorStations")}{syncDates["deepdata-stations"] && <span className="text-white/75 font-mono ml-1">({syncDates["deepdata-stations"]})</span>}</li>
                  <li><span className="text-white/90">Seamounts</span> — {t("dates.fresh_seamounts")}{syncDates["seamounts"] && <span className="text-white/75 font-mono ml-1">({t("dates.fresh_seamounts_prefix")} {syncDates["seamounts"]})</span>}</li>
                  <li><span className="text-white/90">Hydrothermal Vents</span> — {t("dates.fresh_vents")}{syncDates["hydrothermal_vents"] && <span className="text-white/75 font-mono ml-1">({syncDates["hydrothermal_vents"]})</span>}</li>
                  <li><span className="text-white/90">Noise Risk Grid</span> — {t("dates.fresh_noiseRisk")}{syncDates["noise_risk"] && <span className="text-white/75 font-mono ml-1">({syncDates["noise_risk"]})</span>}</li>
                  <li><span className="text-white/90">EEZ Boundaries</span> — {t("dates.fresh_eez")}{syncDates["eez"] && <span className="text-white/75 font-mono ml-1">({syncDates["eez"]})</span>}</li>
                  <li><span className="text-white/90">UNESCO Marine Heritage</span> — {t("dates.fresh_unesco")}{syncDates["protected_marine_sites"] && <span className="text-white/75 font-mono ml-1">({syncDates["protected_marine_sites"]})</span>}</li>
                </ul>
                <h3 className="text-white text-base font-semibold mb-2 mt-4">{t("dates.landLayersTitle")}</h3>
                <ul className="space-y-1.5">
                  <li><span className="text-white/90">Mining Footprints</span> — {t("dates.fresh_miningFootprints")}{syncDates["mining_footprints"] && <span className="text-white/75 font-mono ml-1">({syncDates["mining_footprints"]})</span>}</li>
                  <li><span className="text-white/90">Tailings Dams</span> — {t("dates.fresh_tailings")}{syncDates["tailings_dams"] && <span className="text-white/75 font-mono ml-1">({syncDates["tailings_dams"]})</span>}</li>
                  <li><span className="text-white/90">Active Fires (FIRMS)</span> — {t("dates.fresh_fires")}{syncDates["active_fires"] && <span className="text-white/75 font-mono ml-1">({syncDates["active_fires"]})</span>}</li>
                  <li><span className="text-white/90">Air Quality</span> — {t("dates.fresh_airQuality")}{syncDates["air_quality"] && <span className="text-white/75 font-mono ml-1">({syncDates["air_quality"]})</span>}</li>
                  <li><span className="text-white/90">Landslides</span> — {t("dates.fresh_landslides")}{syncDates["landslides"] && <span className="text-white/75 font-mono ml-1">({syncDates["landslides"]})</span>}</li>
                  <li><span className="text-white/90">Global Dams</span> — {t("dates.fresh_dams")}{syncDates["dams"] && <span className="text-white/75 font-mono ml-1">({syncDates["dams"]})</span>}</li>
                  <li><span className="text-white/90">Surface Water</span> — {t("dates.fresh_surfaceWater")}</li>
                  <li><span className="text-white/90">Water Risk (Aqueduct)</span> — {t("dates.fresh_waterRisk")}{syncDates["water_risk"] && <span className="text-white/75 font-mono ml-1">({syncDates["water_risk"]})</span>}</li>
                </ul>
                <h3 className="text-white text-base font-semibold mb-2 mt-4">{t("dates.generalTitle")}</h3>
                <ul className="space-y-1.5">
                  <li><span className="text-white/90">API responses</span> — {t("dates.fresh_apiResponses")}</li>
                </ul>
              </section>
            </div>
          )}

          {active === "verify" && (
            <div className="px-4 py-3 space-y-4 text-[15px] text-white/80 leading-[1.6]">
              <section>
                <h3 className="text-white/85 text-[13px] font-mono uppercase tracking-[0.15em] mb-1.5">{t("verify.primaryTitle")}</h3>
                <ul className="space-y-2">
                  <li>
                    <span className="text-white/90 font-medium">{t("verify.isa_title")}</span>
                    <p className="mt-0.5">{t("verify.isa")}</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("verify.relinquished_title")}</span>
                    <p className="mt-0.5">{t("verify.relinquished")}</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("verify.reserved_title")}</span>
                    <p className="mt-0.5">{t("verify.reserved")}</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("verify.apeis_title")}</span>
                    <p className="mt-0.5">{t("verify.apeis")}</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("verify.density_title")}</span>
                    <p className="mt-0.5">{t("verify.density_intro")}</p>
                    <ul className="mt-1 ml-3 space-y-0.5 text-white/75 text-[13px] font-mono">
                      <li>{t("verify.sources.argoFloats")} → <span className="text-cyan-400">argovis.colorado.edu</span></li>
                      <li>{t("verify.sources.chemosynthenticSites")} → <span className="text-cyan-400">gbif.org/dataset/dc5abc9f-84d5-4046-a3ef-9ab24ae53756</span></li>
                      <li>{t("verify.sources.oceansitesMoorings")} → <span className="text-cyan-400">oceanops.org</span></li>
                      <li>{t("verify.sources.oncInstruments")} → <span className="text-cyan-400">data.oceannetworks.ca</span></li>
                      <li>{t("verify.sources.obisSpecies")} → <span className="text-cyan-400">obis.org</span></li>
                      <li>{t("verify.sources.wod")} → <span className="text-cyan-400">ncei.noaa.gov/products/world-ocean-database</span></li>
                      <li>{t("verify.sources.pangaea")} → <span className="text-cyan-400">pangaea.de</span></li>
                      <li>{t("verify.sources.bcoDmo")} → <span className="text-cyan-400">bco-dmo.org</span></li>
                      <li>{t("verify.sources.noaaDatasets")} → <span className="text-cyan-400">ncei.noaa.gov</span></li>
                      <li>{t("verify.sources.obisSeamap")} → <span className="text-cyan-400">seamap.env.duke.edu</span></li>
                      <li>{t("verify.sources.cchdo")} → <span className="text-cyan-400">cchdo.ucsd.edu</span></li>
                      <li>{t("verify.sources.sioBenthic")} → <span className="text-cyan-400">sioapps.ucsd.edu/collections/bi/</span></li>
                      <li>{t("verify.sources.isaDeepData")} → <span className="text-cyan-400">api.obis.org/v3/occurrence?nodeid=9d2d95be-32eb-4d81-8911-32cb8bc641c8</span></li>
                      <li>{t("verify.sources.mbariVars")} → <span className="text-cyan-400">api.obis.org/v3/occurrence?datasetid=a419c8da-35ed-4b62-9709-39b56369c44e</span></li>
                      <li>
                        <Trans i18nKey="verify.sources.noaaCorals" t={t}>
                          NOAA Deep-Sea Coral &amp; Sponge (DSCRTP — copy <code>CatalogNumber</code> from the cell-sample tooltip)
                        </Trans>
                        {" → "}
                        <span className="text-cyan-400">services2.arcgis.com/C8EMgrsFcRFL6LrL/arcgis/rest/services/DSCRTP_NatDB/FeatureServer/0/query</span>
                      </li>
                      <li>{t("verify.sources.seabedSubstrate")} → <span className="text-cyan-400">earthbyte.org/seafloor-lithology-of-the-ocean-basins</span></li>
                      <li>{t("verify.sources.arcticSedimentCarbon")}</li>
                    </ul>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("verify.contractorStations_title")}</span>
                    <p className="mt-0.5">{t("verify.contractorStations_intro")}</p>
                    <ul className="mt-1 ml-3 space-y-0.5 text-white/75 text-[13px] font-mono">
                      <li>{t("verify.sources.cs_allArchives")} → <span className="text-cyan-400">datasets.obis.org/hosted/isa/index.html</span></li>
                      <li>{t("verify.sources.cs_perArchive")} → <span className="text-cyan-400">datasets.obis.org/hosted/isa/&lt;slug&gt;/index.html</span> (slug shown in panel)</li>
                      <li>{t("verify.sources.cs_sourceZip")} → <span className="text-cyan-400">datasets.obis.org/hosted/isa/&lt;slug&gt;/&lt;slug&gt;.zip</span> — open occurrence.txt and grep your eventID</li>
                      <li>{t("verify.sources.cs_crossCheck")} → <span className="text-cyan-400">api.obis.org/v3/occurrence?nodeid=9d2d95be-32eb-4d81-8911-32cb8bc641c8</span></li>
                      <li>{t("verify.sources.cs_isaPortal")} → <span className="text-cyan-400">data.isa.org.jm</span> (account required)</li>
                    </ul>
                    <p className="mt-0.5 text-white/75">{t("verify.contractorStations_footer")}</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("verify.obis_title")}</span>
                    <p className="mt-0.5">{t("verify.obis_intro")}</p>
                    <p className="mt-0.5 text-white/75">{t("verify.obis_citation", { year: new Date().getFullYear() })}{syncDates["biodiversity_hotspots"] ? " " + t("verify.obis_citationAccessed", { date: syncDates["biodiversity_hotspots"] }) : ""}</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("verify.argo_title")}</span>
                    <p className="mt-0.5">{t("verify.argo")}</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("verify.vents_title")}</span>
                    <p className="mt-0.5">
                      <Trans i18nKey="verify.vents" t={t}>
                        Beaulieu, Stace E; Szafrański, Kamil M (2020): InterRidge Global Database of Active Submarine Hydrothermal Vent Fields Version 3.4 [dataset]. PANGAEA, <a href="https://doi.org/10.1594/PANGAEA.917894" target="_blank" rel="noopener" className="text-cyan-400 hover:text-cyan-300 underline font-mono">https://doi.org/10.1594/PANGAEA.917894</a>. Each vent entry includes the discovery reference.
                      </Trans>
                    </p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("verify.seamounts_title")}</span>
                    <p className="mt-0.5">
                      <Trans i18nKey="verify.seamounts" t={t}>
                        Yesson, Chris; Letessier, Tom B; Nimmo-Smith, Alex; Hosegood, Phil; Brierley, Andrew S; Hardouin, Marie; Proud, Roland (2020): List of seamounts in the world oceans - An update [dataset]. PANGAEA, <a href="https://doi.org/10.1594/PANGAEA.921688" target="_blank" rel="noopener" className="text-cyan-400 hover:text-cyan-300 underline font-mono">https://doi.org/10.1594/PANGAEA.921688</a>. Based on SRTM v.11 bathymetry. CC BY 4.0.
                      </Trans>
                    </p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("verify.eez_title")}</span>
                    <p className="mt-0.5">{t("verify.eez")}</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("verify.unesco_title")}</span>
                    <p className="mt-0.5">{t("verify.unesco")}</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("verify.oceansites_title")}</span>
                    <p className="mt-0.5">{t("verify.oceansites")}</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("verify.currents_title")}</span>
                    <p className="mt-0.5">{t("verify.currents")} <span className="text-cyan-400">data.marine.copernicus.eu</span></p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">Ocean Climatology (WOA)</span>
                    <p className="mt-0.5">Cross-check via the NOAA WOA23 selector — select variable, depth, and season at <span className="text-cyan-400">ncei.noaa.gov/access/world-ocean-atlas-2023/</span> · NCEI Accession 0270533.</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">Ocean Carbon (GLODAP)</span>
                    <p className="mt-0.5">Cross-check a grid cell value by selecting the same variable and depth at <span className="text-cyan-400">glodap.info/index.php/mapped-data-product/</span>. The mapped product (GLODAPv2.2016b) is also available via the NCEI data portal and the <span className="text-cyan-400">doi.org/10.3334/CDIAC/OTG.NDP093_V2016</span> DOI. Values shown in the hexagon view are served verbatim from the 1° DIVA-interpolated product.</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">Ocean Acidification (modeled)</span>
                    <p className="mt-0.5">The ΩA/ΩC fields are GLODAP's own <span className="text-cyan-400">OmegaA</span>/<span className="text-cyan-400">OmegaC</span> saturation variables — cross-check a hexagon value at the same lat/lon/depth against the GLODAPv2.2016b mapped product at <span className="text-cyan-400">glodap.info/index.php/mapped-data-product/</span> (read directly, never recomputed). The aragonite saturation-horizon depth is <span className="text-white/80">platform-derived</span> (shallowest depth where ΩA crosses 1.0, interpolated from GLODAP's 33 standard levels) — recompute it yourself from the ΩA profile to verify.</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">Cumulative Human Impact (modelled)</span>
                    <p className="mt-0.5">A modelled dimensionless index of total human pressure — the sum of ~10 anthropogenic stressors, present-state only. Download the published global raster and cross-check a cell yourself from NCEAS / Halpern et al. 2025 at <span className="text-cyan-400">doi.org/10.1126/science.adv2906</span> (data archived on the KNB repository, <span className="text-cyan-400">doi.org/10.5063/F18K77KZ</span>, CC0 1.0). Seabed mining is only a minor component and ISA claim areas sit in relatively low-impact abyssal zones — context, not accusation; a concession polygon is not a causal source of this impact.</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">Coral Acidification Exposure (modeled)</span>
                    <p className="mt-0.5">Both inputs crossed here are independently verifiable, but the cross itself is <span className="text-white/80">platform-derived</span> — there is no upstream "exposure" number to look up directly. Cross-check the aragonite saturation horizon against the GLODAPv2.2016b mapped product at <span className="text-cyan-400">glodap.info</span> (same ΩA field used by the Ocean Acidification layer). Cross-check the coral occurrences the VME suitability model was trained on against NOAA's Deep-Sea Coral &amp; Sponge (DSCRTP) database at <span className="text-cyan-400">services2.arcgis.com/C8EMgrsFcRFL6LrL/arcgis/rest/services/DSCRTP_NatDB/FeatureServer/0/query</span>. The click panel's underlying <code className="text-white/75">cell_id</code> (same hex grid as the VME Suitability and Ocean Acidification layers) is the field to quote alongside lat/lon when asking for a side-by-side check of the same cell.</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">Surface Ocean CO₂ (SOCAT)</span>
                    <p className="mt-0.5">Cross-check a grid cell using the decade and variable shown in the hexagon panel at <span className="text-cyan-400">socat.info</span>. The underlying gridded climatology is NOAA NCEI Accession 0315110 — downloadable directly at <span className="text-cyan-400">ncei.noaa.gov/access/ocean-carbon-acidification-data-system-portal/</span> (search accession 0315110). Values in the hexagon view are served verbatim from the SOCATv2026 decadal 1° grid.</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">Historical Oxygen Profiles (WOD)</span>
                    <p className="mt-0.5">Cross-check a cast using the <code className="text-white/75">wod_cast_id</code> shown in the click panel at <span className="text-cyan-400">ncei.noaa.gov/access/world-ocean-database/</span> (WODselect). Profiles are served verbatim — units and QC flags are as published by NOAA NCEI.</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">Arctic River Inputs</span>
                    <p className="mt-0.5">ArcticGRO stations: cross-check discharge and biogeochemistry records at <span className="text-cyan-400">arcticgreatrivers.org/data</span>. PANGAEA Canadian Arctic Archipelago stations: <span className="text-cyan-400">doi.pangaea.de/10.1594/PANGAEA.945702</span>. Concentrations, sampling-date discharge, and citation are served verbatim from the upstream datasets.</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">MEMENTO (Marine CH₄/N₂O)</span>
                    <p className="mt-0.5">Cross-check cruises by name at <span className="text-cyan-400">portal.geomar.de/memento</span> (search by cruise name shown in the click panel). For any unpublished data, contact the contributing scientist before use. Database citation (per MEMENTO's terms of use): Kock &amp; Bange (2015) Eos 96(3), 10–13, doi:10.1029/2015EO023665. Project paper: Bange et al. (2009) Environ. Chem., doi:10.1071/en09033.</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">Vent Fluid Chemistry (MARHYS)</span>
                    <p className="mt-0.5">Download the source workbook yourself at <span className="text-cyan-400">doi.org/10.1594/PANGAEA.972999</span> and find a sample by the Sample-ID shown in the click panel — note that MARHYS reuses some Sample-IDs, so match on the vent site and date as well. Values are served verbatim: nothing is unit-converted, averaged or corrected. A magnesium reading of 0 is a real value, not a gap. ⚠️ Two source errors are reproduced rather than repaired: 39 Guaymas Basin samples carry a latitude of 111.4°, which no latitude can be, and are held without a position; and the Saldanha Hydrothermal Field is published at 36.567 / +33.6, which is dry land in Turkey, where InterRidge has 36.567 / −33.433. Citation, required in full by the dataset's own terms: Diehl &amp; Bach (2024), doi:10.1594/PANGAEA.972999, <em>together with</em> Diehl &amp; Bach (2020), doi:10.1029/2020GC009385.</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">GEOTRACES Trace Metals</span>
                    <p className="mt-0.5">Cross-check a station using the cruise and station shown in the click panel at the BODC DOI landing: <span className="text-cyan-400">doi.org/10.5285/42c92148-8d03-8be6-e063-7086abc09f0c</span>. The full eGEOTRACES data explorer is at <span className="text-cyan-400">eGEOTRACES.org</span>. Data are served verbatim from the GEOTRACES IDP2025 release.</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">Marine Sediment Carbon</span>
                    <p className="mt-0.5">Cross-check a core using the sample details and depth shown in the click panel at <span className="text-cyan-400">mosaic.ethz.ch</span>. The MOSAIC database provides access to raw sediment core archives and supplementary metadata from contributing institutions worldwide. Values are served verbatim from the MOSAIC v1 release.</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">Methane Seeps (SEAFLEA)</span>
                    <p className="mt-0.5">Cross-check a seep record using the <code className="text-white/75">ext_id</code> (Data Base ID) shown in the click panel against the NOAA SEAFLEA ArcGIS hub — query layer 6 directly at <span className="text-cyan-400 font-mono">services2.arcgis.com/C8EMgrsFcRFL6LrL/.../SEAFLEAs_Web_Map_WFL1/FeatureServer/6</span>. Data are served verbatim from the Feb-2019 SEAFLEA snapshot compiled by Phrampus et al. (2020), doi:10.1029/2019GC008747.</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">SIOS Svalbard Observing</span>
                    <p className="mt-0.5">Cross-check a dataset using the <code className="text-white/75">metadata_id</code> shown in the click panel at <span className="text-cyan-400">sios-svalbard.org/metsis/search</span> — search by the platform name or paste the metadata_id. Dataset metadata and access links (OPeNDAP, HTTP, WMS, landing page) are served verbatim from the SIOS METSIS catalogue REST endpoint.</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">Marine Carbon (unified)</span>
                    <p className="mt-0.5">Each click panel lists every source value separately. Cross-check interior carbon at <span className="text-cyan-400">glodap.info</span>, surface CO₂ at <span className="text-cyan-400">socat.info</span>, and oxygen/physical climatology at <span className="text-cyan-400">ncei.noaa.gov/products/world-ocean-atlas</span>. Values are co-located samples from independent climatologies, never a combined number.</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">VME Suitability (modeled)</span>
                    <p className="mt-0.5">The suitability/uncertainty scores are computed on this platform and cannot be looked up at an upstream source — there is no external "answer" to check them against. What you CAN verify is the input data: the coral occurrence records the model was trained on are NOAA's Deep-Sea Coral &amp; Sponge (DSCRTP) database, queryable directly at <span className="text-cyan-400">services2.arcgis.com/C8EMgrsFcRFL6LrL/arcgis/rest/services/DSCRTP_NatDB/FeatureServer/0/query</span>. The environmental predictors are the published GEBCO 2024, seabed substrate (Dutkiewicz et al. 2015), WOA23, ISAS20 and GLODAPv2.2016b climatologies used elsewhere on this platform. The model itself (MaxEnt/elapid) is ours — only the inputs are independently verifiable.</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">Arctic Catchments (ARCADE)</span>
                    <p className="mt-0.5">Cross-check a catchment using the <code className="text-white/75">gid</code> shown in the click panel, or match by centroid coordinates, against the ARCADE v1 dataset at DataVerse NL: <span className="text-cyan-400 font-mono">doi:10.34894/U9HSPV</span>. Variable values (soil organic carbon stock, runoff, permafrost extent, mean air temperature) are served verbatim from the ARCADE v1 release.</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">Permafrost Thaw</span>
                    <p className="mt-0.5">This layer unions <strong>two</strong> compilations and a feature belongs to exactly one of them — check the <code className="text-white/75">source</code> field in the click panel first, because the wrong DOI will not find it. Each feature also links to its own original publication via the <span className="text-cyan-400 font-mono">DOI</span> shown in the panel.</p>
                    <ul className="mt-1 ml-3 list-disc space-y-0.5">
                      <li><code className="text-white/75">alaska_webb</code> — 19,540 points, Alaska, full nine-category taxonomy: Alaska Permafrost Thaw Database v2.0.0, Webb et al. 2026 (ESSD 18:3147), <span className="text-cyan-400 font-mono">zenodo.org/doi/10.5281/zenodo.16996415</span>, CC-BY 4.0.</li>
                      <li><code className="text-white/75">arts_panarctic</code> — 27,699 points, circumpolar, all retrogressive thaw slumps: ARTS v6.0.0, Yang/Rodenhizer/Rogers et al. 2025 (Sci. Data 12:18, <span className="text-cyan-400 font-mono">doi:10.1038/s41597-025-04372-7</span>), <span className="text-cyan-400 font-mono">zenodo.org/doi/10.5281/zenodo.10535025</span>, CC0.</li>
                    </ul>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">Bathymetry &amp; mapping confidence</span>
                    <p className="mt-0.5">This enrichment appears in Argo profile and other per-feature click panels. Depth values come from GEBCO_2024; mapping confidence (TID category) from the GEBCO_2024 Type Identifier grid. Cross-check at <span className="text-cyan-400">gebco.net/data_and_products/gridded_bathymetry_data/</span> — select "GEBCO_2024 TID Grid" and query the same coordinates. Shiptrack density can be explored in GMRT at <span className="text-cyan-400">gmrt.org</span>. Limitations: cells labelled "predicted" or "interpolated" are satellite-gravity-derived (accuracy may be ±100 m or worse in unsurveyed areas); GEBCO applies spatial interpolation between sounding lines; GMRT data are CC-BY with regional coverage gaps; values are not certified for navigation.</p>
                  </li>
                  {layerShown("ais-live") && (
                  <li>
                    <span className="text-white/90 font-medium">Live Vessels (AIS)</span>
                    <p className="mt-0.5">Raw AIS positions from the AISStream.io WebSocket feed, last 60 minutes. Cross-check any vessel by its <code className="text-white/75">MMSI</code> at <span className="text-cyan-400">aisstream.io</span> or <span className="text-cyan-400">marinetraffic.com</span>. Coverage reflects terrestrial + satellite AIS receiver density — dense in coastal shipping lanes and shipping-route corridors, sparse in the open ocean. An empty stretch of ocean does not mean no vessels are present, only that none were within range of an AIS receiver.</p>
                  </li>
                  )}
                  {layerShown("vessel-events") && (
                  <li>
                    <span className="text-white/90 font-medium">Dark Vessels (SAR×AIS)</span>
                    <p className="mt-0.5">SAR detections come from Copernicus Sentinel-1 (ESA/EU), correlated against AIS positions within ±10 min / ±500 m. A "dark" classification means a SAR-detected vessel had no matching AIS broadcast — this can mean AIS was switched off, but can equally mean AIS coverage was too sparse in that area to expect a match (see the Live Vessels coastal-coverage caveat above); it is not on its own evidence of evasion. A detection is only marked 'dark' when other vessels' AIS was being received within 50 km and ±1 h; with no nearby AIS reception it is marked 'ambiguous' (a coverage gap, not a finding). Cross-check a detection's scene via its <code className="text-white/75">sar_detection_id</code> at <span className="text-cyan-400">dataspace.copernicus.eu</span>, or a matched vessel's <code className="text-white/75">matched_mmsi</code> at <span className="text-cyan-400">aisstream.io</span>.</p>
                  </li>
                  )}
                  <li>
                    <span className="text-white/90 font-medium">{t("verify.onc_title")}</span>
                    <p className="mt-0.5">{t("verify.onc")}</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("verify.oncInstruments_title")}</span>
                    <p className="mt-0.5">{t("verify.oncInstruments")}</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("verify.cables_title")}</span>
                    <p className="mt-0.5">{t("verify.cables")}</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("verify.ports_title")}</span>
                    <p className="mt-0.5">{t("verify.ports")}</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("verify.tectonic_title")}</span>
                    <p className="mt-0.5">{t("verify.tectonic")}</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("verify.offshore_title")}</span>
                    <p className="mt-0.5">{t("verify.offshore_intro")}</p>
                    <ul className="mt-1 ml-3 space-y-0.5 text-white/75 text-[13px] font-mono">
                      <li>EU EEZs → <span className="text-cyan-400">emodnet-humanactivities.eu/view-data.php</span></li>
                      <li>USA OCS (oil/gas) → <span className="text-cyan-400">data.bsee.gov/Leasing/Leases/Default.aspx</span> (search by lease number)</li>
                      <li>USA offshore wind → <span className="text-cyan-400">boem.gov/renewable-energy/lease-and-grant-information</span></li>
                      <li>UK (England/Wales/NI) → <span className="text-cyan-400">thecrownestate.co.uk/energy-minerals-and-infrastructure/offshore-wind</span></li>
                      <li>Scotland (ScotWind/INTOG) → <span className="text-cyan-400">crownestatescotland.com/our-portfolio/offshore-wind-and-marine</span></li>
                      <li>UK oil/gas → <span className="text-cyan-400">nstauthority.co.uk/data-centre/nsta-open-data</span></li>
                      <li>UK CCS → <span className="text-cyan-400">nstauthority.co.uk/licensing-consents/carbon-storage</span></li>
                      <li>Norway → <span className="text-cyan-400">factpages.sodir.no</span> (search by licence name)</li>
                      <li>Norway CCS → <span className="text-cyan-400">factpages.sodir.no/storage</span></li>
                      <li>Colombia → <span className="text-cyan-400">anh.gov.co/Paginas/GeoVisor.aspx</span></li>
                      <li>Denmark → <span className="text-cyan-400">data.geus.dk/geusmap</span> (SAMBA licence database)</li>
                      <li>Canada Nova Scotia → <span className="text-cyan-400">cnsopb.ns.ca</span></li>
                      <li>Canada Newfoundland &amp; Labrador → <span className="text-cyan-400">cnlopb.ca</span></li>
                      <li>Mexico → <span className="text-cyan-400">gob.mx/cnh</span></li>
                      <li>Brazil → <span className="text-cyan-400">gov.br/anp/pt-br/assuntos/exploracao-e-producao-de-oleo-e-gas</span></li>
                      <li>Australia → <span className="text-cyan-400">nopta.gov.au/titles-register.html</span></li>
                      <li>New Zealand → <span className="text-cyan-400">nzpam.govt.nz/maps-geoscience/online-permit-register</span></li>
                      <li>Indonesia → <span className="text-cyan-400">geoportal.esdm.go.id/migas</span></li>
                      <li>South Africa → <span className="text-cyan-400">petroleumagencysa.com</span></li>
                      <li>Papua New Guinea → <span className="text-cyan-400">portal.mra.gov.pg</span></li>
                      <li>Namibia → <span className="text-cyan-400">portals.landfolio.com/namibia</span></li>
                      <li>Cook Islands → <span className="text-cyan-400">sbma.gov.ck/map-of-applications</span></li>
                    </ul>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("verify.noiseRisk_title")}</span>
                    <p className="mt-0.5">{t("verify.noiseRisk")}</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("verify.chess_title")}</span>
                    <p className="mt-0.5">{t("verify.chess")}</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">Hydrophone Stations</span>
                    <p className="mt-0.5">Cross-check station metadata at the publishing network's portal — copy the Station ID shown in the popup:</p>
                    <ul className="mt-1 ml-3 space-y-0.5 text-white/75 text-[13px] font-mono">
                      <li>OOI → <span className="text-cyan-400">ooinet.oceanobservatories.org/data_access/</span></li>
                      <li>IMOS → <span className="text-cyan-400">portal.aodn.org.au</span></li>
                      <li>MBARI MARS → <span className="text-cyan-400">docs.mbari.org/pacific-sound/</span></li>
                      <li>AWI PALAOA → <span className="text-cyan-400">doi.pangaea.de/10.1594/PANGAEA.773610</span></li>
                      <li>AWI HAUSGARTEN (Fram Strait) → <span className="text-cyan-400">doi.pangaea.de/10.1594/PANGAEA.964051</span></li>
                      <li>SAMBAH (Baltic Sea C-POD grid) → <span className="text-cyan-400">datadryad.org/stash/dataset/doi:10.5061/dryad.n5tb2rbx7</span></li>
                      <li>CTBTO IMS (global hydroacoustic network) → <span className="text-cyan-400">ctbto.org/our-work/station-profiles/</span></li>
                      <li>OBSEA → <span className="text-cyan-400">obsea.es/index.php/en/observatory</span></li>
                      <li>KM3NeT → <span className="text-cyan-400">km3net.org/research/research-infrastructure/</span></li>
                      <li>NOAA NRS → <span className="text-cyan-400">ncei.noaa.gov/maps/passive-acoustic-data/</span></li>
                      <li>NOAA SanctSound → <span className="text-cyan-400">sanctsound.ioos.us/</span></li>
                      <li>NOAA NEFSC → <span className="text-cyan-400">fisheries.noaa.gov/new-england-mid-atlantic/endangered-species-conservation/passive-acoustic-research-atlantic-marine</span></li>
                      <li>NOAA PIFSC / SEFSC / ONMS / Navy / NPS / IOOS / BOEM / ADEON / AEON / JASCO / FRAM / CSI → single bucket at <span className="text-cyan-400">console.cloud.google.com/storage/browser/noaa-passive-bioacoustic</span> (12 program prefixes — SWFSC + AFSC excluded, mobile platforms only)</li>
                    </ul>
                  </li>
                  <li>
                    <span className="text-white/80 font-medium">{t("verify.worms_title")}</span>
                    <p>{t("verify.worms")}</p>
                  </li>
                </ul>
              </section>
              <section className="mt-3 rounded-md bg-white/5 border border-white/10 p-3">
                <h3 className="text-white/85 text-[13px] font-mono uppercase tracking-[0.15em] mb-1.5">EMODnet acknowledgement</h3>
                <p className="text-white/75 text-[13px] leading-relaxed mb-2">
                  Several marine layers (Submarine Cables, EU EEZs &amp; maritime boundaries, offshore-activity zones, and the underwater-noise field) are served via the European Marine Observation and Data Network (EMODnet), the EU&apos;s in-situ marine data service. EMODnet is a data assembler that harmonises datasets from national and institutional originators — those originators are named per layer in the sources above and in each layer&apos;s Reference entry.
                </p>
                <p className="text-white/75 text-[13px] leading-relaxed mb-1">For aggregated data:</p>
                <p className="text-white/70 text-[13px] leading-relaxed italic mb-2">
                  &ldquo;This data was downloaded from the EMODnet Portal (<span className="text-cyan-400 font-mono">emodnet.ec.europa.eu/en</span>). The data originator(s) is/are the providers listed per layer above and in the source metadata.&rdquo;
                </p>
                <p className="text-white/75 text-[13px] leading-relaxed mb-1">For data products created by EMODnet (e.g. the impulsive-noise / INER field):</p>
                <p className="text-white/70 text-[13px] leading-relaxed italic">
                  &ldquo;This data product was created by EMODnet (<span className="text-cyan-400 font-mono">emodnet.ec.europa.eu/en</span>), and is owned by the EU and licensed under the Creative Commons Attribution 4.0 International (CC BY 4.0) license.&rdquo;
                </p>
              </section>
              <section>
                <h3 className="text-white/85 text-[13px] font-mono uppercase tracking-[0.15em] mb-1.5">{t("verify.landTitle")}</h3>
                <ul className="space-y-2">
                  <li>
                    <span className="text-white/90 font-medium">{t("verify.landMining_title")}</span>
                    <p className="mt-0.5">
                      <Trans i18nKey="verify.landMining" t={t}>
                        Maus, Victor; da Silva, Dieison M; Gutschlhofer, Jakob; da Rosa, Robson; Giljum, Stefan; Gass, Sidnei L B; Luckeneder, Sebastian; Lieber, Mirko; McCallum, Ian (2022): Global-scale mining polygons (Version 2) [dataset]. PANGAEA, <a href="https://doi.org/10.1594/PANGAEA.942325" target="_blank" rel="noopener" className="text-cyan-400 hover:text-cyan-300 underline font-mono">https://doi.org/10.1594/PANGAEA.942325</a>. Sentinel-2 derived polygons at 10m resolution. CC BY 4.0. Companion paper: Maus et al. (2022) Sci. Data 9, 433.
                      </Trans>
                    </p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("verify.tailings_title")}</span>
                    <p className="mt-0.5">{t("verify.tailings")}</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("verify.fires_title")}</span>
                    <p className="mt-0.5">{t("verify.fires")}</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("verify.airQuality_title")}</span>
                    <p className="mt-0.5">{t("verify.airQuality")}</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("verify.landslides_title")}</span>
                    <p className="mt-0.5">{t("verify.landslides")}</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("verify.dams_title")}</span>
                    <p className="mt-0.5">{t("verify.dams")}</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("verify.surfaceWater_title")}</span>
                    <p className="mt-0.5">{t("verify.surfaceWater")}</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("verify.waterRisk_title")}</span>
                    <p className="mt-0.5">{t("verify.waterRisk")}</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("verify.treeCoverLoss_title")}</span>
                    <p className="mt-0.5">{t("verify.treeCoverLoss")}</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("verify.forestCarbon_title")}</span>
                    <p className="mt-0.5">{t("verify.forestCarbon")}</p>
                  </li>
                  <li>
                    <span className="text-white/90 font-medium">{t("verify.soilCarbon_title")}</span>
                    <p className="mt-0.5">{t("verify.soilCarbon")}</p>
                  </li>
                </ul>
              </section>
              <section>
                <h3 className="text-white/85 text-[13px] font-mono uppercase tracking-[0.15em] mb-1.5">{t("verify.limitationsTitle")}</h3>
                <p className="text-white/70 text-[15px] font-medium mb-2 mt-3">{t("verify.limOceanTitle")}</p>
                <ul className="space-y-1.5">
                  <li>{t("verify.lim_obis")}</li>
                  <li>{t("verify.lim_vents")}</li>
                  <li>{t("verify.lim_argo")}</li>
                  <li>{t("verify.lim_isa")}</li>
                  <li>{t("verify.lim_conflict")}</li>
                  <li>{t("verify.lim_oceansites")}</li>
                  <li>{t("verify.lim_onc")}</li>
                  <li>{t("verify.lim_noise")}</li>
                  <li>{t("verify.lim_chess")}</li>
                </ul>
                <p className="text-white/70 text-[15px] font-medium mb-2 mt-3">{t("verify.limLandTitle")}</p>
                <ul className="space-y-1.5">
                  <li>{t("verify.lim_miningFootprints")}</li>
                  <li>{t("verify.lim_tailings")}</li>
                  <li>{t("verify.lim_fires")}</li>
                  <li>{t("verify.lim_airQuality")}</li>
                  <li>{t("verify.lim_landslides")}</li>
                  <li>{t("verify.lim_dams")}</li>
                  <li>{t("verify.lim_surfaceWater")}</li>
                </ul>
              </section>
              <section>
                <h3 className="text-white/85 text-[13px] font-mono uppercase tracking-[0.15em] mb-1.5">{t("verify.reportTitle")}</h3>
                <p>{t("verify.reportText")}</p>
              </section>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-4 py-2 border-t border-white/10 flex-shrink-0">
          <p className="text-white/70 text-[13px] font-mono text-center">
            ISA · OBIS · ChEssBase · Argo · InterRidge · MarineRegions · UNESCO · OceanOPS · ONC · IIASA · BirdLife · UNEP-WCMC · NASA FIRMS · OpenAQ · Global Dam Watch · JRC
          </p>
        </div>
      </div>
    </div>
  );
}
