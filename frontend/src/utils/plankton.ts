// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

/**
 * Plankton (OBIS) map layer — the fixed filter vocabulary, colours and the tile/panel query.
 *
 * ⛔ Mirrors backend/schema/plankton.py: GROUPS order = bit order of the tile's `groups` mask, DECADES,
 * DEPTH_BANDS. The server refuses any other value with a 400, so a drift here shows up as a blank layer.
 * Filters are applied on the SERVER (exact per combination); nothing here filters features client-side.
 */

export const PLANKTON_LAYER_NAME = "Plankton (OBIS)";

export const PLANKTON_GROUPS = ["copepoda", "euphausiacea", "diatoms", "coccolithophores", "dinoflagellates"] as const;
export type PlanktonGroup = (typeof PLANKTON_GROUPS)[number];
/** "-1" = no date (also a future year), "1940" = before 1950. */
export const PLANKTON_DECADES = ["-1", "1940", "1950", "1960", "1970", "1980", "1990", "2000", "2010", "2020"] as const;
/** "0" = 0–200 m, "1" = 200–1000 m, "2" = > 1000 m, "3" = no depth. */
export const PLANKTON_DEPTH_BANDS = ["0", "1", "2", "3"] as const;

export const PLANKTON_GROUP_HEX: Record<PlanktonGroup, string> = {
  copepoda: "#f97316",
  euphausiacea: "#f43f5e",
  diatoms: "#facc15",
  coccolithophores: "#38bdf8",
  dinoflagellates: "#c084fc",
};
const UNKNOWN_RGB: [number, number, number] = [148, 163, 184];

function rgbOf(group: unknown): [number, number, number] {
  const hex = PLANKTON_GROUP_HEX[group as PlanktonGroup];
  if (!hex) return UNKNOWN_RGB;
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

export interface PlanktonFilterState {
  groups: ReadonlySet<string>;
  decades: ReadonlySet<string>;
  bands: ReadonlySet<string>;
  showEdna: boolean;
}

function dim(values: ReadonlySet<string>, vocab: readonly string[]): string | null {
  const chosen = vocab.filter((v) => values.has(v));
  // Empty set = everything (store convention); the full set is the same view, so it is omitted too.
  return chosen.length === 0 || chosen.length === vocab.length ? null : chosen.join(",");
}

/** `g=…&d=…&b=…&e=0`, canonical (vocabulary order), "" when nothing is narrowed. */
export function planktonFilterQuery(f: PlanktonFilterState): string {
  const parts: string[] = [];
  const g = dim(f.groups, PLANKTON_GROUPS);
  const d = dim(f.decades, PLANKTON_DECADES);
  const b = dim(f.bands, PLANKTON_DEPTH_BANDS);
  if (g) parts.push(`g=${g}`);
  if (d) parts.push(`d=${d}`);
  if (b) parts.push(`b=${b}`);
  if (!f.showEdna) parts.push("e=0");
  return parts.join("&");
}

export function planktonFilterActive(f: PlanktonFilterState): boolean {
  return planktonFilterQuery(f) !== "";
}

/** Through the BFF (`/api/v1/...`), never `/v1/...`. `retry` re-keys the URL after the Retry button. */
export function planktonTileUrl(api: string, version: string, f: PlanktonFilterState, retry: number): string {
  const q = planktonFilterQuery(f);
  return `${api}/api/v1/plankton/tiles/{z}/{x}/{y}.pbf?v=${encodeURIComponent(version)}${q ? `&${q}` : ""}&r=${retry}`;
}

/** First-paint version lookup: one cheap row. ⛔ Never /plankton/meta here — its counts can take minutes. */
export function planktonVersionUrl(api: string): string {
  return `${api}/api/v1/plankton/tile-version`;
}

const VERSION_RE = /^[0-9]{14}-[0-9a-f]{6}$/;

export function planktonVersionFromMeta(meta: unknown): string | null {
  const v = (meta as { tile_version?: unknown } | null)?.tile_version;
  return typeof v === "string" && VERSION_RE.test(v) ? v : null;
}

/** Radius in px. `tileZ` < 7 is a grid tile (1° below z4, 0.25° at z4–6): the circle is capped at 0.45 of the
 *  cell spacing at that zoom (512-px world), so neighbouring cells never overlap; a place (z ≥ 7) is not capped. */
export function planktonRadius(n: unknown, tileZ = 99): number {
  const v = Number(n);
  const r = !Number.isFinite(v) || v < 1 ? 3 : Math.min(14, 3 + 2 * Math.log10(v));
  if (tileZ >= 7) return r;
  const spacing = ((tileZ < 4 ? 1 : 0.25) / 360) * 512 * 2 ** tileZ;
  return Math.max(1.5, Math.min(r, 0.45 * spacing));
}

interface TileProps { top_group?: unknown; edna_only?: unknown }

/** Dominant group's colour; an eDNA-only place has no fill (DNA found, no organism counted). */
export function planktonFillColor(p: TileProps | null | undefined): [number, number, number, number] {
  if (p?.edna_only === true) return [0, 0, 0, 0];
  const [r, g, b] = rgbOf(p?.top_group);
  return [r, g, b, 200];
}

/** eDNA-only: an outline in the group colour; otherwise a faint white rim for contrast. */
export function planktonLineColor(p: TileProps | null | undefined): [number, number, number, number] {
  if (p?.edna_only !== true) return [255, 255, 255, 90];
  const [r, g, b] = rgbOf(p?.top_group);
  return [r, g, b, 255];
}

/** Zoom a click on a grid cell lands on: the next band (0.25° grid, then places). */
export function planktonCellZoomTarget(zoom: number): number {
  return zoom < 4 ? 4.5 : zoom < 7 ? 7.5 : zoom;
}
