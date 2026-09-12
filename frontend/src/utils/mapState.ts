// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import type { LayerId } from "../types/layers";
import { VALID_LAYER_IDS } from "./layersParam";

const MAP_STATE_KEY = "abyssal_map_state";

export interface PersistedViewState {
  longitude: number;
  latitude: number;
  zoom: number;
  pitch: number;
  bearing: number;
}

interface PersistedMapState {
  viewState: PersistedViewState;
  activeLayers: LayerId[];
  knownLayers?: LayerId[]; // all layer IDs known at save time — used to detect genuinely new layers
}

export function loadMapState(): PersistedMapState | null {
  try {
    const raw = localStorage.getItem(MAP_STATE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as PersistedMapState;
    // Basic sanity check
    if (
      typeof parsed.viewState?.zoom !== "number" ||
      !Array.isArray(parsed.activeLayers)
    ) return null;
    // Unlike a URL's `?layers=`, a retired id found here means "this layer
    // existed on the visitor's last visit and doesn't anymore" — drop it
    // quietly rather than rejecting the whole saved state (which would also
    // throw away their camera position and, previously, could resurrect a
    // dead id into `activeLayers` forever since nothing else ever pruned it).
    parsed.activeLayers = parsed.activeLayers.filter((id) => VALID_LAYER_IDS.has(id));
    if (parsed.knownLayers) {
      parsed.knownLayers = parsed.knownLayers.filter((id) => VALID_LAYER_IDS.has(id));
    }
    return parsed;
  } catch {
    return null;
  }
}

const RETURN_FLY_KEY = "abyssal_return_fly";

/** Called from Map3D's unmount cleanup — uses latestStateRef, not debounced localStorage. */
export function saveReturnFlyFromViewState(lon: number, lat: number, zoom: number): void {
  try {
    localStorage.setItem(RETURN_FLY_KEY, JSON.stringify({ lon, lat, zoom }));
  } catch {}
}

export function consumeReturnFly(): { lon: number; lat: number; zoom: number } | null {
  try {
    const raw = localStorage.getItem(RETURN_FLY_KEY);
    if (!raw) return null;
    localStorage.removeItem(RETURN_FLY_KEY);
    const p = JSON.parse(raw) as { lon: number; lat: number; zoom: number };
    if (typeof p.lon !== "number" || typeof p.lat !== "number") return null;
    return p;
  } catch { return null; }
}

export function saveMapState(viewState: Record<string, unknown>, activeLayers: Set<LayerId>, allLayerIds: LayerId[]): void {
  try {
    const state: PersistedMapState = {
      viewState: {
        longitude: viewState.longitude as number,
        latitude:  viewState.latitude  as number,
        zoom:      viewState.zoom      as number,
        pitch:     viewState.pitch     as number,
        bearing:   viewState.bearing   as number,
      },
      activeLayers: [...activeLayers],
      knownLayers: allLayerIds,
    };
    localStorage.setItem(MAP_STATE_KEY, JSON.stringify(state));
  } catch {}
}
