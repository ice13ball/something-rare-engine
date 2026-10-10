// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { rampColor } from "../components/map3d/colors";
import { GLODAP_NO_VALUE_RGBA, type RGBA, type RampMeta } from "./glodapPoints";

const API = import.meta.env.VITE_API_BASE_URL ?? "";

export const WOD_CASTS_ID = "wod-casts";
/** Layer name `LayerUnavailableNotice` shows when /meta or the tiles fail. */
export const WOD_FAILED_NAME = "WOD Measurements";
/** Deepest tile the server makes (deck.gl overzooms past it); == backend TILE_MAX_ZOOM. */
export const WOD_TILE_MAX_ZOOM = 12;
const POINT_ALPHA = 235;

/** The part of `/v1/wod/meta` the map reads (`tile_version` null = nothing built). */
export type WodMeta = {
  tile_version: string | null; year_min: number; year_max: number; point_min_zoom: number;
  depths: number[]; variables: string[]; scales: Record<string, number>;
};

/** One tile feature: q cell, k casts, id a real cast of the cell, a/b first/last year, d0..d7 scaled means. */
export type WodProps = { q: number; k: number; id: number; a: number; b: number } & Partial<Record<`d${number}`, number>>;

/**
 * Which tile set to fetch for a WOA variable. AOU and O₂ saturation have no per-cast value (R8): they
 * draw the temperature set's positions in grey.
 */
export function wodTileVar(woaVariable: string, meta: Pick<WodMeta, "variables">): { tileVar: string; measured: boolean } {
  return meta.variables.includes(woaVariable)
    ? { tileVar: woaVariable, measured: true }
    : { tileVar: "temperature", measured: false };
}

/** Unscaled mean at the depth index, or null. ⛔ `== null`, never falsiness: 0 °C and N* = 0 are values. */
export function wodValue(p: WodProps, depthIndex: number, scale: number): number | null {
  const raw = p[`d${depthIndex}` as `d${number}`];
  return raw == null ? null : raw / scale;
}

export function wodColor(
  p: WodProps, depthIndex: number, measured: boolean, scale: number | undefined, vm?: RampMeta,
): RGBA {
  if (!measured || depthIndex < 0 || !scale || !vm?.ramp?.length) return GLODAP_NO_VALUE_RGBA;
  const v = wodValue(p, depthIndex, scale);
  return v === null ? GLODAP_NO_VALUE_RGBA : rampColor(v, vm.vmin, vm.vmax, vm.ramp, POINT_ALPHA);
}

/** What WOA draws for a display mode; the three are mutually exclusive (as `co2Drawing`). */
export function woaDrawing(
  active: boolean, mode: "field" | "hexes" | "points", pointsActive: boolean,
): { field: boolean; hexes: boolean; points: boolean } {
  return {
    field: active && mode === "field",
    hexes: active && mode === "hexes",
    points: active && mode === "points" && pointsActive,
  };
}

export const wodTileUrl = (version: string, tileVar: string, range: readonly [number, number] | null): string =>
  `${API}/api/v1/wod/tiles/${encodeURIComponent(tileVar)}/{z}/{x}/{y}.pbf?v=${encodeURIComponent(version)}`
  + (range ? `&y0=${range[0]}&y1=${range[1]}` : "");

/** The eight display depths of the tiles' `d0..d7` slots (== backend DEPTHS == the WOA display depths). */
export const WOD_DEPTHS = [0, 50, 100, 200, 500, 1000, 1500, 2000] as const;

/** Each display depth's window [lo, hi] in metres (== backend WINDOWS): the value drawn is the accepted one nearest the depth inside it. */
export const WOD_WINDOWS: Record<number, [number, number]> = {
  0: [0, 10], 50: [40, 60], 100: [90, 110], 200: [175, 225], 500: [450, 550],
  1000: [950, 1050], 1500: [1425, 1575], 2000: [1900, 2100],
};
/** `0–10`, for the "no good value in the <lo>–<hi> m window" lines; a depth with no window falls back to itself. */
export const wodWindowLabel = (d: number): string => {
  const w = WOD_WINDOWS[d];
  return w ? `${w[0]}–${w[1]}` : String(d);
};

/** The variables a cast can carry per-cast values for (== backend PICK_VARS); AOU and O₂ saturation are not among them. */
export const WOD_PICK_VARS = ["temperature", "salinity", "oxygen", "phosphate", "silicate", "nitrate", "nstar"] as const;
