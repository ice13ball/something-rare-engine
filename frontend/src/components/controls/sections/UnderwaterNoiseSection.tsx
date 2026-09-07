// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { useMapStore } from "../../../store/mapStore";
import type { LayerId } from "../../../types/layers";
import { analytics } from "../../../utils/analytics";
import {
  NOISE_RISK_FILTER_DEFS,
  AIS_SHIP_CLASS_DEFS,
} from "../filterDefs";
import {
  LayerRow, SubGroup, CheckboxFilter,
} from "../rows";

interface Props {
  expandedFilter: LayerId | null;
  toggleExpand: (id: LayerId) => void;
  toggle: (id: LayerId) => void;
  flyToLayer: ((id: LayerId) => void) | null;
}

export function UnderwaterNoiseSection({
  expandedFilter, toggleExpand, toggle, flyToLayer,
}: Props) {
  const {
    activeLayers,
    noiseRiskFilters, toggleNoiseRiskFilter,
    aisShipTypeFilters, toggleAisShipTypeFilter,
    aisFlagFilters,
  } = useMapStore();

  const { t } = useTranslation(["panels", "common"]);

  return (
    <SubGroup label={t("controls.subgroups.underwaterNoise")} storageKey="sea_vessels">
      <LayerRow
        id="vessel-events"
        label={t("layers.vesselEvents.toggle", { defaultValue: "Dark Vessels" })}
        color="#f59e0b"
        active={activeLayers.has("vessel-events")}
        onToggle={() => toggle("vessel-events")}
        onLocate={() => flyToLayer?.("vessel-events")}
      />
      <LayerRow
        id="ais-live"
        label={t("layers.aisLive.toggle", { defaultValue: "Live Vessels (AIS)" })}
        color="#22d3ee"
        active={activeLayers.has("ais-live")}
        onToggle={() => toggle("ais-live")}
        onLocate={() => flyToLayer?.("ais-live")}
        filterActive={aisShipTypeFilters.size > 0 || aisFlagFilters.size > 0}
        expanded={expandedFilter === "ais-live"}
        onExpandToggle={() => toggleExpand("ais-live")}
        filterContent={
          <CheckboxFilter
            header={t("filters.aisLive.shipClassHeading", { defaultValue: "Ship class" })}
            defs={AIS_SHIP_CLASS_DEFS}
            activeSet={aisShipTypeFilters}
            onToggle={toggleAisShipTypeFilter}
            clearLabel={t("filters.aisLive.clearLabel", { defaultValue: "Reset filters" })}
          />
        }
      />
      <LayerRow
        id="noise-risk" label={t("layers.noiseRisk.toggle")} color="#ff6b00"
        active={activeLayers.has("noise-risk")}
        onToggle={() => toggle("noise-risk")}
        onLocate={() => flyToLayer?.("noise-risk")}
        filterActive={noiseRiskFilters.size > 0}
        expanded={expandedFilter === "noise-risk"}
        onExpandToggle={() => toggleExpand("noise-risk")}
        filterContent={
          <CheckboxFilter
            header={t("filters.noiseRisk.riskLevelHeading")}
            defs={NOISE_RISK_FILTER_DEFS.map(d => ({ ...d, label: t(`filters.noiseRisk.levels.${d.key}` as any) }))}
            activeSet={noiseRiskFilters}
            onToggle={(level) => { toggleNoiseRiskFilter(level); analytics.trackEvent("toggle_noise_filter", { risk_level: level, active: !noiseRiskFilters.has(level) ? 1 : 0 }); }}
            clearLabel={t("filters.noiseRisk.clearLabel")}
          />
        }
      />
    </SubGroup>
  );
}
