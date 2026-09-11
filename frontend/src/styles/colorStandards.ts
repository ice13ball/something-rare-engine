// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

/**
 * Standard scientific color palettes used across the Abyssal Claims map.
 *
 * Every palette here matches an external authoritative source so the legend
 * reads as scientific shorthand, not arbitrary aesthetic choice. Sources are
 * cited inline; see docs/COLOR_STANDARDS.md for the full rationale.
 *
 * All triplets are sRGB [R, G, B] in 0-255. Alpha is added at the call site
 * because fill alpha and outline alpha differ per layer.
 */

export type RGB = [number, number, number];
export type RGBA = [number, number, number, number];

export const withAlpha = (c: RGB, a: number): RGBA => [c[0], c[1], c[2], a];

/* ─────────────────────────────────────────────────────────────────
 * cmocean — perceptually uniform ocean palettes.
 * Source: Thyng, K. M. et al. (2016) "True colors of oceanography",
 * Oceanography 29(3). https://matplotlib.org/cmocean/
 *
 * Each ramp is 11 stops (downsampled from the full 256-step LUT). For
 * deck.gl `colorRange` props this can be used directly; for per-feature
 * coloring use `sampleRamp(ramp, t)` with t in [0, 1].
 * ───────────────────────────────────────────────────────────────── */

// cmocean.deep — bathymetry. Light → dark teal as depth increases.
export const CMOCEAN_DEEP: RGB[] = [
  [253, 253, 204], [206, 235, 178], [156, 217, 166], [114, 198, 165],
  [ 83, 178, 168], [ 67, 156, 169], [ 60, 134, 168], [ 60, 111, 162],
  [ 64,  86, 145], [ 60,  62, 110], [ 41,  39,  65],
];

// cmocean.thermal — sea-surface / water temperature.
export const CMOCEAN_THERMAL: RGB[] = [
  [  4,  35,  51], [ 39,  41, 113], [ 84,  44, 145], [126,  53, 138],
  [167,  68, 121], [205,  86,  98], [232, 113,  72], [246, 148,  60],
  [248, 187,  73], [240, 226, 105], [232, 250, 145],
];

// cmocean.haline — salinity (PSU).
export const CMOCEAN_HALINE: RGB[] = [
  [ 41,  24, 107], [ 39,  47, 142], [ 34,  77, 154], [ 29, 105, 152],
  [ 30, 133, 145], [ 38, 161, 134], [ 70, 187, 113], [136, 207,  82],
  [205, 219,  79], [248, 234, 134], [253, 254, 191],
];

// cmocean.algae — chlorophyll / biomass.
export const CMOCEAN_ALGAE: RGB[] = [
  [214, 249, 207], [177, 226, 175], [135, 202, 144], [ 95, 178, 119],
  [ 60, 152,  95], [ 38, 124,  76], [ 31,  96,  62], [ 26,  68,  50],
  [ 19,  43,  35], [ 11,  22,  20], [  5,   8,   8],
];

// cmocean.speed — current speed magnitude.
export const CMOCEAN_SPEED: RGB[] = [
  [254, 252, 205], [233, 230, 156], [202, 207, 124], [167, 184, 102],
  [129, 162,  86], [ 89, 141,  74], [ 50, 119,  64], [ 26,  95,  53],
  [ 23,  68,  37], [ 19,  41,  22], [  6,  18,   8],
];

// cmocean.balance — diverging anomalies (red-white-blue).
export const CMOCEAN_BALANCE: RGB[] = [
  [ 24,  28, 110], [ 60,  77, 168], [108, 132, 207], [167, 184, 226],
  [220, 224, 235], [247, 247, 247], [240, 211, 195], [228, 159, 134],
  [206, 100,  82], [167,  44,  46], [ 99,  21,  35],
];

// cmocean.topo — relief (oceans below 0 dark blue, land above tan/green).
// Use for seamount elevation columns.
export const CMOCEAN_TOPO: RGB[] = [
  [ 23,  27,  69], [ 39,  64, 122], [ 52, 109, 156], [ 90, 154, 173],
  [149, 195, 187], [212, 214, 188], [183, 173, 110], [148, 130,  68],
  [127, 100,  56], [ 97,  72,  45], [ 64,  46,  31],
];

/** Sample a 0..1 position from an N-stop ramp with linear interpolation. */
export function sampleRamp(ramp: RGB[], t: number): RGB {
  if (!Number.isFinite(t)) return ramp[0];
  if (t <= 0) return ramp[0];
  if (t >= 1) return ramp[ramp.length - 1];
  const pos = t * (ramp.length - 1);
  const i = Math.floor(pos);
  const f = pos - i;
  const a = ramp[i], b = ramp[i + 1];
  return [
    Math.round(a[0] + (b[0] - a[0]) * f),
    Math.round(a[1] + (b[1] - a[1]) * f),
    Math.round(a[2] + (b[2] - a[2]) * f),
  ];
}

