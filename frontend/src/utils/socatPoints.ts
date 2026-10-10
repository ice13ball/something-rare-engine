// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { rampColor } from "../components/map3d/colors";
import { GLODAP_NO_VALUE_RGBA, type RGBA, type RampMeta } from "./glodapPoints";

const API = import.meta.env.VITE_API_BASE_URL ?? "";

export const SOCAT_POINTS_ID = "socat-points";
/** Layer name `LayerUnavailableNotice` shows when /meta or the tiles fail. */
export const SOCAT_FAILED_NAME = "SOCAT Measurements";
/** Deepest tile the server makes (deck.gl overzooms past it); == backend MAX_ZOOM. */
export const SOCAT_TILE_MAX_ZOOM = 12;

/** The part of `/v1/socat/meta` the map reads. `tile_version` is null after a purge (nothing built). */
export type SocatMeta = {
  tile_version: string | null; year_min: number; year_max: number; point_min_zoom: number;
};

/**
 * Tile feature properties of `/v1/socat/tiles`. At z >= 9 one feature = one (UTC year, 256x256 cell):
 * e/n of the cell-year's first observation, k observations, c cruises, q cell (cy*256+cx), f/t/s means
 * scaled to integers (fco2 x10, sst x100, salinity x100). LOD pieces (z <= 8): e, n0, k (= n_obs), y.
 */
export type SocatProps = {
  e: string; n?: number; n0?: number; k?: number; c?: number; q?: number;
  f?: number; t?: number; s?: number; y: number;
};

/** Same grey as GLODAP's "no value" points. */
export const SOCAT_NO_VALUE_RGBA: RGBA = GLODAP_NO_VALUE_RGBA;
/** `density` view: one neutral colour whatever the values. */
export const SOCAT_NEUTRAL_RGBA: RGBA = [96, 165, 250, 200];
const POINT_ALPHA = 235;

/** Decade index as in the field's selector (0 = 1970s ... 5 = 2020s); -1 outside 1970-2029. */
export const decadeOf = (y: number): number => (y >= 1970 && y <= 2029 ? Math.floor((y - 1970) / 10) : -1);

/** Unscaled value of the selected variable, or null when absent. ⛔ `== null`, never falsiness: 0 °C and salinity 0 are values. */
export function socatValue(p: SocatProps, variable: string): number | null {
  const raw = variable === "fco2" ? p.f : variable === "sst" ? p.t : variable === "salinity" ? p.s : undefined;
  if (raw == null) return null;
  return raw / (variable === "fco2" ? 10 : 100);
}

export function socatColor(p: SocatProps, variable: string, decade: number, vm?: RampMeta): RGBA {
  // Density is per decade too (fco2_count_nobs_decade): outside the selected decade / before 1970 it is grey.
  if (decadeOf(p.y) !== decade) return GLODAP_NO_VALUE_RGBA;
  if (variable === "density") return SOCAT_NEUTRAL_RGBA;
  const v = socatValue(p, variable);
  if (v === null || !vm?.ramp?.length) return GLODAP_NO_VALUE_RGBA;
  return rampColor(v, vm.vmin, vm.vmax, vm.ramp, POINT_ALPHA);
}

/** What Surface Ocean CO₂ draws for a display mode; the three are mutually exclusive (as `carbonDrawing`). */
export function co2Drawing(
  active: boolean, mode: "field" | "hexes" | "points", pointsActive: boolean,
): { field: boolean; hexes: boolean; points: boolean } {
  return {
    field: active && mode === "field",
    hexes: active && mode === "hexes",
    points: active && mode === "points" && pointsActive,
  };
}

export const socatTileUrl = (version: string): string =>
  `${API}/api/v1/socat/tiles/{z}/{x}/{y}.pbf?v=${encodeURIComponent(version)}`;
