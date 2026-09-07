// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// Thin re-export: the MOSAIC hex-grid decade filter logic moved to
// hexDecadeFilter.ts once MEMENTO and GEOTRACES needed the same rule.
// Names kept identical — MOSAIC's tests import them from this path.

export type { HexDecadeProps as MosaicHexProps } from "./hexDecadeFilter";
export { hexPassesDecadeFilter, hexFilteredCount, hexVisibleCount } from "./hexDecadeFilter";