/* ─────────────────────────────────────────────────────────────────
 * EPA AQI — US Air Quality Index colors.
 * Source: https://www.airnow.gov/aqi/aqi-basics/
 * Required verbatim: scientists and the public have these memorized.
 * ───────────────────────────────────────────────────────────────── */

export type AqiCategory = "Good" | "Moderate" | "USG" | "Unhealthy" | "Very Unhealthy" | "Hazardous";

export const EPA_AQI: Record<AqiCategory, RGB> = {
  "Good":           [  0, 228,   0],  // #00E400
  "Moderate":       [255, 255,   0],  // #FFFF00
  "USG":            [255, 126,   0],  // #FF7E00
  "Unhealthy":      [255,   0,   0],  // #FF0000
  "Very Unhealthy": [143,  63, 151],  // #8F3F97
  "Hazardous":      [126,   0,  35],  // #7E0023
};

export const EPA_AQI_NO_DATA: RGB = [148, 148, 148];

/* ─────────────────────────────────────────────────────────────────
 * WRI Aqueduct 4.0 — water risk classes.
 * Source: WRI Aqueduct (https://www.wri.org/aqueduct), Kuzma et al. 2023.
 * The "No Data" sentinel is intentionally neutral grey, NOT a risk color.
 * ───────────────────────────────────────────────────────────────── */

export const WRI_AQUEDUCT: RGB[] = [
  [255, 242, 204],  // 0  Low              #FFF2CC
  [255, 230, 153],  // 1  Low–Medium       #FFE699
  [255, 165,   0],  // 2  Medium–High      #FFA500
  [230,  57,  70],  // 3  High             #E63946
  [157,   2,   8],  // 4  Extremely High   #9D0208
];
export const WRI_AQUEDUCT_NO_DATA: RGB = [189, 189, 189]; // #BDBDBD

/* ─────────────────────────────────────────────────────────────────
 * FGDC Geologic / commodity colors.
 * Source: FGDC Digital Cartographic Standard for Geologic Map Symbolization
 * (USGS NGMDB) https://ngmdb.usgs.gov/fgdc_gds/geolsymstd.php
 * Commodity hues follow USGS / industry convention.
 * ───────────────────────────────────────────────────────────────── */

export const FGDC_RESOURCES: Record<string, RGB> = {
  // Polymetallic nodules / Mn — brown-black
  "Polymetallic Manganese Nodules":    [ 74,  60,  42],
  "Polymetallic Nodules":              [ 74,  60,  42],
  // Polymetallic sulphides / Cu-Zn-Pb — copper-orange
  "Polymetallic Sulphides":            [184, 115,  51],
  // Cobalt-rich crusts / Co — pink-magenta
  "Cobalt-Rich Ferromanganese Crusts": [230,  57, 155],
  "Cobalt-rich Ferromanganese Crusts": [230,  57, 155],
  // Nickel — green
  "Nickel":                            [ 90, 174,  97],
  // Rare earth elements — violet
  "Rare Earth Elements":               [118,  42, 131],
  "REE":                               [118,  42, 131],
  // Gold — yellow
  "Gold":                              [255, 215,   0],
  "Au":                                [255, 215,   0],
};

export const FGDC_RESOURCE_FALLBACK: RGB = [100, 160, 255];

/* ─────────────────────────────────────────────────────────────────
 * IUCN / Protected Planet conventions.
 * Source: https://www.protectedplanet.net/
 *  - Terrestrial protected areas are rendered green by Protected Planet.
 *  - Marine protected areas use a darker blue family.
 *
 * IUCN Red List status colors:
 *  https://www.iucnredlist.org/resources/categories-and-criteria
 * ───────────────────────────────────────────────────────────────── */

export const IUCN_PA_TERRESTRIAL: RGB = [ 27,  94,  32]; // #1B5E20 dark green
export const IUCN_PA_MARINE:      RGB = [ 13,  71, 161]; // #0D47A1 dark blue

// IUCN management category gradient (Ia → VI), dark→light green.
export const IUCN_CATEGORY_RAMP: Record<string, RGB> = {
  "Ia":  [ 13,  62,  24],
  "Ib":  [ 27,  94,  32],
  "II":  [ 46, 125,  50],
  "III": [ 76, 175,  80],
  "IV":  [129, 199, 132],
  "V":   [165, 214, 167],
  "VI":  [200, 230, 201],
};

// IUCN Red List status (used by GBIF / OBIS layers).
//   CR/EN → reds, VU → orange, NT → yellow, LC/DD → blue/grey.
export const IUCN_REDLIST: Record<string, RGB> = {
  "CR": [220,  20,  60],   // crimson
  "EN": [233,  90,  90],
  "VU": [245, 158,  11],   // amber
  "NT": [253, 216,  53],   // yellow
  "LC": [121, 167, 207],   // muted blue
  "DD": [158, 158, 158],   // grey
};

