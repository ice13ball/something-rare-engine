// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { ARGO_DEPTH_WINDOW_BOUNDS } from "./argoOxygenPoints";

const API = import.meta.env.VITE_API_BASE_URL ?? "";

/** Deepest tile the server makes (deck.gl overzooms past it); == backend argo_doxy_rules.TILE_MAX_ZOOM. */
export const ARGO_TILE_MAX_ZOOM = 8;
/** == backend POINT_MIN_ZOOM: below it a feature is a grid cell (the mean of `n` profiles), from it one profile. */
export const ARGO_POINT_MIN_ZOOM = 5;
/** The display depths of the tiles' `d0..d7` slots, in slot order (== backend DISPLAY_DEPTHS). */
export const ARGO_DEPTHS: readonly number[] = Object.keys(ARGO_DEPTH_WINDOW_BOUNDS).map(Number).sort((a, b) => a - b);

/** The part of `/v1/argo-oxygen/meta` the map reads (`tile_version` null = no tiles built yet; `years` = drawable
 *  profiles per year in the tile table, e.g. {"2002": 4}, empty while nothing is built). */
export type ArgoTileMeta = {
  tile_version: string | null; year_min: number | null; year_max: number | null; years?: Record<string, number> | null;
};

/** One tile feature. Cell: n profiles, k a real profile of the cell, a/b first/last year. Profile: k its key, a its year.
 *  d0..d7: whole µmol/kg (a cell's mean); an ABSENT slot = no good value there (drawn grey, never 0). */
export type ArgoTileProps = { k: string; a: number; n?: number; b?: number } & Partial<Record<`d${number}`, number>>;

export const argoTileUrl = (version: string, range: readonly [number, number] | null): string =>
  `${API}/api/v1/argo-oxygen/tiles/{z}/{x}/{y}.pbf?v=${encodeURIComponent(version)}`
  + (range ? `&y0=${range[0]}&y1=${range[1]}` : "");

/** A cell carries `n`; a single profile does not. */
export const isArgoCell = (p: ArgoTileProps): boolean => p.n != null;

/** The value at the depth slot, or null. ⛔ `== null`, never falsiness: a 0 would be a real (anoxic) value. */
export function argoTileValue(p: ArgoTileProps | undefined, depthIndex: number): number | null {
  if (!p || depthIndex < 0) return null;
  const raw = p[`d${depthIndex}` as `d${number}`];
  return raw == null ? null : raw;
}

/** Year span for the From/To selects, from /meta (the drawable profiles' first and last year). */
export function argoMetaYearBounds(m: ArgoTileMeta | null): { min: number; max: number } | null {
  return m && typeof m.year_min === "number" && typeof m.year_max === "number" && m.year_min <= m.year_max
    ? { min: m.year_min, max: m.year_max } : null;
}

/** True when /meta's per-year counts say the (inclusive) year range holds no drawable profile. No counts (nothing
 *  built, an older server) is "unknown", never "empty": the tile-version notice covers that case. */
export function argoRangeEmpty(m: ArgoTileMeta | null, range: readonly [number, number] | null): boolean {
  const years = m?.years;
  if (!years) return false;
  const entries = Object.entries(years);
  if (!entries.length) return false;
  return entries.every(([y, n]) => !(n > 0) || (range != null && (Number(y) < range[0] || Number(y) > range[1])));
}
