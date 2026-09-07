// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// frontend/src/utils/startupProfiles.ts
import { useEffect, useState } from "react";
import type { LayerId } from "../types/layers";
import type { LayerConfig } from "./layerConfig";
import { deriveExpansion, SUBGROUP_KEYS } from "./menuTaxonomy";
import { useMapStore } from "../store/mapStore";
import { LAYER_VIEWS } from "./layerViews";

export interface StartupProfile {
  id: string;
  section: "ocean" | "land";
  order_idx: number;
  layers: string[];
  label: Record<string, string>;
  description: Record<string, string>;
  accent?: string | null;
  views?: Record<string, Record<string, string | number>>;
}

export function pickLocale(m: Record<string, string> | undefined, lang: string): string {
  if (!m) return "";
  return m[lang] ?? m[lang.split("-")[0]] ?? m.en ?? Object.values(m)[0] ?? "";
}

/** Fetch enabled startup profiles. profiles === null means the fetch failed —
 *  callers fall back to the legacy Ocean/Land buttons. */
export function useStartupProfiles(): { profiles: StartupProfile[] | null; loading: boolean } {
  const [profiles, setProfiles] = useState<StartupProfile[] | null>([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let alive = true;
    fetch("/api/v1/map/startup-profiles")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d: StartupProfile[]) => { if (alive) setProfiles(d); })
      .catch(() => { if (alive) setProfiles(null); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, []);
  return { profiles, loading };
}

function persistSubgroups(expand: string[]): void {
  try {
    const cur = JSON.parse(localStorage.getItem("abyssal_subgroups") ?? "{}");
    const next = { ...cur };
    for (const k of SUBGROUP_KEYS) next[k] = expand.includes(k);
    localStorage.setItem("abyssal_subgroups", JSON.stringify(next));
  } catch { /* ignore */ }
}

function persistSection(seaOpen: boolean, landOpen: boolean): void {
  try {
    const cur = JSON.parse(localStorage.getItem("abyssal_layers_panel") ?? "{}");
    localStorage.setItem("abyssal_layers_panel", JSON.stringify({ ...cur, seaOpen, landOpen }));
  } catch { /* ignore */ }
}

function applyExpansion(expand: string[], seaOpen: boolean, landOpen: boolean): void {
  persistSubgroups(expand);
  persistSection(seaOpen, landOpen);
  window.dispatchEvent(new CustomEvent("abyssal:expand-subgroups", {
    detail: { expand, collapseOthers: true, seaOpen, landOpen },
  }));
}

/** Expand only the menu categories containing `activeIds`, collapse the rest.
 *  Shared by startup profiles and Discovery guided stories. */
export function applyMenuExpansion(activeIds: Iterable<string>): void {
  const { expand, seaOpen, landOpen } = deriveExpansion(activeIds);
  applyExpansion(expand, seaOpen, landOpen);
}

/** Activate a curated profile: gate its layers, expand only their categories. */
export function applyProfile(
  profile: StartupProfile,
  enabledLayerIds: Set<string> | null,
  setActiveLayers: (s: Set<LayerId>) => void,
): void {
  const wanted = profile.layers.filter((id) => !enabledLayerIds || enabledLayerIds.has(id));
  setActiveLayers(new Set(wanted as LayerId[]));

  const views = profile.views ?? {};
  if (Object.keys(views).length) {
    const store = useMapStore.getState() as unknown as Record<string, (v: unknown) => void>;
    for (const [layerId, fields] of Object.entries(views)) {
      const reg = LAYER_VIEWS[layerId];
      if (!reg) continue;
      for (const f of reg) {
        const raw = (fields as Record<string, unknown>)[f.key];
        if (raw === undefined || raw === null || raw === "") continue;
        const val = f.kind === "number" ? Number(raw) : raw;
        // Guard against a malformed stored view (admin free-text) poisoning
        // display state — e.g. depth:"abc" → NaN → /v1/woa/.../NaN.png.
        if (f.kind === "number" && Number.isNaN(val as number)) continue;
        if (typeof store[f.setter] === "function") store[f.setter](val);
      }
    }
  }

  applyMenuExpansion(wanted);
}

/** Legacy "All ocean/land layers" — mode-filter over layerConfig defaults. */
export function applyMode(
  mode: string,
  layerConfig: LayerConfig[],
  enabledLayerIds: Set<string> | null,
  setActiveLayers: (s: Set<LayerId>) => void,
): void {
  const wanted = layerConfig
    .filter((c) => c.default_on && c.modes.includes(mode))
    .map((c) => c.id)
    .filter((id) => !enabledLayerIds || enabledLayerIds.has(id));
  setActiveLayers(new Set(wanted as LayerId[]));
  applyMenuExpansion(wanted);
}
