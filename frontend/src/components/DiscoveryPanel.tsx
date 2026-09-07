// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { useMapStore } from "../store/mapStore";
import type { LayerId } from "../types/layers";
import { applyMenuExpansion } from "../utils/startupProfiles";

/* ── Preset meta (structural fields only — text lives in panels.json) ── */

interface DiscoveryPresetMeta {
  id: string;       // kebab-case — used for analytics + React key
  i18nKey: string;  // camelCase — matches panels.discovery.presets.<i18nKey>.*
  icon: string;
  mode: "ocean" | "land";
  layers: LayerId[];
  filters?: { key: string; values: string[] }[];
  view: { longitude: number; latitude: number; zoom: number };
}

// Order: 5 ocean stories first, 4 land stories second — DO NOT reshuffle.
const PRESETS_META: DiscoveryPresetMeta[] = [
  // ── Ocean ──────────────────────────────────────────────────────────
  {
    id: "vent-mining-clash",
    i18nKey: "ventMiningClash",
    icon: "🌋",
    mode: "ocean",
    layers: ["contracts", "hydrothermal-vents", "biodiversity-hotspots"],
    view: { longitude: -45, latitude: 14, zoom: 8 },
  },
  {
    id: "ccz-scale",
    i18nKey: "cczScale",
    icon: "🌊",
    mode: "ocean",
    layers: ["contracts", "reserved-areas", "apeis", "seamounts"],
    view: { longitude: -145, latitude: 12, zoom: 3.8 },
  },
  {
    id: "plume-risk",
    i18nKey: "plumeRisk",
    icon: "🌫️",
    mode: "ocean",
    layers: ["contracts", "argo", "biodiversity-hotspots"],
    view: { longitude: -130, latitude: 10, zoom: 5 },
  },
  {
    id: "monitoring-gaps",
    i18nKey: "monitoringGaps",
    icon: "🔬",
    mode: "ocean",
    layers: ["monitoring-density", "contracts", "reserved-areas"],
    view: { longitude: -138, latitude: 11, zoom: 4.2 },
  },
  {
    id: "north-sea-density",
    i18nKey: "northSeaDensity",
    icon: "🛢️",
    mode: "ocean",
    layers: ["offshore-activities", "submarine-cables", "ports"],
    view: { longitude: 3, latitude: 56, zoom: 5.5 },
  },
  // ── Land ───────────────────────────────────────────────────────────
  {
    id: "deforestation-ring",
    i18nKey: "deforestationRing",
    icon: "🌳",
    mode: "land",
    layers: ["mining-footprints", "forest-loss"],
    view: { longitude: -50, latitude: -6, zoom: 6 },
  },
  {
    id: "water-stress-mines",
    i18nKey: "waterStressMines",
    icon: "💧",
    mode: "land",
    layers: ["mining-footprints", "water-risk"],
    view: { longitude: -69, latitude: -24, zoom: 5.5 },
  },
  {
    id: "tailings-danger",
    i18nKey: "tailingsDanger",
    icon: "⚠️",
    mode: "land",
    layers: ["tailings", "mining-footprints"],
    filters: [{ key: "tailingsRisk", values: ["Extreme", "Very High", "High"] }],
    view: { longitude: -44, latitude: -20, zoom: 7 },
  },
  {
    id: "fire-season",
    i18nKey: "fireSeason",
    icon: "🔥",
    mode: "land",
    layers: ["fires", "mining-footprints"],
    filters: [],
    view: { longitude: 120, latitude: -2, zoom: 5 },
  },
];

/* ── Component ────────────────────────────────────────────────────────── */

interface DiscoveryPanelProps {
  onFlyTo: (lon: number, lat: number, zoom: number) => void;
}

