// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useState, useEffect, useRef, useCallback } from "react";
import { useTranslation } from "react-i18next";
import type { FeatureCollection } from "geojson";
import { useMapStore } from "../store/mapStore";
import type { LayerId } from "../types/layers";
import { analytics } from "../utils/analytics";
import LanguageSwitcher from "./LanguageSwitcher";
import { ViewsSwitcher } from "./ViewsSwitcher";
import {
  GroupHeader,
} from "./controls/rows";
import { ClaimsZonesSection } from "./controls/sections/ClaimsZonesSection";
import { LifeGeologySection } from "./controls/sections/LifeGeologySection";
import { AnalysisSection } from "./controls/sections/AnalysisSection";
import { SensorsSection } from "./controls/sections/SensorsSection";
import { OceanClimatologySection } from "./controls/sections/OceanClimatologySection";
import { InfrastructureSection } from "./controls/sections/InfrastructureSection";
import { UnderwaterNoiseSection } from "./controls/sections/UnderwaterNoiseSection";
import { LandCoreSection } from "./controls/sections/LandCoreSection";
import { HazardsMonitoringSection } from "./controls/sections/HazardsMonitoringSection";
import { WaterCarbonSection } from "./controls/sections/WaterCarbonSection";

interface Props {
  claimsData: FeatureCollection | null;
  // Ocean-currents history controls — wired here, rendered by the slider UI (Task 6).
  currentsMeta?: Record<string, import("./CurrentsLayer").CurrentsMeta> | null;
  currentsDate?: string | null;
  setCurrentsDate?: (d: string | null) => void;
  currentsPlaying?: boolean;
  setCurrentsPlaying?: (b: boolean) => void;
  // WOA Climatology meta — passed from Map3D once the layer first activates.
  woaMeta?: { variables: Array<{ key: string; label: string; units: string; vmin: number; vmax: number; cmap: string; baseline: string; depths: number[]; ramp?: Array<{ pos: number; hex: string }> }>; depths: number[] } | null;
  // Ocean Oxygen meta — passed from Map3D once the layer first activates.
  oxygenMeta?: { views: Array<{ key: string; label: string; units: string; vmin: number; vmax: number; cmap: string; ramp: Array<{ pos: number; hex: string }>; depths: number[]; diverging: boolean }>; depths: number[]; attribution: string } | null;
  // Ocean Carbon (GLODAP) meta — passed from Map3D once the layer first activates.
  carbonMeta?: { variables: Array<{ key: string; label: string; units: string; vmin: number; vmax: number; cmap: string; baseline: string; depths: number[]; ramp?: Array<{ pos: number; hex: string }> }>; depths: number[] } | null;
  // Surface Ocean CO₂ (SOCAT) meta — passed from Map3D once the layer first activates.
  co2Meta?: { variables: Array<{ key: string; label: string; units: string; vmin: number; vmax: number; cmap: string; ramp?: Array<{ pos: number; hex: string }> }>; decades: Array<{ index: number; label: string }> } | null;
}



