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

export function HazardsMonitoringSection({
  expandedFilter, toggleExpand, toggle, flyToLayer,
}: Props) {
  const {
    activeLayers,
    fireConfidenceFilters, toggleFireConfidenceFilter,
    firesNearMiningOnly, toggleFiresNearMiningOnly,
  } = useMapStore();

  const { t } = useTranslation(["panels", "common"]);

  return (
    <SubGroup label={t("controls.subgroups.hazardsMonitoring")} storageKey="land_hazards" defaultExpanded>
    {/* ⛔ WITHDRAWN 2026-09-23: the hazard-rating and status filter chips that
        used to live here were built on `hazard_raw`/`status`, both Global
        Tailings Portal-derived fields. The backend no longer sends either
        field on any row (domains/land/common.py TAILINGS_SERVED_WHERE /
        TAILINGS_PORTAL_COLUMNS), so a facet built on them would filter every
        dam to nothing. No filterContent for tailings until/unless GRID-Arendal
        grants permission. */}
    <LayerRow
      id="tailings"
      label={t("layers.tailings.toggle")}
      color="#dc2626"
      active={activeLayers.has("tailings")}
      onToggle={() => toggle("tailings")}
      onLocate={() => flyToLayer?.("tailings")}
    />
    <LayerRow
      id="fires"
      label={t("layers.fires.toggle")}
      color="#ff6b00"
      active={activeLayers.has("fires")}
      onToggle={() => toggle("fires")}
      onLocate={() => flyToLayer?.("fires")}
      filterActive={fireConfidenceFilters.size > 0 || firesNearMiningOnly}
      expanded={expandedFilter === "fires"}
      onExpandToggle={() => toggleExpand("fires")}
      filterContent={
        <>
          <div className="flex items-center justify-end -mt-0.5">
            <FilterResetLink
              show={fireConfidenceFilters.size > 0 || firesNearMiningOnly}
              onReset={() => {
                fireConfidenceFilters.forEach(toggleFireConfidenceFilter);
                if (firesNearMiningOnly) toggleFiresNearMiningOnly();
              }}
            />
          </div>
          <label className="flex items-center gap-2 py-0.5 pb-1.5 mb-0.5 border-b border-white/10 cursor-pointer">
            <input type="checkbox" checked={firesNearMiningOnly} onChange={toggleFiresNearMiningOnly} className="accent-orange-400 w-3 h-3" />
            <span className="text-white/85 text-[13px]">{t("filters.fires.nearMiningOnly")}</span>
          </label>
          {(["High", "Nominal", "Low"] as const).map(c => (
            <label key={c} className="flex items-center gap-2 py-0.5 cursor-pointer">
              <input type="checkbox" checked={fireConfidenceFilters.has(c)} onChange={() => toggleFireConfidenceFilter(c)} className="accent-orange-400 w-3 h-3" />
              <span className="text-white/75 text-[13px]">{t(`filters.fires.confidenceLevels.${c}` as any)}</span>
            </label>
          ))}
        </>
      }
    />
    <LayerRow
      id="air-quality"
      label={t("layers.airQuality.toggle")}
      color="#7c9bb5"
      active={activeLayers.has("air-quality")}
      onToggle={() => toggle("air-quality")}
      onLocate={() => flyToLayer?.("air-quality")}
    />
    <LayerRow
      id="landslides"
      label={t("layers.landslides.toggle")}
      color="#92400e"
      active={activeLayers.has("landslides")}
      onToggle={() => toggle("landslides")}
      onLocate={() => flyToLayer?.("landslides")}
    />
    </SubGroup>
  );
}