export function DiscoveryPanel({ onFlyTo }: DiscoveryPanelProps) {
  const { t } = useTranslation("panels");
  const open = useMapStore(s => s.discoveryOpen);
  const setOpen = useMapStore(s => s.setDiscoveryOpen);
  const [activeMeta, setActiveMeta] = useState<DiscoveryPresetMeta | null>(null);

  const setActiveLayers = useMapStore(s => s.setActiveLayers);
  const resetAllFilters = useMapStore(s => s.resetAllFilters);
  const toggleFireConfidenceFilter = useMapStore(s => s.toggleFireConfidenceFilter);
  const toggleClaimRisk = useMapStore(s => s.toggleClaimRisk);
  const toggleTailingsRiskFilter = useMapStore(s => s.toggleTailingsRiskFilter);
  const enabledLayerIds = useMapStore(s => s.enabledLayerIds);

  // Helper: preset-scoped t() shorthand
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const pt = (i18nKey: string, suffix: string): string =>
    (t as any)(`discovery.presets.${i18nKey}.${suffix}`);

  const applyPreset = useCallback(
    (meta: DiscoveryPresetMeta) => {
      // 1. Reset filters to clean state
      resetAllFilters();

      // 2. Enable exactly the layers this preset needs (gated by admin-enabled layers)
      const gated = meta.layers.filter((id) => !enabledLayerIds || enabledLayerIds.has(id));
      setActiveLayers(new Set(gated));

      // 3. Apply filters if specified
      if (meta.filters) {
        for (const f of meta.filters) {
          for (const v of f.values) {
            if (f.key === "fireConfidence") toggleFireConfidenceFilter(v);
            if (f.key === "claimRisk") toggleClaimRisk(v);
            if (f.key === "tailingsRisk") toggleTailingsRiskFilter(v);
          }
        }
      }

      // 3b. Progressive disclosure: expand only the categories this preset's layers live in
      applyMenuExpansion(gated);

      // 4. Fly to the target location
      onFlyTo(meta.view.longitude, meta.view.latitude, meta.view.zoom);

      // 5. Show the story card and close menu
      setActiveMeta(meta);
      setOpen(false);
    },
    [onFlyTo, setActiveLayers, resetAllFilters, toggleFireConfidenceFilter, toggleClaimRisk, toggleTailingsRiskFilter, enabledLayerIds],
  );

  // Always show all presets — ocean-first order is encoded in PRESETS_META
  const visible = PRESETS_META;

  return (
    <>
      {/* ── Story Card (shown after clicking a preset) ──────────────── */}
      {activeMeta && (
        <div className="fixed top-16 right-4 sm:absolute sm:top-auto sm:bottom-36 sm:right-96 z-overlay w-[calc(100vw-2rem)] sm:w-80 bg-surface-overlay border border-white/15 rounded-xl shadow-2xl backdrop-blur-sm overflow-hidden pointer-events-auto animate-fade-in">
          <div className="px-4 pt-3 pb-2 border-b border-white/10 flex items-start justify-between gap-2">
            <div className="flex items-center gap-2 min-w-0">
              <span className="text-lg shrink-0">{activeMeta.icon}</span>
              <h3 className="text-white/95 text-base font-semibold truncate">{pt(activeMeta.i18nKey, "title")}</h3>
            </div>
            <button
              onClick={() => setActiveMeta(null)}
              aria-label={t("discovery.ariaCloseStory")}
              className="text-white/65 hover:text-white text-base leading-none shrink-0 -m-2 p-2 transition-colors"
            >
              ×
            </button>
          </div>
          <div className="px-4 py-3">
            <p className="text-white/85 text-[15px] leading-relaxed">{pt(activeMeta.i18nKey, "story")}</p>
          </div>
          {(() => {
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const steps = ((t as any)(`discovery.presets.${activeMeta.i18nKey}.nextSteps`, { returnObjects: true }) as string[] | undefined) ?? [];
            return steps.length > 0 ? (
              <div className="px-4 pb-3 border-t border-white/5 pt-2.5">
                <p className="text-white/75 text-[13px] uppercase tracking-wider mb-2">{t("discovery.tryNextLabel")}</p>
                <ul className="space-y-1.5">
                  {steps.map((step, i) => (
                    <li key={i} className="text-white/85 text-[14px] leading-snug flex gap-1.5">
                      <span className="text-white/75 shrink-0">›</span>
                      <span>{step}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null;
          })()}
        </div>
      )}

      {/* ── Preset List (expandable) — finding-led story cards ──────── */}
      {open && (
        <div className="fixed top-16 right-4 sm:absolute sm:top-auto sm:bottom-24 sm:right-4 z-overlay w-[calc(100vw-2rem)] sm:w-[21rem] bg-surface-primary border border-white/15 rounded-xl shadow-2xl backdrop-blur-sm overflow-hidden pointer-events-auto animate-fade-in">
          <div className="px-3.5 py-2 border-b border-white/10 flex items-center justify-between">
            <span className="text-white/80 text-[12px] font-mono uppercase tracking-widest">{t("discovery.headerLabel")}</span>
            <button
              onClick={() => setOpen(false)}
              aria-label={t("discovery.ariaCloseMenu")}
              className="text-white/65 hover:text-white text-sm leading-none -m-2 p-2 transition-colors"
            >
              ×
            </button>
          </div>
          <div className="py-1 max-h-[26rem] overflow-y-auto custom-scrollbar">
            {visible.map((meta, idx) => (
              <button
                key={meta.id}
                onClick={() => applyPreset(meta)}
                className={`w-full px-3.5 py-2.5 text-left hover:bg-white/5 transition-colors flex items-start gap-2.5 group ${
                  /* breathing line between the ocean and land groups */
                  idx > 0 && meta.mode !== visible[idx - 1].mode ? "border-t border-white/10 mt-1 pt-3" : ""
                }`}
              >
                <span className="text-base shrink-0 mt-px">{meta.icon}</span>
                <div className="min-w-0">
                  <p className="text-white/95 text-[14px] font-semibold leading-tight group-hover:text-white transition-colors flex items-center gap-1.5">
                    <span className="truncate">{pt(meta.i18nKey, "title")}</span>
                    <span className={`shrink-0 text-[9px] font-mono uppercase tracking-wider px-1 py-px rounded-sm ${
                      meta.mode === "ocean"
                        ? "text-cyan-400/70 bg-cyan-500/10"
                        : "text-emerald-400/70 bg-emerald-500/10"
                    }`}>
                      {meta.mode === "ocean" ? t("discovery.modeOcean") : t("discovery.modeLand")}
                    </span>
                  </p>
                  <p className="text-white/75 text-[12.5px] leading-snug mt-0.5 line-clamp-2">
                    {pt(meta.i18nKey, "finding")}
                  </p>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* ── Toggle Button ───────────────────────────────────────────── */}
      <button
        onClick={() => { setOpen(!open); if (activeMeta) setActiveMeta(null); }}
        className={`fixed top-4 right-4 sm:absolute sm:top-auto sm:bottom-10 sm:right-4 z-panel flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
          open
            ? "bg-amber-500/20 border border-amber-500/40 text-amber-300"
            : "bg-surface-dim border border-amber-500/25 text-amber-300/70 hover:text-amber-200 hover:border-amber-500/40"
        }`}
        aria-label={t("discovery.ariaOpenMenu")}
      >
        <svg aria-hidden="true" className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 18v-5.25m0 0a6.01 6.01 0 0 0 1.5-.189m-1.5.189a6.01 6.01 0 0 1-1.5-.189m3.75 7.478a12.06 12.06 0 0 1-4.5 0m3.75 2.383a14.406 14.406 0 0 1-3 0M14.25 18v-.192c0-.983.658-1.823 1.508-2.316a7.5 7.5 0 1 0-7.517 0c.85.493 1.509 1.333 1.509 2.316V18" />
        </svg>
        {open ? t("discovery.closeButton") : t("discovery.openButton")}
      </button>
    </>
  );
}
