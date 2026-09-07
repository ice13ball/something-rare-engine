// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { useMapStore } from "../../../../store/mapStore";
import type { LayerId } from "../../../../types/layers";
import { WOD_DECADES, wodDecadeHex } from "../../../../utils/wodDecades";
import { LayerRow, FilterResetLink } from "../../rows";

interface Props {
  expandedFilter: LayerId | null;
  toggleExpand: (id: LayerId) => void;
  toggle: (id: LayerId) => void;
  flyToLayer: ((id: LayerId) => void) | null;
}

export function WodOxygenRow({ expandedFilter, toggleExpand, toggle, flyToLayer }: Props) {
  const {
    activeLayers,
    wodDecadeFilters, toggleWodDecadeFilter,
  } = useMapStore();

  const { t } = useTranslation(["panels", "common"]);

  return (
              <LayerRow
                id="wod-oxygen"
                label={t("layers.wodOxygen.toggle")}
                color="#0891b2"
                active={activeLayers.has("wod-oxygen")}
                onToggle={() => toggle("wod-oxygen")}
                onLocate={() => flyToLayer?.("wod-oxygen")}
                filterActive={wodDecadeFilters.size > 0}
                expanded={expandedFilter === "wod-oxygen"}
                onExpandToggle={() => toggleExpand("wod-oxygen")}
                filterContent={
                  <div className="flex flex-col gap-2">
                    <div className="flex items-center justify-between">
                      <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">Decade</span>
                      {wodDecadeFilters.size > 0 && (
                        <FilterResetLink
                          show
                          onReset={() => wodDecadeFilters.forEach(toggleWodDecadeFilter)}
                        />
                      )}
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {WOD_DECADES.map((d) => {
                        const decade = String(d);
                        const color = wodDecadeHex(d);
                        const active = wodDecadeFilters.size === 0 || wodDecadeFilters.has(decade);
                        return (
                          <button
                            key={decade}
                            onClick={() => toggleWodDecadeFilter(decade)}
                            className={`px-2 py-0.5 rounded text-[11px] font-mono border transition-colors ${
                              active
                                ? "border-transparent text-white"
                                : "border-white/20 text-white/65 bg-white/5"
                            }`}
                            style={active ? { backgroundColor: color, borderColor: color } : {}}
                          >
                            {decade}s
                          </button>
                        );
                      })}
                    </div>
                    <div className="flex flex-wrap gap-x-2 gap-y-0.5 mt-1">
                      {WOD_DECADES.map((d) => (
                        <span key={d} className="flex items-center gap-1 text-[10px] font-mono text-white/70">
                          <span className="inline-block w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: wodDecadeHex(d) }} />
                          {d}s
                        </span>
                      ))}
                    </div>
                  </div>
                }
              />
  );
}
