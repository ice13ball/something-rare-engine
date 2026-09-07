// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { ProfilePicker } from "./ProfilePicker";
import { useMapStore } from "../store/mapStore";
import { useLayerConfig } from "../utils/layerConfig";
import {
  useStartupProfiles, applyProfile, applyMode, type StartupProfile,
} from "../utils/startupProfiles";

/** Reopenable "Views" switcher — a popover version of the two-tier
 *  ProfilePicker used at first-visit (WelcomeOverlay), so users can re-apply
 *  a curated profile or an ocean/land mode at any time from the layers panel
 *  header. Profile-only (no guided tour entry point). */
export function ViewsSwitcher({ onClose }: { onClose: () => void }) {
  const { i18n } = useTranslation();
  const { profiles } = useStartupProfiles();
  const [layerConfig] = useLayerConfig();
  const setActiveLayers = useMapStore((s) => s.setActiveLayers);
  const enabledLayerIds = useMapStore((s) => s.enabledLayerIds);

  const pick = (p: StartupProfile) => { applyProfile(p, enabledLayerIds, setActiveLayers); onClose(); };
  const mode = (m: "ocean" | "land") => { applyMode(m, layerConfig, enabledLayerIds, setActiveLayers); onClose(); };

  return (
    <div
      className="fixed inset-0 z-overlay flex items-center justify-center p-4"
      role="dialog"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <button
        className="absolute inset-0 bg-surface-overlay cursor-default"
        aria-label="Close"
        onClick={onClose}
      />
      <div className="relative bg-[#0d1117] border border-white/10 rounded-xl shadow-2xl w-full max-w-sm p-5">
        <ProfilePicker
          profiles={profiles}
          lang={i18n.language}
          onPickProfile={pick}
          onPickMode={mode}
          onExploreAll={onClose}
        />
      </div>
    </div>
  );
}
