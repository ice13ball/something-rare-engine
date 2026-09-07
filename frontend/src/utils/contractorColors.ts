// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

/**
 * Per-contractor color palette for the `deepdata-stations` map layer.
 *
 * Keys are the short codes parsed from ISA contractor dataset titles
 * (e.g. "NORIPMN12022 Env Template BIO" → "NORI"). The 16 codes below
 * cover ~99% of records observed in the live OBIS ISA node (2026-05).
 *
 * Color choices favour:
 *   - distinct hues so adjacent dots are visually separable
 *   - color-blind friendliness (avoiding red/green-only contrasts)
 *   - alignment with the contractor's sponsor-state when intuitive
 *     (e.g. UKSRL = British blue, IFREMER = French navy, COMRA = red)
 *
 * Returns RGBA tuples for deck.gl `getFillColor`.
 */
export type RGBA = [number, number, number, number];

export const CONTRACTOR_COLORS: Record<string, RGBA> = {
  // TMC / Pacific island sponsors
  NORI:    [244, 114, 182, 230],   // pink     — Nauru-sponsored
  TOML:    [217,  70, 239, 230],   // magenta  — Tonga-sponsored
  // European / industrial geo agencies
  BGR:     [251, 191,  36, 230],   // amber    — Germany (Bundesanstalt für Geowissenschaften)
  IFREMER: [ 96, 165, 250, 230],   // blue     — France
  UKSRL:   [ 14, 165, 233, 230],   // sky      — UK Seabed Resources
  // Asia-Pacific
  COMRA:   [239,  68,  68, 230],   // red      — China Ocean Mineral Resources
  KOREA:   [ 56, 189, 248, 230],   // cyan     — Korea
  JOGMEC:  [167, 139, 250, 230],   // violet   — Japan
  CMM:     [192, 132, 252, 230],   // purple   — Cook Islands Marine Mining
  // Other contractors
  GSR:     [ 52, 211, 153, 230],   // emerald  — Belgium
  OMS:     [ 45, 212, 191, 230],   // teal     — Singapore
  IOM:     [251, 113, 133, 230],   // rose     — Interoceanmetal Joint Org (CZ/PL/RU/SK/BG/CU)
  YUZ:     [248, 113, 113, 230],   // light red — Yuzhmorgeologiya (Russia)
  YUZH:    [220,  38,  38, 230],   // dark red — Yuzhmorgeologiya variant
  RUSMNR:  [185,  28,  28, 230],   // crimson — Russia Ministry of Natural Resources (CRFC contracts)
  DORD:    [163, 230,  53, 230],   // lime     — Deep Ocean Resources Development
  COMA:    [180, 180, 180, 230],   // grey     — likely COMRA typo, low volume
};

/** Default color for unknown / unparsed contractor codes. */
export const FALLBACK_CONTRACTOR_COLOR: RGBA = [148, 163, 184, 200]; // slate-400

/** Sentinel key used in the contractor-filter Set for stations whose code
 * couldn't be parsed from the DwC dataset title. Empty string keeps it
 * visually distinct from real contractor codes. */
export const UNPARSED_CONTRACTOR_KEY = "";

export function colorForContractor(code: string | null | undefined): RGBA {
  if (!code) return FALLBACK_CONTRACTOR_COLOR;
  return CONTRACTOR_COLORS[code.toUpperCase()] ?? FALLBACK_CONTRACTOR_COLOR;
}

/** Stable list for the per-contractor toggle UI. */
export const CONTRACTOR_CODES: readonly string[] = Object.keys(CONTRACTOR_COLORS);