/* ─────────────────────────────────────────────────────────────────
 * NASA FIRMS confidence — yellow→orange→red, community convention.
 * Source: NASA FIRMS confidence categories (low/nominal/high).
 * ───────────────────────────────────────────────────────────────── */

export const FIRMS_CONFIDENCE: Record<string, RGB> = {
  "low":     [255, 214,  10],  // #FFD60A
  "nominal": [255, 107,  53],  // #FF6B35
  "high":    [193,  18,  31],  // #C1121F
};

export const FIRMS_FALLBACK: RGB = [255, 107, 53];

/* ─────────────────────────────────────────────────────────────────
 * ColorBrewer 2.0 qualitative & sequential palettes.
 * Source: Cynthia Brewer, https://colorbrewer2.org/
 *
 * Use Set2 / Dark2 for unordered categorical layers (chemosynthetic
 * habitat type, ship class). Use YlOrRd / YlGnBu for ordered data
 * without a domain-standard palette.
 * ───────────────────────────────────────────────────────────────── */

export const CB_SET2: RGB[] = [
  [102, 194, 165], [252, 141,  98], [141, 160, 203], [231, 138, 195],
  [166, 216,  84], [255, 217,  47], [229, 196, 148], [179, 179, 179],
];

export const CB_DARK2: RGB[] = [
  [ 27, 158, 119], [217,  95,   2], [117, 112, 179], [231,  41, 138],
  [102, 166,  30], [230, 171,   2], [166, 118,  29], [102, 102, 102],
];

export const CB_YLORRD: RGB[] = [
  [255, 255, 178], [254, 217, 118], [254, 178,  76], [253, 141,  60],
  [252,  78,  42], [227,  26,  28], [177,   0,  38],
];

export const CB_YLGNBU: RGB[] = [
  [255, 255, 217], [237, 248, 177], [199, 233, 180], [127, 205, 187],
  [ 65, 182, 196], [ 29, 145, 192], [ 34,  94, 168], [ 12,  44, 132],
  [  8,  29,  88],
];

/* ─────────────────────────────────────────────────────────────────
 * Layer-specific helpers.
 * ───────────────────────────────────────────────────────────────── */

/** Map an OBIS / GBIF IUCN category code to a color (CR/EN red, VU amber, …). */
export function iucnRedlistColor(cat: string | null | undefined): RGB {
  if (!cat) return IUCN_REDLIST.LC;
  return IUCN_REDLIST[cat] ?? IUCN_REDLIST.LC;
}

/**
 * Tailings dam normalised hazard rating (Extreme..Low + Unclassified).
 * Aligned with WRI Aqueduct progression so the two layers read the same:
 * yellow = low, dark red = extreme. Unclassified gets neutral grey
 * (not a risk color) to avoid implying low risk by accident.
 */
export const TAILINGS_HAZARD: Record<string, RGB> = {
  "Low":         WRI_AQUEDUCT[0],
  "Medium":      WRI_AQUEDUCT[1],
  "Significant": WRI_AQUEDUCT[2],
  "High":        WRI_AQUEDUCT[3],
  "Very High":   [206,  20,  41],
  "Extreme":     WRI_AQUEDUCT[4],
};
export const TAILINGS_UNCLASSIFIED: RGB = [148, 148, 148];

/**
 * Chemosynthetic habitat colors — qualitative (no rank), so use ColorBrewer
 * Set2 for adjacent-distinguishable rather than continuous semantics.
 */
export const CHESS_HABITAT: Record<string, RGB> = {
  "seep":       CB_SET2[0],  // teal
  "whale_fall": CB_SET2[3],  // pink
  "omz":          CB_SET2[2],  // periwinkle — legacy value
  "unclassified": CB_SET2[2],
};

/** Noise risk grid (MSFD D11). Diverging YlOrRd-style with neutral data-gap. */
export const NOISE_RISK: Record<string, RGB> = {
  "critical": [177,   0,  38],   // CB_YlOrRd top
  "high":     [227,  26,  28],
  "moderate": [253, 141,  60],
  "low":      [254, 217, 118],
  "data_gap": [149, 117, 205],   // muted purple — distinguishable from risk ramp
  "minimal":  [200, 200, 200],
};

/* ─────────────────────────────────────────────────────────────────
 * Untouched legacy colors — exported for documentation only so other
 * modules can reference them by name even though we don't refactor.
 * ───────────────────────────────────────────────────────────────── */

export const VESSEL_DARK:    RGB = [230,  57,  70]; // matched to red traffic-light
export const VESSEL_MATCHED: RGB = [ 42, 157, 143];
export const VESSEL_AMBIG:   RGB = [244, 162,  97];

export const CLAIM_LINE: RGB = [  0, 242, 255]; // cyan, do not change
