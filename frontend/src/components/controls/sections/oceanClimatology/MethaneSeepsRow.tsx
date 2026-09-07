// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { useMapStore } from "../../../../store/mapStore";
import type { LayerId } from "../../../../types/layers";
import { SEEP_TYPES } from "../../../../utils/seepTypes";
import { LayerRow, FilterResetLink } from "../../rows";

interface Props {
  expandedFilter: LayerId | null;
  toggleExpand: (id: LayerId) => void;
  toggle: (id: LayerId) => void;
  flyToLayer: ((id: LayerId) => void) | null;
}

export function MethaneSeepsRow({ expandedFilter, toggleExpand, toggle, flyToLayer }: Props) {
  const {
    activeLayers,
    methaneSeepsFeatureTypeFilters, toggleMethaneSeepsFeatureTypeFilter,
  } = useMapStore();

  const { t } = useTranslation(["panels", "common"]);

  return (
              <LayerRow
                id="methane-seeps"
                label={t("layers.methaneSeeps.toggle" as any)}
                color="#ef4444"
                active={activeLayers.has("methane-seeps")}
                onToggle={() => toggle("methane-seeps")}
                onLocate={() => flyToLayer?.("methane-seeps")}
                filterActive={methaneSeepsFeatureTypeFilters.size > 0}
                expanded={expandedFilter === "methane-seeps"}
                onExpandToggle={() => toggleExpand("methane-seeps")}
                filterContent={
                  <>
                    <div className="text-white/65 text-[13px] mb-0.5 flex items-center justify-between">
                      <span>{t("controls.featureType", "Feature type")}</span>
                      <FilterResetLink
                        show={methaneSeepsFeatureTypeFilters.size > 0}
                        onReset={() => methaneSeepsFeatureTypeFilters.forEach(toggleMethaneSeepsFeatureTypeFilter)}
                      />
                    </div>
                    {SEEP_TYPES.map(({ key, label, hex }) => {
                      const disabled = methaneSeepsFeatureTypeFilters.size > 0 && !methaneSeepsFeatureTypeFilters.has(key);
                      return (
                        <button
                          key={key}
                          onClick={() => toggleMethaneSeepsFeatureTypeFilter(key)}
                          aria-label={`Toggle ${label}`}
                          aria-pressed={!disabled}
                          className={`flex items-center gap-1.5 w-full text-left text-[13px] py-0.5 transition-opacity ${disabled ? "opacity-60" : "opacity-100"}`}
                        >
                          <span
                            className="w-2 h-2 rounded-full flex-shrink-0 border"
                            style={{ backgroundColor: disabled ? "transparent" : hex, borderColor: hex }}
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
