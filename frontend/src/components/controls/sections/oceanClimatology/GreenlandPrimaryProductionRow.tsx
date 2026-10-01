// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { useMapStore } from "../../../../store/mapStore";
import type { LayerId } from "../../../../types/layers";
import { LayerRow } from "../../rows";

interface Props {
  toggle: (id: LayerId) => void;
  flyToLayer: ((id: LayerId) => void) | null;
}

export function GreenlandPrimaryProductionRow({ toggle, flyToLayer }: Props) {
  const activeLayers = useMapStore((s) => s.activeLayers);
  const { t } = useTranslation(["panels", "common"]);

  return (
              <LayerRow
                id="greenland-primary-production"
                label={t("layers.greenlandPrimaryProduction.toggle" as any)}
                color="#84cc16"
                active={activeLayers.has("greenland-primary-production")}
                onToggle={() => toggle("greenland-primary-production")}
                onLocate={() => flyToLayer?.("greenland-primary-production")}
              />
  );
}
