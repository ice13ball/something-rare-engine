// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// Decision logic for hex-grid decade filters, shared by every layer that
// renders a density hex grid with a per-decade histogram (MOSAIC, MEMENTO,
// GEOTRACES). Kept separate from Map3D.tsx so the "does this hex survive the
// filter" rule is testable without touching deck.gl.

export interface HexDecadeProps {
  count?: number | null;
  by_decade?: Record<string, number> | null;
  n_undated?: number | null;
}

/**
 * A hex survives if any of its decades is selected, or — if "undated" is
 * selected — it holds at least one point with no year at all. An empty
 * selection means "no filter", which is not the same as "nothing selected".
 */
export function hexPassesDecadeFilter(p: HexDecadeProps, selected: Set<string>): boolean {
  if (selected.size === 0) return true;
  const hist = p.by_decade ?? {};
  if (Object.keys(hist).some((d) => selected.has(d))) return true;
  return selected.has("undated") && (p.n_undated ?? 0) > 0;
}

/** How many points remain after filtering — drives the colour ramp, so a hex
 *  shaded for fifty points does not stay dark when only two survive. */
export function hexFilteredCount(p: HexDecadeProps, selected: Set<string>): number {
  if (selected.size === 0) return p.count ?? 0;
  const hist = p.by_decade ?? {};
  const fromDecades = Object.entries(hist)
    .reduce((s, [d, n]) => s + (selected.has(d) ? n : 0), 0);
  return fromDecades + (selected.has("undated") ? (p.n_undated ?? 0) : 0);
}

export function hexVisibleCount(
  feats: Array<{ properties: HexDecadeProps }>,
  selected: Set<string>
): number {
  return feats.filter((f) => hexPassesDecadeFilter(f.properties, selected)).length;
}
