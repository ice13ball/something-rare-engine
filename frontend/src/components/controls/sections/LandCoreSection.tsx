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

export function LandCoreSection({
  toggle, flyToLayer,
}: Props) {
  const {
    activeLayers,
  } = useMapStore();

  const { t } = useTranslation(["panels", "common"]);

  return (
    <SubGroup label={t("controls.subgroups.landCore")} storageKey="land_core" defaultExpanded>
      <LayerRow
        id="mining-footprints"
        label={t("layers.miningFootprints.toggle")}
        color="#ef4444"
        active={activeLayers.has("mining-footprints")}
        onToggle={() => toggle("mining-footprints")}
        onLocate={() => flyToLayer?.("mining-footprints")}
      />
      <LayerRow
        id="forest-loss"
        label={t("layers.forestLoss.toggle")}
        color="#f59e0b"
        active={activeLayers.has("forest-loss")}
        onToggle={() => toggle("forest-loss")}
        onLocate={() => flyToLayer?.("forest-loss")}
      />
    </SubGroup>
  );
}
