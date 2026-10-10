// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { create } from "zustand";

/**
 * The position `[lon, lat]` of the WOD cast the open panel shows: written by `WodCastPanel` from its `/cast`
 * response (a dot of several casts shows the one chosen from the list), drawn by Map3D as the
 * `wod-selected-cast` ring. Kept out of `mapStore` on purpose, like `socatSelection`: derived from a panel
 * fetch, never part of a share link, filter registry or display registry.
 */
type WodSelection = {
  focus: [number, number] | null;
  setFocus: (focus: [number, number] | null) => void;
};

export const useWodSelection = create<WodSelection>((set) => ({
  focus: null,
  setFocus: (focus) => set({ focus }),
}));
