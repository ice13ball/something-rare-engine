// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { useMapStore } from "../../../store/mapStore";
import type { LayerId } from "../../../types/layers";
import { analytics } from "../../../utils/analytics";
import { IUCN_FILTER_DEFS, CHESS_HABITAT_DEFS, CHESS_PHYLUM_DEFS } from "../filterDefs";
import {
  LayerRow, SubGroup, CheckboxFilter, FilterResetLink,
} from "../rows";

interface Props {
  expandedFilter: LayerId | null;
  toggleExpand: (id: LayerId) => void;
  toggle: (id: LayerId) => void;
  flyToLayer: ((id: LayerId) => void) | null;
}

export function LifeGeologySection({ expandedFilter, toggleExpand, toggle, flyToLayer }: Props) {
  const {
    activeLayers,
    iucnFilters, toggleIucnFilter,
    ventStatusFilters, toggleVentStatus,
    chessHabitatFilters, toggleChessHabitatFilter,
    chessPhylumFilters, toggleChessPhylumFilter,
  } = useMapStore();

  const { t } = useTranslation(["panels", "common"]);

  return (
    <SubGroup label={t("controls.subgroups.lifeGeology")} storageKey="sea_life" defaultExpanded>
      <LayerRow
        id="biodiversity-hotspots" label={t("layers.biodiversityHotspots.toggle")} color="#3ce664"
        active={activeLayers.has("biodiversity-hotspots")}
        onToggle={() => toggle("biodiversity-hotspots")}
        onLocate={() => flyToLayer?.("biodiversity-hotspots")}
        filterActive={iucnFilters.size > 0}
        expanded={expandedFilter === "biodiversity-hotspots"}
        onExpandToggle={() => toggleExpand("biodiversity-hotspots")}
        filterContent={
          <CheckboxFilter
            header={t("filters.biodiversityHotspots.iucnStatusHeading")}
            defs={IUCN_FILTER_DEFS.map(d => ({ ...d, code: d.cat, label: t(`filters.biodiversityHotspots.iucn.${d.cat}` as any) }))}
            activeSet={iucnFilters}
            onToggle={(cat) => { toggleIucnFilter(cat); analytics.toggleIucnFilter(cat, !iucnFilters.has(cat)); }}
            clearLabel={t("filters.biodiversityHotspots.clearLabel")}
          />
        }
      />
      <LayerRow
        id="hydrothermal-vents" label={t("layers.hydrothermalVents.toggle")} color="#ff2323"
        active={activeLayers.has("hydrothermal-vents")}
        onToggle={() => toggle("hydrothermal-vents")}
        onLocate={() => flyToLayer?.("hydrothermal-vents")}
        filterActive={ventStatusFilters.size < 3}
        expanded={expandedFilter === "hydrothermal-vents"}
        onExpandToggle={() => toggleExpand("hydrothermal-vents")}
        filterContent={
          <>
            <div className="flex items-center justify-end pb-0.5 -mt-0.5">
              <FilterResetLink
                show={ventStatusFilters.size < 3}
                onReset={() => { for (const s of ["Active", "Inactive", "Extinct"]) if (!ventStatusFilters.has(s)) toggleVentStatus(s); }}
              />
            </div>
            {(["Active", "Inactive", "Extinct"] as const).map(s => (
              <label key={s} className="flex items-center gap-2 py-0.5 cursor-pointer">
                <input type="checkbox" checked={ventStatusFilters.has(s)} onChange={() => toggleVentStatus(s)} className="accent-orange-400 w-3 h-3" />
                <span className="text-white/75 text-[13px]">{t(`filters.hydrothermalVents.statusOptions.${s}` as any)}</span>
              </label>
            ))}
          </>
        }
      />
      <LayerRow
        id="chess"
        label={t("layers.chess.toggle")}
        color="#00c896"
        active={activeLayers.has("chess")}
        onToggle={() => toggle("chess")}
        onLocate={() => flyToLayer?.("chess")}
        filterActive={chessHabitatFilters.size > 0 || chessPhylumFilters.size > 0}
        expanded={expandedFilter === "chess"}
        onExpandToggle={() => toggleExpand("chess")}
        filterContent={
          <>
            <CheckboxFilter
              header={t("filters.chess.habitatTypeHeading")}
              defs={CHESS_HABITAT_DEFS.map(d => ({ ...d, label: t(`filters.chess.habitats.${d.key}` as any) }))}
              activeSet={chessHabitatFilters}
              onToggle={toggleChessHabitatFilter}
              clearLabel={t("filters.chess.clearHabitatLabel")}
            />
            <CheckboxFilter
              header={t("filters.chess.phylumHeading")}
              defs={CHESS_PHYLUM_DEFS}
              activeSet={chessPhylumFilters}
              onToggle={toggleChessPhylumFilter}
              clearLabel={t("filters.chess.clearPhylumLabel")}
            />
          </>
        }
      />
      <LayerRow
        id="seamounts"
        label={t("layers.seamounts.toggle")}
        color="#7eb8f7"
        active={activeLayers.has("seamounts")}
        onToggle={() => toggle("seamounts")}
        onLocate={() => flyToLayer?.("seamounts")}
      />
      <LayerRow
        id="tectonic-plates"
        label={t("layers.tectonicPlates.toggle")}
        color="#c9956e"
        active={activeLayers.has("tectonic-plates")}
        onToggle={() => toggle("tectonic-plates")}
        onLocate={() => flyToLayer?.("tectonic-plates")}
      />
      <LayerRow
        id="bathymetry"
        label={t("layers.bathymetry.toggle")}
        color="#3b82a6"
        active={activeLayers.has("bathymetry")}
        onToggle={() => toggle("bathymetry")}
      />
    </SubGroup>
  );
}