export function Map3DControls({
  claimsData,
  currentsMeta,
  currentsDate,
  setCurrentsDate,
  currentsPlaying,
  setCurrentsPlaying,
  woaMeta,
  oxygenMeta,
  carbonMeta,
  co2Meta,
}: Props) {
  const {
    activeLayers, toggleLayer, disableAllLayers,
    plumeTraces, clearPlumeTraces, removePlumeTracesByPlatform,
    plumeHistoryQueue, clearPlumeHistory,
    hiddenContractors,
    ventStatusFilters,
    argoAlarmFilters,
    claimRiskFilters,
    iucnFilters,
    noiseRiskFilters,
    oceansitesNetworkFilters,
    arcticRiverSourceFilters,
    offshoreActivityFilters,
    offshoreActivityCountryFilters,
    chessHabitatFilters,
    chessPhylumFilters,
    fireConfidenceFilters,
    oncEovFilters,
    firesNearMiningOnly,
    tailingsRiskFilters,
    tailingsStatusFilters,
    aisShipTypeFilters,
    aisFlagFilters,
    deepdataStationContractorFilters,
    methaneSeepsFeatureTypeFilters,
    thawTypeFilters,
    thawCategoryFilters,
    permafrostSourceFilters,
    flyToLayer,
    selectedFeatures,
    mapTapCount,
    resetAllFilters,
  } = useMapStore();

  // ── localStorage-backed panel state ──────────────────────────────────────
  const loadPanelState = () => {
    try { return JSON.parse(localStorage.getItem("abyssal_layers_panel") ?? "{}"); } catch { return {}; }
  };
  const savePanelState = (patch: Record<string, unknown>) => {
    try {
      const cur = loadPanelState();
      localStorage.setItem("abyssal_layers_panel", JSON.stringify({ ...cur, ...patch }));
    } catch {}
  };

  const isMobile = () => window.matchMedia("(max-width: 767px)").matches;

  const mobile = isMobile();
  const [open,          setOpen]          = useState<boolean>(() => loadPanelState().open ?? !isMobile());
  const [seaOpen,        setSeaOpen]        = useState<boolean>(() => loadPanelState().seaOpen ?? !isMobile());
  const [landOpen,       setLandOpen]       = useState<boolean>(() => loadPanelState().landOpen ?? false);
  const [expandedFilter, setExpandedFilter] = useState<LayerId | null>(() => loadPanelState().expandedFilter ?? null);
  const [viewsOpen, setViewsOpen] = useState(false);

  // Persist any state change
  useEffect(() => { savePanelState({ open }); }, [open]);
  useEffect(() => { savePanelState({ seaOpen }); }, [seaOpen]);
  useEffect(() => { savePanelState({ landOpen }); }, [landOpen]);
  useEffect(() => { savePanelState({ expandedFilter }); }, [expandedFilter]);

  // Allow a curated view (e.g. WelcomeOverlay presets) to drive which top-level
  // section (Sea / Land) is open, alongside the sub-group expansion above.
  useEffect(() => {
    const onExpand = (e: Event) => {
      const d = (e as CustomEvent).detail;
      if (d && typeof d === "object" && !Array.isArray(d)) {
        if (typeof d.seaOpen === "boolean") setSeaOpen(d.seaOpen);
        if (typeof d.landOpen === "boolean") setLandOpen(d.landOpen);
      }
    };
    window.addEventListener("abyssal:expand-subgroups", onExpand);
    return () => window.removeEventListener("abyssal:expand-subgroups", onExpand);
  }, []);

  // Fetch distinct ISA contractors (for vessel-events filter pills)
  // Auto-close on mobile when a detail panel opens — prevents both panels covering the map
  useEffect(() => {
    if (isMobile() && selectedFeatures.length > 0) setOpen(false);
  }, [selectedFeatures]);

  // Auto-close on mobile when user taps the map directly
  useEffect(() => {
    if (mapTapCount === 0) return;
    if (isMobile()) setOpen(false);
  }, [mapTapCount]);

  // Fetch the list of countries (sovereigns) with offshore-activity coverage
  // — populated lazily only when the user opens the filter chevron.
  const [offshoreCountries, setOffshoreCountries] = useState<{ sovereign: string; count: number }[] | null>(null);
  useEffect(() => {
    if (expandedFilter !== "offshore-activities" || offshoreCountries !== null) return;
    const API = import.meta.env.VITE_API_BASE_URL ?? "";
    fetch(`${API}/api/v2/spatial/offshore-activities/countries`)
      .then(r => r.ok ? r.json() : [])
      .then((rows: { sovereign: string; count: number }[]) => setOffshoreCountries(rows ?? []))
      .catch(() => setOffshoreCountries([]));
  }, [expandedFilter, offshoreCountries]);

  // ── Undo toast for filter reset ────────────────────────────────────────
  const [undoSnapshot, setUndoSnapshot] = useState<Record<string, Set<string>> | null>(null);
  const undoTimerRef = useRef<ReturnType<typeof setTimeout>>();

  const handleResetFilters = useCallback(() => {
    // Snapshot current filter state before resetting
    const snapshot: Record<string, Set<string>> = {
      claimRiskFilters: new Set(claimRiskFilters),
      ventStatusFilters: new Set(ventStatusFilters),
      argoAlarmFilters: new Set(argoAlarmFilters),
      hiddenContractors: new Set(hiddenContractors),
      iucnFilters: new Set(iucnFilters),
      noiseRiskFilters: new Set(noiseRiskFilters),
      oceansitesNetworkFilters: new Set(oceansitesNetworkFilters),
      chessHabitatFilters: new Set(chessHabitatFilters),
      chessPhylumFilters: new Set(chessPhylumFilters),
      fireConfidenceFilters: new Set(fireConfidenceFilters),
      oncEovFilters: new Set(oncEovFilters),
      tailingsRiskFilters: new Set(tailingsRiskFilters),
      tailingsStatusFilters: new Set(tailingsStatusFilters),
      aisShipTypeFilters: new Set(aisShipTypeFilters),
      aisFlagFilters: new Set(aisFlagFilters),
      offshoreActivityFilters: new Set(offshoreActivityFilters),
      offshoreActivityCountryFilters: new Set(offshoreActivityCountryFilters),
    };
    setUndoSnapshot(snapshot);
    resetAllFilters();
    clearTimeout(undoTimerRef.current);
    undoTimerRef.current = setTimeout(() => setUndoSnapshot(null), 6000);
  }, [claimRiskFilters, ventStatusFilters, argoAlarmFilters, hiddenContractors, iucnFilters, noiseRiskFilters, oceansitesNetworkFilters, chessHabitatFilters, chessPhylumFilters, fireConfidenceFilters, oncEovFilters, firesNearMiningOnly, tailingsRiskFilters, tailingsStatusFilters, aisShipTypeFilters, aisFlagFilters, offshoreActivityFilters, offshoreActivityCountryFilters, deepdataStationContractorFilters, resetAllFilters]);

  const handleUndo = useCallback(() => {
    if (!undoSnapshot) return;
    useMapStore.setState(undoSnapshot);
    setUndoSnapshot(null);
    clearTimeout(undoTimerRef.current);
  }, [undoSnapshot]);

  const hasActiveFilters =
    claimRiskFilters.size > 0 ||
    ventStatusFilters.size < 3 ||
    argoAlarmFilters.size > 0 ||
    hiddenContractors.size > 0 ||
    iucnFilters.size > 0 ||
    noiseRiskFilters.size > 0 ||
    oceansitesNetworkFilters.size > 0 ||
    chessHabitatFilters.size > 0 ||
    chessPhylumFilters.size > 0 ||
    fireConfidenceFilters.size > 0 ||
    oncEovFilters.size > 0 ||
    firesNearMiningOnly ||
    tailingsRiskFilters.size > 0 ||
    tailingsStatusFilters.size > 0 ||
    deepdataStationContractorFilters.size > 0 ||
    arcticRiverSourceFilters.size > 0 ||
    methaneSeepsFeatureTypeFilters.size > 0 ||
    thawTypeFilters.size > 0 ||
    thawCategoryFilters.size > 0 ||
    permafrostSourceFilters.size > 0;

  const { t } = useTranslation(["panels", "common"]);

  const toggle = (id: LayerId) => {
    toggleLayer(id);
    analytics.toggleLayer(id, !activeLayers.has(id));
  };

  const toggleExpand = (id: LayerId) =>
    setExpandedFilter(f => f === id ? null : id);

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className={`z-panel bg-[rgba(10,14,20,0.92)] border border-white/[0.08] text-white/70 hover:text-white text-xs font-mono uppercase tracking-wider px-3 py-2 min-h-[44px] rounded transition-colors ${
          mobile
            ? "fixed bottom-4 right-1/2 mr-1.5"
            : "absolute top-4 left-4"
        }`}
      >
        {t("controls.header.openLayers")}
      </button>
    );
  }

  return (
    <div
      data-panel="layers"
      className={`z-panel bg-[rgba(10,14,20,0.95)] border border-white/[0.08] rounded flex flex-col overflow-hidden ${
        mobile
          ? "fixed bottom-0 left-0 right-0 max-h-[60dvh] rounded-t-lg border-b-0 animate-slide-up"
          : "absolute top-4 left-4 w-72 max-h-[calc(100vh-7rem)]"
      }`}
      style={mobile ? { paddingBottom: "env(safe-area-inset-bottom)" } : undefined}
    >
      {/* Drag handle (mobile) */}
      {mobile && (
        <div className="flex justify-center pt-2 pb-1 shrink-0">
          <div className="w-8 h-1 rounded-full bg-white/20" />
        </div>
      )}
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-white/[0.06] shrink-0">
        <div className="flex items-center gap-2">
          <span data-tutorial="layers-panel" className="text-white/75 text-[10px] font-mono uppercase tracking-widest">{t("controls.layersHeading")}</span>
          {/* Action chips — bordered so they read as buttons, not as part of
              the heading ("LAYERS LAYERS OFF" ran together as one phrase). */}
          <button
            onClick={() => setViewsOpen(true)}
            title={t("controls.header.views")}
            className="text-white/60 hover:text-cyan-300 text-[9px] font-mono uppercase tracking-widest transition-colors border border-white/10 hover:border-cyan-400/40 rounded px-1.5 py-0.5"
          >
            {t("controls.header.views")}
          </button>
          {hasActiveFilters && (
            <button
              onClick={handleResetFilters}
              title={t("common:tooltips.resetAllFilters")}
              aria-label={t("common:tooltips.resetAllFilters")}
              className="text-white/60 hover:text-red-400 text-[9px] font-mono uppercase tracking-widest transition-colors border border-white/10 hover:border-red-400/40 rounded px-1.5 py-0.5"
            >
              {t("common:actions.reset")}
            </button>
          )}
          {activeLayers.size > 0 && (
            <button
              onClick={disableAllLayers}
              title={t("common:tooltips.turnOffAllLayers")}
              aria-label={t("common:tooltips.turnOffAllLayers")}
              className="text-white/60 hover:text-red-400 text-[9px] font-mono uppercase tracking-widest transition-colors border border-white/10 hover:border-red-400/40 rounded px-1.5 py-0.5"
            >
              {t("controls.header.layersOff")}
            </button>
          )}
          {(plumeTraces.length > 0 || plumeHistoryQueue.length > 0) && (
            <button
              onClick={() => { clearPlumeTraces(); clearPlumeHistory(); }}
              title={t("common:tooltips.hideAllPlumes")}
              aria-label={t("common:tooltips.hideAllPlumes")}
              className="text-white/60 hover:text-red-400 text-[9px] font-mono uppercase tracking-widest transition-colors border border-white/10 hover:border-red-400/40 rounded px-1.5 py-0.5"
            >
              {t("controls.header.plumesOff")}
            </button>
          )}
        </div>
        <div className="flex items-center gap-2">
          <LanguageSwitcher />
          <button onClick={() => setOpen(false)} aria-label={t("common:tooltips.closeLayersPanel")} className="text-white/65 hover:text-white text-sm leading-none transition-colors min-w-[44px] min-h-[44px] flex items-center justify-center -mr-2">×</button>
        </div>
      </div>

      <div className="overflow-y-auto custom-scrollbar flex-1 px-2 py-1 space-y-px" style={{ maskImage: "linear-gradient(to bottom, black calc(100% - 32px), transparent 100%)", WebkitMaskImage: "linear-gradient(to bottom, black calc(100% - 32px), transparent 100%)" }}>

        {/* ── Active drift plumes ──────────────────────────────────────────
            One traced float fans out to many profile traces, so group back to
            the float (platformId) the user opened. Per-float × + clear-all. */}
        {plumeTraces.length > 0 && (() => {
          const byFloat = new Map<string, number>();
          for (const tr of plumeTraces) {
            const key = tr.platformId ?? tr.argoId;
            byFloat.set(key, (byFloat.get(key) ?? 0) + 1);
          }
          return (
            <div className="mb-1 rounded bg-white/[0.03] border border-white/[0.06] px-2 py-1.5">
              <div className="flex items-center justify-between mb-1">
                <span className="text-[10px] font-mono uppercase tracking-widest text-white/65">
                  {t("plumes.activeDriftHeading")} ({byFloat.size})
                </span>
                <button
                  onClick={clearPlumeTraces}
                  className="text-[10px] font-mono uppercase tracking-widest text-white/60 hover:text-red-400 transition-colors"
                >
                  {t("plumes.clearAll")}
                </button>
              </div>
              <ul className="space-y-0.5">
                {[...byFloat.entries()].map(([floatId, count]) => (
                  <li key={floatId} className="flex items-center gap-2 text-xs text-white/85">
                    <span className="w-2 h-2 rounded-sm shrink-0" style={{ backgroundColor: "rgb(214,164,64)" }} />
                    <span className="font-mono flex-1 truncate">{floatId}</span>
                    <span className="text-white/60 font-mono text-[10px]">{t("plumes.segments", { n: count })}</span>
                    <button
                      onClick={() => removePlumeTracesByPlatform(floatId)}
                      title={t("plumes.removeOne", { id: floatId })}
                      aria-label={t("plumes.removeOne", { id: floatId })}
                      className="text-white/65 hover:text-red-400 transition-colors min-w-[24px] min-h-[24px] flex items-center justify-center leading-none"
                    >
                      ×
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          );
        })()}

        {/* ── Sea Data ─────────────────────────────────────────────────── */}
        <GroupHeader
          label={t("controls.seaData")}
          expanded={seaOpen}
          onToggle={() => setSeaOpen(v => !v)}
        />

        {seaOpen && (
          <div className="pl-2 border-l border-white/[0.06]">

            <ClaimsZonesSection claimsData={claimsData} expandedFilter={expandedFilter} toggleExpand={toggleExpand} toggle={toggle} flyToLayer={flyToLayer} />
            {/* ── Life & Geology ─────────────────────────────────────── */}
            <LifeGeologySection expandedFilter={expandedFilter} toggleExpand={toggleExpand} toggle={toggle} flyToLayer={flyToLayer} />

            {/* ── Analysis ──────────────────────────────────────────── */}
            <AnalysisSection expandedFilter={expandedFilter} setExpandedFilter={setExpandedFilter} toggleExpand={toggleExpand} toggle={toggle} flyToLayer={flyToLayer} />

            {/* ── Sensors & Monitoring ──────────────────────────────── */}
            <SensorsSection expandedFilter={expandedFilter} toggleExpand={toggleExpand} toggle={toggle} flyToLayer={flyToLayer} currentsMeta={currentsMeta} currentsDate={currentsDate} setCurrentsDate={setCurrentsDate} currentsPlaying={currentsPlaying} setCurrentsPlaying={setCurrentsPlaying} />

            {/* ── Ocean Climatology ─────────────────────────────────── */}
            <OceanClimatologySection expandedFilter={expandedFilter} setExpandedFilter={setExpandedFilter} toggleExpand={toggleExpand} toggle={toggle} flyToLayer={flyToLayer} woaMeta={woaMeta} oxygenMeta={oxygenMeta} carbonMeta={carbonMeta} co2Meta={co2Meta} />

            {/* ── Infrastructure ────────────────────────────────────── */}
            {/* ── Infrastructure ────────────────────────────────────── */}
            <InfrastructureSection expandedFilter={expandedFilter} toggleExpand={toggleExpand} toggle={toggle} flyToLayer={flyToLayer} />

            {/* ── Underwater Noise ──────────────────────────────────── */}
            <UnderwaterNoiseSection expandedFilter={expandedFilter} toggleExpand={toggleExpand} toggle={toggle} flyToLayer={flyToLayer} />

          </div>
        )}

        {/* ── Land Data ────────────────────────────────────────────────── */}
        <GroupHeader
          label={t("controls.landData")}
          expanded={landOpen}
          onToggle={() => setLandOpen(v => !v)}
        />

        {landOpen && (
          <div className="pl-2 border-l border-white/[0.06]">
            <LandCoreSection toggle={toggle} flyToLayer={flyToLayer} />

            <HazardsMonitoringSection expandedFilter={expandedFilter} toggleExpand={toggleExpand} toggle={toggle} flyToLayer={flyToLayer} />

            <WaterCarbonSection toggle={toggle} flyToLayer={flyToLayer} />
          </div>
        )}

      </div>

      {/* Undo toast for filter reset */}
      {undoSnapshot && (
        <div className="absolute bottom-3 left-3 right-3 z-overlay flex items-center justify-between bg-[rgba(10,14,20,0.95)] border border-white/[0.08] rounded px-3 py-1.5 animate-fade-in">
          <span className="text-white/70 text-xs font-mono">{t("controls.header.filtersReset")}</span>
          <button
            onClick={handleUndo}
            aria-label={t("common:tooltips.undoFilterReset")}
            className="text-white/80 hover:text-white/95 text-xs font-mono uppercase tracking-wider transition-colors"
          >
            {t("common:actions.undo")}
          </button>
        </div>
      )}
      {viewsOpen && <ViewsSwitcher onClose={() => setViewsOpen(false)} />}
    </div>
  );
}
