// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useState, useEffect, useMemo } from "react";
import { useTranslation, Trans } from "react-i18next";
import { useSearchParams } from "react-router-dom";
import { useMapStore } from "../store/mapStore";
import type { LayerId } from "../types/layers";
import { parseLayersParam } from "../utils/layersParam";
import { useLayerConfig } from "../utils/layerConfig";
import { loadMapState } from "../utils/mapState";
import { ProfilePicker } from "./ProfilePicker";
import { useStartupProfiles, applyProfile, applyMode, applyMenuExpansion, type StartupProfile } from "../utils/startupProfiles";

/** Sync the left panel section state so the right group is expanded on load. */
function setSectionState(seaOpen: boolean, landOpen: boolean) {
  try {
    const cur = JSON.parse(localStorage.getItem("abyssal_layers_panel") ?? "{}");
    localStorage.setItem("abyssal_layers_panel", JSON.stringify({ ...cur, seaOpen, landOpen }));
  } catch {}
}

export function WelcomeOverlay() {
  const { t, i18n } = useTranslation("tutorial");
  const setActiveLayers = useMapStore((s) => s.setActiveLayers);
  const activeLayers = useMapStore((s) => s.activeLayers);
  const enabledLayerIds = useMapStore((s) => s.enabledLayerIds);
  const [layerConfig] = useLayerConfig();
  const { profiles } = useStartupProfiles();
  const [searchParams, setSearchParams] = useSearchParams();
  // Skip overlay if user already has active layers (e.g. returning from a report page)
  const [visible, setVisible] = useState(() => activeLayers.size === 0);
  // Layer selection saved from the previous session (the app already persists
  // it as abyssal_map_state and Map3D restores it on mount). Read once, purely
  // to decide whether to offer "Continue where I left off".
  const savedLayers = useMemo(() => loadMapState()?.activeLayers ?? [], []);

  // Deep-link arrival (?focus= / ?fly= from a feature page or report): the
  // visitor is being sent to a specific object — don't ask them to pick a
  // mode. Apply the ocean defaults (every current deep-link target is a sea
  // feature) and let Map3D's focus handler add the object's own layer and
  // open its panel. Merge with any layers the focus handler already enabled
  // so we don't wipe them. Don't touch the ?focus/?fly params — Map3D
  // consumes and strips them itself.
  useEffect(() => {
    if (!visible) return;
    if (!searchParams.get("focus") && !searchParams.get("fly")) return;
    const next = new Set<LayerId>([
      ...useMapStore.getState().activeLayers,
      ...(layerConfig
        .filter(c => c.default_on && c.modes.includes("ocean"))
        .map(c => c.id) as LayerId[]),
    ]);
    setActiveLayers(next);
    setSectionState(true, false);
    setVisible(false);
  }, [searchParams, visible, layerConfig, setActiveLayers]);

  // Check ?layers= param on mount and on navigation (React Router aware)
  useEffect(() => {
    // ⛔ Validation lives in `utils/layersParam` and rejects the WHOLE list on
    // one unknown token. The old inline filter validated against LAYER_CONFIGS —
    // 38 of 44 sea layers — and silently dropped the rest, so a link naming a
    // real layer and a link with a typo produced the same quietly-smaller set.
    const ids = parseLayersParam(searchParams.get("layers"));
    if (!ids) return;
    // Activate layers and skip the overlay
    setActiveLayers(new Set(ids));
    setVisible(false);
    // Clean the param from the URL so it doesn't persist on refresh
    const next = new URLSearchParams(searchParams);
    next.delete("layers");
    setSearchParams(next, { replace: true });
  }, [searchParams, setActiveLayers, setSearchParams]);

  const finish = () => {
    setVisible(false);
    useMapStore.getState().setTutorialReady(true);
  };

  const onPickProfile = (p: StartupProfile) => {
    applyProfile(p, enabledLayerIds, setActiveLayers);
    finish();
  };

  const onPickMode = (mode: "ocean" | "land") => {
    applyMode(mode, layerConfig, enabledLayerIds, setActiveLayers);
    finish();
  };

  const onExploreAll = () => {
    // "Explore all" with no prior state = seed the ocean defaults so the map
    // isn't blank; otherwise keep whatever's already active (today's "continue").
    if (useMapStore.getState().activeLayers.size === 0) {
      applyMode("ocean", layerConfig, enabledLayerIds, setActiveLayers);
    }
    finish();
  };

  const onContinue = () => {
    // Map3D already restored the previous session's layers into the store on
    // mount (from abyssal_map_state, incl. auto-adding genuinely-new layers).
    // Keep that set and just reveal the map; only fall back to the raw saved
    // list if the restore effect hasn't landed yet.
    let current = [...useMapStore.getState().activeLayers] as LayerId[];
    if (current.length === 0 && savedLayers.length) {
      current = savedLayers.filter((id) => !enabledLayerIds || enabledLayerIds.has(id)) as LayerId[];
      setActiveLayers(new Set(current));
    }
    applyMenuExpansion(current);
    finish();
  };

  const onGuided = () => {
    // Seed the ocean defaults so the globe isn't blank behind the Discovery
    // panel — and stays populated if the user dismisses it without picking a
    // story. A chosen story's preset replaces activeLayers anyway.
    if (useMapStore.getState().activeLayers.size === 0) {
      applyMode("ocean", layerConfig, enabledLayerIds, setActiveLayers);
    }
    useMapStore.getState().setDiscoveryOpen(true);
    finish();
  };

  if (!visible) return null;

  return (
    <div className="absolute inset-0 z-overlay flex items-center justify-center bg-surface-dim transition-opacity duration-300 p-4">
      <div
        className="bg-surface-primary border border-white/10 rounded-2xl p-5 sm:p-8 max-w-lg sm:max-w-2xl w-full max-h-[90vh] overflow-y-auto custom-scrollbar text-center"
        onClick={e => e.stopPropagation()}
      >
        <h1 className="text-white text-xl font-semibold mb-2">{t("welcome.title")}</h1>
        <p className="text-white/65 text-xs uppercase tracking-widest font-mono mb-4">
          {t("welcome.tagline")}
        </p>
        <p className="text-white/80 text-sm leading-relaxed mb-4 sm:mb-6">
          <Trans
            i18nKey="welcome.description"
            t={t}
            components={{ bold: <span className="text-white/90" /> }}
          />
        </p>
        <div className="grid grid-cols-1 gap-2 sm:gap-3 mb-4 sm:mb-6 text-left">
          <Hint icon="layers" text={t("welcome.hint.layers")} />
          <Hint icon="pin" text={t("welcome.hint.pin")} />
        </div>

        {/* ── Layer mode selector ────────────────────────── */}
        <p className="text-white/70 text-[13px] mb-2 sm:mb-3 font-medium">{t("welcome.subtitle")}</p>
        <ProfilePicker
          profiles={profiles}
          lang={i18n.language}
          onPickProfile={onPickProfile}
          onPickMode={onPickMode}
          onExploreAll={onExploreAll}
          onGuided={onGuided}
          onContinue={savedLayers.length > 0 ? onContinue : undefined}
        />
        <p className="text-white/70 text-xs mt-3 leading-relaxed">
          {t("welcome.footer")}
        </p>
      </div>
    </div>
  );
}

