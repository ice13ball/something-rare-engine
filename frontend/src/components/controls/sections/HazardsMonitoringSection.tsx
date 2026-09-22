// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { useMapStore } from "../../../store/mapStore";
import type { LayerId } from "../../../types/layers";
import { TAILINGS_RISK_FILTER_DEFS } from "../filterDefs";
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
    tailingsRiskFilters, toggleTailingsRiskFilter,
    tailingsStatusFilters, toggleTailingsStatusFilter,
    fireConfidenceFilters, toggleFireConfidenceFilter,
    firesNearMiningOnly, toggleFiresNearMiningOnly,
  } = useMapStore();

  const { t } = useTranslation(["panels", "common"]);

  return (
    <SubGroup label={t("controls.subgroups.hazardsMonitoring")} storageKey="land_hazards" defaultExpanded>
    <LayerRow
      id="tailings"
      label={t("layers.tailings.toggle")}
      color="#dc2626"
      active={activeLayers.has("tailings")}
      onToggle={() => toggle("tailings")}
      onLocate={() => flyToLayer?.("tailings")}
      filterActive={tailingsRiskFilters.size > 0 || tailingsStatusFilters.size > 0}
      expanded={expandedFilter === "tailings"}
      onExpandToggle={() => toggleExpand("tailings")}
      filterContent={
        <>
          <div className="flex items-center justify-between mb-1">
            <p className="text-white/70 text-[10px] uppercase tracking-wider">{t("filters.tailings.riskLevelHeading")}</p>
            <FilterResetLink
              show={tailingsRiskFilters.size > 0 || tailingsStatusFilters.size > 0}
              onReset={() => { tailingsRiskFilters.forEach(toggleTailingsRiskFilter); tailingsStatusFilters.forEach(toggleTailingsStatusFilter); }}
            />
          </div>
          {/* hazard_raw, verbatim from the source — the six most common values
              plus an "other" bucket. Colors are DISTINCT HUES (TAILINGS_RISK_FILTER_DEFS
              / colorStandards.TAILINGS_HAZARD), never a severity ramp — a
              red→green gradient would re-introduce by colour exactly the
              ordinal scoring the deleted risk_class field did by tier. A row
              with no rating is always shown and has no checkbox of its own. */}
          {TAILINGS_RISK_FILTER_DEFS.map(d => (
            <label key={d.key} className="flex items-center gap-2 py-0.5 cursor-pointer">
              <input
                type="checkbox"
                checked={tailingsRiskFilters.has(d.key)}
                onChange={() => toggleTailingsRiskFilter(d.key)}
                className="w-3 h-3"
                style={{ accentColor: d.color }}
              />
              <span className="inline-block w-2 h-2 rounded-full flex-shrink-0" style={{ background: d.color }} />
              <span className="text-white/75 text-[13px]">{t(`filters.tailings.riskLevels.${d.i18nKey}` as any)}</span>
            </label>
          ))}
          <p className="text-white/70 text-[10px] uppercase tracking-wider mt-2 mb-1">{t("filters.tailings.statusHeading")}</p>
          {(["Active", "Inactive", "Closed"] as const).map(s => (
            <label key={s} className="flex items-center gap-2 py-0.5 cursor-pointer">
              <input type="checkbox" checked={tailingsStatusFilters.has(s)} onChange={() => toggleTailingsStatusFilter(s)} className="accent-red-400 w-3 h-3" />
              <span className="text-white/75 text-[13px]">{t(`filters.tailings.statusOptions.${s}` as any)}</span>
            </label>
          ))}
        </>
      }
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
