// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import type { ArcticCatchmentVariable } from "../../store/mapStore";
import {
  FGDC_RESOURCES,
  IUCN_REDLIST,
  NOISE_RISK,
  withAlpha,
} from "../../styles/colorStandards";

// ── SIOS Svalbard topic colour helper ──────────────────────────────────────
export function siosTopicColor(topic?: string): [number, number, number, number] {
  switch (topic) {
    case "oceans":      return [0, 242, 255, 230];   // cyan
    case "atmosphere":  return [251, 191, 36, 230];  // amber
    case "climatologymeteorologyatmosphere":
                        return [251, 191, 36, 230];  // amber (WMO variant)
    case "biota":       return [74, 222, 128, 230];  // green
    case "cryosphere":  return [147, 197, 253, 230]; // light-blue
    default:            return [148, 163, 184, 200]; // slate
  }
}

// ── Field-value colour ramp helpers ────────────────────────────────────────
export function hexToRgbTriple(h: string): [number, number, number] {
  const n = parseInt(h.replace("#", ""), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
export function rampColor(
  value: number, vmin: number, vmax: number,
  stops: { pos: number; hex: string }[], alpha = 170,
): [number, number, number, number] {
  if (!stops || stops.length === 0) return [150, 150, 150, alpha];
  const t = Math.max(0, Math.min(1, (value - vmin) / ((vmax - vmin) || 1)));
  let lo = stops[0], hi = stops[stops.length - 1];
  for (let i = 0; i < stops.length - 1; i++) {
    if (t >= stops[i].pos && t <= stops[i + 1].pos) { lo = stops[i]; hi = stops[i + 1]; break; }
  }
  const f = hi.pos === lo.pos ? 0 : (t - lo.pos) / (hi.pos - lo.pos);
  const a = hexToRgbTriple(lo.hex), b = hexToRgbTriple(hi.hex);
  return [
    Math.round(a[0] + (b[0] - a[0]) * f),
    Math.round(a[1] + (b[1] - a[1]) * f),
    Math.round(a[2] + (b[2] - a[2]) * f),
    alpha,
  ];
}

// Diverging ramp anchored on `center` (piecewise: [vmin,center]→[0,0.5],
// [center,vmax]→[0.5,1]) — mirrors backend acidification._diverging_norm so the
// clickable hexagon view puts the Ω=1 red/blue boundary in the SAME place as the
// server-baked field bitmap. A plain linear rampColor would put the ramp midpoint
// at (vmin+vmax)/2 (~2.25 for aragonite), mis-colouring the biologically critical
// saturation threshold. Only for diverging vars; sequential ones use rampColor.
export function divergingRampColor(
  value: number, vmin: number, center: number, vmax: number,
  stops: { pos: number; hex: string }[], alpha = 170,
): [number, number, number, number] {
  if (!stops || stops.length === 0) return [150, 150, 150, alpha];
  const t = value <= center
    ? 0.5 * Math.max(0, Math.min(1, (value - vmin) / ((center - vmin) || 1)))
    : 0.5 + 0.5 * Math.max(0, Math.min(1, (value - center) / ((vmax - center) || 1)));
  let lo = stops[0], hi = stops[stops.length - 1];
  for (let i = 0; i < stops.length - 1; i++) {
    if (t >= stops[i].pos && t <= stops[i + 1].pos) { lo = stops[i]; hi = stops[i + 1]; break; }
  }
  const f = hi.pos === lo.pos ? 0 : (t - lo.pos) / (hi.pos - lo.pos);
  const a = hexToRgbTriple(lo.hex), b = hexToRgbTriple(hi.hex);
  return [
    Math.round(a[0] + (b[0] - a[0]) * f),
    Math.round(a[1] + (b[1] - a[1]) * f),
    Math.round(a[2] + (b[2] - a[2]) * f),
    alpha,
  ];
}

// Arctic Catchments — per-variable linear colour ramp (data domains from real HydroSHEDS/ERA5)
// ARCTIC_CATCHMENT_RAMP + _arcticCatchmentColor: kept in sync with backend/services/arctic_ramp.py
// (raster render); not used for vector fill since the raster switch. Both `export`ed (no error
// suppression) so noUnusedLocals doesn't flag the kept-for-reference helper at module scope.
export const ARCTIC_CATCHMENT_RAMP: Record<ArcticCatchmentVariable, {
  min: number; max: number;
  lo: [number, number, number];
  hi: [number, number, number];
}> = {
  ocs_mean:    { min: 50,  max: 115,   lo: [255, 247, 236], hi: [127, 39,  4]   }, // t/ha, browns (real p2=55, p98=113)
  oc_tot:      { min: 0,   max: 0.006, lo: [247, 252, 253], hi: [0,   68,  27]  }, // Gt, greens (real p98=0.0057, long-tailed)
  runoff_mean: { min: 0,   max: 1.6,   lo: [247, 251, 255], hi: [8,   48,  107] }, // ~0–2.8 in source units (p98≈1.6), blues
  pf_frac:     { min: 0,   max: 1,     lo: [255, 255, 229], hi: [49,  54,  149] }, // 0–1 permafrost fraction
  t_2m_mean:   { min: 250, max: 282,   lo: [5,   48,  97],  hi: [165, 0,   38]  }, // Kelvin, cold→warm (real p2=254.7, p98=278.7)
};
// _-prefix marks intentionally-unused; `export` is what actually satisfies noUnusedLocals at module
// scope (TS only honours the _ prefix for parameters, not module-level declarations).
export function _arcticCatchmentColor(
  v: number | null | undefined,
  key: ArcticCatchmentVariable,
): [number, number, number, number] {
  if (v == null || Number.isNaN(v)) return [100, 116, 139, 90]; // muted slate "no data"
  const r = ARCTIC_CATCHMENT_RAMP[key];
  if (r.max === r.min) return [100, 116, 139, 170]; // guard div-by-zero for equal min/max ramps
  const t = Math.max(0, Math.min(1, (v - r.min) / (r.max - r.min)));
  const lerp = (a: number, b: number) => Math.round(a + (b - a) * t);
  return [lerp(r.lo[0], r.hi[0]), lerp(r.lo[1], r.hi[1]), lerp(r.lo[2], r.hi[2]), 170];
}

// Resource type colors follow FGDC commodity convention (USGS).
// See styles/colorStandards.ts for sources.
export const RESOURCE_COLOR: Record<string, [number, number, number, number]> = Object.fromEntries(
  Object.entries(FGDC_RESOURCES).map(([k, c]) => [k, withAlpha(c, 200)])
);

export function hotspotPointColor(props: any): [number, number, number, number] {
  // IUCN Red List palette — CR/EN red, VU amber, NT yellow, LC/DD blue/grey.
  const cat: string | undefined = props.iucn_category;
  if (cat === "CR" || cat === "EN") return withAlpha(IUCN_REDLIST.CR, 200);
  if (cat === "VU")                  return withAlpha(IUCN_REDLIST.VU, 200);
  if (cat === "NT")                  return withAlpha(IUCN_REDLIST.NT, 200);
  return withAlpha(IUCN_REDLIST.LC, 200);
}

export function noiseRiskColor(level: string): [number, number, number, number] {
  // ColorBrewer YlOrRd-style ramp + neutral data-gap (see colorStandards.NOISE_RISK).
  const map: Record<string, number> = {
    critical: 220, high: 200, moderate: 180, low: 160, data_gap: 180, minimal: 120,
  };
  const c = NOISE_RISK[level] ?? NOISE_RISK.minimal;
  return withAlpha(c, map[level] ?? 120);
}

// Stable module-level references so deck.gl prop-diffing recognises them as
// unchanged across React re-renders (array literals create new refs each render).
export const MINING_FOOTPRINTS_FILL: [number, number, number, number] = [220, 38, 127, 140];
export const MINING_FOOTPRINTS_STROKE: [number, number, number, number] = [255, 255, 255, 200];

// ── Hydrophone-station source colour registry ──────────────────────────────
// Extracted from an inline switch that lived in Map3D.tsx (was re-created on
// every render — closures aren't referentially stable, unlike this Record).
// Keys MUST match `acoustic_stations.source` exactly (see
// backend/ingestion/acoustic_noaa_archive_ingest.py PROGRAMS — read-only,
// frontend does not import it). This Record, HYDROPHONE_SOURCE_DEFS
// (controls/filterDefs.ts) and HYDROPHONE_SOURCE_LABEL
// (panels/ocean/HydrophoneStationPanel.tsx) are three independent registries
// over the same key set — guarded by __tests__/hydrophone-source-registries.test.ts.
export const HYDROPHONE_SOURCE_COLOR: Record<string, [number, number, number, number]> = {
  ooi:    [232, 121, 249, 255],   // magenta
  imos:   [ 52, 211, 153, 255],   // green
  mars:   [ 34, 211, 238, 255],   // cyan
  palaoa: [248, 250, 252, 255],   // ice white (Antarctic)
  obsea:  [250, 204,  21, 255],   // amber (Iberian)
  km3net: [129, 140, 248, 255],   // indigo (deep Med physics)
  nrs:    [ 56, 189, 248, 255],   // sky-400 — global ocean reference
  sanctsound: [251, 146, 60, 255], // orange-400 — US sanctuaries
  nefsc:  [244, 114, 182, 255],   // pink-400 — right whale corridor
  // Phase 4 — NOAA Passive Acoustic Archive programs
  pifsc:  [ 14, 165, 233, 255],   // sky-500 — Pacific Islands
  sefsc:  [251, 191,  36, 255],   // amber-400 — Gulf of Mexico
  onms:   [249, 115,  22, 255],   // orange-500 — sanctuaries-2
  adeon:  [139,  92, 246, 255],   // violet-500 — Atlantic deepwater
  boem:   [ 75,  85,  99, 255],   // gray-600 — federal regulatory
  aeon:   [167, 139, 250, 255],   // violet-400 — Atlantic ecosystem
  navy:   [ 31,  41,  55, 255],   // gray-800 — Navy
  nps:    [ 16, 185, 129, 255],   // emerald-500 — Park Service
  jasco:  [217,  70, 239, 255],   // fuchsia-500 — contractor
  fram:   [225, 211,  20, 255],   // lime-yellow — Arctic ice
  coastal_studies_institute: [ 14, 116, 144, 255], // cyan-700
  ioos:   [ 79,  70, 229, 255],   // indigo-600 — IOOS
  // Phase 3 — PANGAEA/Dryad additions
  sambah: [ 52, 211, 153, 255],   // emerald-400 — Baltic C-POD (HAUSGARTEN folds into 'fram')
  // Phase 4 — CTBTO IMS
  ims:    [103, 232, 249, 255],   // cyan-300 — treaty-verified global network
  // Phase 5 — 8 NOAA Passive Acoustic Archive programs added 2026-09-15
  // (see PROGRAMS comment in the ingest file for the discovery story).
  // Colours chosen by Euclidean RGB distance against every existing entry
  // above — all ≥58 apart, no two of these 8 closer than ~71 to each other.
  afsc:   [  6,  95,  70, 255],   // emerald-800 — Alaska
  cornell:[185,  28,  28, 255],   // red-700 ("Cornell red")
  mbarc_socal:  [ 59, 130, 246, 255], // blue-500 — Navy family (see 'navy' above)
  mbarc_arctic: [191, 219, 254, 255], // blue-200 — Navy family, icy pale
  mbarc_flip:   [ 30,  64, 175, 255], // blue-800 — Navy family, deep
  swfsc:  [120,  53,  15, 255],   // amber-900 — Southwest Fisheries
  rutgers_njrmi: [101, 163, 13, 255], // lime-600 — NJ Research & Monitoring
  // ⚠️ Lowercase key against an uppercase bucket prefix — deliberate, see the
  // PROGRAMS comment in the ingest file. `acoustic_stations.source` is
  // lowercase for every program; matching anything else here silently drops
  // this source into the gray fallback below.
  md_wea_cpod: [219,  39, 119, 255], // pink-600 — Maryland WEA C-POD
};

const HYDROPHONE_SOURCE_COLOR_DEFAULT: [number, number, number, number] = [156, 163, 175, 255]; // slate fallback

export function hydrophoneSourceColor(source: unknown): [number, number, number, number] {
  return HYDROPHONE_SOURCE_COLOR[String(source)] ?? HYDROPHONE_SOURCE_COLOR_DEFAULT;
}