const ICONS: Record<string, JSX.Element> = {
  layers: (
    <svg aria-hidden="true" className="w-5 h-5 text-white/70 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M6.429 9.75 2.25 12l4.179 2.25m0-4.5 5.571 3 5.571-3m-11.142 0L2.25 7.5 12 2.25l9.75 5.25-4.179 2.25m0 0L12 12.75 6.429 9.75m11.142 0 4.179 2.25L12 17.25 2.25 12l4.179-2.25m11.142 0 4.179 2.25L12 22.5l-9.75-5.25 4.179-2.25" />
    </svg>
  ),
  pin: (
    <svg aria-hidden="true" className="w-5 h-5 text-white/70 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M15 10.5a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 10.5c0 7.142-7.5 11.25-7.5 11.25S4.5 17.642 4.5 10.5a7.5 7.5 0 1 1 15 0Z" />
    </svg>
  ),
  discover: (
    <svg aria-hidden="true" className="w-5 h-5 text-white/70 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 18v-5.25m0 0a6.01 6.01 0 0 0 1.5-.189m-1.5.189a6.01 6.01 0 0 1-1.5-.189m3.75 7.478a12.06 12.06 0 0 1-4.5 0m3.75 2.383a14.406 14.406 0 0 1-3 0M14.25 18v-.192c0-.983.658-1.823 1.508-2.316a7.5 7.5 0 1 0-7.517 0c.85.493 1.509 1.333 1.509 2.316V18" />
    </svg>
  ),
};

function Hint({ icon, text }: { icon: string; text: string }) {
  return (
    <div className="flex items-start gap-3">
      {ICONS[icon]}
      <span className="text-white/70 text-[13px] leading-relaxed">{text}</span>
    </div>
  );
}
