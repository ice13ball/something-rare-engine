// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { create } from "zustand";

/**
 * The cruise segment of the SOCAT observation the open panel shows: written by `SocatObsPanel` from its `/obs`
 * response, drawn by Map3D as the `socat-selected-segment` PathLayer. Kept out of `mapStore` on purpose: it is
 * derived from a panel fetch, never part of a share link, filter registry or display registry.
 * A segment never crosses the antimeridian by construction (the importer cuts it), so one plain path suffices.
 */
type SocatSelection = {
  segment: [number, number][] | null;
  /** The selected observation itself, drawn as a ring on top of the segment. */
  point: [number, number] | null;
  setSelection: (segment: [number, number][] | null, point: [number, number] | null) => void;
};

export const useSocatSelection = create<SocatSelection>((set) => ({
  segment: null,
  point: null,
  setSelection: (segment, point) => set({ segment, point }),
}));
