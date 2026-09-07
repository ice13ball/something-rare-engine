// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useMapStore } from "../../../../store/mapStore";
import type { LayerId } from "../../../../types/layers";

/**
 * Shared toggle for "field layer" rows (WOA, Ocean Carbon, CO2, Oxygen,
 * Arctic Sediment Carbon, Seabed Substrate): expands the filter panel the
 * first time a layer is activated, and collapses it if the layer is
 * toggled back off while its panel is open.
 */
export function useFieldLayerToggle(
  toggle: (id: LayerId) => void,
  expandedFilter: LayerId | null,
  setExpandedFilter: (f: LayerId | null) => void,
) {
  const { activeLayers } = useMapStore();

  return (id: LayerId) => {
    const wasActive = activeLayers.has(id);
    toggle(id);
    if (!wasActive) setExpandedFilter(id);
    else if (expandedFilter === id) setExpandedFilter(null);
  };
}
