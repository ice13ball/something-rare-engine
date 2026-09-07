// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { useMapStore } from "../../../store/mapStore";
import type { LayerId } from "../../../types/layers";
import {
  LayerRow, SubGroup,
} from "../rows";

interface Props {
  toggle: (id: LayerId) => void;
  flyToLayer: ((id: LayerId) => void) | null;
}

export function WaterCarbonSection({
  toggle, flyToLayer,
}: Props) {
  const {
    activeLayers,
  } = useMapStore();

  const { t } = useTranslation(["panels", "common"]);

  return (
    <SubGroup label={t("controls.subgroups.waterCarbon")} storageKey="land_water" defaultExpanded>
    <LayerRow
      id="surface-water"
      label={t("layers.surfaceWater.toggle")}
      color="#06b6d4"
      active={activeLayers.has("surface-water")}
      onToggle={() => toggle("surface-water")}
      onLocate={() => flyToLayer?.("surface-water")}
    />
    <LayerRow
      id="dams"
      label={t("layers.dams.toggle")}
      color="#5e8ab4"
      active={activeLayers.has("dams")}
      onToggle={() => toggle("dams")}
      onLocate={() => flyToLayer?.("dams")}
    />
    <LayerRow
      id="carbon-flux"
      label={t("layers.carbonFlux.toggle")}
      color="#065f46"
      active={activeLayers.has("carbon-flux")}
      onToggle={() => toggle("carbon-flux")}
      onLocate={() => flyToLayer?.("carbon-flux")}
    />
    <LayerRow
      id="soil-carbon"
      label={t("layers.soilCarbon.toggle")}
      color="#78350f"
      active={activeLayers.has("soil-carbon")}
      onToggle={() => toggle("soil-carbon")}
      onLocate={() => flyToLayer?.("soil-carbon")}
    />
    <LayerRow
      id="water-risk"
      label={t("layers.waterRisk.toggle")}
      color="#0ea5e9"
      active={activeLayers.has("water-risk")}
      onToggle={() => toggle("water-risk")}
      onLocate={() => flyToLayer?.("water-risk")}
    />
    </SubGroup>
  );
}
