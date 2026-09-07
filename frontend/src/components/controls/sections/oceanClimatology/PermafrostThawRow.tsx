// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { useMapStore } from "../../../../store/mapStore";
import type { LayerId } from "../../../../types/layers";
import { THAW_CATEGORIES } from "../../../../utils/thawTypes";
import { LayerRow, FilterResetLink } from "../../rows";

interface Props {
  expandedFilter: LayerId | null;
  toggleExpand: (id: LayerId) => void;
  toggle: (id: LayerId) => void;
  flyToLayer: ((id: LayerId) => void) | null;
}

export function PermafrostThawRow({ expandedFilter, toggleExpand, toggle, flyToLayer }: Props) {
  const {
    activeLayers,
    thawTypeFilters, toggleThawTypeFilter,
    thawCategoryFilters, toggleThawCategoryFilter,
    permafrostSourceFilters, togglePermafrostSourceFilter,
  } = useMapStore();

  const { t } = useTranslation(["panels", "common"]);

  return (
              <LayerRow
                id="permafrost-thaw"
                label={t("layers.permafrostThaw.toggle")}
                color="#38bdf8"
                active={activeLayers.has("permafrost-thaw")}
                onToggle={() => toggle("permafrost-thaw")}
                onLocate={() => flyToLayer?.("permafrost-thaw")}
                filterActive={thawTypeFilters.size > 0 || thawCategoryFilters.size > 0 || permafrostSourceFilters.size > 0}
                expanded={expandedFilter === "permafrost-thaw"}
                onExpandToggle={() => toggleExpand("permafrost-thaw")}
                filterContent={
                  <>
                    <div className="text-white/65 text-[13px] mb-0.5 flex items-center justify-between">
                      <span>{t("controls.source", "Source")}</span>
                      <FilterResetLink show={permafrostSourceFilters.size > 0}
                        onReset={() => permafrostSourceFilters.forEach(togglePermafrostSourceFilter)} />
                    </div>
                    {[["alaska_webb","Alaska Thaw DB"],["arts_panarctic","Pan-Arctic Slumps"]].map(([key,label]) => {
                      const disabled = permafrostSourceFilters.size > 0 && !permafrostSourceFilters.has(key);
                      return (
                        <button key={key} onClick={() => togglePermafrostSourceFilter(key)}
                          aria-label={`Toggle ${label}`} aria-pressed={!disabled}
                          className={`flex items-center gap-1.5 w-full text-left text-[13px] py-0.5 transition-opacity ${disabled ? "opacity-60" : "opacity-100"}`}>
                          <span className={disabled ? "text-white/70" : "text-white"}>{label}</span>
                        </button>
                      );
                    })}
                    <div className="text-white/65 text-[13px] mt-2 mb-0.5 flex items-center justify-between">
                      <span>{t("controls.thawType", "Thaw type")}</span>
                      <FilterResetLink
                        show={thawTypeFilters.size > 0}
                        onReset={() => thawTypeFilters.forEach(toggleThawTypeFilter)}
                      />
                    </div>
                    {[["abrupt", "Abrupt"], ["non-abrupt", "Non-abrupt"]].map(([key, label]) => {
                      const disabled = thawTypeFilters.size > 0 && !thawTypeFilters.has(key);
                      return (
                        <button key={key} onClick={() => toggleThawTypeFilter(key)}
                          aria-label={`Toggle ${label}`} aria-pressed={!disabled}
                          className={`flex items-center gap-1.5 w-full text-left text-[13px] py-0.5 transition-opacity ${disabled ? "opacity-60" : "opacity-100"}`}>
                          <span className={disabled ? "text-white/70" : "text-white"}>{label}</span>
                        </button>
                      );
                    })}
                    <div className="text-white/65 text-[13px] mt-2 mb-0.5 flex items-center justify-between">
                      <span>{t("controls.featureCategory", "Feature category")}</span>
                      <FilterResetLink
                        show={thawCategoryFilters.size > 0}
                        onReset={() => thawCategoryFilters.forEach(toggleThawCategoryFilter)}
                      />
                    </div>
                    {THAW_CATEGORIES.map(({ key, label, hex }) => {
                      const disabled = thawCategoryFilters.size > 0 && !thawCategoryFilters.has(key);
                      return (
                        <button key={key} onClick={() => toggleThawCategoryFilter(key)}
                          aria-label={`Toggle ${label}`} aria-pressed={!disabled}
                          className={`flex items-center gap-1.5 w-full text-left text-[13px] py-0.5 transition-opacity ${disabled ? "opacity-60" : "opacity-100"}`}>
                          <span className="w-2 h-2 rounded-full flex-shrink-0 border"
                            style={{ backgroundColor: disabled ? "transparent" : hex, borderColor: hex }} />
                          <span className={disabled ? "text-white/70" : "text-white"}>{label}</span>
                        </button>
                      );
                    })}
                  </>
                }
              />
  );
}
