// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { useMapStore } from "../../../../store/mapStore";
import type { LayerId } from "../../../../types/layers";
import { LayerRow, FilterResetLink } from "../../rows";

interface Props {
  expandedFilter: LayerId | null;
  toggleExpand: (id: LayerId) => void;
  toggle: (id: LayerId) => void;
  flyToLayer: ((id: LayerId) => void) | null;
}

export function ArcticRiversRow({ expandedFilter, toggleExpand, toggle, flyToLayer }: Props) {
  const {
    activeLayers,
    arcticRiverSourceFilters, toggleArcticRiverSourceFilter,
  } = useMapStore();

  const { t } = useTranslation(["panels", "common"]);

  return (
              <LayerRow
                id="arctic-rivers"
                label={t("layers.arcticRivers.toggle")}
                color="#38bdf8"
                active={activeLayers.has("arctic-rivers")}
                onToggle={() => toggle("arctic-rivers")}
                onLocate={() => flyToLayer?.("arctic-rivers")}
                filterActive={arcticRiverSourceFilters.size > 0}
                expanded={expandedFilter === "arctic-rivers"}
                onExpandToggle={() => toggleExpand("arctic-rivers")}
                filterContent={
                  <>
                    <div className="text-white/65 text-[13px] mb-0.5 flex items-center justify-between">
                      <span>Data source</span>
                      <FilterResetLink
                        show={arcticRiverSourceFilters.size > 0}
                        onReset={() => arcticRiverSourceFilters.forEach(toggleArcticRiverSourceFilter)}
                      />
                    </div>
                    {[
                      { key: "arcticgro",    label: "ArcticGRO (6 rivers)", color: "#38bdf8" },
                      { key: "pangaea_caa",  label: "Canadian Archipelago",  color: "#fbbf24" },
                    ].map(({ key, label, color }) => {
                      const disabled = arcticRiverSourceFilters.size > 0 && !arcticRiverSourceFilters.has(key);
                      return (
                        <button
                          key={key}
                          onClick={() => toggleArcticRiverSourceFilter(key)}
                          aria-label={`Toggle ${label}`}
                          aria-pressed={!disabled}
                          className={`flex items-center gap-1.5 w-full text-left text-[13px] py-0.5 transition-opacity ${disabled ? "opacity-60" : "opacity-100"}`}
                        >
                          <span
                            className="w-2 h-2 rounded-full flex-shrink-0 border"
                            style={{ backgroundColor: disabled ? "transparent" : color, borderColor: color }}
                          />
                          <span className={disabled ? "text-white/70" : "text-white"}>{label}</span>
                        </button>
                      );
                    })}
                  </>
                }
              />
  );
}
