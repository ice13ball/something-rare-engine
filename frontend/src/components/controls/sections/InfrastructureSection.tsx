// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { useMapStore } from "../../../store/mapStore";
import type { LayerId } from "../../../types/layers";
import {
  LayerRow, SubGroup, FilterResetLink,
} from "../rows";

interface Props {
  expandedFilter: LayerId | null;
  toggleExpand: (id: LayerId) => void;
  toggle: (id: LayerId) => void;
  flyToLayer: ((id: LayerId) => void) | null;
}

export function InfrastructureSection({
  expandedFilter, toggleExpand, toggle, flyToLayer,
}: Props) {
  const {
    activeLayers,
    cableSourceFilters, toggleCableSourceFilter,
  } = useMapStore();

  const { t } = useTranslation(["panels", "common"]);

  return (
    <SubGroup label={t("controls.subgroups.infrastructure")} storageKey="sea_infra">
      <LayerRow
        id="submarine-cables"
        label={t("layers.submarineCables.toggle")}
        color="#fbbf24"
        active={activeLayers.has("submarine-cables")}
        onToggle={() => toggle("submarine-cables")}
        onLocate={() => flyToLayer?.("submarine-cables")}
        filterActive={cableSourceFilters.size > 0}
        expanded={expandedFilter === "submarine-cables"}
        onExpandToggle={() => toggleExpand("submarine-cables")}
        filterContent={
          <>
            <div className="text-white/65 text-[13px] mb-0.5 flex items-center justify-between">
              <span>{t("filters.submarineCables.dataSourcesHeading")}</span>
              <FilterResetLink
                show={cableSourceFilters.size > 0}
                onReset={() => cableSourceFilters.forEach(toggleCableSourceFilter)}
              />
            </div>
            {[
              { key: "emodnet", label: t("filters.submarineCables.sources.emodnet"), color: "#fbbf24" },
              { key: "noaa",    label: t("filters.submarineCables.sources.noaa"),    color: "#fbbf24" },
              { key: "nz",      label: t("filters.submarineCables.sources.nz"),      color: "#fbbf24" },
              { key: "au",      label: t("filters.submarineCables.sources.au"),      color: "#fbbf24" },
              { key: "onc",     label: t("filters.submarineCables.sources.onc"),     color: "#22d3ee" },
              { key: "ooi",     label: t("filters.submarineCables.sources.ooi"),     color: "#e879f9" },
            ].map(({ key, label, color }) => {
              const disabled = cableSourceFilters.size > 0 && !cableSourceFilters.has(key);
              return (
                <button
                  key={key}
                  onClick={() => toggleCableSourceFilter(key)}
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
            <div className="text-white/60 text-[11px] mt-1 leading-snug">
              {t("filters.submarineCables.sourcesNote")}
            </div>
          </>
        }
      />
      <LayerRow
        id="ports"
        label={t("layers.ports.toggle")}
        color="#60a5fa"
        active={activeLayers.has("ports")}
        onToggle={() => toggle("ports")}
        onLocate={() => flyToLayer?.("ports")}
      />
    </SubGroup>
  );
}
